"""Daily-bar fill engine for swing (CNC / delivery) paper trades with GTT orders.

Mirrors the order the India repo's breakout planner prescribes:
  * GTT single BUY: fires when the day's high reaches the trigger and sends a LIMIT at `limit`.
    If the day opens above the limit (a gap past the chase limit) the order goes unfilled and the
    GTT is consumed - "that is the chase rule working" (breakout.py). Fill = max(open, trigger)
    plus slippage, capped at the limit and at the day's high.
  * Exits: a DAY stop-loss on the buy day, then a GTT OCO (stop / target) from the next session.
    Stop and target on the same day: the stop wins (pessimistic, same as the intraday engine).
    A gap through the stop fills at the open.
  * Time exit: sell at the close after `max_hold_days` sessions. Unfilled entries expire after
    `entry_valid_days` sessions.
  * Costs: nse-trader-skill charges.round_trip with product equity_delivery (incl. DP charge).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from backend.sim.engine import Fill, SimResult

import charges as nse_charges  # noqa: E402  vendored nse-common


@dataclass
class GttSpec:
    symbol: str
    qty: int
    trigger: float
    limit: float
    stop: float
    target: float | None
    placed_on: str                     # 'YYYY-MM-DD': first session considered is the NEXT one
    entry_valid_days: int = 20
    max_hold_days: int = 20
    kind: str = "gtt"
    planned_entry: float | None = None
    exit_on: str | None = None         # manual exit: sell at the open of the first session >= this date


@dataclass
class DailyRules:
    tick: float = 0.05
    slippage_bps: float = 5.0


def _up(x: float, t: float) -> float:
    return round(math.ceil(x / t - 1e-7) * t, 2)


def _down(x: float, t: float) -> float:
    return round(math.floor(x / t + 1e-7) * t, 2)


def validate(o: GttSpec) -> str | None:
    if o.qty <= 0:
        return "Quantity must be at least 1 share."
    if not (o.stop < o.trigger <= o.limit):
        return "Need stop < trigger <= limit for a long GTT."
    if o.target is not None and o.target <= o.trigger:
        return "The target must be above the trigger."
    return None


def simulate_daily(o: GttSpec, bars: list[dict], now: str | None = None, r: DailyRules | None = None) -> SimResult:
    """bars: dicts with date 'YYYY-MM-DD', o, h, l, c (sessions). `now` = last date whose bar is known."""
    r = r or DailyRules()
    res = SimResult(status="working")
    why = validate(o)
    if why:
        res.status, res.reject_reason = "rejected", why
        return res
    res.events.append({"time": o.placed_on, "text": f"GTT BUY {o.qty} {o.symbol}: trigger {o.trigger:.2f}, limit {o.limit:.2f}"})
    days = [b for b in sorted(bars, key=lambda b: b["date"]) if b["date"] > o.placed_on and (now is None or b["date"] <= now)]
    slip = lambda p: max(r.tick, p * r.slippage_bps / 1e4)
    entry_i = None
    lows, highs = [], []
    for i, b in enumerate(days):
        if entry_i is None:
            if i >= o.entry_valid_days:
                res.status = "expired"
                res.events.append({"time": b["date"], "text": f"GTT not triggered in {o.entry_valid_days} sessions: expired"})
                return res
            if b["h"] < o.trigger:
                continue
            if b["o"] > o.limit:
                res.status = "expired"
                res.events.append({"time": b["date"], "text": f"Gapped open at {b['o']:.2f}, above the {o.limit:.2f} limit: "
                                                              "GTT fired but went unfilled (chase rule)"})
                return res
            fill = min(_up(max(b["o"], o.trigger) + slip(o.trigger), r.tick), o.limit, b["h"])
            entry_i = i
            res.entry_price, res.entry_at = fill, b["date"]
            res.fills.append(Fill(b["date"], fill, o.qty, "ENTRY"))
            res.events.append({"time": b["date"], "text": f"GTT triggered: bought {o.qty} at {fill:.2f} (CNC)"})
            if o.planned_entry:
                res.slippage_vs_plan = round(fill - o.planned_entry, 2)
        lows.append(b["l"])
        highs.append(b["h"])
        held = i - entry_i                                # sessions after the buy day
        if o.exit_on and b["date"] >= o.exit_on and i > entry_i:
            return _close(res, o, b, max(_down(b["o"] - slip(b["o"]), r.tick), b["l"]), "MANUAL", lows, highs, held)
        hit_stop = b["l"] <= o.stop
        hit_tgt = o.target is not None and b["h"] >= o.target + r.tick and i > entry_i
        if hit_stop:
            if hit_tgt or i == entry_i:
                res.ambiguous_bars += 1
            raw = min(b["o"], o.stop) if i > entry_i else o.stop
            return _close(res, o, b, max(_down(raw - slip(raw), r.tick), b["l"]), "STOP", lows, highs, held)
        if hit_tgt:
            return _close(res, o, b, min(max(b["o"], o.target), b["h"]), "TARGET", lows, highs, held)
        if held >= o.max_hold_days:
            return _close(res, o, b, b["c"], "TIME_EXIT", lows, highs, held)
    if entry_i is None:
        return res
    last = days[-1]
    res.status, res.last_price, res.stop_now = "open", last["c"], o.stop
    res.unrealized_pnl = round((last["c"] - res.entry_price) * o.qty, 2)
    risk = (o.trigger - o.stop) * o.qty
    res.mae_r = round((min(lows) - res.entry_price) * o.qty / risk, 3)
    res.mfe_r = round((max(highs) - res.entry_price) * o.qty / risk, 3)
    res.bars_held = len(days) - 1 - entry_i
    return res


def _close(res: SimResult, o: GttSpec, b: dict, price: float, reason: str, lows, highs, held: int) -> SimResult:
    price = round(min(max(price, b["l"]), b["h"]), 2)
    entry = res.entry_price
    res.fills.append(Fill(b["date"], price, o.qty, reason))
    res.events.append({"time": b["date"], "text": {"STOP": "Stop hit", "TARGET": "Target hit", "TIME_EXIT":
                       f"Held {o.max_hold_days} sessions: sold at the close", "MANUAL": "Sold by you"}[reason] + f" at {price:.2f}"})
    rt = nse_charges.round_trip(Decimal(f"{entry:.2f}"), Decimal(f"{price:.2f}"), o.qty, product="equity_delivery")
    legs = {k: float(rt["entry"].get(k, 0) + rt["exit"].get(k, 0)) for k in ("brokerage", "stt", "stamp", "txn", "sebi", "ipft", "gst", "dp")}
    gross = round((price - entry) * o.qty, 2)
    risk = (o.trigger - o.stop) * o.qty
    res.status, res.exit_reason, res.exit_price, res.exit_at = "closed", reason, price, b["date"]
    res.gross_pnl, res.costs = gross, {"total": float(rt["total"]), "legs": legs}
    res.net_pnl = round(gross - float(rt["total"]), 2)
    res.r_multiple = round(res.net_pnl / risk, 3) if risk > 0 else None
    res.mae_r = round((min(lows) - entry) * o.qty / risk, 3) if risk > 0 else None
    res.mfe_r = round((max(highs) - entry) * o.qty / risk, 3) if risk > 0 else None
    res.bars_held, res.last_price = held, price
    return res
