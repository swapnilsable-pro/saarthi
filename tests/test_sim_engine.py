"""Phase 3 exit criteria for the fill engine, as properties over thousands of random sessions:
no fill outside its bar, costs exactly nse-trader-skill's charges.round_trip, every intraday
position flat by the square-off bar, no entry after the cutoff, determinism, and that a live
(partial) simulation never contradicts the final one."""
import datetime as dt
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.sim.engine import OrderSpec, Rules, simulate, validate

import charges as nse_charges  # vendored nse-common (on sys.path via backend.clock)

TICK = 0.05
DAY = "2026-11-16"


def _t(slot: int) -> str:
    t = dt.datetime(2026, 11, 16, 9, 15) + dt.timedelta(minutes=5 * slot)
    return t.strftime("%Y-%m-%d %H:%M")


@st.composite
def session(draw):
    """A full 75-bar NSE session as a tick-grid random walk with occasional gaps."""
    p = draw(st.integers(8000, 12000))                       # price in ticks (Rs 400-600)
    bars = []
    for i in range(75):
        gap = draw(st.integers(-30, 30)) if draw(st.integers(0, 9)) == 0 else 0
        o = max(200, p + gap)
        moves = draw(st.lists(st.integers(-12, 12), min_size=3, max_size=3))
        path = [o]
        for m in moves:
            path.append(max(200, path[-1] + m))
        c = path[-1]
        h, l = max(path) + draw(st.integers(0, 4)), min(path) - draw(st.integers(0, 4))
        bars.append({"time": _t(i), "o": o * TICK, "h": h * TICK, "l": max(1, l) * TICK, "c": c * TICK})
        p = c
    return [{k: (round(v, 2) if k != "time" else v) for k, v in b.items()} for b in bars]


@st.composite
def order_for(draw, bars):
    slot = draw(st.integers(0, 70))
    ref = bars[slot]["o"]
    etype = draw(st.sampled_from(["MARKET", "LIMIT", "SL-M"]))
    ticks = lambda lo, hi: draw(st.integers(lo, hi)) * TICK
    entry = round(round(ref / TICK) * TICK + ticks(-20, 20), 2)
    stop = round(entry - ticks(4, 60), 2)
    target = round(entry + ticks(4, 120), 2) if draw(st.booleans()) else None
    return OrderSpec(symbol="RAND", qty=draw(st.integers(1, 500)), entry_type=etype,
                     entry_price=None if etype == "MARKET" else entry, stop=stop, target=target,
                     placed_at=_t(slot), trail_breakeven=draw(st.booleans()), planned_entry=entry)


SETTINGS = settings(max_examples=600, deadline=None, suppress_health_check=[HealthCheck.too_slow])
RULES = Rules(tick=TICK, slippage_bps=3.0)


@SETTINGS
@given(st.data())
def test_engine_properties(data):
    bars = data.draw(session())
    o = data.draw(order_for(bars))
    res = simulate(o, bars, None, RULES)
    by_time = {b["time"]: b for b in bars}

    if validate(o, RULES):
        assert res.status == "rejected" and not res.fills
        return

    # 1. No fill outside its bar's range.
    for f in res.fills:
        b = by_time[f.time]
        assert b["l"] - 1e-9 <= f.price <= b["h"] + 1e-9, (f, b)

    # 2. No entry after the no-new-entries time; nothing still open after the session.
    if res.entry_at:
        assert res.entry_at[11:] < RULES.no_entries_after
    assert res.status in ("closed", "expired", "working")    # full-day replay: nothing left open

    if res.status == "closed":
        # 3. Every intraday position is flat by the square-off bar.
        assert res.exit_at[11:] <= RULES.square_off
        assert res.exit_at >= res.entry_at
        assert [f.kind for f in res.fills][0] == "ENTRY" and len(res.fills) == 2
        # 4. Costs are exactly nse-trader-skill's round trip; net = gross - costs.
        rt = nse_charges.round_trip(Decimal(f"{res.entry_price:.2f}"), Decimal(f"{res.exit_price:.2f}"), o.qty,
                                    product="equity_intraday")
        assert res.costs["total"] == float(rt["total"])
        assert abs(res.net_pnl - (res.gross_pnl - res.costs["total"])) < 0.011
        assert abs(res.gross_pnl - (res.exit_price - res.entry_price) * o.qty) < 0.011
        # 5. Excursions bracket the entry.
        if res.mae_r is not None:                      # R is measured from the planned risk
            assert res.mae_r <= 1e-9 <= res.mfe_r + 1e-9
        # 6. A stop exit never fills above the stop level that was live.
        if res.exit_reason == "STOP":
            assert res.exit_price <= o.stop + 1e-9 or res.exit_at == res.entry_at
        if res.exit_reason == "TARGET":
            assert o.target is not None and res.exit_price >= o.target - 1e-9

    # 7. Determinism.
    assert simulate(o, bars, None, RULES).as_dict() == res.as_dict()


@SETTINGS
@given(st.data())
def test_live_partial_runs_agree_with_the_final_run(data):
    """Re-simulating as bars arrive (the live paper path) never contradicts the end-of-day answer."""
    bars = data.draw(session())
    o = data.draw(order_for(bars))
    final = simulate(o, bars, None, RULES)
    cut = data.draw(st.integers(0, 74))
    now = (dt.datetime.strptime(bars[cut]["time"], "%Y-%m-%d %H:%M") + dt.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
    part = simulate(o, bars, now, RULES)
    if part.status == "closed":
        assert part.as_dict() == final.as_dict()
    elif part.status == "open":
        assert final.entry_at == part.entry_at and final.entry_price == part.entry_price
        assert final.exit_at is None or final.exit_at >= part.entry_at
    elif part.status == "working":
        assert final.entry_at is None or final.entry_at >= now[:16] or final.status != "closed" or final.entry_at > part.events[0]["time"]
    if part.status in ("rejected", "expired"):
        assert part.status == final.status


def test_known_cases():
    bars = [
        {"time": _t(5), "o": 100.0, "h": 101.0, "l": 99.5, "c": 100.8},
        {"time": _t(6), "o": 100.8, "h": 103.2, "l": 100.6, "c": 103.0},     # +1R reached (entry 100.5, stop 99.0)
        {"time": _t(7), "o": 103.0, "h": 103.1, "l": 99.9, "c": 100.3},      # back below entry (fill 100.00): breakeven stop
    ]
    o = OrderSpec("X", 100, "LIMIT", 100.5, 99.0, 110.0, _t(5), trail_breakeven=True)
    # Limit at 100.50: the 09:40 bar traded down to 99.50, through the limit: fill at the open 100.00.
    r = simulate(o, bars, None, RULES)
    assert r.entry_price == 100.0 and r.exit_reason == "BREAKEVEN_STOP"
    # Same bar touches both stop and target: the stop wins, flagged ambiguous.
    amb = [{"time": _t(10), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0},
           {"time": _t(11), "o": 100.0, "h": 105.0, "l": 95.0, "c": 100.0}]
    r = simulate(OrderSpec("X", 10, "MARKET", None, 98.0, 102.0, _t(10), trail_breakeven=False), amb, None, RULES)
    assert r.exit_reason == "STOP" and r.ambiguous_bars == 1
    # Square-off: an open position is closed at the open of the 15:15 bar.
    flat = [{"time": _t(i), "o": 100.0, "h": 100.2, "l": 99.9, "c": 100.0} for i in range(60, 75)]
    r = simulate(OrderSpec("X", 10, "MARKET", None, 95.0, 120.0, _t(60), trail_breakeven=False), flat, None, RULES)
    assert r.exit_reason == "SQUARE_OFF" and r.exit_at.endswith("15:15")
    # Orders placed after the cutoff are rejected; unfilled entries expire at the cutoff.
    assert simulate(OrderSpec("X", 1, "MARKET", None, 95.0, None, _t(63)), flat, None, RULES).status == "rejected"
    r = simulate(OrderSpec("X", 1, "LIMIT", 50.0, 49.0, None, _t(60)), flat, None, RULES)
    assert r.status == "expired"
