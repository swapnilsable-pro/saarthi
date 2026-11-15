"""Phase 6: the daily GTT/CNC engine, as properties over random multi-week paths."""
import datetime as dt
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.sim.daily import DailyRules, GttSpec, simulate_daily, validate

import charges as nse_charges

T = 0.05


@st.composite
def path(draw):
    p, bars, d = draw(st.integers(3000, 5000)), [], dt.date(2026, 9, 1)
    for _ in range(60):
        d += dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        o = max(100, p + (draw(st.integers(-60, 60)) if draw(st.integers(0, 6)) == 0 else 0))
        pts = [o] + [max(100, o + draw(st.integers(-80, 80))) for _ in range(3)]
        h, l, c = max(pts) + draw(st.integers(0, 10)), min(pts) - draw(st.integers(0, 10)), pts[-1]
        bars.append({"date": d.isoformat(), "o": o * T, "h": h * T, "l": max(1, l) * T, "c": c * T})
        p = c
    return [{k: (round(v, 2) if k != "date" else v) for k, v in b.items()} for b in bars]


@st.composite
def gtt(draw, bars):
    ref = bars[draw(st.integers(0, 10))]["c"]
    trig = round(round(ref / T) * T + draw(st.integers(0, 40)) * T, 2)
    return GttSpec(symbol="X", qty=draw(st.integers(1, 400)), trigger=trig,
                   limit=round(trig + draw(st.integers(0, 60)) * T, 2), stop=round(trig - draw(st.integers(5, 120)) * T, 2),
                   target=round(trig + draw(st.integers(5, 300)) * T, 2) if draw(st.booleans()) else None,
                   placed_on=bars[0]["date"], entry_valid_days=draw(st.integers(1, 20)),
                   max_hold_days=draw(st.integers(1, 20)), planned_entry=trig)


@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.data())
def test_daily_engine_properties(data):
    bars = data.draw(path())
    o = data.draw(gtt(bars))
    res = simulate_daily(o, bars, None, DailyRules(tick=T))
    if validate(o):
        assert res.status == "rejected"
        return
    by = {b["date"]: b for b in bars}
    for f in res.fills:                                   # fills inside the day's range
        assert by[f.time]["l"] - 1e-9 <= f.price <= by[f.time]["h"] + 1e-9
    if res.entry_price is not None:
        assert res.entry_price <= o.limit + 1e-9          # never chases past the limit
        assert res.entry_at > o.placed_on
    if res.status == "closed":
        assert res.exit_at >= res.entry_at and res.bars_held <= o.max_hold_days
        rt = nse_charges.round_trip(Decimal(f"{res.entry_price:.2f}"), Decimal(f"{res.exit_price:.2f}"), o.qty, product="equity_delivery")
        assert res.costs["total"] == float(rt["total"])
        assert abs(res.net_pnl - (res.gross_pnl - res.costs["total"])) < 0.011
        assert res.mae_r <= 1e-9 <= res.mfe_r + 1e-9 and res.entry_price >= o.trigger - 1e-9
    assert simulate_daily(o, bars, None, DailyRules(tick=T)).as_dict() == res.as_dict()


def test_gap_above_limit_goes_unfilled():
    bars = [{"date": "2026-09-02", "o": 100, "h": 101, "l": 99, "c": 100},
            {"date": "2026-09-03", "o": 110, "h": 112, "l": 109, "c": 111}]
    r = simulate_daily(GttSpec("X", 10, 105, 106, 95, 130, "2026-09-01"), bars)
    assert r.status == "expired" and "chase" in r.events[-1]["text"]


def test_time_exit_and_dp_charge():
    bars = [{"date": f"2026-09-{d:02d}", "o": 100, "h": 101, "l": 99.5, "c": 100.5} for d in range(2, 12)]
    r = simulate_daily(GttSpec("X", 10, 100.5, 101, 95, 130, "2026-09-01", max_hold_days=3), bars)
    assert r.exit_reason == "TIME_EXIT" and r.bars_held == 3
    assert r.costs["legs"]["dp"] > 0                       # delivery sell pays the DP charge
