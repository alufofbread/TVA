import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import Database
from delivery import MessagePublisher
from test_delivery import FakeChannel


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import bot
        self.module = bot
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(self.root / 'test.db')
        self.db.set_creator_channel('alice', 10, 1)
        self.db.set_automation_channel('leaderboard', 10, 1)
        self.channel = FakeChannel()
        self.publisher = MessagePublisher(SimpleNamespace(user=SimpleNamespace(id=1)), self.db)
        self.publisher.channel = AsyncMock(return_value=self.channel)
        patches = [patch.object(bot.bot, 'database', self.db), patch.object(bot.bot, 'publisher', self.publisher),
                   patch.object(bot.bot, 'automation_lock', asyncio.Lock()), patch.object(bot, 'DATA_DIR', self.root),
                   patch.object(bot, 'UPLOAD_DIR', self.root), patch.object(bot, 'admin_log', new=AsyncMock()),
                   patch('importer.cache_avatar', return_value=None)]
        for mock in patches:
            mock.start()
            self.addCleanup(mock.stop)
        self.interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        async def save(path):
            path.write_text('Creator ID,Creator,Diamonds,Hours,Days,Battles,Data period\nalice,Alice,120000,30,12,10,2026-09-12\nbob,Bob,2000,2,1,2,2026-09-12\n')
        self.attachment = SimpleNamespace(filename='report.csv', size=200, save=AsyncMock(side_effect=save))

    async def test_full_import_real_renders_and_duplicate_delivery(self):
        await self.module.process_report(self.interaction, self.attachment)
        summary = json.loads(self.db.latest_import()['summary'])
        self.assertEqual(summary['channels_updated'], 1)
        self.assertEqual(summary['unmapped'], ['Bob'])
        self.assertTrue(summary['leaderboard_updated'])
        self.assertEqual(self.db.latest_import()['report_date'], '2026-09-12')
        self.assertEqual(len(self.channel.messages), 2)
        self.assertEqual(len(list(self.root.glob('acn-*.png'))), 3)
        await self.module.process_report(self.interaction, self.attachment)
        self.assertEqual(len(self.channel.messages), 2)
        self.assertEqual(len(self.db.creator_history('alice')), 1)
        self.module.admin_log.assert_awaited()

    async def test_busy_import_does_not_save_or_mutate(self):
        async with self.module.bot.automation_lock:
            await self.module.process_report(self.interaction, self.attachment)
        self.attachment.save.assert_not_awaited()
        self.assertIsNone(self.db.latest_import())

    async def test_failed_creator_still_updates_leaderboard(self):
        with patch.object(self.module, 'render_creator_dashboard_files', new=AsyncMock(side_effect=RuntimeError('render'))):
            await self.module.process_report(self.interaction, self.attachment)
        summary = json.loads(self.db.latest_import()['summary'])
        self.assertTrue(summary['leaderboard_updated'])
        self.assertEqual(self.db.latest_import()['delivery_status'], 'partial')

    async def test_non_auto_keeps_history_without_discord_delivery(self):
        await self.module.process_report(self.interaction, self.attachment, automatic=False)
        self.channel.send.assert_not_awaited()
        self.assertEqual(len(self.db.creator_history('alice')), 1)
        self.assertEqual(self.db.latest_import()['delivery_status'], 'manual')
