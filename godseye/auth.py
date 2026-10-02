"""Single-user authentication for OG-WAN.

- The password lives only in the GODS_EYE_PASSWORD environment variable; it is compared in constant time.
- A successful login creates a random session token. The browser keeps it in an HttpOnly cookie; the database keeps
  only an HMAC of it (keyed with SESSION_SECRET), so a database leak does not leak usable sessions.
- Sign-out deletes the session row; "sign out everywhere" deletes all of them.
- Failed attempts are recorded per (hashed) IP in the database, so throttling also works across serverless
  instances: 5 failures in 15 minutes locks that IP out for the rest of the window."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from . import normalize as N
from .config import Config
from .db import Conn

COOKIE = "ge_session"
SESSION_DAYS = 30
TOUCH_MINUTES = 30
WINDOW_MINUTES = 15
MAX_FAILURES = 5


def _hmac(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def password_ok(cfg: Config, supplied: str) -> bool:
    if not cfg.password:
        return False
    a = hashlib.sha256((supplied or "").encode()).digest()
    b = hashlib.sha256(cfg.password.encode()).digest()
    return hmac.compare_digest(a, b)


def ip_key(cfg: Config, ip: str) -> str:
    return _hmac(cfg.session_secret, "ip:" + (ip or "unknown"))[:32]


def recent_failures(conn: Conn, cfg: Config, ip: str) -> int:
    since = N.utcnow() - timedelta(minutes=WINDOW_MINUTES)
    return int(conn.scalar("SELECT COUNT(*) AS n FROM login_attempts WHERE ip_hash = ? AND ok = 0 AND at >= ?",
                           (ip_key(cfg, ip), N.iso(since))) or 0)


def locked_out(conn: Conn, cfg: Config, ip: str) -> int:
    """Seconds until this IP may try again (0 = allowed)."""
    since = N.utcnow() - timedelta(minutes=WINDOW_MINUTES)
    rows = conn.all("SELECT at FROM login_attempts WHERE ip_hash = ? AND ok = 0 AND at >= ? ORDER BY at",
                    (ip_key(cfg, ip), N.iso(since)))
    if len(rows) < MAX_FAILURES:
        return 0
    oldest = N.parse_dt(rows[-MAX_FAILURES]["at"])
    return max(1, int((oldest + timedelta(minutes=WINDOW_MINUTES) - N.utcnow()).total_seconds()))


def record_attempt(conn: Conn, cfg: Config, ip: str, ok: bool) -> None:
    key = ip_key(cfg, ip)
    conn.insert("login_attempts", {"ip_hash": key, "ok": 1 if ok else 0, "at": N.now_iso()})
    if ok:
        conn.run("DELETE FROM login_attempts WHERE ip_hash = ? AND ok = 0", (key,))
    conn.run("DELETE FROM login_attempts WHERE at < ?", (N.iso(N.utcnow() - timedelta(days=2)),))


def create_session(conn: Conn, cfg: Config, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    now = N.utcnow()
    conn.insert("sessions", {"token_hash": _hmac(cfg.session_secret, token), "created_at": N.iso(now),
                             "expires_at": N.iso(now + timedelta(days=SESSION_DAYS)), "last_seen_at": N.iso(now),
                             "user_agent": (user_agent or "")[:200]})
    conn.run("DELETE FROM sessions WHERE expires_at < ?", (N.iso(now),))
    return token


def session_for(conn: Conn, cfg: Config, token: str | None) -> dict | None:
    if not token or len(token) > 200:
        return None
    row = conn.one("SELECT * FROM sessions WHERE token_hash = ?", (_hmac(cfg.session_secret, token),))
    if not row:
        return None
    now = N.utcnow()
    if N.parse_dt(row["expires_at"]) <= now:
        conn.run("DELETE FROM sessions WHERE id = ?", (row["id"],))
        return None
    if (now - N.parse_dt(row["last_seen_at"])).total_seconds() > TOUCH_MINUTES * 60:
        # Sliding expiry: an active device stays signed in.
        conn.update("sessions", row["id"], {"last_seen_at": N.iso(now),
                                            "expires_at": N.iso(now + timedelta(days=SESSION_DAYS))})
    return row


def end_session(conn: Conn, cfg: Config, token: str | None) -> None:
    if token:
        conn.run("DELETE FROM sessions WHERE token_hash = ?", (_hmac(cfg.session_secret, token),))


def end_all_sessions(conn: Conn) -> int:
    return conn.run("DELETE FROM sessions")


def cookie_header(token: str, secure: bool, clear: bool = False) -> str:
    parts = [f"{COOKIE}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Lax",
             f"Max-Age={0 if clear else SESSION_DAYS * 86400}"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
