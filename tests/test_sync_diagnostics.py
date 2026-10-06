import io
import json
import unittest
from urllib.error import HTTPError
from onboarding import safe_api_error


class SyncDiagnosticsTests(unittest.TestCase):
    def error(self,status,message,code=None):
        body=json.dumps({'message':message,'code':code,'details':'private-data-must-not-appear'}).encode()
        return HTTPError('https://example.supabase.co',status,'Bad Request',{},io.BytesIO(body))

    def test_manager_requirement_has_a_fixed_reason(self):
        self.assertEqual(safe_api_error(self.error(400,'Report manager must match exactly one active manager account','P0001')),'manager_account_missing_or_ambiguous')

    def test_migration_missing(self):
        self.assertEqual(safe_api_error(self.error(404,'Private arbitrary response','PGRST202')),'database_migration_missing')

    def test_untrusted_response_cannot_leak(self):
        self.assertEqual(safe_api_error(self.error(400,'private-secret-and-account-data')),'supabase_http_400')

    def test_bad_key_and_connection_have_distinct_reasons(self):
        self.assertEqual(safe_api_error(self.error(401,'bad key')),'service_key_rejected')
        self.assertEqual(safe_api_error(OSError('private-data')),'supabase_connection_failed')
