"""Phase 3: paper accounts, orders through the simulated exchange, account limits, ghost trades."""
import pytest


@pytest.fixture
def demo_idea(client):
    for job in ("evening_scan", "premarket_brief"):
        client.post(f"/api/jobs/{job}/run", json={"mode": "demo"})
    r = client.post("/api/ideas/scan", json={"mode": "demo", "at": "09:45"}).json()
    return r["decisions"][0]["id"]


def test_paper_trade_an_idea_end_to_end(client, demo_idea):
    pv = client.post("/api/paper/preview", json={"mode": "demo", "idea_id": demo_idea}).json()
    assert pv["ok"] and pv["ticket"]["entry_type"] == "LIMIT" and pv["risk"] > 0
    assert pv["estimates"]["at_stop"]["net"] < 0 < pv["estimates"]["at_target"]["net"]

    t = client.post("/api/paper/orders", json={"mode": "demo", "idea_id": demo_idea}).json()
    # The demo session is history, so the whole trade plays out at once: the DEMO breakout failed.
    assert t["status"] == "closed" and t["exit_reason"] == "STOP" and t["mode"] == "replay"
    assert t["followed_plan"] == 1 and t["net_pnl"] < t["gross_pnl"] < 0
    assert [f["kind"] for f in t["fills"]] == ["ENTRY", "STOP"]

    acc = client.get("/api/paper/account?mode=demo").json()
    assert acc["trades_today"] == 1 and acc["day_net"] == pytest.approx(t["net_pnl"])
    assert acc["equity"] == pytest.approx(200000 + t["net_pnl"])
    lst = client.get("/api/paper/trades?mode=demo").json()["trades"]
    assert [x["id"] for x in lst] == [t["id"]]
    assert client.post(f"/api/paper/trades/{t['id']}/cancel").status_code == 409   # already closed


def test_rejections_are_recorded_in_plain_language(client, demo_idea):
    bad = client.post("/api/paper/orders", json={"mode": "demo", "idea_id": demo_idea, "stop": 1500.0}).json()
    assert bad["status"] == "rejected" and "stop must be below" in bad["reject_reason"]
    late = client.post("/api/paper/orders", json={"mode": "demo", "idea_id": demo_idea,
                                                  "placed_at": "2026-11-09 14:35"}).json()
    assert late["status"] == "rejected" and "No new entries" in late["reject_reason"]
    off_grid = client.post("/api/paper/preview", json={"mode": "demo", "idea_id": demo_idea, "stop": 1489.13}).json()
    assert not off_grid["ok"] and "tick" in off_grid["reject_reason"]
    # Rejected orders do not count toward the day's trades.
    assert client.get("/api/paper/account?mode=demo").json()["trades_today"] == 0


def test_daily_limits_lock_the_account(client, demo_idea):
    for _ in range(4):
        assert client.post("/api/paper/orders", json={"mode": "demo", "idea_id": demo_idea}).json()["status"] == "closed"
    acc = client.get("/api/paper/account?mode=demo").json()
    assert acc["trades_left"] == 0 and acc["locked"]
    fifth = client.post("/api/paper/orders", json={"mode": "demo", "idea_id": demo_idea}).json()
    assert fifth["status"] == "rejected" and "limit" in fifth["reject_reason"].lower()


def test_ghost_trades_cover_every_idea_once(client, demo_idea):
    g = client.post("/api/paper/ghosts", json={"mode": "demo"}).json()
    assert g["created"] == 1 and g["ghosts"][0]["verdict"] == "SKIP" and g["ghosts"][0]["status"] == "closed"
    assert client.post("/api/paper/ghosts", json={"mode": "demo"}).json()["created"] == 0
    # Ghosts live in their own book: not in the user's trades, not in the account's P&L.
    assert client.get("/api/paper/trades?mode=demo").json()["trades"] == []
    assert len(client.get("/api/paper/trades?mode=demo&ghost=true").json()["trades"]) == 1
    assert client.get("/api/paper/account?mode=demo").json()["equity"] == 200000


def test_manual_ticket_validation(client):
    r = client.post("/api/paper/preview", json={"mode": "demo", "symbol": "DEMO"})
    assert r.status_code == 422
    r = client.post("/api/paper/orders", json={"mode": "demo", "idea_id": "nope"})
    assert r.status_code == 404


def test_orders_on_a_closed_market_are_rejected(client, demo_idea):
    r = client.post("/api/paper/orders", json={"mode": "demo", "idea_id": demo_idea, "placed_at": "2026-11-10 10:00"}).json()
    assert r["status"] == "rejected" and "does not trade" in r["reject_reason"] and "Balipratipada" in r["reject_reason"]
