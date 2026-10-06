"""Validate a supplied report in a temporary local database; no network writes."""
import argparse
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from database import Database
from importer import import_spreadsheet,load_creators_from_spreadsheet


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook',type=Path)
    parser.add_argument('--payload-output',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as directory,patch('importer.cache_avatar',return_value=None):
        creators,_,observed=load_creators_from_spreadsheet(args.workbook,cache_avatars=False,with_report_date=True)
        database=Database(Path(directory)/'validation.db')
        result=import_spreadsheet(database,args.workbook)
        assert import_spreadsheet(database,args.workbook).duplicate,'Duplicate import did not preserve the snapshot'
        with database.connect() as conn:
            payload=json.loads(conn.execute('select payload from website_report_outbox').fetchone()[0])
        if args.payload_output:args.payload_output.write_text(json.dumps(payload,indent=2),encoding='utf8')
        print(json.dumps({'creators':result.creator_count,'effective_date':observed.isoformat(),
            'total_diamonds':result.total_diamonds,'records':payload['report']['records'],
            'managers':sorted({row.get('manager','') for row in creators}),
            'duplicate_retry':'passed','network_changes':False},indent=2))


if __name__=='__main__':main()
