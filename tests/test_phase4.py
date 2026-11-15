"""Phase 4: batch replay, history, performance books, calibration and gate value (demo, offline)."""
import pytest

from backend.pipeline import perf
from backend.pipeline.batch import replay


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    import asyncio
    from backend.ledger.db import Ledger
    L = Ledger(tmp_path_factory.mktemp("p4") / "l.db")
    summary = asyncio.run(replay(L, "demo", last=40))
    yield L, summary
    L.close()


def test_replay_covers_twenty_plus_sessions(replayed):
    L, s = replayed
    assert s["days"] == 40 and s["ideas"] >= 20 and s["ghosts"] == s["ideas"]
    # Every idea's Time Machine run only saw sessions before its own day.
    for d in L.list_decisions("demo", limit=1000):
        tm = L.get_run(d["odds"]["run_id"])
        assert tm["as_of"].startswith(d["session_day"]) and tm["as_of"][11:] == d["plan"]["entry_at"]
        assert (d.get("detail") or {}).get("origin") == "batch"


def test_replay_is_idempotent(replayed):
    import asyncio
    L, s = replayed
    again = asyncio.run(replay(L, "demo", last=40))
    assert again["ideas"] == 0 and again["ghosts"] == 0


def test_books_and_metrics(replayed):
    L, _ = replayed
    all_ = perf.stats(L, "demo", "all")
    assert all_["trades"] >= 20 and all_["sessions"] >= 20
    assert all_["net"] == pytest.approx(sum(p["net"] for p in all_["equity_curve"]))
    assert all_["equity_curve"][-1]["equity"] == pytest.approx(all_["net"])
    assert all_["max_drawdown"] <= 0
    assert sum(b["n"] for b in all_["r_histogram"]) == all_["trades"]
    assert sum(g["n"] for g in all_["by_entry_hour"]) == all_["trades"]
    assert perf.stats(L, "demo", "mine")["trades"] == 0     # ghosts never leak into the user's book


def test_calibration_and_gate_value(replayed):
    L, _ = replayed
    c = perf.calibration(L, "demo")
    assert c["n"] >= 20 and 0 <= c["brier"] <= 1
    assert sum(b["n"] for b in c["buckets"]) == c["n"]
    assert all(0 <= b["observed"] <= 1 for b in c["buckets"])
    g = perf.gate_value(L, "demo")
    assert g["total_ideas"] == perf.stats(L, "demo", "all")["trades"]


def test_history_api(client):
    r = client.post("/api/replay/batch", json={"mode": "demo", "last": 25}).json()
    assert r["days"] == 25
    h = client.get("/api/history?mode=demo").json()
    assert len(h["days"]) == 25
    day = next(d["day"] for d in h["days"] if d["ideas"])
    dd = client.get(f"/api/history/{day}?mode=demo").json()
    assert dd["ideas"] and dd["ideas"][0]["ghost"]["status"] in ("closed", "expired")
    assert [e["kind"] for e in dd["events"]][0] == "job"
    p = client.get("/api/performance?mode=demo&book=all").json()
    assert p["stats"]["trades"] >= 10 and p["calibration"]["n"] >= 10 and p["gates"]["rows"]
    assert set(p["books"]) == {"mine", "take", "all"}


def test_today_shows_the_latest_session_not_the_latest_replayed_day(client):
    for job in ("evening_scan", "premarket_brief"):
        client.post(f"/api/jobs/{job}/run", json={"mode": "demo"})
    client.post("/api/replay/batch", json={"mode": "demo", "last": 3})      # prepares older days afterwards
    assert client.get("/api/today?mode=demo").json()["session_day"] == "2026-11-09"
