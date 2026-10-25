import unittest
from types import SimpleNamespace
from manager_reports import enrich_summary
from summary_membership import membership_at
from database import Database
from pathlib import Path
import json
import tempfile


class DepartureSummaryTests(unittest.TestCase):
    def summary(self, end='2026-10-23'):
        return dict(start=end[:7]+'-01', end=end, agency=dict(diamonds=None), managers=[
            dict(id='cam', name='Cam', totals=dict(diamonds=None, expected=2))])

    def run_summary(self, end='2026-10-23', active=True, status=None):
        roster=[dict(id='1',handle='former',manager_id='cam'),dict(id='2',handle='current',manager_id='cam')]
        histories={'1':[dict(report_date='2026-10-17',diamonds=1114,hours=2,days=1),
                        dict(report_date='2026-10-18',diamonds=2042,hours=4,days=2)],
                   '2':[dict(report_date=end[:7]+'-22',diamonds=1538,hours=3,days=2),
                        dict(report_date=end,diamonds=1538,hours=3,days=2)] if active else []}
        return enrich_summary(self.summary(end),roster,SimpleNamespace(creator_history=lambda id:histories[id]),
                              {'former': status or dict(active=False,observed_on='2026-10-19')})

    def test_retains_last_month_total_once_and_excludes_departed_from_active_count(self):
        result=self.run_summary()
        manager=result['managers'][0]
        self.assertEqual(manager['totals']['diamonds'],3580)
        self.assertEqual(result['agency']['diamonds'],3580)
        self.assertEqual(manager['creator_count'],1)
        self.assertEqual(manager['valid_days'],4)
        self.assertEqual(manager['daily']['diamonds'],0)
        self.assertEqual(manager['daily']['active_rate'],0)

    def test_missing_active_creator_is_still_unknown(self):
        self.assertIsNone(self.run_summary(active=False)['agency']['diamonds'])

    def test_no_previous_month_earnings_carried_forward(self):
        self.assertEqual(self.run_summary('2026-11-23')['agency']['diamonds'],1538)

    def test_rejoined_creator_requires_current_report(self):
        self.assertIsNone(self.run_summary(status=dict(active=True,observed_on='2026-10-22'))['managers'][0]['totals']['diamonds'])

    def test_legacy_departure_is_recovered_and_future_events_do_not_leak(self):
        with tempfile.TemporaryDirectory() as root:
            db=Database(Path(root)/'test.db')
            from website_sync import initialize
            with db.connect() as conn:
                initialize(conn)
                conn.execute("INSERT INTO import_runs(id,report_date,imported_at,snapshot_hash,filename,creator_count) VALUES(1,'2026-10-19','2026-10-20T00:00:00Z','a','a',1)")
                payload=dict(creators=[dict(id='2',handle='current')],report=dict(end='2026-10-19',records=[]))
                conn.execute('INSERT INTO website_report_outbox(import_id,payload) VALUES(?,?)',(1,json.dumps(payload)))
                person=dict(creator_id='The creator has quit the network',creator_name='former')
                conn.execute('INSERT INTO creator_snapshots VALUES(?,?,?,?)',('The creator has quit the network','2026-10-19',1,json.dumps(person)))
            self.assertFalse(membership_at(db,'2026-10-23')['former']['active'])
            self.assertEqual(membership_at(db,'2026-10-18'),{})
