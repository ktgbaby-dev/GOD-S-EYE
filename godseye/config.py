"""Environment configuration. Secrets come from the process environment or a local `.env` file.
They are never sent to the browser and never logged; /api/status only reports whether a key is set."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # Real environment variables win over .env values.
        os.environ.setdefault(key.strip(), value)


if os.environ.get("GODS_EYE_SKIP_DOTENV") != "1":
    _load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def find_database_url() -> str:
    """DATABASE_URL / POSTGRES_URL, or the prefixed names Vercel's storage integrations can inject
    (e.g. STORAGE_DATABASE_URL). Only postgres:// URLs are accepted."""
    for key in ("DATABASE_URL", "POSTGRES_URL"):
        if env(key).startswith(("postgres://", "postgresql://")):
            return env(key)
    for suffix in ("_DATABASE_URL", "_POSTGRES_URL"):
        for key in sorted(os.environ):
            if key.endswith(suffix) and env(key).startswith(("postgres://", "postgresql://")):
                return env(key)
    return ""


class Config:
    def __init__(self) -> None:
        # Vercel sets VERCEL=1. Its filesystem is temporary, so SQLite is refused there.
        self.on_vercel = env("VERCEL") == "1"
        self.database_url = find_database_url()
        self.db_path = env("GODS_EYE_DB_PATH", str(ROOT / "data" / "gods_eye.db"))
        self.password = env("GODS_EYE_PASSWORD")
        self.session_secret = env("SESSION_SECRET")
        self.cron_secret = env("CRON_SECRET")
        self.secure_cookies = env("SECURE_COOKIES", "1" if self.on_vercel else "0") == "1"
        # Discovery provider credentials (all optional).
        self.youtube_key = env("YOUTUBE_API_KEY")
        self.serper_key = env("SERPER_API_KEY")
        self.brave_key = env("BRAVE_SEARCH_API_KEY")
        self.audius_app_name = env("AUDIUS_APP_NAME", "GodsEye")
        # Tests point providers at local fakes; never set this in production.
        self.provider_base_urls = {
            "audius": env("GODS_EYE_AUDIUS_BASE", "https://api.audius.co"),
            "youtube": env("GODS_EYE_YOUTUBE_BASE", "https://www.googleapis.com/youtube/v3"),
            "serper": env("GODS_EYE_SERPER_BASE", "https://google.serper.dev"),
            "brave": env("GODS_EYE_BRAVE_BASE", "https://api.search.brave.com/res/v1"),
        }
        self.trust_proxy = self.on_vercel or env("TRUST_PROXY") == "1"

    def problems(self) -> list[str]:
        out = []
        if not self.password:
            out.append("GODS_EYE_PASSWORD is not set.")
        elif len(self.password) < 10:
            out.append("GODS_EYE_PASSWORD must be at least 10 characters.")
        if len(self.session_secret) < 32:
            out.append("SESSION_SECRET must be set to at least 32 random characters.")
        if self.on_vercel and not self.database_url:
            out.append("No database connected. On Vercel the disk is temporary: add a Postgres database "
                       "(Storage → Neon) so DATABASE_URL is set, then redeploy.")
        return out


def get_config() -> Config:
    return Config()
