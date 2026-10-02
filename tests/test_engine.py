"""Unit tests: normalization, scoring, strategy validation, import parsing. No network, no database server."""
import unittest
from datetime import timedelta

import helpers  # noqa: F401  (isolated environment)
from godseye import importer, scoring
from godseye import normalize as N
from godseye import settings as S


class NormalizeTests(unittest.TestCase):
    def test_profile_urls(self):
        self.assertEqual(N.parse_profile_url("https://www.instagram.com/amara.music/"), ("instagram", "amara.music"))
        self.assertEqual(N.parse_profile_url("instagram.com/amara.music?igsh=x"), ("instagram", "amara.music"))
        self.assertIsNone(N.parse_profile_url("https://www.instagram.com/p/C0abc/"))
        self.assertEqual(N.parse_profile_url("https://www.tiktok.com/@ama_ra/video/1"), ("tiktok", "ama_ra"))
        self.assertEqual(N.parse_profile_url("https://www.youtube.com/@AmaraMusic"), ("youtube", "AmaraMusic"))
        self.assertEqual(N.parse_profile_url("https://x.com/amara"), ("x", "amara"))
        self.assertIsNone(N.parse_profile_url("https://x.com/search?q=x"))
        self.assertEqual(N.parse_profile_url("https://audius.co/Kutt4life"), ("audius", "Kutt4life"))
        self.assertIsNone(N.parse_profile_url("javascript:alert(1)"))

    def test_handles(self):
        self.assertEqual(N.norm_handle(" @@Amara.Music "), "amara.music")
        self.assertTrue(N.valid_handle("instagram", "amara.music"))
        self.assertFalse(N.valid_handle("instagram", "amara music"))
        self.assertEqual(N.profile_url_for("tiktok", "@ama"), "https://www.tiktok.com/@ama")
        self.assertEqual(N.norm_platform("IG"), "instagram")
        self.assertEqual(N.norm_platform("Twitter"), "x")

    def test_counts(self):
        self.assertEqual(N.parse_count("12.4K"), 12400)
        self.assertEqual(N.parse_count("1,234"), 1234)
        self.assertEqual(N.parse_count("1.2M followers"), 1_200_000)
        self.assertIsNone(N.parse_count("lots"))
        self.assertEqual(N.followers_from_text("12K Followers, 300 Following, 45 Posts"), 12000)
        self.assertEqual(N.fmt_count(12400), "12K")
        self.assertEqual(N.fmt_count(1500), "1.5K")

    def test_genres_and_locations(self):
        self.assertEqual(N.detect_genres("new afropop single"), ["Afropop"])
        self.assertEqual(N.genre_matches("Afrobeats, R&B", ["R&B"]), "R&B")
        self.assertIsNone(N.genre_matches("Country", ["Afrobeats"]))
        self.assertEqual(N.location_matches("Lekki, Lagos", ["Abuja", "Nigeria"]), "Nigeria")
        self.assertEqual(N.location_matches("London", ["Nigeria", "United Kingdom"]), "United Kingdom")
        self.assertIsNone(N.location_matches("Frankfurt am Main", ["Nigeria", "UK"]))
        self.assertEqual(N.region_code("Nigeria"), "NG")

    def test_dates(self):
        ref = N.parse_dt("2026-10-02T12:00:00Z")
        self.assertEqual(N.parse_loose_date("3 days ago", ref).date().isoformat(), "2026-09-29")
        self.assertEqual(N.parse_loose_date("Sep 28, 2026").date().isoformat(), "2026-09-28")
        self.assertEqual(N.parse_loose_date("28/09/2026").date().isoformat(), "2026-09-28")
        start = N.local_day_start("Africa/Lagos", ref=N.parse_dt("2026-10-02T00:30:00Z"))
        self.assertEqual(N.iso(start), "2026-10-01T23:00:00Z")


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.strategy = {**S.DEFAULTS}
        self.now = N.parse_dt("2026-10-02T12:00:00Z")

    def lead(self, **kw):
        base = {"name": "Tobi Waves", "handle": "tobiwaves", "platform": "instagram", "bio": "", "genre": "",
                "location": "", "followers": None, "evidence": [], "discovered_at": N.iso(self.now)}
        base.update(kw)
        return base

    def codes(self, res):
        return {i["code"]: i for i in res["breakdown"]["items"]}

    def test_every_point_is_explained(self):
        res = scoring.score_lead(self.lead(
            bio="Independent artist from Lagos. New EP loading. Producers DM — send beats", followers=12400,
            evidence=[{"label": "Post", "title": "New single out now on all platforms", "url": "https://x.test/p",
                       "date": N.iso(self.now - timedelta(days=3))}]), self.strategy, self.now)
        items = self.codes(res)
        for code in ("seeking_producer", "release_14d", "active_7d", "independent", "audience_emerging",
                     "new_project", "location_fit", "fresh_24h"):
            self.assertIn(code, items)
        self.assertEqual(res["score"], min(100, sum(i["points"] for i in res["breakdown"]["items"])))
        self.assertIn("send beats", items["seeking_producer"]["evidence"])
        self.assertEqual(items["release_14d"]["url"], "https://x.test/p")
        self.assertTrue(res["reason"].startswith("Looking for a producer"))

    def test_unknown_earns_nothing(self):
        res = scoring.score_lead(self.lead(discovered_at=N.iso(self.now - timedelta(days=30))), self.strategy, self.now)
        self.assertEqual(res["score"], 0)
        self.assertEqual(set(res["breakdown"]["unknown"]), {"Last activity date", "Audience size", "Genre", "Location"})

    def test_noise_penalties(self):
        prod = scoring.score_lead(self.lead(name="KD Beats", handle="kdbeats", genre="Afrobeats"), self.strategy, self.now)
        self.assertIn("is_producer", self.codes(prod))
        afro = scoring.score_lead(self.lead(name="Afrobeats Queen", handle="afrobeatsqueen"), self.strategy, self.now)
        self.assertNotIn("is_producer", self.codes(afro))  # "afrobeats" is not "beats"
        page = scoring.score_lead(self.lead(name="Naija Hits TV", handle="naijahitstv"), self.strategy, self.now)
        self.assertIn("aggregator", self.codes(page))
        spam = scoring.score_lead(self.lead(evidence=[{"title": "Afrobeats - fcc0449e"}, {"title": "Afrobeats - 5f556857"}]),
                                  self.strategy, self.now)
        self.assertIn("auto_generated", self.codes(spam))
        old = scoring.score_lead(self.lead(last_activity_at=N.iso(self.now - timedelta(days=200))), self.strategy, self.now)
        self.assertIn("inactive", self.codes(old))
        self.assertEqual(old["score"], 0)  # floored, never negative

    def test_genre_place_is_not_location(self):
        res = scoring.score_lead(self.lead(bio="UK drill artist from Atlanta"), {**self.strategy, "target_locations": ["UK"]},
                                 self.now)
        self.assertNotIn("location_fit", self.codes(res))

    def test_weights_are_configurable(self):
        st = {**self.strategy, "weights": {"seeking_producer": 40, "genre_fit": 0}}
        res = scoring.score_lead(self.lead(bio="need a producer", genre="Afrobeats"), st, self.now)
        items = self.codes(res)
        self.assertEqual(items["seeking_producer"]["points"], 40)
        self.assertNotIn("genre_fit", items)

    def test_score_capped(self):
        res = scoring.score_lead(self.lead(
            bio="Independent. Looking for a producer. Open for collabs. New EP loading. In the studio. Pre-save now",
            followers=5000, genre="Afrobeats", location="Lagos", uploads_30d=5,
            last_release_at=N.iso(self.now - timedelta(days=2))), self.strategy, self.now)
        self.assertEqual(res["score"], 100)
        self.assertGreater(res["breakdown"]["raw"], 100)


class SettingsTests(unittest.TestCase):
    def test_validation(self):
        clean = S.validate({"target_genres": ["Afrobeats", "afrobeats", "  Amapiano "], "daily_target": "25",
                            "target_platforms": ["IG", "tiktok", "other"], "weights": {"genre_fit": 12, "location_fit": 20}})
        self.assertEqual(clean["target_genres"], ["Afrobeats", "Amapiano"])
        self.assertEqual(clean["daily_target"], 25)
        self.assertEqual(clean["target_platforms"], ["instagram", "tiktok"])
        self.assertEqual(clean["weights"], {"location_fit": 20})  # defaults aren't stored as overrides
        with self.assertRaises(ValueError):
            S.validate({"daily_target": 0})
        with self.assertRaises(ValueError):
            S.validate({"weights": {"made_up": 3}})
        with self.assertRaises(ValueError):
            S.validate({"password": "x"})


class ImportParsingTests(unittest.TestCase):
    def test_csv_aliases_and_delimiters(self):
        rows = importer.parse_csv("﻿Artist Name;Username;Platform;Followers\nAmara;@amara.music;IG;12.4K\n")
        self.assertEqual(rows, [{"name": "Amara", "handle": "@amara.music", "platform": "IG", "followers": "12.4K"}])

    def test_csv_needs_identity_column(self):
        with self.assertRaises(importer.ImportError_):
            importer.parse_csv("name,genre\nAmara,Afrobeats\n")

    def test_json(self):
        rows = importer.parse_json('{"leads": [{"name": "A", "handle": "a1", "platform": "tiktok", "extra": {"x": 1}}]}')
        self.assertEqual(rows, [{"name": "A", "handle": "a1", "platform": "tiktok"}])
        with self.assertRaises(importer.ImportError_):
            importer.parse_json("{nope")

    def test_template_is_header_only(self):
        self.assertEqual(importer.template_csv().strip().count("\n"), 0)


if __name__ == "__main__":
    unittest.main()
