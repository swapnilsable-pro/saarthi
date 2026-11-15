"""Phase 5: replay simulator. Exit criterion: no bar, idea or fill after the simulated clock ever
reaches the client."""
import random

import pytest


@pytest.fixture
def sim(client):
    r = client.post("/api/sim/sessions", json={"mode": "demo", "day": "2026-11-09"})
    assert r.status_code == 200, r.text
    return r.json()


def _assert_no_lookahead(s):
    clock = s["clock"]
    for sym in s["symbols"]:
        for b in sym["bars"]:
            # a bar is visible only once it has completed: start + 5 minutes <= clock
            h, m = map(int, b["time"][11:].split(":"))
            end = f"{b['time'][:11]}{(h * 60 + m + 5) // 60:02d}:{(h * 60 + m + 5) % 60:02d}"
            assert end <= clock, (b["time"], clock)
    for i in s["ideas"]:
        assert f"{s['clock'][:11]}{i['decided_at']}" <= clock or i["decided_at"] <= s["time"]
    for t in s["trades"]:
        for e in t["events"]:
            assert e["time"] <= clock


def test_session_starts_at_the_open_with_nothing_visible(sim):
    assert sim["time"] == "09:15" and not sim["done"]
    assert all(not x["bars"] for x in sim["symbols"]) and sim["ideas"] == []
    assert sim["next_event"] == "09:30"


def test_no_lookahead_at_random_clocks(client, sim):
    rid, state = sim["id"], sim
    rng = random.Random(7)
    while not state["done"]:
        state = client.post(f"/api/sim/sessions/{rid}/advance", json={"bars": rng.randint(1, 9)}).json()
        _assert_no_lookahead(state)
    assert state["time"] == "15:30" and "scorecard" in state


def test_idea_appears_exactly_at_its_decision_moment(client, sim):
    rid = sim["id"]
    s = client.post(f"/api/sim/sessions/{rid}/advance", json={"to": "09:35"}).json()
    assert s["ideas"] == []                                   # DEMO's breakout bar closes at 09:40
    s = client.post(f"/api/sim/sessions/{rid}/advance", json={"next_event": True}).json()
    assert s["time"] == "09:40" and [i["symbol"] for i in s["ideas"]] == ["DEMO"]


def test_trading_inside_the_replay(client, sim):
    rid = sim["id"]
    client.post(f"/api/sim/sessions/{rid}/advance", json={"to": "09:40"})
    s = client.post(f"/api/sim/sessions/{rid}/orders", json={"symbol": "DEMO", "qty": 100, "entry_type": "MARKET",
                                                             "stop": 1480.0, "target": 1520.0}).json()
    assert s["trades"][0]["status"] == "working"              # the 09:40 bar has not completed yet
    s = client.post(f"/api/sim/sessions/{rid}/advance", json={"bars": 1}).json()
    t = s["trades"][0]
    assert t["status"] in ("open", "closed") and t["entry_at"] == "2026-11-09 09:40"
    s = client.post(f"/api/sim/sessions/{rid}/advance", json={"to": "15:30"}).json()
    t = s["trades"][0]
    assert t["status"] == "closed" and t["exit_at"] <= "2026-11-09 15:15"
    card = s["scorecard"]
    assert card["you"]["trades"] == 1 and card["you"]["net"] == pytest.approx(t["net_pnl"])
    assert card["hindsight"]["net"] >= max(card["you"]["net"], card["every_idea"]["net"])
    # Replay trades never touch the user's paper account or books.
    assert client.get("/api/paper/account?mode=demo").json()["trades_today"] == 0
    assert client.get("/api/paper/trades?mode=demo").json()["trades"] == []


def test_surprise_hides_names_until_the_close(client):
    s = client.post("/api/sim/sessions", json={"mode": "demo", "surprise": True}).json()
    assert s["day"] is None and s["symbols"][0]["symbol"] == "STOCK A" and s["symbols"][0]["real"] is None
    end = client.post(f"/api/sim/sessions/{s['id']}/advance", json={"to": "15:30"}).json()
    assert end["day"] and end["symbols"][0]["symbol"] == "DEMO"


def test_clock_only_moves_forward_and_bad_days_are_refused(client, sim):
    rid = sim["id"]
    client.post(f"/api/sim/sessions/{rid}/advance", json={"to": "11:00"})
    assert client.post(f"/api/sim/sessions/{rid}/advance", json={"to": "10:00"}).status_code == 409
    assert client.post("/api/sim/sessions", json={"mode": "demo", "day": "2026-08-14"}).status_code == 409
