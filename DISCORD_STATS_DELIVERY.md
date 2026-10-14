# Creator stats delivery

Creator stats now post a new message for each unique imported report, keyed by creator and import-run ID. Previously delivered reports remain unchanged, including the legacy latest-stats message. Zero-hour reports use the same behaviour.

Reimporting an identical report or repeating /stats_all for the latest report recovers the already-delivered message without editing or reposting it. Corrected/new data receives a new import ID and therefore a new stats message. /import-non-auto continues to import without automatic posts. /stats remains an explicit individual response.

Global leaderboards and manager performance summaries continue editing their saved messages. Existing channel assignments, imported history and other automation are preserved. No website database migration is required.

Verification covers consecutive imports, duplicate retries, uncertain send recovery, zero-hour reports, preserving old stats when destinations change and continued leaderboard editing.
