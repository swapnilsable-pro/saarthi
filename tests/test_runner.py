import datetime as dt

import pytest

from backend.skills.registry import registry
from backend.skills.runner import (ArgRejected, build_argv, default_config, extract_json, run_smoke,
                                   run_tool)


def test_extract_json_whole_and_embedded():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json("header line\n  [1, 2]\ntrailer") == [1, 2]
    assert extract_json("no json here") is None
    assert extract_json("") is None


def test_build_argv_appends_json_nowrite_and_time_flag():
    reg = registry()
    spec = reg.tool("nse.timemachine.run")
    argv = build_argv(reg, spec, ["--symbol", "DEMO"], dt.datetime(2026, 11, 10, 10, 0))
    assert argv[2] == "run"
    assert argv[-4:] == ["--json", "--no-write", "--now", "2026-11-10 10:00"]
    assert argv[argv.index("--now") + 1] == "2026-11-10 10:00"


def test_as_of_rejected_for_tools_without_a_time_flag():
    reg = registry()
    with pytest.raises(ValueError):
        build_argv(reg, reg.tool("india.risk.size"), [], dt.datetime(2026, 11, 10))


def test_config_is_always_paper():
    assert default_config()["paper"] is True


@pytest.mark.parametrize("bad", ["/etc/passwd", "~/.ssh/id_rsa", "../../secrets", "a/../../b"])
async def test_paths_outside_project_are_rejected(ledger, bad):
    with pytest.raises(ArgRejected):
        await run_tool("india.ta.summary", ["--csv", bad], ledger=ledger)


async def test_run_is_recorded_with_provenance(ledger):
    spec = registry().tool("nse.timemachine.run")
    rec = await run_tool(spec.id, spec.smoke, ledger=ledger, as_of=spec.smoke_as_of, purpose="test")
    assert rec["status"] == "ok", rec["stderr"]
    row = ledger.get_run(rec["id"])
    assert row["repo_sha"] and len(row["repo_sha"]) == 40
    assert row["as_of"] == "2026-11-10 10:00"
    assert row["output_json"]["symbol"] == "DEMO"
    assert row["input_hashes"], "fixture inputs should be hashed"
    assert all(not a.startswith("/") for a in row["argv"][1:]), "paths stored relative"


async def test_failing_tool_is_recorded_not_raised(ledger):
    rec = await run_tool("india.risk.size", ["--capital", "notanumber"], ledger=ledger)
    assert rec["status"] == "tool_error"
    assert ledger.get_run(rec["id"])["exit_code"] != 0


async def test_every_registered_tool_runs_offline(ledger):
    """Phase 0 exit criterion: every registered tool runs and lands in tool_runs."""
    results = await run_smoke(ledger)
    failed = {r["tool_id"]: r["stderr"][-300:] for r in results if r["status"] != "ok"}
    assert not failed, failed
    reg = registry()
    assert all(r["output_json"] is not None for r in results if reg.tool(r["tool_id"]).json_flag)
    assert len(ledger.list_runs(limit=500)) == len(registry().tools)
