# Aether Creator Network

Aether's Discord automation service, extending the existing Python bot, spreadsheet importer, SQLite database, dashboards and referral system.

## Daily workflow

Upload the daily TikTok report once with `/import`. The bot validates and imports the report, saves historical snapshots, updates mapped creator channels, edits the single global month-to-date leaderboard, records achievements, publishes any enabled achievement digest, and sends an admin summary. A creator without a channel still imports normally and appears in the unmapped list. One failed render or Discord send does not stop other creators or the leaderboard.

Only one import/delivery pipeline runs at a time. A second import receives a busy response. Manual dashboard updates share the lock. Run **one bot process / one Railway replica** against the database; in-process locks are not a distributed queue.

## Setup and commands

Use Python 3.12+:

```sh
python -m venv .venv
# Activate .venv using your shell, then:
pip install -r requirements.txt
python bot.py
```

Copy `.env.example` to `.env` and set `DISCORD_TOKEN` and `DISCORD_GUILD_ID`. Never commit `.env`. Commands require Discord Administrator permission or the existing `bot controller` role. Channel configuration also requires Manage Channels on the invoking member.

Configure once:

- `/set-channel creator_name channel`: retain the existing creator-to-channel mappings. Creator channels should already be private, with member and manager/admin permission overwrites. The bot never creates a role per creator or changes channel permissions.
- `/set-leaderboard-channel channel`: one global month-to-date leaderboard destination.
- `/set-automation-channel purpose channel`: `leaderboard`, `wins`, `events`, `campaigns`, `announcements`, or `logs`.
- `/aether-status`: latest successful database import, report date, creator/mapped counts, full unmapped list, import delivery state, all channel destinations, saved leaderboard state and website receiver/recent request status.

Other retained commands: `/stats`, `/stats_all`, `/leaderboard`, `/profile-import`, `/add-referral`, `/remove-referral`, `/all-referrals`, `/announce`, `/help`, and `/ping`. `/leaderboard` edits the configured global message; it no longer posts a second copy into the command channel. `/announce` retains explicit mentions and a chosen destination. Automated messages disable mentions.

`/import-non-auto` imports data/history and detects achievements without publishing dashboards or marking new achievements for public delivery. It still logs an admin summary. `/import` of the same snapshot can retry dashboard delivery; it does not retroactively enable announcements suppressed by a non-auto import.

Invite with `bot` and `applications.commands` scopes. The bot needs **View Channel, Send Messages, Attach Files, Embed Links, and Read Message History** in its configured channels. Read Message History is required to recover an uncertain send without making a duplicate. Message Content privileged intent is not required for this slash-command service. The bot edits/deletes its own messages; Manage Messages and Manage Channels are not required for those operations.

## Reports and history

Supported formats: `.xlsx`, `.xls`, `.csv`, up to 20 MB. Existing flexible column/header detection and duplicate-row aggregation remain. Required metrics are creator name, diamonds, hours, valid days and battles; optional fields include Creator ID, new followers, Join time, Diamonds last month and avatar URL.

The report effective date comes from `Data period`, falling back to dated filenames such as `Creator data 2026_09_10.xlsx`. If neither exists, pass `report_date:2026-09-10`. An explicit date must agree with dated report contents. Undated and future reports are rejected rather than silently using upload day. Reports older than the latest imported report are rejected to prevent rollback and incorrect referral deltas. Import historical files chronologically into an empty test database if history backfill is needed; the live importer is not a backfill tool.

SQLite stores an import record and a per-creator snapshot for each effective date, including rankings, tier, metrics and incentive status. CSV and Excel both contribute. Current snapshot, referrals, import metadata, history and achievements commit in one transaction. Corrected reports for the latest date replace that date's historical snapshot. Re-uploading a known superseded version is rejected; equivalent current uploads reuse the existing import record. Corrected historical public announcements are not automatically retracted.

Daily trends and PBs use differences between consecutive dated month-to-date snapshots. Day one of a month is a daily value itself. Missing dates and downward corrections are gaps, not zero days or invented daily PBs. Database history is preferred; the existing Excel-file trend fallback remains for pre-migration data without snapshots. Old uploaded reports are not silently backfilled during migration.

Stored leagues retain the existing rule: use **Diamonds last month** where supplied; otherwise preserve an existing creator's tier. The dashboard's current-month tier progress remains distinct. Referral rewards/thresholds remain unchanged; updates and baseline creation use the report effective date. Dashboard reads no longer recalculate referral totals using the wall-clock date. Referral status reflects the latest imported report.

## Achievements and public noise control

Detection/history is always enabled for:

- Daily PBs in diamonds, LIVE hours and new followers, using reliable daily intervals.
- Monthly diamond milestones, configurable through `DIAMOND_MILESTONES`.
- Tier/league changes, rank movement within a month, and completed monthly incentives.

`ANNOUNCE_ACHIEVEMENTS` is empty by default. To enable selected public updates, set for example `ANNOUNCE_ACHIEVEMENTS=milestone,league,incentive`, configure the `wins` channel, and restart. Supported values: `pb,milestone,league,incentive,rank`. The first historical observation establishes a quiet baseline. One digest is posted per import (split only for Discord embed limits), with persistent message IDs and achievement keys preventing repeated announcements. Changes to announcement settings affect future detections, not old suppressed records.

## Website integration

### Application onboarding

The existing leased queue includes creator manager choice and a manual TikTok network gate. Approval sends a private choice email without creating accounts or changing roles. The creator confirms their manager, receives that manager's scout link and cannot change the choice themselves. Only explicit admin network confirmation permits Discord verification, Pending, provisioning and setup email. Creator replaces Pending after password setup; dashboard access is enabled after Discord sync.

Configure the existing Supabase credentials and `ONBOARDING_ENABLED`, `ONBOARDING_PENDING_ROLE_ID`, `ONBOARDING_CREATOR_ROLE_ID`, `RESEND_API_KEY`, `ONBOARDING_EMAIL_FROM`. Keep onboarding disabled until migrations through 010, both website setup pages, manager scout links and this bot are deployed. See `../../website/ONBOARDING_SETUP.md`. Clicks never imply TikTok acceptance.

## Command registration diagnostics

Set `DISCORD_GUILD_ID=1468015338221207656` in Railway. Commands are defined
in bot.py before main runs, using one tree and no cogs/extensions. Startup logs
local global/guild command counts and names, copies global definitions to this
guild, logs the actual guild-sync response and fetches Discord registration back
for verification. Wrong guild IDs and registration failures stop startup.

Expect `Loaded commands locally: N [...]`, `Synced N commands to guild
1468015338221207656: [...]`, `Verified commands registered on Discord: N [...]`
and `Logged in as Team Vextal Analytics#9036 (ID: ...)` (actual Discord bot name).
Counts depend on the commands present in the deployed revision, not a fixed eight.

Install/reauthorize this token's application with both `bot` and
`applications.commands` scopes using the URL printed during startup. The live
installation scopes cannot be confirmed from Gateway connection logs alone.
Check member/channel Use Application Commands and server integration permissions.
Local registration tests: `python -m unittest test_command_startup`.
