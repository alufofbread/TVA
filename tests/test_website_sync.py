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
        with patch.dict(os.environ,env,clear=True), patch('urllib.request.urlopen',return_value=Response()),patch('network_membership.sync_report'),patch('import_members.provision_members') as provision:
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

    def test_departure_in_queued_report_is_backed_up_and_does_not_block_delivery(self):
        marker='The creator has quit the network'
        with self.db.connect() as conn:
            raw=conn.execute('select payload from website_report_outbox').fetchone()[0]
            payload=json.loads(raw)
            payload['creators'].append({'id':marker,'handle':'frostbite_poole'})
            payload['report']['records'].append({'creatorId':marker,'liveSeconds':0,'metrics':{}})
            original=json.dumps(payload)
            conn.execute('update website_report_outbox set payload=?',(original,))
        sent=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'"imported"'
        def deliver(request,**kwargs):
            sent.append(json.loads(request.data)['payload'])
            return Response()
        env={'SUPABASE_URL':'https://test.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'test-secret'}
        with patch.dict(os.environ,env,clear=True),patch('urllib.request.urlopen',side_effect=deliver),patch('network_membership.sync_report') as membership,patch('import_members.provision_members'):
            self.assertEqual(flush(self.db),'synced')
            self.assertEqual(membership.call_args.args[3],['frostbite_poole'])
        self.assertEqual(sent[0]['creators'],[payload['creators'][0]])
        self.assertEqual(sent[0]['report']['records'],[payload['report']['records'][0]])
        self.assertEqual(sent[0]['report']['id'],payload['report']['id'])
        with self.db.connect() as conn:
            repair=conn.execute('select * from website_report_repairs').fetchone()
            self.assertEqual(repair['original_payload'],original)
            self.assertEqual(json.loads(repair['excluded_creators']),[{'id':marker,'handle':'frostbite_poole'}])
            self.assertEqual(conn.execute('select delivered from website_report_outbox').fetchone()[0],1)

    def test_unknown_invalid_id_is_not_silently_removed(self):
        from report_identity import without_departed_creators
        payload={'creators':[{'id':'unexpected message','handle':'creator'}],
                 'report':{'records':[{'creatorId':'unexpected message'}]}}
        cleaned,excluded=without_departed_creators(payload)
        self.assertEqual(cleaned,payload)
        self.assertEqual(excluded,[])

    def test_already_delivered_manual_repair_backfills_departure_without_resending_report(self):
        from website_sync import initialize
        with self.db.connect() as conn:
            initialize(conn)
            conn.execute('update website_report_outbox set delivered=1')
            conn.execute('insert into website_report_repairs(import_id,original_payload,excluded_creators) values(1,?,?)',
                         ('original',json.dumps([{'id':'The creator has quit the network','handle':'frostbite_poole'}])))
        env={'SUPABASE_URL':'https://test.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'test-secret'}
        with patch.dict(os.environ,env,clear=True),patch('urllib.request.urlopen') as send,patch('network_membership.sync_report') as membership,patch('import_members.provision_members') as provision:
            self.assertEqual(flush(self.db),'synced')
            send.assert_not_called();provision.assert_not_called()
            self.assertEqual(membership.call_args.args[3],['frostbite_poole'])
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('select membership_synced from website_report_outbox').fetchone()[0],1)

    def test_departure_recovered_from_original_snapshot_after_outbox_was_manually_cleaned(self):
        from website_sync import initialize
        with self.db.connect() as conn:
            initialize(conn)
            conn.execute('update website_report_outbox set delivered=1,membership_synced=1')
            conn.execute('insert into creator_snapshots(creator_id,report_date,import_id,payload) values(?,?,?,?)',
                         ('The creator has quit the network','2026-09-03',1,json.dumps({'creator_id':'The creator has quit the network','creator_name':'frostbite_poole'})))
        env={'SUPABASE_URL':'https://test.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'test-secret'}
        with patch.dict(os.environ,env,clear=True),patch('urllib.request.urlopen') as send,patch('network_membership.sync_report') as membership:
            self.assertEqual(flush(self.db),'synced')
            send.assert_not_called()
            self.assertEqual(membership.call_args.args[3],['frostbite_poole'])
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('select departure_checked from website_report_outbox').fetchone()[0],1)
