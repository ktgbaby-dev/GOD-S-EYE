"""End-to-end tests through the real WSGI app (the same callable Vercel runs): auth, protected routes, security
headers, lead workflow, search/filters, Today's Drop, import/export, analytics, strategy, cron."""
import csv
import io
import json
import re
import unittest
from pathlib import Path

import helpers
from helpers import Client, fresh_app, qs

ROOT = Path(__file__).resolve().parent.parent


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.app = fresh_app()
        self.c = Client(self.app)

    def test_pages_and_api_are_protected(self):
        for path in ("/", "/dashboard", "/today", "/discover", "/leads", "/leads/1", "/follow-ups", "/analytics",
                     "/strategy", "/settings", "/import"):
            r = self.c.get(path)
            self.assertEqual(r.status, 302, path)
            self.assertTrue(r.headers["location"].startswith("/login"), path)
        self.assertEqual(self.c.get("/app/js/app.js").status, 401)
        self.assertEqual(self.c.get("/app/app.css").status, 401)
        for path in ("/api/dashboard", "/api/leads", "/api/meta", "/api/analytics", "/api/export.csv"):
            self.assertEqual(self.c.get(path).status, 401, path)
        self.assertEqual(self.c.post("/api/leads", {"handle": "x", "platform": "instagram"}).status, 401)
        # The login page and its own assets are public.
        self.assertEqual(self.c.get("/login").status, 200)
        self.assertEqual(self.c.get("/shared/login.js").status, 200)
        self.assertNotIn("dashboard", self.c.get("/login").text.lower().replace("/dashboard", ""))

    def test_login_logout_cycle(self):
        r = self.c.login()
        self.assertEqual(r.status, 200)
        cookie = r.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertEqual(self.c.get("/dashboard").status, 200)
        self.assertEqual(self.c.get("/app/js/app.js").status, 200)
        self.assertEqual(self.c.get("/api/session").json["user"], "OG-WAN")
        self.assertEqual(self.c.get("/login").status, 302)  # already signed in
        token = dict(self.c.cookies)
        self.assertEqual(self.c.post("/api/logout").status, 200)
        self.assertEqual(self.c.get("/api/dashboard").status, 401)
        replay = Client(self.app)
        replay.cookies = token  # the old cookie is dead server-side, not just cleared in the browser
        self.assertEqual(replay.get("/api/dashboard").status, 401)

    def test_logout_everywhere(self):
        a, b = Client(self.app), Client(self.app, ip="203.0.113.8")
        a.login()
        b.login()
        self.assertEqual(a.post("/api/logout-all").json["ended"], 2)
        self.assertEqual(b.get("/api/dashboard").status, 401)

    def test_wrong_password_and_lockout(self):
        for i in range(5):
            r = self.c.login("wrong")
            self.assertEqual(r.status, 401)
        r = self.c.login()  # even the right password is refused while locked out
        self.assertEqual(r.status, 429)
        self.assertIn("Too many attempts", r.json["error"])
        other = Client(self.app, ip="198.51.100.4")  # a different network is unaffected
        self.assertEqual(other.login().status, 200)

    def test_csrf_and_cross_origin(self):
        self.c.login()
        r = self.c.request("POST", "/api/leads", {"handle": "x", "platform": "instagram"},
                           headers={"X-Requested-With": ""})
        self.assertEqual(r.status, 403)
        r = self.c.post("/api/leads", {"handle": "x", "platform": "instagram"}, headers={"Origin": "https://evil.test"})
        self.assertEqual(r.status, 403)

    def test_security_headers(self):
        for path in ("/login", "/api/setup"):
            h = self.c.get(path).headers
            self.assertIn("frame-ancestors 'none'", h["content-security-policy"])
            self.assertEqual(h["x-frame-options"], "DENY")
            self.assertEqual(h["x-content-type-options"], "nosniff")
            self.assertEqual(h["referrer-policy"], "no-referrer")
            self.assertIn("noindex", h["x-robots-tag"])
        self.assertIn("Disallow: /", self.c.get("/robots.txt").text)

    def test_secure_cookie_mode(self):
        app = fresh_app(SECURE_COOKIES="1")
        c = Client(app)
        cookie = c.login().headers["set-cookie"]
        self.assertTrue(cookie.startswith("__Host-ge_session="))
        self.assertIn("Secure", cookie)
        self.assertIn("strict-transport-security", c.get("/api/session").headers)
        fresh_app(SECURE_COOKIES=None)

    def test_unconfigured_app_explains_itself(self):
        app = fresh_app(GODS_EYE_PASSWORD="")
        c = Client(app)
        self.assertFalse(c.get("/api/setup").json["configured"])
        self.assertEqual(c.login("").status, 503)
        self.assertEqual(c.get("/dashboard").status, 302)
        fresh_app(GODS_EYE_PASSWORD=helpers.TEST_PASSWORD)

    def test_every_referenced_asset_is_served(self):
        # Regression: on Vercel a folder named public/ was dropped from the bundle and the pages rendered blank.
        reserved = {"public", "static", "assets"}
        dirs = {p.name for p in (ROOT / "frontend").rglob("*") if p.is_dir()}
        self.assertFalse(dirs & reserved, "Vercel strips these folder names from the Python bundle")
        login_refs = re.findall(r'(?:href|src)="(/[^"]+)"', (ROOT / "frontend" / "login.html").read_text("utf-8"))
        app_refs = re.findall(r'(?:href|src)="(/(?:shared|app)/[^"]+)"', (ROOT / "frontend" / "app.html").read_text("utf-8"))
        for ref in login_refs:
            self.assertEqual(self.c.get(ref).status, 200, ref)
        self.c.login()
        for ref in app_refs:
            self.assertEqual(self.c.get(ref).status, 200, ref)
        views = re.findall(r'import\("\./views/([a-z]+\.js)"\)', (ROOT / "frontend/app/js/app.js").read_text("utf-8"))
        self.assertGreaterEqual(len(views), 10)
        for v in views + ["addlead.js"]:
            self.assertEqual(self.c.get(f"/app/js/views/{v}").status, 200, v)
        self.assertTrue(self.c.get("/api/setup").json["configured"])

    def test_missing_frontend_files_are_reported(self):
        from godseye import web

        original = web.REQUIRED_FILES
        web.REQUIRED_FILES = original + ("shared/does-not-exist.css",)
        try:
            app = fresh_app()
            problems = Client(app).get("/api/setup").json["problems"]
            self.assertTrue(any("shared/does-not-exist.css" in p for p in problems))
        finally:
            web.REQUIRED_FILES = original
            fresh_app()

    def test_no_secrets_in_frontend(self):
        bad = re.compile(r"GODS_EYE_PASSWORD\s*=|SESSION_SECRET\s*=|api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]", re.I)
        for f in (ROOT / "frontend").rglob("*"):
            if f.is_file() and f.suffix in (".js", ".html", ".css"):
                self.assertIsNone(bad.search(f.read_text(encoding="utf-8")), f)
        for js in (ROOT / "frontend").rglob("*.js"):
            self.assertNotIn("localStorage", js.read_text(encoding="utf-8"), js)


class LeadWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.c = Client(fresh_app())
        self.c.login()

    def add(self, **kw):
        body = {"name": "Amara", "handle": "@amara.music", "platform": "Instagram", "genre": "Afrobeats",
                "location": "Lagos, Nigeria", "followers": "12.4K", "notes": "", "source": "Instagram explore",
                "bio": "Independent artist. Open for collabs. New EP loading."}
        body.update(kw)
        return self.c.post("/api/leads", body)

    def test_full_flow(self):
        # Empty states first
        d = self.c.get("/api/dashboard").json
        self.assertEqual(d["stats"]["total"], 0)
        self.assertEqual(d["prospects"], [])
        self.assertTrue(self.c.get("/api/analytics").json["empty"])
        self.assertEqual(self.c.get("/api/today").json["total_today"], 0)

        r = self.add()
        self.assertEqual(r.status, 201)
        lead = r.json["lead"]
        lid = r.json["id"]
        self.assertEqual(lead["handle"], "amara.music")
        self.assertEqual(lead["platform"], "instagram")
        self.assertEqual(lead["profile_url"], "https://www.instagram.com/amara.music/")
        self.assertEqual(lead["followers"], 12400)
        self.assertEqual(lead["provenance"], "manual")
        self.assertEqual(lead["status"], "new")
        self.assertEqual(lead["freshness"], "new_today")
        codes = {i["code"] for i in lead["score_breakdown"]["items"]}
        self.assertTrue({"independent", "seeking_collab", "new_project", "genre_fit", "location_fit"} <= codes)

        # Duplicate prevention (platform + normalized handle, any case / @)
        dup = self.add(handle="AMARA.MUSIC", name="Someone else")
        self.assertEqual(dup.status, 409)
        self.assertEqual(dup.json["lead_id"], lid)
        self.assertEqual(self.add(handle="amara.music", platform="tiktok").status, 201)  # other platform is fine

        # Search: name, handle with @, genre, location, platform, status, keyword
        for q, n in (("amara", 2), ("@amara.music", 2), ("afrobeats", 2), ("lagos", 2), ("tiktok", 1),
                     ("new", 2), ("collabs", 2), ("zzz", 0)):
            self.assertEqual(self.c.get("/api/leads" + qs(q=q)).json["total"], n, q)
        # Filters
        self.assertEqual(self.c.get("/api/leads" + qs(platform="instagram", min_score=30, status="new")).json["total"], 1)
        self.assertEqual(self.c.get("/api/leads/count" + qs(followers="10k-50k")).json["total"], 2)
        self.assertEqual(self.c.get("/api/leads/count" + qs(discovered="today", activity="unknown")).json["total"], 2)
        self.assertEqual(self.c.get("/api/leads/count" + qs(min_score=101)).json["total"], 0)

        # Detail, status workflow, notes
        detail = self.c.get(f"/api/leads/{lid}").json
        self.assertEqual(detail["handles"][0]["handle"], "amara.music")
        r = self.c.post(f"/api/leads/{lid}/status", {"status": "contacted"})
        self.assertEqual(r.json["status"], "contacted")
        self.assertIsNotNone(r.json["last_contacted_at"])
        self.assertFalse(r.json["follow_up_due"])
        r = self.c.post(f"/api/leads/{lid}/status", {"status": "follow_up", "follow_up_at": "2020-01-01"})
        self.assertTrue(r.json["follow_up_due"])
        self.assertEqual(len(self.c.get("/api/follow-ups").json["due"]), 1)
        self.assertEqual(self.c.get("/api/dashboard").json["stats"]["follow_up_ready"], 1)
        r = self.c.patch(f"/api/leads/{lid}", {"notes": "DM'd about a custom beat"})
        self.assertEqual(r.json["notes"], "DM'd about a custom beat")
        self.assertEqual(self.c.get("/api/leads" + qs(q="custom beat")).json["total"], 1)
        self.assertEqual(self.c.post(f"/api/leads/{lid}/status", {"status": "bogus"}).status, 400)
        kinds = [a["kind"] for a in self.c.get(f"/api/leads/{lid}").json["activities"]]
        self.assertEqual(kinds[:3], ["note", "status", "status"])

        # Today's drop lists today's leads and drops "not a fit"
        today = self.c.get("/api/today").json
        self.assertEqual(today["total_today"], 2)
        self.c.post(f"/api/leads/{lid}/status", {"status": "not_fit"})
        today = self.c.get("/api/today").json
        self.assertEqual(today["total_today"], 1)
        self.assertEqual(today["dismissed"], 1)

        # Analytics come from the data
        a = self.c.get("/api/analytics").json
        self.assertEqual(a["totals"]["discovered"], 2)
        self.assertEqual(a["totals"]["contacted"], 1)
        self.assertEqual(sum(v["discovered"] for v in a["volume"]), 2)

        # Delete
        self.assertEqual(self.c.delete(f"/api/leads/{lid}").status, 200)
        self.assertEqual(self.c.get(f"/api/leads/{lid}").status, 404)

    def test_validation(self):
        self.assertEqual(self.c.post("/api/leads", {"name": "x"}).status, 400)
        self.assertEqual(self.add(profile_url="javascript:alert(1)").status, 400)
        self.assertEqual(self.add(handle="bad handle!").status, 400)
        self.assertEqual(self.add(followers="lots").status, 400)
        r = self.c.post("/api/leads", {"profile_url": "https://www.tiktok.com/@newwave_ng"})
        self.assertEqual(r.status, 201)
        self.assertEqual((r.json["lead"]["platform"], r.json["lead"]["handle"]), ("tiktok", "newwave_ng"))

    def test_edit_rescores_and_keeps_handles_unique(self):
        a = self.add().json["id"]
        b = self.add(handle="other.artist", bio="").json["id"]
        before = self.c.get(f"/api/leads/{b}").json["score"]
        after = self.c.patch(f"/api/leads/{b}", {"bio": "Looking for a producer for my debut EP"}).json["score"]
        self.assertGreater(after, before)
        self.assertEqual(self.c.patch(f"/api/leads/{b}", {"handle": "amara.music"}).status, 409)
        r = self.c.patch(f"/api/leads/{b}", {"handle": "renamed.artist"})
        self.assertEqual(r.json["profile_url"], "https://www.instagram.com/renamed.artist/")
        self.assertEqual(self.add(handle="other.artist").status, 201)  # old handle was released
        self.assertNotEqual(a, b)

    def test_strategy_changes_rescore(self):
        lid = self.add().json["id"]
        base = self.c.get(f"/api/leads/{lid}").json["score"]
        r = self.c.put("/api/strategy", {"weights": {"genre_fit": 0}, "target_genres": ["Afrobeats", "Drill"]})
        self.assertEqual(r.status, 200)
        self.assertGreaterEqual(r.json["rescored"], 1)
        self.assertEqual(self.c.get(f"/api/leads/{lid}").json["score"], base - 12)
        self.assertEqual(self.c.put("/api/strategy", {"daily_target": 0}).status, 400)
        self.assertEqual(self.c.get("/api/meta").json["strategy"]["target_genres"], ["Afrobeats", "Drill"])


class ImportExportTests(unittest.TestCase):
    def setUp(self):
        self.c = Client(fresh_app())
        self.c.login()

    def test_csv_preview_then_import_with_duplicates(self):
        self.c.post("/api/leads", {"handle": "existing.one", "platform": "instagram"})
        content = ("name,handle,platform,profile_url,genre,location,followers,source,notes\n"
                   "Amara,@amara.music,Instagram,,Afrobeats,Lagos,12.4K,Friend tip,Met at a show\n"
                   "Existing,existing.one,instagram,,,,,,\n"
                   "Dupe in file,AMARA.MUSIC,ig,,,,,,\n"
                   "From URL,,,https://www.tiktok.com/@fromurl,,,,,\n"
                   "Broken,,,,,,,,\n")
        prev = self.c.post("/api/import", {"format": "csv", "content": content, "dry_run": True}).json
        self.assertEqual(prev["stats"], {"rows": 5, "added": 2, "duplicate": 2, "invalid": 1})
        self.assertEqual(self.c.get("/api/leads/count").json["total"], 1)  # dry run wrote nothing
        res = self.c.post("/api/import", {"format": "csv", "content": content}).json
        self.assertEqual(res["stats"]["added"], 2)
        again = self.c.post("/api/import", {"format": "csv", "content": content}).json
        self.assertEqual(again["stats"]["added"], 0)
        self.assertEqual(again["stats"]["duplicate"], 4)
        lead = self.c.get("/api/leads" + qs(q="amara")).json["items"][0]
        self.assertEqual((lead["provenance"], lead["source"], lead["notes"]), ("import", "Friend tip", "Met at a show"))

    def test_json_and_links(self):
        r = self.c.post("/api/import", {"format": "json", "content": json.dumps(
            [{"name": "J", "handle": "j.son", "platform": "youtube", "followers": 900}])}).json
        self.assertEqual(r["stats"]["added"], 1)
        r = self.c.post("/api/import", {"format": "links", "content":
                        "https://www.instagram.com/linky/\nhttps://example.com/nope\nhttps://www.instagram.com/linky/"}).json
        self.assertEqual(r["stats"], {"rows": 3, "added": 1, "duplicate": 1, "invalid": 1})
        self.assertEqual(self.c.post("/api/import", {"format": "csv", "content": "name\nx\n"}).status, 400)
        self.assertEqual(self.c.post("/api/import", {"format": "xml", "content": "<x/>"}).status, 400)

    def test_export_is_formula_safe(self):
        self.c.post("/api/leads", {"handle": "evil.one", "platform": "instagram", "name": "=HYPERLINK(\"x\")"})
        r = self.c.get("/api/export.csv")
        self.assertIn("text/csv", r.headers["content-type"])
        rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
        self.assertEqual(rows[0][:3], ["id", "name", "handle"])
        self.assertTrue(rows[1][1].startswith("'="))
        self.assertEqual(self.c.get("/api/import/template.csv").text.strip(),
                         "name,handle,platform,profile_url,genre,location,followers,source,notes")


class CronTests(unittest.TestCase):
    def test_cron_requires_secret(self):
        app = fresh_app()
        c = Client(app)
        self.assertEqual(c.get("/api/cron/daily-drop").status, 401)
        self.assertEqual(c.get("/api/cron/daily-drop", headers={"Authorization": "Bearer nope"}).status, 401)
        r = c.get("/api/cron/daily-drop", headers={"Authorization": "Bearer cron-test-secret"})
        self.assertEqual(r.status, 200)
        self.assertTrue(r.json["ok"])
        self.assertTrue(r.json["errors"])  # the (closed) source failed; the run still completed and was logged
        c.login()
        self.assertEqual(c.get("/api/batches").json["items"][0]["kind"], "drop")


if __name__ == "__main__":
    unittest.main()
