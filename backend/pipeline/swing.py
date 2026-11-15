"""Swing ideas (multi-day, delivery/CNC) from claude-trading-skills-india (IMPLEMENTATION_PLAN.md §6.2).

  scan      breakout.py scan   - Stage-2 trend template + VCP / flat base, liquidity, rank
  plan      breakout.py plan   - trigger, chase limit, stop, 2R/3R targets, size, GTT order text
  history   backtest.py run    - the same kind of breakout traded on this stock's history, with costs
  events    events.py range    - results and macro events inside the holding window
  climax    exhaustion.py      - is the move already spent?
  regime    regime.py status   - the market tape, as of the decision date

Point in time: these tools have no as-of flag, so the decision sees a copy of each daily CSV cut
at the decision date (rows after it removed). That is exactly the file the tool would have seen
that evening. Live mode keeps the CSVs the repo's own fetcher (ta.py fetch, yfinance) saved.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import shutil
from pathlib import Path
from typing import Any

from backend.ledger.db import Ledger
from backend.pipeline import brief, ideas
from backend.skills.registry import ROOT
from backend.skills.runner import default_config, run_tool

INDIA_FX = ROOT / "vendor/claude-trading-skills-india/tests/fixtures"
DEMO_SWING_DIR = ROOT / "data/demo/swing"
DAILY = ROOT / "data/daily"
DEMO_SWING_DAY = "2026-09-18"     # a Friday evening in the India repo's daily fixtures

SWING = {
    "capital_inr": 500000, "risk_per_trade_pct": 0.5, "band_pct": 10, "max_candidates": 8,
    "hold_days": 20, "entry_valid_days": 20, "backtest_strategy": "donchian-breakout",
    "min_backtest_trades": 5, "broker": "zerodha",
}

SWING_RULE = (
    "TAKE when: the scan calls the base actionable (S0), the stock passes the Stage-2 trend template (S1), "
    "it is liquid enough (S2), the market is not in correction (S3), no results or company event falls inside "
    "the {hold}-session holding window (S4), the move is not a buying climax (S5), and this stock's own history of "
    "breakouts was profitable after costs (B1: positive expectancy and profit factor > 1 over at least {mint} trades). "
    "A watch-list base or a thin history caps it at WATCH; any failed check makes it SKIP."
)


def _universe_files() -> list[Path]:
    fx = INDIA_FX
    return sorted(list(fx.glob("breakout_stk_*.csv")) + list((fx / "momentum_universe").glob("*.csv"))
                  + list((fx / "sector_stocks").glob("*.csv")))


def _symbol(p: Path) -> str:
    return p.stem.upper()


def demo_universe(as_of: str) -> Path:
    """Copies of the repo's daily fixtures cut at `as_of` (inclusive). Benchmark kept alongside."""
    out = DEMO_SWING_DIR / as_of
    if out.exists() and any(out.glob("*.csv")):
        return out
    out.mkdir(parents=True, exist_ok=True)
    for f in _universe_files() + [INDIA_FX / "breakout_bench_nifty.csv"]:
        rows = list(csv.reader(f.open()))
        keep = [rows[0]] + [r for r in rows[1:] if r and r[0] <= as_of]
        name = "_bench_nifty.csv" if f.name == "breakout_bench_nifty.csv" else f"{_symbol(f)}.csv"
        with (out / name).open("w", newline="") as fh:
            csv.writer(fh).writerows(keep)
    return out


def full_daily(mode: str, symbol: str) -> list[dict]:
    """All daily bars known for a symbol (for paper GTT fills and the hindsight chart)."""
    src = None
    if mode == "demo":
        src = next((f for f in _universe_files() if _symbol(f) == symbol.upper()), None)
    else:
        days = sorted((d for d in DAILY.glob("*") if (d / f"{symbol.upper()}.csv").exists()), reverse=True)
        src = days[0] / f"{symbol.upper()}.csv" if days else None
    if not src or not src.exists():
        return []
    out = []
    for r in csv.DictReader(src.open()):
        try:
            out.append({"date": r["Date"][:10], "o": float(r["Open"]), "h": float(r["High"]),
                        "l": float(r["Low"]), "c": float(r["Close"]), "v": float(r.get("Volume") or 0)})
        except (KeyError, ValueError):
            continue
    return out


async def _live_universe(ledger: Ledger, symbols: list[str], day: str) -> Path:
    out = DAILY / day
    out.mkdir(parents=True, exist_ok=True)
    for s in symbols:
        if not (out / f"{s}.csv").exists():
            await run_tool("india.ta.fetch", ["--symbol", s, "--period", "2y", "--out", str(out / f"{s}.csv")],
                           ledger=ledger, purpose="swing:fetch")
    return out


def _gate(step, label, status, summary, run_id=None, required=True):
    return {"step": step, "label": label, "status": status, "summary": summary, "run_id": run_id,
            "required": required, "passed": {"pass": True, "fail": False}.get(status)}


async def scan(ledger: Ledger, mode: str, *, as_of: str | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    day = as_of or (DEMO_SWING_DAY if mode == "demo" else ideas.clock.ist_now().date().isoformat())
    if mode == "demo":
        folder = demo_universe(day)
        bench = ["--benchmark-csv", str(folder / "_bench_nifty.csv")]
    else:
        syms = symbols or [r["symbol"] for r in brief.today(ledger, "live")["watchlist"]["rows"][:SWING["max_candidates"] * 2]]
        if not syms:
            return {"as_of": day, "error": "No symbols: run the evening scan first.", "decisions": []}
        folder = await _live_universe(ledger, syms, day)
        bench = ["--benchmark", "NIFTY"]
    cfg = default_config()
    sc = await run_tool("india.breakout.scan", ["--csv-dir", str(folder), "--pattern", "[!_]*.csv", *bench],
                        ledger=ledger, config=cfg, purpose=f"swing:{mode}")
    results = (sc.get("output_json") or {}).get("results", [])
    already = ledger.decided_symbols(mode, day, "swing")
    cands = [r for r in results if r.get("verdict") in ("actionable", "watch") and r["name"].upper() not in already]
    cands = sorted(cands, key=lambda r: -(r.get("rank_score") or 0))[: SWING["max_candidates"]]

    regime = await run_tool("india.regime.status", ["--csv", "{india_fx}/regime_novolume.csv", "--volume-csv",
                                                    "{india_fx}/regime_proxy_volume.csv", "--name", "NIFTY 50 (demo data)"]
                            if mode == "demo" else ["--symbol", "NIFTY"], ledger=ledger, as_of=f"{day} 18:00",
                            purpose=f"swing:{mode}")
    made = []
    for c in cands:
        made.append(await _decide(ledger, mode, day, folder, c, sc["id"], regime, bench))
    return {"as_of": day, "mode": mode, "scanned": len(results), "scan_run_id": sc["id"],
            "verdicts": {r["name"].upper(): r.get("verdict") for r in results},
            "decisions": [{"id": d["id"], "symbol": d["symbol"], "verdict": d["verdict"], "score": d["score"]} for d in made]}


async def _decide(ledger: Ledger, mode: str, day: str, folder: Path, cand: dict, scan_run: str, regime: dict,
                  bench: list[str]) -> dict:
    sym = cand["name"].upper()
    f = str(folder / f"{sym}.csv")
    s = SWING
    nxt = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    to = (dt.date.fromisoformat(day) + dt.timedelta(days=int(s["hold_days"] * 1.5))).isoformat()
    plan_r, bt_r, ev_r, ex_r = await asyncio.gather(
        run_tool("india.breakout.plan", ["--csv", f, "--capital", str(s["capital_inr"]), "--risk-pct", str(s["risk_per_trade_pct"]),
                                         "--band", str(s["band_pct"]), "--broker", s["broker"], "--hold-days", str(s["hold_days"]),
                                         *bench],
                 ledger=ledger, purpose=f"swing:{mode}"),
        run_tool("india.backtest.run", ["--csv", f, "--strategy", s["backtest_strategy"], "--segment", "delivery",
                                        "--broker", s["broker"]], ledger=ledger, purpose=f"swing:{mode}"),
        run_tool("india.events.range", ["--from", nxt, "--to", to, "--symbols", sym], ledger=ledger,
                 as_of=f"{day} 18:00", purpose=f"swing:{mode}"),
        run_tool("india.exhaustion.climax", ["--csv", f, "--min-turnover-cr", "0"], ledger=ledger, purpose=f"swing:{mode}"),
    )
    pj = plan_r.get("output_json") or {}
    check, plan = pj.get("check") or cand, pj.get("plan") or {}
    check = check | {"verdict": cand.get("verdict")}     # S0 is the scan's call (with relative strength), not a re-derivation
    bt = (bt_r.get("output_json") or {}).get("metrics") or {}
    gates = []
    v = check.get("verdict")
    gates.append(_gate("S0", "Base ready (scan verdict)", "pass" if v == "actionable" else "no_data",
                       f"{(check.get('base') or {}).get('type', 'base')} grade {(check.get('base') or {}).get('grade', '?')}, "
                       f"state {(check.get('base') or {}).get('state', '?')}, {((check.get('base') or {}).get('from_pivot_pct') or 0):+.1f}% "
                       f"from pivot {(check.get('base') or {}).get('pivot')}: scan says {v}.", scan_run))
    tt = check.get("trend_template") or {}
    missed = [c["label"] + (f" ({c['detail']})" if c.get("detail") else "") for c in tt.get("criteria") or [] if c.get("pass") is False]
    gates.append(_gate("S1", "Stage-2 trend template", "pass" if tt.get("stage2") else "fail",
                       f"{tt.get('passed')}/{tt.get('total')} trend criteria pass." + (f" Missing: {'; '.join(missed)}." if missed else ""),
                       plan_r["id"]))
    liq = check.get("liquidity") or {}
    gates.append(_gate("S2", "Liquidity", "pass" if liq.get("ok") else "fail",
                       f"Average traded value ₹{(liq.get('avg_traded_value_cr') or 0):.1f} cr a day (minimum {liq.get('min_cr')}).", plan_r["id"]))
    reg = ((regime.get("output_json") or {}).get("regime") or {})
    gates.append(_gate("S3", "Market regime", "no_data" if not reg else "fail" if reg.get("label") == "Correction" else "pass",
                       f"{reg.get('label', 'unknown')}: exposure ceiling {reg.get('exposure_ceiling_pct', '?')}%.", regime["id"]))
    evs = (ev_r.get("output_json") or {}).get("events", [])
    own = [e for e in evs if (e.get("symbol") or "").upper() == sym]
    big = [e for e in evs if e.get("impact") == "high" and not e.get("symbol")]
    gates.append(_gate("S4", "No company event in the holding window",
                       "fail" if own else "pass",
                       (f"{own[0]['title']} on {own[0]['date']}" if own else f"No company event before {to}.")
                       + (f" Market events to note: {', '.join(e['title'] for e in big[:3])}." if big else ""), ev_r["id"]))
    exr = ((ex_r.get("output_json") or {}).get("results") or [{}])[0]
    gates.append(_gate("S5", "Not a buying climax", "fail" if exr.get("stage") == "climax" else
                       ("pass" if exr else "no_data"), f"Exhaustion stage {exr.get('stage') or 'none'}, score {exr.get('score')}.",
                       ex_r["id"], required=False))
    n = bt.get("trades") or 0
    if n < s["min_backtest_trades"]:
        gates.append(_gate("B1", "Breakout history on this stock", "no_data",
                           f"Only {n} past breakout trade(s) in the data: too thin to judge.", bt_r["id"]))
    else:
        ok = (bt.get("expectancy_r") or 0) > 0 and (bt.get("profit_factor") or 0) > 1
        gates.append(_gate("B1", "Breakout history on this stock", "pass" if ok else "fail",
                           f"{n} trades, {bt.get('win_rate_pct', 0):.0f}% wins, {bt.get('expectancy_r', 0):+.2f}R a trade, "
                           f"profit factor {bt.get('profit_factor')}.", bt_r["id"]))
    if not plan.get("trigger") or not plan.get("qty"):
        gates.append(_gate("P1", "A tradable plan", "fail", "The planner could not build an entry/stop/size.", plan_r["id"]))
    verdict, failed, reason = ideas.verdict_of(gates)
    t2 = next((t for t in plan.get("targets") or [] if t["R"] == 2.0), None)
    score = round(min(100, (cand.get("rank_score") or 0) * 0.6 + (40 if verdict == "TAKE" else 20 if verdict == "WATCH" else 0)), 1)
    d = {
        "session_day": day, "decided_at": "18:00", "symbol": sym, "setup": "swing", "verdict": verdict,
        "first_failed_gate": failed, "score": score, "mode": mode, "as_of": f"{day} 18:00", "pipeline_version": "swing-1.0",
        "plan": {k: plan.get(k) for k in ("pivot", "trigger", "limit", "stop", "stop_method", "qty", "R_per_share",
                                          "position_value", "risk_if_stopped", "targets", "band", "orders", "warnings",
                                          "checklist", "charges_stop_out", "allocation_pct")}
                | {"target": t2["price"] if t2 else None, "hold_days": s["hold_days"], "entry_valid_days": s["entry_valid_days"],
                   "plan_run_id": plan_r["id"]},
        "odds": {"backtest": {k: bt.get(k) for k in ("trades", "win_rate_pct", "expectancy_r", "profit_factor", "max_drawdown_pct",
                                                     "cagr_pct", "avg_bars_held", "charges_pct_of_gross_profit", "net_pnl",
                                                     "start_date", "end_date")},
                 "red_flags": (bt_r.get("output_json") or {}).get("red_flags") or [], "strategy": s["backtest_strategy"],
                 "run_id": bt_r["id"]},
        "costs": {"charges_stop_out": plan.get("charges_stop_out"), "cost_pct_used": plan.get("cost_pct_used")},
        "config_snapshot": s,
        "detail": {"reason": reason, "gates": gates, "verdict_rule": SWING_RULE.format(hold=s["hold_days"], mint=s["min_backtest_trades"]),
                   "check": {k: check.get(k) for k in ("base", "trend_template", "liquidity", "rank_score", "freshness", "close")},
                   "mood": {"label": reg.get("label")}, "origin": "swing-scan", "name": sym,
                   "synthetic": mode == "demo",
                   "narrative": _narrative(sym, verdict, reason, plan, bt, check)},
    }
    evidence = [{"step": g["step"], "label": g["label"], "passed": g["passed"], "summary": g["summary"], "run_id": g["run_id"]}
                for g in gates]
    d["id"] = ledger.record_decision(d, evidence)
    return d


def _narrative(sym, verdict, reason, plan, bt, check) -> str:
    base = check.get("base") or {}
    if not plan.get("trigger"):
        return f"{sym}: the planner could not build a trade. {reason}"
    t = {x["R"]: x["price"] for x in plan.get("targets") or []}
    lead = {"TAKE": "Every check passed.", "WATCH": "Worth watching, not yet a trade.", "SKIP": "Saarthi would pass."}[verdict]
    hist = (f"Traded as a breakout on its own history, it made {bt.get('expectancy_r', 0):+.2f}R a trade over "
            f"{bt.get('trades')} trades after costs." if bt.get("trades") else "There is no breakout history to test it on.")
    return (f"{lead} {sym} is building a {base.get('type', 'base')} (grade {base.get('grade', '?')}) with a pivot at "
            f"{base.get('pivot')}. The plan: a GTT buy that triggers at {plan['trigger']:.2f} with a chase limit of "
            f"{plan['limit']:.2f}, stop {plan['stop']:.2f}, targets {t.get(2.0, 0):.2f} (2R) and {t.get(3.0, 0):.2f} (3R), "
            f"{plan['qty']} shares risking ₹{plan.get('risk_if_stopped', 0):,.0f}. {hist}"
            + ("" if verdict == "TAKE" else f" Deciding factor - {reason}"))


def remove_demo_cache() -> None:
    shutil.rmtree(DEMO_SWING_DIR, ignore_errors=True)
