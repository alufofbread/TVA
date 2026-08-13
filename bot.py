from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import discord
from discord import app_commands

from avatars import cache_avatar_bytes
from config import BOT_TOKEN, DATABASE_PATH, DATA_DIR, ENV_PATH, GUILD_ID, UPLOAD_DIR, ensure_directories
from dashboard.creator_stats import render_creator_stats
from dashboard.leaderboard import render_leaderboard
from dashboard.referrals import render_all_referrals
from dashboard.trends import render_creator_trends
from database import Database
from importer import ImportErrorWithContext, import_spreadsheet

COMMAND_SYNC_TIMEOUT_SECONDS = 30
BOT_CONTROLLER_ROLE_NAME = "bot controller"
LEADERBOARD_CHANNEL_TYPES = {"daily", "monthly"}


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


async def render_creator_dashboard_files(creator_id: str) -> tuple[Path, Path, str] | None:
    creator = bot.database.find_creator(creator_id)
    if creator is None:
        return None

    creators = bot.database.get_creators()
    output_path = Path(__file__).resolve().parent / "data" / f"stats_{creator.creator_id}.png"
    trends_path = Path(__file__).resolve().parent / "data" / f"trends_{creator.creator_id}.png"
    referrals = bot.database.get_referrals_for_referrer(creator.creator_id)
    await asyncio.to_thread(render_creator_stats, creator, len(creators), output_path, referrals)
    await asyncio.to_thread(render_creator_trends, creator, trends_path)
    return output_path, trends_path, creator.creator_name


async def send_creator_dashboard(channel: discord.abc.Messageable, creator_id: str) -> str | None:
    creator = bot.database.find_creator(creator_id)
    if creator is None:
        return "creator missing from the latest import"

    # A creator with no live hours does not need an empty dashboard (or the
    # Send Files permission). Give their own assigned channel a clear update.
    if creator.hours <= 0:
        await channel.send(
            f"Hi {creator.creator_name}! You haven't gone live yet this month, so there are no stats to share just yet. "
            "Once you go LIVE, your stats will be sent here after the next data import."
        )
        return None

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


async def send_auto_stats_to_creator_channels(max_channels: int | None = None) -> tuple[int, list[str]]:
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
        name="/import-non-auto",
        value="Import a spreadsheet without automatically sending creator stats.",
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


@bot.tree.command(name="import-non-auto", description="Import a spreadsheet without automatically sending creator stats.")
@app_commands.describe(spreadsheet="Excel spreadsheet containing creator performance data")
@app_commands.check(bot_controller_check)
async def import_non_auto_command(interaction: discord.Interaction, spreadsheet: discord.Attachment) -> None:
    """Refresh stored creator data without posting to any assigned channels."""
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
        f"Imported {result.creator_count} creators. Total diamonds: {result.total_diamonds:,}. "
        f"No creator stats or leaderboards were sent.{duplicate_note}",
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


@bot.tree.command(name="all-referrals", description="Generate a dashboard of all active referrals and rewards owed.")
@app_commands.check(bot_controller_check)
async def all_referrals_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    referrals = bot.database.get_active_referrals()
    output_path = Path(__file__).resolve().parent / "data" / "all_referrals.png"
    await asyncio.to_thread(render_all_referrals, referrals, output_path)
    await interaction.followup.send(
        file=discord.File(output_path, filename="team-vextal-active-referrals.png"),
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
