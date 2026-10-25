# Report delivery and automatic LIVE watchlist

TikTok can replace a departed creator's ID with `The creator has quit the network`. The importer now recognises this exact status, excludes the departed creator from the active snapshot, and preserves their previous report history. Unknown invalid IDs are not silently discarded or converted into invented IDs.

The website delivery worker repairs existing queued reports with that status. It preserves the original JSON and excluded entries in `website_report_repairs`, removes the matching creator/metrics rows only from the pending delivery, and retries the same report identity. No report is marked delivered without a successful server acknowledgement and account-provisioning pass. If a report was repaired manually using the same backup table and already delivered, its departure information is recovered without resending or changing its receipt.

## LIVE membership feed

`network_membership.py` writes only creator IDs, handles, active/departed status and report dates into the private Supabase Storage bucket `agency-live-watchlist`, object `membership.json`. The bucket must be private, accept `application/json`, and allow at least 2 MB. Initialise it once with `{"version":1,"creators":{}}`. The worker uses the existing server credentials; no additional public endpoint, browser secret or database migration is required.

FTLN reads the existing service-only `import_member_roster` RPC and the private feed. New/enabled roster members are added automatically. Explicit report departures, disabled accounts and removals from the roster are removed from the automatic list. A report's absence of a creator alone is not treated as proof that they left: partial reports must not remove unrelated members. Older report replays cannot override newer membership events. A later genuine active report can record a rejoin.

The outbox's additive `membership_synced` field allows previously delivered imports to backfill this feed without changing reports, passwords, identities, account access or Discord mappings. The delivery lock serialises updates. **Keep one running TVA instance**, as already required for the persistent SQLite database; the private feed has one writer.

## Deployment order

1. Verify the existing TVA `/data` volume and single instance.
2. Create/verify the private bucket and initial object. Do not reset an existing feed.
3. Configure FTLN with the same `SUPABASE_URL` and server-only `SUPABASE_SERVICE_ROLE_KEY`; preserve all existing variables, channel configuration and volume files.
4. Deploy TVA, then check the outbox repair/backfill logs.
5. Deploy FTLN and confirm `[agency roster] synced` and the `/watchliststatus` command.

Manual watchlist add/remove/list commands remain available. FTLN's persistent state remembers manual exclusions so the next agency sync does not undo an operator's removal. An explicit later manual addition can be used as a fallback after a departure. Any future agency departure transition clears a prior manual pin for that creator.

The original local member list is backed up before first roster adoption. Unrelated manual extras remain tracked; they are not assumed to be former agency members. Never clear an entire watchlist on a failed roster request. Failed feed writes leave delivery queued for retry; FTLN continues using its last successful saved list.
