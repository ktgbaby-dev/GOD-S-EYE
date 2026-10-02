"""Pure helpers: time, platforms, handles, profile URLs, follower counts, genres and locations. No I/O."""
import re
import unicodedata
from datetime import datetime, timedelta, timezone, tzinfo
from urllib.parse import urlparse

# ------------------------------------------------------------------------------------------------ time

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return iso(utcnow())


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value) -> datetime | None:
    """ISO date/datetime (with or without zone) -> aware UTC datetime. Unknown -> None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
        if not m:
            return parse_loose_date(s)
        dt = datetime(int(m[1]), int(m[2]), int(m[3]))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_loose_date(text: str, ref: datetime | None = None) -> datetime | None:
    """Dates as search engines print them: '3 days ago', 'yesterday', 'Sep 28, 2026', '28 Sep 2026', 28/09/2026."""
    ref = ref or utcnow()
    s = (text or "").strip().lower()
    if not s:
        return None
    if s in ("today", "just now"):
        return ref
    if s == "yesterday":
        return ref - timedelta(days=1)
    m = re.match(r"^(\d+|an?|one)\s+(second|minute|hour|day|week|month|year)s?\s+ago", s)
    if m:
        n = 1 if m[1] in ("a", "an", "one") else int(m[1])
        unit = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30,
                "year": 365}[m[2]]
        return ref - timedelta(days=n * unit)
    try:
        m = re.match(r"^([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
        if m and m[1] in _MONTHS:
            return datetime(int(m[3]), _MONTHS[m[1]], int(m[2]), tzinfo=timezone.utc)
        m = re.match(r"^(\d{1,2})\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})", s)
        if m and m[2] in _MONTHS:
            return datetime(int(m[3]), _MONTHS[m[2]], int(m[1]), tzinfo=timezone.utc)
        m = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$", s)
        if m:  # day-first, as written in Nigeria and the UK
            return datetime(int(m[3]), int(m[2]), int(m[1]), tzinfo=timezone.utc)
    except ValueError:
        return None
    return None


def days_since(value, ref: datetime | None = None) -> float | None:
    dt = parse_dt(value)
    if dt is None:
        return None
    return max(0.0, ((ref or utcnow()) - dt).total_seconds() / 86400)


_FIXED_OFFSETS = {"Africa/Lagos": 60, "Africa/Accra": 0, "Europe/London": 0, "UTC": 0, "Africa/Johannesburg": 120,
                  "Africa/Nairobi": 180}


def get_tz(name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # no tz database on this machine: fall back to a fixed offset
        return timezone(timedelta(minutes=_FIXED_OFFSETS.get(name, 60)))


def local_day_start(tz_name: str, days_back: int = 0, ref: datetime | None = None) -> datetime:
    """Start of the local calendar day (days_back days ago) as an aware UTC datetime."""
    tz = get_tz(tz_name)
    local = (ref or utcnow()).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return start.astimezone(timezone.utc)


def local_date_str(value, tz_name: str) -> str:
    dt = parse_dt(value)
    return dt.astimezone(get_tz(tz_name)).strftime("%Y-%m-%d") if dt else ""


# ------------------------------------------------------------------------------------------------ platforms

PLATFORMS: dict[str, dict] = {
    "instagram": {"label": "Instagram", "url": "https://www.instagram.com/{h}/"},
    "tiktok": {"label": "TikTok", "url": "https://www.tiktok.com/@{h}"},
    "youtube": {"label": "YouTube", "url": "https://www.youtube.com/@{h}"},
    "x": {"label": "X", "url": "https://x.com/{h}"},
    "audius": {"label": "Audius", "url": "https://audius.co/{h}"},
    "soundcloud": {"label": "SoundCloud", "url": "https://soundcloud.com/{h}"},
    "audiomack": {"label": "Audiomack", "url": "https://audiomack.com/{h}"},
    "boomplay": {"label": "Boomplay", "url": ""},
    "spotify": {"label": "Spotify", "url": ""},
    "other": {"label": "Other", "url": ""},
}

_PLATFORM_ALIASES = {
    "ig": "instagram", "insta": "instagram", "instagram": "instagram",
    "tiktok": "tiktok", "tik tok": "tiktok", "tt": "tiktok",
    "youtube": "youtube", "yt": "youtube", "you tube": "youtube",
    "x": "x", "twitter": "x", "x (twitter)": "x",
    "audius": "audius", "soundcloud": "soundcloud", "sound cloud": "soundcloud",
    "audiomack": "audiomack", "boomplay": "boomplay", "spotify": "spotify", "other": "other",
}


def norm_platform(value: str) -> str:
    v = (value or "").strip().lower()
    return _PLATFORM_ALIASES.get(v, "other" if v else "")


def platform_label(key: str) -> str:
    return PLATFORMS.get(key, PLATFORMS["other"])["label"]


_HANDLE_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,59}$")


def clean_handle(handle: str) -> str:
    """Display form: no leading @, no surrounding spaces or slashes, original case kept."""
    h = unicodedata.normalize("NFKC", handle or "").strip().strip("/").strip()
    while h.startswith("@"):
        h = h[1:]
    return h.strip()


def norm_handle(handle: str) -> str:
    return clean_handle(handle).lower()


def valid_handle(platform: str, handle: str) -> bool:
    h = norm_handle(handle)
    if not h:
        return False
    if platform in ("spotify", "boomplay", "other"):
        return len(h) <= 120 and not any(c.isspace() for c in h)
    return bool(_HANDLE_RX.match(h))


def profile_url_for(platform: str, handle: str) -> str:
    tpl = PLATFORMS.get(platform, {}).get("url", "")
    h = clean_handle(handle)
    return tpl.format(h=h) if tpl and h else ""


def safe_url(url: str) -> str:
    """Only http(s) URLs are stored or rendered as links."""
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", u, re.I):
            u = "https://" + u
        else:
            return ""
    p = urlparse(u)
    return u if p.scheme in ("http", "https") and p.netloc else ""


_IG_RESERVED = {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "direct", "about", "developer",
                "legal", "web", "privacy", "help", "challenge", "s", "sessions"}
_X_RESERVED = {"home", "i", "search", "intent", "share", "hashtag", "explore", "settings", "login", "signup", "tos"}
_GENERIC_RESERVED = {"search", "discover", "explore", "login", "signup", "upload", "charts", "trending", "settings",
                     "pages", "terms", "privacy", "you", "feed", "watch", "results", "playlist", "embed", "shorts"}


def parse_profile_url(url: str) -> tuple[str, str] | None:
    """Public profile/post URL -> (platform, handle). None if no handle can be read from the URL itself."""
    u = safe_url(url)
    if not u:
        return None
    p = urlparse(u)
    host = p.netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    parts = [s for s in p.path.split("/") if s]
    if not parts:
        return None
    first = parts[0]
    if host.endswith("instagram.com"):
        if first.lower() in _IG_RESERVED:
            return None
        return ("instagram", first) if valid_handle("instagram", first) else None
    if host.endswith("tiktok.com"):
        if first.startswith("@") and valid_handle("tiktok", first):
            return "tiktok", clean_handle(first)
        return None
    if host.endswith("youtube.com"):
        if first.startswith("@") and valid_handle("youtube", first):
            return "youtube", clean_handle(first)
        if first in ("c", "user") and len(parts) > 1 and valid_handle("youtube", parts[1]):
            return "youtube", parts[1]
        if first == "channel" and len(parts) > 1 and re.match(r"^UC[\w-]{20,}$", parts[1]):
            return "youtube", parts[1]
        return None
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        if first.lower() in _X_RESERVED or not re.match(r"^\w{1,15}$", first):
            return None
        return "x", first
    if host.endswith("audius.co"):
        return ("audius", first) if first.lower() not in _GENERIC_RESERVED and valid_handle("audius", first) else None
    if host.endswith("soundcloud.com"):
        return ("soundcloud", first) if first.lower() not in _GENERIC_RESERVED and valid_handle("soundcloud", first) else None
    if host.endswith("audiomack.com"):
        return ("audiomack", first) if first.lower() not in _GENERIC_RESERVED and valid_handle("audiomack", first) else None
    if host == "open.spotify.com" and first == "artist" and len(parts) > 1:
        return "spotify", parts[1]
    if host.endswith("boomplay.com") and first == "artists" and len(parts) > 1:
        return "boomplay", parts[1]
    return None


# ------------------------------------------------------------------------------------------------ numbers

def parse_count(value) -> int | None:
    """'12.4K' -> 12400, '1,234' -> 1234, '1.2M followers' -> 1200000. Unknown -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    s = str(value).strip().lower().replace(",", "").replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)([kmb])?", s)
    if not m:
        return None
    n = float(m[1]) * {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m[2] or "", 1)
    return int(round(n))


def followers_from_text(text: str) -> int | None:
    m = re.search(r"(\d[\d,.]*\s?[KkMmBb]?)\+?\s+(?:followers|subscribers|fans)\b", text or "", re.I)
    return parse_count(m[1]) if m else None


def fmt_count(n: int | None) -> str:
    if n is None:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 10_000:
        return f"{n / 1000:.0f}K"
    if n >= 1_000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


# ------------------------------------------------------------------------------------------------ genres / places

# Canonical genre -> phrases that count as a mention. Genres not listed here match on their own name.
GENRE_SYNONYMS: dict[str, list[str]] = {
    "Afrobeats": ["afrobeats", "afrobeat", "afro beats", "afro-beats", "afro beat"],
    "Afropop": ["afropop", "afro pop", "afro-pop"],
    "Afro-fusion": ["afro-fusion", "afrofusion", "afro fusion"],
    "Amapiano": ["amapiano", "ama piano"],
    "R&B": ["r&b", "rnb", "r'n'b", "r and b", "r & b", "rhythm and blues"],
    "Hip-Hop": ["hip-hop", "hip hop", "hiphop"],
    "Rap": ["rap", "rapper"],
    "Afro-soul": ["afro-soul", "afrosoul", "afro soul"],
    "Street-pop": ["street-pop", "street pop", "streetpop"],
    "Alté": ["alté", "alte"],
    "Highlife": ["highlife", "high life"],
    "Dancehall": ["dancehall"],
    "Drill": ["drill"],
    "Trap": ["trap"],
    "Gospel": ["gospel"],
    "Soul": ["soul"],
    "Pop": ["pop"],
    "Reggae": ["reggae"],
    "Fuji": ["fuji"],
    "Afro-house": ["afro house", "afro-house", "afrohouse"],
}


def _phrases(genre: str) -> list[str]:
    g = genre.strip()
    return GENRE_SYNONYMS.get(g) or next(
        (v for k, v in GENRE_SYNONYMS.items() if k.lower() == g.lower()), [g.lower()])


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None


def detect_genres(text: str, candidates: list[str] | None = None) -> list[str]:
    """Genres mentioned in the text, in the order of `candidates` (defaults to the known list).
    'Afropop' is not also reported as 'Pop'."""
    t = (text or "").lower()
    found: list[str] = []
    for g in candidates or list(GENRE_SYNONYMS):
        if any(_contains_phrase(t, p) for p in _phrases(g)):
            found.append(g)
    if "Pop" in found and any(g in found for g in ("Afropop", "Street-pop", "Hyperpop")):
        if not re.search(r"(?<![a-z-])pop(?![a-z])", re.sub(r"afro[ -]?pop|street[ -]?pop", "", t)):
            found.remove("Pop")
    return found


def genre_matches(genre: str, targets: list[str]) -> str | None:
    """The target genre that `genre` (free text, possibly 'Afrobeats, R&B') satisfies, if any."""
    hits = detect_genres(genre, targets)
    return hits[0] if hits else None


COUNTRY_NAMES = {"NG": "Nigeria", "GH": "Ghana", "GB": "United Kingdom", "UK": "United Kingdom", "ZA": "South Africa",
                 "KE": "Kenya", "US": "United States", "CA": "Canada", "IE": "Ireland", "FR": "France",
                 "DE": "Germany", "NL": "Netherlands", "CM": "Cameroon", "SN": "Senegal", "CI": "Côte d'Ivoire",
                 "UG": "Uganda", "TZ": "Tanzania", "RW": "Rwanda", "BJ": "Benin", "TG": "Togo", "SL": "Sierra Leone",
                 "LR": "Liberia", "GM": "Gambia", "ZW": "Zimbabwe", "ZM": "Zambia", "BW": "Botswana", "AE": "UAE"}

# Cities/regions -> the country they belong to, so a target of "Nigeria" also matches "Lagos".
PLACE_COUNTRY = {
    "lagos": "Nigeria", "abuja": "Nigeria", "ibadan": "Nigeria", "port harcourt": "Nigeria", "ph city": "Nigeria",
    "benin city": "Nigeria", "enugu": "Nigeria", "kano": "Nigeria", "kaduna": "Nigeria", "warri": "Nigeria",
    "abeokuta": "Nigeria", "owerri": "Nigeria", "uyo": "Nigeria", "calabar": "Nigeria", "jos": "Nigeria",
    "ilorin": "Nigeria", "akure": "Nigeria", "asaba": "Nigeria", "onitsha": "Nigeria", "lekki": "Nigeria",
    "ikeja": "Nigeria", "surulere": "Nigeria", "yaba": "Nigeria", "osogbo": "Nigeria", "ile-ife": "Nigeria",
    "accra": "Ghana", "kumasi": "Ghana", "tema": "Ghana", "takoradi": "Ghana",
    "london": "United Kingdom", "manchester": "United Kingdom", "birmingham": "United Kingdom",
    "leeds": "United Kingdom", "liverpool": "United Kingdom", "glasgow": "United Kingdom", "bristol": "United Kingdom",
    "nottingham": "United Kingdom", "leicester": "United Kingdom", "sheffield": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "johannesburg": "South Africa", "cape town": "South Africa", "durban": "South Africa", "pretoria": "South Africa",
    "nairobi": "Kenya", "mombasa": "Kenya", "kampala": "Uganda", "dar es salaam": "Tanzania", "kigali": "Rwanda",
    "douala": "Cameroon", "yaoundé": "Cameroon", "dakar": "Senegal", "abidjan": "Côte d'Ivoire",
    "freetown": "Sierra Leone", "monrovia": "Liberia", "harare": "Zimbabwe", "lusaka": "Zambia", "dubai": "UAE",
    "toronto": "Canada", "houston": "United States", "atlanta": "United States", "new york": "United States",
    "los angeles": "United States", "dallas": "United States", "chicago": "United States",
}
_COUNTRY_ALIASES = {"uk": "United Kingdom", "u.k.": "United Kingdom", "united kingdom": "United Kingdom",
                    "great britain": "United Kingdom", "britain": "United Kingdom", "naija": "Nigeria",
                    "usa": "United States", "u.s.a.": "United States", "united states": "United States",
                    "south africa": "South Africa", "sa": "South Africa", "nigeria": "Nigeria", "ghana": "Ghana",
                    "kenya": "Kenya", "uae": "UAE"}


def canonical_country(target: str) -> str | None:
    t = (target or "").strip().lower()
    if t in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[t]
    for name in COUNTRY_NAMES.values():
        if name.lower() == t:
            return name
    return None


def location_matches(location_text: str, targets: list[str]) -> str | None:
    """The first target satisfied by the location text. 'Lagos, Nigeria' satisfies 'Lagos' and 'Nigeria';
    'Lekki' satisfies 'Nigeria' (city -> country) but not 'Abuja'."""
    t = (location_text or "").lower()
    if not t.strip():
        return None
    mentioned_countries = {c for place, c in PLACE_COUNTRY.items() if _contains_phrase(t, place)}
    for alias, country in _COUNTRY_ALIASES.items():
        if len(alias) > 2 and _contains_phrase(t, alias):
            mentioned_countries.add(country)
    if re.search(r"(?<![a-z])uk(?![a-z])", t):
        mentioned_countries.add("United Kingdom")
    for target in targets:
        tl = target.strip().lower()
        if not tl:
            continue
        if _contains_phrase(t, tl):
            return target
        country = canonical_country(target)
        if country and country in mentioned_countries:
            return target
    return None


def region_code(location: str) -> str:
    """Best-effort ISO country code for a target location (used to bias API searches)."""
    country = canonical_country(location) or PLACE_COUNTRY.get((location or "").strip().lower())
    for code, name in COUNTRY_NAMES.items():
        if name == country and code != "UK":
            return code
    return ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
