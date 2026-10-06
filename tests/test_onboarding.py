import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import onboarding


class ProvisionTests(unittest.TestCase):
    def test_conflicting_login_is_not_taken_over(self):
        job={'network_confirmed_at':'confirmed','application_status':'accepted','application_id':'app','handle':'new.creator','lease_id':'lease'}
        address='u'+'new.creator'.encode().hex()+'@accounts.aether.invalid'
        with patch.object(onboarding,'api',return_value={'users':[{'email':address,'id':'existing','app_metadata':{}}]}),patch.object(onboarding,'rpc') as rpc:
            with self.assertRaisesRegex(onboarding.OnboardingError,'existing_login_conflict'):onboarding.provision(job)
            rpc.assert_not_called()

    def test_retry_recovers_owned_auth_user(self):
        job={'network_confirmed_at':'confirmed','application_status':'accepted','application_id':'app','handle':'new.creator','lease_id':'lease'}
        address='u'+'new.creator'.encode().hex()+'@accounts.aether.invalid'
        user={'email':address,'id':'owned','app_metadata':{'onboarding_application':'app'}}
        with patch.object(onboarding,'api',return_value={'users':[user]}) as api,patch.object(onboarding,'rpc') as rpc:
            self.assertEqual(onboarding.provision(job),user)
            api.assert_called_once();rpc.assert_called_once_with('bind_onboarding_account',application='app',lease='lease',auth_account='owned')


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_then_email_then_creator(self):
        job={'network_confirmed_at':'confirmed','stage':'queued','application_id':'app','lease_id':'lease'}
        events=[]
        async def sync(client,job,complete=False):events.append('creator' if complete else 'pending')
        def provision(job):events.append('account');return {'id':'user'}
        def invite(job,user):events.append('link')
        def send(job):events.append('email')
        with patch.object(onboarding,'provision',side_effect=provision),patch.object(onboarding,'invite',side_effect=invite),patch.object(onboarding,'send_invite',side_effect=send),patch.object(onboarding,'sync_discord',side_effect=sync),patch.object(onboarding,'rpc') as rpc:
            await onboarding.process(None,job)
            self.assertEqual(events,['pending','account','link','email'])
            self.assertEqual(rpc.call_args.kwargs['new_stage'],'invite_sent')

    async def test_email_failure_keeps_pending_and_retries(self):
        job={'network_confirmed_at':'confirmed','stage':'invite_ready','application_id':'app','lease_id':'lease'}
        with patch.object(onboarding,'provision',return_value={'id':'user'}),patch.object(onboarding,'invite') as invite,patch.object(onboarding,'send_invite',side_effect=onboarding.OnboardingError('email_delivery_failed')),patch.object(onboarding,'sync_discord',new=AsyncMock()) as sync,patch.object(onboarding,'rpc') as rpc:
            await onboarding.process(None,job)
            invite.assert_not_called();sync.assert_not_called()
            rpc.assert_called_once_with('fail_onboarding',application='app',lease='lease',error='email_delivery_failed')

    async def test_resume_after_email_does_not_resend(self):
        job={'password_ready_at':'saved','network_confirmed_at':'confirmed','stage':'invite_sent','application_id':'app','lease_id':'lease'}
        with patch.object(onboarding,'provision',return_value={'id':'user'}),patch.object(onboarding,'send_invite') as send,patch.object(onboarding,'sync_discord',new=AsyncMock()) as sync,patch.object(onboarding,'rpc') as rpc:
            await onboarding.process(None,job)
            send.assert_not_called();sync.assert_awaited_once_with(None,job,complete=True)
            self.assertEqual(rpc.call_args.kwargs['new_stage'],'complete')

    async def test_scout_stage_never_creates_account_or_discord_role(self):
        job={'stage':'choose_manager','application_id':'app','lease_id':'lease'}
        with patch.object(onboarding,'send_manager_choice') as send,patch.object(onboarding,'provision') as provision,patch.object(onboarding,'sync_discord',new=AsyncMock()) as sync,patch.object(onboarding,'rpc') as rpc:
            await onboarding.process(None,job)
            send.assert_called_once();provision.assert_not_called();sync.assert_not_called()
            self.assertEqual(rpc.call_args.args[0],'mark_choice_email_sent')

    async def test_unconfirmed_network_never_creates_auth_account(self):
        job={'stage':'awaiting_network','application_id':'app','lease_id':'lease'}
        with patch.object(onboarding,'provision') as provision,patch.object(onboarding,'sync_discord',new=AsyncMock()) as sync,patch.object(onboarding,'rpc') as rpc:
            await onboarding.process(None,job)
            provision.assert_not_called();sync.assert_not_called()
            self.assertEqual(rpc.call_args.kwargs['error'],'network_not_confirmed')

    async def test_email_sent_waits_for_password_before_creator_role(self):
        job={'stage':'invite_sent','network_confirmed_at':'confirmed','application_id':'app','lease_id':'lease'}
        with patch.object(onboarding,'provision',return_value={'id':'user'}),patch.object(onboarding,'sync_discord',new=AsyncMock()) as sync,patch.object(onboarding,'rpc') as rpc:
            await onboarding.process(None,job)
            sync.assert_not_called();rpc.assert_not_called()

    async def test_role_replacement_preserves_other_roles(self):
        class Role:
            managed=False
            permissions=SimpleNamespace(administrator=False)
            def __init__(self,id):self.id=id
            def is_default(self):return False
            def __ge__(self,other):return False
        pending,creator,unrelated=Role(1),Role(2),Role(3)
        member=SimpleNamespace(bot=False,roles=[pending,unrelated],add_roles=AsyncMock(),remove_roles=AsyncMock())
        guild=SimpleNamespace(me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True),top_role=Role(9)),get_role=lambda id:{1:pending,2:creator}[id],fetch_member=AsyncMock(return_value=member))
        client=SimpleNamespace(get_guild=lambda id:guild)
        with patch.dict('os.environ',{'DISCORD_GUILD_ID':'123','ONBOARDING_PENDING_ROLE_ID':'1','ONBOARDING_CREATOR_ROLE_ID':'2'}):
            await onboarding.sync_discord(client,{'discord_user_id':'123456789012345678'},complete=True)
        self.assertEqual(member.add_roles.call_args.args,(creator,));self.assertEqual(member.remove_roles.call_args.args,(pending,))
