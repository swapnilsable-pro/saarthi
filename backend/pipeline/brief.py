"""Assemble the Today screen from the latest evening scan and pre-market brief.

Every value here is read from a stored tool run and carries that run's id so the UI can open
the evidence. The only logic of Saarthi's own is the mood rule below: a fixed mapping from the
regime tool's label, plus two documented downgrades, returned with the answer so the user can
see exactly how it was reached.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from backend import clock
from backend.ledger.db import Ledger

LEVELS = ["stand_aside", "caution", "go"]
REGIME_TO_LEVEL = {
    "Confirmed uptrend": "go",
    "Uptrend under pressure": "caution",
    "Rally attempt": "caution",
    "Correction": "stand_aside",
}
BREADTH_WEAK_BELOW = 30          # breadth score (0-100) under this downgrades one level
MOOD_RULE = (
    "Start from the market-regime label: Confirmed uptrend = Go; Uptrend under pressure or "
    "Rally attempt = Caution; Correction = Stand aside. Then step down one level if breadth "
    f"scores below {BREADTH_WEAK_BELOW}/100, and one more if a high-impact event falls on the "
    "session day. Nothing else changes the mood."
)
HEADLINES = {
    "go": "Conditions support taking valid setups at normal size.",
    "caution": "Trade smaller and only the cleanest setups.",
    "stand_aside": "The market is in correction. Protect capital; new long entries are not favoured.",
    "unknown": "Market regime unavailable; run the pre-market brief.",
}


class Evidence:
    """Loads tool outputs for a job run, remembering which run each value came from."""

    def __init__(self, ledger: Ledger, job: dict | None):
        self.job = job
        self.outputs: dict[str, Any] = {}
        self.run_ids: dict[str, str] = {}
        self.status: dict[str, dict] = {}
        if not job:
            return
        for key, step in job["steps"].items():
            self.status[key] = {k: v for k, v in step.items() if k != "optional"}
            rid = step.get("tool_run_id")
            if rid:
                self.run_ids[key] = rid
                run = ledger.get_run(rid)
                if run and run["status"] == "ok":
                    self.outputs[key] = run["output_json"]

    def get(self, key: str) -> Any:
        return self.outputs.get(key)


def _down(level: str) -> str:
    i = LEVELS.index(level)
    return LEVELS[max(0, i - 1)]


def _events_on(events: list[dict], day: str) -> list[dict]:
    out = []
    for e in events:
        start, end = e.get("date") or "", e.get("end") or e.get("date") or ""
        if start <= day <= end:
            out.append(e)
    return out


def market_mood(pm: Evidence, session_day: str) -> dict[str, Any]:
    regime_out = pm.get("regime")
    factors: list[dict[str, Any]] = []
    if not regime_out:
        return {"level": "unknown", "headline": HEADLINES["unknown"], "regime": None,
                "factors": [], "rule": MOOD_RULE}

    reg = regime_out.get("regime", {})
    trend = regime_out.get("trend", {})
    label = reg.get("label", "")
    level = REGIME_TO_LEVEL.get(label, "caution")
    factors.append({"label": "Market regime", "value": label, "effect": "base",
                    "detail": reg.get("stance"), "step": "regime", "run_id": pm.run_ids.get("regime")})

    breadth = pm.get("breadth")
    if breadth and breadth.get("score"):
        sc = breadth["score"]
        weak = sc.get("value") is not None and sc["value"] < BREADTH_WEAK_BELOW
        if weak:
            level = _down(level)
        factors.append({"label": "Breadth", "value": f'{sc.get("value", 0):.0f}/100 · {sc.get("label", "")}',
                        "effect": "down" if weak else "none", "detail": breadth.get("read"),
                        "step": "breadth", "run_id": pm.run_ids.get("breadth")})

    events = (pm.get("events") or {}).get("events", [])
    high_today = [e for e in _events_on(events, session_day) if e.get("impact") == "high"]
    if high_today:
        level = _down(level)
    factors.append({"label": "High-impact events on session day",
                    "value": ", ".join(e["title"] for e in high_today) or "None",
                    "effect": "down" if high_today else "none", "step": "events",
                    "run_id": pm.run_ids.get("events")})

    sectors = pm.get("sectors")
    if sectors and sectors.get("rotation"):
        rot = sectors["rotation"]
        factors.append({"label": "Sector tilt", "value": rot.get("tilt"), "effect": "info",
                        "detail": rot.get("reason"), "step": "sectors", "run_id": pm.run_ids.get("sectors")})

    return {
        "level": level,
        "headline": HEADLINES[level],
        "regime": {
            "index": regime_out.get("name"),
            "as_of": regime_out.get("as_of"),
            "label": label,
            "exposure_ceiling_pct": reg.get("exposure_ceiling_pct"),
            "max_new_positions": reg.get("max_new_positions"),
            "stance": reg.get("stance"),
            "close": trend.get("close"),
            "vs_sma50_pct": trend.get("vs_sma50_pct"),
            "vs_sma200_pct": trend.get("vs_sma200_pct"),
            "drawdown_pct": trend.get("drawdown_pct"),
            "distribution_days_25": ((regime_out.get("distribution") or {}).get("counts") or {}).get("d25"),
            "what_would_change": regime_out.get("what_would_change") or [],
        },
        "factors": factors,
        "rule": MOOD_RULE,
    }


def event_risk(pm: Evidence, session_day: str) -> dict[str, Any]:
    out = pm.get("events") or {}
    events = out.get("events", [])
    today = _events_on(events, session_day)
    upcoming = [e for e in events if (e.get("date") or "") > session_day][:12]
    high = [e for e in today if e.get("impact") == "high"]
    holiday = [e for e in today if e.get("category") == "holiday"]
    return {
        "session_day": session_day,
        "today": [_event_view(e) for e in today],
        "upcoming": [_event_view(e) for e in upcoming],
        "gate": {"blocked": bool(high),
                 "reason": ("High-impact event today: " + ", ".join(e["title"] for e in high)) if high
                 else "No high-impact event on the session day."},
        "holiday": holiday[0]["title"] if holiday else None,
        "run_id": pm.run_ids.get("events"),
    }


def _event_view(e: dict) -> dict:
    return {k: e.get(k) for k in ("date", "end", "title", "category", "impact", "time_ist", "symbol",
                                  "why", "uncertain", "weekday")}


def watchlist(ev: Evidence, pm: Evidence, session_day: str) -> dict[str, Any]:
    daily = ev.get("daily") or {}
    deals = (ev.get("deals") or {}).get("aggregated", [])
    results = (ev.get("results") or {}).get("items", [])
    news = (pm.get("news") or {}).get("items", [])

    deals_by: dict[str, list] = {}
    for d in deals:
        deals_by.setdefault(d["symbol"], []).append(d)
    results_by: dict[str, list] = {}
    for r in results:
        results_by.setdefault(r.get("symbol", ""), []).append(r)
    news_by: dict[str, list] = {}
    for n in news:
        news_by.setdefault(n.get("symbol", ""), []).append(n)

    rows = []
    for h in daily.get("hits", []):
        sym = h["symbol"]
        close, prev = h.get("close"), h.get("prev_close")
        flags = []
        if h.get("band_pct") is not None:
            flags.append({"kind": "band", "text": f'{h["band_pct"]}% price band'})
        if h.get("asm"):
            flags.append({"kind": "asm", "text": f'ASM: {h["asm"]}'})
        sym_deals = deals_by.get(sym, [])
        sym_results = results_by.get(sym, [])
        if sym_results:
            flags.append({"kind": "results", "text": "Results: " + sym_results[0].get("date", "")})
        rows.append({
            "symbol": sym,
            "name": h.get("name"),
            "setups": h.get("setups", []),
            "close": close,
            "change_pct": round((close - prev) / prev * 100, 2) if close and prev else None,
            "turnover_cr": round(h["turnover_lacs"] / 100, 1) if h.get("turnover_lacs") is not None else None,
            "delivery_pct": h.get("delivery_pct"),
            "rsi14": h.get("rsi14"),
            "flags": flags,
            "deals": {
                "net_value_cr": round(sum(d.get("net_value_lacs", 0) for d in sym_deals) / 100, 2),
                "clients": [d["client"] for d in sym_deals][:3],
            } if sym_deals else None,
            "filings": [{"time": n.get("time"), "category": n.get("category"), "text": n.get("text"),
                         "tags": n.get("tags"), "url": n.get("url")} for n in news_by.get(sym, [])[:3]],
            "evidence": {k: ev.run_ids.get(k) for k in ("daily", "bands", "deals", "results")}
                        | {"news": pm.run_ids.get("news")},
        })
    return {
        "as_of": daily.get("as_of"),
        "scanned": daily.get("scanned"),
        "sessions": daily.get("sessions"),
        "floors": daily.get("floors"),
        "rows": rows,
        "run_id": ev.run_ids.get("daily"),
        "deals_run_id": ev.run_ids.get("deals"),
        "top_deals": sorted(deals, key=lambda d: -abs(d.get("net_value_lacs", 0)))[:8],
        "results_calendar": results[:20],
    }


def _warnings(pm: Evidence, ev: Evidence) -> list[dict[str, str]]:
    out = []
    for key, src in (("regime", pm), ("breadth", pm), ("sectors", pm)):
        o = src.get(key) or {}
        for text in (o.get("notes") or []) + (o.get("warnings") or []):
            out.append({"step": key, "text": str(text).lstrip("⚠ ").strip(), "run_id": src.run_ids.get(key)})
    for src in (ev, pm):
        for key, st in src.status.items():
            if st.get("status") == "skipped":
                out.append({"step": key, "text": st.get("reason", "skipped"), "run_id": None})
            elif st.get("status") not in ("ok", None):
                out.append({"step": key, "text": f"{st['tool_id']} {st['status']}", "run_id": st.get("tool_run_id")})
    return out


def _job_view(job: dict | None) -> dict | None:
    if not job:
        return None
    return {k: job[k] for k in ("id", "job", "mode", "session_day", "as_of", "status", "started_at",
                                "duration_ms", "trigger", "created_at")}


def today(ledger: Ledger, mode: str, session_day: str | None = None) -> dict[str, Any]:
    """The brief for the latest prepared session, or for one specific session (point-in-time:
    a replayed day only ever sees the jobs that were prepared for that day)."""
    ev_job = ledger.latest_job("evening_scan", mode, session_day)
    pm_job = ledger.latest_job("premarket_brief", mode, session_day)
    ev, pm = Evidence(ledger, ev_job), Evidence(ledger, pm_job)

    if mode == "demo":
        now = clock.parse((pm_job or ev_job or {}).get("as_of") or "2026-11-11 08:30")
    else:
        now = clock.ist_now()
    session_day = session_day or (pm_job or ev_job or {}).get("session_day") or now.date().isoformat()

    sectors = pm.get("sectors") or {}
    breadth = pm.get("breadth") or {}
    news = (pm.get("news") or {}).get("items", [])
    return {
        "mode": mode,
        "clock": clock.session_info(now),
        "session_day": session_day,
        "jobs": {"evening_scan": _job_view(ev_job), "premarket_brief": _job_view(pm_job)},
        "mood": market_mood(pm, session_day),
        "events": event_risk(pm, session_day),
        "watchlist": watchlist(ev, pm, session_day),
        "sectors": {
            "tilt": (sectors.get("rotation") or {}).get("tilt"),
            "summary": sectors.get("summary"),
            "size_read": (sectors.get("size_read") or {}).get("read"),
            "leaders": [{"label": s["label"], "quadrant": s["quadrant"], "score": s.get("score")}
                        for s in sorted(sectors.get("sectors", []), key=lambda s: -(s.get("score") or 0))[:6]],
            "run_id": pm.run_ids.get("sectors"),
        } if sectors else None,
        "breadth": {
            "score": (breadth.get("score") or {}).get("value"),
            "label": (breadth.get("score") or {}).get("label"),
            "read": breadth.get("read"),
            "advances": (breadth.get("advance_decline") or {}).get("advances"),
            "declines": (breadth.get("advance_decline") or {}).get("declines"),
            "run_id": pm.run_ids.get("breadth"),
        } if breadth else None,
        "news": {"items": news[:10], "count": len(news), "run_id": pm.run_ids.get("news")},
        "warnings": _warnings(pm, ev),
    }
