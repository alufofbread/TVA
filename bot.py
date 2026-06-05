from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import discord
from discord import app_commands

from avatars import cache_avatar_bytes
from config import BOT_TOKEN, DATABASE_PATH, DATA_DIR, ENV_PATH, GUILD_ID, UPLOAD_DIR, ensure_directories
from dashboard.creator_stats import render_creator_stats
from dashboard.leaderboard import render_leaderboard
from dashboard.trends import render_creator_trends
from database import Database
from importer import ImportErrorWithContext, import_spreadsheet

COMMAND_SYNC_TIMEOUT_SECONDS = 30


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


class TeamVextalBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
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


@bot.event
async def on_ready() -> None:
    print(f"Team Vextal Analytics signed in as {bot.user}", flush=True)


@bot.tree.command(name="help", description="Show Team Vextal bot commands.")
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
        name="/stats",
        value="Generate an individual creator analytics dashboard.",
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
async def ping_command(interaction: discord.Interaction) -> None:
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency: {latency_ms} ms", ephemeral=True)


@bot.tree.command(name="import", description="Import the latest Team Vextal creator spreadsheet.")
@app_commands.describe(spreadsheet="Excel spreadsheet containing creator performance data")
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


@bot.tree.command(name="leaderboard", description="Generate the Team Vextal leaderboard dashboard.")
async def leaderboard_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    creators = bot.database.get_creators()
    if not creators:
        await interaction.followup.send("No creator data is available yet. Run /import with the latest spreadsheet first.")
        return

    output_path = Path("data") / "leaderboard.png"
    full_path = Path(__file__).resolve().parent / output_path
    await asyncio.to_thread(render_leaderboard, creators, bot.database.get_summary(), full_path)
    await interaction.followup.send(file=discord.File(full_path, filename="team-vextal-leaderboard.png"))


@bot.tree.command(name="stats", description="Generate an individual creator analytics dashboard.")
@app_commands.describe(creator_name="Creator username or partial name")
async def stats_command(interaction: discord.Interaction, creator_name: str) -> None:
    await interaction.response.defer(thinking=True)
    creator = bot.database.find_creator(creator_name)
    if creator is None:
        await interaction.followup.send(f"I couldn't find a creator matching '{creator_name}'. Check the spelling or import the latest spreadsheet.")
        return

    creators = bot.database.get_creators()
    output_path = Path(__file__).resolve().parent / "data" / f"stats_{creator.creator_id}.png"
    trends_path = Path(__file__).resolve().parent / "data" / f"trends_{creator.creator_id}.png"
    await asyncio.to_thread(render_creator_stats, creator, len(creators), output_path)
    await asyncio.to_thread(render_creator_trends, creator, trends_path)
    await interaction.followup.send(file=discord.File(output_path, filename=f"team-vextal-{creator.creator_id}.png"))
    await asyncio.sleep(0.5)
    await interaction.followup.send(file=discord.File(trends_path, filename=f"team-vextal-{creator.creator_id}-trends.png"))


@stats_command.autocomplete("creator_name")
async def stats_creator_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return creator_autocomplete(current)


@bot.tree.command(name="profile-import", description="Manually upload a creator profile picture.")
@app_commands.describe(
    creator_name="Creator username from the imported creator list",
    image="Profile picture image to use on dashboards",
)
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
    print(f"Using data directory: {DATA_DIR}", flush=True)
    print(f"Using database: {DATABASE_PATH}", flush=True)
    bot.run(get_required_bot_token())


if __name__ == "__main__":
    main()
