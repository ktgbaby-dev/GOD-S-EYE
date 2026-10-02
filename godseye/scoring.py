"""Transparent lead scoring. A score is the sum of the signals that fired, clamped to 0–100.

Every signal has a fixed code, a label, configurable points (Strategy page) and, when it fires, the evidence that
triggered it. Unknown data never earns points. There is no model and no hidden weighting: what you see in the
breakdown is the whole calculation."""
import re
from datetime import datetime

from . import normalize as N

# (code, group, label, default points, short phrase used in the "why" sentence)
SIGNALS: list[tuple[str, str, str, int, str]] = [
    ("active_7d", "Activity", "Active in the last 7 days", 15, "active this week"),
    ("active_30d", "Activity", "Active in the last 30 days", 8, "active this month"),
    ("consistent", "Activity", "Consistent output (3+ uploads in 30 days)", 8, "posting consistently"),
    ("release_14d", "Release", "Released music in the last 14 days", 18, "just released music"),
    ("release_60d", "Release", "Released music in the last 60 days", 10, "released music recently"),
    ("promoting_upcoming", "Release", "Promoting upcoming music", 10, "teasing new music"),
    ("independent", "Artist status", "Independent / unsigned", 10, "independent"),
    ("audience_emerging", "Artist status", "Emerging audience (1K–50K)", 10, "emerging audience"),
    ("audience_growing", "Artist status", "Growing audience (50K–250K)", 6, "growing audience"),
    ("audience_micro", "Artist status", "Early audience (under 1K)", 3, "early-stage audience"),
    ("audience_large", "Artist status", "Large audience (250K+)", 2, "large audience"),
    ("seeking_producer", "Production need", "Publicly looking for a producer or beats", 22, "looking for a producer"),
    ("seeking_collab", "Production need", "Open to collaborations", 12, "open to collabs"),
    ("new_project", "Production need", "Working on a new project", 8, "building a new project"),
    ("studio_activity", "Production need", "Talking about recording / studio time", 5, "in the studio"),
    ("genre_fit", "Fit", "Genre matches your sound", 12, "genre fit"),
    ("location_fit", "Fit", "In a target location", 12, "in a target market"),
    ("fresh_24h", "Freshness", "Discovered in the last 24 hours", 5, "fresh find"),
    ("fresh_7d", "Freshness", "Discovered this week", 2, "found this week"),
    ("is_producer", "Noise", "Looks like a producer or beat seller", -30, "looks like a producer"),
    ("aggregator", "Noise", "Looks like a channel or page, not an artist", -30, "looks like a page, not an artist"),
    ("auto_generated", "Noise", "Uploads look auto-generated or spammy", -30, "uploads look auto-generated"),
    ("label_signed", "Noise", "Label mention: may have in-house producers", -8, "label mention"),
    ("inactive", "Noise", "No activity for 90+ days", -12, "quiet for 90+ days"),
]
SIGNAL_BY_CODE = {s[0]: s for s in SIGNALS}
GROUPS = ["Activity", "Release", "Artist status", "Production need", "Fit", "Freshness", "Noise"]
DEFAULT_WEIGHTS = {s[0]: s[3] for s in SIGNALS}

# Signals that are only reported as "unknown" when the data needed to test them is missing.
KEY_CHECKS = [("activity", "Last activity date"), ("followers", "Audience size"), ("genre", "Genre"),
              ("location", "Location")]

# ------------------------------------------------------------------------------------------------ phrase lists
SEEKING_PRODUCER = [
    "looking for a producer", "looking for producers", "looking for a beat", "looking for beats", "need a producer",
    "need producers", "needs a producer", "need beats", "need a beat", "send me beats", "send beats",
    "send your beats", "beats wanted", "producer needed", "producers needed", "producers wanted", "producers dm",
    "producers hit me", "accepting beats", "beat submissions", "submit beats", "submit your beats",
    "searching for a producer", "in need of a producer", "who's got beats", "who got beats",
]
SEEKING_COLLAB = [
    "open for collab", "open for collabs", "open to collab", "open to collabs", "collabs open", "collab open",
    "dm for collab", "dm for collabs", "for collab", "for collabs",
    "let's collab", "lets collab", "collaborations welcome", "open for features", "features open",
    "dm for features", "available for features", "open to features", "bookings & collabs", "bookings and collabs",
    "bookings/collabs", "collabs & bookings", "collabs and bookings", "open for collaboration",
]
NEW_PROJECT = [
    "new ep", "new album", "ep loading", "album loading", "project loading", "mixtape loading", "debut ep",
    "debut album", "upcoming ep", "upcoming album", "new project", "next project", "ep coming", "album coming",
    "ep out soon", "album out soon", "working on my", "working on new music", "recording my ep",
    "recording my album", "new tape",
]
UPCOMING = [
    "coming soon", "out soon", "dropping soon", "drops friday", "dropping friday", "out friday", "pre-save",
    "presave", "pre save", "snippet", "snippets", "dropping this", "drops this", "drops next", "dropping next",
    "countdown", "release date", "loading...", "who's ready for", "unreleased",
]
RELEASE = [
    "out now", "new single", "new music", "official video", "official music video", "official audio",
    "official visualizer", "official lyric video", "stream now", "available on all platforms",
    "available everywhere", "on all platforms", "streaming everywhere", "new song", "debut single",
    "music video", "lyric video", "visualizer", "now streaming", "just dropped", "out everywhere",
]
STUDIO = [
    "in the studio", "studio session", "studio sessions", "studio vibes", "recording session", "studio days",
    "studio time", "late night studio", "studio flow", "in the booth", "booth session", "cooking in the studio",
    "studio diaries", "studio life",
]
INDEPENDENT = ["independent artist", "independent musician", "indie artist", "unsigned", "self-released",
               "self released", "diy artist", "independent"]
PRODUCER_BIO = [
    "music producer", "beatmaker", "beat maker", "record producer", "i make beats", "beats for sale", "buy beats",
    "beat store", "lease beats", "beat leases", "type beat", "free beat", "beat tape", "mixing engineer",
    "mix engineer", "mastering engineer", "beats available", "exclusive beats", "producer |", "producer/",
    "producer.", "producer &", "| producer", "audio engineer",
]
PRODUCER_TITLE = ["type beat", "instrumental", "free beat", "beat for sale", "[free]", "(free)", "beat tape"]
LABEL = [
    "signed to", "signed artist", "record label", "under the label", "mavin records", "mavin global", "ybnl",
    "chocolate city", "dmw", "starboy entertainment", "spaceship records", "marlian music", "sony music",
    "universal music", "warner music", "def jam", "atlantic records", "columbia records", "island records",
    "rca records", "emi records", "5k records", "upfront & personal",
]
AGGREGATOR_NAME = [
    r"\btv\b", r"\bvevo\b", r"\brecords?\b", r"\bmix(es|tape)?s?\b", r"\bhits\b", r"\bplaylists?\b", r"\bradio\b",
    r"\bentertainment\b", r"\bpromo(tions?)?\b", r"\bblog\b", r"\bmagazine\b", r"\bmedia\b", r"\blyrics\b",
    r"\bchannel\b", r"\bfm\b", r"\bcharts?\b", r"\bupdates?\b", r"\bnews\b", r"- topic$", r"\bcompilations?\b",
    r"\bnation\b", r"\bdaily\b", r"\bvibes only\b", r"\bmusic plug\b",
]


_GENRE_PLACES = re.compile(r"\b(uk|london|nyc|chicago|detroit|atlanta|brooklyn|texas|jersey)[ -]?(drill|rap|garage|grime|funky|hip[ -]?hop|club|trap)\b", re.I)
_HASH_RX = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{8,}\b", re.I)


def _find(text: str, phrases: list[str]) -> tuple[str, str] | None:
    """First phrase found in text -> (phrase, short quote around it)."""
    t = text.lower()
    for p in phrases:
        idx = _index_of(t, p)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(text), idx + len(p) + 40)
            quote = text[start:end].strip().replace("\n", " ")
            return p, ("…" if start > 0 else "") + re.sub(r"\s+", " ", quote) + ("…" if end < len(text) else "")
    return None


def _index_of(text: str, phrase: str) -> int:
    if phrase[0].isalnum() and phrase[-1].isalnum():
        m = re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text)
        return m.start() if m else -1
    return text.find(phrase)


def _corpus(lead: dict) -> list[tuple[str, str, str | None, str | None]]:
    """[(source label, text, url, date)] — bio first, then each evidence item."""
    out = []
    if lead.get("bio"):
        out.append(("Bio", lead["bio"], lead.get("profile_url") or None, None))
    for ev in lead.get("evidence") or []:
        text = " ".join(x for x in (ev.get("title"), ev.get("text")) if x)
        if text.strip():
            out.append((ev.get("label") or ev.get("kind") or "Source", text, ev.get("url"), ev.get("date")))
    return out


def _search(corpus, phrases) -> dict | None:
    for label, text, url, date in corpus:
        hit = _find(text, phrases)
        if hit:
            return {"evidence": f"{label}: “{hit[1]}”", "url": url, "date": date, "phrase": hit[0]}
    return None


def _days(n: float) -> str:
    n = int(n)
    return "today" if n == 0 else ("1 day ago" if n == 1 else f"{n} days ago")


def score_lead(lead: dict, strategy: dict, now: datetime | None = None) -> dict:
    """Return {"score", "breakdown", "reason", "last_activity_at", "last_release_at"} for a lead dict.

    `lead` needs: name, handle, platform, bio, genre, location, followers, evidence (list), discovered_at,
    last_activity_at, last_release_at, uploads_30d. `strategy` supplies target genres/locations and weights."""
    now = now or N.utcnow()
    weights = {**DEFAULT_WEIGHTS, **(strategy.get("weights") or {})}
    corpus = _corpus(lead)
    fired: dict[str, dict] = {}

    def fire(code, evidence, url=None, date=None):
        if code not in fired:
            fired[code] = {"evidence": evidence, "url": url, "date": date}

    # ---- dates: activity and releases (explicit fields + dated evidence)
    release_at = N.parse_dt(lead.get("last_release_at"))
    release_ev = None
    for label, text, url, date in corpus:
        d = N.parse_dt(date)
        if d and _find(text, RELEASE):
            if release_at is None or d > release_at:
                release_at, release_ev = d, (label, text, url)
    activity_at = N.parse_dt(lead.get("last_activity_at"))
    for _label, _text, _url, date in corpus:
        d = N.parse_dt(date)
        if d and d <= now and (activity_at is None or d > activity_at):
            activity_at = d
    if release_at and release_at <= now and (activity_at is None or release_at > activity_at):
        activity_at = release_at

    act_days = N.days_since(activity_at, now) if activity_at else None
    if act_days is not None:
        if act_days <= 7:
            fire("active_7d", f"Last public activity {_days(act_days)}")
        elif act_days <= 30:
            fire("active_30d", f"Last public activity {_days(act_days)}")
        elif act_days > 90:
            fire("inactive", f"Last public activity {_days(act_days)}")
    uploads = lead.get("uploads_30d")
    if isinstance(uploads, int) and uploads >= 3:
        fire("consistent", f"{uploads} uploads in the last 30 days")

    if release_at and release_at <= now:
        rel_days = N.days_since(release_at, now)
        what = f"Music released {_days(rel_days)}"
        url = release_ev[2] if release_ev else None
        if release_ev:
            what += f" ({release_ev[0]}: “{_shorten(release_ev[1])}”)"
        if rel_days <= 14:
            fire("release_14d", what, url)
        elif rel_days <= 60:
            fire("release_60d", what, url)

    # ---- text signals
    for code, phrases in (("seeking_producer", SEEKING_PRODUCER), ("seeking_collab", SEEKING_COLLAB),
                          ("new_project", NEW_PROJECT), ("promoting_upcoming", UPCOMING),
                          ("studio_activity", STUDIO), ("independent", INDEPENDENT), ("label_signed", LABEL)):
        hit = _search(corpus, phrases)
        if hit:
            fire(code, hit["evidence"], hit["url"], hit["date"])
    if "independent" in fired and "label_signed" in fired:
        del fired["label_signed"]  # "independent, formerly signed to…" — trust the explicit claim

    # ---- noise: producers and pages
    name_handle = f"{lead.get('name', '')} {lead.get('handle', '')}".lower()
    nh = re.sub(r"afro[ -]?beats?", "", name_handle)
    producer = None
    if re.search(r"(beats?|beatz|prod\b|prodby|producer|instrumentals?)", nh):
        producer = f"Name/handle: “{lead.get('name') or lead.get('handle')}”"
    elif lead.get("bio") and _find(lead["bio"], PRODUCER_BIO):
        producer = f"Bio: “{_find(lead['bio'], PRODUCER_BIO)[1]}”"
    else:
        titles = [ev for ev in (lead.get("evidence") or []) if ev.get("title")]
        beat_titles = [ev for ev in titles if _find(ev["title"], PRODUCER_TITLE)]
        if titles and len(beat_titles) * 2 >= len(titles):
            producer = f"Uploads titled like beats: “{_shorten(beat_titles[0]['title'])}”"
    if producer:
        fire("is_producer", producer)
    titles = [ev["title"] for ev in (lead.get("evidence") or []) if ev.get("title")]
    hashed = [t for t in titles if _HASH_RX.search(t)]
    bases: dict[str, int] = {}
    for t in titles:
        base = re.sub(r"[\s\-_#(\[]*([0-9a-f]{6,}|\d+)[)\]]*\s*$", "", t.lower()).strip()
        bases[base] = bases.get(base, 0) + 1
    if len(hashed) >= 2:
        fire("auto_generated", f"Titles like “{_shorten(hashed[0])}”")
    elif titles and max(bases.values()) >= 3:
        fire("auto_generated", f"{max(bases.values())} uploads share the title “{_shorten(max(bases, key=bases.get))}”")
    name = (lead.get("name") or "").lower()
    for rx in AGGREGATOR_NAME:
        if re.search(rx, name):
            fire("aggregator", f"Name: “{lead.get('name')}”")
            break

    # ---- audience
    followers = lead.get("followers")
    if isinstance(followers, int):
        label = f"{N.fmt_count(followers)} followers"
        if followers >= 250_000:
            fire("audience_large", label)
        elif followers >= 50_000:
            fire("audience_growing", label)
        elif followers >= 1_000:
            fire("audience_emerging", label)
        else:
            fire("audience_micro", label)

    # ---- fit
    targets_g = strategy.get("target_genres") or []
    genre_text = lead.get("genre") or ""
    g = N.genre_matches(genre_text, targets_g) if genre_text else None
    if g:
        fire("genre_fit", f"Genre: {genre_text}")
    else:
        for label, text, url, date in corpus:
            hits = N.detect_genres(text, targets_g)
            if hits:
                fire("genre_fit", f"{label} mentions {hits[0]}", url)
                break
    targets_l = strategy.get("target_locations") or []
    loc = lead.get("location") or ""
    lm = N.location_matches(loc, targets_l) if loc else None
    if lm:
        fire("location_fit", f"Location: {loc}")
    elif targets_l:
        # Only self-descriptions count (bio, profile snippets): captions and track tags mention places loosely,
        # and genre names like "UK drill" are not locations.
        for label, text, url, _date in [c for c in corpus if c[0] == "Bio" or c[0].endswith("profile")]:
            lm = N.location_matches(_GENRE_PLACES.sub(" ", text), targets_l)
            if lm:
                fire("location_fit", f"{label} mentions {lm}", url)
                break

    # ---- freshness
    disc_days = N.days_since(lead.get("discovered_at"), now)
    if disc_days is not None:
        if disc_days <= 1:
            fire("fresh_24h", "Discovered " + ("today" if disc_days < 1 else "yesterday"))
        elif disc_days <= 7:
            fire("fresh_7d", f"Discovered {_days(disc_days)}")

    items = []
    for code, group, label, _default, _phrase in SIGNALS:
        if code in fired and weights.get(code, 0) != 0:
            items.append({"code": code, "group": group, "label": label, "points": int(weights[code]), **fired[code]})
    raw = sum(i["points"] for i in items)
    total = max(0, min(100, raw))

    unknown = []
    if activity_at is None:
        unknown.append("Last activity date")
    if not isinstance(followers, int):
        unknown.append("Audience size")
    if not genre_text and "genre_fit" not in fired:
        unknown.append("Genre")
    if not loc and "location_fit" not in fired:
        unknown.append("Location")

    breakdown = {"total": total, "raw": raw, "items": items, "unknown": unknown, "scored_at": N.iso(now)}
    return {"score": total, "breakdown": breakdown, "reason": build_reason(items, lead),
            "last_activity_at": N.iso(activity_at) if activity_at else None,
            "last_release_at": N.iso(release_at) if release_at else None}


def _shorten(text: str, n: int = 70) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def build_reason(items: list[dict], lead: dict) -> str:
    """One plain sentence from the strongest positive signals, plus any caution."""
    positives = sorted([i for i in items if i["points"] > 0 and i["group"] != "Freshness"],
                       key=lambda i: -i["points"])
    parts = [SIGNAL_BY_CODE[i["code"]][4] for i in positives[:4]]
    negatives = [SIGNAL_BY_CODE[i["code"]][4] for i in items if i["points"] < 0]
    if not parts and not negatives:
        return "Not enough public signal yet. Add a bio, release date or follower count to score this properly."
    sentence = ", ".join(parts)
    sentence = sentence[:1].upper() + sentence[1:] if sentence else ""
    if negatives:
        caution = "Caution: " + ", ".join(negatives) + "."
        return (sentence + ". " if sentence else "") + caution
    return sentence + "."


def weights_catalogue(weights: dict) -> list[dict]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    return [{"code": c, "group": g, "label": l, "default": d, "points": int(w[c])} for c, g, l, d, _p in SIGNALS]
