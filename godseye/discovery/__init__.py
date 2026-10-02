"""Discovery engine: picks which provider queries to run (rotating so batches don't repeat), runs them against real
sources, de-duplicates against the database and stores the results as a batch.

    run_batch(conn, cfg, strategy, plan, kind)   -> batch summary + candidates

New leads enter as NEW with provenance "verified" and their source URL. Leads already in the database are marked
"seen again" (last_seen_at, seen_count) and are never re-surfaced as new."""
import random
import time

from .. import leads as L
from .. import normalize as N
from ..config import Config
from ..db import Conn, dumps, loads
from .audius import AudiusProvider
from .base import LOOKING_FOR, SIGNAL_LABELS, DiscoveryProvider, ProviderError
from .websearch import WebSearchProvider
from .youtube import YouTubeProvider

PROVIDERS: list[type[DiscoveryProvider]] = [AudiusProvider, YouTubeProvider, WebSearchProvider]
TIME_BUDGET = 45.0  # seconds per batch, well inside a serverless function's limit


def all_providers(cfg: Config) -> list[DiscoveryProvider]:
    return [cls(cfg) for cls in PROVIDERS]


def provider_status(cfg: Config, strategy: dict) -> list[dict]:
    out = []
    for p in all_providers(cfg):
        out.append({"key": p.key, "label": p.label, "platforms": list(p.platforms), "env": list(p.env_vars),
                    "configured": p.configured(), "enabled": p.key in strategy["enabled_providers"],
                    "description": p.description,
                    "engine": getattr(p, "engine", None) if p.configured() else None})
    return out


def make_plan(strategy: dict, params: dict | None = None, kind: str = "drop") -> dict:
    """A scan plan from the Discover form (params) or, for the daily drop, from the Strategy settings."""
    params = params or {}
    genres = [g for g in (params.get("genres") or []) if g] or strategy["target_genres"]
    locations = [l for l in (params.get("locations") or []) if l] or strategy["target_locations"]
    platforms = [N.norm_platform(p) for p in (params.get("platforms") or []) if p and p != "all"] \
        or strategy["target_platforms"]
    signal = params.get("signal") if params.get("signal") in SIGNAL_LABELS else "any"
    looking = params.get("looking_for") if params.get("looking_for") in LOOKING_FOR else "artists"
    try:
        min_score = int(params.get("min_score", strategy["keep_min_score"]))
    except (TypeError, ValueError):
        min_score = strategy["keep_min_score"]
    return {"kind": kind, "genres": genres[:12], "locations": locations[:12], "platforms": platforms,
            "signal": signal, "looking_for": looking, "min_score": max(0, min(100, min_score)),
            "max_queries": strategy["max_queries_per_batch"]}


def _usable(cfg: Config, strategy: dict, plan: dict) -> list[DiscoveryProvider]:
    return [p for p in all_providers(cfg)
            if p.key in strategy["enabled_providers"] and p.configured() and set(p.platforms) & set(plan["platforms"])]


def _choose_specs(conn: Conn, providers: list[DiscoveryProvider], plan: dict) -> list[tuple[DiscoveryProvider, dict, dict]]:
    """Least-recently-run specs first, round-robin across providers, at most plan['max_queries']."""
    rng = random.Random(N.utcnow().strftime("%Y-%m-%d-%H"))
    per_provider = []
    for p in providers:
        specs = p.specs(plan)
        rng.shuffle(specs)
        logs = {r["query_key"]: r for r in conn.all("SELECT * FROM query_log WHERE provider = ?", (p.key,))}
        specs.sort(key=lambda s: (logs.get(s["key"], {}).get("last_run_at") or ""))
        per_provider.append([(p, s, logs.get(s["key"])) for s in specs])
    chosen = []
    while len(chosen) < plan["max_queries"] and any(per_provider):
        for queue in per_provider:
            if queue and len(chosen) < plan["max_queries"]:
                chosen.append(queue.pop(0))
    return chosen


def _merge_candidates(cands: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for c in cands:
        key = (c["platform"], N.norm_handle(c["handle"]))
        if key not in merged:
            merged[key] = c
            continue
        m = merged[key]
        m["evidence"] = L.merge_evidence(m.get("evidence") or [], c.get("evidence") or [])
        for k in ("followers", "location", "genre", "bio", "uploads_30d"):
            if m.get(k) in (None, "") and c.get(k) not in (None, ""):
                m[k] = c[k]
        for k in ("last_activity_at", "last_release_at"):
            a, b = N.parse_dt(m.get(k)), N.parse_dt(c.get(k))
            if b and (not a or b > a):
                m[k] = N.iso(b)
        known = {(h["platform"], h["handle"].lower()) for h in m.get("linked") or []}
        m["linked"] = (m.get("linked") or []) + [h for h in c.get("linked") or []
                                                 if (h["platform"], h["handle"].lower()) not in known]
    return list(merged.values())


def run_batch(conn: Conn, cfg: Config, strategy: dict, plan: dict, kind: str = "scan") -> dict:
    started = time.monotonic()
    deadline = started + TIME_BUDGET
    batch_id = conn.insert("batches", {"kind": kind, "status": "running", "started_at": N.now_iso(),
                                       "params": dumps(plan)})
    conn.commit()
    providers = _usable(cfg, strategy, plan)
    errors, notes, queries = [], [], []
    raw: list[dict] = []
    if not providers:
        notes.append("No discovery source is enabled and configured for the selected platforms.")
    for provider, spec, log in _choose_specs(conn, providers, plan):
        if time.monotonic() > deadline - 5:
            notes.append("Time budget reached; remaining queries will run in the next batch.")
            break
        spec = {**spec, "targets": plan["genres"], "locations": plan["locations"]}
        cursor = (log or {}).get("cursor") or ""
        entry = {"provider": provider.key, "label": spec["label"], "found": 0, "error": ""}
        try:
            found, next_cursor = provider.run(spec, cursor, deadline)
            entry["found"] = len(found)
            for c in found:
                c["query"] = spec["label"]
            raw.extend(found)
        except ProviderError as e:
            next_cursor = cursor
            entry["error"] = str(e)
            errors.append(f"{provider.label}: {e}")
        queries.append(entry)
        now = N.now_iso()
        conn.run("INSERT INTO query_log (provider, query_key, query, runs, last_run_at, cursor, last_count) "
                 "VALUES (?, ?, ?, 1, ?, ?, ?) ON CONFLICT (provider, query_key) DO UPDATE SET "
                 "runs = query_log.runs + 1, last_run_at = excluded.last_run_at, cursor = excluded.cursor, "
                 "last_count = excluded.last_count, query = excluded.query",
                 (provider.key, spec["key"], dumps({"label": spec["label"]}), now, next_cursor, entry["found"]))
    for p in providers:
        notes.extend(n for n in p.notes if n not in notes)

    stats = {"queries": len(queries), "found": 0, "added": 0, "seen": 0, "filtered": 0, "invalid": 0}
    results = []
    for cand in _merge_candidates(raw):
        stats["found"] += 1
        outcome, lead_id, score = _ingest(conn, cand, strategy, plan, batch_id)
        stats[outcome if outcome in stats else "invalid"] += 1
        cid = conn.insert("candidates", {"batch_id": batch_id, "provider": cand["source"], "platform": cand["platform"],
                                         "handle_norm": N.norm_handle(cand["handle"]), "payload": dumps(cand),
                                         "score": score, "outcome": outcome, "lead_id": lead_id,
                                         "created_at": N.now_iso()})
        results.append({"candidate_id": cid, "outcome": outcome, "lead_id": lead_id, "score": score})
    status = "error" if errors and not stats["found"] and queries and all(q["error"] for q in queries) else "done"
    conn.update("batches", batch_id, {"status": status, "finished_at": N.now_iso(), "stats": dumps(stats),
                                      "errors": dumps(errors), "notes": dumps(notes)})
    conn.commit()
    return {"batch_id": batch_id, "stats": stats, "errors": errors, "notes": notes, "queries": queries,
            "providers": [p.key for p in providers], "seconds": round(time.monotonic() - started, 1)}


def _ingest(conn: Conn, cand: dict, strategy: dict, plan: dict, batch_id: int) -> tuple[str, int | None, int]:
    if not cand.get("handle") or not N.valid_handle(cand["platform"], cand["handle"]):
        return "invalid", None, 0
    existing = L.find_by_handle(conn, cand["platform"], cand["handle"])
    if not existing:
        for h in cand.get("linked") or []:
            existing = L.find_by_handle(conn, h["platform"], h["handle"])
            if existing:
                break
    if existing:
        row = L.merge_sighting(conn, existing, cand, strategy, batch_id)
        return "seen", existing, int(row["score"])
    data = {k: cand.get(k) for k in ("name", "handle", "platform", "profile_url", "genre", "location", "followers",
                                     "bio", "source_url", "last_activity_at", "last_release_at")}
    data["profile_url"] = N.safe_url(data.get("profile_url") or "")
    data["source_url"] = N.safe_url(data.get("source_url") or "")
    probe = {**data, "evidence": cand.get("evidence") or [], "uploads_30d": cand.get("uploads_30d"),
             "discovered_at": N.now_iso()}
    score = int(L.apply_score(probe, strategy)["score"])
    if score < plan["min_score"]:
        return "filtered", None, score
    lead_id = L.create(conn, data, strategy, "verified", cand.get("source_label") or cand["source"],
                       evidence=cand.get("evidence"), linked=cand.get("linked"), batch_id=batch_id,
                       uploads_30d=cand.get("uploads_30d"))
    return "added", lead_id, score


def batch_view(conn: Conn, batch_id: int, strategy: dict) -> dict | None:
    b = conn.one("SELECT * FROM batches WHERE id = ?", (batch_id,))
    if not b:
        return None
    now = N.utcnow()
    rows = conn.all("SELECT * FROM candidates WHERE batch_id = ? ORDER BY score DESC, id", (batch_id,))
    lead_ids = [r["lead_id"] for r in rows if r["lead_id"]]
    leads = {}
    if lead_ids:
        for r in conn.all(f"SELECT * FROM leads WHERE id IN ({', '.join('?' for _ in lead_ids)})", lead_ids):
            leads[r["id"]] = L.serialize(r, strategy, now)
    items = []
    for r in rows:
        payload = loads(r["payload"], {})
        item = {"candidate_id": r["id"], "outcome": r["outcome"], "score": r["score"], "lead": leads.get(r["lead_id"])}
        if not item["lead"]:
            item["preview"] = {k: payload.get(k) for k in ("name", "handle", "platform", "profile_url", "followers",
                                                           "location", "genre", "source_label", "source_url")}
            item["preview"]["platform_label"] = N.platform_label(payload.get("platform", "other"))
            item["preview"]["followers_label"] = N.fmt_count(payload.get("followers"))
        items.append(item)
    return {"id": b["id"], "kind": b["kind"], "status": b["status"], "started_at": b["started_at"],
            "finished_at": b["finished_at"], "params": loads(b["params"], {}), "stats": loads(b["stats"], {}),
            "errors": loads(b["errors"], []), "notes": loads(b["notes"], []), "items": items}


def keep_candidate(conn: Conn, candidate_id: int, strategy: dict) -> int:
    """OG-WAN overrides the noise filter for one candidate."""
    row = conn.one("SELECT * FROM candidates WHERE id = ?", (candidate_id,))
    if not row:
        raise L.LeadError("Candidate not found", 404)
    if row["lead_id"]:
        return row["lead_id"]
    cand = loads(row["payload"], {})
    existing = L.find_by_handle(conn, cand["platform"], cand["handle"])
    if existing:
        conn.update("candidates", candidate_id, {"lead_id": existing, "outcome": "seen"})
        return existing
    data = {k: cand.get(k) for k in ("name", "handle", "platform", "profile_url", "genre", "location", "followers",
                                     "bio", "source_url", "last_activity_at", "last_release_at")}
    lead_id = L.create(conn, data, strategy, "verified", cand.get("source_label") or cand["source"],
                       evidence=cand.get("evidence"), linked=cand.get("linked"), batch_id=row["batch_id"],
                       uploads_30d=cand.get("uploads_30d"))
    L.log(conn, lead_id, "kept", "Kept from the noise filter")
    conn.update("candidates", candidate_id, {"lead_id": lead_id, "outcome": "kept"})
    return lead_id
