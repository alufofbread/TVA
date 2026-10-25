"""Single-writer, private network status feed shared with the LIVE notifier."""
import json
import re
import urllib.request
from datetime import date, datetime, timezone

BUCKET = 'agency-live-watchlist'
OBJECT = 'membership.json'


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def merge_report(current, payload, departed_handles, imported_at):
    if not isinstance(current, dict) or current.get('version') != 1 or not isinstance(current.get('creators'), dict):
        raise ValueError('Invalid membership feed')
    result = {'version': 1, 'creators': dict(current['creators'])}
    observed_on = date.fromisoformat(payload['report']['end'])
    revision = timestamp(imported_at)
    active = {row['handle']: row['id'] for row in payload['creators']}
    if set(active).intersection(departed_handles):
        raise ValueError('Conflicting membership status')
    updates = {handle: {'id': creator_id, 'active': True} for handle, creator_id in active.items()}
    updates.update({handle: {'id': None, 'active': False} for handle in departed_handles})
    for handle, update in updates.items():
        if not re.fullmatch(r'[a-z0-9_.]{2,24}', handle):
            raise ValueError('Invalid membership handle')
        previous = result['creators'].get(handle)
        if previous:
            previous_rank = (date.fromisoformat(previous['observed_on']), timestamp(previous['imported_at']))
            if previous_rank > (observed_on, revision):
                continue
        result['creators'][handle] = {**update, 'observed_on': observed_on.isoformat(), 'imported_at': revision.isoformat()}
    return result


def sync_report(base, headers, payload, departed_handles, imported_at):
    # The TVA outbox delivery lock serialises writes; keep one running TVA instance.
    url = base + '/storage/v1/object/' + BUCKET + '/' + OBJECT
    request = urllib.request.Request(url, headers={**headers, 'Cache-Control': 'no-cache'}, method='GET')
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(2000001)
    if len(raw) > 2000000:
        raise ValueError('Membership feed is too large')
    current = json.loads(raw)
    updated = merge_report(current, payload, departed_handles, imported_at)
    if updated == current:
        return
    encoded = json.dumps(updated).encode()
    if len(encoded) > 2000000:
        raise ValueError('Membership feed is too large')
    request = urllib.request.Request(url, data=encoded, headers={**headers, 'x-upsert': 'true', 'Cache-Control': 'no-cache'}, method='POST')
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()
