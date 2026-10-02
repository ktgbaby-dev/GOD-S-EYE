"""Discovery engine tests against a local fake of the Audius, YouTube Data and Serper APIs (127.0.0.1).
Covers: provider parsing, verified provenance + source URLs, linked handles, cross-provider de-duplication,
"seen before" on re-runs, noise filtering + keep, query rotation/cursors, and provider failures."""
import json
import threading
import unittest
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import helpers  # noqa: F401
from helpers import Client, fresh_app
from godseye import normalize as N
from godseye.discovery.websearch import WebSearchProvider

NOW = N.utcnow()
D = lambda days: N.iso(NOW - timedelta(days=days))  # noqa: E731

AUDIUS_USERS = {
    "u1": {"id": "u1", "handle": "TemiWav", "name": "Temi Wav", "follower_count": 4200, "location": "Lagos, Nigeria",
           "bio": "Independent artist. Open for collabs.", "instagram_handle": "temiwav", "verified_with_instagram": True,
           "tiktok_handle": "temiwav_", "twitter_handle": None, "is_deactivated": False},
    "u2": {"id": "u2", "handle": "prodbykay", "name": "Prod by Kay", "follower_count": 300, "location": "Accra",
           "bio": "Music producer. Beats for sale.", "instagram_handle": None, "is_deactivated": False},
}
AUDIUS_TRACKS = [
    {"id": "t1", "title": "Ọ̀rẹ́ (Afrobeats)", "genre": "World", "tags": "afrobeats,lagos", "release_date": D(2),
     "permalink": "/TemiWav/ore", "user": AUDIUS_USERS["u1"]},
    {"id": "t2", "title": "Afro type beat - Sunset", "genre": "Hip-Hop/Rap", "tags": "afrobeats,type beat",
     "release_date": D(1), "permalink": "/prodbykay/sunset", "user": AUDIUS_USERS["u2"]},
]
YT_CHANNELS = {
    "UCaaaaaaaaaaaaaaaaaaaaaa": {"id": "UCaaaaaaaaaaaaaaaaaaaaaa", "snippet": {
        "title": "Kemi Ade", "customUrl": "@kemiade", "country": "NG",
        "description": "Afropop singer from Abuja. New EP loading. IG: @kemi.ade  tiktok.com/@kemiade"},
        "statistics": {"subscriberCount": "18400", "hiddenSubscriberCount": False},
        "contentDetails": {"relatedPlaylists": {"uploads": "UUaaaaaaaaaaaaaaaaaaaaaa"}}},
    "UCbbbbbbbbbbbbbbbbbbbbbb": {"id": "UCbbbbbbbbbbbbbbbbbbbbbb", "snippet": {
        "title": "Kemi Ade - Topic", "customUrl": "", "country": "NG", "description": ""},
        "statistics": {"subscriberCount": "10"}, "contentDetails": {}},
}


class FakeSources(BaseHTTPRequestHandler):
    calls: list[str] = []
    fail_youtube = False

    def log_message(self, *a):
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        FakeSources.calls.append(u.path + "?" + u.query)
        if u.path == "/audius/v1/tracks/search":
            offset = int(q.get("offset", ["0"])[0])
            return self._json({"data": AUDIUS_TRACKS if offset == 0 else []})
        if u.path.startswith("/audius/v1/users/") and u.path.endswith("/tracks"):
            uid = u.path.split("/")[4]
            return self._json({"data": [t for t in AUDIUS_TRACKS if t["user"]["id"] == uid]})
        if u.path.startswith("/yt/"):
            if FakeSources.fail_youtube:
                return self._json({"error": {"message": "quotaExceeded"}}, 403)
            if "key" not in q:
                return self._json({"error": {"message": "no key"}}, 400)
            if u.path == "/yt/search":
                return self._json({"nextPageToken": "PAGE2", "items": [
                    {"id": {"videoId": "v1"}, "snippet": {"channelId": "UCaaaaaaaaaaaaaaaaaaaaaa", "title": "Kemi Ade - Gbese (Official Video)",
                                                          "description": "New single out now", "publishedAt": D(4)}},
                    {"id": {"videoId": "v2"}, "snippet": {"channelId": "UCbbbbbbbbbbbbbbbbbbbbbb", "title": "Gbese",
                                                          "description": "", "publishedAt": D(4)}}]})
            if u.path == "/yt/channels":
                ids = q["id"][0].split(",")
                return self._json({"items": [YT_CHANNELS[i] for i in ids if i in YT_CHANNELS]})
            if u.path == "/yt/playlistItems":
                return self._json({"items": [
                    {"snippet": {"title": "Kemi Ade - Gbese (Official Video)"}, "contentDetails": {"videoId": "v1", "videoPublishedAt": D(4)}},
                    {"snippet": {"title": "Studio session vlog"}, "contentDetails": {"videoId": "v3", "videoPublishedAt": D(12)}},
                    {"snippet": {"title": "Snippet"}, "contentDetails": {"videoId": "v4", "videoPublishedAt": D(20)}}]})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        FakeSources.calls.append(u.path + " " + body.get("q", ""))
        if u.path == "/serper/search":
            if self.headers.get("X-API-KEY") != "serper-test":
                return self._json({"message": "Unauthorized"}, 401)
            return self._json({"organic": [
                {"title": "Kemi Ade (@kemi.ade) • Instagram photos and videos", "link": "https://www.instagram.com/kemi.ade/",
                 "snippet": "21K Followers, 500 Following, 210 Posts - See Instagram photos and videos from Kemi Ade (@kemi.ade)"},
                {"title": "Dayo Flex on Instagram: \"Producers DM, need beats for my EP\"", "link": "https://www.instagram.com/p/XYZ123/",
                 "snippet": "@dayoflex · Lagos. Producers DM, need beats for my EP. Independent artist.", "date": "2 days ago"},
                {"title": "Afrobeats news", "link": "https://www.pulse.ng/afrobeats", "snippet": "not a profile"},
            ]})
        return self._json({"error": "not found"}, 404)


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeSources)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeSources.calls = []
        FakeSources.fail_youtube = False
        WebSearchProvider.operators_blocked = False
        self.app = fresh_app(GODS_EYE_AUDIUS_BASE=self.base + "/audius", GODS_EYE_YOUTUBE_BASE=self.base + "/yt",
                             GODS_EYE_SERPER_BASE=self.base + "/serper", YOUTUBE_API_KEY="yt-test",
                             SERPER_API_KEY="serper-test")
        self.c = Client(self.app)
        self.c.login()
        self.c.put("/api/strategy", {"target_genres": ["Afrobeats"], "target_locations": ["Nigeria"],
                                     "max_queries_per_batch": 3})

    def tearDown(self):
        fresh_app(YOUTUBE_API_KEY=None, SERPER_API_KEY=None)

    def scan(self, **body):
        r = self.c.post("/api/discover", {"genres": ["Afrobeats"], "locations": ["Nigeria"], "min_score": 30, **body})
        self.assertEqual(r.status, 200, r.text)
        return r.json

    def test_providers_status(self):
        prov = {p["key"]: p for p in self.c.get("/api/meta").json["providers"]}
        self.assertTrue(all(p["configured"] for p in prov.values()))
        self.assertEqual(prov["websearch"]["engine"], "serper")
        text = json.dumps(self.c.get("/api/settings").json) + json.dumps(self.c.get("/api/meta").json)
        self.assertNotIn("yt-test", text)
        self.assertNotIn("serper-test", text)

    def test_scan_all_sources(self):
        res = self.scan(platforms=["audius", "youtube", "instagram"], signal="recent_release")
        run, batch = res["run"], res["batch"]
        self.assertEqual(run["errors"], [])
        self.assertEqual(set(run["providers"]), {"audius", "youtube", "websearch"})
        by_handle = {(i["lead"] or i["preview"])["handle"].lower(): i for i in batch["items"]}

        temi = by_handle["temiwav"]["lead"]
        self.assertEqual(by_handle["temiwav"]["outcome"], "added")
        self.assertEqual(temi["provenance"], "verified")
        self.assertEqual(temi["source_url"], "https://audius.co/TemiWav/ore")
        self.assertEqual(temi["location"], "Lagos, Nigeria")
        detail = self.c.get(f"/api/leads/{temi['id']}").json
        linked = {(h["platform"], h["handle"]): h["provenance"] for h in detail["handles"]}
        self.assertEqual(linked[("instagram", "temiwav")], "verified_link")
        self.assertEqual(linked[("tiktok", "temiwav_")], "linked")
        self.assertIn("release_14d", {i["code"] for i in detail["score_breakdown"]["items"]})

        self.assertEqual(by_handle["prodbykay"]["outcome"], "filtered")  # a producer: noise

        kemi = by_handle["kemiade"]["lead"]
        self.assertEqual((kemi["platform"], kemi["followers"], kemi["location"]), ("youtube", 18400, "Nigeria"))
        self.assertEqual(kemi["uploads_30d"], 3)
        self.assertNotIn("Kemi Ade - Topic", json.dumps(batch))  # auto-generated channels are skipped
        # Serper returned @kemi.ade on Instagram, which Kemi's YouTube bio links: same artist, not a new lead.
        self.assertNotIn("kemi.ade", by_handle)
        self.assertEqual(self.c.get("/api/leads/count?q=kemi").json["total"], 1)

        dayo = by_handle["dayoflex"]["lead"]
        self.assertEqual((dayo["platform"], dayo["source_url"]), ("instagram", "https://www.instagram.com/p/XYZ123/"))
        self.assertIn("seeking_producer", {i["code"] for i in dayo["score_breakdown"]["items"]})
        self.assertNotIn("pulse.ng", json.dumps(batch))

    def test_rerun_marks_seen_and_rotates(self):
        first = self.scan(platforms=["audius"])["run"]
        self.assertEqual(first["stats"]["added"], 1)
        second = self.scan(platforms=["audius"])["run"]
        self.assertEqual(second["stats"]["added"], 0)
        # Audius returned fewer than a page, so the cursor reset and the same tracks came back: seen, not new.
        third = self.scan(platforms=["audius", "youtube"], signal="recent_release")
        outcomes = {(i["lead"] or i["preview"])["handle"].lower(): i["outcome"] for i in third["batch"]["items"]}
        self.assertEqual(outcomes["temiwav"], "seen")
        lead = self.c.get("/api/leads?q=temiwav").json["items"][0]
        self.assertGreaterEqual(lead["seen_count"], 2)
        self.assertEqual(lead["freshness"], "new_today")  # discovered_at never moves
        self.c.post("/api/discover", {"genres": ["Afrobeats"], "platforms": ["youtube"], "signal": "recent_release"})
        yt_calls = [c for c in FakeSources.calls if c.startswith("/yt/search")]
        self.assertIn("pageToken=PAGE2", yt_calls[-1])  # resumes where the last run stopped

    def test_keep_filtered_candidate(self):
        batch = self.scan(platforms=["audius"])["batch"]
        filtered = [i for i in batch["items"] if i["outcome"] == "filtered"][0]
        r = self.c.post(f"/api/candidates/{filtered['candidate_id']}/keep")
        self.assertEqual(r.status, 200)
        lead = self.c.get(f"/api/leads/{r.json['lead_id']}").json
        self.assertEqual((lead["handle"], lead["provenance"]), ("prodbykay", "verified"))
        self.assertEqual(self.c.post(f"/api/candidates/{filtered['candidate_id']}/keep").json["lead_id"], lead["id"])

    def test_provider_failure_is_reported_not_fatal(self):
        FakeSources.fail_youtube = True
        res = self.scan(platforms=["youtube", "audius"])
        self.assertTrue(any("quotaExceeded" in e for e in res["run"]["errors"]))
        self.assertEqual(res["run"]["stats"]["added"], 1)  # Audius still delivered

    def test_daily_drop_uses_strategy(self):
        r = self.c.post("/api/drop").json
        self.assertGreater(r["run"]["stats"]["added"], 0)
        self.assertEqual(r["drop"]["total_today"], r["run"]["stats"]["added"])
        dash = self.c.get("/api/dashboard").json
        self.assertEqual(dash["stats"]["new_today"], r["run"]["stats"]["added"])
        self.assertTrue(dash["drop_ran_today"])
        cron = Client(self.app).get("/api/cron/daily-drop", headers={"Authorization": "Bearer cron-test-secret"}).json
        self.assertEqual(cron["skipped"], "A drop already ran today")

    def test_disabled_and_unconfigured_sources(self):
        self.c.put("/api/strategy", {"enabled_providers": []})
        res = self.scan(platforms=["audius"])
        self.assertEqual(res["run"]["providers"], [])
        self.assertTrue(res["run"]["notes"])
        self.assertEqual(FakeSources.calls, [])


if __name__ == "__main__":
    unittest.main()
