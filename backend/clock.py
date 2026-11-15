"""The NSE clock, straight from nse-trader-skill's nse-common/nsecal.py (imported read-only).

Saarthi never keeps its own holiday list or session times; this module only phrases
nsecal's answers for the UI and the scheduler.
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from backend.skills.registry import ROOT

_NSE_COMMON = str(ROOT / "vendor/nse-trader-skill/nse-common")
if _NSE_COMMON not in sys.path:
    sys.path.insert(0, _NSE_COMMON)

import nsecal  # noqa: E402  (vendored, unmodified)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# Phase boundaries the UI shows on the session ribbon. Open/close/square-off come from
# nsecal; the opening-range length and entry cutoff are the user's config.
OR_MINUTES = 15
NO_ENTRIES_AFTER = dt.time(14, 30)
EVENING_SCAN_AT = dt.time(18, 30)     # after NSE publishes the bhavcopy
PREMARKET_AT = dt.time(8, 30)


def ist_now() -> dt.datetime:
    return dt.datetime.now(IST).replace(tzinfo=None)


def parse(value: str | None) -> dt.datetime:
    if not value:
        return ist_now()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"bad IST time {value!r}")


def _t(d: dt.date, t: dt.time) -> dt.datetime:
    return dt.datetime.combine(d, t)


def session_info(now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or ist_now()
    today = now.date()
    covered = nsecal.covered(today)
    sess = nsecal.session(today) if covered else None
    out: dict[str, Any] = {
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "weekday": now.strftime("%A"),
        "calendar_covered": covered,
        "calendar_through": nsecal.HOLIDAYS_THROUGH,
        "is_session_day": bool(sess),
        "holiday": nsecal.HOLIDAYS.get(today.isoformat()) if not sess else None,
        "muhurat": today.isoformat() in getattr(nsecal, "MUHURAT", {}),
    }
    if sess:
        o, c = sess
        sq = min(nsecal.SQUARE_OFF, c) if c > o else c
        or_end = (_t(today, o) + dt.timedelta(minutes=OR_MINUTES)).time()
        marks = {
            "pre_open": nsecal.PRE_OPEN_START.strftime("%H:%M"),
            "open": o.strftime("%H:%M"),
            "or_end": or_end.strftime("%H:%M"),
            "no_new_entries": min(NO_ENTRIES_AFTER, sq).strftime("%H:%M"),
            "square_off": sq.strftime("%H:%M"),
            "close": c.strftime("%H:%M"),
        }
        out["marks"] = marks
        out["phase"] = _phase(now.time(), o, c, or_end, sq)
        span = (_t(today, c) - _t(today, o)).total_seconds()
        out["progress"] = max(0.0, min(1.0, (now - _t(today, o)).total_seconds() / span)) if span else 0
    else:
        out["phase"] = "closed"
        out["marks"] = None
        out["progress"] = None
    try:
        nxt = nsecal.next_session_day(today) if not (sess and now.time() < sess[1]) else today
        out["next_session"] = nxt.isoformat() if nxt else None
    except Exception:  # past the published table
        out["next_session"] = None
    try:
        out["prev_session"] = nsecal.prev_session_day(today).isoformat()
    except Exception:
        out["prev_session"] = None
    return out


def _phase(t: dt.time, o: dt.time, c: dt.time, or_end: dt.time, sq: dt.time) -> str:
    if t < nsecal.PRE_OPEN_START:
        return "pre_market"
    if t < o:
        return "pre_open"
    if t < or_end:
        return "opening_range"
    if t < NO_ENTRIES_AFTER:
        return "entry_window"
    if t < sq:
        return "manage_only"
    if t < c:
        return "square_off"
    return "post_close"


def target_session_day(job: str, now: dt.datetime) -> dt.date | None:
    """Which session a job prepares for. The evening scan after a session prepares the NEXT one;
    the pre-market brief prepares today (or the next session on a non-trading day)."""
    d = now.date()
    if job == "evening_scan":
        return nsecal.next_session_day(d)
    if nsecal.covered(d) and nsecal.session(d):
        return d
    return nsecal.next_session_day(d)


def due_jobs(now: dt.datetime, already_done) -> list[tuple[str, dt.date]]:
    """Scheduler rule, pure for testing. already_done(job, session_day_iso) -> bool."""
    out = []
    d = now.date()
    is_session = nsecal.covered(d) and bool(nsecal.session(d))
    if is_session and now.time() >= EVENING_SCAN_AT:
        target = nsecal.next_session_day(d)
        if target and not already_done("evening_scan", target.isoformat()):
            out.append(("evening_scan", target))
    if is_session and PREMARKET_AT <= now.time() < nsecal.SESSION_CLOSE:
        if not already_done("premarket_brief", d.isoformat()):
            out.append(("premarket_brief", d))
    return out
