from datetime import date
from unittest.mock import patch
import unittest
from test_importer import ReportFixture
from history import daily_points


class HistoryTests(ReportFixture, unittest.TestCase):
    def test_effective_date_and_csv_history(self):
        from importer import import_spreadsheet
        result = import_spreadsheet(self.db, self.report())
        self.assertEqual(result.report_date, date(2026, 9, 10))
        self.assertEqual(self.db.creator_history('alice')[0]['report_date'], '2026-09-10')
        self.assertEqual(len(self.db.missing_creator_channels()), 2)
        import_spreadsheet(self.db, self.report(25000, '2026-09-11'))
        self.assertEqual(daily_points(self.db.creator_history('alice'))[0]['diamonds'], 5000)

    def test_import_rollback_on_referral_failure(self):
        from importer import import_spreadsheet
        import_spreadsheet(self.db, self.report())
        with patch.object(self.db, 'update_referrals_from_snapshot', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                import_spreadsheet(self.db, self.report(50000, '2026-09-11'))
        self.assertEqual(self.db.find_creator('alice').diamonds, 20000)
        self.assertEqual(len(self.db.creator_history('alice')), 1)

    def test_duplicate_and_older_reports(self):
        from importer import import_spreadsheet, ImportErrorWithContext
        import_spreadsheet(self.db, self.report())
        self.assertTrue(import_spreadsheet(self.db, self.report()).duplicate)
        self.assertEqual(len(self.db.creator_history('alice')), 1)
        with self.assertRaises(ImportErrorWithContext):
            import_spreadsheet(self.db, self.report(1000, '2026-09-09'))

    def test_missing_date_is_explicit_error(self):
        from importer import import_spreadsheet, ImportErrorWithContext
        path = self.report(day='')
        with self.assertRaises(ImportErrorWithContext):
            import_spreadsheet(self.db, path)
        self.assertEqual(import_spreadsheet(self.db, path, date(2026, 9, 10)).report_date, date(2026, 9, 10))

    def test_gaps_and_resets_do_not_invent_daily_records(self):
        rows = [dict(report_date=d, diamonds=n, hours=0, new_followers=0) for d,n in
                [('2026-08-30', 100), ('2026-09-01', 10), ('2026-09-03', 200), ('2026-09-04', 150)]]
        self.assertEqual(daily_points(rows), [dict(report_date='2026-09-01', diamonds=10, hours=0, new_followers=0)])
    def test_same_date_correction_and_superseded_version(self):
        from importer import import_spreadsheet, ImportErrorWithContext
        first = self.report(1000, name='first.csv')
        import_spreadsheet(self.db, first)
        import_spreadsheet(self.db, self.report(2000, name='corrected.csv'))
        self.assertEqual(len(self.db.creator_history('alice')), 1)
        self.assertEqual(self.db.creator_history('alice')[0]['diamonds'], 2000)
        with self.assertRaises(ImportErrorWithContext):
            import_spreadsheet(self.db, first)

    def test_report_date_conflict_is_rejected(self):
        from importer import import_spreadsheet, ImportErrorWithContext
        with self.assertRaises(ImportErrorWithContext):
            import_spreadsheet(self.db, self.report(), date(2026, 9, 11))

    def test_history_failure_rolls_back_all_import_tables(self):
        from importer import import_spreadsheet
        with patch('achievements.record_achievements', side_effect=RuntimeError('database error')):
            with self.assertRaises(RuntimeError):
                import_spreadsheet(self.db, self.report())
        self.assertEqual(self.db.get_creators(), [])
        self.assertIsNone(self.db.latest_import())
        self.assertEqual(self.db.creator_history('alice'), [])

    def test_month_reset_and_same_month_referral_correction(self):
        from importer import import_spreadsheet
        import_spreadsheet(self.db, self.report(10000, '2026-08-31'))
        self.db.add_referral(self.db.find_creator('bob'), self.db.find_creator('alice'), 'Alice', date(2026, 8, 20))
        import_spreadsheet(self.db, self.report(2000, '2026-09-01'))
        import_spreadsheet(self.db, self.report(1500, '2026-09-01'))
        with self.db.connect() as conn:
            referral = conn.execute('SELECT * FROM referrals').fetchone()
        self.assertEqual(referral['diamonds'], 11500)
        self.assertEqual(referral['last_report_date'], '2026-09-01')
