"""Batch replay: re-run past sessions exactly as the live scheduler would have, one day at a time.

For each session day D (oldest first):
  1. the pre-market brief is prepared for D, with every point-in-time tool told it is D 08:30;
  2. the opening-range scan finds D's breakouts; each is decided at the close of its confirming bar
     (the scan is re-run at that moment, so the decision sees nothing later - same as live);
  3. after the session, every idea is ghost-traded as planned (backend/sim/paper.run_ghosts).
The Time Machine is always run with --now at the decision moment, so it only draws on sessions
before D. Days with fewer than MIN_HISTORY earlier sessions are skipped: the Time Machine refuses them.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any

from backend import bars
from backend.ledger.db import Ledger
from backend.pipeline import ideas
from backend.pipeline.jobs import run_job
from backend.sim import paper

MIN_HISTORY = 20


def replayable_days(mode: str, symbols: list[str]) -> tuple[list[dt.date], str | None]:
    """Session days in the saved charts that have enough earlier history, plus the chart folder."""
    folder = bars.demo_dir() if mode == "demo" else None
    if mode == "live":
        today = dt.date.today()
        for s in symbols:
            folder = bars.history_dir("live", s, today - dt.timedelta(days=90))
            if folder:
                break
    if folder is None:
        return [], None
    days = bars.session_days(mode, symbols[0], folder)
    return days[MIN_HISTORY:], str(folder)


async def replay(ledger: Ledger, mode: str, *, last: int = 30, symbols: list[str] | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    syms = symbols or (["DEMO"] if mode == "demo" else [])
    if not syms:
        return {"error": "Pass the symbols whose saved charts to replay.", "days": 0}
    days, folder = replayable_days(mode, syms)
    days = days[-last:]
    made: list[dict] = []
    ghosts = 0
    for day in days:
        m, g = await replay_day(ledger, mode, day, syms, folder)
        made += m
        ghosts += g
    counts: dict[str, int] = {}
    for d in made:
        counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
    return {"mode": mode, "symbols": syms, "days": len(days),
            "from": days[0].isoformat() if days else None, "to": days[-1].isoformat() if days else None,
            "ideas": len(made), "by_verdict": counts, "ghosts": ghosts,
            "seconds": round(time.perf_counter() - t0, 1)}


async def replay_day(ledger: Ledger, mode: str, day: dt.date, syms: list[str], folder: str) -> tuple[list[dict], int]:
    """One session, point-in-time: brief, a decision at each breakout's bar close, then ghosts."""
    if not ledger.latest_job("premarket_brief", mode, day.isoformat()):
        await run_job("premarket_brief", mode, ledger, trigger="replay", session_day=day, replay=(mode == "live"))
    made = []
    for b in await _breakouts(ledger, mode, day, syms, folder):
        bar_close = dt.datetime.combine(day, dt.time(*map(int, b["at"].split(":")))) + dt.timedelta(minutes=5)
        r = await ideas.scan_and_decide(ledger, mode, bar_close, symbols=[b["symbol"]], folder=folder, origin="batch")
        made += r["decisions"]
    ghosts = len(await asyncio.to_thread(paper.run_ghosts, ledger, mode, day.isoformat()))
    return made, ghosts


async def _breakouts(ledger: Ledger, mode: str, day: dt.date, syms: list[str], folder: str) -> list[dict]:
    from backend.skills.runner import run_tool
    run = await run_tool("nse.scan.orb", ["--offline", folder, "--symbols", ",".join(syms),
                                          "--or-minutes", str(ideas.SETTINGS["orb_minutes"])],
                         ledger=ledger, as_of=f"{day.isoformat()} 15:30", purpose=f"replay-probe:{mode}")
    already = ledger.decided_symbols(mode, day.isoformat(), "orb")
    return [b for b in (run.get("output_json") or {}).get("breakouts", [])
            if b["symbol"] not in already and b["at"] < ideas.SETTINGS["no_entries_after"]]
