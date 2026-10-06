import sqlite3
import tempfile
import unittest
from pathlib import Path
from database import Database


class MigrationTests(unittest.TestCase):
    def test_legacy_channels_migrate_once_monthly_preferred(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'db.sqlite'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE leaderboard_channels (channel_type TEXT PRIMARY KEY, channel_id INTEGER, updated_by INTEGER, updated_at TEXT)')
                conn.executemany('INSERT INTO leaderboard_channels VALUES (?, ?, 9, ?)', [('daily', 11, 'old'), ('monthly', 22, 'old')])
            conn.close()
            db = Database(path)
            self.assertEqual(db.automation_channels()['leaderboard'], 22)
            db.set_automation_channel('leaderboard', 33, 9)
            self.assertEqual(Database(path).automation_channels()['leaderboard'], 33)
            self.assertEqual(len(db.get_leaderboard_channels()), 2)

    def test_shared_transaction_rolls_back_existing_methods(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / 'db.sqlite')
            with self.assertRaises(RuntimeError):
                with db.transaction():
                    db.set_creator_channel('alice', 11, 9)
                    db.set_automation_channel('events', 22, 9)
                    raise RuntimeError('fail')
            self.assertEqual(db.automation_channels(), {})
            with db.connect() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM creator_channels').fetchone()[0], 0)
