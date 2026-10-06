import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from database import Database, referral_reward_for_diamonds
from importer import ImportErrorWithContext, import_spreadsheet, load_creators_from_spreadsheet


class ReportFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / 'test.db')
        self.avatar = patch('importer.cache_avatar', return_value=None)
        self.avatar.start()
        self.addCleanup(self.avatar.stop)

    def report(self, diamonds=20000, day='2026-09-10', name='report.csv'):
        path = self.root / name
        path.write_text("Creator ID,Creator,Diamonds,Hours,Days,Battles,Data period,Join time\n"
                        f"alice,Alice,{diamonds},20,10,5,{day},2026-09-01\n"
                        f"bob,Bob,1000,5,2,1,{day},2026-09-01\n", encoding='utf-8')
        return path


class ImportTests(ReportFixture, unittest.TestCase):
    def test_csv_ranking_mapping_and_avatar_survive(self):
        path = self.report()
        result = import_spreadsheet(self.db, path, date(2026, 9, 10))
        self.assertEqual(result.creator_count, 2)
        self.assertEqual(self.db.get_creators()[0].creator_id, 'alice')
        self.db.set_creator_channel('alice', 123, 456)
        self.db.update_creator_avatar('alice', 'manual-upload', 'avatar.jpg')
        import_spreadsheet(self.db, path, date(2026, 9, 10))
        self.assertEqual(self.db.get_creator_channels()[0].channel_id, 123)
        self.assertEqual(self.db.find_creator('alice').avatar_path, 'avatar.jpg')

    def test_duplicate_does_not_reapply_referrals(self):
        path = self.report()
        import_spreadsheet(self.db, path, date(2026, 9, 10))
        self.db.add_referral(self.db.find_creator('bob'), self.db.find_creator('alice'), 'Alice', date(2026, 9, 1))
        path = self.report(30000, '2026-09-11')
        import_spreadsheet(self.db, path, date(2026, 9, 11))
        with patch.object(self.db, 'update_referrals_from_snapshot') as update:
            result = import_spreadsheet(self.db, path, date(2026, 9, 11))
        self.assertTrue(result.duplicate)
        update.assert_not_called()
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('SELECT diamonds FROM referrals').fetchone()[0], 30000)

    def test_invalid_report_preserves_snapshot(self):
        import_spreadsheet(self.db, self.report(), date(2026, 9, 10))
        invalid = self.root / 'invalid.csv'
        invalid.write_text('Creator,Diamonds\nAlice,99\n')
        with self.assertRaises(ImportErrorWithContext):
            import_spreadsheet(self.db, invalid)
        self.assertEqual(self.db.find_creator('alice').diamonds, 20000)

    def test_excel_and_csv_agree(self):
        import pandas as pd
        csv = self.report()
        excel = self.root / 'report.xlsx'
        pd.read_csv(csv).to_excel(excel, index=False)
        self.assertEqual(load_creators_from_spreadsheet(csv)[0], load_creators_from_spreadsheet(excel)[0])

    def test_reward_boundaries(self):
        self.assertEqual(referral_reward_for_diamonds(14999), (0, 0))
        self.assertEqual(referral_reward_for_diamonds(15000), (1, 5))
        self.assertEqual(referral_reward_for_diamonds(500000), (6, 65))


if __name__ == '__main__':
    unittest.main()
