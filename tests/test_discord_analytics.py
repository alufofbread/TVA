import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from dashboard.daily_graph import last_three_days, render_three_day_graph
from manager_reports import build_reports, enrich_summary, ManagerReports
from database import Database
from delivery import MessagePublisher
from test_delivery import FakeChannel
from PIL import Image

def data(count=1):
    return dict(start='2026-10-01',end='2026-10-12',agency=dict(diamonds=200,reported=2,expected=2),agency_targets=dict(diamonds=400),managers=[dict(name='Manager '+str(i),totals=dict(diamonds=100,reported=1,expected=1),targets=dict(diamonds=200)) for i in range(count)])

class GraphTests(unittest.TestCase):
    def test_gap_zero_and_daily_delta(self):
        rows=last_three_days([dict(report_date=d,diamonds=v) for d,v in [('2026-10-01',10),('2026-10-02',10),('2026-10-04',40),('2026-10-05',45)]])
        self.assertEqual([r['diamonds'] for r in rows],[0,None,5])
    def test_month_reset_correction_and_conflict(self):
        rows=last_three_days([dict(report_date=d,diamonds=v) for d,v in [('2026-09-30',999),('2026-10-01',20),('2026-10-02',10)]])
        self.assertEqual([r['diamonds'] for r in rows],[None,20,None])
        self.assertIsNone(last_three_days([dict(report_date='2026-10-01',diamonds=v) for v in [1,2]])[0]['diamonds'])
    def test_empty_and_single_render(self):
        self.assertEqual(last_three_days([]),[])
        with tempfile.TemporaryDirectory() as root:
            file=render_three_day_graph(SimpleNamespace(creator_name='Creator'),[dict(report_date='2026-10-01',diamonds=0)],Path(root)/'graph.png')
            with Image.open(file) as image:self.assertEqual(image.size,(1024,420))
    def test_report_progress_pages_and_missing(self):
        pages=build_reports(data(25))
        self.assertEqual([len(p.fields) for p in pages],[10,10,5])
        self.assertIn('50.0%',pages[0].description)
        self.assertIn('50.0%',pages[0].fields[0].value)
        self.assertTrue(all(len(p)<6000 for p in pages))
        report=data();report['agency']['diamonds']=0;report['managers'][0]['totals']['diamonds']=None
        self.assertIn('Unavailable',build_reports(report)[0].fields[0].value)

class ReportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def test_new_zero_creator_does_not_hide_team_daily_earnings(self):
        report = data()
        report['managers'][0]['totals']['expected'] = 2
        roster = [dict(id=name, manager='Manager 0') for name in ('active', 'new')]
        histories = {
            'active': [dict(report_date='2026-10-11',diamonds=10000,hours=10,days=3),
                       dict(report_date='2026-10-12',diamonds=19821,hours=12,days=4)],
            'new': [dict(report_date='2026-10-12',diamonds=0,hours=0,days=0)]}
        result = enrich_summary(report, roster, SimpleNamespace(creator_history=lambda creator: histories[creator]))
        self.assertEqual(result['managers'][0]['daily'],
                         dict(diamonds=9821,went_live=1,valid_days=1,active_rate=.5))
        histories['new'][0]['hours'] = 1973 / 3600
        result = enrich_summary(report, roster, SimpleNamespace(creator_history=lambda creator: histories[creator]))
        self.assertEqual(result['managers'][0]['daily']['diamonds'],9821)
        self.assertEqual(result['managers'][0]['daily']['went_live'],1)
        self.assertTrue(result['managers'][0]['daily']['went_live_partial'])

    def test_display_name_does_not_change_manager_team_matching(self):
        report = data()
        report['managers'][0].update(id='manager-id',username='vextal.manager',name='Vextal')
        roster = [dict(id='creator',manager_id='manager-id',manager='vextal.manager')]
        history = [dict(report_date='2026-10-11',diamonds=100,hours=1,days=1),
                   dict(report_date='2026-10-12',diamonds=200,hours=2,days=2)]
        result = enrich_summary(report,roster,SimpleNamespace(creator_history=lambda creator:history))
        self.assertEqual(result['managers'][0]['name'],'Vextal')
        self.assertEqual(result['managers'][0]['daily']['diamonds'],100)

    async def test_daily_posts_preserve_previous_images_and_next_date_sends_new(self):
        with tempfile.TemporaryDirectory() as root:
            db = Database(Path(root)/'db.sqlite')
            channel = FakeChannel()
            publisher = MessagePublisher(SimpleNamespace(user=SimpleNamespace(id=1)), db)
            publisher.channel = AsyncMock(return_value=channel)
            reports = ManagerReports(SimpleNamespace(database=db, publisher=publisher))
            current = data()
            with patch('manager_reports.rpc',side_effect=lambda name,**kwargs: current if name=='discord_manager_performance' else []):
                await reports.publish(report_date=current['end'], daily=True)
                await reports.publish(report_date=current['end'], daily=True)
                self.assertEqual(channel.send.await_count,1)
                channel.messages[0].edit.assert_not_awaited()
                current['end'] = '2026-10-13'
                await reports.publish(report_date=current['end'], daily=True)
                self.assertEqual(channel.send.await_count,2)
                channel.messages[0].edit.assert_not_awaited()
                await reports.publish(report_date=current['end'],daily=True,manual=True)
                await reports.publish(report_date=current['end'],daily=True,manual=True)
                self.assertEqual(channel.send.await_count,4)
                self.assertTrue(all(message.edit.await_count==0 for message in channel.messages))

    def test_manager_totals_daily_activity_and_missing_baseline(self):
        report = data(2)
        roster = [dict(id='alice', manager='Manager 0'), dict(id='bob', manager='Manager 1')]
        history = [dict(report_date='2026-10-11', diamonds=80, hours=1, days=1),
                   dict(report_date='2026-10-12', diamonds=100, hours=2, days=2)]
        db = SimpleNamespace(creator_history=lambda creator: history if creator == 'alice' else history[1:])
        enriched = enrich_summary(report, roster, db)
        first, second = enriched['managers']
        self.assertEqual(first['daily'], dict(diamonds=20, went_live=1, valid_days=1, active_rate=1))
        self.assertIsNone(second['daily']['diamonds'])
        self.assertEqual(first['creator_count'], 1)
        self.assertEqual(first['valid_days'], 2)
        history[1]['days'] = 1
        without_valid_day = enrich_summary(report, roster, db)['managers'][0]
        self.assertEqual(without_valid_day['daily']['went_live'], 1)
        self.assertEqual(without_valid_day['daily']['active_rate'], 0)
        from dashboard.manager_summary import render_manager_summary
        from io import BytesIO
        pages = render_manager_summary(enriched)
        with Image.open(BytesIO(pages[0])) as image:
            self.assertEqual(image.width, 1024)
            self.assertGreater(image.height, 1000)

    async def test_restart_updates_same_message_and_manual_is_suppressed(self):
        with tempfile.TemporaryDirectory() as root:
            db=Database(Path(root)/'db.sqlite');channel=FakeChannel()
            publisher=MessagePublisher(SimpleNamespace(user=SimpleNamespace(id=1)),db)
            publisher.channel=AsyncMock(return_value=channel)
            client=SimpleNamespace(database=db,publisher=publisher)
            with patch.object(db,'automation_channels',return_value={'manager-performance':10}),patch.object(db,'latest_import',return_value={'report_date':'2026-10-12'}),patch('manager_reports.rpc',side_effect=lambda name, **kwargs: data() if name == 'discord_manager_performance' else []):
                report=ManagerReports(client)
                self.assertEqual(await report.publish(),1)
                self.assertEqual(await report.publish(),0)
                await ManagerReports(client).publish()
                channel.send.assert_awaited_once()
                channel.messages[0].edit.assert_awaited_once()
            with patch.object(db,'automation_channels',return_value={'manager-performance':10}),patch.object(db,'latest_import',return_value={'report_date':'2026-10-12','delivery_status':'manual'}),patch('manager_reports.rpc') as rpc:
                self.assertEqual(await ManagerReports(client).publish(),0)
                rpc.assert_not_called()

class AvatarTests(unittest.TestCase):
    def test_approved_cache_refresh_and_removal(self):
        import website_avatars as avatars
        from io import BytesIO
        image=BytesIO();Image.new('RGB',(32,32),'blue').save(image,'PNG')
        creator=SimpleNamespace(creator_id='123',avatar_url='',avatar_path='')
        def update(id,url,path):creator.avatar_url=url;creator.avatar_path=path
        db=SimpleNamespace(find_creator=lambda id:creator,update_creator_avatar=update)
        profile=dict(creator_id='123',account_id='abcd',avatar_path='abcd/1234.png')
        with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',SUPABASE_URL='https://example.supabase.co',SUPABASE_SERVICE_ROLE_KEY='test'),patch.object(avatars,'AVATAR_DIR',Path(root)),patch.object(avatars,'ensure_directories'),patch.object(avatars,'rpc',return_value=[profile]),patch.object(avatars,'api',return_value={'signedURL':'/object/sign/profile-pictures/abcd/1234.png?token=private'}) as sign,patch.object(avatars,'_read_url',return_value=image.getvalue()):
            self.assertEqual(avatars._refresh_website_avatars(db),1)
            self.assertEqual(avatars._refresh_website_avatars(db),0)
            sign.assert_called_once()
            self.assertNotIn('token',Path(root,'website-revisions.json').read_text())
            import os
            os.utime(creator.avatar_path,(0,0))
            self.assertEqual(avatars._refresh_website_avatars(db),1)
            self.assertEqual(sign.call_count,2)
            profile['avatar_path']='someoneelse/1234.png'
            avatars._refresh_website_avatars(db);self.assertEqual(sign.call_count,2)
            profile['avatar_path']=None
            old=Path(creator.avatar_path);avatars._refresh_website_avatars(db)
            self.assertFalse(old.exists());self.assertEqual(creator.avatar_path,'')
    def test_handle_used_for_lookup(self):
        import avatars
        with patch.object(avatars,'find_tiktok_avatar_url',return_value=None) as lookup:
            avatars.cache_avatar('123456',username='@realhandle')
            lookup.assert_called_once_with('realhandle')

class ManagerReportRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_page_retry_recovers_and_shrink_archives_excess_pages(self):
        with tempfile.TemporaryDirectory() as root:
            db=Database(Path(root)/'test.db');channel=FakeChannel()
            publisher=MessagePublisher(SimpleNamespace(user=SimpleNamespace(id=1)),db);publisher.channel=AsyncMock(return_value=channel)
            client=SimpleNamespace(database=db,publisher=publisher);report=ManagerReports(client)
            current=data(21)
            with patch.object(db,'automation_channels',return_value={'manager-performance':10}),patch.object(db,'latest_import',return_value={'report_date':'2026-10-12'}),patch('manager_reports.rpc',side_effect=lambda name,**kwargs:current if name=='discord_manager_performance' else []):
                real=publisher.upsert
                async def uncertain(key,*args,**kwargs):
                    result=await real(key,*args,**kwargs)
                    if key=='manager-performance:1':
                        with db.connect() as conn:conn.execute("update discord_messages set message_id=null,status='pending' where message_key=?",(key,))
                        raise TimeoutError('lost acknowledgement')
                    return result
                with patch.object(publisher,'upsert',side_effect=uncertain):
                    with self.assertRaises(TimeoutError):await report.publish()
                self.assertIsNone(report.digest)
                self.assertEqual(await report.publish(),3);self.assertEqual(channel.send.await_count,3)
                current['managers']=current['managers'][:2]
                self.assertEqual(await report.publish(),1)
                self.assertEqual(db.message_record('manager-performance:1')['status'],'deleted')
                self.assertEqual(db.message_record('manager-performance:2')['status'],'deleted')
                self.assertEqual(channel.send.await_count,3)
                self.assertEqual(await report.publish(),0)
