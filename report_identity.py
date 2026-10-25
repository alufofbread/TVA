"""Recognise TikTok export status cells without inventing creator identities."""
from copy import deepcopy
import re

DEPARTED_CREATOR_ID = 'the creator has quit the network'


def departed_creator_id(value):
    return ' '.join(str(value or '').split()).casefold() == DEPARTED_CREATOR_ID


def without_departed_creators(payload):
    """Remove only known departure status rows and their matching report records.

    Earlier reports and the agency roster are never changed here. Unknown invalid
    IDs still fail website validation rather than being silently discarded.
    """
    excluded = [row for row in payload['creators'] if departed_creator_id(row.get('id'))]
    if not excluded:
        return payload, []
    cleaned = deepcopy(payload)
    cleaned['creators'] = [row for row in cleaned['creators'] if not departed_creator_id(row.get('id'))]
    cleaned['report']['records'] = [row for row in cleaned['report']['records']
                                    if not departed_creator_id(row.get('creatorId'))]
    if not cleaned['creators']:
        raise ValueError('Report contains no active creator identities')
    if any(not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', str(row.get('id') or ''))
           or not re.fullmatch(r'[a-z0-9_.]{1,100}', str(row.get('handle') or ''))
           for row in cleaned['creators']):
        raise ValueError('Report contains another invalid creator identity')
    ids = {row['id'] for row in cleaned['creators']}
    records = cleaned['report']['records']
    if len(ids) != len(cleaned['creators']) or len(records) != len(ids) or {row['creatorId'] for row in records} != ids:
        raise ValueError('Report creator and metric rows do not match')
    return cleaned, excluded
