import sqlite3

import pytest

RUN = {"tool_id": "x", "repo": "nse", "repo_sha": "0" * 40, "argv": ["python3", "x.py"],
       "exit_code": 0, "status": "ok", "duration_ms": 1, "output_json": {"a": 1}}


def test_round_trip(ledger):
    rid = ledger.record_run(RUN)
    row = ledger.get_run(rid)
    assert row["output_json"] == {"a": 1} and row["argv"] == ["python3", "x.py"]
    assert ledger.list_runs("x")[0]["id"] == rid


@pytest.mark.parametrize("sql", ["UPDATE tool_runs SET status='tool_error'", "DELETE FROM tool_runs"])
def test_tool_runs_are_append_only(ledger, sql):
    ledger.record_run(RUN)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.execute(sql)


@pytest.mark.parametrize("sql", ["UPDATE decisions SET verdict='TAKE'", "DELETE FROM decisions",
                                 "UPDATE evidence SET passed=0", "DELETE FROM evidence"])
def test_decision_tables_are_append_only(ledger, sql):
    ledger.execute("INSERT INTO decisions (id, session_day, decided_at, symbol, setup, verdict) "
                   "VALUES ('d1', '2026-11-10', '10:40', 'TCS', 'orb', 'SKIP')")
    ledger.execute("INSERT INTO evidence (decision_id, step, label, passed) VALUES ('d1', 'G3', 'bands', 0)")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.execute(sql)
