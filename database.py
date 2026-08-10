from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from config import DATABASE_PATH, ensure_directories


@dataclass(slots=True)
class Creator:
    creator_id: str
    creator_name: str
    diamonds: int
    hours: float
    days: int
    battles: int
    new_followers: int
    tier: int
    rank: int
    incentive_status: str
    avatar_url: str
    avatar_path: str
    join_date: str
    last_updated: str


@dataclass(slots=True)
class CreatorChannel:
    creator_id: str
    creator_name: str
    channel_id: int
    updated_by: int
    updated_at: str


@dataclass(slots=True)
class LeaderboardChannel:
    channel_type: str
    channel_id: int
    updated_by: int
    updated_at: str


@dataclass(slots=True)
class Referral:
    id: int
    referrer_id: str
    referrer_name: str
    creator_id: str
    creator_name: str
    start_date: str
    end_date: str
    diamonds: int
    hours: float
    last_diamonds: int
    last_hours: float
    days_remaining: int
    current_tier: int
    status: str
    final_reward: str


class Database:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        ensure_directories()
        self.path = path
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS creators (
                    creator_id TEXT PRIMARY KEY,
                    creator_name TEXT NOT NULL,
                    diamonds INTEGER NOT NULL DEFAULT 0,
                    hours REAL NOT NULL DEFAULT 0,
                    days INTEGER NOT NULL DEFAULT 0,
                    battles INTEGER NOT NULL DEFAULT 0,
                    new_followers INTEGER NOT NULL DEFAULT 0,
                    tier INTEGER NOT NULL DEFAULT 1,
                    rank INTEGER NOT NULL DEFAULT 0,
                    incentive_status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
                    avatar_url TEXT NOT NULL DEFAULT '',
                    avatar_path TEXT NOT NULL DEFAULT '',
                    join_date TEXT NOT NULL DEFAULT '',
                    last_updated TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id TEXT NOT NULL,
                    referrer_name TEXT NOT NULL,
                    creator_id TEXT NOT NULL DEFAULT '',
                    creator_name TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    diamonds INTEGER NOT NULL DEFAULT 0,
                    hours REAL NOT NULL DEFAULT 0,
                    last_diamonds INTEGER NOT NULL DEFAULT 0,
                    last_hours REAL NOT NULL DEFAULT 0,
                    days_remaining INTEGER NOT NULL DEFAULT 30,
                    current_tier INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'Active',
                    final_reward TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id, status)")
            self._ensure_column(conn, "creators", "avatar_url", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "creators", "avatar_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "creators", "new_followers", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "creators", "join_date", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS import_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL DEFAULT '',
                    imported_at TEXT NOT NULL,
                    creator_count INTEGER NOT NULL
                )
                """
            )
            self._ensure_column(conn, "import_history", "snapshot_hash", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS creator_channels (
                    creator_id TEXT PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    updated_by INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leaderboard_channels (
                    channel_type TEXT PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    updated_by INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (channel_type IN ('daily', 'monthly'))
                )
                """
            )
    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def replace_creators(self, creators: Iterable[dict], filename: str, file_hash: str, snapshot_hash: str = "") -> int:
        rows = list(creators)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            existing_rows = conn.execute(
                "SELECT creator_id, creator_name, avatar_url, avatar_path, join_date, tier FROM creators"
            ).fetchall()
            existing_by_id = {row["creator_id"]: row for row in existing_rows}
            existing_by_name = {row["creator_name"].strip().lower(): row for row in existing_rows}

            for row in rows:
                existing = existing_by_id.get(row["creator_id"]) or existing_by_name.get(
                    str(row["creator_name"]).strip().lower()
                )
                if existing and not row.get("avatar_path"):
                    row["avatar_url"] = existing["avatar_url"]
                    row["avatar_path"] = existing["avatar_path"]
                if existing and not row.get("join_date"):
                    row["join_date"] = existing["join_date"]
                if existing and row.pop("preserve_existing_tier", False):
                    row["tier"] = existing["tier"]
                else:
                    row.pop("preserve_existing_tier", None)

            conn.execute("DELETE FROM creators")
            conn.executemany(
                """
                INSERT INTO creators (
                    creator_id, creator_name, diamonds, hours, days, battles, new_followers,
                    tier, rank, incentive_status, avatar_url, avatar_path, join_date, last_updated
                )
                VALUES (
                    :creator_id, :creator_name, :diamonds, :hours, :days, :battles, :new_followers,
                    :tier, :rank, :incentive_status, :avatar_url, :avatar_path, :join_date, :last_updated
                )
                """,
                [{**row, "last_updated": now} for row in rows],
            )
            # Keep one history record per file.  Re-uploading an identical
            # spreadsheet may refresh the current snapshot, but it is not a
            # new reporting day and should not create another import entry.
            # Backfill this value on pre-existing history rows during the
            # migration to content-based referral deduplication.
            conn.execute(
                "UPDATE import_history SET snapshot_hash = ? WHERE file_hash = ? AND snapshot_hash = ''",
                (snapshot_hash, file_hash),
            )
            conn.execute(
                """
                INSERT INTO import_history (filename, file_hash, snapshot_hash, imported_at, creator_count)
                SELECT ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM import_history WHERE file_hash = ?
                )
                """,
                (filename, file_hash, snapshot_hash, now, len(rows), file_hash),
            )
        return len(rows)

    def add_referral(self, referrer: Creator, creator: Creator | None, creator_name: str, start_date: date) -> Referral:
        """Save a referral and baseline its current monthly snapshot.

        The baseline prevents performance earned before the referral date from being counted.
        """
        end_date = start_date + timedelta(days=30)
        referred_id = creator.creator_id if creator else ""
        referred_name = creator.creator_name if creator else creator_name.strip()
        # The spreadsheet is month-to-date. For someone who joined this month,
        # every reported metric belongs to the referral period, even if the
        # referral is recorded after the latest import.
        joined_this_month = (start_date.year, start_date.month) == (date.today().year, date.today().month)
        baseline_diamonds = 0 if creator and joined_this_month else (creator.diamonds if creator else 0)
        baseline_hours = 0.0 if creator and joined_this_month else (creator.hours if creator else 0.0)
        starting_diamonds = creator.diamonds if creator and joined_this_month else 0
        starting_hours = creator.hours if creator and joined_this_month else 0.0
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO referrals (
                    referrer_id, referrer_name, creator_id, creator_name, start_date, end_date,
                    diamonds, hours, last_diamonds, last_hours, days_remaining, current_tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (referrer.creator_id, referrer.creator_name, referred_id, referred_name,
                 start_date.isoformat(), end_date.isoformat(), starting_diamonds, starting_hours,
                 baseline_diamonds, baseline_hours, max(0, (end_date - date.today()).days),
                 self._tier_for_diamonds(starting_diamonds)),
            )
            row = conn.execute("SELECT * FROM referrals WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return Referral(**dict(row))

    def update_referrals_from_snapshot(self, creators: Iterable[dict], observed_on: date | None = None) -> None:
        """Accumulate referral performance independently from the replaceable monthly snapshot."""
        observed_on = observed_on or date.today()
        creator_rows = list(creators)
        by_id = {str(row["creator_id"]): row for row in creator_rows}
        by_name = {str(row["creator_name"]).strip().lower(): row for row in creator_rows}
        with self.connect() as conn:
            referrals = conn.execute("SELECT * FROM referrals WHERE status = 'Active'").fetchall()
            for referral in referrals:
                end_date = date.fromisoformat(referral["end_date"])
                creator = by_id.get(referral["creator_id"]) or by_name.get(referral["creator_name"].strip().lower())
                diamonds, hours = referral["diamonds"], referral["hours"]
                last_diamonds, last_hours = referral["last_diamonds"], referral["last_hours"]
                creator_id = referral["creator_id"]
                creator_name = referral["creator_name"]
                if creator and observed_on >= date.fromisoformat(referral["start_date"]):
                    current_diamonds = int(creator["diamonds"])
                    current_hours = float(creator["hours"])
                    referral_start = date.fromisoformat(referral["start_date"])
                    joined_this_month = (referral_start.year, referral_start.month) == (
                        observed_on.year,
                        observed_on.month,
                    )
                    # Repair referrals created after an import under the old
                    # baseline logic. Their month-to-date performance should
                    # count from their Join time, rather than remain at zero.
                    if joined_this_month and diamonds == 0 and hours == 0:
                        diamonds, hours = current_diamonds, current_hours
                        last_diamonds, last_hours = current_diamonds, current_hours
                        creator_id, creator_name = creator["creator_id"], creator["creator_name"]
                    else:
                        # Monthly sheets are cumulative. A smaller value marks a new month, so
                        # its full value is the new contribution rather than a negative delta.
                        diamonds += current_diamonds - last_diamonds if current_diamonds >= last_diamonds else current_diamonds
                        hours += current_hours - last_hours if current_hours >= last_hours else current_hours
                        last_diamonds, last_hours = current_diamonds, current_hours
                        creator_id, creator_name = creator["creator_id"], creator["creator_name"]

                current_tier = self._tier_for_diamonds(diamonds)
                days_remaining = max(0, (end_date - observed_on).days)
                completed = observed_on >= end_date
                status = "Completed" if completed else "Active"
                final_reward = f"Tier {current_tier}" if completed else ""
                conn.execute(
                    """
                    UPDATE referrals SET creator_id=?, creator_name=?, diamonds=?, hours=?,
                        last_diamonds=?, last_hours=?, days_remaining=?, current_tier=?, status=?, final_reward=?
                    WHERE id=?
                    """,
                    (creator_id, creator_name, int(round(diamonds)), round(hours, 2), last_diamonds,
                     last_hours, days_remaining, current_tier, status, final_reward, referral["id"]),
                )

    @staticmethod
    def _tier_for_diamonds(diamonds: int) -> int:
        # Kept here to make stored referrals independent of the current snapshot table.
        thresholds = (0, 100_000, 200_000, 300_000, 500_000, 700_000, 1_000_000, 1_600_000, 2_500_000, 5_000_000)
        return max(index + 1 for index, threshold in enumerate(thresholds) if diamonds >= threshold)

    def get_referrals_for_referrer(self, referrer_id: str, include_completed: bool = False) -> list[Referral]:
        # A dashboard opened after day 30 must not keep showing an expired referral
        # merely because no new spreadsheet has arrived that day.
        # Reconcile against the current snapshot so referrals created after an
        # import can immediately show their already-earned month-to-date totals.
        with self.connect() as conn:
            creators = [dict(row) for row in conn.execute("SELECT * FROM creators").fetchall()]
        self.update_referrals_from_snapshot(creators, date.today())
        query = "SELECT * FROM referrals WHERE referrer_id = ?"
        if not include_completed:
            query += " AND status = 'Active'"
        query += " ORDER BY end_date ASC, id ASC"
        with self.connect() as conn:
            rows = conn.execute(query, (referrer_id,)).fetchall()
        return [Referral(**dict(row)) for row in rows]

    def update_creator_avatar(self, creator_id: str, avatar_url: str, avatar_path: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE creators
                SET avatar_url = ?, avatar_path = ?, last_updated = ?
                WHERE creator_id = ?
                """,
                (avatar_url, avatar_path, now, creator_id),
            )

    def set_creator_channel(self, creator_id: str, channel_id: int, updated_by: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO creator_channels (creator_id, channel_id, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(creator_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (creator_id, channel_id, updated_by, now),
            )

    def get_creator_channels(self) -> list[CreatorChannel]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.creator_id,
                    c.creator_name,
                    cc.channel_id,
                    cc.updated_by,
                    cc.updated_at
                FROM creator_channels cc
                INNER JOIN creators c ON c.creator_id = cc.creator_id
                ORDER BY c.rank ASC
                """
            ).fetchall()
        return [CreatorChannel(**dict(row)) for row in rows]

    def set_leaderboard_channel(self, channel_type: str, channel_id: int, updated_by: int) -> None:
        if channel_type not in {"daily", "monthly"}:
            raise ValueError("leaderboard channel type must be 'daily' or 'monthly'")

        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO leaderboard_channels (channel_type, channel_id, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_type) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (channel_type, channel_id, updated_by, now),
            )

    def get_leaderboard_channels(self) -> list[LeaderboardChannel]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT channel_type, channel_id, updated_by, updated_at
                FROM leaderboard_channels
                ORDER BY CASE channel_type WHEN 'daily' THEN 0 ELSE 1 END
                """
            ).fetchall()
        return [LeaderboardChannel(**dict(row)) for row in rows]

    def has_import_hash(self, file_hash: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM import_history WHERE file_hash = ? LIMIT 1",
                (file_hash,),
            ).fetchone()
        return row is not None

    def has_referral_snapshot_hash(self, snapshot_hash: str) -> bool:
        """Return whether these daily metrics have already updated referrals."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM import_history WHERE snapshot_hash = ? LIMIT 1",
                (snapshot_hash,),
            ).fetchone()
        return row is not None

    def get_creators(self) -> list[Creator]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM creators ORDER BY rank ASC").fetchall()
        return [Creator(**dict(row)) for row in rows]

    def find_creator(self, creator_name: str) -> Creator | None:
        needle = creator_name.strip().lower()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM creators
                WHERE lower(creator_name) = ?
                   OR lower(creator_name) LIKE ?
                   OR lower(creator_id) = ?
                   OR lower(creator_id) LIKE ?
                ORDER BY
                    CASE WHEN lower(creator_name) = ? THEN 0 ELSE 1 END,
                    rank ASC
                LIMIT 1
                """,
                (needle, f"%{needle}%", needle, f"%{needle}%", needle),
            ).fetchone()
        return Creator(**dict(row)) if row else None

    def get_summary(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(diamonds), 0) AS total_diamonds,
                    COUNT(*) AS active_creators,
                    COALESCE(SUM(battles), 0) AS total_battles
                FROM creators
                """
            ).fetchone()
        return dict(row)
