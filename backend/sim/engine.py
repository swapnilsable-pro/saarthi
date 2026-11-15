"""The simulated exchange's fill engine (IMPLEMENTATION_PLAN.md §7.3). Pure and deterministic.

simulate(order, bars, now, rules) replays ONE paper order over completed 5-minute bars and
returns everything that happened. It is stateless on purpose: a live paper trade is simply
re-simulated from its order each time new bars arrive, so there is no incremental state to
drift, and a replay gives exactly the same answer as the live run did.

Rules (pessimistic wherever a 5-minute bar hides the order of events):
  * Gap: an order whose price is jumped by the bar's open fills at the open.
  * SL-M / stop: triggers when the bar trades through the trigger; fills at trigger (or a worse
    open) plus slippage = max(1 tick, slippage_bps of price), never outside the bar's range.
  * LIMIT: fills only if price traded THROUGH the limit by at least one tick (no touch fills).
  * Stop and target in the same bar: stop first (as nse-timemachine does), flagged ambiguous.
  * Entry bar: exits are checked in the same bar, stop first, so an intrabar reversal after a
    breakout entry counts against you.
  * Breakeven trail (optional): once a bar's high reaches +1R, the stop moves to the entry
    price from the NEXT bar (the india trail tool's "1R+: stop to breakeven").
  * Entries not filled by the no-new-entries time expire. Open intraday (MIS) positions are
    squared off at the open of the square-off bar (15:15 IST), like a broker would.
  * Costs come from nse-trader-skill's charges.round_trip, unchanged.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from backend import clock  # noqa: F401  puts nse-common on sys.path

import charges as nse_charges  # noqa: E402  (vendored, unmodified)

ENTRY_TYPES = ("MARKET", "LIMIT", "SL-M")


@dataclass
class Rules:
    tick: float = 0.05
    slippage_bps: float = 3.0
    no_entries_after: str = "14:30"
    square_off: str = "15:15"
    product: str = "MIS"


@dataclass
class OrderSpec:
    symbol: str
    qty: int
    entry_type: str                 # MARKET | LIMIT | SL-M
    entry_price: float | None       # limit price, or SL-M trigger; for MARKET, informational
    stop: float
    target: float | None
    placed_at: str                  # "YYYY-MM-DD HH:MM" IST; first bar considered starts at/after this
    side: str = "BUY"               # Phase 3 trades the long side only, like the ideas
    trail_breakeven: bool = True
    planned_entry: float | None = None   # what the idea planned, for slippage-vs-plan
    exit_at: str | None = None      # manual exit request: close at the open of the first bar >= this


@dataclass
class Fill:
    time: str
    price: float
    qty: int
    kind: str                       # ENTRY | STOP | TARGET | BREAKEVEN_STOP | SQUARE_OFF | MANUAL | DATA_END
    note: str = ""


@dataclass
class SimResult:
    status: str                     # working | open | closed | expired | rejected
    fills: list[Fill] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)
    exit_reason: str | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    entry_at: str | None = None
    exit_at: str | None = None
    stop_now: float | None = None
    gross_pnl: float | None = None
    costs: dict[str, Any] | None = None
    net_pnl: float | None = None
    r_multiple: float | None = None
    mae_r: float | None = None
    mfe_r: float | None = None
    bars_held: int | None = None
    ambiguous_bars: int = 0
    slippage_vs_plan: float | None = None
    last_price: float | None = None
    unrealized_pnl: float | None = None
    reject_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fills"] = [asdict(f) for f in self.fills]
        return d


# ----------------------------------------------------------------------------- helpers
def _round(x: float, tick: float, mode: str) -> float:
    """Round to the tick grid: 'up' (worse for a buyer), 'down' (worse for a seller), or nearest."""
    n = x / tick
    n = math.ceil(n - 1e-7) if mode == "up" else math.floor(n + 1e-7) if mode == "down" else round(n)
    return round(n * tick, 2)


def _slip(price: float, r: Rules) -> float:
    return max(r.tick, price * r.slippage_bps / 1e4)


def _buy_fill(raw: float, bar: dict, r: Rules) -> float:
    """Worse for a buyer (higher), on the tick grid, but never above the bar's high."""
    return min(_round(raw + _slip(raw, r), r.tick, "up"), bar["h"])


def _sell_fill(raw: float, bar: dict, r: Rules) -> float:
    """Worse for a seller (lower), on the tick grid, but never below the bar's low."""
    return max(_round(raw - _slip(raw, r), r.tick, "down"), bar["l"])


def _hm(t: str) -> str:
    return t[11:16]


def _on_grid(p: float, tick: float) -> bool:
    return abs(round(p / tick) * tick - p) < 1e-6


def validate(o: OrderSpec, r: Rules) -> str | None:
    """Broker-style rejections, in plain language. None means accepted."""
    if o.side != "BUY":
        return "Only long (BUY) paper trades are supported in this phase."
    if o.qty <= 0:
        return "Quantity must be at least 1 share."
    if o.entry_type not in ENTRY_TYPES:
        return f"Unknown order type {o.entry_type}."
    if o.entry_type != "MARKET" and (o.entry_price is None or o.entry_price <= 0):
        return "A limit or stop-market entry needs a price."
    for name, p in (("entry", o.entry_price if o.entry_type != "MARKET" else None), ("stop", o.stop),
                    ("target", o.target)):
        if p is not None and not _on_grid(p, r.tick):
            return f"The {name} price {p} is not on the ₹{r.tick} tick grid."
    ref = o.entry_price if o.entry_type != "MARKET" else o.planned_entry
    if ref is not None and o.stop >= ref:
        return "The stop must be below the entry for a long trade."
    if ref is not None and o.target is not None and o.target <= ref:
        return "The target must be above the entry for a long trade."
    if o.target is not None and o.target <= o.stop:
        return "The target must be above the stop."
    if _hm(o.placed_at) >= r.no_entries_after:
        return f"No new entries after {r.no_entries_after} IST."
    return None


# ----------------------------------------------------------------------------- the engine
def simulate(o: OrderSpec, bars: list[dict], now: str | None = None, r: Rules | None = None) -> SimResult:
    """Replay the order over bars (dicts: time 'YYYY-MM-DD HH:MM' bar START in IST, o, h, l, c).
    Only bars that have COMPLETED by `now` are used (a bar starting at t completes at t+5m)."""
    r = r or Rules()
    res = SimResult(status="working")
    why = validate(o, r)
    if why:
        res.status, res.reject_reason = "rejected", why
        res.events.append({"time": o.placed_at, "text": f"Rejected: {why}"})
        return res
    res.events.append({"time": o.placed_at, "text": f"{o.entry_type} BUY {o.qty} {o.symbol} placed"
                       + (f" at {o.entry_price:.2f}" if o.entry_price and o.entry_type != "MARKET" else "")})

    day = o.placed_at[:10]
    usable = []
    for b in sorted(bars, key=lambda b: b["time"]):
        if b["time"][:10] != day or b["time"] < o.placed_at or b.get("c") is None:
            continue
        if now is not None:
            end = (dt.datetime.strptime(b["time"], "%Y-%m-%d %H:%M") + dt.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
            if end > now:
                continue
        usable.append(b)

    stop = o.stop
    entry_px = None
    entry_i = None
    lows, highs = [], []
    be_armed = False
    for i, b in enumerate(usable):
        t = _hm(b["time"])
        # ------------------------------------------------------------ entry
        if entry_px is None:
            if t >= r.no_entries_after or t >= r.square_off:
                res.status = "expired"
                res.events.append({"time": b["time"], "text": f"Entry not filled by {r.no_entries_after}: order expired"})
                return res
            fill = None
            if o.entry_type == "MARKET":
                fill = _buy_fill(b["o"], b, r)
            elif o.entry_type == "SL-M" and b["h"] >= o.entry_price:
                fill = _buy_fill(max(b["o"], o.entry_price), b, r)
            elif o.entry_type == "LIMIT" and b["l"] <= o.entry_price - r.tick:
                fill = min(b["o"], o.entry_price)          # a limit never pays more than its price
            if fill is None:
                continue
            entry_px, entry_i = fill, i
            res.fills.append(Fill(b["time"], fill, o.qty, "ENTRY"))
            res.entry_price, res.entry_at = fill, b["time"]
            res.events.append({"time": b["time"], "text": f"Bought {o.qty} at {fill:.2f}"})
            if o.planned_entry:
                res.slippage_vs_plan = round(fill - o.planned_entry, 2)

        lows.append(b["l"])
        highs.append(b["h"])

        # ------------------------------------------------------------ manual exit / square-off
        if o.exit_at and b["time"] >= o.exit_at and i > entry_i:
            return _close(res, o, r, b, _sell_fill(b["o"], b, r), "MANUAL", lows, highs, i - entry_i + 1)
        if r.product == "MIS" and t >= r.square_off and i > entry_i:
            return _close(res, o, r, b, _sell_fill(b["o"], b, r), "SQUARE_OFF", lows, highs, i - entry_i + 1)

        # ------------------------------------------------------------ exits (stop first)
        hit_stop = b["l"] <= stop
        hit_target = o.target is not None and b["h"] >= o.target + r.tick
        if hit_stop:
            if hit_target or i == entry_i:
                res.ambiguous_bars += 1
            raw = min(b["o"], stop) if i > entry_i else stop
            kind = "BREAKEVEN_STOP" if be_armed else "STOP"
            return _close(res, o, r, b, _sell_fill(raw, b, r), kind, lows, highs, i - entry_i + 1)
        if hit_target:
            px = max(b["o"], o.target) if i > entry_i else o.target
            return _close(res, o, r, b, px, "TARGET", lows, highs, i - entry_i + 1)

        # ------------------------------------------------------------ breakeven trail (from next bar)
        if o.trail_breakeven and not be_armed and entry_px > o.stop and b["h"] >= entry_px + (entry_px - o.stop):
            be_armed, stop = True, max(stop, _round(entry_px, r.tick, "up"))
            res.events.append({"time": b["time"], "text": f"+1R reached: stop moved to breakeven {stop:.2f}"})

    # Ran out of completed bars.
    if entry_px is None:
        res.status = "working"
        return res
    last = usable[-1]
    session_over = now is None or _hm(now) >= "15:30" or now[:10] > day
    if session_over:
        return _close(res, o, r, last, last["c"], "DATA_END", lows, highs, len(usable) - entry_i)
    res.status, res.stop_now, res.last_price = "open", stop, last["c"]
    res.unrealized_pnl = round((last["c"] - entry_px) * o.qty, 2)
    risk = risk_base(o, entry_px)
    res.mae_r = round((min(lows) - entry_px) * o.qty / risk, 3) if risk else None
    res.mfe_r = round((max(highs) - entry_px) * o.qty / risk, 3) if risk else None
    return res


def risk_base(o: OrderSpec, fill: float) -> float | None:
    """Rupees at risk for R-multiples: the PLANNED risk (planned/limit/trigger entry minus the initial
    stop) times quantity. Measuring R from the plan keeps a lucky or unlucky fill from rescaling it."""
    ref = o.planned_entry or (o.entry_price if o.entry_type != "MARKET" else None) or fill
    per = ref - o.stop
    if per <= 0:
        per = fill - o.stop
    return per * o.qty if per > 0 else None


def _close(res: SimResult, o: OrderSpec, r: Rules, bar: dict, price: float, reason: str,
           lows: list[float], highs: list[float], bars_held: int) -> SimResult:
    price = round(min(max(price, bar["l"]), bar["h"]), 2)       # never outside the bar
    entry = res.entry_price
    res.fills.append(Fill(bar["time"], price, o.qty, reason))
    res.events.append({"time": bar["time"], "text": {
        "STOP": "Stopped out", "BREAKEVEN_STOP": "Stopped at breakeven", "TARGET": "Target hit",
        "SQUARE_OFF": f"Squared off at {r.square_off} (intraday)", "MANUAL": "Closed by you",
        "DATA_END": "Session data ended: closed at last price"}[reason] + f" at {price:.2f}"})
    rt = nse_charges.round_trip(Decimal(f"{entry:.2f}"), Decimal(f"{price:.2f}"), o.qty,
                                product="equity_intraday" if r.product == "MIS" else "equity_delivery")
    legs = {k: float(rt["entry"].get(k, 0) + rt["exit"].get(k, 0))
            for k in ("brokerage", "stt", "stamp", "txn", "sebi", "ipft", "gst", "dp")}
    gross = round((price - entry) * o.qty, 2)
    total = float(rt["total"])
    risk = risk_base(o, entry)
    res.status, res.exit_reason, res.exit_price, res.exit_at = "closed", reason, price, bar["time"]
    res.gross_pnl, res.costs, res.net_pnl = gross, {"total": total, "legs": legs}, round(gross - total, 2)
    res.r_multiple = round(res.net_pnl / risk, 3) if risk else None
    res.mae_r = round((min(lows) - entry) * o.qty / risk, 3) if risk else None
    res.mfe_r = round((max(highs) - entry) * o.qty / risk, 3) if risk else None
    res.bars_held = bars_held
    res.last_price = price
    return res
