"""Reconstruct explicit membership events without changing historical reports."""
import json
from network_membership import merge_report
from report_identity import departed_creator_id, without_departed_creators


def membership_at(database, cutoff):
    state = {'version': 1, 'creators': {}}
    with database.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'website_report_outbox' not in tables:
            return {}
        rows = conn.execute('''SELECT o.import_id,o.payload,i.imported_at
            FROM website_report_outbox o JOIN import_runs i ON i.id=o.import_id
            ORDER BY o.import_id''').fetchall()
        for row in rows:
            original = json.loads(row['payload'])
            if original['report']['end'] > cutoff:
                continue
            payload, excluded = without_departed_creators(original)
            departed = set(original.get('departures', []))
            departed.update(person['handle'] for person in excluded)
            if 'website_report_repairs' in tables:
                repair = conn.execute('SELECT excluded_creators FROM website_report_repairs WHERE import_id=?', (row['import_id'],)).fetchone()
                if repair:
                    departed.update(person['handle'] for person in json.loads(repair[0]))
            for snapshot in conn.execute('SELECT payload FROM creator_snapshots WHERE import_id=?', (row['import_id'],)):
                person = json.loads(snapshot[0])
                if departed_creator_id(person.get('creator_id')):
                    departed.add(person['creator_name'].strip().lstrip('@').lower())
            state = merge_report(state, payload, departed, row['imported_at'])
    return state['creators']
