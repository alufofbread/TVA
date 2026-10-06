import unittest
from test_importer import ReportFixture
from unittest.mock import patch
from importer import import_spreadsheet


class AchievementTests(ReportFixture, unittest.TestCase):
    def test_milestone_and_pb_are_deduplicated(self):
        with patch('achievements.ANNOUNCE_ACHIEVEMENTS', {'milestone','pb'}):
            import_spreadsheet(self.db, self.report(1000, '2026-09-01'))
            import_spreadsheet(self.db, self.report(110000, '2026-09-02'))
            import_spreadsheet(self.db, self.report(110000, '2026-09-02'))
        with self.db.connect() as conn:
            wins = conn.execute("SELECT * FROM achievements WHERE publish=1").fetchall()
        self.assertEqual(sum(r['kind'] == 'milestone' for r in wins), 1)
        self.assertEqual(sum(r['kind'] == 'pb' for r in wins), 1)

    def test_initial_baseline_and_manual_import_are_silent(self):
        with patch('achievements.ANNOUNCE_ACHIEVEMENTS', {'milestone','pb'}):
            import_spreadsheet(self.db, self.report(110000, '2026-09-01'))
            import_spreadsheet(self.db, self.report(300000, '2026-09-02'), publish=False)
        with self.db.connect() as conn:
            self.assertGreater(conn.execute('SELECT COUNT(*) FROM achievements').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM achievements WHERE publish=1').fetchone()[0], 0)
    def test_rank_league_and_incentive_changes(self):
        import pandas as pd
        path = self.report(500, '2026-09-01')
        frame = pd.read_csv(path)
        frame['Diamonds last month'] = [0, 0]
        frame.to_csv(path, index=False)
        import_spreadsheet(self.db, path)
        path = self.report(300000, '2026-09-22')
        frame = pd.read_csv(path)
        frame.loc[0, ['Hours', 'Days']] = [90, 22]
        frame['Diamonds last month'] = [200000, 0]
        frame.to_csv(path, index=False)
        with patch('achievements.ANNOUNCE_ACHIEVEMENTS', {'rank', 'league', 'incentive'}):
            import_spreadsheet(self.db, path)
            import_spreadsheet(self.db, path)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT kind FROM achievements WHERE creator_id='alice' AND publish=1").fetchall()
        self.assertEqual(sorted(r['kind'] for r in rows), ['incentive', 'league', 'rank'])
        self.assertEqual(self.db.creator_history('alice')[-1]['rank_movement'], 1)
