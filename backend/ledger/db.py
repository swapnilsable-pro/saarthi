"""Evidence ledger: SQLite, append-only for the audit tables.

tool_runs, decisions and evidence can never be updated or deleted (triggers enforce it);
corrections are new rows. paper_trades is mutable while a trade is open (Phase 3).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(os.environ.get("SAARTHI_DB", Path(__file__).resolve().parents[2] / "data" / "saarthi.db"))

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tool_runs (
  id            TEXT PRIMARY KEY,
  tool_id       TEXT NOT NULL,
  repo          TEXT NOT NULL,
  repo_sha      TEXT NOT NULL,
  argv          TEXT NOT NULL,          -- JSON list, exactly what was executed
  as_of         TEXT,                   -- IST moment the tool was told it was (point-in-time runs)
  input_hashes  TEXT NOT NULL,          -- JSON {path: sha256}
  exit_code     INTEGER NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('ok','tool_error','timeout','bad_output')),
  duration_ms   INTEGER NOT NULL,
  output_json   TEXT,                   -- parsed JSON, if the tool printed any
  output_text   TEXT,                   -- raw stdout (truncated)
  stderr        TEXT,
  purpose       TEXT,                   -- 'smoke' | 'api' | 'pipeline' | ...
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_tool_runs_tool ON tool_runs(tool_id, created_at);

CREATE TABLE IF NOT EXISTS job_runs (
  id            TEXT PRIMARY KEY,
  job           TEXT NOT NULL,            -- evening_scan | premarket_brief | ...
  mode          TEXT NOT NULL CHECK (mode IN ('live','demo')),
  session_day   TEXT NOT NULL,            -- the NSE session this job prepares for
  as_of         TEXT,                     -- IST moment the tools were told it was (demo/replay)
  status        TEXT NOT NULL CHECK (status IN ('ok','partial','failed')),
  steps         TEXT NOT NULL,            -- JSON {step_key: {tool_run_id, status, tool_id}}
  started_at    TEXT NOT NULL,
  duration_ms   INTEGER NOT NULL,
  trigger       TEXT NOT NULL,            -- 'manual' | 'schedule'
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_job_runs ON job_runs(job, mode, created_at);

CREATE TABLE IF NOT EXISTS decisions (
  id                TEXT PRIMARY KEY,
  session_day       TEXT NOT NULL,
  decided_at        TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  setup             TEXT NOT NULL,
  verdict           TEXT NOT NULL CHECK (verdict IN ('TAKE','WATCH','SKIP')),
  first_failed_gate TEXT,
  score             REAL,
  plan              TEXT,
  odds              TEXT,
  costs             TEXT,
  config_snapshot   TEXT,
  pipeline_version  TEXT,
  mode              TEXT,                 -- live | demo
  as_of             TEXT,                 -- IST moment the decision was made (replays: simulated)
  detail            TEXT,                 -- JSON: gates, variants, timing curve, narrative
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS evidence (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_id  TEXT NOT NULL REFERENCES decisions(id),
  step         TEXT NOT NULL,
  label        TEXT NOT NULL,
  passed       INTEGER,
  summary      TEXT,
  tool_run_id  TEXT REFERENCES tool_runs(id)
);

CREATE TABLE IF NOT EXISTS replay_sessions (
  id          TEXT PRIMARY KEY,
  data_mode   TEXT NOT NULL,
  day         TEXT NOT NULL,
  symbols     TEXT NOT NULL,              -- JSON list
  surprise    INTEGER NOT NULL DEFAULT 0, -- hide date and names until the close
  clock       TEXT NOT NULL,              -- simulated IST 'YYYY-MM-DD HH:MM'
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS paper_accounts (
  id          TEXT PRIMARY KEY,
  data_mode   TEXT NOT NULL CHECK (data_mode IN ('live','demo')),
  name        TEXT NOT NULL,
  capital     REAL NOT NULL,
  settings    TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS paper_trades (
  id              TEXT PRIMARY KEY,
  account_id      TEXT NOT NULL,
  decision_id     TEXT REFERENCES decisions(id),
  mode            TEXT NOT NULL CHECK (mode IN ('live','replay','batch','ghost')),
  symbol          TEXT NOT NULL,
  side            TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  product         TEXT NOT NULL CHECK (product IN ('MIS','CNC')),
  qty             INTEGER NOT NULL,
  fills           TEXT,
  exit_reason     TEXT,
  gross_pnl       REAL,
  costs           TEXT,
  net_pnl         REAL,
  r_multiple      REAL,
  mae_r           REAL,
  mfe_r           REAL,
  bars_held       INTEGER,
  followed_plan   INTEGER,
  ambiguous_bars  INTEGER,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

APPEND_ONLY = ("tool_runs", "job_runs", "decisions", "evidence")


def _triggers() -> str:
    out = []
    for t in APPEND_ONLY:
        for op in ("UPDATE", "DELETE"):
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;")
    return "\n".join(out)


class Ledger:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA + _triggers())
        self._migrate()

    def _migrate(self) -> None:
        """Additive column migrations for ledgers created by earlier phases."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(decisions)")}
        for col in ("mode", "as_of", "detail"):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE decisions ADD COLUMN {col} TEXT")
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(paper_trades)")}
        for col in self.PAPER_EXTRA:
            if col not in cols:
                self._conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} TEXT")
        self._conn.commit()

    # Columns paper trading added after Phase 0's schema (stored as TEXT; numbers are JSON-encoded).
    PAPER_EXTRA = ("data_mode", "session_day", "status", "order_spec", "result", "entry_price", "exit_price",
                   "entry_at", "exit_at", "updated_at", "reject_reason", "replay_id")
    PAPER_JSON = ("fills", "costs", "order_spec", "result")
    PAPER_NUM = ("gross_pnl", "net_pnl", "r_multiple", "mae_r", "mfe_r", "entry_price", "exit_price")

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- tool runs
    def record_run(self, run: dict[str, Any]) -> str:
        run_id = run.get("id") or uuid.uuid4().hex
        row = {
            "id": run_id,
            "tool_id": run["tool_id"],
            "repo": run["repo"],
            "repo_sha": run["repo_sha"],
            "argv": json.dumps(run["argv"]),
            "as_of": run.get("as_of"),
            "input_hashes": json.dumps(run.get("input_hashes", {})),
            "exit_code": run["exit_code"],
            "status": run["status"],
            "duration_ms": run["duration_ms"],
            "output_json": json.dumps(run["output_json"]) if run.get("output_json") is not None else None,
            "output_text": run.get("output_text"),
            "stderr": run.get("stderr"),
            "purpose": run.get("purpose"),
        }
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        with self._lock, self._conn:
            self._conn.execute(f"INSERT INTO tool_runs ({cols}) VALUES ({qs})", tuple(row.values()))
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM tool_runs WHERE id = ?", (run_id,)).fetchone()
        return _decode(r) if r else None

    def list_runs(self, tool_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = ("SELECT id, tool_id, repo, repo_sha, as_of, exit_code, status, duration_ms, purpose, "
             "created_at FROM tool_runs")
        params: tuple = ()
        if tool_id:
            q += " WHERE tool_id = ?"
            params = (tool_id,)
        q += " ORDER BY created_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, params + (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- job runs
    def record_job(self, job: dict[str, Any]) -> str:
        job_id = job.get("id") or uuid.uuid4().hex
        row = {
            "id": job_id, "job": job["job"], "mode": job["mode"], "session_day": job["session_day"],
            "as_of": job.get("as_of"), "status": job["status"], "steps": json.dumps(job["steps"]),
            "started_at": job["started_at"], "duration_ms": job["duration_ms"],
            "trigger": job.get("trigger", "manual"),
        }
        cols, qs = ", ".join(row), ", ".join("?" for _ in row)
        with self._lock, self._conn:
            self._conn.execute(f"INSERT INTO job_runs ({cols}) VALUES ({qs})", tuple(row.values()))
        return job_id

    def latest_job(self, job: str, mode: str, session_day: str | None = None) -> dict[str, Any] | None:
        q, params = "SELECT * FROM job_runs WHERE job = ? AND mode = ?", [job, mode]
        if session_day:
            q += " AND session_day = ?"
            params.append(session_day)
        with self._lock:
            # Without a day: the most recent SESSION prepared (replays may prepare older days later).
            r = self._conn.execute(q + " ORDER BY session_day DESC, created_at DESC LIMIT 1", params).fetchone()
        if not r:
            return None
        d = dict(r)
        d["steps"] = json.loads(d["steps"])
        return d

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["steps"] = json.loads(d["steps"])
            out.append(d)
        return out

    def has_job_for(self, job: str, mode: str, session_day: str) -> bool:
        with self._lock:
            r = self._conn.execute(
                "SELECT 1 FROM job_runs WHERE job=? AND mode=? AND session_day=? AND status!='failed' LIMIT 1",
                (job, mode, session_day)).fetchone()
        return r is not None

    # ---------------------------------------------------------------- decisions
    DECISION_JSON = ("plan", "odds", "costs", "config_snapshot", "detail")

    def record_decision(self, d: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        dec_id = d.get("id") or uuid.uuid4().hex
        row = {
            "id": dec_id, "session_day": d["session_day"], "decided_at": d["decided_at"],
            "symbol": d["symbol"], "setup": d["setup"], "verdict": d["verdict"],
            "first_failed_gate": d.get("first_failed_gate"), "score": d.get("score"),
            "pipeline_version": d.get("pipeline_version"), "mode": d["mode"], "as_of": d.get("as_of"),
        } | {k: json.dumps(d.get(k)) for k in self.DECISION_JSON}
        cols, qs = ", ".join(row), ", ".join("?" for _ in row)
        with self._lock, self._conn:
            self._conn.execute(f"INSERT INTO decisions ({cols}) VALUES ({qs})", tuple(row.values()))
            for e in evidence:
                self._conn.execute(
                    "INSERT INTO evidence (decision_id, step, label, passed, summary, tool_run_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (dec_id, e["step"], e["label"], None if e.get("passed") is None else int(e["passed"]),
                     e.get("summary"), e.get("run_id")))
        return dec_id

    def _decode_decision(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        for k in self.DECISION_JSON:
            if d.get(k) is not None:
                d[k] = json.loads(d[k])
        return d

    def list_decisions(self, mode: str, session_day: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        q, params = "SELECT * FROM decisions WHERE mode = ?", [mode]
        if session_day:
            q += " AND session_day = ?"
            params.append(session_day)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [self._decode_decision(r) for r in rows]

    def get_decision(self, dec_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM decisions WHERE id = ?", (dec_id,)).fetchone()
            ev = self._conn.execute("SELECT step, label, passed, summary, tool_run_id FROM evidence "
                                    "WHERE decision_id = ? ORDER BY id", (dec_id,)).fetchall()
        if not r:
            return None
        d = self._decode_decision(r)
        d["evidence"] = [dict(e) for e in ev]
        return d

    def decided_symbols(self, mode: str, session_day: str, setup: str) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT symbol FROM decisions WHERE mode=? AND session_day=? AND setup=?",
                                      (mode, session_day, setup)).fetchall()
        return {r[0] for r in rows}

    # ---------------------------------------------------------------- paper trading (mutable)
    def get_account(self, data_mode: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM paper_accounts WHERE data_mode=? ORDER BY created_at LIMIT 1",
                                   (data_mode,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["settings"] = json.loads(d["settings"])
        return d

    def create_account(self, data_mode: str, name: str, capital: float, settings: dict) -> str:
        acc_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO paper_accounts (id, data_mode, name, capital, settings) VALUES (?,?,?,?,?)",
                               (acc_id, data_mode, name, capital, json.dumps(settings)))
        return acc_id

    def upsert_paper_trade(self, t: dict[str, Any]) -> str:
        t = dict(t)
        t.setdefault("id", uuid.uuid4().hex)
        row = {k: (json.dumps(v) if k in self.PAPER_JSON and v is not None else v) for k, v in t.items()}
        with self._lock, self._conn:
            exists = self._conn.execute("SELECT 1 FROM paper_trades WHERE id=?", (t["id"],)).fetchone()
            if exists:                                   # partial update: only the given columns
                sets = [k for k in row if k not in ("id", "created_at")]
                self._conn.execute(f"UPDATE paper_trades SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                                   tuple(row[k] for k in sets) + (t["id"],))
            else:
                cols, qs = ", ".join(row), ", ".join("?" for _ in row)
                self._conn.execute(f"INSERT INTO paper_trades ({cols}) VALUES ({qs})", tuple(row.values()))
        return t["id"]

    def _decode_paper(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        for k in self.PAPER_JSON:
            if d.get(k) is not None:
                d[k] = json.loads(d[k])
        for k in self.PAPER_NUM:
            if isinstance(d.get(k), str):
                d[k] = float(d[k])
        return d

    def get_paper_trade(self, trade_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM paper_trades WHERE id=?", (trade_id,)).fetchone()
        return self._decode_paper(r) if r else None

    def list_paper_trades(self, account_id: str | None = None, mode: str | None = None, data_mode: str | None = None,
                          decision_id: str | None = None, session_day: str | None = None,
                          replay_id: str | None = None) -> list[dict[str, Any]]:
        q, params = "SELECT * FROM paper_trades WHERE 1=1", []
        for col, val in (("account_id", account_id), ("mode", mode), ("data_mode", data_mode),
                         ("decision_id", decision_id), ("session_day", session_day), ("replay_id", replay_id)):
            if val is not None:
                q += f" AND {col}=?"
                params.append(val)
        q += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [self._decode_paper(r) for r in rows]

    # ---------------------------------------------------------------- replay sessions (mutable)
    def create_replay(self, data_mode: str, day: str, symbols: list[str], surprise: bool, clock: str) -> str:
        rid = uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO replay_sessions (id, data_mode, day, symbols, surprise, clock) "
                               "VALUES (?,?,?,?,?,?)", (rid, data_mode, day, json.dumps(symbols), int(surprise), clock))
        return rid

    def get_replay(self, rid: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM replay_sessions WHERE id=?", (rid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["symbols"] = json.loads(d["symbols"])
        return d

    def set_replay_clock(self, rid: str, clock: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE replay_sessions SET clock=? WHERE id=?", (clock, rid))

    def list_replays(self, data_mode: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM replay_sessions WHERE data_mode=? ORDER BY created_at DESC LIMIT 50",
                                      (data_mode,)).fetchall()
        return [dict(r) | {"symbols": json.loads(r["symbols"])} for r in rows]

    def execute(self, sql: str, params: tuple = ()) -> None:
        """Raw statement; used by tests to prove the append-only triggers."""
        with self._lock, self._conn:
            self._conn.execute(sql, params)


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("argv", "input_hashes", "output_json"):
        if d.get(k) is not None:
            d[k] = json.loads(d[k])
    return d
