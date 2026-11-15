"""History and performance (IMPLEMENTATION_PLAN.md §8). Pure bookkeeping over the ledger.

Three books:
  mine  - the user's own paper trades.
  take  - ghost trades of ideas the verdict said TAKE ("if you had taken every TAKE as planned").
  all   - ghost trades of every idea, TAKE, WATCH or SKIP (the counterfactual book).
Ghosts are produced after each session and never feed a decision; they are hindsight and the UI
labels them so.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from statistics import mean
from typing import Any

from backend.ledger.db import Ledger

BOOKS = ("mine", "take", "all")
R_BINS = [-3.0, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0]


def _decisions(ledger: Ledger, mode: str) -> dict[str, dict]:
    return {d["id"]: d for d in ledger.list_decisions(mode, limit=100000)}


def _book(ledger: Ledger, mode: str, book: str, decisions: dict[str, dict]) -> list[dict]:
    trades = [t for t in ledger.list_paper_trades(data_mode=mode) if not t.get("replay_id")]
    if book == "mine":
        rows = [t for t in trades if t["mode"] != "ghost"]
    else:
        rows = [t for t in trades if t["mode"] == "ghost"]
        if book == "take":
            rows = [t for t in rows if decisions.get(t["decision_id"], {}).get("verdict") == "TAKE"]
    for t in rows:
        d = decisions.get(t["decision_id"]) or {}
        t["_verdict"] = d.get("verdict")
        t["_regime"] = ((d.get("detail") or {}).get("mood") or {}).get("label")
        t["_first_failed"] = d.get("first_failed_gate")
    return rows


def _drawdown(curve: list[float]) -> float:
    peak, worst = 0.0, 0.0
    for v in curve:
        peak = max(peak, v)
        worst = min(worst, v - peak)
    return round(worst, 2)


def _group(rows: list[dict], key) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for t in rows:
        k = key(t)
        if k is not None:
            g[k].append(t)
    out = []
    for k, ts in sorted(g.items()):
        nets = [t["net_pnl"] for t in ts]
        rs = [t["r_multiple"] for t in ts if t["r_multiple"] is not None]
        out.append({"key": k, "n": len(ts), "net": round(sum(nets), 2), "avg_r": round(mean(rs), 3) if rs else None,
                    "win_rate": round(sum(1 for n in nets if n > 0) / len(nets), 3)})
    return out


def stats(ledger: Ledger, mode: str, book: str) -> dict[str, Any]:
    decisions = _decisions(ledger, mode)
    rows = _book(ledger, mode, book, decisions)
    closed = sorted([t for t in rows if t["status"] == "closed"], key=lambda t: t["exit_at"] or "")
    unfilled = [t for t in rows if t["status"] in ("expired",)]
    out: dict[str, Any] = {"book": book, "mode": mode, "trades": len(closed), "unfilled": len(unfilled),
                           "sessions": len({t["session_day"] for t in closed})}
    if not closed:
        return out | {"empty": True}
    nets = [t["net_pnl"] for t in closed]
    rs = [t["r_multiple"] for t in closed if t["r_multiple"] is not None]
    wins, losses = [n for n in nets if n > 0], [n for n in nets if n <= 0]
    cum, curve = 0.0, []
    for t in closed:
        cum += t["net_pnl"]
        curve.append({"t": t["exit_at"], "equity": round(cum, 2), "symbol": t["symbol"], "net": t["net_pnl"]})
    gross = sum(abs(t["gross_pnl"] or 0) for t in closed)
    costs = sum((t["costs"] or {}).get("total", 0) for t in closed)
    hist = []
    for lo, hi in zip([-math.inf] + R_BINS, R_BINS + [math.inf]):
        hist.append({"from": None if lo == -math.inf else lo, "to": None if hi == math.inf else hi,
                     "n": sum(1 for r in rs if lo <= r < hi)})
    weekday = lambda t: dt.date.fromisoformat(t["session_day"]).strftime("%a")
    return out | {
        "empty": False,
        "net": round(sum(nets), 2), "expectancy": round(mean(nets), 2), "avg_r": round(mean(rs), 3) if rs else None,
        "win_rate": round(len(wins) / len(nets), 3),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None,
        "avg_win": round(mean(wins), 2) if wins else None, "avg_loss": round(mean(losses), 2) if losses else None,
        "max_drawdown": _drawdown([c["equity"] for c in curve]),
        "avg_mae_r": round(mean(t["mae_r"] for t in closed if t["mae_r"] is not None), 3),
        "avg_mfe_r": round(mean(t["mfe_r"] for t in closed if t["mfe_r"] is not None), 3),
        "costs_total": round(costs, 2), "costs_pct_of_gross": round(100 * costs / gross, 1) if gross else None,
        "equity_curve": curve, "r_histogram": hist,
        "by_exit": _group(closed, lambda t: t["exit_reason"]),
        "by_entry_hour": _group(closed, lambda t: (t["entry_at"] or "")[11:13] + ":00" if t["entry_at"] else None),
        "by_weekday": sorted(_group(closed, weekday), key=lambda g: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(g["key"])),
        "by_regime": _group(closed, lambda t: t["_regime"] or "unknown"),
        "by_verdict": _group(closed, lambda t: t["_verdict"]) if book != "mine" else [],
        "followed_plan": _group(closed, lambda t: {1: "followed plan", 0: "deviated"}.get(t.get("followed_plan"))) if book == "mine" else [],
    }


def calibration(ledger: Ledger, mode: str) -> dict[str, Any]:
    """Was the Time Machine honest? Predicted P(target first) vs what happened, using the ghost's
    no-trail twin (the Time Machine's own model: stop vs target, flat at 15:15)."""
    decisions = _decisions(ledger, mode)
    pts = []
    for t in ledger.list_paper_trades(data_mode=mode, mode="ghost"):
        d = decisions.get(t["decision_id"])
        cal = (t.get("result") or {}).get("calib") or {}
        if not d or not (d.get("odds") or {}).get("p_target") or cal.get("status") != "closed":
            continue
        pts.append({"p": d["odds"]["p_target"], "hit": 1 if cal["exit_reason"] == "TARGET" else 0,
                    "pred_net": d["odds"]["net_per_trade"], "real_net": cal["net_pnl"], "symbol": d["symbol"],
                    "day": d["session_day"], "verdict": d["verdict"], "id": d["id"]})
    if not pts:
        return {"n": 0, "buckets": [], "points": []}
    buckets = []
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        b = [p for p in pts if lo <= p["p"] < hi or (i == 9 and p["p"] == 1.0)]
        if b:
            buckets.append({"from": lo, "to": hi, "n": len(b), "predicted": round(mean(p["p"] for p in b), 3),
                            "observed": round(mean(p["hit"] for p in b), 3)})
    brier = mean((p["p"] - p["hit"]) ** 2 for p in pts)
    base = mean(p["hit"] for p in pts)
    brier_ref = mean((base - p["hit"]) ** 2 for p in pts)    # always predicting the base rate
    n = len(pts)
    pred, obs = mean(p["p"] for p in pts), base
    se = math.sqrt(max(obs * (1 - obs), 1e-9) / n)
    return {
        "n": n, "buckets": buckets, "points": pts,
        "mean_predicted": round(pred, 3), "mean_observed": round(obs, 3),
        "gap": round(obs - pred, 3), "gap_se": round(se, 3),
        "brier": round(brier, 4), "brier_reference": round(brier_ref, 4),
        "predicted_net_avg": round(mean(p["pred_net"] for p in pts), 2),
        "realized_net_avg": round(mean(p["real_net"] for p in pts), 2),
        "verdict": _calib_verdict(obs - pred, se, n, brier, brier_ref),
    }


def _calib_verdict(gap: float, se: float, n: int, brier: float, brier_ref: float) -> str:
    if n < 20:
        return f"Too few outcomes to judge yet ({n}); calibration needs at least 20."
    if abs(gap) <= 2 * se:
        head = "On average, consistent: the observed hit rate is within the statistical noise of the predicted odds."
    else:
        head = ("Optimistic: targets were hit less often than predicted." if gap < 0
                else "Pessimistic: targets were hit more often than predicted.")
    if brier >= brier_ref:
        head += (" But trade by trade it did no better than always guessing the average hit rate "
                 f"(Brier {brier:.3f} vs {brier_ref:.3f}), so its odds are not yet telling ideas apart.")
    return head


def gate_value(ledger: Ledger, mode: str) -> dict[str, Any]:
    """For each check, the ghost P&L of the ideas it stopped (by first failing check), and of the
    ideas that passed everything. Negative blocked P&L = the check saved money."""
    decisions = _decisions(ledger, mode)
    ghosts = {t["decision_id"]: t for t in ledger.list_paper_trades(data_mode=mode, mode="ghost")}
    labels: dict[str, str] = {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in decisions.values():
        g = ghosts.get(d["id"])
        if not g or g["status"] != "closed":
            continue
        key = d["first_failed_gate"] or "PASSED"
        groups[key].append(g)
        for gate in (d.get("detail") or {}).get("gates", []):
            labels[gate["step"]] = gate["label"]
    rows = []
    for k, ts in groups.items():
        net = sum(t["net_pnl"] for t in ts)
        rs = [t["r_multiple"] for t in ts if t["r_multiple"] is not None]
        rows.append({"gate": k, "label": "Passed every check (TAKE)" if k == "PASSED" else labels.get(k, k),
                     "n": len(ts), "ghost_net": round(net, 2), "avg_r": round(mean(rs), 3) if rs else None,
                     "effect": None if k == "PASSED" else ("saved" if net < 0 else "cost")})
    rows.sort(key=lambda r: (r["gate"] != "PASSED", r["ghost_net"]))
    return {"rows": rows, "total_ideas": sum(r["n"] for r in rows)}


def history(ledger: Ledger, mode: str) -> dict[str, Any]:
    decisions = list(_decisions(ledger, mode).values())
    trades = [t for t in ledger.list_paper_trades(data_mode=mode) if not t.get("replay_id")]
    days: dict[str, dict] = defaultdict(lambda: {"ideas": 0, "TAKE": 0, "WATCH": 0, "SKIP": 0,
                                                 "take_ghost_net": 0.0, "all_ghost_net": 0.0, "my_net": 0.0, "my_trades": 0})
    verdict_of = {d["id"]: d["verdict"] for d in decisions}
    for d in decisions:
        x = days[d["session_day"]]
        x["ideas"] += 1
        x[d["verdict"]] += 1
    for t in trades:
        if t["status"] != "closed":
            continue
        x = days[t["session_day"]]
        if t["mode"] == "ghost":
            x["all_ghost_net"] += t["net_pnl"]
            if verdict_of.get(t["decision_id"]) == "TAKE":
                x["take_ghost_net"] += t["net_pnl"]
        else:
            x["my_net"] += t["net_pnl"]
            x["my_trades"] += 1
    for j in ledger.list_jobs(limit=10000):
        if j["mode"] == mode:
            days[j["session_day"]]   # a prepared day with no ideas still shows on the calendar
    return {"mode": mode, "days": [{"day": k} | {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                                   for k, v in sorted(days.items())]}


def day_detail(ledger: Ledger, mode: str, day: str) -> dict[str, Any]:
    decisions = ledger.list_decisions(mode, day)
    trades = [t for t in ledger.list_paper_trades(data_mode=mode, session_day=day) if not t.get("replay_id")]
    ghosts = {t["decision_id"]: t for t in trades if t["mode"] == "ghost"}
    mine = [t for t in trades if t["mode"] != "ghost"]
    jobs = [j for j in ledger.list_jobs(limit=10000) if j["mode"] == mode and j["session_day"] == day]
    events = []
    for j in jobs:
        at = j["as_of"] or j["started_at"]
        prev_evening = j["job"] == "evening_scan" and at[:10] < day
        events.append({"time": ("prev " if prev_evening else "") + at[11:16], "kind": "job",
                       "sort": "00:00" if prev_evening else at[11:16],
                       "text": f"{j['job'].replace('_', ' ')} ({j['status']})"
                               + (f", the evening of {at[:10]}" if prev_evening else ""), "ref": j["id"]})
    ideas = []
    for d in sorted(decisions, key=lambda d: d["decided_at"]):
        g = ghosts.get(d["id"])
        ideas.append({"id": d["id"], "symbol": d["symbol"], "decided_at": d["decided_at"], "verdict": d["verdict"],
                      "score": d["score"], "reason": (d.get("detail") or {}).get("reason"),
                      "origin": (d.get("detail") or {}).get("origin"),
                      "p_target": (d.get("odds") or {}).get("p_target"),
                      "pred_net": (d.get("odds") or {}).get("net_per_trade"),
                      "ghost": None if not g else {k: g.get(k) for k in ("status", "exit_reason", "net_pnl", "r_multiple",
                                                                         "entry_at", "exit_at")}})
        events.append({"time": d["decided_at"], "kind": "idea", "text": f"{d['symbol']}: {d['verdict']}", "ref": d["id"]})
    for t in mine:
        for f in t.get("fills") or []:
            events.append({"time": f["time"][11:16], "kind": "fill",
                           "text": f"{t['symbol']} {f['kind'].lower().replace('_', ' ')} {f['qty']} @ {f['price']:.2f}", "ref": t["id"]})
    events.sort(key=lambda e: e.get("sort") or e["time"])
    for e in events:
        e.pop("sort", None)
    return {"mode": mode, "day": day, "events": events, "ideas": ideas,
            "my_trades": [{k: t.get(k) for k in ("id", "symbol", "status", "exit_reason", "net_pnl", "r_multiple",
                                                 "entry_at", "exit_at", "decision_id")} for t in mine],
            "jobs": [{k: j[k] for k in ("id", "job", "status", "as_of", "trigger")} for j in jobs]}
