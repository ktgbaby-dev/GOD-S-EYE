"""GOD'S EYE — private client discovery system for OG-WAN.

Vercel imports `app` (a WSGI callable) from this file. Locally:

    python app.py --init      # write .env with a generated password + secrets (prints where, never the password)
    python app.py             # serve on http://127.0.0.1:5620
    python app.py --db data/demo.db --port 5621
"""
import argparse
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from godseye import api  # noqa: E402,F401  (registers routes)
from godseye.web import app  # noqa: E402

__all__ = ["app"]


def init_env() -> None:
    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else (ROOT / ".env.example").read_text(encoding="utf-8")
    wanted = {"GODS_EYE_PASSWORD": secrets.token_urlsafe(14), "SESSION_SECRET": secrets.token_hex(32),
              "CRON_SECRET": secrets.token_hex(24)}
    lines = text.splitlines()
    for key, value in wanted.items():
        if re.search(rf"^{key}=.+", text, re.M):
            continue
        lines = [l for l in lines if not re.match(rf"^#?\s*{key}=", l)] + [f"{key}={value}"]
    env.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(f"Wrote {env}. Your password is the GODS_EYE_PASSWORD line in that file.")


class _Server(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)


def _scheduler(stop: threading.Event) -> None:
    """Local stand-in for the Vercel cron: runs the daily drop once a day after the configured hour."""
    from godseye import discovery, drop
    from godseye import normalize as N
    from godseye import settings as S
    from godseye.web import setup

    while not stop.wait(600):
        st = setup()
        if st["db"] is None:
            continue
        try:
            with st["db"].connect() as conn:
                strategy = S.load(conn)
                local_hour = N.utcnow().astimezone(N.get_tz(strategy["timezone"])).hour
                if local_hour >= strategy["drop_hour"] and not drop.drop_ran_today(conn, strategy):
                    plan = discovery.make_plan(strategy, None, "drop")
                    res = discovery.run_batch(conn, st["cfg"], strategy, plan, kind="drop")
                    print(f"[gods-eye] daily drop: {res['stats']}", flush=True)
        except Exception as e:  # keep the scheduler alive; the next tick retries
            print(f"[gods-eye] scheduler error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="GOD'S EYE — private client discovery for OG-WAN")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5620")))
    ap.add_argument("--db", help="SQLite file (default data/gods_eye.db)")
    ap.add_argument("--init", action="store_true", help="create .env with generated secrets and exit")
    ap.add_argument("--no-scheduler", action="store_true", help="don't run the automatic daily drop")
    ap.add_argument("--quiet", action="store_true", help="no access log")
    args = ap.parse_args()
    if args.init:
        init_env()
        return
    if args.db:
        os.environ["GODS_EYE_DB_PATH"] = str(Path(args.db).resolve())
    from godseye.web import setup

    st = setup(reset=True)
    for p in st["problems"]:
        print(f"Not ready: {p}", file=sys.stderr)
    if st["problems"]:
        print("Run  python app.py --init  to generate a local .env.", file=sys.stderr)
    srv = make_server(args.host, args.port, app, server_class=_Server, handler_class=_QuietHandler)
    srv.quiet = args.quiet
    where = "PostgreSQL" if st["db"] and st["db"].dialect == "pg" else (st["db"].path if st["db"] else "none")
    print(f"GOD'S EYE online at http://{args.host}:{args.port}  (database: {where})", flush=True)
    stop = threading.Event()
    if not args.no_scheduler:
        threading.Thread(target=_scheduler, args=(stop,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
