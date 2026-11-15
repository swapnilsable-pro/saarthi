"""Scheduled jobs (IMPLEMENTATION_PLAN.md §5.1): which repo tools run, with which arguments.

Two modes:
  live  the tools fetch from NSE / Yahoo themselves (yfinance for the India repo's --symbol).
  demo  the tools read each repo's own test fixtures, frozen at a session in Nov 2026, so the
        cockpit can be explored on a weekend, offline, or in CI. Demo output is real tool
        output on real archived data, just not today's.

A job never computes a market number itself; it only decides what to run.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from backend import clock
from backend.ledger.db import Ledger
from backend.skills.registry import ROOT
from backend.skills.runner import run_tool

UPLOADS = ROOT / "data" / "uploads"
CACHE = ROOT / "data" / "cache"   # bhavcopies etc. survive between runs (the run dir does not)

# The demo story: evening scan after Fri 6 Nov 2026, pre-market brief and intraday session on
# Mon 9 Nov 2026 - the last session in nse-trader-skill's fixtures, where its synthetic DEMO
# instrument has 60 sessions of 5-minute history and an opening-range breakout.
DEMO_EVENING_AS_OF = "2026-11-06 18:30"
DEMO_PREMARKET_AS_OF = "2026-11-09 08:30"
DEMO_SESSION = dt.date(2026, 11, 9)


@dataclass
class Step:
    key: str
    tool_id: str
    args: list[str] = field(default_factory=list)
    as_of: str | None = None          # passed to the tool's own time flag
    optional: bool = False            # a failure here makes the job 'partial', not 'failed'
    skip_reason: str | None = None    # set when the step cannot run (e.g. missing upload)


def evening_steps(mode: str, session_day: dt.date, replay: bool = False) -> list[Step]:
    if mode == "demo":
        return [
            Step("universe", "nse.scan.universe", ["--offline", "{nse_fx}/nse-scanner/EQUITY_L.csv"]),
            # --sessions 24: exactly the bhavcopies the fixtures hold up to 6 Nov. Asking for more makes
            # the scanner fetch the missing day from NSE (and cache it beside the fixtures).
            Step("daily", "nse.scan.daily", ["--offline", "{nse_fx}/nse-scanner", "--min-turnover", "0",
                                             "--sessions", "24", "--show", "50"], as_of=DEMO_EVENING_AS_OF),
            Step("bands", "nse.scan.bands", ["--offline", "{nse_fx}/nse-scanner"]),
            Step("deals", "nse.deals", ["--offline", "{nse_fx}/nse-deals", "--show", "50"], optional=True),
            Step("results", "nse.analyst.calendar", ["--offline", "{nse_fx}/nse-analyst", "--back", "3650",
                                                     "--show", "50"], optional=True),
        ]
    return [
        Step("universe", "nse.scan.universe"),
        Step("daily", "nse.scan.daily", ["--show", "50", "--cache", str(CACHE / "bhav")]),
        Step("bands", "nse.scan.bands"),
        Step("deals", "nse.deals", ["--show", "50"], optional=True),
        Step("results", "nse.analyst.calendar", ["--days", "7", "--back", "1", "--show", "100"], optional=True),
    ]


def premarket_steps(mode: str, session_day: dt.date, replay: bool = False) -> list[Step]:
    if mode == "demo":
        day = session_day.isoformat()
        return [
            Step("regime", "india.regime.status", ["--csv", "{india_fx}/regime_novolume.csv",
                                                   "--volume-csv", "{india_fx}/regime_proxy_volume.csv",
                                                   "--name", "NIFTY 50 (demo data)"]),
            Step("breadth", "india.breadth.status", ["--ad-csv", "{india_fx}/breadth_ad.csv"], optional=True),
            Step("sectors", "india.sectors.rotation", ["--csv-dir", "{india_fx}/sector_indices"], optional=True),
            Step("events", "india.events.range", ["--from", day, "--to", _plus(day, 7)],
                 as_of=f"{day} 08:30"),
            Step("news", "nse.news.announcements", ["--offline", "{nse_fx}/nse-news", "--hours", "8760",
                                                    "--no-state", "--all"], optional=True),
        ]
    day = session_day.isoformat()
    if replay:   # a past live session: only the steps whose tools can answer as of that morning
        return [
            Step("regime", "india.regime.status", ["--symbol", "NIFTY"], as_of=f"{day} 08:30"),
            Step("events", "india.events.range", ["--from", day, "--to", _plus(day, 7)], as_of=f"{day} 08:30"),
        ]
    ad = UPLOADS / "breadth_ad.csv"
    return [
        Step("regime", "india.regime.status", ["--symbol", "NIFTY"]),
        Step("breadth", "india.breadth.status", ["--ad-csv", str(ad.relative_to(ROOT))], optional=True,
             skip_reason=None if ad.exists() else
             "Upload NSE's daily advance/decline CSV as data/uploads/breadth_ad.csv to enable breadth."),
        Step("sectors", "india.sectors.rotation", [], optional=True),
        Step("events", "india.events.range", ["--from", day, "--to", _plus(day, 7)]),
        Step("news", "nse.news.announcements", ["--hours", "16", "--no-state", "--all", "--fast"],
             optional=True),
    ]


JOBS: dict[str, Callable[[str, dt.date], list[Step]]] = {
    "evening_scan": evening_steps,
    "premarket_brief": premarket_steps,
}


def _plus(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def _demo_as_of(job: str, day: dt.date) -> str:
    if job == "evening_scan":
        return DEMO_EVENING_AS_OF if day == DEMO_SESSION else \
            f"{clock.nsecal.prev_session_day(day).isoformat()} 18:30"
    return f"{day.isoformat()} 08:30"


def session_day_for(job: str, mode: str, now: dt.datetime | None = None) -> dt.date:
    if mode == "demo":
        return DEMO_SESSION
    return clock.target_session_day(job, now or clock.ist_now())


async def run_job(job: str, mode: str, ledger: Ledger, *, trigger: str = "manual",
                  session_day: dt.date | None = None, replay: bool = False) -> dict:
    if job not in JOBS:
        raise KeyError(f"unknown job {job!r}")
    if mode not in ("live", "demo"):
        raise ValueError("mode must be 'live' or 'demo'")
    day = session_day or session_day_for(job, mode)
    steps = JOBS[job](mode, day, replay)
    started = clock.ist_now()
    t0 = time.perf_counter()
    sem = asyncio.Semaphore(3)

    async def one(s: Step) -> tuple[str, dict]:
        if s.skip_reason:
            return s.key, {"tool_id": s.tool_id, "status": "skipped", "reason": s.skip_reason,
                           "optional": s.optional}
        async with sem:
            rec = await run_tool(s.tool_id, s.args, ledger=ledger, as_of=s.as_of, purpose=f"job:{job}")
        return s.key, {"tool_id": s.tool_id, "status": rec["status"], "tool_run_id": rec["id"],
                       "optional": s.optional}

    results = dict(await asyncio.gather(*(one(s) for s in steps)))
    required_bad = [k for k, v in results.items() if not v["optional"] and v["status"] != "ok"]
    any_bad = [k for k, v in results.items() if v["status"] != "ok"]
    status = "failed" if len(required_bad) == len([s for s in steps if not s.optional]) else \
             "partial" if any_bad else "ok"
    record = {
        "job": job, "mode": mode, "session_day": day.isoformat(),
        "as_of": _demo_as_of(job, day) if mode == "demo" else None,
        "status": status, "steps": results, "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_ms": int((time.perf_counter() - t0) * 1000), "trigger": trigger,
    }
    record["id"] = ledger.record_job(record)
    return record


def orb_tick_due(now: dt.datetime, last_tick: dt.datetime | None) -> dt.datetime | None:
    """The 5-minute bar boundary to scan at, if one is due: entry window only, once per bar."""
    d = now.date()
    if not (nsecal_covered(d) and clock.nsecal.session(d)):
        return None
    bar = now.replace(second=0, microsecond=0, minute=now.minute - now.minute % 5)
    or_end = (dt.datetime.combine(d, clock.nsecal.SESSION_OPEN) + dt.timedelta(minutes=clock.OR_MINUTES)).time()
    if not (or_end < bar.time() <= clock.NO_ENTRIES_AFTER):
        return None
    if last_tick and bar <= last_tick:
        return None
    return bar


def nsecal_covered(d: dt.date) -> bool:
    return clock.nsecal.covered(d)


async def scheduler_loop(ledger: Ledger, interval_s: int = 30) -> None:
    """Live-mode scheduler: evening scan, pre-market brief, and an opening-range scan after each
    completed 5-minute bar in the entry window. NSE session days only (nsecal)."""
    from backend.pipeline.ideas import scan_and_decide
    last_tick = None
    while True:
        now = clock.ist_now()
        try:
            for job, day in clock.due_jobs(now, lambda j, d: ledger.has_job_for(j, "live", d)):
                await run_job(job, "live", ledger, trigger="schedule", session_day=day)
            bar = orb_tick_due(now, last_tick)
            if bar:
                last_tick = bar
                await scan_and_decide(ledger, "live", bar)
            if bar or (clock.nsecal.covered(now.date()) and clock.nsecal.session(now.date())
                       and dt.time(9, 20) <= now.time() <= dt.time(15, 35) and now.minute % 5 == 0):
                from backend.sim.paper import refresh_open_live
                await refresh_open_live(ledger)
            if now.time() >= dt.time(15, 45) and clock.nsecal.covered(now.date()) and clock.nsecal.session(now.date()):
                from backend.sim.paper import run_ghosts
                await asyncio.to_thread(run_ghosts, ledger, "live", now.date().isoformat())
        except Exception as e:  # never let the loop die; the next tick retries
            print(f"[scheduler] {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(interval_s)
