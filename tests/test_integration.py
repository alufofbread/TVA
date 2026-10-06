import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from database import Database
from delivery import MessagePublisher
from integration import IntegrationService
from test_delivery import FakeChannel


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / 'test.db')
        self.db.set_automation_channel('events', 10, 1)
        self.discord = SimpleNamespace(user=SimpleNamespace(id=1), is_ready=lambda: True)
        self.channel = FakeChannel()
        self.publisher = MessagePublisher(self.discord, self.db)
        self.publisher.channel = AsyncMock(return_value=self.channel)
        self.service = IntegrationService(self.discord, self.db, self.publisher, 's' * 40, AsyncMock())
        self.client = TestClient(TestServer(self.service.application()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    def payload(self, kind='event.created', revision=1, request_id=None):
        return dict(request_id=request_id or f'req-{revision}', type=kind, event_id='event-1', revision=revision,
                    data=dict(name='Aether Live', description='Creator gathering', date='2026-10-01',
                              starts_at='2026-10-01T18:00:00+01:00', ends_at='2026-10-01T19:00:00+01:00', url='https://example.com/events/1'))

    async def post(self, data, authorized=True):
        response = await self.client.post('/integrations/events', json=data,
                                         headers={'Authorization': 'Bearer ' + 's'*40} if authorized else {})
        return response.status, await response.json()

    async def test_create_update_delete_and_retries(self):
        self.assertEqual((await self.post(self.payload()))[0], 200)
        self.assertEqual((await self.post(self.payload()))[1]['status'], 'duplicate')
        self.assertEqual((await self.post(self.payload(request_id='another')))[1]['status'], 'duplicate')
        self.assertEqual((await self.post(self.payload('event.updated', 2)))[1]['status'], 'updated')
        self.assertEqual(len(self.channel.messages), 1)
        self.assertEqual((await self.post(self.payload('event.deleted', 3)))[1]['status'], 'deleted')
        self.assertEqual((await self.post(self.payload('event.deleted', 3)))[1]['status'], 'duplicate')
        self.channel.messages[0].delete.assert_awaited_once()
        self.assertEqual((await self.post(self.payload(request_id='old-retry')))[1]['status'], 'stale-ignored')
        self.assertEqual(len(self.channel.messages), 1)

    async def test_invalid_auth_and_payload(self):
        self.assertEqual((await self.post(self.payload(), False))[0], 401)
        invalid = self.payload()
        invalid['data']['url'] = 'javascript:alert(1)'
        self.assertEqual((await self.post(invalid))[0], 400)
        invalid = self.payload()
        invalid['data']['starts_at'] = '2026-10-01T18:00:00'
        self.assertEqual((await self.post(invalid))[0], 400)
        self.assertEqual((await self.post(self.payload('campaign.created')))[0], 400)
        self.channel.send.assert_not_awaited()

    async def test_request_and_revision_conflicts(self):
        await self.post(self.payload())
        changed = self.payload()
        changed['data']['name'] = 'Changed without revision'
        self.assertEqual((await self.post(changed))[0], 409)
        changed['request_id'] = 'different-request'
        self.assertEqual((await self.post(changed))[0], 409)

    async def test_send_timeout_reconciles_existing_discord_post(self):
        send = self.channel.send_value
        async def uncertain(**kwargs):
            await send(**kwargs)
            raise TimeoutError('Simulate connection lost after Discord accepted message')
        self.channel.send.side_effect = uncertain
        self.assertEqual((await self.post(self.payload()))[0], 503)
        self.channel.send.side_effect = send
        self.assertEqual((await self.post(self.payload()))[0], 200)
        self.assertEqual(len(self.channel.messages), 1)

    async def test_concurrent_retries_create_one_post(self):
        results = await asyncio.gather(*(self.post(self.payload()) for _ in range(4)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(len(self.channel.messages), 1)

    async def test_missing_channel_and_discord_unavailable_are_retryable(self):
        with self.db.connect() as conn:
            conn.execute('DELETE FROM automation_channels')
        self.assertEqual((await self.post(self.payload()))[0], 503)
        self.db.set_automation_channel('events', 10, 1)
        self.assertEqual((await self.post(self.payload()))[0], 200)
        self.discord.is_ready = lambda: False
        self.assertEqual((await self.post(self.payload('event.updated', 2)))[0], 503)
    async def test_restart_retains_deduplication(self):
        await self.post(self.payload())
        await self.client.close()
        self.service = IntegrationService(self.discord, Database(self.db.path), self.publisher, 's'*40, AsyncMock())
        self.client = TestClient(TestServer(self.service.application()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.assertEqual((await self.post(self.payload()))[1]['status'], 'duplicate')
        self.assertEqual((await self.post(self.payload('event.updated', 2)))[1]['status'], 'updated')
        self.assertEqual(len(self.channel.messages), 1)

    async def test_oversize_and_malformed_json(self):
        headers = {'Authorization': 'Bearer ' + 's'*40, 'Content-Type': 'application/json'}
        response = await self.client.post('/integrations/events', data='{"x":"' + 'a'*40000 + '"}', headers=headers)
        self.assertEqual(response.status, 413)
        response = await self.client.post('/integrations/events', data='{broken', headers=headers)
        self.assertEqual(response.status, 400)
        self.channel.send.assert_not_awaited()

    async def test_conflicting_revision_after_uncertain_send_is_rejected(self):
        send = self.channel.send_value
        async def uncertain(**kwargs):
            await send(**kwargs)
            raise TimeoutError()
        self.channel.send.side_effect = uncertain
        self.assertEqual((await self.post(self.payload()))[0], 503)
        changed = self.payload(request_id='different-request')
        changed['data']['name'] = 'Conflicting'
        self.assertEqual((await self.post(changed))[0], 409)
        self.channel.send.side_effect = send
        self.assertEqual((await self.post(self.payload()))[0], 200)
        self.assertEqual(len(self.channel.messages), 1)

    async def test_unknown_delete_prevents_late_create(self):
        self.assertEqual((await self.post(self.payload('event.deleted', 3)))[1]['status'], 'deleted')
        self.assertEqual((await self.post(self.payload()))[1]['status'], 'stale-ignored')
        self.channel.send.assert_not_awaited()
