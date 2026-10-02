"""Discovery provider contract.

A provider turns a ScanPlan (what OG-WAN is looking for) into query specs, runs one spec at a time against a real
public source, and returns candidates. A candidate is a public profile the source actually returned: providers
never invent names or handles. To add a source, subclass DiscoveryProvider and register it in discovery/__init__.py.

Candidate dict:
    platform, handle, name, profile_url, followers, location, genre, bio,
    last_activity_at, last_release_at, uploads_30d,
    source (provider key), source_label, source_url,
    evidence: [{kind, label, title, text, url, date}],
    linked:   [{platform, handle, url, provenance: "linked" | "verified_link"}]
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .. import normalize as N
from ..config import Config

USER_AGENT = "GodsEye/1.0 (private client discovery)"

LOOKING_FOR = {"artists": "artist", "singers": "singer", "rappers": "rapper", "songwriters": "songwriter",
               "groups": "music group"}

# Search phrases per signal. The first phrase of each list is used most; rotation picks the others over time.
SIGNAL_PHRASES = {
    "recent_release": ["new single", "out now", "official video"],
    "seeking_producer": ["looking for a producer", "need beats", "send beats"],
    "upcoming_project": ["new EP", "coming soon", "snippet"],
    "collab": ["open for collabs", "collab"],
    "studio": ["studio session", "in the studio"],
}
SIGNAL_LABELS = {"any": "Any signal", "recent_release": "Recently released music",
                 "seeking_producer": "Looking for producers / beats", "upcoming_project": "Upcoming project",
                 "collab": "Open to collaborations", "studio": "In the studio"}


class ProviderError(Exception):
    pass


def http_json(url: str, *, method: str = "GET", params: dict | None = None, headers: dict | None = None,
              body: dict | None = None, timeout: float = 15) -> dict | list:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, "")}, doseq=True)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            payload = json.loads(e.read().decode("utf-8", "replace"))
            err = payload.get("error") if isinstance(payload, dict) else None
            detail = (err.get("message") if isinstance(err, dict) else err) or payload.get("message") or ""
        except Exception:
            pass
        # Never echo the URL: it can carry an API key.
        raise ProviderError(f"HTTP {e.code}" + (f": {str(detail)[:160]}" if detail else ""))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"Network error: {getattr(e, 'reason', e)}")
    except ValueError:
        raise ProviderError("Source returned invalid JSON")


class DiscoveryProvider:
    key = "base"
    label = "Base"
    platforms: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    description = ""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.notes: list[str] = []

    def configured(self) -> bool:
        return True

    def specs(self, plan: dict) -> list[dict]:
        """Query specs for this plan: [{"key": stable string, "label": shown in the run log, ...params}]."""
        raise NotImplementedError

    def run(self, spec: dict, cursor: str, deadline: float) -> tuple[list[dict], str]:
        """Run one spec from `cursor` (''=start). Return (candidates, next_cursor; '' when exhausted)."""
        raise NotImplementedError


# ------------------------------------------------------------------------------------------------ shared helpers

def plan_phrases(plan: dict) -> list[tuple[str, str]]:
    """[(signal key, phrase)] for the plan's signal; 'any' cycles through every signal."""
    sig = plan.get("signal") or "any"
    keys = list(SIGNAL_PHRASES) if sig == "any" else [sig]
    out = []
    for i in range(3):
        for k in keys:
            phrases = SIGNAL_PHRASES.get(k, [])
            if i < len(phrases):
                out.append((k, phrases[i]))
    return out


_LINK_PATTERNS = [
    ("instagram", re.compile(r"instagram\.com/([A-Za-z0-9._]{2,30})", re.I)),
    ("tiktok", re.compile(r"tiktok\.com/@([A-Za-z0-9._]{2,30})", re.I)),
    ("x", re.compile(r"(?:twitter|x)\.com/([A-Za-z0-9_]{2,15})\b", re.I)),
    ("instagram", re.compile(r"\b(?:ig|insta|instagram)\s*[:\-–]\s*@?([A-Za-z0-9._]{2,30})", re.I)),
    ("tiktok", re.compile(r"\b(?:tiktok|tik tok|tt)\s*[:\-–]\s*@?([A-Za-z0-9._]{2,30})", re.I)),
    ("x", re.compile(r"\b(?:twitter|x)\s*[:\-–]\s*@?([A-Za-z0-9_]{2,15})\b", re.I)),
]


def linked_handles(text: str, source_label: str) -> list[dict]:
    """Handles an artist lists on their own public profile (e.g. 'IG: @name' in a YouTube description).
    These are suggestions: the artist published them, but GOD'S EYE has not verified the other account."""
    out, seen = [], set()
    for platform, rx in _LINK_PATTERNS:
        for m in rx.finditer(text or ""):
            h = m.group(1).rstrip(".")
            key = (platform, h.lower())
            if h.lower() in ("p", "reel", "explore", "accounts", "intent", "share", "home") or key in seen:
                continue
            if N.valid_handle(platform, h):
                seen.add(key)
                out.append({"platform": platform, "handle": h, "url": N.profile_url_for(platform, h),
                            "provenance": "linked", "source": source_label})
    return out[:6]


def detect_genre(texts: list[str], targets: list[str], fallback: str = "") -> str:
    found: list[str] = []
    for t in texts:
        for g in N.detect_genres(t, targets or None) + N.detect_genres(t):
            if g not in found:
                found.append(g)
    if not found and fallback:
        found = [fallback]
    return ", ".join(found[:3])[:80]


def short(text: str, n: int = 280) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"
