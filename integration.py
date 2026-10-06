"""Authenticated, versioned server-to-server event receiver.

Each resource handler owns its Discord rendering; the receiver owns auth,
validation, durable request receipts, ordering and retries.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import date, datetime
from urllib.parse import urlsplit

import discord
from aiohttp import web

from automation_store import utcnow


class PayloadError(ValueError):
    pass


class Conflict(ValueError):
    pass


def short_text(value, name, limit, required=False):
    if value is None and not required:
        return ''
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise PayloadError(f'{name} must be a string of 1-{limit} characters' if required else f'Invalid {name}')
    return value.strip()


def validate_event(payload):
    if not isinstance(payload, dict):
        raise PayloadError('Body must be a JSON object')
    result = {}
    for field in ('request_id', 'event_id'):
        value = short_text(payload.get(field), field, 100, True)
        if not re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
            raise PayloadError(f'Invalid {field}')
        result[field] = value
    result['type'] = short_text(payload.get('type'), 'type', 80, True)
    revision = payload.get('revision')
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise PayloadError('revision must be a positive integer')
    result['revision'] = revision
    if result['type'] == 'event.deleted':
        result['data'] = {}
        return result
    data = payload.get('data')
    if not isinstance(data, dict):
        raise PayloadError('data must be an object')
    clean = {'name': short_text(data.get('name'), 'name', 200, True),
             'description': short_text(data.get('description'), 'description', 3000)}
    for key in ('date', 'starts_at', 'ends_at'):
        value = short_text(data.get(key), key, 40)
        if value:
            try:
                if key == 'date':
                    date.fromisoformat(value)
                elif datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() is None:
                    raise ValueError('Timezone required')
            except ValueError as exc:
                raise PayloadError(f'{key} must be ISO formatted; timestamps must include a timezone') from exc
        clean[key] = value
    if not clean['date'] and not clean['starts_at']:
        raise PayloadError('Provide date or starts_at')
    if clean['ends_at'] and not clean['starts_at']:
        raise PayloadError('ends_at requires starts_at')
    if clean['ends_at'] and datetime.fromisoformat(clean['ends_at'].replace('Z','+00:00')) <= datetime.fromisoformat(clean['starts_at'].replace('Z','+00:00')):
        raise PayloadError('ends_at must follow starts_at')
    for key in ('image_url', 'url'):
        value = short_text(data.get(key), key, 1000)
        if value:
            parsed = urlsplit(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise PayloadError(f'{key} must be an HTTPS URL without credentials')
        clean[key] = value
    result['data'] = clean
    return result


def event_embed(data):
    embed = discord.Embed(title=data['name'], description=data['description'] or None, color=0x257BFF)
    if data['date']:
        embed.add_field(name='Date', value=data['date'])
    for key, label in (('starts_at', 'Starts'), ('ends_at', 'Ends')):
        if data[key]:
            stamp = int(datetime.fromisoformat(data[key].replace('Z','+00:00')).timestamp())
            embed.add_field(name=label, value=f'<t:{stamp}:F>', inline=False)
    if data['image_url']:
        embed.set_image(url=data['image_url'])
    view = None
    if data['url']:
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label='View on Aether', url=data['url']))
    return embed, view


class IntegrationService:
    def __init__(self, client, database, publisher, secret, logger):
        if len(secret) < 32:
            raise ValueError('AETHER_INTEGRATION_SECRET must contain at least 32 characters')
        self.client, self.database, self.publisher = client, database, publisher
        self.secret, self.logger = secret, logger
        self.lock = asyncio.Lock()
        self.runner = None
        self.running = False
        self.last_error = None
        self._last_invalid_log = 0
        # Future resource types register their validator/handler here.
        self.handlers = {kind: (validate_event, self.handle_event) for kind in ('event.created', 'event.updated', 'event.deleted')}

    def application(self):
        app = web.Application(client_max_size=32 * 1024)
        app.router.add_post('/integrations/events', self.receive)
        app.router.add_get('/health', self.health)
        return app

    async def start(self, host, port):
        self.runner = web.AppRunner(self.application(), access_log=None)
        await self.runner.setup()
        try:
            await web.TCPSite(self.runner, host, port).start()
        except Exception:
            await self.runner.cleanup()
            raise
        self.running = True

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
        self.running = False

    async def health(self, request):
        ready = self.client.is_ready()
        return web.json_response({'status': 'ready' if ready else 'discord-unavailable'}, status=200 if ready else 503)

    async def invalid(self, reason):
        self.last_error = f'{utcnow()}: {reason}'
        logging.warning('Integration request rejected: %s', reason)
        # Do not let unauthenticated traffic flood the Discord admin channel.
        if time.monotonic() - self._last_invalid_log > 60:
            self._last_invalid_log = time.monotonic()
            await self.logger(f'Aether integration rejected request: {reason}')

    async def receive(self, request):
        expected = ('Bearer ' + self.secret).encode('utf-8')
        if not hmac.compare_digest(request.headers.get('Authorization', '').encode('utf-8'), expected):
            await self.invalid('Unauthorized request')
            return web.json_response({'error': 'Unauthorized'}, status=401)
        if not self.client.is_ready():
            return web.json_response({'error': 'Discord not ready; retry later'}, status=503)
        try:
            if request.content_type != 'application/json':
                raise PayloadError('Content-Type must be application/json')
            raw = await request.json()
            if not isinstance(raw, dict) or not isinstance(raw.get('type'), str) or raw['type'] not in self.handlers:
                raise PayloadError('Unsupported event type')
            validator, handler = self.handlers[raw['type']]
            payload = validator(raw)
        except (ValueError, UnicodeError, web.HTTPRequestEntityTooLarge) as exc:
            reason = 'Payload too large' if isinstance(exc, web.HTTPRequestEntityTooLarge) else str(exc)
            await self.invalid(reason)
            return web.json_response({'error': reason}, status=413 if isinstance(exc, web.HTTPRequestEntityTooLarge) else 400)
        async with self.lock:
            try:
                outcome = await self.process(payload, handler)
                return web.json_response({'status': outcome})
            except Conflict as exc:
                await self.invalid(str(exc))
                return web.json_response({'error': str(exc)}, status=409)
            except Exception as exc:
                logging.exception('Integration delivery failed')
                self.last_error = f'{utcnow()}: {type(exc).__name__}'
                await self.logger(f'Aether integration {payload["request_id"]} failed ({type(exc).__name__}); backend may retry.')
                return web.json_response({'error': 'Delivery failed; retry the same request'}, status=503)

    async def process(self, payload, handler):
        content = {k: v for k,v in payload.items() if k != 'request_id'}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        request_id = payload['request_id']
        with self.database.connect() as conn:
            receipt = conn.execute('SELECT * FROM integration_requests WHERE request_id=?', (request_id,)).fetchone()
            if receipt:
                if receipt['payload_hash'] != fingerprint:
                    raise Conflict('request_id was already used for a different payload')
                if receipt['status'] == 'complete':
                    return 'duplicate'
            else:
                conflicting = conn.execute("SELECT 1 FROM integration_requests WHERE resource_id=? AND revision=? AND event_type LIKE 'event.%' AND payload_hash!=? AND status!='rejected'",
                                           (payload['event_id'], payload['revision'], fingerprint)).fetchone()
                if conflicting:
                    raise Conflict('Revision was already used for different event content')
                now = utcnow()
                conn.execute('''INSERT INTO integration_requests VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL)''',
                             (request_id, fingerprint, payload['type'], payload['event_id'], payload['revision'], now, now))
        await self.logger(f'Aether website event received: {payload["type"]} ({payload["event_id"]}, revision {payload["revision"]})')
        try:
            outcome = await handler(payload, fingerprint)
        except Exception as exc:
            with self.database.connect() as conn:
                conn.execute("UPDATE integration_requests SET status=?, updated_at=?, error=? WHERE request_id=?", ("rejected" if isinstance(exc, Conflict) else "failed", utcnow(), str(exc) if isinstance(exc, Conflict) else type(exc).__name__, request_id))
            raise
        with self.database.connect() as conn:
            conn.execute("UPDATE integration_requests SET status='complete', updated_at=?, error=NULL WHERE request_id=?", (utcnow(), request_id))
        await self.logger(f'Aether website {payload["type"]}: {outcome} ({payload["event_id"]})')
        return outcome

    async def handle_event(self, payload, fingerprint):
        event_id, revision = payload['event_id'], payload['revision']
        with self.database.connect() as conn:
            previous = conn.execute('SELECT * FROM website_events WHERE event_id=?', (event_id,)).fetchone()
            newer = conn.execute("SELECT 1 FROM integration_requests WHERE resource_id=? AND event_type LIKE 'event.%' AND revision>? AND status IN ('pending','failed','complete')", (event_id, revision)).fetchone()
        if newer or (previous and previous['revision'] > revision):
            return 'stale-ignored'
        if previous and previous['revision'] == revision:
            if previous['payload_hash'] != fingerprint:
                raise Conflict('Revision was already used for different event content')
            return 'duplicate'
        key = 'website:event:' + event_id
        deleting = payload['type'] == 'event.deleted'
        channel_id, message_id = None, None
        if deleting:
            await self.publisher.delete(key)
            outcome = 'deleted'
        else:
            record = self.database.message_record(key)
            channel_id = (previous['channel_id'] if previous and not previous['deleted'] else None) or (record['channel_id'] if record and record['status'] != 'deleted' else None) or self.database.automation_channels().get('events')
            if not channel_id:
                raise RuntimeError('Events channel is not configured')
            embed, view = event_embed(payload['data'])
            message = await self.publisher.upsert(key, channel_id, embed=embed, view=view)
            message_id = message.id
            outcome = 'updated' if previous and not previous['deleted'] else 'created'
        with self.database.connect() as conn:
            conn.execute('''INSERT INTO website_events VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET revision=excluded.revision,
                payload_hash=excluded.payload_hash, deleted=excluded.deleted,
                channel_id=excluded.channel_id, message_id=excluded.message_id, updated_at=excluded.updated_at''',
                (event_id, revision, fingerprint, int(deleting), channel_id, message_id, utcnow()))
        return outcome
