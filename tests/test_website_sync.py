import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date
from database import Database
from website_sync import enqueue, flush


class WebsiteSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=Database(Path(self.temp.name)/'test.db')
        self.row=dict(creator_id='1234567890123456789',creator_name='real.handle',diamonds=1200,hours=2.5,days=2,new_followers=4,battles=3)
        with self.db.transaction() as conn:
            enqueue(conn,1,'a'*64,'report.csv',date(2026,9,3),[self.row])

    def test_no_credentials_retains_delivery(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(flush(self.db),'not configured')
        with self.db.connect() as conn:
            row=conn.execute('select * from website_report_outbox').fetchone()
            self.assertEqual(row['delivered'],0)
            payload=json.loads(row['payload'])
            self.assertEqual(payload['report']['records'][0]['liveSeconds'],9000)
            self.assertNotIn('LIVE streams',payload['report']['records'][0]['metrics'])

    def test_failure_retries_same_payload(self):
        env={'SUPABASE_URL':'https://test.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'test-secret'}
        with patch.dict(os.environ,env,clear=True), patch('urllib.request.urlopen',side_effect=OSError('offline')):
            self.assertEqual(flush(self.db),'pending')
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('select attempts from website_report_outbox').fetchone()[0],1)
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'"duplicate"'
        with patch.dict(os.environ,env,clear=True), patch('urllib.request.urlopen',return_value=Response()),patch('import_members.provision_members') as provision:
            self.assertEqual(flush(self.db),'synced')
            provision.assert_called_once()
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('select delivered from website_report_outbox').fetchone()[0],1)

    def test_enqueue_rollback_and_duplicate(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as conn:
                enqueue(conn,2,'b'*64,'report.csv',date(2026,9,4),[self.row])
                raise RuntimeError('rollback')
        with self.db.transaction() as conn:
            enqueue(conn,1,'a'*64,'report.csv',date(2026,9,3),[self.row])
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('select count(*) from website_report_outbox').fetchone()[0],1)
