import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import Database
from delivery import MessagePublisher


class FakeMessage:
    def __init__(self, message_id, content='', embed=None):
        self.id, self.content = message_id, content or ''
        self.embeds = [embed] if embed else []
        self.author = SimpleNamespace(id=1)
        self.edit = AsyncMock(side_effect=self.edit_value)
        self.delete = AsyncMock()

    async def edit_value(self, **kwargs):
        self.content = kwargs.get('content') or ''
        self.embeds = [kwargs['embed']] if kwargs.get('embed') else []
        return self


class FakeChannel:
    id = 10
    def __init__(self):
        self.messages = []
        self.send = AsyncMock(side_effect=self.send_value)
        self.fetch_message = AsyncMock(side_effect=self.fetch_value)

    async def send_value(self, **kwargs):
        message = FakeMessage(len(self.messages) + 100, kwargs.get('content'), kwargs.get('embed'))
        self.messages.append(message)
        return message

    async def fetch_value(self, message_id):
        return next(m for m in self.messages if m.id == message_id)

    async def history(self, **kwargs):
        for message in self.messages:
            yield message


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / 'test.db')
        self.channel = FakeChannel()
        self.publisher = MessagePublisher(SimpleNamespace(user=SimpleNamespace(id=1)), self.db)
        self.publisher.channel = AsyncMock(return_value=self.channel)

    async def test_repeated_delivery_edits(self):
        first = await self.publisher.upsert('leaderboard', 10, content='first')
        second = await self.publisher.upsert('leaderboard', 10, content='second')
        self.assertEqual(first.id, second.id)
        self.channel.send.assert_awaited_once()
        first.edit.assert_awaited_once()

    async def test_recover_send_when_message_id_was_not_saved(self):
        first = await self.publisher.upsert('event:abc', 10, content='first')
        with self.db.connect() as conn:
            conn.execute("UPDATE discord_messages SET message_id=NULL, status='pending'")
        second = await self.publisher.upsert('event:abc', 10, content='retry')
        self.assertEqual(first.id, second.id)
        self.channel.send.assert_awaited_once()

    async def test_delete_idempotent(self):
        first = await self.publisher.upsert('event:abc', 10, content='first')
        await self.publisher.delete('event:abc')
        await self.publisher.delete('event:abc')
        first.delete.assert_awaited_once()
        self.assertEqual(self.db.message_record('event:abc')['status'], 'deleted')

    async def test_creator_render_failure_does_not_stop_next_creator(self):
        import bot
        assignments = [SimpleNamespace(creator_id=v, creator_name=v, channel_id=10) for v in ('bad','good')]
        with patch.object(bot.bot.database, 'get_creator_channels', return_value=assignments), patch.object(bot.bot.publisher, 'channel', new=AsyncMock(return_value=self.channel)), patch.object(bot, 'send_creator_dashboard', new=AsyncMock(side_effect=[RuntimeError('render'), None])) as send:
            count, failures = await bot.send_auto_stats_to_creator_channels()
        self.assertEqual(count, 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(send.await_count, 2)
    async def test_permissions_failure_does_not_create_replacement(self):
        import discord
        first = await self.publisher.upsert('leaderboard', 10, content='first')
        self.channel.fetch_message.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'denied')
        with self.assertRaises(discord.Forbidden):
            await self.publisher.upsert('leaderboard', 10, content='retry')
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.db.message_record('leaderboard')['message_id'], first.id)

    async def test_deleted_message_is_replaced(self):
        import discord
        first = await self.publisher.upsert('leaderboard', 10, content='first')
        first_marker = self.db.message_record('leaderboard')['marker']
        self.channel.fetch_message.side_effect = discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), 'gone')
        replacement = await self.publisher.upsert('leaderboard', 10, content='retry')
        self.assertNotEqual(first.id, replacement.id)
        self.assertNotEqual(first_marker, self.db.message_record('leaderboard')['marker'])

    async def test_channel_change_removes_previous_message(self):
        first = await self.publisher.upsert('leaderboard', 10, content='first')
        await self.publisher.upsert('leaderboard', 20, content='moved')
        first.delete.assert_awaited_once()
        self.assertEqual(self.db.message_record('leaderboard')['channel_id'], 20)
