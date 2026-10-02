"""Public web search for Instagram and TikTok profiles, via a search API (Serper = Google results, or Brave).

GOD'S EYE never loads Instagram or TikTok pages itself. It reads what the search engine has publicly indexed: the
result URL (which carries the @handle), the title (name) and the snippet (bio text, follower count, captions).
Needs SERPER_API_KEY (https://serper.dev) or BRAVE_SEARCH_API_KEY (https://brave.com/search/api/)."""
import re

from .. import normalize as N
from .base import LOOKING_FOR, DiscoveryProvider, ProviderError, detect_genre, http_json, plan_phrases, short

DOMAINS = {"instagram": "instagram.com", "tiktok": "tiktok.com"}
GL = {"NG": "ng", "GH": "gh", "GB": "uk", "ZA": "za", "KE": "ke", "US": "us", "CA": "ca"}


class WebSearchProvider(DiscoveryProvider):
    key = "websearch"
    label = "Web search (Instagram · TikTok)"
    platforms = ("instagram", "tiktok")
    env_vars = ("SERPER_API_KEY", "BRAVE_SEARCH_API_KEY")
    description = ("Search-engine results for public Instagram and TikTok profiles and posts. Uses Serper (Google) "
                   "or Brave Search.")
    operators_blocked = False  # learned per process: free Serper plans reject site: and "quotes"

    def configured(self) -> bool:
        return bool(self.cfg.serper_key or self.cfg.brave_key)

    @property
    def engine(self) -> str:
        return "serper" if self.cfg.serper_key else "brave"

    def specs(self, plan: dict) -> list[dict]:
        role = LOOKING_FOR.get(plan.get("looking_for") or "artists", "artist")
        out = []
        for platform in [p for p in (plan.get("platforms") or []) if p in DOMAINS]:
            for genre in plan.get("genres") or []:
                for loc in plan.get("locations") or [""]:
                    for sig, phrase in plan_phrases(plan):
                        q = f'site:{DOMAINS[platform]} {genre} {role} {loc} "{phrase}"'.replace("  ", " ")
                        out.append({"key": f"{platform}|{genre}|{loc}|{phrase}|{role}".lower(),
                                    "label": f"{N.platform_label(platform)} · {genre} {role} {loc} “{phrase}”",
                                    "q": q, "platform": platform, "region": N.region_code(loc), "signal": sig})
        return out

    def run(self, spec: dict, cursor: str, deadline: float) -> tuple[list[dict], str]:
        page = int(cursor or 1)
        results = self._search(spec, page)
        out, seen = [], set()
        for r in results:
            cand = self._candidate(r, spec)
            if cand and (cand["platform"], cand["handle"].lower()) not in seen:
                seen.add((cand["platform"], cand["handle"].lower()))
                out.append(cand)
        return out, (str(page + 1) if len(results) >= 10 and page < 5 else "")

    def _search(self, spec: dict, page: int) -> list[dict]:
        if self.engine == "serper":
            q = simplify(spec["q"]) if WebSearchProvider.operators_blocked else spec["q"]
            try:
                data = self._serper(q, spec, page)
            except ProviderError as e:
                if "not allowed" in str(e).lower() and q != simplify(spec["q"]):
                    WebSearchProvider.operators_blocked = True
                    data = self._serper(simplify(spec["q"]), spec, page)
                else:
                    raise
            if WebSearchProvider.operators_blocked:
                note = ("Your Serper plan blocks site: and \"quoted\" operators, so plain-word searches were used "
                        "(broader results; non-profile links are discarded).")
                if note not in self.notes:
                    self.notes.append(note)
            return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", ""),
                     "date": r.get("date")} for r in data.get("organic") or [] if r.get("link")]
        base = self.cfg.provider_base_urls["brave"].rstrip("/")
        data = http_json(f"{base}/web/search", params={
            "q": spec["q"], "count": 20, "offset": page - 1, "freshness": "pm", "search_lang": "en",
            "country": spec.get("region") or "ALL"}, headers={"X-Subscription-Token": self.cfg.brave_key})
        results = ((data or {}).get("web") or {}).get("results") or []
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", ""),
                 "date": r.get("page_age") or r.get("age")} for r in results if r.get("url")]

    def _serper(self, q: str, spec: dict, page: int) -> dict:
        base = self.cfg.provider_base_urls["serper"].rstrip("/")
        body = {"q": q, "num": 20, "page": page, "hl": "en", "tbs": "qdr:m"}
        if GL.get(spec.get("region") or ""):
            body["gl"] = GL[spec["region"]]
        data = http_json(f"{base}/search", method="POST", headers={"X-API-KEY": self.cfg.serper_key}, body=body)
        if not isinstance(data, dict):
            raise ProviderError("Unexpected search response")
        return data

    def _candidate(self, r: dict, spec: dict) -> dict | None:
        url, title, snippet = N.safe_url(r.get("url", "")), _clean(r.get("title", "")), _clean(r.get("snippet", ""))
        parsed = N.parse_profile_url(url)
        is_profile = bool(parsed)
        if not parsed:  # post / reel URL: the handle has to be read from the title or snippet
            host = url.lower()
            platform = "instagram" if "instagram.com" in host else ("tiktok" if "tiktok.com" in host else "")
            handle = _handle_from_text(title + " " + snippet)
            if not platform or not handle:
                return None
            parsed = (platform, handle)
            is_profile = False
        platform, handle = parsed
        if platform not in DOMAINS:
            return None
        name = _name_from_title(title, handle) or handle
        date = N.parse_dt(r.get("date")) if r.get("date") else None
        bio = _bio_from_snippet(snippet) if is_profile else ""
        evidence = [{"kind": "profile" if is_profile else "post",
                     "label": ("Search result · profile" if is_profile else "Search result · post"),
                     "title": title, "text": short(snippet, 300), "url": url, "date": N.iso(date)}]
        followers = N.followers_from_text(snippet) if is_profile else None
        genre = detect_genre([title, snippet], spec.get("targets") or [])
        engine = "Google via Serper" if self.engine == "serper" else "Brave Search"
        return {
            "platform": platform, "handle": handle, "name": name[:120],
            "profile_url": N.profile_url_for(platform, handle), "followers": followers,
            "location": "", "genre": genre, "bio": bio[:1500],
            "last_activity_at": N.iso(date) if date and not is_profile else None, "last_release_at": None,
            "uploads_30d": None, "source": self.key, "source_label": f"Web search ({engine})", "source_url": url,
            "evidence": evidence, "linked": [],
        }


def simplify(query: str) -> str:
    """'site:instagram.com Afrobeats artist Lagos "new single"' -> 'instagram Afrobeats artist Lagos new single'."""
    q = re.sub(r"\bsite:(?:www\.)?([a-z0-9-]+)\.[a-z.]+", r"\1", query, flags=re.I).replace('"', " ")
    return re.sub(r"\s+", " ", q).strip()


def _clean(text: str) -> str:
    import html

    return html.unescape(re.sub(r"\s+", " ", text or "")).strip()


def _handle_from_text(text: str) -> str:
    m = re.search(r"\(@([A-Za-z0-9._]{2,30})\)", text) or re.search(r"@([A-Za-z0-9._]{2,30})", text)
    if m:
        return m.group(1).rstrip(".")
    m = re.match(r"^([A-Za-z0-9._]{2,30}) on (?:Instagram|TikTok)\b", text)
    return m.group(1) if m else ""


def _name_from_title(title: str, handle: str) -> str:
    t = re.split(r"\s*[•|]\s*(?:Instagram|TikTok)", title)[0]
    t = re.sub(r"\s*\(@[^)]*\).*$", "", t)
    t = re.sub(r"\s+on (?:Instagram|TikTok).*$", "", t, flags=re.I)
    t = t.strip(" -–:\"'")
    if not t or t.lower() in ("instagram", "tiktok", "login", "log in"):
        return handle
    return t[:120]


def _bio_from_snippet(snippet: str) -> str:
    s = re.sub(r"^[\d.,KkMm]+\s+Followers?,\s*[\d.,KkMm]+\s+Following,\s*[\d.,KkMm]+\s+Posts?\s*[-–]\s*", "", snippet)
    s = re.sub(r"See Instagram photos and videos from [^)]*\)\.?", "", s)
    s = re.sub(r"^.*?\(@[^)]*\) on TikTok \|\s*", "", s)
    s = re.sub(r"^[\d.,KkMm]+\s+Likes?\.\s*[\d.,KkMm]+\s+Followers?\.\s*", "", s)
    return s.strip(" .-–")
