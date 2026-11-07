import unittest,tempfile
from pathlib import Path
from datetime import date,datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from report_window import calendar_window,uk_today
from manager_reports import enrich_summary
from importer import load_creators_from_spreadsheet,ImportErrorWithContext
from dashboard.daily_graph import render_daily_graph,draw_daily_graph
from website_statistics import projection


class StatisticsRepairTests(unittest.TestCase):
    def test_seven_calendar_dates_include_empty_dates_and_today(self):
        rows=calendar_window([],end=date(2026,11,2))
        self.assertEqual([r['date'] for r in rows],[date(2026,10,27)+timedelta(days=i) for i in range(7)])
        self.assertTrue(all(row['diamonds'] is None for row in rows))

    def test_three_days_and_metric_independence(self):
        history=[dict(report_date='2026-11-01',diamonds=10,hours=None),dict(report_date='2026-11-02',diamonds=10,hours=None)]
        self.assertEqual([r['diamonds'] for r in calendar_window(history,3,end='2026-11-03')],[10,0,None])

    def test_duplicate_conflict_is_order_independent(self):
        history=[dict(report_date='2026-11-01',diamonds=x) for x in (1,2,1)]
        self.assertIsNone(calendar_window(history,3,end='2026-11-01')[-1]['diamonds'])
        self.assertIsNone(calendar_window(history[::-1],3,end='2026-11-01')[-1]['diamonds'])

    def test_downward_correction_to_zero_is_not_zero_activity(self):
        history=[dict(report_date='2026-11-01',diamonds=10),dict(report_date='2026-11-02',diamonds=0)]
        self.assertIsNone(calendar_window(history,3,end='2026-11-02')[-1]['diamonds'])

    def test_zero_missing_baseline_correction_and_month_reset(self):
        history=[dict(report_date=d,diamonds=x) for d,x in [('2026-10-30',999),('2026-10-31',998),('2026-11-01',4),('2026-11-02',None),('2026-11-03',0)]]
        self.assertEqual([r['diamonds'] for r in calendar_window(history,7,end='2026-11-03')],[None,None,None,None,4,None,0])

    def test_uk_midnight_and_dst_calendar_continuity(self):
        self.assertEqual(uk_today(datetime(2026,7,1,23,30,tzinfo=timezone.utc)),date(2026,7,2))
        for stamp in [datetime(2026,3,29,1,30,tzinfo=timezone.utc),datetime(2026,10,25,1,30,tzinfo=timezone.utc)]:
            rows=calendar_window([],now=stamp)
            self.assertEqual(len({r['date'] for r in rows}),7)
            self.assertEqual((rows[-1]['date']-rows[0]['date']).days,6)

    def test_graph_draws_every_date_label_including_missing(self):
        rows=calendar_window([],7,end='2026-11-03')
        with patch('dashboard.daily_graph.line'),patch('dashboard.daily_graph.text') as text:
            draw_daily_graph(SimpleNamespace(),rows,(100,50,900,300))
        labels=[call.args[2] for call in text.call_args_list if call.args[2] in [r['date'].strftime('%d %b') for r in rows]]
        self.assertEqual(labels,[r['date'].strftime('%d %b') for r in rows])

    def test_large_diamonds_real_image(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            file=render_daily_graph(SimpleNamespace(creator_name='ISOLATED QA'),[dict(report_date='2026-11-01',diamonds=12_000_000)],Path(folder)/'chart.png',end='2026-11-03')
            with Image.open(file) as image:self.assertEqual(image.size,(1024,420))

    def test_manager_id_wins_over_a_matching_display_name(self):
        report=dict(start='2026-11-01',end='2026-11-02',agency=dict(diamonds=None),managers=[dict(id='real',name='Alias',totals=dict(expected=1,diamonds=None))])
        roster=[dict(id='a',manager_id='other',manager='Alias')]
        result=enrich_summary(report,roster,SimpleNamespace(creator_history=lambda _:[]))
        self.assertIsNone(result['managers'][0]['daily']['diamonds'])
        self.assertEqual(result['managers'][0]['coverage']['diamonds']['expected'],0)

    def test_partial_coverage_never_relabels_subtotal_as_total(self):
        report=dict(start='2026-11-01',end='2026-11-02',agency=dict(diamonds=None),managers=[dict(id='m',name='Manager',totals=dict(expected=2,diamonds=None,valid_days=None))])
        roster=[dict(id=x,manager_id='m') for x in ('a','b')]
        history={'a':[dict(report_date='2026-11-02',diamonds=42,hours=0,days=0)],'b':[]}
        result=enrich_summary(report,roster,SimpleNamespace(creator_history=lambda id:history[id]))
        self.assertIsNone(result['agency']['diamonds'])
        self.assertEqual(result['coverage']['diamonds'],dict(known_total=42,reported=1,expected=2,missing_creator_ids=['b']))

    def test_all_unknown_activity_never_displays_zero(self):
        report=dict(start='2026-11-01',end='2026-11-02',agency=dict(diamonds=None),managers=[dict(id='m',name='Manager',totals=dict(expected=1,diamonds=None))])
        result=enrich_summary(report,[dict(id='a',manager_id='m')],SimpleNamespace(creator_history=lambda _:[dict(report_date='2026-11-02',diamonds=None,hours=None,days=None)]))
        self.assertIsNone(result['managers'][0]['daily']['went_live'])

    def test_no_imported_records_remain_missing(self):
        report=dict(start='2026-11-01',end='2026-11-02',agency=dict(diamonds=None),managers=[dict(id='m',name='Manager',totals=dict(expected=1,diamonds=None))])
        result=enrich_summary(report,[dict(id='a',manager_id='m')],SimpleNamespace(creator_history=lambda _:[]))
        self.assertIsNone(result['managers'][0]['daily']['diamonds'])
        self.assertIsNone(result['managers'][0]['valid_days'])

    def report(self,folder,rows):
        p=Path(folder)/'report.csv';p.write_text('Creator ID,Creator,Diamonds,Hours,Days,Battles,Data period\n'+rows,encoding='utf-8');return p

    def test_overlapping_mtd_snapshots_select_latest_without_sum(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.report(folder,'id,Alice,100,1,1,0,2026-10-01 ~ 2026-10-04\nid,Alice,150,2,2,0,2026-10-01 ~ 2026-10-05\n')
            self.assertEqual(load_creators_from_spreadsheet(p,cache_avatars=False)[0][0]['diamonds'],150)

    def test_conflicting_duplicate_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.report(folder,'id,Alice,100,1,1,0,2026-10-05\nid,Alice,150,2,2,0,2026-10-05\n')
            with self.assertRaises(ImportErrorWithContext):load_creators_from_spreadsheet(p,cache_avatars=False)

    def test_missing_metric_is_rejected_and_zero_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.report(folder,'id,Alice,,1,1,0,2026-10-05\n')
            with self.assertRaises(ImportErrorWithContext):load_creators_from_spreadsheet(p,cache_avatars=False)
            p=self.report(folder,'id,Alice,0,0,0,0,2026-10-05\n')
            self.assertEqual(load_creators_from_spreadsheet(p,cache_avatars=False)[0][0]['diamonds'],0)

    def test_projection_requires_all_published_requirements(self):
        rules=[dict(rank=1,name='Published',requirements=[dict(type='diamonds',value=10),dict(type='hours',value=2)])]
        self.assertIsNone(projection(dict(rules=rules,diamonds=100,hours=None))[0])
        self.assertEqual(projection(dict(rules=rules,diamonds=100,hours=2))[0]['name'],'Published')

    def test_authoritative_context_does_not_mix_local_history(self):
        report=dict(start='2026-11-01',end='2026-11-02',agency=dict(diamonds=0),managers=[dict(id='m',name='Manager',totals=dict(expected=1,diamonds=0,valid_days=0))])
        history=[dict(report_date='2026-11-01',diamonds=0,hours=0,days=0),dict(report_date='2026-11-02',diamonds=0,hours=0,days=0)]
        source=dict(creators=[dict(id='a',history=history,diamonds=0,hours=0,days=0)])
        def forbidden(_):raise AssertionError('Authoritative contract must not query stale local history')
        result=enrich_summary(report,[dict(id='a',manager_id='m')],SimpleNamespace(creator_history=forbidden),source=source)
        self.assertEqual(result['managers'][0]['daily']['diamonds'],0)
        self.assertEqual(result['managers'][0]['valid_days'],0)

    def test_complete_report_excludes_departed_creators_without_deleting_history(self):
        report=dict(start='2026-11-01',end='2026-11-02',agency=dict(diamonds=20),managers=[dict(id='m',name='Manager',totals=dict(expected=1,diamonds=20,valid_days=1))])
        roster=[dict(id=id,manager_id='m') for id in ('active','departed')]
        source=dict(complete_roster=True,creators=[dict(id='active',active=True,diamonds=20,hours=1,days=1,history=[dict(report_date='2026-11-01',diamonds=10,hours=0,days=0),dict(report_date='2026-11-02',diamonds=20,hours=1,days=1)]),dict(id='departed',active=False,history=[])])
        result=enrich_summary(report,roster,SimpleNamespace(creator_history=lambda _:[]),source=source)
        self.assertEqual(result['coverage']['diamonds']['expected'],1)
        self.assertEqual(result['managers'][0]['daily']['diamonds'],10)
        self.assertEqual(result['managers'][0]['creator_count'],1)
        self.assertEqual(len(roster),2)


if __name__=='__main__':unittest.main()
