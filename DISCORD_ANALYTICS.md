# Discord analytics

Apply the existing profile-picture migration and `022_manager_performance_targets.sql`, then `023_discord_analytics.sql` from aether-site before enabling manager reports. Existing Supabase bot service credentials are reused; browser users cannot call the Discord RPCs.

Configure the destination with `/set-automation-channel purpose:manager-performance channel:<channel>`. Configure monthly agency and manager diamond targets in the website Admin Performance Targets panel. Reports update after successful website synchronization and pick up target changes on subsequent sync cycles. Report pages have stable persisted message keys; restarts and uncertain sends reuse the durable publisher. Manual/non-auto imports do not publish manager summaries. Monthly totals use one exact month-to-date website import. Missing roster coverage is unavailable rather than a partial total. Contribution is unavailable when agency diamonds are zero.

The leaderboard retains the top 15 and full imported roster totals, with a new navy/blue/purple image. Stats now include a compact three-date daily diamonds image. Cumulative month-to-date snapshots require an adjacent previous date to establish daily diamonds, except the first of a month. Missing baselines, corrections and conflicting snapshots are unavailable; a verified unchanged snapshot is zero.

Avatars first reuse approved website profile pictures through freshly signed private storage requests. Cached images refresh after 24 hours and profile revisions refresh after changes. URLs and service credentials are never persisted in the revision manifest. Removed or disabled profiles clear the website image cache. TikTok fallback now resolves the creator handle instead of a numeric ID; missing images retain the existing initials fallback.

Run `python -m unittest discover -s tests`. Tests use fake Discord channels and exercise report restarts, persistent message updates, graph baselines/zero/corrections, avatar expiry/cache/removal and existing import/schedule behavior. Live Discord delivery requires the configured bot and channel permissions; local tests do not claim deployment.
