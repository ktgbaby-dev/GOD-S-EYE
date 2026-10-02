"""Activity analytics, computed from the lead database on every request. No stored or estimated figures."""
from datetime import timedelta

from . import normalize as N
from .db import Conn
from .settings import STATUSES


def compute(conn: Conn, strategy: dict, days: int = 30) -> dict:
    now = N.utcnow()
    tz = strategy["timezone"]
    total = int(conn.scalar("SELECT COUNT(*) AS n FROM leads") or 0)
    if total == 0:
        return {"empty": True, "total": 0}
    one = lambda sql, p=(): int(conn.scalar(sql, p) or 0)  # noqa: E731
    contacted = one("SELECT COUNT(*) AS n FROM leads WHERE last_contacted_at IS NOT NULL")
    clients = one("SELECT COUNT(*) AS n FROM leads WHERE status = 'client'")
    follow_up = one("SELECT COUNT(*) AS n FROM leads WHERE status = 'follow_up'")
    avg = conn.scalar("SELECT AVG(score) AS a FROM leads")
    by_status = {r["status"]: int(r["n"]) for r in conn.all("SELECT status, COUNT(*) AS n FROM leads GROUP BY status")}
    by_platform = [{"key": r["platform"], "label": N.platform_label(r["platform"]), "count": int(r["n"])}
                   for r in conn.all("SELECT platform, COUNT(*) AS n FROM leads GROUP BY platform ORDER BY n DESC")]
    genres: dict[str, int] = {}
    unknown_genre = 0
    for r in conn.all("SELECT genre, COUNT(*) AS n FROM leads GROUP BY genre"):
        parts = [g.strip() for g in (r["genre"] or "").split(",") if g.strip()]
        if not parts:
            unknown_genre += int(r["n"])
        for g in parts[:1]:  # primary genre only, so the bars add up to the lead count
            genres[g] = genres.get(g, 0) + int(r["n"])
    by_genre = [{"label": g, "count": n} for g, n in sorted(genres.items(), key=lambda kv: -kv[1])[:10]]
    by_source = [{"label": r["source"] or "Unknown", "count": int(r["n"])} for r in conn.all(
        "SELECT source, COUNT(*) AS n FROM leads GROUP BY source ORDER BY n DESC LIMIT 8")]
    by_provenance = {r["provenance"]: int(r["n"]) for r in conn.all(
        "SELECT provenance, COUNT(*) AS n FROM leads GROUP BY provenance")}

    start = N.local_day_start(tz, days - 1, ref=now)
    volume = {}
    for i in range(days):
        d = (start + timedelta(days=i, hours=12)).astimezone(N.get_tz(tz)).strftime("%Y-%m-%d")
        volume[d] = 0
    for r in conn.all("SELECT discovered_at FROM leads WHERE discovered_at >= ?", (N.iso(start),)):
        d = N.local_date_str(r["discovered_at"], tz)
        if d in volume:
            volume[d] += 1
    contacted_daily = {d: 0 for d in volume}
    for r in conn.all("SELECT last_contacted_at FROM leads WHERE last_contacted_at >= ?", (N.iso(start),)):
        d = N.local_date_str(r["last_contacted_at"], tz)
        if d in contacted_daily:
            contacted_daily[d] += 1
    bands = [("0–39", 0, 39), ("40–59", 40, 59), ("60–79", 60, 79), ("80–100", 80, 100)]
    score_bands = [{"label": lbl, "count": one("SELECT COUNT(*) AS n FROM leads WHERE score >= ? AND score <= ?",
                                               (lo, hi))} for lbl, lo, hi in bands]
    batches = one("SELECT COUNT(*) AS n FROM batches WHERE kind IN ('drop', 'scan')")
    filtered = one("SELECT COUNT(*) AS n FROM candidates WHERE outcome = 'filtered'")
    return {
        "empty": False,
        "totals": {"discovered": total, "contacted": contacted, "follow_ups": follow_up, "clients": clients,
                   "avg_score": round(float(avg or 0), 1),
                   "conversion": round(clients / contacted * 100, 1) if contacted else None,
                   "scans": batches, "noise_filtered": filtered},
        "funnel": [{"key": k, "label": label, "count": by_status.get(k, 0)} for k, label, _d in STATUSES],
        "by_platform": by_platform, "by_genre": by_genre, "unknown_genre": unknown_genre,
        "by_source": by_source, "by_provenance": by_provenance, "score_bands": score_bands,
        "volume": [{"date": d, "discovered": n, "contacted": contacted_daily[d]} for d, n in volume.items()],
        "days": days,
    }
