"""Phase 2: intraday opening-range ideas, end to end on the nse repo's fixtures (offline)."""
import datetime as dt

import pytest

from backend.pipeline import ideas
from backend.pipeline.ideas import best_window, scan_and_decide, verdict_of
from backend.pipeline.jobs import orb_tick_due, run_job

DAY = dt.date(2026, 11, 9)


@pytest.fixture
async def demo(ledger):
    for job in ("evening_scan", "premarket_brief"):
        assert (await run_job(job, "demo", ledger))["status"] == "ok"
    return ledger


async def test_no_breakout_before_the_range_completes(demo):
    r = await scan_and_decide(demo, "demo", dt.datetime(2026, 11, 9, 9, 30))
    assert r["breakouts"] == [] and r["decisions"] == []


async def test_demo_breakout_becomes_a_fully_evidenced_idea(demo):
    r = await scan_and_decide(demo, "demo", dt.datetime(2026, 11, 9, 9, 45))
    assert [b["symbol"] for b in r["breakouts"]] == ["DEMO"]
    d = demo.get_decision(r["decisions"][0]["id"])

    # The synthetic random walk has no edge after costs: an honest SKIP on net expectancy.
    assert d["verdict"] == "SKIP" and d["first_failed_gate"] == "C6"
    assert d["odds"]["net_per_trade"] < 0 and d["odds"]["trials"] == 10000

    plan = d["plan"]
    assert plan["entry"] > plan["range"]["high"] > plan["stop"]
    assert plan["target"] > plan["entry"] and plan["qty"] > 0
    assert plan["entry_at"] == "09:40"                       # bar 09:35-09:40 confirmed the breakout
    # Every price sits on the NSE tick grid (slab 0.10 above Rs 1,000).
    for px in (plan["entry"], plan["stop"], plan["target"]):
        assert abs(round(px / 0.10) * 0.10 - px) < 1e-6

    gates = {g["step"]: g for g in d["detail"]["gates"]}
    assert set(gates) >= {"G0", "G1", "G2", "G3", "G4", "G5", "G6", "C3", "C6", "C6b"}
    assert gates["G3"]["status"] == "na" and gates["G4"]["status"] == "na"   # synthetic: no exchange, no results
    assert gates["G6"]["required"] is False

    assert len(d["detail"]["variants"]) == 6                 # 2 stop methods x 3 targets
    assert d["detail"]["timing"][0]["at"] == "09:40" and d["detail"]["timing"][-1]["at"] <= "14:30"
    assert abs(d["costs"]["cross_check_delta"]) <= 1         # both repos' calculators agree
    assert len(d["evidence"]) == len(d["detail"]["gates"])
    for g in d["detail"]["gates"]:
        if g["run_id"]:
            assert demo.get_run(g["run_id"])["status"] == "ok"


async def test_runs_are_point_in_time(demo):
    r = await scan_and_decide(demo, "demo", dt.datetime(2026, 11, 9, 9, 45))
    d = demo.get_decision(r["decisions"][0]["id"])
    orb = demo.get_run(r["orb_run_id"])
    assert orb["as_of"] == "2026-11-09 09:45"
    tm = demo.get_run(d["odds"]["run_id"])
    assert tm["as_of"] == "2026-11-09 09:40" and "--now" in tm["argv"]


async def test_a_breakout_is_decided_once(demo):
    await scan_and_decide(demo, "demo", dt.datetime(2026, 11, 9, 9, 45))
    again = await scan_and_decide(demo, "demo", dt.datetime(2026, 11, 9, 10, 30))
    assert again["decisions"] == [] and again["already_decided"] == ["DEMO"]


def _g(step, status, required=True):
    return {"step": step, "label": step, "status": status, "summary": "", "required": required}


def test_verdict_rule():
    assert verdict_of([_g("G1", "pass"), _g("C6", "pass")])[0] == "TAKE"
    assert verdict_of([_g("G1", "pass"), _g("G3", "no_data"), _g("C6", "pass")])[:2] == ("WATCH", "G3")
    assert verdict_of([_g("G3", "no_data"), _g("C6", "fail")])[:2] == ("SKIP", "C6")    # a failure beats missing data
    assert verdict_of([_g("G1", "pass"), _g("G6", "no_data", required=False)])[0] == "TAKE"
    assert verdict_of([_g("G1", "pass"), _g("G6", "fail", required=False)])[0] == "SKIP"


def test_best_window():
    curve = [{"at": t, "net_per_trade": v} for t, v in
             [("09:40", 50), ("09:55", 100), ("10:10", 90), ("10:25", 40), ("10:40", -5)]]
    w = best_window(curve)
    assert (w["from"], w["to"], w["peak_at"], w["edge_ends"]) == ("09:55", "10:10", "09:55", "10:25")
    assert best_window([{"at": "09:40", "net_per_trade": -1}])["from"] is None
    assert best_window([]) is None


def test_tick_helpers_come_from_the_india_repo():
    assert ideas.tick_for(200) == 0.01 and ideas.tick_for(800) == 0.05 and ideas.tick_for(1500) == 0.10
    assert ideas.to_tick(1493.62, "up") == 1493.7 and ideas.to_tick(1489.18, "down") == 1489.1


def test_orb_tick_schedule():
    assert orb_tick_due(dt.datetime(2026, 11, 16, 9, 25), None) is None          # range still forming
    assert orb_tick_due(dt.datetime(2026, 11, 16, 9, 37), None) == dt.datetime(2026, 11, 16, 9, 35)
    assert orb_tick_due(dt.datetime(2026, 11, 16, 9, 38), dt.datetime(2026, 11, 16, 9, 35)) is None
    assert orb_tick_due(dt.datetime(2026, 11, 16, 14, 40), None) is None         # after the entry cutoff
    assert orb_tick_due(dt.datetime(2026, 11, 15, 10, 0), None) is None          # Sunday


def test_ideas_api(client):
    for job in ("evening_scan", "premarket_brief"):
        client.post(f"/api/jobs/{job}/run", json={"mode": "demo"})
    r = client.post("/api/ideas/scan", json={"mode": "demo", "at": "09:45"}).json()
    idea_id = r["decisions"][0]["id"]
    lst = client.get("/api/ideas?mode=demo").json()
    assert lst["count"] == 1 and lst["ideas"][0]["verdict"] == "SKIP"
    full = client.get(f"/api/ideas/{idea_id}").json()
    assert full["plan"]["qty"] > 0 and full["evidence"]
    cut = client.get(f"/api/ideas/{idea_id}/bars").json()
    after = client.get(f"/api/ideas/{idea_id}/bars?full=true").json()
    assert cut["bars"] and all(b["time"] < "2026-11-09 09:45" for b in cut["bars"])   # no look-ahead
    assert len(after["bars"]) > len(cut["bars"])
    assert client.get("/api/ideas/nope").status_code == 404
    assert client.post("/api/ideas/scan", json={"mode": "demo", "at": "nonsense"}).status_code == 422
