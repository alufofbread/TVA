import unittest
from unittest.mock import patch
from import_members import provision_members
from onboarding import OnboardingError
import tempfile
from pathlib import Path
from datetime import date
from importer import load_creators_from_spreadsheet


class ImportMemberTests(unittest.TestCase):
    def test_report_manager_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.csv'
            path.write_text("Creator ID,Creator,Diamonds,Hours,Days,Battles,Creator Network manager\n123,alice,1,1,1,1,manager.handle\n",encoding='utf8')
            creators,_=load_creators_from_spreadsheet(path,date(2026,9,1),cache_avatars=False)
            self.assertEqual(creators[0]['manager'],'manager.handle')

    def roster(self):return [{'id':'123','handle':'alice','account_id':None}]

    def test_create_and_bind(self):
        with patch('import_members.rpc',side_effect=[self.roster(),None]) as rpc,patch('import_members.api',side_effect=[{'users':[]},{'id':'new'}]) as api:
            provision_members()
            rpc.assert_any_call('bind_import_member',creator='123',auth_account='new')
            body=api.call_args.args[1]
            self.assertEqual(body['email'],'u616c696365@accounts.aether.invalid')
            self.assertEqual(body['app_metadata'],{'import_creator':'123','initial_password_change_required':True})
            self.assertEqual(body['password'],'Password01')

    def test_recover_created_login_without_resetting_password(self):
        with patch('import_members.rpc',side_effect=[self.roster(),None]),patch('import_members.api',return_value={'users':[{'id':'saved','email':'u616c696365@accounts.aether.invalid','app_metadata':{'import_creator':'123'}}]}) as api:
            provision_members()
            api.assert_called_once()

    def test_conflicting_login_cannot_be_claimed(self):
        with patch('import_members.rpc',return_value=self.roster()),patch('import_members.api',return_value={'users':[{'id':'other','email':'u616c696365@accounts.aether.invalid'}]}):
            with self.assertRaises(OnboardingError):provision_members()

    def test_existing_account_is_preserved(self):
        with patch('import_members.rpc',return_value=[{'id':'123','handle':'alice','account_id':'saved'}]),patch('import_members.api') as api:
            provision_members()
            api.assert_not_called()
