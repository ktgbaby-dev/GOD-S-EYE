# GOD'S EYE

**A private client discovery system for OG-WAN.**

GOD'S EYE answers one question every morning: *who should OG-WAN know about today?* It pulls fresh, real prospects
(artists who may need production, beats, mixing or artist development) from public sources, scores each one with a
transparent breakdown, and gives OG-WAN their handles, the evidence, and a workflow from first look to client:

```
DISCOVER → FILTER → PRIORITIZE → REVIEW → SAVE → CONTACT
```

It never invents people. Every discovered lead keeps the public source URL it came from. With no API keys configured it
still works: Audius needs no key, and manual add, CSV/JSON import and pasted profile links feed the same pipeline.

---

## Quick start (this machine)

```bash
cd "C:/Users/acer/Documents/CLAUDE CODE/gods-eye"
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python app.py --init      # writes .env with a generated password + secrets
.venv/Scripts/python app.py             # http://127.0.0.1:5620
```

The password is the `GODS_EYE_PASSWORD` line in `.env` (git-ignored). `--init` never prints it.

Preview entries in the workspace `.claude/launch.json`:

| Entry | Port | Database |
|---|---|---|
| `gods-eye` | 5620 | `data/gods_eye.db`: the real local database, starts empty |
| `gods-eye-demo` | 5621 | `data/demo.db`: fictional demo data (see below) |

Tests (40 tests; no network, no keys):

```bash
.venv/Scripts/python -m unittest discover -s tests -v
```

---

## Environment variables

Nothing here is ever sent to the browser. `/api/settings` only says whether a key is set.

| Variable | Required | Purpose |
|---|---|---|
| `GODS_EYE_PASSWORD` | **yes** | OG-WAN's password (10+ characters). |
| `SESSION_SECRET` | **yes** | 32+ random characters. Keys the hashes of session tokens and IPs. |
| `DATABASE_URL` | **on Vercel** | Postgres connection string (Neon via Vercel Storage sets it automatically; `POSTGRES_URL` or a prefixed `*_DATABASE_URL` also work). Locally the app uses SQLite. |
| `CRON_SECRET` | recommended | Lets Vercel Cron trigger the daily drop (`/api/cron/daily-drop`). Without it the endpoint refuses. |
| `YOUTUBE_API_KEY` | optional | YouTube Data API v3 discovery. |
| `SERPER_API_KEY` | optional | Instagram + TikTok discovery via Google results (serper.dev). |
| `BRAVE_SEARCH_API_KEY` | optional | Alternative to Serper (used only when Serper isn't set). |
| `AUDIUS_APP_NAME` | no | `app_name` sent to Audius (default `GodsEye`). |
| `SECURE_COOKIES` | no | Defaults to `1` on Vercel. Set `1` on any other HTTPS host. |
| `GODS_EYE_DB_PATH` | no | SQLite file path (default `data/gods_eye.db`). |

Generate a secret: `python -c "import secrets; print(secrets.token_hex(32))"`

---

## Deploying to Vercel

The repo deploys as a Python function: `app.py` exports `app` (a WSGI callable), declared in `pyproject.toml`
(`[tool.vercel] entrypoint = "app:app"`). `vercel.json` sets a 60-second limit and the daily cron.

1. Push the repo to GitHub and import it in Vercel (framework preset: **Other**, no build command).
2. **Storage → Create Database → Neon (Postgres)** and connect it to the project for all environments.
   This adds `DATABASE_URL`. Vercel's disk is temporary, so the app refuses to run there without Postgres and says so
   on the login screen.
3. **Settings → Environment Variables**, for Production (and Preview if you use it):
   - `GODS_EYE_PASSWORD`: OG-WAN's password
   - `SESSION_SECRET`: 64 hex characters from the command above
   - `CRON_SECRET`: another random string
   - optional: `YOUTUBE_API_KEY`, `SERPER_API_KEY` or `BRAVE_SEARCH_API_KEY`
4. Redeploy (environment changes only apply to new deployments). Tables are created on the first request.
5. The cron runs `0 5 * * *` (05:00 UTC = 06:00 in Lagos). On the Hobby plan Vercel allows daily crons only, and may
   run them any time within that hour. Change the time in `vercel.json`.

Changing the password: edit `GODS_EYE_PASSWORD` in Vercel, redeploy, then **Settings → Sign out everywhere**.

---

## Discovery sources

Providers live in `godseye/discovery/`. Each subclasses `DiscoveryProvider` (`specs(plan)` → query specs,
`run(spec, cursor)` → candidates) and is registered in `discovery/__init__.py`. Adding a source doesn't touch the UI.

| Source | Key | What it returns | Tested |
|---|---|---|---|
| **Audius** (open music platform API) | none | Recent tracks by genre → the artists, followers, location, bio, upload history, and the Instagram / TikTok / X handles they list (Audius marks the ones the artist verified). | Live, against the real API, and with a local fake |
| **YouTube Data API v3** | `YOUTUBE_API_KEY` | Recent music videos for genre + signal + location → channel @handle, subscribers, country, recent uploads, handles in the channel description. ~115 quota units per query, about 80 queries/day on the free quota. | Local fake only; no key available here |
| **Web search** (Serper or Brave) | `SERPER_API_KEY` / `BRAVE_SEARCH_API_KEY` | `site:instagram.com` / `site:tiktok.com` searches → profile and post results, with handle, name, follower count and caption text from the indexed snippet. Free Serper plans reject `site:` and quotes: the app retries in plain words and keeps only profile links. | Local fake only |
| **Manual import** | none | CSV, JSON, pasted profile links, + Add lead. | Yes |

Platform rules: GOD'S EYE never logs in anywhere, never loads Instagram or TikTok pages itself, and stores only public,
professional information. Instagram's official API can't search other accounts and TikTok's Research API is
academic-only, so Instagram and TikTok prospects come from search-engine results. The **Manual recon** panel on
Discover builds hashtag and search links for OG-WAN to open in his own browser.

**Freshness and no repeats.** Every query is logged with a resume cursor (page token / offset), and each batch runs the
least-recently-used queries first. A lead is unique on `platform + normalized handle`, including handles linked from
other profiles, so an artist found on YouTube and again on Instagram is one lead. Re-sightings update
`last_seen_at` and `seen_count` but never `discovered_at`, so they show as SEEN BEFORE, not new. Leads with no activity
(or not seen) for `stale_days` show as STALE and are pushed out of the daily list.

**Provenance labels.** `SOURCE VERIFIED` = returned by a real source, with its URL kept on the lead. `MANUAL ENTRY` /
`IMPORTED` = added by OG-WAN. Handles an artist lists on their own profile are shown as "listed on their profile · not
verified" unless the platform verified the link.

## Scoring

`godseye/scoring.py`. The score is the sum of the signals that fired, clamped to 0–100. Each signal records the evidence
that triggered it (quote, date, link). Unknown data earns nothing and is listed as unknown. Points are editable on the
Strategy page, and saving rescores every lead.

| Group | Signals (default points) |
|---|---|
| Activity | active in 7 days +15 · active in 30 days +8 · 3+ uploads in 30 days +8 |
| Release | released music in 14 days +18 · in 60 days +10 · promoting upcoming music +10 |
| Artist status | independent / unsigned +10 · audience 1K–50K +10 · 50K–250K +6 · under 1K +3 · 250K+ +2 |
| Production need | looking for a producer / beats +22 · open to collabs +12 · new project +8 · studio talk +5 |
| Fit | genre matches targets +12 · in a target location +12 (a country matches its cities) |
| Freshness | discovered in 24 h +5 · this week +2 |
| Noise | producer / beat seller −30 · page or channel, not an artist −30 · auto-generated uploads −30 · label mention −8 · quiet 90+ days −12 |

Candidates below **Keep from discovery** (default 40) are counted as NOISE FILTERED and can still be kept from the
Discover results. Leads at or above the **threshold** (default 70) are HIGH PRIORITY.

## Security

- Password only in `GODS_EYE_PASSWORD`; compared in constant time; never in frontend code or `localStorage`.
- Sessions: random token in an `HttpOnly`, `SameSite=Lax` cookie (`__Host-` prefixed and `Secure` on HTTPS). The
  database stores only an HMAC of the token, so sign-out really ends the session. 30-day sliding expiry.
- Every page except `/login`, every `/app/*` asset and every API route except login require a session (server-side;
  unauthenticated page requests redirect to `/login`).
- Brute-force protection: 5 wrong passwords in 15 minutes locks that network out; recorded in the database, so it holds
  across serverless instances.
- Mutations need the `X-Requested-With: GodsEye` header and a same-origin `Origin` (CSRF).
- Strict CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `noindex` everywhere, and `robots.txt` disallows all.
- CSV export neutralises spreadsheet formulas in public text.

## Demo data

`tools/seed_demo.py` fills **a separate file**, `data/demo.db`, with 36 clearly fictional leads (names end in
"(demo)", handles start with `demo.`, links go to example.com, every row flagged `is_demo`). It refuses to write to the
main database. The UI shows a DEMO DATA banner whenever demo rows exist, and **Settings → Data → Remove demo data**
deletes them. Production starts empty and says so.

## Not yet verified live

- **Postgres** (the Vercel database path) has not run against a real server: none can be installed on this machine.
  The SQL is portable by design and every statement the tests execute parses under a Postgres grammar check. The first
  real run will be the Vercel deploy; if the login screen shows a database error, check the function log.
- **YouTube, Serper and Brave** are built and tested against local fakes of their APIs, not with real keys.

## Project layout

```
app.py                 WSGI entry (Vercel) + local server, --init, built-in daily scheduler
godseye/
  config.py db.py schema.sql   environment, SQLite/Postgres adapter, portable schema + indexes
  web.py api.py auth.py        routing, auth gate, security headers, JSON API, sessions + throttling
  leads.py scoring.py          lead repository/search/workflow, transparent scoring engine
  drop.py analytics.py         Today's Drop, dashboard, follow-ups, analytics
  importer.py settings.py      CSV/JSON/links import, strategy defaults + validation
  normalize.py                 handles, profile URLs, counts, genres, locations, time
  discovery/                   base.py (provider contract), audius.py, youtube.py, websearch.py, engine
frontend/
  login.html app.html          login gate (public) and app shell (served only with a session)
  shared/                      shared tokens, login assets, favicon (not "public/": Vercel strips that folder name)
  app/                         app.css, js/app.js (router), js/ui.js, js/views/*
tests/                         test_engine.py, test_api.py, test_discovery.py (local fake sources)
tools/seed_demo.py             development demo data (separate database)
```

## Stack note

The brief preferred Next.js + TypeScript + Tailwind. Node.js isn't installed on this machine and the brief required
building, running and testing the real product here, so GOD'S EYE uses the same proven stack as Kard Radar: Python 3.12+
(standard-library WSGI, `psycopg` for Postgres) and a build-free vanilla-JS frontend. It deploys to Vercel as a Python
function. The backend is a clean JSON API, so the frontend could move to Next.js later without touching discovery,
scoring or the data model.
