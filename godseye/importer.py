"""Manual import: CSV, JSON and pasted profile links. Imported leads join the same database and workflow as
discovered ones (provenance "import"). Duplicates are detected by platform + normalized handle and never re-added."""
import csv
import io
import json

from . import leads as L
from . import normalize as N
from .db import Conn, dumps

MAX_ROWS = 2000
FIELD_ALIASES = {
    "name": "name", "artist": "name", "artist name": "name", "artist_name": "name", "full name": "name",
    "handle": "handle", "username": "handle", "user": "handle", "@handle": "handle", "social handle": "handle",
    "platform": "platform", "network": "platform", "site": "platform",
    "profile_url": "profile_url", "profile url": "profile_url", "url": "profile_url", "link": "profile_url",
    "profile": "profile_url", "profile link": "profile_url",
    "genre": "genre", "genres": "genre", "style": "genre",
    "location": "location", "city": "location", "country": "location",
    "followers": "followers", "followers count": "followers", "follower_count": "followers", "audience": "followers",
    "subscribers": "followers",
    "source": "source", "found via": "source", "notes": "notes", "note": "notes",
    "bio": "bio", "caption": "bio", "description": "bio",
    "source_url": "source_url", "source url": "source_url", "evidence url": "source_url",
    "last_activity_at": "last_activity_at", "last active": "last_activity_at", "last activity": "last_activity_at",
    "last_release_at": "last_release_at", "last release": "last_release_at", "latest release": "last_release_at",
}
TEMPLATE_FIELDS = ["name", "handle", "platform", "profile_url", "genre", "location", "followers", "source", "notes"]


class ImportError_(ValueError):
    pass


def parse_csv(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    if not text.strip():
        raise ImportError_("The file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ImportError_("No header row found")
    mapping = {f: FIELD_ALIASES.get((f or "").strip().lower()) for f in reader.fieldnames}
    if not any(v in ("handle", "profile_url") for v in mapping.values()):
        raise ImportError_("Needs a 'handle' or 'profile_url' column. Download the template to see the format.")
    rows = []
    for raw in reader:
        row = {mapping[k]: (v or "").strip() for k, v in raw.items() if k in mapping and mapping[k]}
        if any(row.values()):
            rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ImportError_(f"Too many rows: the limit is {MAX_ROWS} per import")
    return rows


def parse_json(text: str) -> list[dict]:
    try:
        data = json.loads(text.lstrip("﻿"))
    except ValueError as e:
        raise ImportError_(f"Not valid JSON ({e.msg} at line {e.lineno})")
    if isinstance(data, dict):
        data = data.get("leads") or data.get("data") or data.get("items")
    if not isinstance(data, list):
        raise ImportError_("JSON must be a list of leads, or an object with a 'leads' list")
    if len(data) > MAX_ROWS:
        raise ImportError_(f"Too many rows: the limit is {MAX_ROWS} per import")
    rows = []
    for item in data:
        if not isinstance(item, dict):
            raise ImportError_("Every lead in the JSON list must be an object")
        row = {}
        for k, v in item.items():
            field = FIELD_ALIASES.get(str(k).strip().lower())
            if field and v is not None and not isinstance(v, (dict, list)):
                row[field] = str(v).strip()
        rows.append(row)
    return rows


def parse_links(text: str) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        url = line.strip().strip(",")
        if url:
            rows.append({"profile_url": url})
        if len(rows) > MAX_ROWS:
            raise ImportError_(f"Too many links: the limit is {MAX_ROWS}")
    if not rows:
        raise ImportError_("Paste at least one profile link")
    return rows


def run_import(conn: Conn, rows: list[dict], strategy: dict, *, fmt: str, dry_run: bool, default_source: str) -> dict:
    results, seen_in_file = [], {}
    stats = {"rows": len(rows), "added": 0, "duplicate": 0, "invalid": 0}
    batch_id = None
    if not dry_run:
        batch_id = conn.insert("batches", {"kind": "import", "status": "running", "started_at": N.now_iso(),
                                           "params": dumps({"format": fmt, "rows": len(rows)})})
    for i, row in enumerate(rows, start=1):
        if fmt == "links":
            parsed = N.parse_profile_url(row.get("profile_url", ""))
            if not parsed:
                results.append({"row": i, "outcome": "invalid", "error": "Couldn't read a handle from this link",
                                "input": row.get("profile_url", "")[:200]})
                stats["invalid"] += 1
                continue
            row = {**row, "platform": parsed[0], "handle": parsed[1]}
        try:
            data = L.clean_input(row)
        except L.LeadError as e:
            results.append({"row": i, "outcome": "invalid", "error": str(e), "input": _label(row)})
            stats["invalid"] += 1
            continue
        key = (data["platform"], N.norm_handle(data["handle"]))
        existing = L.find_by_handle(conn, *key)
        if existing or key in seen_in_file:
            results.append({"row": i, "outcome": "duplicate", "lead_id": existing,
                            "error": "Already in GOD'S EYE" if existing else f"Repeats row {seen_in_file[key]}",
                            "input": _label(data)})
            stats["duplicate"] += 1
            continue
        seen_in_file[key] = i
        source = data.pop("source", "") or default_source
        lead_id = None
        if not dry_run:
            lead_id = L.create(conn, data, strategy, "import", source, batch_id=batch_id)
        results.append({"row": i, "outcome": "added", "lead_id": lead_id, "input": _label(data)})
        stats["added"] += 1
    if batch_id:
        conn.update("batches", batch_id, {"status": "done", "finished_at": N.now_iso(), "stats": dumps(stats)})
    return {"dry_run": dry_run, "stats": stats, "results": results[:500], "batch_id": batch_id}


def _label(row: dict) -> str:
    h = row.get("handle") or row.get("profile_url") or ""
    plat = N.platform_label(row["platform"]) if row.get("platform") else ""
    return " · ".join(x for x in (row.get("name"), ("@" + N.clean_handle(h)) if row.get("handle") else h, plat) if x)[:200]


def template_csv() -> str:
    """Header row only: OG-WAN fills in real leads."""
    return ",".join(TEMPLATE_FIELDS) + "\r\n"
