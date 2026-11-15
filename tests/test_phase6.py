"""Phase 6: swing ideas with backtest evidence, and paper GTT fills on daily bars."""
import csv

from backend.pipeline import swing


def test_demo_universe_is_cut_at_the_decision_date():
    folder = swing.demo_universe("2026-09-18")
    for f in folder.glob("*.csv"):
        dates = [r[0] for r in csv.reader(f.open())][1:]
        assert dates and max(dates) <= "2026-09-18", f


def test_swing_scan_records_evidenced_ideas(client):
    r = client.post("/api/swing/scan", json={"mode": "demo"}).json()
    assert r["as_of"] == "2026-09-18" and r["scanned"] >= 15 and r["decisions"]
    ideas = client.get("/api/ideas?mode=demo&setup=swing").json()["ideas"]
    assert {i["symbol"] for i in ideas} == {d["symbol"] for d in r["decisions"]}
    d = client.get(f"/api/ideas/{r['decisions'][0]['id']}").json()
    steps = {g["step"] for g in d["detail"]["gates"]}
    assert {"S0", "S1", "S2", "S3", "S4", "S5", "B1"} <= steps
    assert d["plan"]["trigger"] < d["plan"]["limit"] and d["plan"]["stop"] < d["plan"]["trigger"]
    assert d["plan"]["orders"]["gtt_entry"].startswith("GTT")
    assert "trades" in d["odds"]["backtest"]
    # Verdicts follow the scan's call (with relative strength), never contradict it with a TAKE.
    for dec in r["decisions"]:
        if r["verdicts"][dec["symbol"]] != "actionable":
            assert dec["verdict"] != "TAKE"
    # Scanning the same evening again decides nothing new.
    assert client.post("/api/swing/scan", json={"mode": "demo"}).json()["decisions"] == []


def test_paper_gtt_from_a_swing_idea(client):
    r = client.post("/api/swing/scan", json={"mode": "demo"}).json()
    uclock = next(d for d in r["decisions"] if d["symbol"] == "UCLOCK")
    t = client.post("/api/paper/gtt", json={"mode": "demo", "idea_id": uclock["id"]}).json()
    assert t["product"] == "CNC" and t["order_spec"]["kind"] == "gtt"
    # The fixture's UCLOCK crosses its 203.15 trigger on 29 Sep 2026 (after the 18 Sep decision).
    assert t["entry_at"] == "2026-09-29" and t["entry_price"] >= 203.15
    assert t["status"] in ("open", "closed")
    if t["status"] == "closed":
        assert t["costs"]["legs"]["dp"] > 0
    # Swing trades do not use up the intraday trade limit.
    acc = client.get("/api/paper/account?mode=demo&day=2026-09-18").json()
    assert acc["trades_today"] == 0
    bars = client.get("/api/daily-bars?mode=demo&symbol=UCLOCK&until=2026-09-18").json()["bars"]
    assert bars and bars[-1]["date"] <= "2026-09-18"


def test_bad_gtt_requests(client):
    assert client.post("/api/paper/gtt", json={"mode": "demo", "idea_id": "nope"}).status_code == 404
    r = client.post("/api/swing/scan", json={"mode": "demo"}).json()
    bad = client.post("/api/paper/gtt", json={"mode": "demo", "idea_id": r["decisions"][0]["id"], "stop": 999.0}).json()
    assert bad["status"] == "rejected"


def test_narrator_is_off_by_default(client):
    assert client.get("/api/health").json()["narrator"] is False
    r = client.post("/api/swing/scan", json={"mode": "demo"}).json()
    resp = client.post(f"/api/ideas/{r['decisions'][0]['id']}/narrate")
    assert resp.status_code == 503 and "off" in resp.json()["detail"]


def test_built_ui_is_served_when_present(client):
    from backend.api.app import _DIST
    if _DIST.exists():
        r = client.get("/")
        assert r.status_code == 200 and 'id="root"' in r.text
