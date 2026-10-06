"""Persistent Discord messages with recovery after uncertain send outcomes."""
import asyncio
import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

import discord
from automation_store import utcnow


class MessagePublisher:
    def __init__(self, client, database):
        self.client, self.database = client, database
        self.lock = asyncio.Lock()

    async def channel(self, channel_id):
        channel = self.client.get_channel(channel_id) or await self.client.fetch_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError('Configured destination must be a server text channel')
        from config import GUILD_ID
        if str(channel.guild.id) != str(GUILD_ID):
            raise ValueError('Configured destination belongs to another server')
        return channel

    async def _recover(self, record):
        channel = await self.channel(record['channel_id'])
        if record['message_id']:
            try:
                return await channel.fetch_message(record['message_id'])
            except discord.NotFound:
                return None
        if record['status'] == 'deleted':
            return None
        # A send may have reached Discord just before a crash/timeout. Scan all
        # messages since the durable intent, not an arbitrary last-N window.
        after = datetime.fromisoformat(record['started_at']) - timedelta(seconds=5)
        async for message in channel.history(limit=None, after=after):
            if message.author.id != self.client.user.id:
                continue
            if record['marker'] in message.content or any(record['marker'] in (e.footer.text or '') for e in message.embeds):
                return message
        return None

    async def upsert(self, key, channel_id, *, content='', embed=None, view=None, files_factory=None):
        async with self.lock:
            record = self.database.message_record(key)
            message = await self._recover(record) if record else None
            if record and record['channel_id'] != channel_id and message:
                await message.delete()
                message = None
            if not record or record['channel_id'] != channel_id or record['status'] == 'deleted' or (record['message_id'] and message is None):
                marker = 'ACN:' + hashlib.sha256((key + uuid4().hex).encode()).hexdigest()[:20]
                now = utcnow()
                with self.database.connect() as conn:
                    conn.execute('''INSERT OR REPLACE INTO discord_messages
                        (message_key, channel_id, marker, started_at, updated_at) VALUES (?, ?, ?, ?, ?)''',
                        (key, channel_id, marker, now, now))
                record = self.database.message_record(key)
            if embed:
                embed = embed.copy()
                embed.set_footer(text=f'Aether Creator Network | {record["marker"]}')
            else:
                content = f'{content}\n-# {record["marker"]}'
            files = files_factory() if files_factory else []
            try:
                kwargs = dict(content=content or None, embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                if message:
                    message = await message.edit(**kwargs, attachments=files)
                else:
                    channel = await self.channel(channel_id)
                    message = await channel.send(**kwargs, files=files, nonce=record['marker'])
                with self.database.connect() as conn:
                    conn.execute("UPDATE discord_messages SET message_id=?, status='sent', error=NULL, updated_at=? WHERE message_key=?",
                                 (message.id, utcnow(), key))
                return message
            except Exception as exc:
                with self.database.connect() as conn:
                    conn.execute("UPDATE discord_messages SET error=?, updated_at=? WHERE message_key=?", (type(exc).__name__, utcnow(), key))
                raise
            finally:
                for file in files:
                    file.close()

    async def delete(self, key):
        async with self.lock:
            record = self.database.message_record(key)
            if not record:
                return
            message = await self._recover(record)
            if message:
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
            with self.database.connect() as conn:
                conn.execute("UPDATE discord_messages SET status='deleted', message_id=NULL, updated_at=?, error=NULL WHERE message_key=?", (utcnow(), key))
