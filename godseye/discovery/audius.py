"""Audius — a public music platform with an open API (no key). https://docs.audius.org/

Searches recent tracks for each target genre and returns the uploading artists with their public stats, recent
releases and the Instagram / TikTok / X handles they list on their Audius profile (Audius marks the ones the artist
verified by signing in to that platform)."""
import time

from .. import normalize as N
from .base import DiscoveryProvider, ProviderError, detect_genre, http_json, short

PAGE = 50
ENRICH_MAX = 15  # per query: extra call per artist for upload history


class AudiusProvider(DiscoveryProvider):
    key = "audius"
    label = "Audius"
    platforms = ("audius",)
    env_vars = ()
    description = "Open music-platform API. Recent tracks by genre, artist stats and self-listed social handles."

    def _get(self, path: str, params: dict | None = None) -> dict:
        base = self.cfg.provider_base_urls["audius"].rstrip("/")
        data = http_json(f"{base}/v1{path}", params={**(params or {}), "app_name": self.cfg.audius_app_name})
        if not isinstance(data, dict):
            raise ProviderError("Unexpected Audius response")
        return data

    def specs(self, plan: dict) -> list[dict]:
        out = []
        for genre in plan.get("genres") or []:
            out.append({"key": f"tracks:{genre.lower()}", "label": f"Audius · recent {genre} tracks", "genre": genre})
        return out

    def run(self, spec: dict, cursor: str, deadline: float) -> tuple[list[dict], str]:
        offset = int(cursor or 0)
        data = self._get("/tracks/search", {"query": spec["genre"], "sort_method": "recent", "limit": PAGE,
                                            "offset": offset})
        tracks = [t for t in data.get("data") or [] if isinstance(t, dict) and t.get("user")]
        by_user: dict[str, dict] = {}
        for t in tracks:
            u = t["user"]
            if u.get("is_deactivated") or not u.get("handle"):
                continue
            entry = by_user.setdefault(u["id"], {"user": u, "tracks": []})
            entry["tracks"].append(t)
        now = N.utcnow()
        candidates = []
        for i, (uid, entry) in enumerate(by_user.items()):
            uploads = None
            history = entry["tracks"]
            if i < ENRICH_MAX and time.monotonic() < deadline - 3:
                try:
                    hist = self._get(f"/users/{uid}/tracks", {"sort": "date", "limit": 10})
                    history = [t for t in hist.get("data") or [] if isinstance(t, dict)] or history
                    uploads = sum(1 for t in history if (N.days_since(_track_date(t), now) or 999) <= 30)
                except ProviderError:
                    pass
            candidates.append(self._candidate(entry["user"], entry["tracks"], history, uploads, spec))
        next_cursor = str(offset + PAGE) if len(data.get("data") or []) >= PAGE and offset < 400 else ""
        return candidates, next_cursor

    def _candidate(self, u: dict, found: list[dict], history: list[dict], uploads, spec) -> dict:
        now = N.utcnow()
        handle = u["handle"]
        unique = {t.get("id") or t.get("permalink") or t.get("title"): t for t in [*found, *history]}
        dated = sorted(((N.parse_dt(_track_date(t)), t) for t in unique.values() if N.parse_dt(_track_date(t))),
                       key=lambda x: x[0], reverse=True)
        released = [d for d, _t in dated if d <= now]
        evidence = []
        for d, t in dated[:6]:
            evidence.append({"kind": "track", "label": "Audius track", "title": t.get("title", ""),
                             "text": short(" · ".join(x for x in (t.get("genre"), t.get("tags"), t.get("mood"),
                                                                 t.get("description")) if x), 220),
                             "url": "https://audius.co" + t["permalink"] if t.get("permalink") else "",
                             "date": N.iso(d)})
        texts = [f"{t.get('title', '')} {t.get('tags') or ''} {t.get('description') or ''}" for _d, t in dated]
        genre = detect_genre([u.get("bio") or "", *texts], spec.get("targets") or [spec["genre"]],
                             next((t.get("genre") for _d, t in dated if t.get("genre")), ""))
        linked = []
        for field, platform, verified in (("instagram_handle", "instagram", "verified_with_instagram"),
                                          ("tiktok_handle", "tiktok", "verified_with_tiktok"),
                                          ("twitter_handle", "x", "verified_with_twitter")):
            h = N.clean_handle(u.get(field) or "")
            if h and N.valid_handle(platform, h):
                linked.append({"platform": platform, "handle": h, "url": N.profile_url_for(platform, h),
                               "provenance": "verified_link" if u.get(verified) else "linked",
                               "source": "Audius profile"})
        profile = f"https://audius.co/{handle}"
        return {
            "platform": "audius", "handle": handle, "name": (u.get("name") or handle).strip(),
            "profile_url": profile, "followers": u.get("follower_count"),
            "location": (u.get("location") or "").strip()[:120], "genre": genre, "bio": (u.get("bio") or "")[:1500],
            "last_activity_at": N.iso(released[0]) if released else None,
            "last_release_at": N.iso(released[0]) if released else None,
            "uploads_30d": uploads, "source": self.key, "source_label": "Audius API",
            "source_url": evidence[0]["url"] if evidence and evidence[0]["url"] else profile,
            "evidence": evidence, "linked": linked,
        }


def _track_date(t: dict) -> str:
    return t.get("release_date") or t.get("created_at") or ""
