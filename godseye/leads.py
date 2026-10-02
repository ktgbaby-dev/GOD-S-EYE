"""Lead repository: create, merge re-sightings, edit, status workflow, search/filter, freshness, rescoring."""
from datetime import datetime, timedelta

from . import normalize as N
from . import scoring
from .db import Conn, dumps, loads
from .settings import ACTIVE_STATUSES, STATUS_KEYS, STATUSES

MAX_EVIDENCE = 15
EDITABLE = ("name", "handle", "platform", "profile_url", "genre", "location", "followers", "bio", "notes", "source",
            "source_url", "last_activity_at", "last_release_at", "follow_up_at")


class LeadError(ValueError):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


# ------------------------------------------------------------------------------------------------ freshness

def is_stale(row: dict, stale_days: int, now: datetime) -> bool:
    ref = row.get("last_activity_at") or row.get("last_seen_at")
    d = N.days_since(ref, now)
    return d is not None and d > stale_days


def freshness(row: dict, strategy: dict, now: datetime) -> str:
    today = N.local_day_start(strategy["timezone"], ref=now)
    disc = N.parse_dt(row.get("discovered_at"))
    if disc and disc >= today:
        return "new_today"
    if is_stale(row, strategy["stale_days"], now):
        return "stale"
    return "seen_before"


def follow_up_due(row: dict, now: datetime) -> bool:
    if row.get("status") not in ("contacted", "follow_up"):
        return False
    due = N.parse_dt(row.get("follow_up_at"))
    return due is None or due <= now


# ------------------------------------------------------------------------------------------------ serialization

def serialize(row: dict, strategy: dict, now: datetime, handles: list[dict] | None = None) -> dict:
    out = dict(row)
    out["score_breakdown"] = loads(row.get("score_breakdown"), {})
    out["evidence"] = loads(row.get("evidence"), [])
    out["platform_label"] = N.platform_label(row["platform"])
    out["followers_label"] = N.fmt_count(row.get("followers"))
    out["freshness"] = freshness(row, strategy, now)
    out["high_priority"] = row["score"] >= strategy["score_threshold"]
    out["follow_up_due"] = follow_up_due(row, now)
    out["is_demo"] = bool(row.get("is_demo"))
    if handles is not None:
        out["handles"] = handles
    return out


def handles_for(conn: Conn, lead_id: int) -> list[dict]:
    rows = conn.all("SELECT platform, handle, url, provenance, source FROM lead_handles WHERE lead_id = ? ORDER BY id",
                    (lead_id,))
    for r in rows:
        r["platform_label"] = N.platform_label(r["platform"])
        r["url"] = r["url"] or N.profile_url_for(r["platform"], r["handle"])
    return rows


def get(conn: Conn, lead_id: int) -> dict | None:
    return conn.one("SELECT * FROM leads WHERE id = ?", (lead_id,))


def find_by_handle(conn: Conn, platform: str, handle: str) -> int | None:
    return conn.scalar("SELECT lead_id FROM lead_handles WHERE platform = ? AND handle_norm = ?",
                       (platform, N.norm_handle(handle)))


def log(conn: Conn, lead_id: int, kind: str, detail: str = "") -> None:
    conn.insert("activities", {"lead_id": lead_id, "kind": kind, "detail": detail[:500], "created_at": N.now_iso()})


# ------------------------------------------------------------------------------------------------ scoring

def _score_input(row: dict) -> dict:
    data = dict(row)
    data["evidence"] = loads(row.get("evidence"), []) if isinstance(row.get("evidence"), str) else row.get("evidence") or []
    return data


def apply_score(row: dict, strategy: dict, now: datetime | None = None) -> dict:
    """Score a lead dict and return the columns to store."""
    res = scoring.score_lead(_score_input(row), strategy, now)
    return {"score": res["score"], "score_breakdown": dumps(res["breakdown"]), "reason": res["reason"],
            "last_activity_at": res["last_activity_at"], "last_release_at": res["last_release_at"]}


def rescore(conn: Conn, lead_id: int, strategy: dict) -> dict:
    row = get(conn, lead_id)
    cols = apply_score(row, strategy)
    conn.update("leads", lead_id, cols)
    return {**row, **cols}


def rescore_all(conn: Conn, strategy: dict) -> int:
    now = N.utcnow()
    changed = 0
    for row in conn.all("SELECT * FROM leads"):
        cols = apply_score(row, strategy, now)
        if any(str(row.get(k)) != str(v) for k, v in cols.items() if k != "score_breakdown") or \
                loads(row["score_breakdown"], {}).get("items") != loads(cols["score_breakdown"], {}).get("items"):
            conn.update("leads", row["id"], cols)
            changed += 1
    return changed


# ------------------------------------------------------------------------------------------------ create / merge

def clean_input(data: dict, partial: bool = False) -> dict:
    """Validate user-supplied lead fields (manual add, edit, import)."""
    out: dict = {}
    if "profile_url" in data:
        raw = str(data.get("profile_url") or "").strip()
        out["profile_url"] = N.safe_url(raw)
        if raw and not out["profile_url"]:
            raise LeadError("Profile URL must be a web address (https://…)")
    if "platform" in data or not partial:
        out["platform"] = N.norm_platform(str(data.get("platform") or ""))
    if "handle" in data or not partial:
        out["handle"] = N.clean_handle(str(data.get("handle") or ""))
    if not partial and out.get("profile_url") and (not out.get("handle") or not out.get("platform")):
        parsed = N.parse_profile_url(out["profile_url"])
        if parsed:
            out["platform"] = out.get("platform") or parsed[0]
            out["handle"] = out.get("handle") or parsed[1]
    if not partial:
        if not out.get("handle"):
            raise LeadError("Handle is required (or a profile URL GOD'S EYE can read a handle from)")
        if not out.get("platform"):
            raise LeadError("Platform is required")
    if out.get("handle") is not None and "handle" in out:
        if not out["handle"] and partial:
            raise LeadError("Handle can't be empty")
        if out["handle"] and not N.valid_handle(out.get("platform") or "other", out["handle"]):
            raise LeadError("That handle has characters the platform doesn't allow")
    for key, limit in (("name", 120), ("genre", 80), ("location", 120), ("source", 80)):
        if key in data or (not partial and key == "name"):
            out[key] = " ".join(str(data.get(key) or "").split())[:limit]
    if not partial and not out.get("name"):
        out["name"] = out["handle"]
    for key, limit in (("bio", 2000), ("notes", 5000)):
        if key in data:
            out[key] = str(data.get(key) or "").strip()[:limit]
    if "source_url" in data:
        out["source_url"] = N.safe_url(str(data.get("source_url") or ""))
    if "followers" in data:
        raw = data.get("followers")
        n = N.parse_count(raw)
        if raw not in (None, "") and n is None:
            raise LeadError("Followers must be a number like 12400 or 12.4K")
        out["followers"] = n
    for key in ("last_activity_at", "last_release_at", "follow_up_at"):
        if key in data:
            raw = data.get(key)
            dt = N.parse_dt(raw) if raw else None
            if raw and dt is None:
                raise LeadError(f"{key.replace('_', ' ')} must be a date (YYYY-MM-DD)")
            out[key] = N.iso(dt) if dt else None
    return out


def create(conn: Conn, data: dict, strategy: dict, provenance: str, source: str, *, evidence=None,
           linked=None, batch_id=None, is_demo=False, discovered_at=None, uploads_30d=None) -> int:
    """Insert a lead (data already validated). Raises LeadError(409) if any of its handles is already known."""
    platform, handle = data["platform"], data["handle"]
    existing = find_by_handle(conn, platform, handle)
    if existing:
        raise LeadError("Already in GOD'S EYE", 409, lead_id=existing)
    now = N.now_iso()
    row = {
        "name": data.get("name") or handle, "handle": handle, "handle_norm": N.norm_handle(handle),
        "platform": platform, "profile_url": data.get("profile_url") or N.profile_url_for(platform, handle),
        "genre": data.get("genre", ""), "location": data.get("location", ""), "followers": data.get("followers"),
        "bio": data.get("bio", ""), "status": "new", "provenance": provenance, "source": source[:80],
        "source_url": data.get("source_url", ""), "evidence": dumps((evidence or [])[:MAX_EVIDENCE]),
        "discovered_at": discovered_at or now, "last_seen_at": discovered_at or now, "seen_count": 1,
        "last_activity_at": data.get("last_activity_at"), "last_release_at": data.get("last_release_at"),
        "uploads_30d": uploads_30d, "notes": data.get("notes", ""), "is_demo": 1 if is_demo else 0,
        "batch_id": batch_id, "status_changed_at": discovered_at or now, "created_at": now, "updated_at": now,
    }
    row.update(apply_score(row, strategy))
    lead_id = conn.insert("leads", row)
    _add_handle(conn, lead_id, platform, handle, row["profile_url"], "source" if provenance == "verified" else provenance,
                source)
    for h in linked or []:
        _add_handle(conn, lead_id, h["platform"], h["handle"], h.get("url", ""), h.get("provenance", "linked"),
                    h.get("source", source))
    log(conn, lead_id, "created", {"verified": "Found by discovery", "manual": "Added manually",
                                   "import": "Imported", "demo": "Demo data"}.get(provenance, provenance)
        + (f" · {source}" if source else ""))
    return lead_id


def _add_handle(conn: Conn, lead_id: int, platform: str, handle: str, url: str, provenance: str, source: str) -> bool:
    if not platform or not N.valid_handle(platform, handle):
        return False
    owner = find_by_handle(conn, platform, handle)
    if owner:
        return False
    conn.insert("lead_handles", {"lead_id": lead_id, "platform": platform, "handle": N.clean_handle(handle),
                                 "handle_norm": N.norm_handle(handle),
                                 "url": N.safe_url(url) or N.profile_url_for(platform, handle),
                                 "provenance": provenance, "source": source[:80], "created_at": N.now_iso()})
    return True


def merge_evidence(old: list[dict], new: list[dict]) -> list[dict]:
    seen, out = set(), []
    for ev in [*new, *old]:
        key = (ev.get("url") or "") + "|" + (ev.get("title") or ev.get("text") or "")[:80]
        if key not in seen:
            seen.add(key)
            out.append(ev)
    out.sort(key=lambda e: e.get("date") or "", reverse=True)
    return out[:MAX_EVIDENCE]


def merge_sighting(conn: Conn, lead_id: int, cand: dict, strategy: dict, batch_id: int | None) -> dict:
    """A provider returned a lead we already have: refresh public stats, keep evidence, mark it seen again.
    It is NOT re-surfaced as new: discovered_at never changes."""
    row = get(conn, lead_id)
    now = N.now_iso()
    patch: dict = {"last_seen_at": now, "seen_count": int(row["seen_count"] or 1) + 1, "updated_at": now}
    if cand.get("followers") is not None and row["platform"] == cand["platform"]:
        patch["followers"] = cand["followers"]
    for key in ("location", "genre", "bio"):
        if cand.get(key) and not row.get(key):
            patch[key] = cand[key]
    if cand.get("uploads_30d") is not None and row["platform"] == cand["platform"]:
        patch["uploads_30d"] = cand["uploads_30d"]
    for key in ("last_activity_at", "last_release_at"):
        new = N.parse_dt(cand.get(key))
        if new and (not row.get(key) or new > N.parse_dt(row[key])):
            patch[key] = N.iso(new)
    patch["evidence"] = dumps(merge_evidence(loads(row["evidence"], []), cand.get("evidence") or []))
    merged = {**row, **patch}
    patch.update(apply_score(merged, strategy))
    conn.update("leads", lead_id, patch)
    _add_handle(conn, lead_id, cand["platform"], cand["handle"], cand.get("profile_url", ""), "source",
                cand.get("source", ""))
    for h in cand.get("linked") or []:
        _add_handle(conn, lead_id, h["platform"], h["handle"], h.get("url", ""), h.get("provenance", "linked"),
                    cand.get("source", ""))
    log(conn, lead_id, "seen_again", f"Seen again by {cand.get('source_label') or cand.get('source', 'discovery')}")
    return {**row, **patch}


# ------------------------------------------------------------------------------------------------ edits / workflow

def update_fields(conn: Conn, lead_id: int, data: dict, strategy: dict) -> dict:
    row = get(conn, lead_id)
    if not row:
        raise LeadError("Lead not found", 404)
    clean = clean_input({k: v for k, v in data.items() if k in EDITABLE}, partial=True)
    if "handle" in clean or "platform" in clean:
        platform = clean.get("platform") or row["platform"]
        handle = clean.get("handle") or row["handle"]
        if not N.valid_handle(platform, handle):
            raise LeadError("That handle has characters the platform doesn't allow")
        owner = find_by_handle(conn, platform, handle)
        if owner and owner != lead_id:
            raise LeadError("Another lead already has that handle", 409, lead_id=owner)
        if (platform, N.norm_handle(handle)) != (row["platform"], row["handle_norm"]):
            conn.run("DELETE FROM lead_handles WHERE lead_id = ? AND platform = ? AND handle_norm = ?",
                     (lead_id, row["platform"], row["handle_norm"]))
            clean["handle_norm"] = N.norm_handle(handle)
            if "profile_url" not in clean and row["profile_url"] == N.profile_url_for(row["platform"], row["handle"]):
                clean["profile_url"] = N.profile_url_for(platform, handle)
            _add_handle(conn, lead_id, platform, handle, clean.get("profile_url") or row["profile_url"],
                        "manual", "Edited")
    if "follow_up_at" in clean and clean["follow_up_at"] and row["status"] not in ("contacted", "follow_up"):
        clean["status"] = "follow_up"
        clean["status_changed_at"] = N.now_iso()
    if not clean:
        return row
    clean["updated_at"] = N.now_iso()
    merged = {**row, **clean}
    if any(k in clean for k in ("bio", "genre", "location", "followers", "last_activity_at", "last_release_at",
                                "name", "handle", "platform")):
        clean.update(apply_score(merged, strategy))
    conn.update("leads", lead_id, clean)
    if "notes" in clean and clean["notes"] != row["notes"]:
        log(conn, lead_id, "note", "Notes updated")
    changed = [k for k in data if k in EDITABLE and k in clean and k != "notes" and clean[k] != row.get(k)]
    if changed:
        log(conn, lead_id, "edited", "Updated " + ", ".join(sorted(c.replace("_", " ") for c in changed)))
    return {**row, **clean}


def set_status(conn: Conn, lead_id: int, status: str, strategy: dict, follow_up_at: str | None = None) -> dict:
    row = get(conn, lead_id)
    if not row:
        raise LeadError("Lead not found", 404)
    if status not in STATUS_KEYS:
        raise LeadError("Unknown status")
    now = N.utcnow()
    patch = {"status": status, "status_changed_at": N.iso(now), "updated_at": N.iso(now)}
    due = N.parse_dt(follow_up_at) if follow_up_at else None
    if follow_up_at and due is None:
        raise LeadError("Follow-up date must be YYYY-MM-DD")
    if status == "contacted":
        patch["last_contacted_at"] = N.iso(now)
        patch["follow_up_at"] = N.iso(due or now + timedelta(days=strategy["follow_up_days"]))
    elif status == "follow_up":
        patch["follow_up_at"] = N.iso(due or now)
    elif status in ("client", "not_fit", "new", "watching", "contact"):
        patch["follow_up_at"] = None
    conn.update("leads", lead_id, patch)
    label = dict((k, l) for k, l, _d in STATUSES)[status]
    detail = f"Status → {label}"
    if status == "contacted":
        detail += f" · follow up {N.local_date_str(patch['follow_up_at'], strategy['timezone'])}"
    elif status == "follow_up" and due:
        detail += f" · due {N.local_date_str(patch['follow_up_at'], strategy['timezone'])}"
    log(conn, lead_id, "status", detail)
    return {**row, **patch}


def delete(conn: Conn, lead_id: int) -> None:
    conn.run("DELETE FROM lead_handles WHERE lead_id = ?", (lead_id,))
    conn.run("DELETE FROM activities WHERE lead_id = ?", (lead_id,))
    conn.run("UPDATE candidates SET lead_id = NULL WHERE lead_id = ?", (lead_id,))
    conn.run("DELETE FROM leads WHERE id = ?", (lead_id,))


# ------------------------------------------------------------------------------------------------ search / filter

FOLLOWER_RANGES = {
    "lt1k": (0, 999), "1k-10k": (1_000, 9_999), "10k-50k": (10_000, 49_999), "50k-250k": (50_000, 249_999),
    "250k+": (250_000, None),
}
SORTS = {
    "score": "score DESC, discovered_at DESC",
    "newest": "discovered_at DESC, score DESC",
    "activity": "CASE WHEN last_activity_at IS NULL THEN 1 ELSE 0 END, last_activity_at DESC, score DESC",
    "followers": "CASE WHEN followers IS NULL THEN 1 ELSE 0 END, followers DESC, score DESC",
    "name": "LOWER(name) ASC",
    "follow_up": "CASE WHEN follow_up_at IS NULL THEN 1 ELSE 0 END, follow_up_at ASC, score DESC",
}
_STATUS_WORDS = {"new": "new", "watching": "watching", "watch": "watching", "contact": "contact",
                 "contacted": "contacted", "follow-up": "follow_up", "follow up": "follow_up", "followup": "follow_up",
                 "client": "client", "clients": "client", "not a fit": "not_fit", "not fit": "not_fit",
                 "rejected": "not_fit", "dismissed": "not_fit"}


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def build_where(f: dict, strategy: dict, now: datetime) -> tuple[str, list]:
    where, params = ["1 = 1"], []
    q = " ".join(str(f.get("q") or "").split()).lower()
    if q:
        status_hit = _STATUS_WORDS.get(q)
        terms = [q] if status_hit else q.split(" ")
        for term in terms[:8]:
            t = term.lstrip("@") or term
            plat = N.norm_platform(t)
            clause = ("(LOWER(name) LIKE ? ESCAPE '\\' OR handle_norm LIKE ? ESCAPE '\\' OR LOWER(genre) LIKE ? ESCAPE '\\'"
                      " OR LOWER(location) LIKE ? ESCAPE '\\' OR LOWER(bio) LIKE ? ESCAPE '\\'"
                      " OR LOWER(notes) LIKE ? ESCAPE '\\' OR LOWER(reason) LIKE ? ESCAPE '\\'"
                      " OR LOWER(source) LIKE ? ESCAPE '\\'"
                      " OR id IN (SELECT lead_id FROM lead_handles WHERE handle_norm LIKE ? ESCAPE '\\')")
            p = _like(t)
            params += [p] * 9
            if plat and plat != "other":
                clause += " OR platform = ?"
                params.append(plat)
            if status_hit:
                clause += " OR status = ?"
                params.append(status_hit)
            where.append(clause + ")")
    platforms = [N.norm_platform(p) for p in str(f.get("platform") or "").split(",") if p.strip()]
    if platforms:
        where.append(f"platform IN ({', '.join('?' for _ in platforms)})")
        params += platforms
    statuses = [s for s in str(f.get("status") or "").split(",") if s in STATUS_KEYS]
    if f.get("status") == "active":
        statuses = list(ACTIVE_STATUSES)
    if statuses:
        where.append(f"status IN ({', '.join('?' for _ in statuses)})")
        params += statuses
    if f.get("genre"):
        where.append("LOWER(genre) LIKE ? ESCAPE '\\'")
        params.append(_like(str(f["genre"]).lower()))
    if f.get("location"):
        where.append("LOWER(location) LIKE ? ESCAPE '\\'")
        params.append(_like(str(f["location"]).lower()))
    for key, op in (("min_score", ">="), ("max_score", "<=")):
        if str(f.get(key) or "").strip():
            try:
                params.append(int(f[key]))
                where.append(f"score {op} ?")
            except ValueError:
                pass
    tz = strategy["timezone"]
    disc = f.get("discovered")
    if disc == "today":
        where.append("discovered_at >= ?")
        params.append(N.iso(N.local_day_start(tz, ref=now)))
    elif disc in ("7d", "30d"):
        where.append("discovered_at >= ?")
        params.append(N.iso(N.local_day_start(tz, int(disc[:-1]) - 1, ref=now)))
    elif disc == "older":
        where.append("discovered_at < ?")
        params.append(N.iso(N.local_day_start(tz, 29, ref=now)))
    act = f.get("activity")
    if act in ("7d", "30d", "90d"):
        where.append("last_activity_at >= ?")
        params.append(N.iso(now - timedelta(days=int(act[:-1]))))
    elif act == "inactive":
        where.append("last_activity_at < ?")
        params.append(N.iso(now - timedelta(days=90)))
    elif act == "unknown":
        where.append("last_activity_at IS NULL")
    fr = f.get("followers")
    if fr in FOLLOWER_RANGES:
        lo, hi = FOLLOWER_RANGES[fr]
        where.append("followers >= ?")
        params.append(lo)
        if hi is not None:
            where.append("followers <= ?")
            params.append(hi)
    elif fr == "unknown":
        where.append("followers IS NULL")
    fresh = f.get("freshness")
    stale_cut = N.iso(now - timedelta(days=strategy["stale_days"]))
    stale_sql = ("((last_activity_at IS NOT NULL AND last_activity_at < ?) OR "
                 "(last_activity_at IS NULL AND last_seen_at < ?))")
    if fresh == "new_today":
        where.append("discovered_at >= ?")
        params.append(N.iso(N.local_day_start(tz, ref=now)))
    elif fresh == "stale":
        where.append(stale_sql)
        params += [stale_cut, stale_cut]
    elif fresh in ("seen_before", "fresh"):
        if fresh == "seen_before":
            where.append("discovered_at < ?")
            params.append(N.iso(N.local_day_start(tz, ref=now)))
        where.append("NOT " + stale_sql)
        params += [stale_cut, stale_cut]
    if f.get("provenance") in ("verified", "manual", "import", "demo"):
        where.append("provenance = ?")
        params.append(f["provenance"])
    if f.get("due") == "1":
        where.append("status IN ('contacted', 'follow_up') AND (follow_up_at IS NULL OR follow_up_at <= ?)")
        params.append(N.iso(now))
    elif f.get("due") == "upcoming":
        where.append("status IN ('contacted', 'follow_up') AND follow_up_at > ?")
        params.append(N.iso(now))
    return " AND ".join(where), params


def query(conn: Conn, f: dict, strategy: dict, limit: int = 50, offset: int = 0, count_only: bool = False):
    now = N.utcnow()
    where, params = build_where(f, strategy, now)
    total = int(conn.scalar(f"SELECT COUNT(*) AS n FROM leads WHERE {where}", params) or 0)
    if count_only:
        return [], total
    order = SORTS.get(f.get("sort") or "score", SORTS["score"])
    rows = conn.all(f"SELECT * FROM leads WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                    [*params, int(limit), int(offset)])
    return [serialize(r, strategy, now) for r in rows], total


def facets(conn: Conn) -> dict:
    return {
        "platforms": [r["platform"] for r in conn.all("SELECT DISTINCT platform FROM leads ORDER BY platform")],
        "genres": sorted({g.strip() for r in conn.all("SELECT DISTINCT genre FROM leads WHERE genre <> ''")
                          for g in r["genre"].split(",") if g.strip()}, key=str.lower)[:60],
        "locations": [r["location"] for r in conn.all(
            "SELECT location, COUNT(*) AS n FROM leads WHERE location <> '' GROUP BY location ORDER BY n DESC "
            "LIMIT 40")],
    }


# ------------------------------------------------------------------------------------------------ prioritising

def priority(lead: dict) -> float:
    """Ordering for 'who should OG-WAN know about today': score first, nudged by freshness and readiness."""
    p = float(lead["score"])
    if lead["freshness"] == "new_today":
        p += 6
    elif lead["freshness"] == "stale":
        p -= 40
    if lead["status"] == "contact":
        p += 8
    elif lead["status"] == "watching":
        p += 2
    return p


def top_prospects(conn: Conn, strategy: dict, limit: int = 10) -> list[dict]:
    now = N.utcnow()
    rows = conn.all("SELECT * FROM leads WHERE status IN ('new', 'watching', 'contact') AND score >= ? "
                    "ORDER BY score DESC, discovered_at DESC LIMIT 400", (strategy["keep_min_score"],))
    leads = [serialize(r, strategy, now) for r in rows]
    leads = [l for l in leads if l["freshness"] != "stale"]
    leads.sort(key=lambda l: l["discovered_at"], reverse=True)
    leads.sort(key=priority, reverse=True)  # stable: newest first among equal priority
    return leads[:limit]
