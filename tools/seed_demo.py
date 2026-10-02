"""Development-only demo data: fills a SEPARATE database with clearly fictional leads so the UI, charts and
workflow can be exercised without real data.

    .venv/Scripts/python tools/seed_demo.py                 # writes data/demo.db
    .venv/Scripts/python app.py --db data/demo.db --port 5621

Every row is marked is_demo=1 / provenance "demo", every handle starts with "demo.", and every profile link points
at example.com, so nothing here can be mistaken for (or link to) a real artist. It refuses to touch the default
database or any Postgres URL. Remove it any time: delete data/demo.db, or Settings → Data → Remove demo data."""
import os
import random
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
target = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "demo.db").resolve()
if target.name == "gods_eye.db":
    sys.exit("Refusing to seed the main database. Demo data goes in its own file (default data/demo.db).")
os.environ["GODS_EYE_DB_PATH"] = str(target)

from godseye import leads as L  # noqa: E402
from godseye import normalize as N  # noqa: E402
from godseye import settings as S  # noqa: E402
from godseye.config import get_config  # noqa: E402
from godseye.db import Database  # noqa: E402

FIRST = ["Nova", "Kairo", "Sade", "Temi", "Juno", "Ayo", "Zuri", "Lumi", "Rex", "Ola", "Ivy", "Kemi", "Dax", "Mira",
         "Tobi", "Eko", "Zara", "Femi", "Lola", "Bayo", "Ade", "Nia", "Kofi", "Ama", "Sol", "Wale", "Yemi", "Ife",
         "Remi", "Tayo", "Odun", "Seyi", "Kai", "Lex", "Bisi", "Uche"]
GENRES = ["Afrobeats", "Afropop", "R&B", "Hip-Hop", "Amapiano", "Afro-fusion", "Street-pop"]
PLACES = ["Lagos, Nigeria", "Abuja, Nigeria", "Ibadan, Nigeria", "Port Harcourt, Nigeria", "London, UK",
          "Accra, Ghana", "Manchester, UK", ""]
PLATFORMS = ["instagram", "instagram", "instagram", "tiktok", "tiktok", "youtube", "audius"]
BIOS = [
    "Independent artist. New EP loading. Producers DM.",
    "Singer · songwriter. Open for collabs. Booking via email.",
    "Afro-fusion from the 6ix. Debut single out now on all platforms.",
    "Studio sessions every week. Looking for a producer for my next project.",
    "Rapper. Unsigned. Snippet in highlights, dropping Friday.",
    "Making music for the culture. Stream my latest everywhere.",
    "R&B voice. New music coming soon.",
    "",
]
STATUSES = ["new"] * 12 + ["watching"] * 5 + ["contact"] * 4 + ["contacted"] * 6 + ["follow_up"] * 3 + ["client"] * 3 + ["not_fit"] * 3


def main() -> None:
    if target.exists():
        target.unlink()
    db = Database(get_config(), str(target))
    rng = random.Random(7)
    now = N.utcnow()
    with db.connect() as conn:
        strategy = S.load(conn)
        for i, first in enumerate(FIRST):
            platform = rng.choice(PLATFORMS)
            handle = f"demo.{first.lower()}{rng.randint(1, 99)}"
            discovered = now - timedelta(days=rng.choice([0, 0, 0, 0, 1, 2, 3, 5, 8, 12, 16, 21, 27]), hours=rng.randint(0, 20))
            activity = discovered - timedelta(days=rng.choice([0, 1, 2, 4, 9, 20, 45, 120]))
            followers = rng.choice([None, 420, 1800, 6400, 12400, 38000, 74000, 310000])
            data = {"name": f"{first} (demo)", "handle": handle, "platform": platform,
                    "profile_url": f"https://example.com/demo/{handle}", "genre": rng.choice(GENRES),
                    "location": rng.choice(PLACES), "followers": followers, "bio": rng.choice(BIOS),
                    "source_url": "", "last_activity_at": N.iso(activity),
                    "last_release_at": N.iso(activity) if rng.random() < 0.5 else None}
            lead_id = L.create(conn, data, strategy, "demo", "Demo seed", is_demo=True, discovered_at=N.iso(discovered))
            status = STATUSES[i % len(STATUSES)]
            if status != "new":
                L.set_status(conn, lead_id, status, strategy)
                if status in ("contacted", "follow_up", "client"):
                    contacted = discovered + timedelta(days=rng.randint(0, 3))
                    due = contacted + timedelta(days=rng.choice([-2, 1, 4, 6]))
                    conn.update("leads", lead_id, {"last_contacted_at": N.iso(min(contacted, now)),
                                                   "follow_up_at": N.iso(due) if status != "client" else None})
        n = conn.scalar("SELECT COUNT(*) AS n FROM leads")
    print(f"Seeded {n} fictional demo leads into {target}")


if __name__ == "__main__":
    main()
