"""Today's Drop, the dashboard briefing, follow-ups and visit tracking. All numbers come from the database."""
from datetime import timedelta

from . import leads as L
from . import normalize as N
from .db import Conn, loads
from .settings import get_meta, set_meta

RESCORE_HOURS = 6
VISIT_GAP_MINUTES = 30


def maybe_rescore(conn: Conn, strategy: dict, force: bool = False) -> None:
    """Freshness and activity signals depend on today's date, so stored scores are refreshed every few hours."""
    last = N.parse_dt(get_meta(conn, "rescored_at"))
    if force or last is None or (N.utcnow() - last).total_seconds() > RESCORE_HOURS * 3600:
        L.rescore_all(conn, strategy)
        set_meta(conn, "rescored_at", N.now_iso())


def register_visit(conn: Conn) -> str | None:
    """Return when the previous visit was (None on the very first visit).
    A visit = dashboard opens less than 30 minutes apart."""
    now = N.utcnow()
    current = N.parse_dt(get_meta(conn, "visit_current"))
    previous = get_meta(conn, "visit_previous")
    if current is None:
        set_meta(conn, "visit_previous", "")
        set_meta(conn, "visit_current", N.iso(now))
        return None
    if (now - current).total_seconds() > VISIT_GAP_MINUTES * 60:
        previous = N.iso(current)
        set_meta(conn, "visit_previous", previous)
    set_meta(conn, "visit_current", N.iso(now))
    return previous or None


def _batches_since(conn: Conn, since_iso: str, kinds=("drop", "scan")) -> list[dict]:
    rows = conn.all(f"SELECT * FROM batches WHERE started_at >= ? AND kind IN ({', '.join('?' for _ in kinds)}) "
                    "ORDER BY started_at DESC", (since_iso, *kinds))
    return [{"id": r["id"], "kind": r["kind"], "status": r["status"], "started_at": r["started_at"],
             "finished_at": r["finished_at"], "stats": loads(r["stats"], {}), "errors": loads(r["errors"], []),
             "notes": loads(r["notes"], [])} for r in rows]


def last_scan(conn: Conn) -> dict | None:
    r = conn.one("SELECT * FROM batches WHERE kind IN ('drop', 'scan') AND finished_at IS NOT NULL "
                 "ORDER BY finished_at DESC LIMIT 1")
    if not r:
        return None
    return {"id": r["id"], "kind": r["kind"], "finished_at": r["finished_at"], "stats": loads(r["stats"], {}),
            "errors": loads(r["errors"], [])}


def today_drop(conn: Conn, strategy: dict) -> dict:
    now = N.utcnow()
    start = N.local_day_start(strategy["timezone"], ref=now)
    rows = conn.all("SELECT * FROM leads WHERE discovered_at >= ?", (N.iso(start),))
    leads = [L.serialize(r, strategy, now) for r in rows]
    dismissed = sum(1 for l in leads if l["status"] == "not_fit")
    live = [l for l in leads if l["status"] != "not_fit"]
    live.sort(key=lambda l: l["discovered_at"], reverse=True)
    live.sort(key=L.priority, reverse=True)
    target = strategy["daily_target"]
    week_start = N.local_day_start(strategy["timezone"], 6, ref=now)
    earlier_rows = conn.all("SELECT * FROM leads WHERE status = 'new' AND discovered_at >= ? AND discovered_at < ? "
                            "AND score >= ? ORDER BY score DESC LIMIT 60",
                            (N.iso(week_start), N.iso(start), strategy["keep_min_score"]))
    earlier = [l for l in (L.serialize(r, strategy, now) for r in earlier_rows) if l["freshness"] != "stale"]
    earlier.sort(key=L.priority, reverse=True)
    return {
        "date": now.astimezone(N.get_tz(strategy["timezone"])).strftime("%Y-%m-%d"),
        "items": live[:target], "total_today": len(live), "overflow": max(0, len(live) - target),
        "dismissed": dismissed, "high_priority": sum(1 for l in live if l["high_priority"]),
        "reviewed": sum(1 for l in live if l["status"] != "new"),
        "earlier": earlier[:10], "earlier_total": len(earlier), "target": target,
        "batches": _batches_since(conn, N.iso(start)), "last_scan": last_scan(conn),
    }


def drop_ran_today(conn: Conn, strategy: dict) -> bool:
    start = N.local_day_start(strategy["timezone"])
    return bool(conn.scalar("SELECT COUNT(*) AS n FROM batches WHERE kind = 'drop' AND started_at >= ? "
                            "AND status = 'done'", (N.iso(start),)))


def follow_ups(conn: Conn, strategy: dict) -> dict:
    now = N.utcnow()
    rows = conn.all("SELECT * FROM leads WHERE status IN ('contacted', 'follow_up') "
                    "ORDER BY CASE WHEN follow_up_at IS NULL THEN 0 ELSE 1 END, follow_up_at ASC")
    items = [L.serialize(r, strategy, now) for r in rows]
    due = [l for l in items if l["follow_up_due"]]
    upcoming = [l for l in items if not l["follow_up_due"]]
    week_ago = N.iso(now - timedelta(days=7))
    recent_clients = conn.all("SELECT * FROM leads WHERE status = 'client' AND status_changed_at >= ? "
                              "ORDER BY status_changed_at DESC LIMIT 10", (week_ago,))
    return {"due": due, "upcoming": upcoming,
            "recent_clients": [L.serialize(r, strategy, now) for r in recent_clients]}


def dashboard(conn: Conn, strategy: dict) -> dict:
    now = N.utcnow()
    previous_visit = register_visit(conn)
    start = N.iso(N.local_day_start(strategy["timezone"], ref=now))
    stale_cut = N.iso(now - timedelta(days=strategy["stale_days"]))
    total = int(conn.scalar("SELECT COUNT(*) AS n FROM leads") or 0)
    new_today = int(conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE discovered_at >= ? AND status <> 'not_fit'",
                                (start,)) or 0)
    high = int(conn.scalar(
        "SELECT COUNT(*) AS n FROM leads WHERE status IN ('new', 'watching', 'contact') AND score >= ? AND NOT "
        "((last_activity_at IS NOT NULL AND last_activity_at < ?) OR (last_activity_at IS NULL AND last_seen_at < ?))",
        (strategy["score_threshold"], stale_cut, stale_cut)) or 0)
    since_visit = int(conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE discovered_at > ?", (previous_visit,)) or 0)         if previous_visit else 0
    due = int(conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE status IN ('contacted', 'follow_up') AND "
                          "(follow_up_at IS NULL OR follow_up_at <= ?)", (N.iso(now),)) or 0)
    contact_ready = int(conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE status = 'contact'") or 0)
    unreviewed = int(conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE status = 'new'") or 0)
    filtered_today = int(conn.scalar(
        "SELECT COUNT(*) AS n FROM candidates WHERE outcome = 'filtered' AND created_at >= ?", (start,)) or 0)
    prospects = L.top_prospects(conn, strategy, limit=8)
    fu = follow_ups(conn, strategy)["due"][:4]
    return {
        "stats": {"new_today": new_today, "high_priority": high, "new_since_visit": since_visit,
                  "follow_up_ready": due, "contact_ready": contact_ready, "unreviewed": unreviewed,
                  "noise_filtered_today": filtered_today, "total": total},
        "previous_visit": previous_visit, "prospects": prospects, "follow_ups": fu,
        "last_scan": last_scan(conn), "drop_ran_today": drop_ran_today(conn, strategy),
        "date": now.astimezone(N.get_tz(strategy["timezone"])).strftime("%Y-%m-%d"),
    }
