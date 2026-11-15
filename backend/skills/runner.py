"""Skill Runner: executes a registered repo tool, unmodified, and records the run in the ledger.

Each run gets a fresh working directory holding trader/config.json (the NSE tools read and
write under trader/ relative to cwd), so runs never see each other's files. No shell is
involved: argv goes straight to the interpreter.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.ledger.db import Ledger
from backend.skills.registry import ROOT, Registry, ToolSpec, registry, repo_sha

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_TEXT = 200_000
NSE_CONFIG_EXAMPLE = ROOT / "vendor/nse-trader-skill/nse-common/config.example.json"


class ArgRejected(ValueError):
    """An argument tried to reach outside the project or the run's own directory."""


def default_config() -> dict[str, Any]:
    cfg = json.loads(NSE_CONFIG_EXAMPLE.read_text())
    cfg["paper"] = True  # Saarthi never trades for real; the UI cannot change this
    return cfg


def parse_as_of(value: str | dt.datetime | None) -> dt.datetime | None:
    if value is None or isinstance(value, dt.datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"as_of must look like 'YYYY-MM-DD HH:MM', got {value!r}")


def _check_args(args: list[str]) -> None:
    root = ROOT.resolve()
    for a in args:
        if "\x00" in a:
            raise ArgRejected("NUL byte in argument")
        if a.startswith("/") or a.startswith("~"):
            p = Path(a).expanduser().resolve()
            if root not in p.parents and p != root:
                raise ArgRejected(f"path outside the project: {a}")
        if ".." in Path(a).parts:
            raise ArgRejected(f"parent-directory path: {a}")


def _hash_path(p: Path) -> str:
    h = hashlib.sha256()
    if p.is_file():
        h.update(p.read_bytes())
    else:
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(f.relative_to(p).as_posix().encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def input_hashes(args: list[str], cwd: Path) -> dict[str, str]:
    out = {}
    for a in args:
        if a.startswith("-") or len(a) > 4096:
            continue
        p = Path(a) if Path(a).is_absolute() else cwd / a
        if p.exists():
            try:
                out[a] = _hash_path(p)
            except OSError:
                out[a] = "unreadable"
    return out


def extract_json(stdout: str) -> Any:
    """Whole stdout as JSON, else the first JSON document that starts a line."""
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    offset = 0
    for line in stdout.splitlines(keepends=True):
        s = line.lstrip()
        if s[:1] in ("{", "["):
            try:
                obj, _ = dec.raw_decode(stdout, offset + len(line) - len(s))
                return obj
            except json.JSONDecodeError:
                pass
        offset += len(line)
    return None


def build_argv(reg: Registry, spec: ToolSpec, args: list[str], as_of: dt.datetime | None) -> list[str]:
    argv = [sys.executable, str(reg.script_path(spec)), *spec.command, *reg.expand(args)]
    if spec.json_flag and spec.json_flag not in argv:
        argv.append(spec.json_flag)
    if spec.no_write and "--no-write" not in argv:
        argv.append("--no-write")
    if as_of is not None:
        if spec.time_flag is None:
            raise ValueError(f"{spec.id} cannot run point-in-time (no time flag)")
        argv += spec.time_flag.render(as_of)
    return argv


async def run_tool(
    tool_id: str,
    args: list[str] | None = None,
    *,
    ledger: Ledger,
    as_of: str | dt.datetime | None = None,
    config: dict[str, Any] | None = None,
    purpose: str = "api",
    timeout: int | None = None,
    reg: Registry | None = None,
) -> dict[str, Any]:
    reg = reg or registry()
    spec = reg.tool(tool_id)
    args = list(args or [])
    _check_args(reg.expand(args))
    when = parse_as_of(as_of)
    argv = build_argv(reg, spec, args, when)

    work = Path(tempfile.mkdtemp(prefix="saarthi-run-"))
    try:
        (work / "trader").mkdir()
        (work / "trader" / "config.json").write_text(json.dumps(config or default_config(), indent=2))
        env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8",
               "PYTHONDONTWRITEBYTECODE": "1"}
        hashes = input_hashes(argv[2:], work)

        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=work, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout or spec.timeout)
            status = "ok" if proc.returncode == 0 else "tool_error"
            code = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            out_b, err_b = await proc.communicate()
            status, code = "timeout", -9
        ms = int((time.perf_counter() - t0) * 1000)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    stdout = out_b.decode("utf-8", "replace")
    stderr = err_b.decode("utf-8", "replace")
    parsed = extract_json(stdout) if spec.json_flag else None
    if status == "ok" and spec.json_flag and parsed is None:
        status = "bad_output"

    record = {
        "tool_id": spec.id,
        "repo": spec.repo,
        "repo_sha": repo_sha(spec.repo),
        "argv": [Path(argv[0]).name, *[_rel(a) for a in argv[1:]]],
        "as_of": when.strftime("%Y-%m-%d %H:%M") if when else None,
        "input_hashes": {_rel(k): v for k, v in hashes.items()},
        "exit_code": code,
        "status": status,
        "duration_ms": ms,
        "output_json": parsed,
        "output_text": stdout[:MAX_TEXT],
        "stderr": stderr[-8000:],
        "purpose": purpose,
    }
    record["id"] = ledger.record_run(record)
    return record


def _rel(a: str) -> str:
    """Store project paths relative to the repo root so runs replay on any machine."""
    try:
        return str(Path(a).resolve().relative_to(ROOT.resolve()))
    except (ValueError, OSError):
        return a


async def run_smoke(ledger: Ledger, reg: Registry | None = None,
                    tool_ids: list[str] | None = None) -> list[dict[str, Any]]:
    reg = reg or registry()
    ids = tool_ids or list(reg.tools)
    sem = asyncio.Semaphore(4)

    async def one(tid: str) -> dict[str, Any]:
        spec = reg.tool(tid)
        async with sem:
            return await run_tool(tid, spec.smoke, ledger=ledger, as_of=spec.smoke_as_of,
                                  purpose="smoke", reg=reg)

    return list(await asyncio.gather(*(one(t) for t in ids)))
