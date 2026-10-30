"""Durable server-side report delivery. No Discord or Supabase secrets in payloads."""
import asyncio
import json
import logging
import os
import re
import urllib.request
import threading
from report_identity import without_departed_creators, departed_creator_id

_delivery_lock = threading.Lock()
_last_queue_signature = None
_report_logger = logging.getLogger('aether.website_sync')
if not _report_logger.handlers:
    _report_handler = logging.StreamHandler()
    _report_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    _report_logger.addHandler(_report_handler)
_report_logger.setLevel(logging.INFO)
_report_logger.propagate = False


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS website_report_outbox (
        import_id INTEGER PRIMARY KEY, payload TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS website_report_repairs (
        import_id INTEGER PRIMARY KEY, original_payload TEXT NOT NULL,
        excluded_creators TEXT NOT NULL, repaired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    if 'membership_synced' not in {row[1] for row in conn.execute('PRAGMA table_info(website_report_outbox)')}:
        conn.execute('ALTER TABLE website_report_outbox ADD COLUMN membership_synced INTEGER NOT NULL DEFAULT 0')
    if 'departure_checked' not in {row[1] for row in conn.execute('PRAGMA table_info(website_report_outbox)')}:
        conn.execute('ALTER TABLE website_report_outbox ADD COLUMN departure_checked INTEGER NOT NULL DEFAULT 0')


def enqueue(conn, import_id, digest, filename, observed_on, creators, departed_handles=()):
    initialize(conn)
    aliases=json.loads(os.environ.get('REPORT_MANAGER_ALIASES','{}'))
    payload = {'creators': [{'id': row['creator_id'], 'handle': row['creator_name'].strip().lstrip('@').lower(),
                            **({'manager': aliases.get(row['manager'].strip().lower(),row['manager'].strip().lstrip('@').lower())} if row.get('manager') else {})}
                            for row in creators],
               'report': {'id': 'sha256:' + digest, 'source': filename,
                          'start': observed_on.replace(day=1).isoformat(), 'end': observed_on.isoformat(),
                          'records': [{'creatorId': row['creator_id'], 'liveSeconds': row.get('live_seconds',round(row['hours'] * 3600)),
                                       'metrics': {'Diamonds': row['diamonds'], 'Valid go LIVE days': row['days'],
                                                   'New followers': row['new_followers'], 'Battles': row['battles'],
                                                   **({'LIVE streams':row['live_streams']} if row.get('live_streams') is not None else {})}}
                                      for row in creators]}}
    # Unknown source metrics (e.g. LIVE streams) stay absent, never invented as zero.
    if departed_handles:
        payload['departures'] = list(departed_handles)
    conn.execute('INSERT OR IGNORE INTO website_report_outbox(import_id,payload) VALUES (?,?)',
                 (import_id, json.dumps(payload)))


def flush(database):
    # Background retries and an immediate command delivery share one ordered sender.
    with _delivery_lock:
        return _flush(database)


def _flush(database):
    global _last_queue_signature
    url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    secret = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if not url or not secret:
        return 'not configured'
    if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co', url):
        raise ValueError('SUPABASE_URL must be the project HTTPS endpoint')
    headers = {'Content-Type': 'application/json', 'apikey': secret}
    if secret.startswith('eyJ'):
        headers['Authorization'] = 'Bearer ' + secret
    with database.connect() as conn:
        initialize(conn)
        rows = conn.execute('SELECT * FROM website_report_outbox WHERE delivered=0 OR membership_synced=0 OR departure_checked=0 ORDER BY import_id LIMIT 20').fetchall()
    signature = tuple((row['import_id'], row['delivered'], row['membership_synced'], row['departure_checked']) for row in rows)
    if signature != _last_queue_signature:
        _report_logger.info('Website queue batch: %s pending report deliveries; %s membership/departure checks; import IDs=%s',
                            sum(not row['delivered'] for row in rows), len(rows), [row['import_id'] for row in rows])
        _last_queue_signature = signature
    for row in rows:
        original = json.loads(row['payload'])
        departures = set(original.get('departures', []))
        with database.connect() as conn:
            repair = conn.execute('SELECT excluded_creators FROM website_report_repairs WHERE import_id=?', (row['import_id'],)).fetchone()
            run = conn.execute('SELECT imported_at FROM import_runs WHERE id=?', (row['import_id'],)).fetchone()
            snapshots = conn.execute('SELECT payload FROM creator_snapshots WHERE import_id=?', (row['import_id'],)).fetchall()
        # A manually cleaned outbox may have no repair receipt. The original
        # local snapshot still records TikTok's explicit departure status.
        for snapshot in snapshots:
            person = json.loads(snapshot[0])
            if departed_creator_id(person.get('creator_id')):
                handle = str(person.get('creator_name', '')).strip().lstrip('@').lower()
                if re.fullmatch(r'[a-z0-9_.]{2,24}', handle):
                    departures.add(handle)
        if repair:
            departures.update(person['handle'] for person in json.loads(repair[0]))
        try:
            payload, excluded = without_departed_creators(original)
        except ValueError:
            logging.warning('Website report delivery pending for import %s; reason=invalid_report_creator; manual review required.', row['import_id'])
            return 'pending'
        if excluded:
            departures.update(person['handle'] for person in excluded)
            with database.connect() as conn:
                conn.execute('INSERT OR IGNORE INTO website_report_repairs(import_id,original_payload,excluded_creators) VALUES (?,?,?)',
                             (row['import_id'], row['payload'], json.dumps(excluded)))
                conn.execute('UPDATE website_report_outbox SET payload=? WHERE import_id=? AND delivered=0 AND payload=?',
                             (json.dumps(payload), row['import_id'], row['payload']))
            _report_logger.info('Preserved original import %s payload and excluded %s TikTok departure status row(s) from website delivery.', row['import_id'], len(excluded))
        with database.connect() as conn:
            conn.execute('UPDATE website_report_outbox SET attempts=attempts+1 WHERE import_id=?', (row['import_id'],))
        # Membership metadata is a separate service call. Do not change exact
        # report receipt payloads, which are compared on idempotent retries.
        report_payload = {key: value for key, value in payload.items() if key != 'departures'}
        request = urllib.request.Request(url + '/rest/v1/rpc/import_creator_report',
            data=json.dumps({'payload': report_payload}).encode(), headers=headers, method='POST')
        stage='report_import'
        try:
            if not row['delivered']:
                with urllib.request.urlopen(request, timeout=20) as response:
                    outcome = json.load(response)
                if outcome not in ('imported', 'duplicate'):
                    raise ValueError('Unexpected report acknowledgement')
            from network_membership import sync_report
            stage='watchlist_membership'
            imported_at = run[0] if run else payload['report']['end'] + 'T23:59:59+00:00'
            sync_report(url, headers, payload, sorted(departures), imported_at)
            if not row['delivered']:
                from import_members import provision_members
                stage='account_provision'
                provision_members()
        except Exception as error:
            # Never print request headers, raw response bodies or creator data.
            from onboarding import safe_api_error, report_sync_hint
            reason=safe_api_error(error)
            logging.warning('Website report delivery pending for import %s; stage=%s; reason=%s; action=%s Later reports remain queued behind this import; will retry.', row['import_id'],stage,reason,report_sync_hint(reason))
            return 'pending'
        with database.connect() as conn:
            conn.execute('UPDATE website_report_outbox SET delivered=1,membership_synced=1,departure_checked=1 WHERE import_id=?', (row['import_id'],))
        _report_logger.info('Website import %s synced; explicit departures=%s.', row['import_id'], len(departures))
    return 'synced' if len(rows) < 20 else 'pending'


def sync_channel_mappings(database):
    from onboarding import rpc
    guild=os.environ.get('DISCORD_GUILD_ID','')
    if not guild.isdigit():return
    for member in rpc('import_member_roster'):
        if member.get('channel_id') and database.find_creator(member['id']):
            database.set_creator_channel(member['id'],int(member['channel_id']),int(guild))


async def worker(database,on_synced=None):
    delay = 30
    while True:
        try:
            result = await asyncio.to_thread(flush, database)
            if result=='synced':
                await asyncio.to_thread(sync_channel_mappings,database)
                if on_synced:await on_synced()
            delay = min(delay * 2, 300) if result == 'pending' else 30
        except Exception:
            logging.warning('Website report sync configuration needs attention.')
            delay = 300
        await asyncio.sleep(delay)
