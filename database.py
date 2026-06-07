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
