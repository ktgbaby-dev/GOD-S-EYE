"""Test helpers: an isolated environment (temp SQLite, test secrets) and an in-process WSGI client that keeps
cookies like a browser. Import this module before anything from `godseye`."""
import io
import json
import os
import sys
import tempfile
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_PASSWORD = "test-password-123"
os.environ["GODS_EYE_SKIP_DOTENV"] = "1"
for key in ("DATABASE_URL", "POSTGRES_URL", "VERCEL", "YOUTUBE_API_KEY", "SERPER_API_KEY", "BRAVE_SEARCH_API_KEY",
            "SECURE_COOKIES", "TRUST_PROXY"):
    os.environ.pop(key, None)
os.environ["GODS_EYE_PASSWORD"] = TEST_PASSWORD
os.environ["SESSION_SECRET"] = "s" * 48
os.environ["CRON_SECRET"] = "cron-test-secret"
# Tests never reach real APIs: unless a test starts its fake source server, sources point at a closed local port.
for key in ("GODS_EYE_AUDIUS_BASE", "GODS_EYE_YOUTUBE_BASE", "GODS_EYE_SERPER_BASE", "GODS_EYE_BRAVE_BASE"):
    os.environ[key] = "http://127.0.0.1:9"


def fresh_app(**env):
    """Point the app at a brand-new temp database (plus any env overrides) and return the WSGI callable."""
    tmp = tempfile.mkdtemp(prefix="godseye-test-")
    os.environ["GODS_EYE_DB_PATH"] = str(Path(tmp) / "test.db")
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from godseye import api  # noqa: F401  (registers routes)
    from godseye import web

    web.setup(reset=True)
    return web.app


class Client:
    def __init__(self, app, ip="203.0.113.7"):
        self.app = app
        self.cookies: dict[str, str] = {}
        self.ip = ip

    def request(self, method, path, body=None, headers=None, raw=None):
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
                   "CONTENT_LENGTH": str(len(payload)), "wsgi.input": io.BytesIO(payload),
                   "REMOTE_ADDR": self.ip, "HTTP_HOST": "localhost"}
        setup_testing_defaults(environ)
        environ["HTTP_HOST"] = "localhost"
        if self.cookies:
            environ["HTTP_COOKIE"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        h = {"X-Requested-With": "GodsEye", "Content-Type": "application/json"} if method != "GET" else {}
        h.update(headers or {})
        for k, v in h.items():
            key = k.upper().replace("-", "_")
            environ[key if key in ("CONTENT_TYPE",) else "HTTP_" + key] = v
        captured = {}

        def start_response(status, hdrs):
            captured["status"] = int(status.split()[0])
            captured["headers"] = hdrs

        chunks = self.app(environ, start_response)
        data = b"".join(chunks)
        for k, v in captured["headers"]:
            if k.lower() == "set-cookie":
                c = SimpleCookie()
                c.load(v)
                for name, morsel in c.items():
                    if morsel.value:
                        self.cookies[name] = morsel.value
                    else:
                        self.cookies.pop(name, None)
        return Resp(captured["status"], dict((k.lower(), v) for k, v in captured["headers"]), data)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body if body is not None else {}, **kw)

    def patch(self, path, body=None, **kw):
        return self.request("PATCH", path, body or {}, **kw)

    def put(self, path, body=None, **kw):
        return self.request("PUT", path, body or {}, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, None, **kw)

    def login(self, password=TEST_PASSWORD):
        return self.post("/api/login", {"password": password})


class Resp:
    def __init__(self, status, headers, data):
        self.status = status
        self.headers = headers
        self.data = data

    @property
    def json(self):
        return json.loads(self.data.decode("utf-8"))

    @property
    def text(self):
        return self.data.decode("utf-8")


def qs(**kw):
    return "?" + urlencode({k: v for k, v in kw.items() if v is not None})
