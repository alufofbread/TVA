from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import discord
from discord import app_commands
try:
    from TikTokLive import TikTokLiveClient
except ImportError:
    TikTokLiveClient = None

from avatars import cache_avatar_bytes
from config import BOT_TOKEN, DATABASE_PATH, DATA_DIR, ENV_PATH, GUILD_ID, UPLOAD_DIR, ensure_directories
from dashboard.creator_stats import render_creator_stats
from dashboard.leaderboard import render_leaderboard
from dashboard.trends import render_creator_trends
from database import Database
from importer import ImportErrorWithContext, import_spreadsheet

COMMAND_SYNC_TIMEOUT_SECONDS = 30
MAX_AUTO_STATS_CHANNELS = 25
BOT_CONTROLLER_ROLE_NAME = "bot controller"
LEADERBOARD_CHANNEL_TYPES = {"daily", "monthly"}
LIVE_NOTIFICATION_POLL_SECONDS = 120
LIVE_NOTIFICATION_INITIAL_DELAY_SECONDS = 15
DEFAULT_LIVE_NOTIFICATION_MESSAGE = "@everyone {creator} is live right now\ncheck it out here {url}"
LIVE_NOTIFICATION_CHANNEL_ID = 1512190588009582753
LIVE_NOTIFICATION_CONCURRENT_CHECKS = 5


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


class TeamVextalCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if can_use_bot(interaction.user):
            return True

        await send_app_error(interaction, f"You need the {BOT_CONTROLLER_ROLE_NAME} role to use this bot.")
        return False


class TeamVextalBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = TeamVextalCommandTree(self)
        self.database = Database()
        self.live_notification_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        guild = get_required_guild()
        self.tree.copy_global_to(guild=guild)
        print(f"Syncing slash commands to Discord server {GUILD_ID}...", flush=True)
        try:
            await asyncio.wait_for(self.tree.sync(guild=guild), timeout=COMMAND_SYNC_TIMEOUT_SECONDS)
            print("Slash commands synced.", flush=True)
        except asyncio.TimeoutError:
            print(
                f"Slash command sync timed out after {COMMAND_SYNC_TIMEOUT_SECONDS}s. "
                "The bot will still connect, but slash command updates may not appear until the next restart. "
                "Check the guild ID, bot invite scopes, and Discord connectivity if this keeps happening.",
                flush=True,
            )
        except discord.Forbidden as exc:
            print(
                f"Missing Discord access for server {GUILD_ID}. Make sure DISCORD_GUILD_ID in {ENV_PATH} "
                "is the server ID, the bot has been invited to that server, and the invite used both "
                "'bot' and 'applications.commands' scopes.",
                flush=True,
            )
            print(f"Discord sync error: {exc}", flush=True)
        except discord.HTTPException as exc:
            print(f"Slash command sync failed, but the bot will still connect: {exc}", flush=True)

    async def close(self) -> None:
        if self.live_notification_task is not None:
            self.live_notification_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.live_notification_task
        await super().close()


bot = TeamVextalBot()


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


def live_creator_autocomplete(current: str) -> list[app_commands.Choice[str]]:
    choices = creator_autocomplete(current)
    if "random".startswith(current.strip().lower()):
        return [app_commands.Choice(name="Random creator", value="random"), *choices[:24]]
    return choices


def normalize_tiktok_username(username: str) -> str:
    cleaned = username.strip()
    if "tiktok.com/@" in cleaned:
        cleaned = cleaned.split("tiktok.com/@", 1)[1].split("/", 1)[0]
    elif "/" in cleaned:
        cleaned = cleaned.rstrip("/").split("/")[-1]
    return cleaned.lstrip("@").lower()


def creator_display_name(creator_id: str) -> str:
    creator = bot.database.find_creator(creator_id)
    return creator.creator_name if creator else f"@{creator_id}"


async def is_tiktok_creator_live(creator_id: str) -> bool:
    if TikTokLiveClient is None:
        raise RuntimeError("TikTokLive is not installed. Run pip install -r requirements.txt and restart the bot.")

    client = TikTokLiveClient(unique_id=f"@{creator_id}")
    return bool(await client.is_live())


def render_live_notification_message(template: str, creator_id: str) -> str:
    creator_name = creator_display_name(creator_id)
    username = creator_name.lstrip("@") or creator_id
    url = f"https://www.tiktok.com/@{username}/live"
    try:
        rendered = template.format(
            creator=creator_name,
            username=username,
            url=url,
        )
    except (KeyError, IndexError, ValueError):
        rendered = template

    return rendered.strip() or DEFAULT_LIVE_NOTIFICATION_MESSAGE.format(
        creator=creator_name,
        username=creator_id,
        url=url,
    )


async def send_live_notification(channel_id: int, creator_id: str, message: str) -> bool:
    target_channel_id = LIVE_NOTIFICATION_CHANNEL_ID or channel_id
    channel = bot.get_channel(target_channel_id)
    if channel is None:
        channel = await bot.fetch_channel(target_channel_id)

    if not isinstance(channel, discord.abc.Messageable):
        return False

    await channel.send(
        render_live_notification_message(message, creator_id),
        allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=True),
    )
    return True


async def check_creator_live_notification(notification, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        try:
            is_live = await is_tiktok_creator_live(notification.creator_id)
        except Exception as exc:
            print(f"TikTok live check failed for @{notification.creator_id}: {exc}", flush=True)
            return

        if is_live and not notification.last_live:
            try:
                sent = await send_live_notification(
                    notification.channel_id,
                    notification.creator_id,
                    notification.message,
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                print(f"Could not send live notification for @{notification.creator_id}: {exc}", flush=True)
                sent = False

            bot.database.update_creator_live_state(notification.creator_id, True, notified=sent)
        elif is_live != notification.last_live:
            bot.database.update_creator_live_state(notification.creator_id, is_live)


async def creator_live_notification_loop() -> None:
    await bot.wait_until_ready()
    await asyncio.sleep(LIVE_NOTIFICATION_INITIAL_DELAY_SECONDS)
    print("TikTok live notification watcher started.", flush=True)

    while not bot.is_closed():
        creators = bot.database.get_creators()
        if LIVE_NOTIFICATION_CHANNEL_ID and creators:
            added_count = bot.database.ensure_creator_live_notifications(
                (creator.creator_id for creator in creators),
                LIVE_NOTIFICATION_CHANNEL_ID,
                DEFAULT_LIVE_NOTIFICATION_MESSAGE,
                updated_by=0,
            )
            if added_count:
                print(f"Added {added_count} imported creator(s) to TikTok live watcher.", flush=True)

        notifications = bot.database.get_creator_live_notifications()
        if TikTokLiveClient is None and notifications:
            print("TikTokLive is not installed; live notification checks are paused.", flush=True)
            await asyncio.sleep(LIVE_NOTIFICATION_POLL_SECONDS)
            continue

        semaphore = asyncio.Semaphore(LIVE_NOTIFICATION_CONCURRENT_CHECKS)
        await asyncio.gather(
            *(check_creator_live_notification(notification, semaphore) for notification in notifications)
        )

        await asyncio.sleep(LIVE_NOTIFICATION_POLL_SECONDS)


async def render_creator_dashboard_files(creator_id: str) -> tuple[Path, Path, str] | None:
    creator = bot.database.find_creator(creator_id)
    if creator is None:
        return None

    creators = bot.database.get_creators()
    output_path = Path(__file__).resolve().parent / "data" / f"stats_{creator.creator_id}.png"
    trends_path = Path(__file__).resolve().parent / "data" / f"trends_{creator.creator_id}.png"
    await asyncio.to_thread(render_creator_stats, creator, len(creators), output_path)
    await asyncio.to_thread(render_creator_trends, creator, trends_path)
    return output_path, trends_path, creator.creator_name


async def send_creator_dashboard(channel: discord.abc.Messageable, creator_id: str) -> str | None:
    rendered = await render_creator_dashboard_files(creator_id)
    if rendered is None:
        return "creator missing from the latest import"

    output_path, trends_path, creator_name = rendered
    await channel.send(
        content=f"Latest stats for {creator_name}",
        file=discord.File(output_path, filename=f"team-vextal-{creator_id}.png"),
    )
    await asyncio.sleep(0.5)
    await channel.send(file=discord.File(trends_path, filename=f"team-vextal-{creator_id}-trends.png"))
    return None


async def send_auto_stats_to_creator_channels(max_channels: int | None = MAX_AUTO_STATS_CHANNELS) -> tuple[int, list[str]]:
    assignments = bot.database.get_creator_channels()
    if not assignments:
        return 0, []

    sent_count = 0
    failures: list[str] = []
    selected_assignments = assignments[:max_channels] if max_channels is not None else assignments
    for assignment in selected_assignments:
        channel = bot.get_channel(assignment.channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(assignment.channel_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                failures.append(f"{assignment.creator_name}: channel unavailable")
                continue

        if not isinstance(channel, discord.abc.Messageable):
            failures.append(f"{assignment.creator_name}: saved channel cannot receive messages")
            continue

        try:
            error = await send_creator_dashboard(channel, assignment.creator_id)
        except discord.Forbidden:
            failures.append(f"{assignment.creator_name}: missing permission to send files")
            continue
        except discord.HTTPException as exc:
            failures.append(f"{assignment.creator_name}: Discord send failed ({exc.status})")
            continue

        if error:
            failures.append(f"{assignment.creator_name}: {error}")
            continue
        sent_count += 1

    if max_channels is not None and len(assignments) > max_channels:
        failures.append(f"Skipped {len(assignments) - max_channels} extra channel assignments.")

    return sent_count, failures


async def render_leaderboard_file(channel_type: str = "monthly") -> Path | None:
    creators = bot.database.get_creators()
    if not creators:
        return None

    output_path = Path(__file__).resolve().parent / "data" / f"leaderboard_{channel_type}.png"
    await asyncio.to_thread(render_leaderboard, creators, bot.database.get_summary(), output_path)
    return output_path


async def send_saved_leaderboards() -> tuple[int, list[str]]:
    assignments = bot.database.get_leaderboard_channels()
    if not assignments:
        return 0, []

    sent_count = 0
    failures: list[str] = []
    rendered_paths: dict[str, Path] = {}
    for assignment in assignments:
        channel = bot.get_channel(assignment.channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(assignment.channel_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                failures.append(f"{assignment.channel_type}: channel unavailable")
                continue

        if not isinstance(channel, discord.abc.Messageable):
            failures.append(f"{assignment.channel_type}: saved channel cannot receive messages")
            continue

        if assignment.channel_type not in rendered_paths:
            rendered = await render_leaderboard_file(assignment.channel_type)
            if rendered is None:
                failures.append(f"{assignment.channel_type}: no creator data imported")
                continue
            rendered_paths[assignment.channel_type] = rendered

        try:
            await channel.send(
                content=f"{assignment.channel_type.title()} Team Vextal leaderboard",
                file=discord.File(
                    rendered_paths[assignment.channel_type],
                    filename=f"team-vextal-{assignment.channel_type}-leaderboard.png",
                ),
            )
        except discord.Forbidden:
            failures.append(f"{assignment.channel_type}: missing permission to send files")
            continue
        except discord.HTTPException as exc:
            failures.append(f"{assignment.channel_type}: Discord send failed ({exc.status})")
            continue

        sent_count += 1

    return sent_count, failures


@bot.event
async def on_ready() -> None:
    print(f"Team Vextal Analytics signed in as {bot.user}", flush=True)
    if bot.live_notification_task is None or bot.live_notification_task.done():
        bot.live_notification_task = asyncio.create_task(creator_live_notification_loop())


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

    raise error


@bot.tree.command(name="help", description="Show Team Vextal bot commands.")
@app_commands.check(bot_controller_check)
async def help_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Team Vextal Bot Help",
        description="Available slash commands:",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="/import",
        value="Import the latest Team Vextal creator spreadsheet.",
        inline=False,
    )
    embed.add_field(
        name="/leaderboard",
        value="Generate the Team Vextal leaderboard dashboard.",
        inline=False,
    )
    embed.add_field(
        name="/set-leaderboard-channel",
        value="Assign the daily or monthly leaderboard to a Discord channel.",
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
        name="/creator_notif",
        value="Watch a TikTok creator and ping a channel when they go live.",
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
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="ping", description="Check whether the bot is online.")
@app_commands.check(bot_controller_check)
async def ping_command(interaction: discord.Interaction) -> None:
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency: {latency_ms} ms")


@bot.tree.command(name="import", description="Import the latest Team Vextal creator spreadsheet.")
@app_commands.describe(spreadsheet="Excel spreadsheet containing creator performance data")
@app_commands.check(bot_controller_check)
async def import_command(interaction: discord.Interaction, spreadsheet: discord.Attachment) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    if not spreadsheet.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        await interaction.followup.send("Please upload a spreadsheet with a .xlsx, .xls, or .csv extension.", ephemeral=True)
        return

    ensure_directories()
    destination = UPLOAD_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex}_{spreadsheet.filename}"
    try:
        await spreadsheet.save(destination)
        result = await asyncio.to_thread(import_spreadsheet, bot.database, destination)
    except ImportErrorWithContext as exc:
        await interaction.followup.send(f"Import failed: {exc}", ephemeral=True)
        return
    except Exception as exc:
        await interaction.followup.send(f"Import failed unexpectedly: {exc}", ephemeral=True)
        return

    duplicate_note = " Duplicate spreadsheet detected; the current snapshot was refreshed." if result.duplicate else ""
    await interaction.followup.send(
        f"Imported {result.creator_count} creators. Total diamonds: {result.total_diamonds:,}.{duplicate_note}",
        ephemeral=True,
    )

    sent_count, failures = await send_auto_stats_to_creator_channels()
    if sent_count or failures:
        failure_note = f" {len(failures)} failed: {'; '.join(failures[:5])}" if failures else ""
        await interaction.followup.send(
            f"Auto-sent updated stats to {sent_count} creator channel(s).{failure_note}",
            ephemeral=True,
        )


@bot.tree.command(name="leaderboard", description="Generate the Team Vextal leaderboard dashboard.")
@app_commands.check(bot_controller_check)
async def leaderboard_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    full_path = await render_leaderboard_file("monthly")
    if full_path is None:
        await interaction.followup.send("No creator data is available yet. Run /import with the latest spreadsheet first.")
        return

    await interaction.followup.send(file=discord.File(full_path, filename="team-vextal-leaderboard.png"))
    sent_count, failures = await send_saved_leaderboards()
    if sent_count or failures:
        failure_note = f" {len(failures)} failed: {'; '.join(failures[:5])}" if failures else ""
        await interaction.followup.send(f"Sent leaderboard to {sent_count} saved channel(s).{failure_note}")


@bot.tree.command(name="stats", description="Generate an individual creator analytics dashboard.")
@app_commands.describe(creator_name="Creator username or partial name")
@app_commands.check(bot_controller_check)
async def stats_command(interaction: discord.Interaction, creator_name: str) -> None:
    await interaction.response.defer(thinking=True)
    creator = bot.database.find_creator(creator_name)
    if creator is None:
        await interaction.followup.send(f"I couldn't find a creator matching '{creator_name}'. Check the spelling or import the latest spreadsheet.")
        return

    rendered = await render_creator_dashboard_files(creator.creator_id)
    if rendered is None:
        await interaction.followup.send(f"I couldn't find a creator matching '{creator_name}'. Check the spelling or import the latest spreadsheet.")
        return

    output_path, trends_path, _creator_name = rendered
    await interaction.followup.send(file=discord.File(output_path, filename=f"team-vextal-{creator.creator_id}.png"))
    await asyncio.sleep(0.5)
    await interaction.followup.send(file=discord.File(trends_path, filename=f"team-vextal-{creator.creator_id}-trends.png"))


@stats_command.autocomplete("creator_name")
async def stats_creator_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@bot.tree.command(name="stats_all", description="Send all saved creator stats dashboards to their assigned channels.")
@app_commands.check(bot_controller_check)
async def stats_all_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    sent_count, failures = await send_auto_stats_to_creator_channels(max_channels=None)
    if not sent_count and not failures:
        await interaction.followup.send("No creator stat channels are saved yet. Use /set-channel first.")
        return

    failure_note = f" {len(failures)} failed: {'; '.join(failures[:5])}" if failures else ""
    await interaction.followup.send(
        f"Sent updated stats to {sent_count} saved creator channel(s).{failure_note}",
    )


@bot.tree.command(name="set-leaderboard-channel", description="Send future leaderboards to a daily or monthly channel.")
@app_commands.describe(
    leaderboard_type="Choose whether this channel receives the daily or monthly leaderboard",
    channel="Channel that should receive this leaderboard",
)
@app_commands.choices(
    leaderboard_type=[
        app_commands.Choice(name="Daily", value="daily"),
        app_commands.Choice(name="Monthly", value="monthly"),
    ]
)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.check(bot_controller_check)
async def set_leaderboard_channel_command(
    interaction: discord.Interaction,
    leaderboard_type: app_commands.Choice[str],
    channel: discord.TextChannel | None = None,
) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.followup.send("Please choose a server text channel for the leaderboard.", ephemeral=True)
        return

    if leaderboard_type.value not in LEADERBOARD_CHANNEL_TYPES:
        await interaction.followup.send("Please choose Daily or Monthly.", ephemeral=True)
        return

    bot.database.set_leaderboard_channel(leaderboard_type.value, target_channel.id, interaction.user.id)
    await interaction.followup.send(
        f"The {leaderboard_type.name.lower()} leaderboard will be sent to {target_channel.mention} when /leaderboard runs.",
        ephemeral=True,
    )


@set_leaderboard_channel_command.error
async def set_leaderboard_channel_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, BotControllerRequired):
        message = f"You need the {BOT_CONTROLLER_ROLE_NAME} role to use this bot."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "You need Manage Channels permission to set leaderboard channels."
    else:
        message = f"Could not set the leaderboard channel: {error}"

    await send_app_error(interaction, message)


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

    bot.database.set_creator_channel(creator.creator_id, target_channel.id, interaction.user.id)
    await interaction.followup.send(
        f"{creator.creator_name}'s stats and graphs will be sent to {target_channel.mention} after running /stats_all.",
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


@bot.tree.command(name="creator_notif", description="Ping a channel when a TikTok creator goes live.")
@app_commands.describe(
    creator_username="Creator ID/TikTok username, or random to pick one from the imported DB.",
    message="Custom ping message. Supports {creator}, {username}, and {url}.",
    channel="Channel that should receive the live notification.",
)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.check(bot_controller_check)
async def creator_notif_command(
    interaction: discord.Interaction,
    creator_username: str | None = None,
    message: str = DEFAULT_LIVE_NOTIFICATION_MESSAGE,
    channel: discord.TextChannel | None = None,
) -> None:
    await interaction.response.defer(thinking=True)
    creator_input = (creator_username or "random").strip()
    if creator_input.lower() == "random":
        creators = bot.database.get_creators()
        if not creators:
            await interaction.followup.send("No creators are imported yet. Run /import first, then try random.")
            return
        selected_creator = random.choice(creators)
        creator_id = selected_creator.creator_id
    else:
        creator_id = normalize_tiktok_username(creator_input)

    if not creator_id:
        await interaction.followup.send("Please enter a TikTok username or creator ID.")
        return

    if len(message) > 1800:
        await interaction.followup.send("Please keep the notification message under 1,800 characters.")
        return

    target_channel = channel or interaction.channel
    if LIVE_NOTIFICATION_CHANNEL_ID:
        target_channel = bot.get_channel(LIVE_NOTIFICATION_CHANNEL_ID)
        if target_channel is None:
            target_channel = await bot.fetch_channel(LIVE_NOTIFICATION_CHANNEL_ID)

    if not isinstance(target_channel, discord.TextChannel):
        await interaction.followup.send("Please choose a server text channel for live notifications.")
        return

    bot.database.set_creator_live_notification(creator_id, target_channel.id, message, interaction.user.id)
    await interaction.followup.send(
        f"Live notifications for @{creator_display_name(creator_id).lstrip('@')} will be sent to {target_channel.mention}.",
    )


@creator_notif_command.autocomplete("creator_username")
async def creator_notif_creator_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return live_creator_autocomplete(current)


@creator_notif_command.error
async def creator_notif_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, BotControllerRequired):
        message = f"You need the {BOT_CONTROLLER_ROLE_NAME} role to use this bot."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "You need Manage Channels permission to set live notification channels."
    else:
        message = f"Could not set the live notification: {error}"

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
