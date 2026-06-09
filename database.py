from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
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
                    last_updated TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "creators", "avatar_url", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "creators", "avatar_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "creators", "new_followers", "INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS import_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    creator_count INTEGER NOT NULL
                )
                """
            )
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

    def replace_creators(self, creators: Iterable[dict], filename: str, file_hash: str) -> int:
        rows = list(creators)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            existing_rows = conn.execute(
                "SELECT creator_id, creator_name, avatar_url, avatar_path, tier FROM creators"
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
                if existing and row.pop("preserve_existing_tier", False):
                    row["tier"] = existing["tier"]
                else:
                    row.pop("preserve_existing_tier", None)

            conn.execute("DELETE FROM creators")
            conn.executemany(
                """
                INSERT INTO creators (
                    creator_id, creator_name, diamonds, hours, days, battles, new_followers,
                    tier, rank, incentive_status, avatar_url, avatar_path, last_updated
                )
                VALUES (
                    :creator_id, :creator_name, :diamonds, :hours, :days, :battles, :new_followers,
                    :tier, :rank, :incentive_status, :avatar_url, :avatar_path, :last_updated
                )
                """,
                [{**row, "last_updated": now} for row in rows],
            )
            conn.execute(
                """
                INSERT INTO import_history (filename, file_hash, imported_at, creator_count)
                VALUES (?, ?, ?, ?)
                """,
                (filename, file_hash, now, len(rows)),
            )
        return len(rows)

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
