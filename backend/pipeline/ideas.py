"""Intraday opening-range-breakout ideas (IMPLEMENTATION_PLAN.md §6.1).

For each breakout the nse-trader-skill scanner reports, run a fixed sequence of gates and
calculations. Every market number comes from a repo tool run (recorded in tool_runs); Saarthi
only chooses arguments from the user's settings, compares tool outputs with those settings,
and ranks. Each idea - TAKE, WATCH or SKIP - is written to the append-only decisions ledger
with one evidence row per step.

Plan geometry that is a *choice*, not a market fact (which stop method, which R multiple for
the target) comes from SETTINGS and is shown on screen. The Time Machine judges every choice.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import json
import sys
from decimal import Decimal
from typing import Any

from backend import bars, clock
from backend.ledger.db import Ledger
from backend.pipeline import brief
from backend.skills.registry import ROOT
from backend.skills.runner import default_config, run_tool

import charges as nse_charges  # noqa: E402  vendored nse-common/charges.py (clock put it on sys.path)
import nsecal                  # noqa: E402

PIPELINE_VERSION = "orb-1.0"

# Load the India repo's breakout planner for its NSE tick-slab helpers (read-only import; the
# module loads its own siblings under unique names, so nothing collides with nse-common).
_spec = importlib.util.spec_from_file_location(
    "saarthi_india_breakout", ROOT / "vendor/claude-trading-skills-india/skills/breakout-planner/scripts/breakout.py")
india_breakout = importlib.util.module_from_spec(_spec)
sys.modules["saarthi_india_breakout"] = india_breakout
_spec.loader.exec_module(india_breakout)

SETTINGS: dict[str, Any] = {
    "capital_inr": 200000,
    "risk_per_trade_pct": 0.5,
    "max_alloc_pct": 100,            # intraday: one position may use the whole (unlevered) capital
    "cost_pct_intraday": 0.05,       # round-trip cost % hint for the India sizing tool
    "min_reward_risk": 1.5,          # net, after costs (nse config default, and why)
    "min_p_target": 0.30,            # Time Machine probability the target is hit first
    "stop_methods": ["or_mid", "or_low"],
    "target_r": [1.5, 2.0, 3.0],
    "trials": 10000,
    "scan_trials": 2000,             # per plan variant and per timing slot
    "timing_step_min": 15,
    "seed": 19,
    "orb_minutes": 15,
    "orb_max_symbols": 10,           # live: Yahoo throttles; keep this small
    "no_entries_after": "14:30",
    "flat_by": "15:15",
    "broker": "zerodha",
}

VERDICT_RULE = (
    "TAKE when every required check passes: G0 session and entry window, G1 market regime not in "
    "correction, G2 no high-impact event, G3 not ASM / band-locked, G4 no results today, G5 a 5-minute "
    "close above the opening-range high, C3 net reward:risk at least {min_rr}, C6 positive net expectancy "
    "after costs, and P(target first) at least {min_p:.0%}. Any failed check makes it SKIP (the first failure "
    "is the headline). Missing data on a required check caps it at WATCH. G6 (exhaustion) is advisory when "
    "daily data is unavailable. Checks marked n/a do not apply to the instrument (e.g. a synthetic test series)."
)

STOP_LABEL = {"or_mid": "Opening-range midpoint", "or_low": "Opening-range low"}


# ------------------------------------------------------------------------------------ helpers
def tick_for(price: float) -> float:
    return india_breakout.tick_for(price)


def to_tick(price: float, mode: str) -> float:
    return india_breakout.to_tick(price, None, mode)


def _hm(t: dt.datetime) -> str:
    return t.strftime("%H:%M")


def _parse_hm(day: dt.date, hm: str) -> dt.datetime:
    h, m = map(int, hm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m))


class Ctx:
    """One scan's context: mode, clock, the bar folder, Today's evidence and the run helper."""

    def __init__(self, ledger: Ledger, mode: str, at: dt.datetime, settings: dict):
        self.ledger, self.mode, self.at, self.s = ledger, mode, at, settings
        self.day = at.date()
        self.today = brief.today(ledger, mode, self.day.isoformat())
        self.watch = {r["symbol"]: r for r in self.today["watchlist"]["rows"]}
        self.results_today = {r.get("symbol") for r in self.today["watchlist"]["results_calendar"]
                              if (r.get("date") or "")[:10] == self.day.isoformat()}
        self.have_evening = self.today["jobs"]["evening_scan"] is not None
        self.config = default_config() | {"capital_inr": settings["capital_inr"],
                                          "risk_per_trade_pct": settings["risk_per_trade_pct"],
                                          "min_reward_risk": settings["min_reward_risk"],
                                          "no_entries_after": settings["no_entries_after"],
                                          "flat_by": settings["flat_by"]}
        self.sem = asyncio.Semaphore(4)

    async def run(self, tool_id: str, args: list[str], as_of: dt.datetime | None = None) -> dict:
        async with self.sem:
            return await run_tool(tool_id, args, ledger=self.ledger, config=self.config,
                                  as_of=as_of.strftime("%Y-%m-%d %H:%M") if as_of else None,
                                  purpose=f"idea:{self.mode}")


def _gate(step: str, label: str, status: str, summary: str, run_id: str | None = None,
          required: bool = True) -> dict:
    return {"step": step, "label": label, "status": status, "summary": summary, "run_id": run_id,
            "required": required, "passed": {"pass": True, "fail": False}.get(status)}


# ------------------------------------------------------------------------------------ gates
def context_gates(ctx: Ctx, sym: str, entry_at: dt.datetime) -> list[dict]:
    t, s = ctx.today, ctx.s
    out = []
    sess = nsecal.session(ctx.day) if nsecal.covered(ctx.day) else None
    cutoff = _parse_hm(ctx.day, s["no_entries_after"])
    if not sess:
        out.append(_gate("G0", "Session and entry window", "fail", "No NSE session on this day."))
    elif entry_at > cutoff:
        out.append(_gate("G0", "Session and entry window", "fail",
                         f"Entry at {_hm(entry_at)} is after the {s['no_entries_after']} cutoff."))
    else:
        out.append(_gate("G0", "Session and entry window", "pass",
                         f"Entry at {_hm(entry_at)}, before the {s['no_entries_after']} cutoff."))

    mood = t["mood"]
    reg_run = next((f["run_id"] for f in mood["factors"] if f["step"] == "regime"), None)
    if mood["level"] == "unknown":
        out.append(_gate("G1", "Market regime", "no_data", "Pre-market brief has not run.", None))
    elif mood["level"] == "stand_aside":
        out.append(_gate("G1", "Market regime", "fail", f"Regime is {mood['regime']['label']}: stand aside.", reg_run))
    else:
        out.append(_gate("G1", "Market regime", "pass",
                         f"{mood['regime']['label']}; mood {mood['level'].replace('_', ' ')}.", reg_run))

    ev = t["events"]
    if not ev.get("run_id"):
        out.append(_gate("G2", "Event risk", "no_data", "Event calendar has not run."))
    else:
        out.append(_gate("G2", "Event risk", "fail" if ev["gate"]["blocked"] else "pass", ev["gate"]["reason"], ev["run_id"]))

    row = ctx.watch.get(sym)
    if sym in bars.SYNTHETIC:
        out.append(_gate("G3", "Tradable (bands, ASM)", "na",
                         "Not applicable: a synthetic test instrument has no exchange price band or surveillance."))
        out.append(_gate("G4", "Results day", "na", "Not applicable: a synthetic test instrument reports no results."))
        return out
    if row:
        asm = [f for f in row["flags"] if f["kind"] == "asm"]
        band = [f for f in row["flags"] if f["kind"] == "band"]
        if asm:
            out.append(_gate("G3", "Tradable (bands, ASM)", "fail", asm[0]["text"] + ": no clean intraday trade.",
                             row["evidence"].get("daily")))
        else:
            out.append(_gate("G3", "Tradable (bands, ASM)", "pass",
                             (band[0]["text"] + "; stop sits well inside it.") if band else "No ASM, no tight price band.",
                             row["evidence"].get("daily")))
    else:
        out.append(_gate("G3", "Tradable (bands, ASM)", "no_data",
                         "Not on the evening watchlist, so its band and ASM status were not checked."))

    if not ctx.have_evening:
        out.append(_gate("G4", "Results day", "no_data", "Results calendar has not run."))
    else:
        rid = _step_run(ctx, "evening_scan", "results")
        if sym in ctx.results_today:
            out.append(_gate("G4", "Results day", "fail", "Board meeting for results today: gap risk.", rid))
        else:
            out.append(_gate("G4", "Results day", "pass", "No results scheduled for this session.", rid))
    return out


def _step_run(ctx: Ctx, job: str, step: str) -> str | None:
    j = ctx.ledger.latest_job(job, ctx.mode, ctx.day.isoformat())
    return ((j or {}).get("steps", {}).get(step) or {}).get("tool_run_id")


async def exhaustion_gate(ctx: Ctx, sym: str) -> dict:
    if ctx.mode == "demo":
        return _gate("G6", "Not exhausted (climax check)", "no_data",
                     "Demo instrument has no daily history for the climax check.", required=False)
    prev = nsecal.prev_session_day(ctx.day)
    run = await ctx.run("india.exhaustion.climax", ["--symbols", sym, "--min-turnover-cr", "0"],
                        as_of=dt.datetime.combine(prev, dt.time(18, 0)))
    res = ((run.get("output_json") or {}).get("results") or [])
    if run["status"] != "ok" or not res:
        return _gate("G6", "Not exhausted (climax check)", "no_data", "Daily data unavailable for the climax check.",
                     run["id"], required=False)
    r = res[0]
    if r.get("stage") == "climax":
        return _gate("G6", "Not exhausted (climax check)", "fail",
                     f"Buying-climax read (score {r.get('score')}): the move may be spent.", run["id"])
    return _gate("G6", "Not exhausted (climax check)", "pass",
                 f"No climax (stage {r.get('stage') or 'none'}, score {r.get('score')}).", run["id"])


# ------------------------------------------------------------------------------------ plan + odds
async def size(ctx: Ctx, entry: float, stop: float) -> dict:
    s = ctx.s
    return await ctx.run("india.risk.size", [
        "--capital", str(s["capital_inr"]), "--risk-pct", str(s["risk_per_trade_pct"]),
        "--entry", f"{entry:.2f}", "--stop", f"{stop:.2f}", "--cost-pct", str(s["cost_pct_intraday"]),
        "--max-alloc-pct", str(s["max_alloc_pct"])])


async def timemachine(ctx: Ctx, sym: str, folder: str, entry: float, stop: float, target: float, qty: int,
                      at: dt.datetime, trials: int) -> dict:
    return await ctx.run("nse.timemachine.run", [
        "--offline", folder, "--symbol", sym, "--entry", f"{entry:.2f}", "--stop", f"{stop:.2f}",
        "--target", f"{target:.2f}", "--qty", str(qty), "--at", _hm(at), "--flat-by", ctx.s["flat_by"],
        "--trials", str(trials), "--seed", str(ctx.s["seed"])], as_of=at)


def _tm_view(run: dict) -> dict | None:
    o = run.get("output_json")
    if run["status"] != "ok" or not o:
        return None
    b, h = o["bootstrap"], o["history"]
    return {
        "p_target": b["p"]["target"], "p_stop": b["p"]["stop"], "p_neither": b["p"]["neither"],
        "net_per_trade": b["net_per_trade"], "gross_per_trade": b["gross_per_trade"],
        "ambiguous_bars": b["ambiguous_bars"], "trials": o["trials"],
        "history": {"p_target": h["p"]["target"], "p_stop": h["p"]["stop"], "p_neither": h["p"]["neither"],
                    "sessions_fired": h.get("sessions_fired"), "net_per_trade": h["net_per_trade"],
                    "counts": h["counts"]},
        "net_rr": o["reward_risk"]["net"], "gross_rr": o["reward_risk"]["gross"],
        "breakeven_per_share": o["costs"]["breakeven_per_share"], "costs": o["costs"],
        "sessions": o["sessions"], "synthetic_bars": o.get("synthetic_bars"), "bar_origin": o.get("bar_origin"),
        "run_id": run["id"],
    }


def cost_breakdown(entry: float, exit_price: float, qty: int) -> dict:
    rt = nse_charges.round_trip(Decimal(f"{entry:.2f}"), Decimal(f"{exit_price:.2f}"), qty, product="equity_intraday")
    legs = {}
    for k in ("brokerage", "stt", "stamp", "txn", "sebi", "ipft", "gst"):
        legs[k] = float(rt["entry"].get(k, 0) + rt["exit"].get(k, 0))
    return {"total": float(rt["total"]), "legs": legs}


async def build_idea(ctx: Ctx, brk: dict, folder: str, orb_run_id: str) -> dict:
    s, sym = ctx.s, brk["symbol"]
    hi, lo, mid = brk["range_high"], brk["range_low"], brk["range_mid"]
    bar_start = _parse_hm(ctx.day, brk["at"])
    entry_at = bar_start + dt.timedelta(minutes=5)       # the confirming bar has closed
    gates = context_gates(ctx, sym, entry_at)
    gates.append(_gate("G5", "Opening-range breakout", "pass",
                       f"5-minute bar from {brk['at']} closed at {brk['close']:.2f}, above the opening-range "
                       f"high {hi:.2f} (+{brk['over_pct']:.2f}%).", orb_run_id))

    tick = tick_for(hi)
    entry = to_tick(max(hi + tick, brk["close"]), "up")
    stops = {"or_mid": to_tick(mid, "down"), "or_low": to_tick(lo - tick, "down")}
    stops = {k: v for k, v in stops.items() if k in s["stop_methods"] and v < entry}

    exh_task = asyncio.create_task(exhaustion_gate(ctx, sym))
    size_runs = dict(zip(stops, await asyncio.gather(*(size(ctx, entry, st) for st in stops.values()))))

    variants: list[dict] = []
    tasks = []
    for method, stop in stops.items():
        sz = size_runs[method].get("output_json") or {}
        qty = int(sz.get("units") or 0)
        if qty <= 0:
            continue
        for k in s["target_r"]:
            target = to_tick(entry + k * (entry - stop), "down")
            variants.append({"stop_method": method, "stop": stop, "target_r": k, "target": target, "qty": qty,
                             "size_run_id": size_runs[method]["id"]})
            tasks.append(timemachine(ctx, sym, folder, entry, stop, target, qty, entry_at, s["scan_trials"]))
    for v, run in zip(variants, await asyncio.gather(*tasks)):
        v["odds"] = _tm_view(run)
        v["run_id"] = run["id"]

    scored = [v for v in variants if v["odds"]]
    eligible = [v for v in scored if v["odds"]["net_rr"] >= s["min_reward_risk"]] or scored
    chosen = max(eligible, key=lambda v: v["odds"]["net_per_trade"]) if eligible else None
    gates.append(await exh_task)

    if not chosen:
        gates.append(_gate("C6", "Odds (Time Machine)", "no_data",
                           "The Time Machine could not run (not enough intraday history)."))
        return _finish(ctx, sym, brk, entry, entry_at, None, None, None, [], variants, gates, None)

    # Final, full-precision run on the chosen plan, plus sizing and cost cross-checks.
    stop, target, qty = chosen["stop"], chosen["target"], chosen["qty"]
    t1 = to_tick(entry + 1.0 * (entry - stop), "down")
    final_run, rr_run, india_cost_run, trail1, trail2 = await asyncio.gather(
        timemachine(ctx, sym, folder, entry, stop, target, qty, entry_at, s["trials"]),
        ctx.run("india.risk.rr", ["--entry", f"{entry:.2f}", "--stop", f"{stop:.2f}", "--target", f"{target:.2f}",
                                  "--win-rate", f"{100 * chosen['odds']['p_target']:.1f}",
                                  "--cost-pct", str(s["cost_pct_intraday"])]),
        ctx.run("india.costs.charges", ["--segment", "intraday", "--buy", f"{entry:.2f}", "--sell", f"{target:.2f}",
                                        "--qty", str(qty), "--broker", s["broker"]]),
        # One tick past each rung: the trail tool moves the stop once price is strictly beyond +1R / +2R.
        ctx.run("india.risk.trail", ["--entry", f"{entry:.2f}", "--stop", f"{stop:.2f}",
                                     "--highest-close", f"{t1 + tick:.2f}"]),
        ctx.run("india.risk.trail", ["--entry", f"{entry:.2f}", "--stop", f"{stop:.2f}",
                                     "--highest-close", f"{to_tick(entry + 2 * (entry - stop), 'down') + tick:.2f}"]),
    )
    odds = _tm_view(final_run) or chosen["odds"]

    # Timing curve: the same plan entered at each later slot (the Time Machine conditions on time of day).
    slots, t = [], entry_at
    cutoff = _parse_hm(ctx.day, s["no_entries_after"])
    while t <= cutoff:
        slots.append(t)
        t += dt.timedelta(minutes=s["timing_step_min"])
    curve_runs = await asyncio.gather(*(timemachine(ctx, sym, folder, entry, stop, target, qty, sl, s["scan_trials"])
                                        for sl in slots))
    curve = []
    for sl, run in zip(slots, curve_runs):
        v = _tm_view(run)
        if v:
            curve.append({"at": _hm(sl), "net_per_trade": v["net_per_trade"], "p_target": v["p_target"],
                          "p_stop": v["p_stop"], "run_id": run["id"]})
    window = best_window(curve)

    sz = (size_runs[chosen["stop_method"]].get("output_json") or {})
    rr = rr_run.get("output_json") or {}
    india_cost = (india_cost_run.get("output_json") or {}).get("total_charges")
    costs = {"at_target": cost_breakdown(entry, target, qty), "at_stop": cost_breakdown(entry, stop, qty),
             "india_at_target": india_cost, "india_run_id": india_cost_run["id"]}
    costs["cross_check_delta"] = None if india_cost is None else round(costs["at_target"]["total"] - india_cost, 2)

    # Calculation gates.
    gates.append(_gate("C3", "Net reward:risk after costs", "pass" if odds["net_rr"] >= s["min_reward_risk"] else "fail",
                       f"{odds['net_rr']:.2f} after costs (gross {odds['gross_rr']:.2f}); minimum {s['min_reward_risk']}.",
                       final_run["id"]))
    ne = odds["net_per_trade"]
    gates.append(_gate("C6", "Net expectancy after costs", "pass" if ne > 0 else "fail",
                       (f"Average outcome {'+' if ne >= 0 else '−'}₹{abs(ne):,.0f} per trade after costs over "
                        f"{odds['trials']:,} simulated sessions" + ("." if ne > 0 else ": the plan loses money on average.")),
                       final_run["id"]))
    gates.append(_gate("C6b", "Chance the target comes first", "pass" if odds["p_target"] >= s["min_p_target"] else "fail",
                       f"{odds['p_target']:.0%} target first, {odds['p_stop']:.0%} stop first, "
                       f"{odds['p_neither']:.0%} neither by {s['flat_by']}; minimum {s['min_p_target']:.0%}.",
                       final_run["id"]))

    plan = {
        "entry": entry, "trigger": to_tick(hi + tick, "up"), "entry_at": _hm(entry_at), "tick": tick,
        "stop": stop, "stop_method": chosen["stop_method"], "stop_label": STOP_LABEL[chosen["stop_method"]],
        "target": target, "target_r": chosen["target_r"], "t1": t1, "qty": qty,
        "risk_per_share": round(entry - stop, 2), "risk_amount": round(qty * (entry - stop), 2),
        "position_value": round(qty * entry, 2), "risk_pct_of_capital": sz.get("risk_pct_of_capital"),
        "sizing_notes": sz.get("notes") or [], "size_run_id": chosen["size_run_id"],
        "range": {"high": hi, "low": lo, "mid": mid, "minutes": s["orb_minutes"]},
        "no_entries_after": s["no_entries_after"], "flat_by": s["flat_by"],
        "best_window": window,
        "exit_ladder": [
            {"at": f"+1R ({t1:.2f})", "action": (trail1.get("output_json") or {}).get("stage"),
             "stop": (trail1.get("output_json") or {}).get("recommended_stop"), "run_id": trail1["id"]},
            {"at": f"+2R ({to_tick(entry + 2 * (entry - stop), 'down'):.2f})",
             "action": (trail2.get("output_json") or {}).get("stage"),
             "stop": (trail2.get("output_json") or {}).get("recommended_stop"), "run_id": trail2["id"]},
            {"at": f"Target {target:.2f}", "action": "Take profit (bracket target)", "stop": None, "run_id": None},
            {"at": s["flat_by"], "action": "Square off whatever is left (MIS)", "stop": None, "run_id": None},
        ],
        "time_stop": None,
        "rr_tool": {"expectancy_R": rr.get("expectancy_R"), "breakeven_win_rate_pct": rr.get("breakeven_win_rate_pct"),
                    "verdict": rr.get("verdict"), "run_id": rr_run["id"]},
    }
    return _finish(ctx, sym, brk, entry, entry_at, plan, odds, costs, curve, variants, gates, final_run["id"])


def best_window(curve: list[dict]) -> dict | None:
    """The run of entry slots, around the best one, where net expectancy stays positive and within
    80% of its peak. Pure bookkeeping over Time Machine outputs."""
    if not curve:
        return None
    peak_i = max(range(len(curve)), key=lambda i: curve[i]["net_per_trade"])
    peak = curve[peak_i]["net_per_trade"]
    if peak <= 0:
        return {"from": None, "to": None, "peak_at": curve[peak_i]["at"], "peak": peak,
                "note": "No entry time has positive net expectancy for this plan."}
    keep = lambda i: curve[i]["net_per_trade"] > 0 and curve[i]["net_per_trade"] >= 0.8 * peak
    a = b = peak_i
    while a - 1 >= 0 and keep(a - 1):
        a -= 1
    while b + 1 < len(curve) and keep(b + 1):
        b += 1
    last_pos = max((i for i, c in enumerate(curve) if c["net_per_trade"] > 0), default=None)
    return {"from": curve[a]["at"], "to": curve[b]["at"], "peak_at": curve[peak_i]["at"], "peak": peak,
            "edge_ends": curve[last_pos]["at"] if last_pos is not None else None}


def verdict_of(gates: list[dict]) -> tuple[str, str | None, str]:
    for g in gates:
        if g["required"] and g["status"] == "fail":
            return "SKIP", g["step"], f"{g['label']}: {g['summary']}"
    for g in gates:
        if g["status"] == "fail":                               # advisory failure (G6 with data)
            return "SKIP", g["step"], f"{g['label']}: {g['summary']}"
    missing = [g for g in gates if g["required"] and g["status"] == "no_data"]
    if missing:
        return "WATCH", missing[0]["step"], f"Waiting on data: {missing[0]['label']}. {missing[0]['summary']}"
    return "TAKE", None, "Every required check passed."


def score_of(ctx: Ctx, sym: str, plan: dict | None, odds: dict | None) -> tuple[float, list[dict]]:
    if not plan or not odds:
        return 0.0, []
    exp_r = odds["net_per_trade"] / plan["risk_amount"] if plan["risk_amount"] else 0
    level = ctx.today["mood"]["level"]
    row = ctx.watch.get(sym) or {}
    deliv = row.get("delivery_pct")
    terms = [
        {"term": "Net expectancy", "weight": 40, "value": max(0.0, min(1.0, exp_r / 0.3)),
         "why": f"{exp_r:+.2f}R per trade (full marks at +0.3R)"},
        {"term": "P(target first)", "weight": 25, "value": odds["p_target"], "why": f"{odds['p_target']:.0%}"},
        {"term": "Market mood", "weight": 15, "value": {"go": 1, "caution": 0.5}.get(level, 0), "why": level},
        {"term": "Breakout strength", "weight": 10, "value": None, "why": "relative strength: not measured intraday yet"},
        {"term": "Delivery / deals", "weight": 10,
         "value": None if deliv is None else (1.0 if (deliv >= 50 or row.get("deals")) else 0.4),
         "why": "no daily data" if deliv is None else f"delivery {deliv:.0f}%" + (", deal print" if row.get("deals") else "")},
    ]
    got = sum(t["weight"] * t["value"] for t in terms if t["value"] is not None)
    possible = sum(t["weight"] for t in terms if t["value"] is not None)
    return round(100 * got / possible, 1) if possible else 0.0, terms


def narrative(sym: str, verdict: str, reason: str, plan: dict | None, odds: dict | None, mood: dict) -> str:
    if not plan or not odds:
        return f"{sym} broke out of its opening range, but the Time Machine could not judge the trade. {reason}"
    hist = odds["history"]
    w = plan["best_window"] or {}
    when = (f"The edge is best for entries between {w['from']} and {w['to']}." if w.get("from")
            else "No entry time showed a positive edge after costs.")
    lead = {"TAKE": "Every check passed.", "WATCH": "Close, but one check is waiting on data.",
            "SKIP": "Saarthi would pass on this one."}[verdict]
    return (
        f"{lead} {sym} closed above its first-15-minute high at {plan['entry_at']}. "
        f"Buying at {plan['entry']:.2f} with a stop at {plan['stop']:.2f} ({plan['stop_label'].lower()}) risks "
        f"₹{plan['risk_amount']:,.0f} on {plan['qty']} shares. Across {odds['trials']:,} simulated rests-of-session the "
        f"target at {plan['target']:.2f} came first {odds['p_target']:.0%} of the time, and on the "
        f"{hist['sessions_fired'] or 0} past sessions where this exact rule fired it came first "
        f"{hist['p_target']:.0%} of the time. After charges the average outcome is "
        f"{'+' if odds['net_per_trade'] >= 0 else '−'}₹{abs(odds['net_per_trade']):,.0f} a trade. {when} Market mood: {mood['level'].replace('_', ' ')}."
        + ("" if verdict == "TAKE" else f" Deciding factor - {reason}")
    )


def _finish(ctx, sym, brk, entry, entry_at, plan, odds, costs, curve, variants, gates, final_run_id) -> dict:
    verdict, failed, reason = verdict_of(gates)
    score, terms = score_of(ctx, sym, plan, odds)
    decision = {
        "session_day": ctx.day.isoformat(), "decided_at": _hm(entry_at), "symbol": sym, "setup": "orb",
        "verdict": verdict, "first_failed_gate": failed, "score": score, "mode": ctx.mode,
        "as_of": ctx.at.strftime("%Y-%m-%d %H:%M"), "pipeline_version": PIPELINE_VERSION,
        "plan": plan, "odds": odds, "costs": costs,
        "config_snapshot": ctx.s,
        "detail": {
            "reason": reason, "gates": gates, "variants": variants, "timing": curve, "score_terms": terms,
            "breakout": brk, "narrative": narrative(sym, verdict, reason, plan, odds, ctx.today["mood"]),
            "verdict_rule": VERDICT_RULE.format(min_rr=ctx.s["min_reward_risk"], min_p=ctx.s["min_p_target"]),
            "mood": {"level": ctx.today["mood"]["level"], "label": (ctx.today["mood"]["regime"] or {}).get("label")},
            "synthetic": bool(odds and odds.get("synthetic_bars")) or sym in bars.SYNTHETIC,
            "origin": getattr(ctx, "origin", "scan"),
            "name": (ctx.watch.get(sym) or {}).get("name") or ("Synthetic test instrument" if sym == "DEMO" else None),
        },
    }
    evidence = [{"step": g["step"], "label": g["label"], "passed": g["passed"], "summary": g["summary"],
                 "run_id": g["run_id"]} for g in gates]
    decision["id"] = ctx.ledger.record_decision(decision, evidence)
    return decision


# ------------------------------------------------------------------------------------ scan entrypoint
def _symbols(ctx: Ctx, symbols: list[str] | None) -> list[str]:
    if symbols:
        return [s.strip().upper() for s in symbols if s.strip()]
    if ctx.mode == "demo":
        return bars.DEMO_SYMBOLS
    rows = sorted(ctx.today["watchlist"]["rows"], key=lambda r: -(r.get("turnover_cr") or 0))
    return [r["symbol"] for r in rows[: ctx.s["orb_max_symbols"]]]


async def scan_and_decide(ledger: Ledger, mode: str, at: dt.datetime, *, symbols: list[str] | None = None,
                          settings: dict | None = None, folder: str | None = None, origin: str = "scan") -> dict:
    s = SETTINGS | (settings or {})
    ctx = Ctx(ledger, mode, at, s)
    syms = _symbols(ctx, symbols)
    if not syms:
        return {"as_of": at.strftime("%Y-%m-%d %H:%M"), "error": "No symbols: run the evening scan first.",
                "breakouts": [], "decisions": []}

    fetch_errors, throttled = {}, None
    if mode == "live" and folder is None:
        ready = []
        for sym in syms:
            if throttled:
                fetch_errors[sym] = "not fetched: Yahoo is rate-limiting this IP"
                continue
            try:
                await asyncio.to_thread(bars.ensure_live, sym, ctx.day)
                ready.append(sym)
            except bars.nsedata.ThrottledError as e:   # the repo's own signal: stop, as scan.py does
                throttled = str(e)
                fetch_errors[sym] = "Yahoo rate limit (HTTP 429)"
            except Exception as e:                     # unknown symbol, network: report, keep going
                fetch_errors[sym] = f"{type(e).__name__}: {e}"
        syms = ready
    errors = [{"symbol": k, "why": v} for k, v in fetch_errors.items()]
    if not syms:
        return {"as_of": at.strftime("%Y-%m-%d %H:%M"), "session_day": ctx.day.isoformat(), "scanned": [],
                "throttled": throttled, "breakouts": [], "errors": errors, "decisions": [],
                "error": "No intraday bars available" + (" (Yahoo rate limit; it lifts after minutes to hours)."
                                                         if throttled else ".")}
    folder = folder or str(bars.bars_dir(mode, ctx.day))
    ctx.origin = origin
    orb = await ctx.run("nse.scan.orb", ["--offline", folder, "--symbols", ",".join(syms),
                                         "--or-minutes", str(s["orb_minutes"])], as_of=at)
    out = orb.get("output_json") or {}
    already = ledger.decided_symbols(mode, ctx.day.isoformat(), "orb")
    new = [b for b in out.get("breakouts", []) if b["symbol"] not in already]
    decisions = []
    for b in new:                                  # sequential: each idea already fans out internally
        decisions.append(await build_idea(ctx, b, folder, orb["id"]))
    return {
        "as_of": at.strftime("%Y-%m-%d %H:%M"), "session_day": ctx.day.isoformat(), "scanned": syms,
        "orb_run_id": orb["id"], "orb_status": orb["status"], "breakouts": out.get("breakouts", []),
        "throttled": throttled, "errors": out.get("errors", []) + errors,
        "already_decided": sorted(already & {b["symbol"] for b in out.get("breakouts", [])}),
        "decisions": [{"id": d["id"], "symbol": d["symbol"], "verdict": d["verdict"], "score": d["score"]}
                      for d in decisions],
    }
