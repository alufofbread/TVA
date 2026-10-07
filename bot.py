from __future__ import annotations

import asyncio
import logging
import json
import hashlib
import re
from datetime import date
from pathlib import Path
from uuid import uuid4

import discord
from discord import app_commands

from avatars import cache_avatar_bytes
from config import BOT_TOKEN, DATABASE_PATH, DATA_DIR, ENV_PATH, GUILD_ID, UPLOAD_DIR, ensure_directories
from dashboard.creator_stats import render_creator_stats
from dashboard.leaderboard import render_leaderboard
from dashboard.referrals import render_all_referrals
from dashboard.trends import render_creator_trends, load_creator_daily_trends
from database import Database
from importer import ImportErrorWithContext, import_spreadsheet
from config import CHANNEL_PURPOSES, MAX_REPORT_BYTES
from delivery import MessagePublisher
from automation_store import utcnow

COMMAND_SYNC_TIMEOUT_SECONDS = 30
BOT_CONTROLLER_ROLE_NAME = "bot controller"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)


def get_required_bot_token() -> str:
    if not BOT_TOKEN or BOT_TOKEN == "your-bot-token":
        raise RuntimeError(f"DISCORD_TOKEN is not set. Add it to {ENV_PATH}.")
    return BOT_TOKEN


def get_required_guild() -> discord.Object:
    if not GUILD_ID or GUILD_ID == "your-server-id":
        raise RuntimeError(f"DISCORD_GUILD_ID is not set. Add it to {ENV_PATH}.")
    try:
        return discord.Object(id=int(GUILD_ID))
    except ValueError as exc:
        raise RuntimeError("DISCORD_GUILD_ID must be a numeric Discord server ID.") from exc


def can_use_bot(user: discord.User | discord.Member) -> bool:
    if not isinstance(user, discord.Member):
        return False

    if user.guild_permissions.administrator:
        return True

    return any(role.name.lower() == BOT_CONTROLLER_ROLE_NAME for role in user.roles)


class BotControllerRequired(app_commands.CheckFailure):
    pass


async def bot_controller_check(interaction: discord.Interaction) -> bool:
    if can_use_bot(interaction.user):
        return True

    raise BotControllerRequired()


async def send_app_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class AetherCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.guild_id) != str(GUILD_ID):
            await send_app_error(interaction, 'This bot is configured for a different server.')
            return False
        if can_use_bot(interaction.user):
            return True

        await send_app_error(interaction, f"You need the {BOT_CONTROLLER_ROLE_NAME} role to use this bot.")
        return False


class AetherBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = AetherCommandTree(self)
        self.database = Database()
        self.automation_lock = asyncio.Lock()
        self.publisher = MessagePublisher(self, self.database)

    async def setup_hook(self) -> None:
        from command_startup import register_commands
        await register_commands(self, get_required_guild(), COMMAND_SYNC_TIMEOUT_SECONDS)
        from website_sync import worker
        self.website_sync_task = asyncio.create_task(worker(self.database))
        from onboarding import worker as onboarding_worker
        self.onboarding_task = asyncio.create_task(onboarding_worker(self))
        from config import INTEGRATION_SECRET, INTEGRATION_HOST, INTEGRATION_PORT
        from integration import IntegrationService
        self.integration = None
        if INTEGRATION_SECRET:
            self.integration = IntegrationService(self, self.database, self.publisher, INTEGRATION_SECRET, admin_log)
            await self.integration.start(INTEGRATION_HOST, INTEGRATION_PORT)

    async def close(self):
        onboarding_task = getattr(self, 'onboarding_task', None)
        if onboarding_task:
            onboarding_task.cancel()
            try:
                await onboarding_task
            except asyncio.CancelledError:
                pass
        task = getattr(self, 'website_sync_task', None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if getattr(self, 'integration', None):
            await self.integration.close()
        await super().close()

bot = AetherBot()


def creator_autocomplete(current: str) -> list[app_commands.Choice[str]]:
    needle = current.strip().lower()
    creators = bot.database.get_creators()
    matches = [
        creator
        for creator in creators
        if not needle
        or needle in creator.creator_name.lower()
        or needle in creator.creator_id.lower()
    ]
    return [
        app_commands.Choice(name=f"{creator.creator_name} (@{creator.creator_id})"[:100], value=creator.creator_id)
        for creator in matches[:25]
    ]


async def render_creator_dashboard_files(creator_id: str) -> tuple[Path, Path, str] | None:
    creator = bot.database.find_creator(creator_id)
    if creator is None:
        return None

    creators = bot.database.get_creators()
    safe_id = hashlib.sha256(creator.creator_id.encode()).hexdigest()[:20]
    output_path = DATA_DIR / f"acn-stats-{safe_id}.png"
    trends_path = DATA_DIR / f"acn-trends-{safe_id}.png"
    referrals = bot.database.get_referrals_for_referrer(creator.creator_id)
    points = await asyncio.to_thread(load_creator_daily_trends, creator, database=bot.database)
    await asyncio.to_thread(render_creator_stats, creator, len(creators), output_path, referrals, points)
    await asyncio.to_thread(render_creator_trends, creator, trends_path, points)
    return output_path, trends_path, creator.creator_name


async def send_creator_dashboard(channel: discord.abc.Messageable, creator_id: str) -> str | None:
    creator = bot.database.find_creator(creator_id)
    if creator is None:
        return 'creator missing from the latest import'
    key = f'creator:{creator_id}'
    if creator.hours <= 0:
        await bot.publisher.upsert(key, channel.id, content=f'Hi {creator.creator_name}! No LIVE hours reported this month yet.')
        return None
    rendered = await render_creator_dashboard_files(creator_id)
    if rendered is None:
        return 'creator missing from the latest import'
    output_path, trends_path, creator_name = rendered
    await bot.publisher.upsert(key, channel.id, content=f'Latest Aether stats for {creator_name}',
        files_factory=lambda: [discord.File(output_path, filename='acn-stats.png'), discord.File(trends_path, filename='acn-trends.png')])
    return None


async def send_auto_stats_to_creator_channels(max_channels: int | None = None) -> tuple[int, list[str]]:
    assignments = bot.database.get_creator_channels()
    if not assignments:
        return 0, []

    sent_count = 0
    failures: list[str] = []
    selected_assignments = assignments[:max_channels] if max_channels is not None else assignments
    for assignment in selected_assignments:
        try:
            channel = await bot.publisher.channel(assignment.channel_id)
            error = await send_creator_dashboard(channel, assignment.creator_id)
            if error:
                failures.append(f'{assignment.creator_name}: {error}')
                continue
            sent_count += 1
        except Exception as exc:
            logging.exception('Creator dashboard failed: %s', assignment.creator_id)
            failures.append(f'{assignment.creator_name}: render/delivery failed ({type(exc).__name__})')

    if max_channels is not None and len(assignments) > max_channels:
        failures.append(f"Skipped {len(assignments) - max_channels} extra channel assignments.")

    return sent_count, failures


async def render_leaderboard_file() -> Path | None:
    creators = bot.database.get_creators()
    if not creators:
        return None
    output_path = DATA_DIR / 'acn-global-leaderboard.png'
    latest = bot.database.latest_import()
    report_date = date.fromisoformat(latest['report_date']) if latest else None
    await asyncio.to_thread(render_leaderboard, creators, bot.database.get_summary(), output_path, report_date)
    return output_path


async def send_saved_leaderboards() -> tuple[int, list[str]]:
    channel_id = bot.database.automation_channels().get('leaderboard')
    if not channel_id:
        return 0, ['Global leaderboard channel is not configured.']
    try:
        path = await render_leaderboard_file()
        if path is None:
            return 0, ['No creator data imported.']
        await bot.publisher.upsert('leaderboard', channel_id, content='Aether global leaderboard | Month to date',
                                   files_factory=lambda: [discord.File(path, filename='acn-leaderboard.png')])
        return 1, []
    except Exception as exc:
        logging.exception('Global leaderboard update failed')
        return 0, [f'Global leaderboard failed ({type(exc).__name__}).']


async def admin_log(message):
    logging.info('%s', message)
    channel_id = bot.database.automation_channels().get('logs')
    if not channel_id:
        return
    try:
        channel = await bot.publisher.channel(channel_id)
        for offset in range(0, len(message), 1900):
            await channel.send(message[offset:offset + 1900], allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        logging.exception('Could not deliver admin log')


async def publish_achievements(import_id):
    channel_id = bot.database.automation_channels().get('wins')
    with bot.database.connect() as conn:
        rows = conn.execute('SELECT * FROM achievements WHERE import_id=? AND publish=1 AND announced_at IS NULL ORDER BY achievement_key', (import_id,)).fetchall()
    if not rows:
        return 0
    if not channel_id:
        raise RuntimeError('Wins channel is not configured for enabled announcements')
    # One digest per import, split only to meet Discord's embed size limit.
    chunks, lines = [], []
    for row in rows:
        line = row['description']
        if sum(len(v) + 1 for v in lines) + len(line) > 3500:
            chunks.append(lines)
            lines = []
        lines.append(line)
    if lines:
        chunks.append(lines)
    for index, lines in enumerate(chunks):
        await bot.publisher.upsert(f'achievements:{import_id}:{index}', channel_id,
            embed=discord.Embed(title='Aether creator wins', description='\n'.join(lines), color=0x257BFF))
    with bot.database.connect() as conn:
        conn.execute('UPDATE achievements SET announced_at=? WHERE import_id=? AND publish=1 AND announced_at IS NULL ORDER BY achievement_key', (utcnow(), import_id))
    return len(rows)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id}); configured guild: {GUILD_ID}", flush=True)


@bot.event
async def on_disconnect() -> None:
    print("Bot disconnected from Discord gateway", flush=True)


@bot.event
async def on_resumed() -> None:
    print("Bot resumed connection to Discord gateway", flush=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, BotControllerRequired):
        await send_app_error(interaction, f"You need the {BOT_CONTROLLER_ROLE_NAME} role to use this bot.")
        return

    if isinstance(error, app_commands.MissingPermissions):
        await send_app_error(interaction, 'You need Manage Channels permission to configure automation channels.')
        return
    logging.error('Slash command failed', exc_info=error)
    await send_app_error(interaction, 'The command failed. Check the bot logs for details.')


@bot.tree.command(name="help", description="Show Aether bot commands.")
@app_commands.check(bot_controller_check)
async def help_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Aether Bot Help",
        description="Available slash commands:",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="/import",
        value="Import a report, update creator channels and global leaderboard, and detect achievements.",
        inline=False,
    )
    embed.add_field(
        name="/import-non-auto",
        value="Import a spreadsheet without automatically sending creator stats.",
        inline=False,
    )
    embed.add_field(
        name="/leaderboard",
        value="Generate the Aether leaderboard dashboard.",
        inline=False,
    )
    embed.add_field(
        name="/set-leaderboard-channel",
        value="Assign the single global month-to-date leaderboard channel.",
        inline=False,
    )
    embed.add_field(
        name="/stats",
        value="Generate an individual creator analytics dashboard as a manual fallback.",
        inline=False,
    )
    embed.add_field(
        name="/stats_all",
        value="Send all saved creator stats dashboards to their /set-channel channels.",
        inline=False,
    )
    embed.add_field(
        name="/set-channel",
        value="Assign a creator's stats and graphs to a Discord channel.",
        inline=False,
    )
    embed.add_field(
        name="/add-referral",
        value="Start a 30-day referral tracker for a referrer and creator.",
        inline=False,
    )
    embed.add_field(
        name="/all-referrals",
        value="Generate a dashboard of current referral links and rewards owed.",
        inline=False,
    )
    embed.add_field(
        name="/profile-import",
        value="Manually upload a creator profile picture.",
        inline=False,
    )
    embed.add_field(
        name="/ping",
        value="Check whether the bot is online and see its latency.",
        inline=False,
    )
    embed.add_field(
        name="/announce",
        value="Post an announcement message in a selected channel.",
        inline=False,
    )
    embed.add_field(name='/set-automation-channel', value='Configure leaderboard, wins, events, campaigns, announcements and admin logs.', inline=False)
    embed.add_field(name='/aether-status', value='Show import, channel and website integration health.', inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="ping", description="Check whether the bot is online.")
@app_commands.check(bot_controller_check)
async def ping_command(interaction: discord.Interaction) -> None:
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency: {latency_ms} ms")


@bot.tree.command(name="announce", description="Post an announcement in a selected channel.")
@app_commands.describe(
    channel="Channel where the announcement should be posted",
    message="Announcement text (mentions are enabled)",
)
@app_commands.check(bot_controller_check)
async def announce_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: app_commands.Range[str, 1, 2_000],
) -> None:
    try:
        # Do not override Discord's default allowed mentions: announcements are
        # intentionally permitted to notify mentioned members, roles, and everyone.
        await channel.send(message)
    except discord.Forbidden:
        await interaction.response.send_message(
            f"I don't have permission to post in {channel.mention}.", ephemeral=True
        )
        return
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"I couldn't send that announcement: {exc}", ephemeral=True)
        return

    await interaction.response.send_message(f"Announcement sent to {channel.mention}.", ephemeral=True)


async def process_report(interaction, spreadsheet, report_date=None, automatic=True):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if bot.automation_lock.locked():
        await interaction.followup.send('Another import or dashboard update is running. Please retry when it finishes.', ephemeral=True)
        return
    async with bot.automation_lock:
        destination = None
        try:
            if not spreadsheet.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
                raise ImportErrorWithContext('Please upload an XLSX, XLS, or CSV report.')
            if spreadsheet.size > MAX_REPORT_BYTES:
                raise ImportErrorWithContext('Reports must be at most 20 MB.')
            effective = date.fromisoformat(report_date) if report_date else None
            ensure_directories()
            filename = re.sub(r'[^A-Za-z0-9_. ()-]', '_', spreadsheet.filename)
            destination = UPLOAD_DIR / f'{uuid4().hex}_{filename}'
            await spreadsheet.save(destination)
            result = await asyncio.to_thread(import_spreadsheet, bot.database, destination, effective, automatic)
        except Exception as exc:
            logging.exception('Report import failed')
            if destination:
                destination.unlink(missing_ok=True)
            error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            await admin_log(f'Aether import failed: {error}')
            await interaction.followup.send(f'Import failed: {error}', ephemeral=True)
            return
        from website_sync import flush
        try:
            website_status = await asyncio.to_thread(flush, bot.database)
        except Exception:
            logging.warning('Website report sync configuration needs attention.')
            website_status = 'pending'
        missing = bot.database.missing_creator_channels()
        sent, failures, leaderboard, achievements = 0, [], 0, 0
        if automatic:
            sent, failures = await send_auto_stats_to_creator_channels()
            leaderboard, board_failures = await send_saved_leaderboards()
            failures.extend(board_failures)
            try:
                achievements = await publish_achievements(result.import_id)
            except Exception as exc:
                logging.exception('Achievement delivery failed')
                failures.append(f'Achievement digest failed ({type(exc).__name__})')
        summary = dict(creators=result.creator_count, channels_updated=sent,
                       unmapped=[r['creator_name'] for r in missing], leaderboard_updated=bool(leaderboard),
                       achievements=achievements, failures=failures, website_sync=website_status)
        status = 'partial' if failures else 'complete' if automatic else 'manual'
        bot.database.finish_import_delivery(result.import_id, summary, status)
        message = (f'Aether report {result.report_date}: {result.creator_count} creators imported; '
                   f'{sent} creator channels updated; {len(missing)} unmapped. Website: {website_status}. '
                   f'Leaderboard: {"updated" if leaderboard else "not updated"}. '
                   f'{"Duplicate report; history preserved. " if result.duplicate else ""}'
                   f'{"Automatic delivery disabled. " if not automatic else ""}')
        if missing:
            message += '\nUnmapped creators: ' + ', '.join(f"{r['creator_name']} ({r['creator_id']})" for r in missing)
        if failures:
            message += '\nProblems: ' + '; '.join(failures)
        await admin_log(message)
        # Persistent admin summary is delivered even if a very large import outlives the interaction token.
        try:
            await interaction.followup.send(message[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logging.warning('Import completed after interaction expired; see admin logs/status.')


@bot.tree.command(name='import', description='Import an Aether report and update creator channels, leaderboard and achievements.')
@app_commands.describe(spreadsheet='TikTok XLSX, XLS, or CSV report', report_date='Optional effective date YYYY-MM-DD if absent from report')
@app_commands.check(bot_controller_check)
async def import_command(interaction: discord.Interaction, spreadsheet: discord.Attachment, report_date: str | None = None):
    await process_report(interaction, spreadsheet, report_date)


@bot.tree.command(name='import-non-auto', description='Import a report and history without publishing dashboards or achievements.')
@app_commands.check(bot_controller_check)
async def import_non_auto_command(interaction: discord.Interaction, spreadsheet: discord.Attachment, report_date: str | None = None):
    await process_report(interaction, spreadsheet, report_date, automatic=False)


@bot.tree.command(name='leaderboard', description='Update the current Aether global month-to-date leaderboard.')
@app_commands.check(bot_controller_check)
async def leaderboard_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    async with bot.automation_lock:
        sent, failures = await send_saved_leaderboards()
    await interaction.followup.send('Global leaderboard updated.' if sent else '; '.join(failures), ephemeral=True)


@bot.tree.command(name="stats", description="Generate an individual creator analytics dashboard.")
@app_commands.describe(creator_name="Creator username or partial name")
@app_commands.check(bot_controller_check)
async def stats_command(interaction: discord.Interaction, creator_name: str) -> None:
    await interaction.response.defer(thinking=True)
    async with bot.automation_lock:
        creator = bot.database.find_creator(creator_name)
        if creator is None:
            await interaction.followup.send(f"I couldn't find a creator matching '{creator_name}'. Check the spelling or import the latest spreadsheet.")
            return

        rendered = await render_creator_dashboard_files(creator.creator_id)
        if rendered is None:
            await interaction.followup.send(f"I couldn't find a creator matching '{creator_name}'. Check the spelling or import the latest spreadsheet.")
            return

        output_path, trends_path, _creator_name = rendered
        await interaction.followup.send(file=discord.File(output_path, filename=f"acn-{creator.creator_id}.png"))
        await asyncio.sleep(0.5)
        await interaction.followup.send(file=discord.File(trends_path, filename=f"acn-{creator.creator_id}-trends.png"))

@stats_command.autocomplete("creator_name")
async def stats_creator_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@bot.tree.command(name="all-referrals", description="Generate a dashboard of all active referrals and rewards owed.")
@app_commands.check(bot_controller_check)
async def all_referrals_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    async with bot.automation_lock:
        referrals = bot.database.get_active_referrals()
        output_path = DATA_DIR / "acn-referrals.png"
        await asyncio.to_thread(render_all_referrals, referrals, output_path)
        await interaction.followup.send(
            file=discord.File(output_path, filename="acn-active-referrals.png"),
        )

@bot.tree.command(name="add-referral", description="Start tracking a referral from the referred creator's join date.")
@app_commands.describe(
    referrer_name="Creator who made the referral",
    referred_creator="Creator being referred (uses their imported Join time)",
)
@app_commands.check(bot_controller_check)
async def add_referral_command(
    interaction: discord.Interaction,
    referrer_name: str,
    referred_creator: str,
) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    async with bot.automation_lock:
        referrer = bot.database.find_creator(referrer_name)
        if referrer is None:
            await interaction.followup.send(
                f"I couldn't find referrer '{referrer_name}'. Import the latest stats sheet first.", ephemeral=True
            )
            return
        referred = bot.database.find_creator(referred_creator)
        if referred is None:
            await interaction.followup.send(
                f"I couldn't find referred creator '{referred_creator}'. Import the latest stats sheet first.",
                ephemeral=True,
            )
            return
        if not referred.join_date:
            await interaction.followup.send(
                f"{referred.creator_name} has no Join time in the imported data. Import a sheet with a Join time column first.",
                ephemeral=True,
            )
            return
        referral_start = date.fromisoformat(referred.join_date)
        referral = bot.database.add_referral(referrer, referred, referred_creator, referral_start)
        tracked_name = referral.creator_name
        await interaction.followup.send(
            f"Started tracking {tracked_name} for {referrer.creator_name} from their join date ({referral.start_date}). "
            f"The 30-day period ends on {referral.end_date}.",
            ephemeral=True,
        )


@add_referral_command.autocomplete("referrer_name")
async def add_referral_referrer_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@add_referral_command.autocomplete("referred_creator")
async def add_referral_creator_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@bot.tree.command(name="remove-referral", description="Remove an active referral so it can be added again.")
@app_commands.describe(
    referrer_name="Creator who made the referral",
    referred_creator="Referred creator to remove",
)
@app_commands.check(bot_controller_check)
async def remove_referral_command(
    interaction: discord.Interaction,
    referrer_name: str,
    referred_creator: str,
) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    async with bot.automation_lock:
        referrer = bot.database.find_creator(referrer_name)
        if referrer is None:
            await interaction.followup.send(
                f"I couldn't find referrer '{referrer_name}'. Check the spelling or import the latest sheet.",
                ephemeral=True,
            )
            return

        referred = bot.database.find_creator(referred_creator)
        removed = bot.database.remove_referral(referrer.creator_id, referred, referred_creator)
        if removed is None:
            await interaction.followup.send(
                f"No active referral for {referred_creator} under {referrer.creator_name} was found.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"Removed {removed.creator_name}'s referral under {referrer.creator_name} "
            f"(started {removed.start_date}). You can now use /add-referral to create it again.",
            ephemeral=True,
        )


@remove_referral_command.autocomplete("referrer_name")
async def remove_referral_referrer_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@remove_referral_command.autocomplete("referred_creator")
async def remove_referral_creator_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@bot.tree.command(name="stats_all", description="Send all saved creator stats dashboards to their assigned channels.")
@app_commands.check(bot_controller_check)
async def stats_all_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    async with bot.automation_lock:
        sent_count, failures = await send_auto_stats_to_creator_channels(max_channels=None)
        if not sent_count and not failures:
            await interaction.followup.send("No creator stat channels are saved yet. Use /set-channel first.")
            return

        failure_note = f" {len(failures)} failed: {'; '.join(failures[:5])}" if failures else ""
        await interaction.followup.send(
            f"Sent updated stats to {sent_count} saved creator channel(s).{failure_note}",
        )

@bot.tree.command(name='set-leaderboard-channel', description='Set the single Aether global leaderboard channel.')
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.check(bot_controller_check)
async def set_leaderboard_channel_command(interaction: discord.Interaction, channel: discord.TextChannel):
    bot.database.set_automation_channel('leaderboard', channel.id, interaction.user.id)
    await interaction.response.send_message(f'Global leaderboard channel: {channel.mention}. Updated automatically after /import.', ephemeral=True)


@bot.tree.command(name='set-automation-channel', description='Configure an Aether automation destination.')
@app_commands.choices(purpose=[app_commands.Choice(name=p.title(), value=p) for p in CHANNEL_PURPOSES])
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.check(bot_controller_check)
async def set_automation_channel_command(interaction: discord.Interaction, purpose: app_commands.Choice[str], channel: discord.TextChannel):
    bot.database.set_automation_channel(purpose.value, channel.id, interaction.user.id)
    await interaction.response.send_message(f'{purpose.name} channel: {channel.mention}', ephemeral=True)


@bot.tree.command(name='aether-status', description='Show import, channel, leaderboard and website integration status.')
@app_commands.check(bot_controller_check)
async def aether_status_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    latest = bot.database.latest_import()
    missing = bot.database.missing_creator_channels()
    channels = bot.database.automation_channels()
    record = bot.database.message_record('leaderboard')
    with bot.database.connect() as conn:
        recent = conn.execute('SELECT * FROM integration_requests ORDER BY updated_at DESC LIMIT 1').fetchone()
    integration = getattr(bot, 'integration', None)
    embed = discord.Embed(title='Aether automation status', color=0x257BFF)
    embed.add_field(name='Last successful data import', value=(f"{latest['imported_at']}\nReport: {latest['report_date']}\nCreators: {latest['creator_count']}\nDelivery: {latest['delivery_status']}" if latest else 'No Aether imports yet'), inline=False)
    if latest and (problems := json.loads(latest['summary']).get('failures')):
        embed.add_field(name='Latest delivery problems', value='; '.join(problems)[:1000], inline=False)
    embed.add_field(name='Creator channels', value=f'{len(bot.database.get_creator_channels())} mapped / {len(missing)} unmapped', inline=False)
    embed.add_field(name='Automation channels', value='\n'.join(f'{p}: <#{channels[p]}>' if p in channels else f'{p}: not configured' for p in CHANNEL_PURPOSES), inline=False)
    embed.add_field(name='Global leaderboard', value=f"{record['status']} | Updated {record['updated_at']} | Message {record['message_id']} | Error: {record['error'] or 'none'}" if record else 'No saved message', inline=False)
    embed.add_field(name='Website integration', value='Listening; Discord ready' if integration and integration.running and bot.is_ready() else 'Disabled or not ready', inline=False)
    if integration and integration.last_error:
        embed.add_field(name='Recent receiver error', value=integration.last_error[:1000], inline=False)
    if recent:
        embed.add_field(name='Most recent integration request', value=f"{recent['event_type']} | {recent['status']} | {recent['updated_at']}\n{recent['error'] or 'No error'}", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)
    if missing:
        names = 'Unmapped creators: ' + ', '.join(f"{r['creator_name']} ({r['creator_id']})" for r in missing)
        for offset in range(0, len(names), 1900):
            await interaction.followup.send(names[offset:offset+1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="set-channel", description="Send a creator's future stats and graphs to a channel.")
@app_commands.describe(
    creator_name="Creator username from the imported creator list",
    channel="Channel that should receive this creator's stats and graphs",
)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.check(bot_controller_check)
async def set_channel_command(
    interaction: discord.Interaction,
    creator_name: str,
    channel: discord.TextChannel | None = None,
) -> None:
    await interaction.response.defer(thinking=True)
    creator = bot.database.find_creator(creator_name)
    if creator is None:
        await interaction.followup.send(f"I couldn't find a creator matching '{creator_name}'. Run /import first or check the spelling.", ephemeral=True)
        return

    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.followup.send("Please choose a server text channel for creator stats.", ephemeral=True)
        return

    try:
        bot.database.set_creator_channel(creator.creator_id, target_channel.id, interaction.user.id)
    except ValueError as error:
        await interaction.followup.send(str(error),ephemeral=True)
        return
    await interaction.followup.send(
        f"{creator.creator_name}'s stats and graphs will be sent to {target_channel.mention} automatically after /import.",
        ephemeral=False,
    )


@set_channel_command.autocomplete("creator_name")
async def set_channel_creator_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@set_channel_command.error
async def set_channel_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, BotControllerRequired):
        message = f"You need the {BOT_CONTROLLER_ROLE_NAME} role to use this bot."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "You need Manage Channels permission to set creator stats channels."
    else:
        message = f"Could not set the stats channel: {error}"

    await send_app_error(interaction, message)


@bot.tree.command(name="profile-import", description="Manually upload a creator profile picture.")
@app_commands.describe(
    creator_name="Creator username from the imported creator list",
    image="Profile picture image to use on dashboards",
)
@app_commands.check(bot_controller_check)
async def profile_import_command(
    interaction: discord.Interaction,
    creator_name: str,
    image: discord.Attachment,
) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    async with bot.automation_lock:

        creator = bot.database.find_creator(creator_name)
        if creator is None:
            await interaction.followup.send(f"I couldn't find a creator matching '{creator_name}'. Run /import first or check the spelling.", ephemeral=True)
            return

        if image.content_type and not image.content_type.startswith("image/"):
            await interaction.followup.send("Please upload an image file for the profile picture.", ephemeral=True)
            return

        try:
            image_bytes = await image.read()
            cached_avatar = await asyncio.to_thread(cache_avatar_bytes, creator.creator_id, image_bytes)
        except Exception as exc:
            await interaction.followup.send(f"Profile picture import failed unexpectedly: {exc}", ephemeral=True)
            return

        if cached_avatar is None:
            await interaction.followup.send("I couldn't read that image. Try a PNG, JPG, or WEBP under 6 MB.", ephemeral=True)
            return

        avatar_url, avatar_path = cached_avatar
        bot.database.update_creator_avatar(creator.creator_id, avatar_url, avatar_path)
        await interaction.followup.send(f"Updated profile picture for {creator.creator_name}.", ephemeral=True)


@profile_import_command.autocomplete("creator_name")
async def profile_import_creator_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


def main() -> None:
    configure_logging()
    print(f"Using data directory: {DATA_DIR}", flush=True)
    print(f"Using database: {DATABASE_PATH}", flush=True)
    try:
        bot.run(get_required_bot_token(), log_handler=None)
    except KeyboardInterrupt:
        print("Bot interrupted", flush=True)
    except Exception as exc:
        print(f"Bot encountered an error: {exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
