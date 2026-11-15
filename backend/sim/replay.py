"""Replay simulator ("flight simulator", IMPLEMENTATION_PLAN.md §9.5).

A replay session has a simulated IST clock on one past session. Everything it returns is cut at
that clock: only 5-minute bars that have COMPLETED by then, only ideas whose decision moment has
passed, and paper trades simulated by the engine with now = clock. Ideas are the same point-in-time
decisions the batch replayer records (made at each breakout bar's close with tools told that moment),
so the simulator never needs to look ahead to show them.

At 15:30 the session ends and a scorecard compares you, Saarthi's plan, and perfect hindsight.
"""
from __future__ import annotations

import datetime as dt
import random
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from backend import bars
from backend.ledger.db import Ledger
from backend.pipeline import batch, ideas
from backend.sim import paper
from backend.sim.engine import OrderSpec, simulate

import charges as nse_charges  # noqa: E402  vendored nse-common

OPEN, CLOSE, SQUARE_OFF, OR_END = "09:15", "15:30", "15:15", "09:30"


class ReplayError(ValueError):
    pass


def _t(day: str, hm: str) -> str:
    return f"{day} {hm}"


def _add(clock: str, minutes: int) -> str:
    t = dt.datetime.strptime(clock, "%Y-%m-%d %H:%M") + dt.timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%d %H:%M")


def _alias(i: int) -> str:
    return f"STOCK {chr(65 + i)}"


async def create(ledger: Ledger, mode: str, *, day: str | None = None, symbols: list[str] | None = None,
                 surprise: bool = False) -> dict[str, Any]:
    syms = [s.upper() for s in (symbols or (["DEMO"] if mode == "demo" else []))]
    if not syms:
        raise ReplayError("Pick at least one stock to replay.")
    days, folder = batch.replayable_days(mode, syms)
    if not days:
        raise ReplayError("No saved intraday history to replay for these stocks.")
    if surprise or not day:
        chosen = random.choice(days)
    else:
        chosen = dt.date.fromisoformat(day)
        if chosen not in days:
            raise ReplayError(f"{day} is not a replayable session (needs {batch.MIN_HISTORY} earlier sessions of history).")
    # Make sure the day's ideas exist (point-in-time, identical to what the scheduler would have done).
    await batch.replay_day(ledger, mode, chosen, syms, folder)
    rid = ledger.create_replay(mode, chosen.isoformat(), syms, surprise, _t(chosen.isoformat(), OPEN))
    return state(ledger, rid)


def _ideas(ledger: Ledger, r: dict) -> list[dict]:
    return [d for d in ledger.list_decisions(r["data_mode"], r["day"]) if d["symbol"] in r["symbols"]]


def _bars(r: dict, sym: str, clock: str | None) -> list[dict]:
    until = dt.datetime.strptime(clock, "%Y-%m-%d %H:%M") if clock else None
    return bars.session_bars(r["data_mode"], sym, dt.date.fromisoformat(r["day"]), until)


def _trades(ledger: Ledger, r: dict) -> list[dict]:
    """Re-simulate every trade of this replay at the current clock (never beyond it)."""
    out = []
    for t in ledger.list_paper_trades(replay_id=r["id"]):
        if t["status"] in ("rejected", "cancelled"):
            out.append(t)
            continue
        spec = OrderSpec(**t["order_spec"])
        res = simulate(spec, _bars(r, spec.symbol, None), r["clock"], paper._rules(
            spec.entry_price or spec.planned_entry or spec.stop, paper.PAPER_DEFAULTS))
        ledger.upsert_paper_trade({
            "id": t["id"], "status": res.status, "result": res.as_dict(), "fills": [asdict(f) for f in res.fills],
            "exit_reason": res.exit_reason, "gross_pnl": res.gross_pnl, "costs": res.costs, "net_pnl": res.net_pnl,
            "r_multiple": res.r_multiple, "mae_r": res.mae_r, "mfe_r": res.mfe_r, "bars_held": res.bars_held,
            "entry_price": res.entry_price, "exit_price": res.exit_price, "entry_at": res.entry_at, "exit_at": res.exit_at})
        out.append(ledger.get_paper_trade(t["id"]))
    return out


def state(ledger: Ledger, rid: str) -> dict[str, Any]:
    r = ledger.get_replay(rid)
    if not r:
        raise ReplayError("No such replay.")
    clock, day = r["clock"], r["day"]
    done = clock >= _t(day, CLOSE)
    hide = bool(r["surprise"]) and not done
    names = {s: (_alias(i) if hide else s) for i, s in enumerate(r["symbols"])}
    visible = [d for d in _ideas(ledger, r) if d["as_of"] <= clock]
    trades = _trades(ledger, r)
    upcoming = sorted({d["as_of"] for d in _ideas(ledger, r) if d["as_of"] > clock}
                      | {t for t in (_t(day, OR_END), _t(day, "14:30"), _t(day, SQUARE_OFF), _t(day, CLOSE)) if t > clock})
    out = {
        "id": rid, "mode": r["data_mode"], "surprise": bool(r["surprise"]), "done": done,
        "day": None if hide else day, "label": "Mystery session" if hide else day,
        "clock": clock, "time": clock[11:], "next_event": upcoming[0][11:] if upcoming else None,
        "symbols": [{"symbol": names[s], "real": None if hide else s,
                     "bars": _bars(r, s, clock)} for s in r["symbols"]],
        "ideas": [{"id": None if hide else d["id"], "symbol": names[d["symbol"]], "decided_at": d["decided_at"],
                   "verdict": d["verdict"], "reason": (d.get("detail") or {}).get("reason"), "score": d["score"],
                   "plan": {k: (d.get("plan") or {}).get(k) for k in ("entry", "stop", "target", "qty", "entry_at",
                                                                      "best_window", "risk_amount")} if d.get("plan") else None,
                   "odds": {k: (d.get("odds") or {}).get(k) for k in ("p_target", "net_per_trade", "net_rr")}
                           if d.get("odds") else None} for d in visible],
        "trades": [_trade_view(t, names) for t in trades],
        "pnl": {"realized": round(sum(t["net_pnl"] or 0 for t in trades if t["status"] == "closed"), 2),
                "unrealized": round(sum(((t.get("result") or {}).get("unrealized_pnl") or 0) for t in trades
                                        if t["status"] == "open"), 2)},
    }
    if done:
        out["scorecard"] = scorecard(ledger, r, trades)
    return out


def _trade_view(t: dict, names: dict[str, str]) -> dict:
    v = {k: t.get(k) for k in ("id", "status", "qty", "entry_price", "exit_price", "entry_at", "exit_at", "exit_reason",
                               "net_pnl", "r_multiple", "reject_reason")}
    v["symbol"] = names.get(t["symbol"], t["symbol"])
    v["order"] = {k: (t.get("order_spec") or {}).get(k) for k in ("entry_type", "entry_price", "stop", "target", "placed_at")}
    v["unrealized_pnl"] = (t.get("result") or {}).get("unrealized_pnl")
    v["stop_now"] = (t.get("result") or {}).get("stop_now")
    v["events"] = (t.get("result") or {}).get("events", [])
    return v


def advance(ledger: Ledger, rid: str, *, bars_n: int | None = None, to: str | None = None,
            next_event: bool = False) -> dict[str, Any]:
    r = ledger.get_replay(rid)
    if not r:
        raise ReplayError("No such replay.")
    end = _t(r["day"], CLOSE)
    if next_event:
        nxt = state(ledger, rid)["next_event"]
        target = _t(r["day"], nxt) if nxt else end
    elif to:
        target = _t(r["day"], to)
    else:
        target = _add(r["clock"], 5 * (bars_n or 1))
    if target <= r["clock"]:
        raise ReplayError("The replay clock only moves forward.")
    ledger.set_replay_clock(rid, min(target, end))
    return state(ledger, rid)


def place(ledger: Ledger, rid: str, order: dict[str, Any]) -> dict[str, Any]:
    """A paper order inside the replay, placed at the simulated clock."""
    r = ledger.get_replay(rid)
    if not r:
        raise ReplayError("No such replay.")
    if r["clock"] >= _t(r["day"], CLOSE):
        raise ReplayError("The session is over.")
    names = {(_alias(i) if r["surprise"] else s): s for i, s in enumerate(r["symbols"])}
    sym = names.get(order.get("symbol", ""), order.get("symbol", "")).upper()
    if sym not in r["symbols"]:
        raise ReplayError("That stock is not in this replay.")
    spec = OrderSpec(symbol=sym, qty=int(order["qty"]), entry_type=order.get("entry_type", "MARKET"),
                     entry_price=order.get("entry_price"), stop=float(order["stop"]), target=order.get("target"),
                     placed_at=r["clock"], trail_breakeven=bool(order.get("trail_breakeven", True)),
                     planned_entry=order.get("entry_price") or _last_close(r, sym))
    rules = paper._rules(spec.entry_price or spec.planned_entry, paper.PAPER_DEFAULTS)
    from backend.sim.engine import validate
    why = validate(spec, rules)
    ledger.upsert_paper_trade({
        "account_id": f"sim-{rid}", "replay_id": rid, "decision_id": order.get("decision_id"), "mode": "replay",
        "data_mode": r["data_mode"], "session_day": r["day"], "symbol": sym, "side": "BUY", "product": "MIS",
        "qty": spec.qty, "order_spec": asdict(spec), "status": "rejected" if why else "working", "reject_reason": why,
    })
    return state(ledger, rid)


def close(ledger: Ledger, rid: str, trade_id: str) -> dict[str, Any]:
    r = ledger.get_replay(rid)
    t = ledger.get_paper_trade(trade_id)
    if not r or not t or t.get("replay_id") != rid:
        raise ReplayError("No such trade in this replay.")
    if t["status"] == "working":
        ledger.upsert_paper_trade({"id": trade_id, "status": "cancelled"})
    elif t["status"] == "open":
        spec = dict(t["order_spec"]) | {"exit_at": r["clock"]}       # out at the next bar's open
        ledger.upsert_paper_trade({"id": trade_id, "order_spec": spec})
    return state(ledger, rid)


def _last_close(r: dict, sym: str) -> float | None:
    b = _bars(r, sym, r["clock"])
    return b[-1]["c"] if b else None


def scorecard(ledger: Ledger, r: dict, trades: list[dict]) -> dict[str, Any]:
    day = r["day"]
    decisions = _ideas(ledger, r)
    ghosts = {g["decision_id"]: g for g in ledger.list_paper_trades(mode="ghost", data_mode=r["data_mode"], session_day=day)}
    you = [t for t in trades if t["status"] == "closed"]
    take = [ghosts[d["id"]] for d in decisions if d["verdict"] == "TAKE" and d["id"] in ghosts]
    every = [ghosts[d["id"]] for d in decisions if d["id"] in ghosts]
    best = None
    for s in r["symbols"]:
        h = hindsight(r, s, next((d["plan"]["qty"] for d in decisions if d["symbol"] == s and d.get("plan")), None))
        if h and (best is None or h["net"] > best["net"]):
            best = h
    net = lambda ts: round(sum(t["net_pnl"] or 0 for t in ts if t["status"] == "closed"), 2)
    yours = net(you)
    return {
        "you": {"net": yours, "trades": len(you)},
        "saarthi_take": {"net": net(take), "trades": len([t for t in take if t["status"] == "closed"])},
        "every_idea": {"net": net(every), "trades": len([t for t in every if t["status"] == "closed"])},
        "hindsight": best,
        "ideas": [{"symbol": d["symbol"], "verdict": d["verdict"], "decided_at": d["decided_at"],
                   "ghost_net": (ghosts.get(d["id"]) or {}).get("net_pnl")} for d in decisions],
        "capture_pct": round(100 * yours / best["net"], 1) if best and best["net"] > 0 else None,
    }


def hindsight(r: dict, sym: str, qty: int | None) -> dict[str, Any] | None:
    """The best single long trade anyone could have made: buy a bar's low before the entry cutoff,
    sell a later bar's high before square-off, at the idea's size (or the capital), after costs."""
    full = _bars(r, sym, None)
    lim_in, lim_out = ideas.SETTINGS["no_entries_after"], SQUARE_OFF
    best, lo_i = None, None
    for j, b in enumerate(full):
        t = b["time"][11:]
        if lo_i is not None and t < lim_out and (best is None or b["h"] - full[lo_i]["l"] > best[2]):
            best = (lo_i, j, b["h"] - full[lo_i]["l"])
        if t < lim_in and (lo_i is None or b["l"] < full[lo_i]["l"]):
            lo_i = j
    if not best or best[2] <= 0:
        return None
    i, j, _ = best
    buy, sell = full[i]["l"], full[j]["h"]
    q = qty or int(paper.PAPER_DEFAULTS["capital_inr"] // buy)
    cost = float(nse_charges.round_trip(Decimal(f"{buy:.2f}"), Decimal(f"{sell:.2f}"), q, product="equity_intraday")["total"])
    return {"symbol": sym, "buy": buy, "buy_at": full[i]["time"][11:], "sell": sell, "sell_at": full[j]["time"][11:],
            "qty": q, "net": round((sell - buy) * q - cost, 2)}
