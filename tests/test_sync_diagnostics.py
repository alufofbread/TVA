import io
import json
import unittest
from urllib.error import HTTPError
from onboarding import OnboardingError, safe_api_error, report_sync_hint


class SyncDiagnosticsTests(unittest.TestCase):
    def error(self,status,message,code=None):
        body=json.dumps({'message':message,'code':code,'details':'private-data-must-not-appear'}).encode()
        return HTTPError('https://example.supabase.co',status,'Bad Request',{},io.BytesIO(body))

    def test_manager_requirement_has_a_fixed_reason(self):
        self.assertEqual(safe_api_error(self.error(400,'Report manager must match exactly one active manager account','P0001')),'manager_account_missing_or_ambiguous')

    def test_specific_manager_diagnostics_survive_error_wrapping(self):
        messages={
            'Report manager account was not found':'manager_account_missing',
            'Report manager matches multiple eligible manager accounts':'manager_account_ambiguous',
            'Report manager matches multiple ineligible manager accounts':'manager_account_ambiguous',
            'Report manager account is banned':'manager_account_banned',
            'Report manager account is disabled without pending staff setup':'manager_account_disabled',
            'Report manager identity belongs to a non-manager account':'manager_account_wrong_role',
        }
        for message,reason in messages.items():
            with self.subTest(reason=reason):
                self.assertEqual(safe_api_error(self.error(400,message,'P0001')),reason)
                self.assertEqual(safe_api_error(OnboardingError(reason)),reason)
                self.assertNotIn('private-data',report_sync_hint(reason))
        self.assertNotIn('private-secret',report_sync_hint('private-secret'))

    def test_migration_missing(self):
        self.assertEqual(safe_api_error(self.error(404,'Private arbitrary response','PGRST202')),'database_migration_missing')

    def test_untrusted_response_cannot_leak(self):
        self.assertEqual(safe_api_error(self.error(400,'private-secret-and-account-data')),'supabase_http_400')

    def test_bad_key_and_connection_have_distinct_reasons(self):
        self.assertEqual(safe_api_error(self.error(401,'bad key')),'service_key_rejected')
        self.assertEqual(safe_api_error(OSError('private-data')),'supabase_connection_failed')
