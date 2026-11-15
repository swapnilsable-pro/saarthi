"""Paper trading service: accounts, orders, the account's risk limits, and ghost trades.

Every paper trade stores its ORDER and is re-simulated by the pure engine whenever it is read
while still working or open, so the stored result is always what engine.simulate says about
the bars available at that moment. Nothing here can reach a broker: SimulatedExchange is the
only OrderGateway.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from backend import bars, clock
from backend.ledger.db import Ledger
from backend.pipeline import ideas
from backend.sim.daily import DailyRules, GttSpec, simulate_daily
from backend.sim.engine import OrderSpec, Rules, risk_base, simulate, validate
from backend.sim.gateway import OrderGateway

import charges as nse_charges  # noqa: E402  vendored nse-common

PAPER_DEFAULTS = {
    "capital_inr": 200000,
    "daily_loss_cap_pct": 2.0,       # nse-trader-skill config default
    "max_trades_per_day": 4,         # nse-trader-skill config default
    "slippage_bps": 3.0,
}


class PaperError(ValueError):
    """An order the account's own rules refuse (shown to the user, broker-style)."""


def account(ledger: Ledger, data_mode: str) -> dict[str, Any]:
    acc = ledger.get_account(data_mode)
    if acc:
        return acc
    cap = PAPER_DEFAULTS["capital_inr"]
    ledger.create_account(data_mode, f"Paper ₹{cap:,.0f}" + (" (demo)" if data_mode == "demo" else ""), cap,
                          dict(PAPER_DEFAULTS))
    return ledger.get_account(data_mode)


def _rules(entry_ref: float, settings: dict) -> Rules:
    return Rules(tick=ideas.tick_for(entry_ref), slippage_bps=settings["slippage_bps"],
                 no_entries_after=ideas.SETTINGS["no_entries_after"], square_off=ideas.SETTINGS["flat_by"])


def _now_for(data_mode: str, day: str) -> str | None:
    """None = the whole session is history (replay to the end). Live and today: cut at now."""
    if data_mode == "demo":
        return None
    now = clock.ist_now()
    return None if day < now.date().isoformat() else now.strftime("%Y-%m-%d %H:%M")


def account_state(ledger: Ledger, data_mode: str, day: str | None = None) -> dict[str, Any]:
    acc = account(ledger, data_mode)
    s = acc["settings"]
    if day is None:
        from backend.pipeline.jobs import DEMO_SESSION
        day = DEMO_SESSION.isoformat() if data_mode == "demo" else clock.ist_now().date().isoformat()
    trades = [t for t in ledger.list_paper_trades(account_id=acc["id"]) if t["mode"] != "ghost"]
    realized = sum(t["net_pnl"] or 0 for t in trades if t["status"] == "closed")
    today = [t for t in trades if t["session_day"] == day and t["status"] not in ("rejected", "cancelled")]
    day_net = sum(t["net_pnl"] or 0 for t in today if t["status"] == "closed")
    unreal = sum((t["result"] or {}).get("unrealized_pnl") or 0 for t in today if t["status"] == "open")
    risk_used = sum(_planned_risk(t) for t in today if t["status"] in ("working", "open"))
    cap = acc["capital"] * s["daily_loss_cap_pct"] / 100
    entries = [t for t in today if t["status"] in ("working", "open", "closed", "expired") and t["product"] == "MIS"]
    lock = None
    if day_net <= -cap:
        lock = f"Daily loss cap reached ({s['daily_loss_cap_pct']}% = ₹{cap:,.0f}): no new entries until the next session."
    elif len(entries) >= s["max_trades_per_day"]:
        lock = f"Trade limit reached ({s['max_trades_per_day']} a day)."
    return {
        "account": acc, "session_day": day, "equity": round(acc["capital"] + realized, 2),
        "realized_total": round(realized, 2), "day_net": round(day_net, 2), "day_unrealized": round(unreal, 2),
        "risk_open": round(risk_used, 2), "daily_loss_cap": round(cap, 2),
        "trades_today": len(entries), "trades_left": max(0, s["max_trades_per_day"] - len(entries)),
        "locked": lock,
    }


def _planned_risk(t: dict) -> float:
    o = t["order_spec"] or {}
    if o.get("kind") == "gtt":
        return max(0.0, (o["trigger"] - o["stop"]) * o["qty"])
    spec = OrderSpec(**o)
    return risk_base(spec, (o.get("planned_entry") or o.get("entry_price") or 0)) or 0.0


def preview(ledger: Ledger, data_mode: str, spec: OrderSpec) -> dict[str, Any]:
    """What the ticket would do, before placing: rejections, risk, costs at stop and target."""
    st = account_state(ledger, data_mode, spec.placed_at[:10])
    ref = spec.entry_price if spec.entry_type != "MARKET" else (spec.planned_entry or spec.stop)
    rules = _rules(ref, st["account"]["settings"])
    why = validate(spec, rules) or st["locked"]
    day = dt.date.fromisoformat(spec.placed_at[:10])
    if not why and not (clock.nsecal.covered(day) and clock.nsecal.session(day)):
        why = f"The NSE equity market does not trade on {day.isoformat()} ({clock.session_info(dt.datetime.combine(day, dt.time(12))).get('holiday') or day.strftime('%A')})."
    risk = risk_base(spec, ref) or 0
    if not why and st["day_net"] - risk < -st["daily_loss_cap"]:
        why = (f"A full stop-out (₹{risk:,.0f}) would breach today's loss cap "
               f"(₹{st['daily_loss_cap']:,.0f}, ₹{st['daily_loss_cap'] + st['day_net']:,.0f} left).")
    est = {}
    for label, exit_px in (("at_stop", spec.stop), ("at_target", spec.target)):
        if exit_px is None:
            continue
        rt = nse_charges.round_trip(Decimal(f"{ref:.2f}"), Decimal(f"{exit_px:.2f}"), spec.qty, product="equity_intraday")
        gross = (exit_px - ref) * spec.qty
        est[label] = {"gross": round(gross, 2), "costs": float(rt["total"]), "net": round(gross - float(rt["total"]), 2)}
    return {"ok": why is None, "reject_reason": why, "tick": rules.tick, "risk": round(risk, 2),
            "position_value": round(ref * spec.qty, 2),
            "risk_pct_of_capital": round(100 * risk / st["account"]["capital"], 3),
            "estimates": est, "account": {k: v for k, v in st.items() if k != "account"}}


class SimulatedExchange(OrderGateway):
    """Saarthi's only order gateway: orders go to the in-process engine, never to a broker."""

    paper = True

    def __init__(self, ledger: Ledger, data_mode: str):
        self.ledger, self.data_mode = ledger, data_mode

    def place(self, order: dict[str, Any]) -> dict[str, Any]:
        spec = OrderSpec(**{k: order[k] for k in OrderSpec.__dataclass_fields__ if k in order})
        decision_id = order.get("decision_id")
        pv = preview(self.ledger, self.data_mode, spec)
        acc = account(self.ledger, self.data_mode)
        row = {
            "account_id": acc["id"], "decision_id": decision_id,
            "mode": "live" if self.data_mode == "live" and _now_for("live", spec.placed_at[:10]) else "replay",
            "data_mode": self.data_mode, "session_day": spec.placed_at[:10], "symbol": spec.symbol,
            "side": spec.side, "product": "MIS", "qty": spec.qty, "order_spec": asdict(spec),
            "status": "rejected" if not pv["ok"] else "working", "reject_reason": pv["reject_reason"],
            "followed_plan": None,
        }
        if decision_id:
            d = self.ledger.get_decision(decision_id)
            plan = (d or {}).get("plan") or {}
            row["followed_plan"] = int(bool(plan) and spec.qty == plan.get("qty") and spec.stop == plan.get("stop")
                                       and spec.target == plan.get("target")
                                       and (spec.entry_price or spec.planned_entry) == plan.get("entry"))
        trade_id = self.ledger.upsert_paper_trade(row)
        return refresh(self.ledger, trade_id) if pv["ok"] else self.ledger.get_paper_trade(trade_id)

    def cancel(self, order_id: str) -> dict[str, Any]:
        t = self.ledger.get_paper_trade(order_id)
        if not t:
            raise PaperError("No such paper trade.")
        if t["status"] == "working":
            self.ledger.upsert_paper_trade({"id": order_id, "status": "cancelled", "updated_at": clock.ist_now().isoformat()})
            return self.ledger.get_paper_trade(order_id)
        if t["status"] == "open":                       # close at the next bar's open
            now = clock.ist_now()
            nxt = now.replace(second=0, microsecond=0, minute=now.minute - now.minute % 5) + dt.timedelta(minutes=5)
            spec = dict(t["order_spec"]) | {"exit_at": nxt.strftime("%Y-%m-%d %H:%M")}
            self.ledger.upsert_paper_trade({"id": order_id, "order_spec": spec})
            return refresh(self.ledger, order_id)
        raise PaperError(f"Trade is {t['status']}; nothing to cancel.")


def refresh(ledger: Ledger, trade_id: str, *, fetch: bool = False) -> dict[str, Any]:
    """Re-simulate a working/open trade on the bars available now."""
    t = ledger.get_paper_trade(trade_id)
    if not t or t["status"] not in ("working", "open"):
        return t
    if (t["order_spec"] or {}).get("kind") == "gtt":
        return _refresh_gtt(ledger, t)
    spec = OrderSpec(**t["order_spec"])
    day = dt.date.fromisoformat(t["session_day"])
    if fetch and t["data_mode"] == "live":
        try:
            bars.ensure_live(spec.symbol, day)
        except Exception:
            pass                                          # throttled: simulate on what we have
    series = bars.session_bars(t["data_mode"], spec.symbol, day)
    acc = account(ledger, t["data_mode"])
    ref = spec.entry_price if spec.entry_type != "MARKET" else (spec.planned_entry or spec.stop)
    res = simulate(spec, series, _now_for(t["data_mode"], t["session_day"]), _rules(ref, acc["settings"]))
    upd = {
        "id": trade_id, "status": res.status, "result": res.as_dict(), "fills": [asdict(f) for f in res.fills],
        "exit_reason": res.exit_reason, "gross_pnl": res.gross_pnl, "costs": res.costs, "net_pnl": res.net_pnl,
        "r_multiple": res.r_multiple, "mae_r": res.mae_r, "mfe_r": res.mfe_r, "bars_held": res.bars_held,
        "ambiguous_bars": res.ambiguous_bars, "entry_price": res.entry_price, "exit_price": res.exit_price,
        "entry_at": res.entry_at, "exit_at": res.exit_at, "updated_at": clock.ist_now().isoformat(),
    }
    if t.get("followed_plan") and res.exit_reason == "MANUAL":
        upd["followed_plan"] = 0
    ledger.upsert_paper_trade(upd)
    return ledger.get_paper_trade(trade_id)


def order_from_idea(d: dict[str, Any]) -> dict[str, Any]:
    """The default ticket for an idea: a LIMIT buy at the planned entry, placed when the breakout
    bar closed, with the plan's stop, target, quantity and breakeven trail."""
    p = d["plan"]
    return {"symbol": d["symbol"], "qty": p["qty"], "entry_type": "LIMIT", "entry_price": p["entry"],
            "stop": p["stop"], "target": p["target"], "placed_at": f"{d['session_day']} {p['entry_at']}",
            "trail_breakeven": True, "planned_entry": p["entry"], "decision_id": d["id"]}


def run_ghosts(ledger: Ledger, data_mode: str, day: str) -> list[dict[str, Any]]:
    """Trade EVERY idea of a finished session as planned, TAKE or not, in a separate ghost book.
    Phase 4 compares ghosts by verdict to show what each gate saved or cost. Never shown as
    the user's results, and never visible to a decision (they run after the session)."""
    if data_mode == "live" and day >= clock.ist_now().date().isoformat() and clock.ist_now().time() < dt.time(15, 30):
        return []
    acc = account(ledger, data_mode)
    have = {t["decision_id"] for t in ledger.list_paper_trades(mode="ghost", data_mode=data_mode, session_day=day)}
    out = []
    for d in ledger.list_decisions(data_mode, day):
        if d["setup"] != "orb" or not d.get("plan") or d["id"] in have:
            continue
        o = order_from_idea(d)
        spec = OrderSpec(**{k: o[k] for k in OrderSpec.__dataclass_fields__ if k in o})
        series = bars.session_bars(data_mode, spec.symbol, dt.date.fromisoformat(day))
        rules = _rules(spec.entry_price, acc["settings"])
        res = simulate(spec, series, None, rules)
        # Calibration twin: the Time Machine models stop-vs-target only (no breakeven trail), so the
        # honest test of its P(target first) is the same order without the trail.
        twin = simulate(OrderSpec(**(asdict(spec) | {"trail_breakeven": False})), series, None, rules)
        result = res.as_dict() | {"calib": {"status": twin.status, "exit_reason": twin.exit_reason,
                                            "net_pnl": twin.net_pnl, "r_multiple": twin.r_multiple}}
        tid = ledger.upsert_paper_trade({
            "account_id": acc["id"], "decision_id": d["id"], "mode": "ghost", "data_mode": data_mode,
            "session_day": day, "symbol": spec.symbol, "side": "BUY", "product": "MIS", "qty": spec.qty,
            "order_spec": asdict(spec), "status": res.status, "result": result,
            "fills": [asdict(f) for f in res.fills], "exit_reason": res.exit_reason, "gross_pnl": res.gross_pnl,
            "costs": res.costs, "net_pnl": res.net_pnl, "r_multiple": res.r_multiple, "mae_r": res.mae_r,
            "mfe_r": res.mfe_r, "bars_held": res.bars_held, "ambiguous_bars": res.ambiguous_bars,
            "entry_price": res.entry_price, "exit_price": res.exit_price, "entry_at": res.entry_at,
            "exit_at": res.exit_at, "followed_plan": 1, "updated_at": clock.ist_now().isoformat(),
        })
        out.append(ledger.get_paper_trade(tid) | {"verdict": d["verdict"]})
    return out


async def refresh_open_live(ledger: Ledger) -> int:
    """Scheduler hook: re-simulate live paper trades after each new bar (fetching their charts)."""
    n = 0
    for t in ledger.list_paper_trades(data_mode="live"):
        if t["status"] in ("working", "open"):
            await asyncio.to_thread(refresh, ledger, t["id"], fetch=True)
            n += 1
    return n


# ------------------------------------------------------------------------------- swing: GTT / CNC
def gtt_from_idea(d: dict[str, Any]) -> dict[str, Any]:
    """The India breakout planner's own order: GTT single BUY (trigger, chase limit), then an OCO
    stop / target. Target = the plan's 2R target (the planner prints 2R and 3R)."""
    p = d["plan"]
    return {"kind": "gtt", "symbol": d["symbol"], "qty": p["qty"], "trigger": p["trigger"], "limit": p["limit"],
            "stop": p["stop"], "target": p.get("target"), "placed_on": d["session_day"],
            "entry_valid_days": p.get("entry_valid_days", 20), "max_hold_days": p.get("hold_days", 20),
            "planned_entry": p["trigger"]}


def place_gtt(ledger: Ledger, data_mode: str, spec: dict[str, Any], decision_id: str | None = None) -> dict[str, Any]:
    g = GttSpec(**{k: spec[k] for k in GttSpec.__dataclass_fields__ if k in spec})
    from backend.sim.daily import validate as gtt_validate
    why = gtt_validate(g)
    acc = account(ledger, data_mode)
    tid = ledger.upsert_paper_trade({
        "account_id": acc["id"], "decision_id": decision_id, "mode": "replay" if data_mode == "demo" else "live",
        "data_mode": data_mode, "session_day": g.placed_on, "symbol": g.symbol, "side": "BUY", "product": "CNC",
        "qty": g.qty, "order_spec": asdict(g), "status": "rejected" if why else "working", "reject_reason": why,
        "followed_plan": 1 if decision_id else None,
    })
    return ledger.get_paper_trade(tid) if why else refresh(ledger, tid)


def _refresh_gtt(ledger: Ledger, t: dict[str, Any]) -> dict[str, Any]:
    from backend.pipeline import swing
    g = GttSpec(**{k: v for k, v in t["order_spec"].items() if k in GttSpec.__dataclass_fields__})
    series = swing.full_daily(t["data_mode"], g.symbol)
    now = None if t["data_mode"] == "demo" else clock.ist_now().date().isoformat()
    res = simulate_daily(g, series, now, DailyRules(tick=ideas.tick_for(g.trigger)))
    if t["data_mode"] == "demo" and res.status == "open":
        res.events.append({"time": series[-1]["date"] if series else "", "text": "Demo data ends here: position still open"})
    ledger.upsert_paper_trade({
        "id": t["id"], "status": res.status, "result": res.as_dict(), "fills": [asdict(f) for f in res.fills],
        "exit_reason": res.exit_reason, "gross_pnl": res.gross_pnl, "costs": res.costs, "net_pnl": res.net_pnl,
        "r_multiple": res.r_multiple, "mae_r": res.mae_r, "mfe_r": res.mfe_r, "bars_held": res.bars_held,
        "entry_price": res.entry_price, "exit_price": res.exit_price, "entry_at": res.entry_at, "exit_at": res.exit_at,
        "updated_at": clock.ist_now().isoformat()})
    return ledger.get_paper_trade(t["id"])
