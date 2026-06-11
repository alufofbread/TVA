# Team Vextal Analytics

Production-ready Discord slash-command bot for importing TikTok creator performance spreadsheets and generating SaaS-style PNG dashboards.

## Features

- `/import` accepts `.xlsx`, `.xls`, or `.csv` spreadsheet attachments.
- `/leaderboard` returns a dark Team Vextal leaderboard PNG.
- `/set-leaderboard-channel leaderboard_type channel` stores the daily or monthly leaderboard channel.
- `/stats creator_name` returns an individual creator analytics PNG as a manual fallback.
- `/stats_all` sends all saved creator stats dashboards to their `/set-channel` channels.
- `/set-channel creator_name channel` stores a creator's stats channel for automatic updates.
- `/profile-import creator_name image` manually sets a creator profile picture.
- SQLite stores the current monthly creator snapshot.
- Flexible spreadsheet column detection with clear import errors.
- Tier, ranking, and incentive status recalculation after each import.
- After `/import`, the bot sends each mapped creator their own stats and trends graphs.
- When `/leaderboard` runs, the bot sends the leaderboard to the saved daily and monthly channels.

## Setup

```powershell
cd vextal
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bot.py
```

Create a local `.env` file in the `vextal` folder:

```env
DISCORD_TOKEN=your-reset-bot-token
DISCORD_GUILD_ID=your-server-id
```

Then start the bot:

```powershell
python bot.py
```

Both `DISCORD_TOKEN` and `DISCORD_GUILD_ID` are required.

## Railway Deployment

Deploy the `vextal` folder as the Railway service root.

1. Push this project to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Set the service root directory to `vextal` if Railway asks for one.
4. Add these service variables:

```env
DISCORD_TOKEN=your-reset-bot-token
DISCORD_GUILD_ID=your-server-id
```

5. Add a Railway Volume to the bot service so imports, avatars, and the SQLite database persist between redeploys.
6. Mount the volume anywhere convenient, for example `/data`. The app automatically uses Railway's `RAILWAY_VOLUME_MOUNT_PATH`.
7. Deploy. The included `railway.json` starts the bot with `python bot.py`.

After it is live, use `/ping` in Discord to confirm the hosted bot is online. Your partner can then use `/import` with the daily spreadsheet without your PC being on.

If the bot is hosted on Railway without a persistent Volume, it will refuse to start. This prevents imports from being saved to temporary container storage and disappearing when Railway restarts or redeploys the service.

## Invite URL

In the Discord Developer Portal, open **OAuth2 > URL Generator**.

Select scopes:

- `bot`
- `applications.commands`

Select bot permissions:

- `Send Messages`
- `Attach Files`
- `Use Slash Commands`
- `Manage Channels` if admins should use `/set-channel`

Open the generated URL and invite the bot to the same server as `DISCORD_GUILD_ID`.

If startup fails with `403 Forbidden: Missing Access`, the bot is not installed in that server or was invited without the `applications.commands` scope.

## Expected Spreadsheet Columns

The importer accepts common aliases:

- Creator ID: `creator id`, `user id`, `tiktok id`
- Creator: `creator`, `creator name`, `creator's username`, `username`, `tiktok username`, `host`
- Diamonds: `diamonds`, `total diamonds`, `received diamonds`, `points`
- Hours: `hours`, `live hours`, `LIVE duration`, `duration`, `valid hours`
- Days: `days`, `valid days`, `Valid go LIVE days`, `active days`
- Battles: `battles`, `total battles`, `pk battles`, `Matches`
- New Followers: `new followers`
- Data Period: `Data period`, `period`, `reporting period`
- Avatar URL (optional): `avatar url`, `profile picture url`, `profile image url`

Duplicate creator rows are grouped by creator name and added together so the stored creator snapshot is the monthly total. The report month is taken from `Data period` or from filenames like `Creator data 2026_06_02 14_59 UTC+0 (1)`.
If no avatar URL is provided, the bot tries to fetch the TikTok profile image using the creator ID as the TikTok username, then falls back to initials if TikTok blocks or omits the image.

## Tier System

- Tier 1: 0
- Tier 2: 100,000
- Tier 3: 200,000
- Tier 4: 300,000
- Tier 5: 500,000
- Tier 6: 700,000
- Tier 7: 1,000,000
- Tier 8: 1,600,000
- Tier 9: 2,500,000
- Tier 10: 5,000,000

## Incentive System

Achieved requires:

- Diamonds >= 250,000
- Valid Days >= 22
- Live Hours >= 80

Statuses:

- `ACHIEVED`: all targets complete.
- `IN_PROGRESS`: target remains possible.
- `NOT_ACHIEVABLE`: valid days can no longer reach 22 in the current month.

## Project Structure

```text
vextal/
├── bot.py
├── database.py
├── importer.py
├── config.py
├── dashboard/
│   ├── leaderboard.py
│   ├── creator_stats.py
│   ├── style.py
│   └── assets/
│       ├── fonts/
│       ├── logo.png
│       └── templates/
├── data/
│   ├── database.db
│   └── uploads/
└── requirements.txt
```
