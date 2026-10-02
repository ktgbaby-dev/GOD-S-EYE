"""Strategy and app settings, stored in the database (never hard-coded in the frontend).

Defaults are the starting strategy from the GOD'S EYE brief; OG-WAN edits them on the Strategy page."""
from . import normalize as N
from .db import Conn, dumps, loads
from .scoring import DEFAULT_WEIGHTS

STATUSES = [
    ("new", "New", "Not reviewed."),
    ("watching", "Watching", "Interesting, not ready for outreach."),
    ("contact", "Contact", "Worth contacting."),
    ("contacted", "Contacted", "OG-WAN has reached out."),
    ("follow_up", "Follow-up", "Needs another touch."),
    ("client", "Client", "Converted into a client."),
    ("not_fit", "Not a fit", "Dismissed."),
]
STATUS_KEYS = [s[0] for s in STATUSES]
ACTIVE_STATUSES = ("new", "watching", "contact")  # still being evaluated / worth surfacing

DEFAULTS: dict = {
    "target_genres": ["Afrobeats", "Afropop", "R&B", "Hip-Hop", "Amapiano"],
    "target_locations": ["Nigeria", "Lagos", "Abuja", "United Kingdom", "Ghana"],
    "target_platforms": ["instagram", "tiktok", "youtube", "audius"],
    "score_threshold": 70,       # HIGH PRIORITY at or above this
    "keep_min_score": 40,        # discovery keeps candidates at or above this; the rest is "noise filtered"
    "daily_target": 20,          # size of Today's Drop
    "follow_up_days": 4,         # default gap before a contacted lead is follow-up ready
    "stale_days": 45,            # no activity / not seen for this long = STALE
    "timezone": "Africa/Lagos",
    "drop_hour": 6,              # local hour the automatic daily drop may run
    "max_queries_per_batch": 6,  # cost control for paid search APIs
    "enabled_providers": ["audius", "youtube", "websearch"],
    "weights": {},               # overrides of scoring.DEFAULT_WEIGHTS
}

LIMITS = {
    "score_threshold": (1, 100), "keep_min_score": (0, 100), "daily_target": (1, 100), "follow_up_days": (1, 60),
    "stale_days": (7, 365), "drop_hour": (0, 23), "max_queries_per_batch": (1, 30),
}


def load(conn: Conn) -> dict:
    out = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)) for k, v in DEFAULTS.items()}
    for row in conn.all("SELECT key, value FROM settings"):
        if row["key"] in DEFAULTS:
            out[row["key"]] = loads(row["value"], DEFAULTS[row["key"]])
    return out


def _clean_list(values, max_items=40, max_len=60) -> list[str]:
    seen, out = set(), []
    for v in values or []:
        s = " ".join(str(v).split())[:max_len]
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:max_items]


def validate(patch: dict) -> dict:
    """Return a cleaned subset of `patch`; raise ValueError with a readable message on bad input."""
    clean: dict = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise ValueError(f"Unknown setting: {key}")
        if key in ("target_genres", "target_locations"):
            if not isinstance(value, list):
                raise ValueError(f"{key} must be a list")
            clean[key] = _clean_list(value)
        elif key == "target_platforms":
            vals = [N.norm_platform(v) for v in (value or [])]
            clean[key] = [v for v in dict.fromkeys(vals) if v and v != "other"]
        elif key == "enabled_providers":
            clean[key] = [str(v) for v in dict.fromkeys(value or []) if str(v) in ("audius", "youtube", "websearch")]
        elif key == "timezone":
            tz = str(value or "").strip()
            if not tz or len(tz) > 64:
                raise ValueError("Timezone is required")
            clean[key] = tz
        elif key == "weights":
            if not isinstance(value, dict):
                raise ValueError("weights must be an object")
            w = {}
            for code, pts in value.items():
                if code not in DEFAULT_WEIGHTS:
                    raise ValueError(f"Unknown signal: {code}")
                try:
                    n = int(pts)
                except (TypeError, ValueError):
                    raise ValueError(f"Points for {code} must be a whole number")
                if not -50 <= n <= 50:
                    raise ValueError("Signal points must be between -50 and 50")
                if n != DEFAULT_WEIGHTS[code]:
                    w[code] = n
            clean[key] = w
        else:
            lo, hi = LIMITS[key]
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a whole number")
            if not lo <= n <= hi:
                raise ValueError(f"{key} must be between {lo} and {hi}")
            clean[key] = n
    return clean


def save(conn: Conn, patch: dict) -> dict:
    clean = validate(patch)
    now = N.now_iso()
    for key, value in clean.items():
        conn.run("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                 (key, dumps(value), now))
    return clean


def get_meta(conn: Conn, key: str, default: str = "") -> str:
    v = conn.scalar("SELECT value FROM meta WHERE key = ?", (key,))
    return default if v is None else v


def set_meta(conn: Conn, key: str, value: str) -> None:
    conn.run("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
             (key, value))
