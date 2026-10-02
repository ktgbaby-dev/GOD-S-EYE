"""WSGI application: routing, auth gate, CSRF checks, security headers, protected static files.

The same `app` callable runs locally (`python app.py`) and on Vercel (`app.py` exports it), so what is tested here
is what is deployed. Nothing under /app/ or /api/ (except login) is served without a valid session."""
import json
import mimetypes
import re
import sys
import threading
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, urlparse

from . import auth
from . import settings as S
from .config import ROOT, Config, get_config
from .db import Database

FRONTEND = ROOT / "frontend"
MAX_BODY = 6 * 1024 * 1024
APP_PAGES = re.compile(r"^/(dashboard|today|discover|leads|leads/\d+|follow-ups|analytics|strategy|settings|import)/?$")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
BASE_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", CSP),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()"),
    ("X-Robots-Tag", "noindex, nofollow, noarchive"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
]


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class Response:
    def __init__(self, status=200, body=None, content_type="application/json", headers=None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = list(headers or [])


class Request:
    def __init__(self, environ, cfg: Config, db: Database | None):
        self.environ = environ
        self.cfg = cfg
        self.db = db
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        raw_path = environ.get("PATH_INFO", "/") or "/"
        try:  # WSGI hands over the path as latin-1; restore UTF-8
            raw_path = raw_path.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        self.path = raw_path
        self.query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False)
        self.params: dict = {}
        self.json: dict = {}
        self.conn = None
        self.session = None
        self._strategy = None
        cookie = SimpleCookie()
        try:
            cookie.load(environ.get("HTTP_COOKIE", ""))
        except Exception:
            pass
        morsel = cookie.get(cookie_name(cfg))
        self.token = morsel.value if morsel else None

    def header(self, name: str, default: str = "") -> str:
        key = name.upper().replace("-", "_")
        if key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            return self.environ.get(key, default)
        return self.environ.get("HTTP_" + key, default)

    @property
    def client_ip(self) -> str:
        if self.cfg.trust_proxy:  # Vercel's edge sets these; elsewhere they could be spoofed
            fwd = self.header("X-Real-IP") or self.header("X-Forwarded-For").split(",")[0].strip()
            if fwd:
                return fwd
        return self.environ.get("REMOTE_ADDR", "")

    def arg(self, name: str, default=None):
        v = self.query.get(name)
        return v[0] if v else default

    def args(self) -> dict:
        return {k: v[0] for k, v in self.query.items()}

    @property
    def strategy(self) -> dict:
        if self._strategy is None:
            self._strategy = S.load(self.conn)
        return self._strategy

    def reset_strategy(self):
        self._strategy = None


def cookie_name(cfg: Config) -> str:
    # __Host- cookies must be Secure, host-only and Path=/ — browsers enforce it.
    return "__Host-" + auth.COOKIE if cfg.secure_cookies else auth.COOKIE


ROUTES: list[tuple[str, re.Pattern, callable, str]] = []


def route(method: str, pattern: str, access: str = "auth"):
    """access: 'auth' (session required), 'public', or 'cron' (CRON_SECRET bearer token)."""
    rx = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn, access))
        return fn
    return deco


# ------------------------------------------------------------------------------------------------ app state

_lock = threading.Lock()
_state: dict = {}


def setup(cfg: Config | None = None, db: Database | None = None, reset: bool = False) -> dict:
    with _lock:
        if _state and not reset:
            return _state
        _state.clear()
        cfg = cfg or get_config()
        problems = cfg.problems()
        if not problems and db is None:
            try:
                db = Database(cfg)
                db.connect().close()  # creates tables on first run
            except Exception as e:  # report the class only: the URL contains a password
                traceback.print_exc()
                db = None
                problems.append(f"Could not open the database ({type(e).__name__}). Check DATABASE_URL.")
        for p in problems:
            print(f"[gods-eye] {p}", file=sys.stderr)
        _state.update(cfg=cfg, db=db if not problems else None, problems=problems)
        return _state


# ------------------------------------------------------------------------------------------------ responses

def _finish(resp: Response, cfg: Config, head: bool) -> tuple[str, list, bytes]:
    body = resp.body
    if resp.content_type == "application/json":
        body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        ctype = "application/json; charset=utf-8"
    else:
        ctype = resp.content_type
        if isinstance(body, str):
            body = body.encode("utf-8")
    body = body or b""
    headers = [("Content-Type", ctype), ("Content-Length", str(len(body)))]
    if not any(k.lower() == "cache-control" for k, _ in resp.headers):
        headers.append(("Cache-Control", "no-store"))
    headers += resp.headers + BASE_HEADERS
    if cfg.secure_cookies:
        headers.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
    return f"{resp.status} {HTTPStatus(resp.status).phrase}", headers, (b"" if head else body)


def redirect(location: str, extra_headers=None) -> Response:
    return Response(302, b"", "text/plain", [("Location", location), *(extra_headers or [])])


def _file(base, rel: str, cache: str) -> Response | None:
    target = (base / rel).resolve()
    if not str(target).startswith(str(base.resolve())) or not target.is_file():
        return None
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if target.suffix == ".js":
        ctype = "text/javascript"
    elif target.suffix == ".webmanifest":
        ctype = "application/manifest+json"
    if ctype.startswith("text/") or ctype in ("image/svg+xml", "application/manifest+json"):
        ctype += "; charset=utf-8"
    return Response(200, target.read_bytes(), ctype, [("Cache-Control", cache)])


def _page(name: str) -> Response:
    return Response(200, (FRONTEND / name).read_bytes(), "text/html; charset=utf-8", [("Cache-Control", "no-store")])


# ------------------------------------------------------------------------------------------------ dispatch

def handle(req: Request, problems: list[str]) -> Response:
    path = req.path
    if path.startswith("/api/"):
        return _api(req, problems)
    if req.method not in ("GET", "HEAD"):
        return Response(405, {"error": "Method not allowed"})
    if path == "/robots.txt":
        return Response(200, "User-agent: *\nDisallow: /\n", "text/plain; charset=utf-8")
    if path == "/favicon.ico":
        return redirect("/public/favicon.svg")
    if path.startswith("/public/"):
        return _file(FRONTEND / "public", path[len("/public/"):], "public, max-age=3600") or _not_found()
    if path == "/login":
        if not problems and _authed(req):
            return redirect(_safe_next(req.arg("next")))
        return _page("login.html")
    if path == "/" or APP_PAGES.match(path) or path.startswith("/app/"):
        if problems or not _authed(req):
            if path.startswith("/app/"):
                return Response(401, b"Sign in required", "text/plain; charset=utf-8")
            nxt = path if path != "/" else "/dashboard"
            return redirect("/login" + ("?next=" + quote(nxt) if nxt != "/dashboard" else ""))
        if path == "/":
            return redirect("/dashboard")
        if path.startswith("/app/"):
            return _file(FRONTEND / "app", path[len("/app/"):], "private, no-cache") or _not_found()
        return _page("app.html")
    return _not_found()


def _not_found() -> Response:
    return Response(404, b"Not found", "text/plain; charset=utf-8")


def _safe_next(nxt: str | None) -> str:
    if nxt and nxt.startswith("/") and not nxt.startswith("//") and (APP_PAGES.match(nxt.split("?")[0])):
        return nxt
    return "/dashboard"


def _authed(req: Request) -> bool:
    if req.session is not None:
        return True
    if req.conn is None or not req.token:
        return False
    req.session = auth.session_for(req.conn, req.cfg, req.token)
    return req.session is not None


def _api(req: Request, problems: list[str]) -> Response:
    try:
        for method, rx, fn, access in ROUTES:
            if method != req.method:
                continue
            m = rx.match(req.path)
            if not m:
                continue
            req.params = m.groupdict()
            if access != "public" and problems:
                raise ApiError(503, "GOD'S EYE is not configured yet", problems=problems)
            if access == "auth" and not _authed(req):
                raise ApiError(401, "Sign in required")
            if access == "cron":
                expected = req.cfg.cron_secret
                got = req.header("Authorization")
                if not expected or not auth.hmac.compare_digest(got.encode(), f"Bearer {expected}".encode()):
                    raise ApiError(401, "Unauthorized")
            if req.method not in ("GET", "HEAD") and access != "cron":
                if req.header("X-Requested-With") != "GodsEye":
                    raise ApiError(403, "Missing request header")
                origin = req.header("Origin")
                host = req.header("Host")
                if origin and host and urlparse(origin).netloc != host:
                    raise ApiError(403, "Cross-origin request refused")
            body = req.environ.get("_body", b"")
            if body:
                try:
                    data = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise ApiError(400, "Body must be JSON")
                if not isinstance(data, dict):
                    raise ApiError(400, "Body must be a JSON object")
                req.json = data
            result = fn(req)
            return result if isinstance(result, Response) else Response(200, result)
        raise ApiError(404, "Not found")
    except ApiError as e:
        return Response(e.status, {"error": e.message, **e.extra})


def app(environ, start_response):
    """The WSGI callable (Vercel imports `app` from app.py, which re-exports this)."""
    st = setup()
    cfg, db, problems = st["cfg"], st["db"], st["problems"]
    head = environ.get("REQUEST_METHOD", "GET").upper() == "HEAD"
    if head:
        environ["REQUEST_METHOD"] = "GET"
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        status, headers, body = _finish(Response(413, {"error": "Request too large"}), cfg, head)
        start_response(status, headers)
        return [body]
    environ["_body"] = environ["wsgi.input"].read(length) if length else b""
    req = Request(environ, cfg, db)
    try:
        if db is not None:
            req.conn = db.connect()
        resp = handle(req, problems)
        if req.conn is not None:
            if resp.status < 400 or resp.status == 409:
                req.conn.commit()
            else:
                req.conn.rollback()
    except Exception:
        traceback.print_exc()
        if req.conn is not None:
            try:
                req.conn.rollback()
            except Exception:
                pass
        resp = Response(500, {"error": "Something went wrong on the server. Check the function log."})
    finally:
        if req.conn is not None:
            try:
                req.conn.close()
            except Exception:
                pass
    status, headers, body = _finish(resp, cfg, head)
    start_response(status, headers)
    return [body]
