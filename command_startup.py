"""Guild command registration only; no analytics or ticket code."""
import asyncio

EXPECTED_GUILD_ID = 1468015338221207656


async def register_commands(client, guild, timeout=30):
    if guild.id != EXPECTED_GUILD_ID:
        raise RuntimeError(f'DISCORD_GUILD_ID must be {EXPECTED_GUILD_ID}; got {guild.id}. Refusing to register in the wrong server.')
    local=client.tree.get_commands()
    print(f'Loaded commands locally: {len(local)} {[c.name for c in local]}',flush=True)
    guild_only=client.tree.get_commands(guild=guild)
    print(f'Guild commands before copying: {len(guild_only)} {[c.name for c in guild_only]}',flush=True)
    # This bot defines global commands with decorators; copy them to the target
    # guild before guild sync. It has one tree and no cogs/extensions to load.
    client.tree.copy_global_to(guild=guild)
    expected={c.name for c in client.tree.get_commands(guild=guild)}
    if not expected:raise RuntimeError('No commands loaded; refusing to sync an empty command tree.')
    url=f'https://discord.com/oauth2/authorize?client_id={client.application_id}&scope=bot%20applications.commands&guild_id={guild.id}&disable_guild_select=true'
    print(f'Registering application {client.application_id} in guild {guild.id}. Install/reauthorize with bot + applications.commands: {url}',flush=True)
    try:
        synced=await asyncio.wait_for(client.tree.sync(guild=guild),timeout=timeout)
        names=[c.name for c in synced]
        print(f'Synced {len(synced)} commands to guild {guild.id}: {names}',flush=True)
        if set(names)!=expected:raise RuntimeError('Discord returned a different command list than the loaded guild tree.')
        remote=await asyncio.wait_for(client.tree.fetch_commands(guild=guild),timeout=timeout)
        names=[c.name for c in remote]
        print(f'Verified commands registered on Discord: {len(remote)} {names}',flush=True)
        if set(names)!=expected:raise RuntimeError('Discord registration verification failed: missing or unexpected commands.')
    except Exception:
        print(f'Command registration FAILED for guild {guild.id}. Check the token application, guild membership and applications.commands installation scope. Reauthorize: {url}',flush=True)
        raise
