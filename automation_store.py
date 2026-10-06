"""Additive persistence for Aether automation; legacy tables remain intact."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from config import CHANNEL_PURPOSES


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class AutomationStore:
    def init_automation(self):
        statements = (
            """CREATE TABLE IF NOT EXISTS automation_channels (
                purpose TEXT PRIMARY KEY, channel_id INTEGER NOT NULL,
                updated_by INTEGER NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY, report_date TEXT NOT NULL, imported_at TEXT NOT NULL,
                filename TEXT NOT NULL, snapshot_hash TEXT UNIQUE NOT NULL,
                creator_count INTEGER NOT NULL, delivery_status TEXT NOT NULL DEFAULT 'pending',
                summary TEXT NOT NULL DEFAULT '{}')""",
            """CREATE TABLE IF NOT EXISTS creator_snapshots (
                creator_id TEXT NOT NULL, report_date TEXT NOT NULL,
                import_id INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (creator_id, report_date))""",
            """CREATE TABLE IF NOT EXISTS achievements (
                achievement_key TEXT PRIMARY KEY, creator_id TEXT NOT NULL,
                report_date TEXT NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL,
                import_id INTEGER NOT NULL, announced_at TEXT,
                publish INTEGER NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS discord_messages (
                message_key TEXT PRIMARY KEY, channel_id INTEGER NOT NULL,
                message_id INTEGER, marker TEXT NOT NULL, started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT)""",
            """CREATE TABLE IF NOT EXISTS integration_requests (
                request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                event_type TEXT NOT NULL, resource_id TEXT NOT NULL, revision INTEGER NOT NULL,
                status TEXT NOT NULL, received_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                error TEXT)""",
            """CREATE TABLE IF NOT EXISTS website_events (
                event_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                payload_hash TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                channel_id INTEGER, message_id INTEGER, updated_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_snapshots_date ON creator_snapshots(report_date)",
        )
        with self.connect() as conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute("""INSERT OR IGNORE INTO automation_channels
                SELECT 'leaderboard', channel_id, updated_by, updated_at
                FROM leaderboard_channels ORDER BY CASE channel_type WHEN 'monthly' THEN 0 ELSE 1 END LIMIT 1""")

    def set_automation_channel(self, purpose, channel_id, updated_by):
        if purpose not in CHANNEL_PURPOSES:
            raise ValueError('Unknown automation channel purpose')
        with self.connect() as conn:
            conn.execute("""INSERT INTO automation_channels VALUES (?, ?, ?, ?)
                ON CONFLICT(purpose) DO UPDATE SET channel_id=excluded.channel_id,
                updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
                (purpose, channel_id, updated_by, utcnow()))

    def automation_channels(self):
        with self.connect() as conn:
            return {row['purpose']: row['channel_id'] for row in conn.execute('SELECT * FROM automation_channels')}

    def latest_import(self):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM import_runs ORDER BY id DESC LIMIT 1').fetchone()
            return dict(row) if row else None

    def finish_import_delivery(self, import_id, summary, status='complete'):
        with self.connect() as conn:
            conn.execute('UPDATE import_runs SET delivery_status=?, summary=? WHERE id=?',
                         (status, json.dumps(summary), import_id))

    def creator_history(self, creator_id):
        with self.connect() as conn:
            return [dict(json.loads(row['payload']), report_date=row['report_date']) for row in conn.execute(
                'SELECT * FROM creator_snapshots WHERE creator_id=? ORDER BY report_date', (creator_id,))]

    def missing_creator_channels(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('''SELECT c.creator_id, c.creator_name FROM creators c
                LEFT JOIN creator_channels cc ON cc.creator_id=c.creator_id
                WHERE cc.channel_id IS NULL ORDER BY c.rank''')]

    def message_record(self, key):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM discord_messages WHERE message_key=?', (key,)).fetchone()
            return dict(row) if row else None
