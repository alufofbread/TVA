import io
import json
import unittest
from urllib.error import HTTPError
from onboarding import OnboardingError, safe_api_error


class SafeApiErrorTests(unittest.TestCase):
    def error(self, body):
        return HTTPError('https://fixture.supabase.co',400,'Bad Request',{},io.BytesIO(json.dumps(body).encode()))

    def test_sqlstate_survives_both_error_layers(self):
        code=safe_api_error(self.error({'code':'21000','message':'private report details'}))
        self.assertEqual(code,'supabase_sql_21000')
        self.assertEqual(safe_api_error(OnboardingError(code)),code)

    def test_invalid_codes_and_messages_are_not_logged(self):
        self.assertEqual(safe_api_error(self.error({'code':'secret-token','message':'secret-token'})),'supabase_http_400')
        self.assertEqual(safe_api_error(self.error({'code':['secret-token']})),'supabase_http_400')

    def test_specific_report_rejections(self):
        for message,code in [('Report identity conflict','report_identity_conflict'),('Invalid report metrics','invalid_report_metrics'),('Invalid report metadata','invalid_report_metadata')]:
            self.assertEqual(safe_api_error(self.error({'code':'P0001','message':message})),code)

    def test_existing_manager_diagnostic_is_preserved(self):
        self.assertEqual(safe_api_error(self.error({'code':'P0001','message':'Report manager must match exactly one active manager account'})),'manager_account_missing_or_ambiguous')
