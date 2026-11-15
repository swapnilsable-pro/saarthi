"""Saarthi API, Phase 0: list registered tools, run them, read the evidence ledger.

Run locally:  uv run uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import os
import platform
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend import bars, clock, narrator
from backend.ledger.db import DEFAULT_DB, Ledger
from backend.pipeline import batch, brief, ideas, perf, swing
from backend.pipeline.jobs import JOBS, run_job, scheduler_loop
from backend.sim import paper, replay as sim_replay
from backend.sim.engine import OrderSpec
from backend.skills.registry import registry, repo_sha
from backend.skills.runner import ArgRejected, run_smoke, run_tool

PAPER_ONLY = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ledger = Ledger(os.environ.get("SAARTHI_DB", DEFAULT_DB))
    task = None
    if os.environ.get("SAARTHI_SCHEDULER", "0") == "1":
        task = asyncio.create_task(scheduler_loop(app.state.ledger))
    yield
    if task:
        task.cancel()
    app.state.ledger.close()


app = FastAPI(title="Saarthi: NSE Trade Cockpit", version="0.2.0-phase1", lifespan=lifespan)


def _ledger(request: Request) -> Ledger:
    return request.app.state.ledger


class RunRequest(BaseModel):
    args: list[str] = Field(default_factory=list, description="arguments after the subcommand")
    as_of: str | None = Field(None, description="IST moment, 'YYYY-MM-DD HH:MM' (point-in-time tools)")
    use_smoke_args: bool = Field(False, description="ignore args/as_of and use the registry smoke invocation")


class JobRequest(BaseModel):
    mode: Literal["live", "demo"] = "demo"


class ScanRequest(BaseModel):
    mode: Literal["live", "demo"] = "demo"
    at: str | None = Field(None, description="IST 'YYYY-MM-DD HH:MM' or 'HH:MM' on the session day; "
                                              "default: now (live) or 09:45 (demo)")
    symbols: list[str] | None = None


class TicketRequest(BaseModel):
    mode: Literal["live", "demo"] = "demo"
    idea_id: str | None = Field(None, description="prefill from this idea; fields below override")
    symbol: str | None = None
    qty: int | None = None
    entry_type: Literal["MARKET", "LIMIT", "SL-M"] | None = None
    entry_price: float | None = None
    stop: float | None = None
    target: float | None = None
    placed_at: str | None = Field(None, description="IST 'YYYY-MM-DD HH:MM'; default: the idea's entry time, or now")
    trail_breakeven: bool | None = None


class GhostRequest(BaseModel):
    mode: Literal["live", "demo"] = "demo"
    day: str | None = None


class ReplayRequest(BaseModel):
    mode: Literal["live", "demo"] = "demo"
    last: int = Field(30, ge=1, le=60, description="how many most recent replayable sessions")
    symbols: list[str] | None = None


class SimCreate(BaseModel):
    mode: Literal["live", "demo"] = "demo"
    day: str | None = None
    symbols: list[str] | None = None
    surprise: bool = False


class SimAdvance(BaseModel):
    bars: int | None = Field(None, ge=1, le=75)
    to: str | None = Field(None, description="HH:MM")
    next_event: bool = False


class SimOrder(BaseModel):
    symbol: str
    qty: int = Field(..., ge=1)
    entry_type: Literal["MARKET", "LIMIT", "SL-M"] = "MARKET"
    entry_price: float | None = None
    stop: float
    target: float | None = None
    trail_breakeven: bool = True


class SwingScan(BaseModel):
    mode: Literal["live", "demo"] = "demo"
    as_of: str | None = Field(None, description="YYYY-MM-DD evening to decide on (demo default 2026-09-18)")
    symbols: list[str] | None = None


class GttRequest(BaseModel):
    mode: Literal["live", "demo"] = "demo"
    idea_id: str
    qty: int | None = None
    trigger: float | None = None
    limit: float | None = None
    stop: float | None = None
    target: float | None = None


class SmokeRequest(BaseModel):
    tool_ids: list[str] | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    reg = registry()
    return {
        "status": "ok",
        "paper_only": PAPER_ONLY,
        "python": platform.python_version(),
        "repos": {k: {"path": str(r.path), "sha": repo_sha(k)} for k, r in reg.repos.items()},
        "tools": len(reg.tools),
        "narrator": narrator.enabled(),
    }


@app.get("/api/tools")
def list_tools() -> list[dict[str, Any]]:
    return [_tool_view(t) for t in registry().tools.values()]


@app.get("/api/tools/{tool_id}")
def get_tool(tool_id: str) -> dict[str, Any]:
    try:
        return _tool_view(registry().tool(tool_id))
    except KeyError:
        raise HTTPException(404, f"unknown tool {tool_id}")


@app.post("/api/tools/{tool_id}/run")
async def run(tool_id: str, body: RunRequest, request: Request) -> dict[str, Any]:
    reg = registry()
    try:
        spec = reg.tool(tool_id)
    except KeyError:
        raise HTTPException(404, f"unknown tool {tool_id}")
    args, as_of = (spec.smoke, spec.smoke_as_of) if body.use_smoke_args else (body.args, body.as_of)
    try:
        return await run_tool(tool_id, args, ledger=_ledger(request), as_of=as_of, purpose="api")
    except ArgRejected as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/smoke")
async def smoke(body: SmokeRequest, request: Request) -> dict[str, Any]:
    try:
        results = await run_smoke(_ledger(request), tool_ids=body.tool_ids)
    except KeyError as e:
        raise HTTPException(404, str(e))
    summary = [{"tool_id": r["tool_id"], "status": r["status"], "duration_ms": r["duration_ms"],
                "run_id": r["id"], "has_json": r["output_json"] is not None} for r in results]
    return {"ok": all(s["status"] == "ok" for s in summary), "results": summary}


@app.get("/api/runs")
def list_runs(request: Request, tool_id: str | None = None,
              limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return _ledger(request).list_runs(tool_id, limit)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, Any]:
    run = _ledger(request).get_run(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    return run


@app.get("/api/session")
def session(at: str | None = None) -> dict[str, Any]:
    """NSE clock from nse-trader-skill's nsecal. `at` = 'YYYY-MM-DD HH:MM' IST to ask about another moment."""
    try:
        return clock.session_info(clock.parse(at) if at else None)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/jobs")
def list_jobs(request: Request, limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    return {"available": list(JOBS), "scheduler": os.environ.get("SAARTHI_SCHEDULER", "0") == "1",
            "runs": _ledger(request).list_jobs(limit)}


@app.post("/api/jobs/{job}/run")
async def trigger_job(job: str, body: JobRequest, request: Request) -> dict[str, Any]:
    if job not in JOBS:
        raise HTTPException(404, f"unknown job {job}")
    return await run_job(job, body.mode, _ledger(request), trigger="manual")


@app.get("/api/today")
def today(request: Request, mode: Literal["live", "demo"] = "demo") -> dict[str, Any]:
    return brief.today(_ledger(request), mode)


@app.post("/api/ideas/scan")
async def scan_ideas(body: ScanRequest) -> dict[str, Any]:
    """Run the opening-range scan at a moment and turn each new breakout into a decided idea."""
    from backend.pipeline.jobs import DEMO_SESSION
    base = DEMO_SESSION if body.mode == "demo" else clock.ist_now().date()
    try:
        if body.at and len(body.at) <= 5:
            at = clock.parse(f"{base.isoformat()} {body.at}")
        elif body.at:
            at = clock.parse(body.at)
        else:
            at = clock.parse(f"{base.isoformat()} 09:45") if body.mode == "demo" else clock.ist_now()
    except ValueError as e:
        raise HTTPException(422, str(e))
    if body.mode == "live" and at > clock.ist_now():
        raise HTTPException(422, "cannot scan the future")
    return await ideas.scan_and_decide(app.state.ledger, body.mode, at, symbols=body.symbols)


@app.post("/api/swing/scan")
async def swing_scan(body: SwingScan, request: Request) -> dict[str, Any]:
    return await swing.scan(_ledger(request), body.mode, as_of=body.as_of, symbols=body.symbols)


@app.get("/api/daily-bars")
def daily_bars(mode: Literal["live", "demo"], symbol: str, until: str | None = None) -> dict[str, Any]:
    rows = swing.full_daily(mode, symbol)
    return {"symbol": symbol.upper(), "bars": [r for r in rows if not until or r["date"] <= until]}


@app.post("/api/paper/gtt")
def paper_gtt(body: GttRequest, request: Request) -> dict[str, Any]:
    """A PAPER GTT (swing, CNC) from a swing idea's plan; fields override the plan."""
    d = _ledger(request).get_decision(body.idea_id)
    if not d or d["setup"] != "swing" or not (d.get("plan") or {}).get("trigger"):
        raise HTTPException(404, "no such swing idea with a plan")
    spec = paper.gtt_from_idea(d) | body.model_dump(exclude={"mode", "idea_id"}, exclude_none=True)
    return paper.place_gtt(_ledger(request), body.mode, spec, decision_id=d["id"])


@app.get("/api/ideas")
def list_ideas(request: Request, mode: Literal["live", "demo"] = "demo", day: str | None = None,
               setup: Literal["orb", "swing"] | None = None) -> dict[str, Any]:
    rows = [d for d in _ledger(request).list_decisions(mode, day) if not setup or d["setup"] == setup]
    slim = [{k: d.get(k) for k in ("id", "session_day", "decided_at", "symbol", "setup", "verdict",
                                   "first_failed_gate", "score", "as_of", "created_at")}
            | {"reason": (d.get("detail") or {}).get("reason"),
               "name": (d.get("detail") or {}).get("name"),
               "synthetic": (d.get("detail") or {}).get("synthetic"),
               "plan": {k: (d.get("plan") or {}).get(k) for k in ("entry", "stop", "target", "qty", "risk_amount",
                                                                  "best_window", "entry_at", "trigger", "limit",
                                                                  "risk_if_stopped")} if d.get("plan") else None,
               "odds": ({k: (d.get("odds") or {}).get(k) for k in ("p_target", "net_per_trade", "net_rr")}
                        if d["setup"] == "orb" else (d.get("odds") or {}).get("backtest")) if d.get("odds") else None}
            for d in rows]
    return {"mode": mode, "count": len(slim), "ideas": slim, "settings": ideas.SETTINGS}


@app.get("/api/ideas/{idea_id}")
def get_idea(idea_id: str, request: Request) -> dict[str, Any]:
    d = _ledger(request).get_decision(idea_id)
    if not d:
        raise HTTPException(404, "no such idea")
    return d


@app.get("/api/ideas/{idea_id}/bars")
def idea_bars(idea_id: str, request: Request, full: bool = False) -> dict[str, Any]:
    """The session's 5-minute bars for the chart, cut at the decision moment unless full=true
    (full shows what happened next - hindsight, labelled as such in the UI)."""
    d = _ledger(request).get_decision(idea_id)
    if not d:
        raise HTTPException(404, "no such idea")
    day = clock.parse(d["session_day"]).date()
    until = None if full else clock.parse(d["as_of"])
    return {"symbol": d["symbol"], "day": d["session_day"], "cut_at": None if full else d["as_of"],
            "bars": bars.session_bars(d["mode"], d["symbol"], day, until)}


def _ticket(body: TicketRequest, request: Request) -> dict[str, Any]:
    base: dict[str, Any] = {}
    if body.idea_id:
        d = _ledger(request).get_decision(body.idea_id)
        if not d or not d.get("plan"):
            raise HTTPException(404, "no such idea, or it has no plan")
        if d["mode"] != body.mode:
            raise HTTPException(422, f"this idea belongs to {d['mode']} mode")
        base = paper.order_from_idea(d)
    over = body.model_dump(exclude={"mode", "idea_id"}, exclude_none=True)
    t = base | over
    if "placed_at" not in t:
        t["placed_at"] = clock.ist_now().strftime("%Y-%m-%d %H:%M")
    t.setdefault("trail_breakeven", True)
    if not t.get("planned_entry"):
        t["planned_entry"] = t.get("entry_price")
    missing = [k for k in ("symbol", "qty", "entry_type", "stop") if t.get(k) in (None, "")]
    if missing:
        raise HTTPException(422, f"missing {', '.join(missing)}")
    t["symbol"] = t["symbol"].upper()
    return t


def _spec(t: dict[str, Any]) -> OrderSpec:
    return OrderSpec(**{k: t[k] for k in OrderSpec.__dataclass_fields__ if k in t})


@app.get("/api/bars")
def session_bars(mode: Literal["live", "demo"], symbol: str, day: str) -> dict[str, Any]:
    """5-minute bars of one session from the bar store (live: only completed bars up to now)."""
    try:
        d = clock.parse(day).date()
    except ValueError as e:
        raise HTTPException(422, str(e))
    until = clock.ist_now() if mode == "live" and d == clock.ist_now().date() else None
    return {"symbol": symbol.upper(), "day": d.isoformat(), "bars": bars.session_bars(mode, symbol.upper(), d, until)}


@app.get("/api/paper/account")
def paper_account(request: Request, mode: Literal["live", "demo"] = "demo") -> dict[str, Any]:
    return paper.account_state(_ledger(request), mode)


@app.post("/api/paper/preview")
def paper_preview(body: TicketRequest, request: Request) -> dict[str, Any]:
    t = _ticket(body, request)
    return {"ticket": t} | paper.preview(_ledger(request), body.mode, _spec(t))


@app.post("/api/paper/orders")
def paper_place(body: TicketRequest, request: Request) -> dict[str, Any]:
    """Place a PAPER order on the simulated exchange. There is no other kind of order."""
    t = _ticket(body, request)
    return paper.SimulatedExchange(_ledger(request), body.mode).place(t)


@app.get("/api/paper/trades")
def paper_trades(request: Request, mode: Literal["live", "demo"] = "demo", ghost: bool = False,
                 idea_id: str | None = None) -> dict[str, Any]:
    L = _ledger(request)
    rows = [r for r in L.list_paper_trades(data_mode=mode, decision_id=idea_id) if not r.get("replay_id")]
    rows = [paper.refresh(L, r["id"]) if r["status"] in ("working", "open") else r for r in rows]
    rows = [r for r in rows if (r["mode"] == "ghost") == ghost]
    return {"mode": mode, "trades": rows}


@app.get("/api/paper/trades/{trade_id}")
def paper_trade(trade_id: str, request: Request) -> dict[str, Any]:
    t = paper.refresh(_ledger(request), trade_id)
    if not t:
        raise HTTPException(404, "no such paper trade")
    return t


@app.post("/api/paper/trades/{trade_id}/cancel")
def paper_cancel(trade_id: str, request: Request) -> dict[str, Any]:
    t = _ledger(request).get_paper_trade(trade_id)
    if not t:
        raise HTTPException(404, "no such paper trade")
    try:
        return paper.SimulatedExchange(_ledger(request), t["data_mode"]).cancel(trade_id)
    except paper.PaperError as e:
        raise HTTPException(409, str(e))


@app.post("/api/paper/ghosts")
def paper_ghosts(body: GhostRequest, request: Request) -> dict[str, Any]:
    from backend.pipeline.jobs import DEMO_SESSION
    day = body.day or (DEMO_SESSION.isoformat() if body.mode == "demo" else clock.ist_now().date().isoformat())
    made = paper.run_ghosts(_ledger(request), body.mode, day)
    return {"day": day, "created": len(made),
            "ghosts": [{"symbol": g["symbol"], "verdict": g["verdict"], "status": g["status"],
                        "exit_reason": g["exit_reason"], "net_pnl": g["net_pnl"], "r_multiple": g["r_multiple"]}
                       for g in made]}


@app.post("/api/replay/batch")
async def replay_batch(body: ReplayRequest, request: Request) -> dict[str, Any]:
    """Re-run past sessions as the scheduler would have (point-in-time), then ghost-trade every idea."""
    return await batch.replay(_ledger(request), body.mode, last=body.last, symbols=body.symbols)


@app.get("/api/history")
def history(request: Request, mode: Literal["live", "demo"] = "demo") -> dict[str, Any]:
    return perf.history(_ledger(request), mode)


@app.get("/api/history/{day}")
def history_day(day: str, request: Request, mode: Literal["live", "demo"] = "demo") -> dict[str, Any]:
    return perf.day_detail(_ledger(request), mode, day)


@app.get("/api/performance")
def performance(request: Request, mode: Literal["live", "demo"] = "demo",
                book: Literal["mine", "take", "all"] = "all") -> dict[str, Any]:
    L = _ledger(request)
    return {"stats": perf.stats(L, mode, book), "calibration": perf.calibration(L, mode),
            "gates": perf.gate_value(L, mode),
            "books": {b: perf.stats(L, mode, b).get("trades", 0) for b in perf.BOOKS}}


def _sim(fn, *a, **k):
    try:
        return fn(*a, **k)
    except sim_replay.ReplayError as e:
        raise HTTPException(409, str(e))


@app.get("/api/sim/days")
def sim_days(mode: Literal["live", "demo"] = "demo", symbols: str | None = None) -> dict[str, Any]:
    syms = [s.strip().upper() for s in symbols.split(",")] if symbols else (["DEMO"] if mode == "demo" else [])
    days, _ = batch.replayable_days(mode, syms) if syms else ([], None)
    return {"symbols": syms, "days": [d.isoformat() for d in days]}


@app.post("/api/sim/sessions")
async def sim_create(body: SimCreate, request: Request) -> dict[str, Any]:
    try:
        return await sim_replay.create(_ledger(request), body.mode, day=body.day, symbols=body.symbols,
                                       surprise=body.surprise)
    except sim_replay.ReplayError as e:
        raise HTTPException(409, str(e))


@app.get("/api/sim/sessions/{rid}")
def sim_state(rid: str, request: Request) -> dict[str, Any]:
    return _sim(sim_replay.state, _ledger(request), rid)


@app.post("/api/sim/sessions/{rid}/advance")
def sim_advance(rid: str, body: SimAdvance, request: Request) -> dict[str, Any]:
    return _sim(sim_replay.advance, _ledger(request), rid, bars_n=body.bars, to=body.to, next_event=body.next_event)


@app.post("/api/sim/sessions/{rid}/orders")
def sim_order(rid: str, body: SimOrder, request: Request) -> dict[str, Any]:
    return _sim(sim_replay.place, _ledger(request), rid, body.model_dump())


@app.post("/api/sim/sessions/{rid}/trades/{trade_id}/close")
def sim_close(rid: str, trade_id: str, request: Request) -> dict[str, Any]:
    return _sim(sim_replay.close, _ledger(request), rid, trade_id)


@app.post("/api/ideas/{idea_id}/narrate")
def narrate_idea(idea_id: str, request: Request) -> dict[str, Any]:
    """Optional: Claude explains the recorded evidence in plain English (never decides anything)."""
    d = _ledger(request).get_decision(idea_id)
    if not d:
        raise HTTPException(404, "no such idea")
    try:
        return narrator.narrate(d)
    except narrator.NarratorError as e:
        raise HTTPException(503, str(e))


def _tool_view(t) -> dict[str, Any]:
    return {
        "id": t.id, "repo": t.repo, "script": t.script, "command": t.command, "role": t.role,
        "json": bool(t.json_flag), "point_in_time": t.point_in_time,
        "time_flag": t.time_flag.flag if t.time_flag else None,
        "network": t.network, "timeout": t.timeout,
    }


# ------------------------------------------------------------------ single-container mode
# When the web app has been built (npm --prefix web run build), serve it from the API too, so
# `uvicorn backend.api.app:app` (or the Docker image) is the whole product on one port.
from pathlib import Path as _Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_DIST = _Path(__file__).resolve().parents[2] / "web" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def _index() -> FileResponse:
        return FileResponse(_DIST / "index.html")
