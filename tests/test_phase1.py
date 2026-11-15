"""Phase 1: NSE clock, scheduled jobs, the Today brief and its endpoints (all offline, demo mode)."""
import datetime as dt

import pytest

from backend import clock
from backend.pipeline import brief
from backend.pipeline.jobs import run_job


# ------------------------------------------------------------------ clock (nsecal-backed)
@pytest.mark.parametrize("when, phase", [
    ("2026-11-15 10:00", "closed"),          # Sunday
    ("2026-11-10 10:00", "closed"),          # Diwali Balipratipada, per nsecal
    ("2026-11-16 08:45", "pre_market"),
    ("2026-11-16 09:05", "pre_open"),
    ("2026-11-16 09:20", "opening_range"),
    ("2026-11-16 10:05", "entry_window"),
    ("2026-11-16 14:45", "manage_only"),
    ("2026-11-16 15:20", "square_off"),
    ("2026-11-16 16:00", "post_close"),
])
def test_phases(when, phase):
    assert clock.session_info(clock.parse(when))["phase"] == phase


def test_holiday_is_named_and_next_session_skips_it():
    info = clock.session_info(clock.parse("2026-11-10 10:00"))
    assert info["holiday"] and "Balipratipada" in info["holiday"]
    assert info["next_session"] == "2026-11-11"


def test_scheduler_rule():
    done: set[tuple[str, str]] = set()
    seen = lambda j, d: (j, d) in done
    assert clock.due_jobs(dt.datetime(2026, 11, 16, 7, 0), seen) == []
    assert clock.due_jobs(dt.datetime(2026, 11, 16, 8, 31), seen) == [("premarket_brief", dt.date(2026, 11, 16))]
    done.add(("premarket_brief", "2026-11-16"))
    assert clock.due_jobs(dt.datetime(2026, 11, 16, 12, 0), seen) == []
    assert clock.due_jobs(dt.datetime(2026, 11, 16, 18, 31), seen) == [("evening_scan", dt.date(2026, 11, 17))]
    assert clock.due_jobs(dt.datetime(2026, 11, 15, 9, 0), seen) == []      # Sunday: nothing


# ------------------------------------------------------------------ jobs + brief
@pytest.fixture
async def demo_ledger(ledger):
    for job in ("evening_scan", "premarket_brief"):
        rec = await run_job(job, "demo", ledger)
        assert rec["status"] == "ok", rec["steps"]
    return ledger


async def test_jobs_record_every_step(demo_ledger):
    job = demo_ledger.latest_job("evening_scan", "demo")
    assert job["session_day"] == "2026-11-09"
    assert set(job["steps"]) == {"universe", "daily", "bands", "deals", "results"}
    for step in job["steps"].values():
        assert demo_ledger.get_run(step["tool_run_id"])["status"] == "ok"


async def test_today_brief_is_built_from_evidence(demo_ledger):
    t = brief.today(demo_ledger, "demo")
    assert t["clock"]["phase"] == "pre_market" and t["session_day"] == "2026-11-09"
    # Regime says "Confirmed uptrend" (go) but the demo breadth score is 21/100, so one step down.
    assert t["mood"]["regime"]["label"] == "Confirmed uptrend"
    assert t["mood"]["level"] == "caution"
    effects = {f["label"]: f["effect"] for f in t["mood"]["factors"]}
    assert effects["Breadth"] == "down"
    assert all(f["run_id"] for f in t["mood"]["factors"])
    rows = t["watchlist"]["rows"]
    assert len(rows) >= 5 and t["watchlist"]["as_of"] == "2026-11-06"
    assert rows[0]["evidence"]["daily"] == t["watchlist"]["run_id"]
    assert t["events"]["run_id"] and t["sectors"]["tilt"] == "Risk-on"


def test_mood_rule_mapping():
    class P:  # minimal Evidence stand-in
        def __init__(self, outputs): self.outputs, self.run_ids = outputs, {}
        def get(self, k): return self.outputs.get(k)
    reg = lambda label: {"regime": {"label": label}, "trend": {}}
    assert brief.market_mood(P({"regime": reg("Correction")}), "2026-11-16")["level"] == "stand_aside"
    assert brief.market_mood(P({"regime": reg("Rally attempt")}), "2026-11-16")["level"] == "caution"
    high = {"events": [{"date": "2026-11-16", "impact": "high", "title": "RBI policy"}]}
    m = brief.market_mood(P({"regime": reg("Confirmed uptrend"), "events": high}), "2026-11-16")
    assert m["level"] == "caution"
    assert brief.market_mood(P({}), "2026-11-16")["level"] == "unknown"


def test_job_runs_are_append_only(ledger):
    import sqlite3
    ledger.record_job({"job": "evening_scan", "mode": "demo", "session_day": "2026-11-11", "status": "ok",
                       "steps": {}, "started_at": "x", "duration_ms": 1})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.execute("DELETE FROM job_runs")


# ------------------------------------------------------------------ API
def test_today_api_flow(client):
    assert client.get("/api/today?mode=demo").json()["jobs"]["evening_scan"] is None
    for job in ("evening_scan", "premarket_brief"):
        r = client.post(f"/api/jobs/{job}/run", json={"mode": "demo"})
        assert r.status_code == 200 and r.json()["status"] == "ok"
    t = client.get("/api/today?mode=demo").json()
    assert t["mood"]["level"] == "caution" and t["watchlist"]["rows"]
    assert client.get("/api/jobs").json()["runs"][0]["job"] == "premarket_brief"
    assert client.post("/api/jobs/nope/run", json={"mode": "demo"}).status_code == 404
    assert client.get("/api/today?mode=bogus").status_code == 422


def test_session_api(client):
    s = client.get("/api/session?at=2026-11-16 10:05").json()
    assert s["phase"] == "entry_window" and s["marks"]["square_off"] == "15:15"
    assert client.get("/api/session?at=garbage").status_code == 422
