import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
from database import Database
from importer import import_spreadsheet,load_creators_from_spreadsheet,parse_number


class CreatorExportTests(unittest.TestCase):
    def test_tiktok_export_columns_and_exact_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Creator data 2026_10_06.xlsx'
            workbook=Workbook();sheet=workbook.active
            sheet.append(['Data period','Creator ID',"Creator's username",'Group','Creator Network manager','Join time',
                          'Days since joining','Diamonds','LIVE duration','Valid go LIVE days','New followers','LIVE streams','Diamonds last month','Matches'])
            sheet.append(['2026-10-01 ~ 2026-10-05','7689377887576915989','vextal.live','Not in a group','manager@example.com',
                          '2026-10-04 22:32:54 (UTC+0)','3','11242','1h 45m 13s','1','30','2','-','0'])
            workbook.save(path)
            with patch('importer.cache_avatar',return_value=None),patch.dict(os.environ,{'REPORT_MANAGER_ALIASES':'{}'}):
                creators,_,observed=load_creators_from_spreadsheet(path,cache_avatars=False,with_report_date=True)
                self.assertEqual(observed,date(2026,10,5))
                self.assertEqual(creators[0]['live_seconds'],6313)
                self.assertTrue(creators[0]['preserve_existing_tier'])
                db=Database(Path(directory)/'test.db')
                result=import_spreadsheet(db,path)
                self.assertEqual(result.creator_count,1)
                self.assertTrue(import_spreadsheet(db,path).duplicate)
                with db.connect() as conn:
                    payload=json.loads(conn.execute('select payload from website_report_outbox').fetchone()[0])
                self.assertEqual(payload['creators'][0]['manager'],'manager@example.com')
                self.assertEqual(payload['creators'][0]['id'],'7689377887576915989')
                self.assertEqual(payload['report']['end'],'2026-10-05')
                self.assertEqual(payload['report']['records'][0],{'creatorId':'7689377887576915989','liveSeconds':6313,
                    'metrics':{'Diamonds':11242,'Valid go LIVE days':1,'New followers':30,'Battles':0,'LIVE streams':2}})

    def test_seconds_only_and_full_duration(self):
        self.assertEqual(round(parse_number('13s')*3600),13)
        self.assertEqual(round(parse_number('1h 45m 13s')*3600),6313)

    def test_export_departure_status_is_excluded_without_inventing_an_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Creator_data_2026_10_20.csv'
            path.write_text("Data period,Creator ID,Creator's username,Diamonds,LIVE duration,Valid go LIVE days,Matches\n"
                            "2026-10-01 ~ 2026-10-19,123456789,active.creator,100,1h,1,0\n"
                            "2026-10-01 ~ 2026-10-19,The creator has quit the network,frostbite_poole,10,1h,1,0\n",encoding='utf8')
            creators,_,observed,departed=load_creators_from_spreadsheet(path,cache_avatars=False,with_report_date=True,with_departures=True)
            self.assertEqual(observed,date(2026,10,19))
            self.assertEqual(departed,['frostbite_poole'])
            self.assertEqual([r['creator_id'] for r in creators],['123456789'])
            self.assertEqual(creators[0]['rank'],1)

    def test_latest_departure_removes_earlier_rows_of_the_same_creator_from_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Creator_data_2026_10_20.csv'
            path.write_text("Data period,Creator ID,Creator's username,Diamonds,LIVE duration,Valid go LIVE days,Matches\n"
                            "2026-10-19,123456789,active.creator,100,1h,1,0\n"
                            "2026-10-18,987654321,frostbite_poole,10,1h,1,0\n"
                            "2026-10-19,The creator has quit the network,frostbite_poole,10,1h,1,0\n",encoding='utf8')
            creators,_=load_creators_from_spreadsheet(path,cache_avatars=False)
            self.assertEqual([r['creator_name'] for r in creators],['active.creator'])
