import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import bot


class ManagerCommandTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        return SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))

    async def test_manual_send_uses_latest_report_and_daily_destination(self):
        interaction = self.interaction()
        with patch.object(bot.bot, 'automation_lock', asyncio.Lock()), patch.object(bot.bot.database, 'latest_import', return_value={'report_date': '2026-10-14', 'delivery_status': 'manual'}), patch.object(bot.bot.manager_reports, 'publish', new=AsyncMock(return_value=1)) as publish:
            await bot.manager_summary_command.callback(interaction)
        publish.assert_awaited_once_with(report_date='2026-10-14', daily=True, manual=True)
        self.assertIn('1554887728183640158', interaction.followup.send.call_args.args[0])

    async def test_no_report_explains_import_is_needed(self):
        interaction = self.interaction()
        with patch.object(bot.bot, 'automation_lock', asyncio.Lock()), patch.object(bot.bot.database, 'latest_import', return_value=None), patch.object(bot.bot.manager_reports, 'publish', new=AsyncMock()) as publish:
            await bot.manager_summary_command.callback(interaction)
        publish.assert_not_awaited()
        self.assertIn('Import a report first', interaction.followup.send.call_args.args[0])

    async def test_busy_pipeline_does_not_publish(self):
        interaction = self.interaction()
        lock = asyncio.Lock()
        async with lock:
            with patch.object(bot.bot, 'automation_lock', lock), patch.object(bot.bot.manager_reports, 'publish', new=AsyncMock()) as publish:
                await bot.manager_summary_command.callback(interaction)
        publish.assert_not_awaited()
        self.assertIn('being processed', interaction.followup.send.call_args.args[0])
