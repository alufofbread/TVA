from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = Path(os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
AVATAR_DIR = DATA_DIR / "avatars"
DATABASE_PATH = DATA_DIR / "database.db"

load_dotenv(ENV_PATH)

BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")

BRAND_NAME = "TEAM VEXTAL"
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
    # Add tier 2, tier 3, etc. here when the Fasttrack incentive targets are confirmed.
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
