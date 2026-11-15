import datetime as dt

from backend.skills.registry import registry, repo_sha


def test_every_script_exists_and_is_inside_its_repo():
    reg = registry()
    for spec in reg.tools.values():
        path = reg.script_path(spec)
        assert path.is_file(), f"{spec.id}: {path} missing"
        assert reg.repos[spec.repo].abs_path in path.parents


def test_every_tool_has_an_offline_smoke_invocation():
    for spec in registry().tools.values():
        assert spec.smoke, f"{spec.id} has no smoke args"


def test_smoke_as_of_only_on_point_in_time_tools():
    for spec in registry().tools.values():
        if spec.smoke_as_of:
            assert spec.point_in_time, f"{spec.id} has smoke_as_of but no time flag"


def test_time_flags_render():
    when = dt.datetime(2026, 11, 9, 18, 30)
    for spec in registry().tools.values():
        if spec.time_flag:
            flag, value = spec.time_flag.render(when)
            assert flag.startswith("--") and value.startswith("2026-11-09")


def test_both_repos_present_and_pinned():
    reg = registry()
    assert set(reg.repos) == {"nse", "india"}
    for key in reg.repos:
        sha = repo_sha(key)
        assert len(sha) == 40, f"{key} is not a git checkout"


def test_broker_integration_is_not_registered():
    for spec in registry().tools.values():
        assert "broker-integration" not in spec.script
