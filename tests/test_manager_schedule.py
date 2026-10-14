import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from database import Database
from manager_reports import ManagerReports


class ManagerScheduleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Database(Path(temporary.name) / 'db.sqlite')
        self.report = ManagerReports(SimpleNamespace(database=self.db))
        with self.db.connect() as conn:
            conn.execute('CREATE TABLE website_report_outbox(import_id INTEGER PRIMARY KEY, delivered INTEGER)')

    def add_report(self, day, delivered=1):
        with self.db.connect() as conn:
            row = conn.execute("""INSERT INTO import_runs(report_date,imported_at,filename,snapshot_hash,creator_count,delivery_status)
                VALUES (?,?,'report.csv',?,1,'complete')""", (day, day, day))
            conn.execute('INSERT INTO website_report_outbox VALUES (?,?)', (row.lastrowid, delivered))

    async def test_daily_report_posts_without_waiting_for_month_end(self):
        self.add_report('2026-10-14')
        with patch.object(self.report, 'publish', new=AsyncMock(return_value=1)) as publish:
            self.assertEqual(await self.report.publish_due(), 1)
            self.assertEqual(await self.report.publish_due(), 0)
            publish.assert_awaited_once_with(report_date='2026-10-14', daily=True)
        restarted = ManagerReports(SimpleNamespace(database=self.db))
        with patch.object(restarted, 'publish', new=AsyncMock()) as publish:
            self.assertEqual(await restarted.publish_due(), 0)
            publish.assert_not_awaited()

    async def test_waits_for_website_sync_and_next_day_gets_a_new_summary(self):
        self.add_report('2026-10-14', delivered=0)
        with patch.object(self.report, 'publish', new=AsyncMock(return_value=1)) as publish:
            self.assertEqual(await self.report.publish_due(), 0)
            with self.db.connect() as conn:
                conn.execute('UPDATE website_report_outbox SET delivered=1')
            self.assertEqual(await self.report.publish_due(), 1)
            self.add_report('2026-10-15')
            self.assertEqual(await self.report.publish_due(), 1)
            self.assertEqual(publish.await_count, 2)
            publish.assert_awaited_with(report_date='2026-10-15', daily=True)

    async def test_failed_delivery_retries(self):
        self.add_report('2026-10-14')
        with patch.object(self.report, 'publish', new=AsyncMock(side_effect=[RuntimeError('offline'), 1])):
            with self.assertRaises(RuntimeError):
                await self.report.publish_due()
            self.assertEqual(await self.report.publish_due(), 1)

    def test_targets_are_scoped_to_month_and_survive_restart(self):
        self.db.set_team_diamonds('2026-10', 'target', 1354619, 123)
        restarted = Database(self.db.path)
        self.assertEqual(restarted.team_diamonds('2026-10')['target'], 1354619)
        self.assertEqual(restarted.team_diamonds('2026-11'), {})
        for month, amount in [('2026-13', 1), ('2026-1', 1), ('2026-10', -1)]:
            with self.assertRaises(ValueError):
                restarted.set_team_diamonds(month, 'target', amount, 123)
