from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


def _is_railway() -> bool:
    return any(
        os.getenv(name)
        for name in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_DEPLOYMENT_ID",
        )
    )


def _resolve_data_dir() -> Path:
    explicit_data_dir = os.getenv("DATA_DIR")
    if explicit_data_dir:
        return Path(explicit_data_dir)

    railway_volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if railway_volume_path:
        return Path(railway_volume_path)

    if _is_railway():
        common_volume_path = Path("/data")
        if common_volume_path.exists():
            return common_volume_path
        raise RuntimeError(
            "Railway persistent storage is not configured. Add a Volume to the bot service "
            "and mount it at /data, or set DATA_DIR to the mounted volume path."
        )

    return BASE_DIR / "data"


DATA_DIR = _resolve_data_dir()
UPLOAD_DIR = DATA_DIR / "uploads"
AVATAR_DIR = DATA_DIR / "avatars"
DATABASE_PATH = DATA_DIR / "database.db"


BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")

from branding import BRAND_SHORT
BRAND_NAME = BRAND_SHORT
CURRENCY_SYMBOL = "£"
INCENTIVE_REWARD = 80

DIAMOND_INCENTIVE_TARGET = 250_000
DAYS_INCENTIVE_TARGET = 22
HOURS_INCENTIVE_TARGET = 80

INCENTIVE_TIERS = [
    {
        "tier": 1,
        "diamonds": DIAMOND_INCENTIVE_TARGET,
        "days": DAYS_INCENTIVE_TARGET,
        "hours": HOURS_INCENTIVE_TARGET,
        "reward": INCENTIVE_REWARD,
    },
    # Add tier 2, tier 3, etc. here when the Aether incentive targets are confirmed.
]

TIER_THRESHOLDS = {
    1: 0,
    2: 100_000,
    3: 200_000,
    4: 300_000,
    5: 500_000,
    6: 700_000,
    7: 1_000_000,
    8: 1_600_000,
    9: 2_500_000,
    10: 5_000_000,
}


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)

INTEGRATION_SECRET = os.getenv("AETHER_INTEGRATION_SECRET", "")
INTEGRATION_HOST = os.getenv("INTEGRATION_HOST", "0.0.0.0")
INTEGRATION_PORT = int(os.getenv("PORT", os.getenv("INTEGRATION_PORT", "8080")))
MAX_REPORT_BYTES = 20 * 1024 * 1024
CHANNEL_PURPOSES = ("leaderboard", "wins", "events", "campaigns", "announcements", "logs")
ANNOUNCE_ACHIEVEMENTS = frozenset(filter(None, (v.strip() for v in os.getenv("ANNOUNCE_ACHIEVEMENTS", "").split(","))))
DIAMOND_MILESTONES = tuple(sorted({int(v) for v in os.getenv("DIAMOND_MILESTONES", "100000,250000,500000,1000000,2500000,5000000").split(",") if v.strip()}))

if ANNOUNCE_ACHIEVEMENTS - {"pb", "milestone", "league", "incentive", "rank"}:
    raise ValueError("Unknown ANNOUNCE_ACHIEVEMENTS type")
if any(value <= 0 for value in DIAMOND_MILESTONES):
    raise ValueError("DIAMOND_MILESTONES must be positive")
