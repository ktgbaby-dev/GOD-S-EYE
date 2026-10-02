"""YouTube Data API v3 (official; needs YOUTUBE_API_KEY). https://developers.google.com/youtube/v3

Searches recent music videos for genre + signal + location, then reads each uploading channel's public stats,
@handle, country and recent uploads. Quota: a search costs 100 units, channel/upload lookups 1 unit each; the free
daily quota is 10,000 units (roughly 80 queries)."""
import re
import time
from datetime import timedelta

from .. import normalize as N
from ..scoring import RELEASE
from .base import (LOOKING_FOR, DiscoveryProvider, ProviderError, detect_genre, http_json, linked_handles,
                   plan_phrases, short)

ENRICH_MAX = 15
RELEASE_WORDS = RELEASE + ["official", "audio", "lyrics", "visualiser", "visualizer", "performance video"]


class YouTubeProvider(DiscoveryProvider):
    key = "youtube"
    label = "YouTube"
    platforms = ("youtube",)
    env_vars = ("YOUTUBE_API_KEY",)
    description = "Official YouTube Data API. Recent music videos by genre and signal, channel stats and uploads."

    def configured(self) -> bool:
        return bool(self.cfg.youtube_key)

    def _get(self, path: str, params: dict) -> dict:
        base = self.cfg.provider_base_urls["youtube"].rstrip("/")
        data = http_json(f"{base}/{path}", params={**params, "key": self.cfg.youtube_key})
        if not isinstance(data, dict):
            raise ProviderError("Unexpected YouTube response")
        return data

    def specs(self, plan: dict) -> list[dict]:
        role = LOOKING_FOR.get(plan.get("looking_for") or "artists", "artist")
        out = []
        locations = plan.get("locations") or [""]
        for genre in plan.get("genres") or []:
            for loc in locations:
                for sig, phrase in plan_phrases(plan):
                    q = " ".join(x for x in (genre, role if sig != "recent_release" else "", phrase, loc) if x)
                    out.append({"key": f"{genre}|{loc}|{phrase}|{role}".lower(), "label": f"YouTube · {q}", "q": q,
                                "region": N.region_code(loc), "signal": sig})
        return out

    def run(self, spec: dict, cursor: str, deadline: float) -> tuple[list[dict], str]:
        days = 21 if spec.get("signal") == "recent_release" else 45
        params = {"part": "snippet", "type": "video", "videoCategoryId": "10", "q": spec["q"], "maxResults": 25,
                  "order": "relevance", "publishedAfter": N.iso(N.utcnow() - timedelta(days=days)),
                  "relevanceLanguage": "en", "safeSearch": "none", "pageToken": cursor or None}
        if spec.get("region"):
            params["regionCode"] = spec["region"]
        data = self._get("search", params)
        videos: dict[str, list[dict]] = {}
        for item in data.get("items") or []:
            sn = item.get("snippet") or {}
            cid = sn.get("channelId")
            vid = (item.get("id") or {}).get("videoId")
            if cid and vid:
                videos.setdefault(cid, []).append({"id": vid, **sn})
        if not videos:
            return [], data.get("nextPageToken") or ""
        channels = self._get("channels", {"part": "snippet,statistics,contentDetails",
                                          "id": ",".join(list(videos)[:50]), "maxResults": 50})
        out = []
        for i, ch in enumerate(channels.get("items") or []):
            sn = ch.get("snippet") or {}
            if (sn.get("title") or "").endswith(" - Topic"):
                continue  # auto-generated artist channels: no person behind the handle
            uploads = None
            recent = []
            playlist = ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
            if playlist and i < ENRICH_MAX and time.monotonic() < deadline - 3:
                try:
                    pl = self._get("playlistItems", {"part": "snippet,contentDetails", "playlistId": playlist,
                                                     "maxResults": 10})
                    recent = pl.get("items") or []
                    now = N.utcnow()
                    uploads = sum(1 for it in recent if (N.days_since(
                        (it.get("contentDetails") or {}).get("videoPublishedAt"), now) or 999) <= 30)
                except ProviderError:
                    pass
            out.append(self._candidate(ch, videos.get(ch.get("id"), []), recent, uploads, spec))
        return out, data.get("nextPageToken") or ""

    def _candidate(self, ch: dict, found: list[dict], recent: list[dict], uploads, spec: dict) -> dict:
        sn = ch.get("snippet") or {}
        stats = ch.get("statistics") or {}
        cid = ch["id"]
        custom = N.clean_handle(sn.get("customUrl") or "")
        handle = custom if custom and N.valid_handle("youtube", custom) else cid
        profile = f"https://www.youtube.com/@{handle}" if handle != cid else f"https://www.youtube.com/channel/{cid}"
        evidence, release_at = [], None
        for v in found:
            title = _unescape(v.get("title", ""))
            evidence.append({"kind": "video", "label": "YouTube video", "title": title,
                             "text": short(_unescape(v.get("description", "")), 220),
                             "url": f"https://www.youtube.com/watch?v={v['id']}", "date": N.iso(N.parse_dt(v.get("publishedAt")))})
        for it in recent:
            s2 = it.get("snippet") or {}
            vid = (it.get("contentDetails") or {}).get("videoId")
            date = (it.get("contentDetails") or {}).get("videoPublishedAt") or s2.get("publishedAt")
            url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
            if url and any(e["url"] == url for e in evidence):
                continue
            evidence.append({"kind": "upload", "label": "YouTube upload", "title": _unescape(s2.get("title", "")),
                             "text": "", "url": url, "date": N.iso(N.parse_dt(date))})
        now = N.utcnow()
        for e in evidence:
            d = N.parse_dt(e["date"])
            t = e["title"].lower()
            if d and d <= now and any(w in t for w in RELEASE_WORDS) and "type beat" not in t:
                release_at = d if release_at is None or d > release_at else release_at
        dates = [N.parse_dt(e["date"]) for e in evidence if N.parse_dt(e["date"])]
        activity = max(dates) if dates else None
        followers = None if stats.get("hiddenSubscriberCount") else N.parse_count(stats.get("subscriberCount"))
        desc = sn.get("description") or ""
        genre = detect_genre([desc, *[e["title"] + " " + e["text"] for e in evidence]], spec.get("targets") or [])
        evidence.sort(key=lambda e: e.get("date") or "", reverse=True)
        return {
            "platform": "youtube", "handle": handle, "name": _unescape(sn.get("title") or handle).strip(),
            "profile_url": profile, "followers": followers,
            "location": N.COUNTRY_NAMES.get((sn.get("country") or "").upper(), ""), "genre": genre,
            "bio": desc[:1500], "last_activity_at": N.iso(activity), "last_release_at": N.iso(release_at),
            "uploads_30d": uploads, "source": self.key, "source_label": "YouTube Data API",
            "source_url": evidence[0]["url"] if evidence else profile, "evidence": evidence[:10],
            "linked": linked_handles(desc, "YouTube channel description"),
        }


def _unescape(text: str) -> str:
    import html

    return html.unescape(re.sub(r"\s+", " ", text or "")).strip()
