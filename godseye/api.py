"""JSON API routes. Thin handlers over the service modules; every number returned is computed from the database."""
import csv
import io
import time

from . import analytics, auth, discovery, drop, importer
from . import leads as L
from . import normalize as N
from . import scoring
from . import settings as S
from .db import loads
from .discovery.base import LOOKING_FOR, SIGNAL_LABELS
from .web import ApiError, Request, Response, cookie_name, route

VERSION = "1.0.0"


def _lead_or_404(req: Request, lead_id) -> dict:
    try:
        row = L.get(req.conn, int(lead_id))
    except (TypeError, ValueError):
        row = None
    if not row:
        raise ApiError(404, "Lead not found")
    return row


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except L.LeadError as e:
        raise ApiError(e.status, str(e), **e.extra)
    except ValueError as e:
        raise ApiError(400, str(e))


# ------------------------------------------------------------------------------------------------ auth

@route("GET", "/api/setup", access="public")
def setup_status(req: Request):
    from .web import setup

    problems = setup()["problems"]
    return {"configured": not problems, "problems": problems}


@route("POST", "/api/login", access="public")
def login(req: Request):
    from .web import setup

    if setup()["problems"] or req.conn is None:
        raise ApiError(503, "GOD'S EYE is not configured yet")
    wait = auth.locked_out(req.conn, req.cfg, req.client_ip)
    if wait:
        raise ApiError(429, f"Too many attempts. Try again in {max(1, round(wait / 60))} min.", retry_after=wait)
    password = str(req.json.get("password") or "")
    ok = auth.password_ok(req.cfg, password)
    auth.record_attempt(req.conn, req.cfg, req.client_ip, ok)
    req.conn.commit()
    if not ok:
        time.sleep(0.4)  # slows guessing without hurting the real user
        left = auth.MAX_FAILURES - auth.recent_failures(req.conn, req.cfg, req.client_ip)
        raise ApiError(401, "Access denied." + (f" {left} attempt{'s' if left != 1 else ''} left." if 0 < left <= 2 else ""))
    token = auth.create_session(req.conn, req.cfg, req.header("User-Agent"))
    cookie = auth.cookie_header(token, req.cfg.secure_cookies).replace(auth.COOKIE + "=", cookie_name(req.cfg) + "=", 1)
    return Response(200, {"ok": True}, headers=[("Set-Cookie", cookie)])


def _clear_cookie(req: Request) -> tuple[str, str]:
    c = auth.cookie_header("", req.cfg.secure_cookies, clear=True).replace(auth.COOKIE + "=", cookie_name(req.cfg) + "=", 1)
    return "Set-Cookie", c


@route("POST", "/api/logout")
def logout(req: Request):
    auth.end_session(req.conn, req.cfg, req.token)
    return Response(200, {"ok": True}, headers=[_clear_cookie(req)])


@route("POST", "/api/logout-all")
def logout_all(req: Request):
    n = auth.end_all_sessions(req.conn)
    return Response(200, {"ok": True, "ended": n}, headers=[_clear_cookie(req)])


@route("GET", "/api/session")
def session(req: Request):
    s = req.session
    return {"user": "OG-WAN", "signed_in_at": s["created_at"], "expires_at": s["expires_at"]}


# ------------------------------------------------------------------------------------------------ meta / briefing

@route("GET", "/api/meta")
def meta(req: Request):
    st = req.strategy
    return {
        "version": VERSION,
        "statuses": [{"key": k, "label": l, "description": d} for k, l, d in S.STATUSES],
        "platforms": [{"key": k, "label": v["label"], "url_template": bool(v["url"])} for k, v in N.PLATFORMS.items()],
        "signals": [{"key": k, "label": v} for k, v in SIGNAL_LABELS.items()],
        "looking_for": [{"key": k, "label": k.title()} for k in LOOKING_FOR],
        "strategy": st,
        "providers": discovery.provider_status(req.cfg, st),
        "facets": L.facets(req.conn),
        "demo_count": int(req.conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE is_demo = 1") or 0),
        "total_leads": int(req.conn.scalar("SELECT COUNT(*) AS n FROM leads") or 0),
    }


@route("GET", "/api/nav")
def nav_counts(req: Request):
    """Small counters for the navigation: today's fresh prospects and follow-ups due."""
    st = req.strategy
    start = N.iso(N.local_day_start(st["timezone"]))
    return {
        "today": int(req.conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE discovered_at >= ? AND status <> 'not_fit'",
                                     (start,)) or 0),
        "due": int(req.conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE status IN ('contacted', 'follow_up') AND "
                                   "(follow_up_at IS NULL OR follow_up_at <= ?)", (N.now_iso(),)) or 0),
        "demo": int(req.conn.scalar("SELECT COUNT(*) AS n FROM leads WHERE is_demo = 1") or 0),
    }


@route("GET", "/api/dashboard")
def dashboard(req: Request):
    drop.maybe_rescore(req.conn, req.strategy)
    return drop.dashboard(req.conn, req.strategy)


@route("GET", "/api/today")
def today(req: Request):
    drop.maybe_rescore(req.conn, req.strategy)
    return drop.today_drop(req.conn, req.strategy)


@route("POST", "/api/drop")
def generate_drop(req: Request):
    plan = discovery.make_plan(req.strategy, None, "drop")
    result = discovery.run_batch(req.conn, req.cfg, req.strategy, plan, kind="drop")
    return {"run": result, "drop": drop.today_drop(req.conn, req.strategy)}


@route("GET", "/api/cron/daily-drop", access="cron")
def cron_drop(req: Request):
    if drop.drop_ran_today(req.conn, req.strategy) and req.arg("force") != "1":
        return {"ok": True, "skipped": "A drop already ran today"}
    plan = discovery.make_plan(req.strategy, None, "drop")
    result = discovery.run_batch(req.conn, req.cfg, req.strategy, plan, kind="drop")
    return {"ok": True, "stats": result["stats"], "errors": result["errors"]}


# ------------------------------------------------------------------------------------------------ discovery

@route("POST", "/api/discover")
def discover(req: Request):
    body = req.json
    params = {"genres": _list(body.get("genres")), "locations": _list(body.get("locations")),
              "platforms": _list(body.get("platforms")), "signal": body.get("signal"),
              "looking_for": body.get("looking_for"), "min_score": body.get("min_score")}
    plan = discovery.make_plan(req.strategy, params, "scan")
    result = discovery.run_batch(req.conn, req.cfg, req.strategy, plan, kind="scan")
    return {"run": result, "batch": discovery.batch_view(req.conn, result["batch_id"], req.strategy)}


def _list(v) -> list[str]:
    if isinstance(v, str):
        v = [x for x in v.split(",")]
    return [str(x).strip() for x in (v or []) if str(x).strip()][:20]


@route("GET", "/api/batches")
def batches(req: Request):
    rows = req.conn.all("SELECT * FROM batches ORDER BY started_at DESC LIMIT ?", (min(50, int(req.arg("limit", 20))),))
    return {"items": [{"id": r["id"], "kind": r["kind"], "status": r["status"], "started_at": r["started_at"],
                       "finished_at": r["finished_at"], "params": loads(r["params"], {}), "stats": loads(r["stats"], {}),
                       "errors": loads(r["errors"], [])} for r in rows]}


@route("GET", "/api/batches/<bid>")
def batch(req: Request):
    try:
        view = discovery.batch_view(req.conn, int(req.params["bid"]), req.strategy)
    except ValueError:
        view = None
    if not view:
        raise ApiError(404, "Batch not found")
    return view


@route("POST", "/api/candidates/<cid>/keep")
def keep(req: Request):
    try:
        cid = int(req.params["cid"])
    except ValueError:
        raise ApiError(404, "Candidate not found")
    lead_id = _wrap(discovery.keep_candidate, req.conn, cid, req.strategy)
    return {"lead_id": lead_id}


# ------------------------------------------------------------------------------------------------ leads

FILTER_KEYS = ("q", "platform", "status", "genre", "location", "min_score", "max_score", "discovered", "activity",
               "followers", "freshness", "provenance", "due", "sort")


def _filters(req: Request) -> dict:
    return {k: req.arg(k) for k in FILTER_KEYS if req.arg(k) not in (None, "")}


@route("GET", "/api/leads")
def list_leads(req: Request):
    try:
        limit = max(1, min(200, int(req.arg("limit", 50))))
        offset = max(0, int(req.arg("offset", 0)))
    except ValueError:
        raise ApiError(400, "limit/offset must be numbers")
    items, total = L.query(req.conn, _filters(req), req.strategy, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@route("GET", "/api/leads/count")
def count_leads(req: Request):
    _items, total = L.query(req.conn, _filters(req), req.strategy, count_only=True)
    return {"total": total}


@route("POST", "/api/leads")
def create_lead(req: Request):
    data = _wrap(L.clean_input, req.json)
    source = data.pop("source", "") or "Added manually"
    lead_id = _wrap(L.create, req.conn, data, req.strategy, "manual", source)
    return Response(201, {"id": lead_id, "lead": _detail(req, lead_id)})


def _detail(req: Request, lead_id: int) -> dict:
    row = L.get(req.conn, lead_id)
    now = N.utcnow()
    lead = L.serialize(row, req.strategy, now, handles=L.handles_for(req.conn, lead_id))
    lead["activities"] = req.conn.all("SELECT kind, detail, created_at FROM activities WHERE lead_id = ? "
                                      "ORDER BY id DESC LIMIT 60", (lead_id,))
    lead["sightings"] = [{"batch_id": r["batch_id"], "outcome": r["outcome"], "provider": r["provider"],
                          "at": r["created_at"], "kind": r["kind"]} for r in req.conn.all(
        "SELECT c.batch_id, c.outcome, c.provider, c.created_at, b.kind FROM candidates c "
        "JOIN batches b ON b.id = c.batch_id WHERE c.lead_id = ? ORDER BY c.id DESC LIMIT 20", (lead_id,))]
    lead["signal_catalogue"] = scoring.weights_catalogue(req.strategy.get("weights"))
    return lead


@route("GET", "/api/leads/<lid>")
def get_lead(req: Request):
    row = _lead_or_404(req, req.params["lid"])
    return _detail(req, row["id"])


@route("PATCH", "/api/leads/<lid>")
def patch_lead(req: Request):
    row = _lead_or_404(req, req.params["lid"])
    _wrap(L.update_fields, req.conn, row["id"], req.json, req.strategy)
    return _detail(req, row["id"])


@route("POST", "/api/leads/<lid>/status")
def lead_status(req: Request):
    row = _lead_or_404(req, req.params["lid"])
    _wrap(L.set_status, req.conn, row["id"], str(req.json.get("status") or ""), req.strategy,
          req.json.get("follow_up_at") or None)
    return _detail(req, row["id"])


@route("DELETE", "/api/leads/<lid>")
def delete_lead(req: Request):
    row = _lead_or_404(req, req.params["lid"])
    L.delete(req.conn, row["id"])
    return {"ok": True}


@route("GET", "/api/follow-ups")
def follow_ups(req: Request):
    return drop.follow_ups(req.conn, req.strategy)


@route("GET", "/api/analytics")
def get_analytics(req: Request):
    try:
        days = max(7, min(90, int(req.arg("days", 30))))
    except ValueError:
        days = 30
    return analytics.compute(req.conn, req.strategy, days)


# ------------------------------------------------------------------------------------------------ strategy / settings

@route("GET", "/api/strategy")
def get_strategy(req: Request):
    st = req.strategy
    return {"strategy": st, "signals": scoring.weights_catalogue(st.get("weights")), "groups": scoring.GROUPS}


@route("PUT", "/api/strategy")
def put_strategy(req: Request):
    allowed = {k: v for k, v in req.json.items() if k in S.DEFAULTS}
    _wrap(S.save, req.conn, allowed)
    req.reset_strategy()
    changed = L.rescore_all(req.conn, req.strategy)
    drop.set_meta(req.conn, "rescored_at", N.now_iso())
    return {"strategy": req.strategy, "signals": scoring.weights_catalogue(req.strategy.get("weights")),
            "groups": scoring.GROUPS, "rescored": changed}


@route("GET", "/api/settings")
def get_settings(req: Request):
    db = req.db
    return {
        "providers": discovery.provider_status(req.cfg, req.strategy),
        "database": "PostgreSQL" if db.dialect == "pg" else "SQLite (local file)",
        "sessions": int(req.conn.scalar("SELECT COUNT(*) AS n FROM sessions") or 0),
        "signed_in_at": req.session["created_at"], "cron_configured": bool(req.cfg.cron_secret),
        "on_vercel": req.cfg.on_vercel, "demo_count": int(req.conn.scalar(
            "SELECT COUNT(*) AS n FROM leads WHERE is_demo = 1") or 0),
        "query_log": req.conn.all("SELECT provider, query, runs, last_run_at, last_count FROM query_log "
                                  "ORDER BY last_run_at DESC LIMIT 15"),
        "version": VERSION,
    }


@route("POST", "/api/demo/clear")
def clear_demo(req: Request):
    ids = [r["id"] for r in req.conn.all("SELECT id FROM leads WHERE is_demo = 1")]
    for lid in ids:
        L.delete(req.conn, lid)
    req.conn.run("DELETE FROM candidates WHERE batch_id IN (SELECT id FROM batches WHERE is_demo = 1)")
    req.conn.run("DELETE FROM batches WHERE is_demo = 1")
    return {"removed": len(ids)}


# ------------------------------------------------------------------------------------------------ import / export

@route("POST", "/api/import")
def do_import(req: Request):
    fmt = str(req.json.get("format") or "csv").lower()
    content = str(req.json.get("content") or "")
    if len(content) > 4 * 1024 * 1024:
        raise ApiError(413, "File too large: keep imports under 4 MB")
    parser = {"csv": importer.parse_csv, "json": importer.parse_json, "links": importer.parse_links}.get(fmt)
    if not parser:
        raise ApiError(400, "Format must be csv, json or links")
    try:
        rows = parser(content)
    except importer.ImportError_ as e:
        raise ApiError(400, str(e))
    default_source = " ".join(str(req.json.get("source") or "").split())[:80] or \
        {"csv": "CSV import", "json": "JSON import", "links": "Pasted links"}[fmt]
    return importer.run_import(req.conn, rows, req.strategy, fmt=fmt, dry_run=bool(req.json.get("dry_run")),
                               default_source=default_source)


@route("GET", "/api/import/template.csv")
def import_template(req: Request):
    return Response(200, importer.template_csv(), "text/csv; charset=utf-8",
                    [("Content-Disposition", 'attachment; filename="gods-eye-import-template.csv"')])


EXPORT_FIELDS = ["id", "name", "handle", "platform", "profile_url", "genre", "location", "followers", "score",
                 "status", "provenance", "source", "source_url", "discovered_at", "last_seen_at", "last_activity_at",
                 "last_release_at", "last_contacted_at", "follow_up_at", "reason", "notes"]


@route("GET", "/api/export.csv")
def export_csv(req: Request):
    items, _total = L.query(req.conn, _filters(req), req.strategy, limit=100000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_FIELDS)
    for it in items:
        w.writerow(["" if it.get(f) is None else _csv_safe(it.get(f)) for f in EXPORT_FIELDS])
    stamp = N.utcnow().strftime("%Y%m%d")
    return Response(200, "﻿" + buf.getvalue(), "text/csv; charset=utf-8",
                    [("Content-Disposition", f'attachment; filename="gods-eye-leads-{stamp}.csv"')])


def _csv_safe(value):
    """Stop spreadsheet formula injection from public bios/names (=, +, -, @ at the start of a cell)."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not s[1:2].isdigit() else s
