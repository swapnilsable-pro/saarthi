def test_health_reports_paper_only_and_pinned_repos(client):
    h = client.get("/api/health").json()
    assert h["paper_only"] is True
    assert set(h["repos"]) == {"nse", "india"}
    assert all(len(r["sha"]) == 40 for r in h["repos"].values())


def test_list_and_get_tools(client):
    tools = client.get("/api/tools").json()
    assert len(tools) >= 20
    ids = {t["id"] for t in tools}
    assert {"nse.timemachine.run", "india.risk.size"} <= ids
    assert client.get("/api/tools/nse.scan.orb").json()["point_in_time"] is True
    assert client.get("/api/tools/nope").status_code == 404


def test_run_then_read_back_from_ledger(client):
    r = client.post("/api/tools/india.risk.rr/run", json={"use_smoke_args": True})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "ok" and run["output_json"]
    stored = client.get(f"/api/runs/{run['id']}").json()
    assert stored["tool_id"] == "india.risk.rr"
    assert any(x["id"] == run["id"] for x in client.get("/api/runs?tool_id=india.risk.rr").json())


def test_run_with_custom_args_and_as_of(client):
    body = {"args": ["--from", "2026-11-01", "--to", "2026-12-31"], "as_of": "2026-11-13 09:00"}
    run = client.post("/api/tools/india.events.range/run", json=body).json()
    assert run["status"] == "ok" and run["as_of"] == "2026-11-13 09:00"


def test_bad_inputs(client):
    assert client.post("/api/tools/india.ta.summary/run",
                       json={"args": ["--csv", "/etc/passwd"]}).status_code == 400
    assert client.post("/api/tools/india.risk.size/run",
                       json={"as_of": "2026-11-13 09:00"}).status_code == 422
    assert client.post("/api/tools/nope/run", json={}).status_code == 404
    assert client.get("/api/runs/does-not-exist").status_code == 404


def test_smoke_endpoint_subset(client):
    r = client.post("/api/smoke", json={"tool_ids": ["nse.scan.daily", "india.costs.charges"]}).json()
    assert r["ok"] is True and len(r["results"]) == 2
