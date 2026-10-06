"""Server-only, recoverable accepted-application provisioning and Discord sync."""
import asyncio
import json
import logging
import os
import re
import secrets
import urllib.request
import urllib.error


class OnboardingError(RuntimeError):
    pass


def safe_api_error(error):
    """Return fixed diagnostic codes; never echo server bodies or credentials."""
    if isinstance(error,urllib.error.HTTPError):
        try:
            result=json.loads(error.read(16384))
        except Exception:result={}
        messages={
            'Report manager must match exactly one active manager account':'manager_account_missing_or_ambiguous',
            'Report manager has no active manager account':'manager_account_missing_or_ambiguous',
            'Import login conflict':'existing_login_conflict',
            'Creator already has an account':'existing_login_conflict',
            'Creator password unavailable':'creator_password_unavailable',
            'Account already assigned':'existing_login_conflict',
        }
        if isinstance(result,dict):
            if result.get('message') in messages:return messages[result['message']]
            code=result.get('code')
            if code in ('PGRST202','PGRST205','42883','42P01','42703'):return 'database_migration_missing'
            if code=='42501':return 'service_key_permissions'
            if code=='23505':return 'account_or_report_conflict'
        if error.code in (401,403):return 'service_key_rejected'
        if error.code==429:return 'supabase_rate_limited'
        return 'supabase_http_'+str(error.code)
    if isinstance(error,OnboardingError) and str(error) in {
        'supabase_not_configured','invalid_import_handle','existing_login_conflict',
        'supabase_request_failed','database_migration_missing','service_key_permissions',
        'account_or_report_conflict','service_key_rejected','supabase_rate_limited',
        'manager_account_missing_or_ambiguous','creator_password_unavailable'}:
        return str(error)
    if isinstance(error,(OSError,TimeoutError)):return 'supabase_connection_failed'
    return 'supabase_request_failed'


def api(path, body=None, method=None):
    url=os.environ.get('SUPABASE_URL','').rstrip('/')
    key=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
    if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co',url) or not key:
        raise OnboardingError('supabase_not_configured')
    headers={'apikey':key,'Content-Type':'application/json'}
    if key.startswith('eyJ'):headers['Authorization']='Bearer '+key
    request=urllib.request.Request(url+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
    try:
        with urllib.request.urlopen(request,timeout=20) as response:
            raw=response.read()
            return json.loads(raw) if raw else None
    except Exception as error:
        # Response bodies may contain credentials or PII; never log them.
        raise OnboardingError(safe_api_error(error)) from None


def rpc(name,**body):
    return api('/rest/v1/rpc/'+name,body)


def provision(job):
    if not job.get('network_confirmed_at'):raise OnboardingError('network_not_confirmed')
    if job['application_status']!='accepted':raise OnboardingError('application_not_accepted')
    handle=job['handle']
    if not re.fullmatch(r'[a-z0-9_.]{2,24}',handle):raise OnboardingError('invalid_handle')
    address='u'+handle.encode('ascii').hex()+'@accounts.aether.invalid'
    user=None
    if job.get('account_id'):
        user=api('/auth/v1/admin/users/'+job['account_id'])
    else:
        page=1
        while True:
            users=api(f'/auth/v1/admin/users?page={page}&per_page=200')['users']
            user=next((u for u in users if u.get('email','').lower()==address),None)
            if user or len(users)<200:break
            page+=1
        if user and user.get('app_metadata',{}).get('onboarding_application')!=job['application_id']:
            raise OnboardingError('existing_login_conflict')
        if not user:
            user=api('/auth/v1/admin/users',{'email':address,'password':secrets.token_urlsafe(48),'email_confirm':True,
                'app_metadata':{'onboarding_application':job['application_id']}},'POST')
    user=user.get('user',user)
    if user.get('app_metadata',{}).get('onboarding_application')!=job['application_id']:
        raise OnboardingError('existing_login_conflict')
    rpc('bind_onboarding_account',application=job['application_id'],lease=job['lease_id'],auth_account=user['id'])
    return user


def invite(job,user):
    link=api('/auth/v1/admin/generate_link',{'type':'recovery','email':user['email']},'POST')
    token=link.get('hashed_token') or link.get('properties',{}).get('hashed_token')
    if not token or not re.fullmatch(r'[a-fA-F0-9]+',token):raise OnboardingError('invite_generation_failed')
    url='https://aetherlivestudio.app/accept-invite.html#token_hash='+token
    rpc('update_onboarding',application=job['application_id'],lease=job['lease_id'],new_stage='invite_ready',setup_url=url)


def send_email(job,subject,text,generation):
    key=os.environ.get('RESEND_API_KEY','')
    sender=os.environ.get('ONBOARDING_EMAIL_FROM','')
    if not key or not sender:raise OnboardingError('email_not_configured')
    body={'from':sender,'to':[job['email']],'subject':subject,'text':text}
    request=urllib.request.Request('https://api.resend.com/emails',data=json.dumps(body).encode(),method='POST',
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Idempotency-Key':'onboarding/'+generation})
    try:
        with urllib.request.urlopen(request,timeout=20) as response:
            if not json.load(response).get('id'):raise ValueError('No acknowledgement')
    except Exception:raise OnboardingError('email_delivery_failed') from None


def send_manager_choice(job):
    url=job.get('choice_url','')
    if not re.fullmatch(r'https://aetherlivestudio[.]app/choose-manager[.]html#token=[a-f0-9]{64}',url):
        raise OnboardingError('manager_choice_link_missing')
    send_email(job,'Choose your Aether manager',
        f"Your Aether application has been approved for the next stage.\n\nChoose and confirm your manager using this private link:\n{url}\n\nYour manager choice will be locked. You will then receive their TikTok scout link. TikTok must accept you into the network before we create your Aether account.\n",'manager-choice/'+job['application_id'])


def send_invite(job):
    saved=rpc('read_onboarding_invite',application=job['application_id'],lease=job['lease_id'])
    if not saved:raise OnboardingError('invite_missing')
    send_email(job,'Set up your Aether creator account',
        f"Your TikTok network acceptance has been confirmed.\n\nSet your password using this private one-time link:\n{saved['setup_url']}\n\nSign in with your TikTok handle: @{job['handle']}\n\nYou will keep Pending until you save your password and Discord setup finishes. If the link expires, ask Aether for a fresh invitation.\n",saved['generation'])


async def sync_discord(client,job,complete=False):
    guild=client.get_guild(int(os.environ.get('DISCORD_GUILD_ID','0')))
    role_id=os.environ.get('ONBOARDING_CREATOR_ROLE_ID' if complete else 'ONBOARDING_PENDING_ROLE_ID','')
    if not guild or not role_id.isdigit():raise OnboardingError('discord_role_not_configured')
    pending_id=os.environ.get('ONBOARDING_PENDING_ROLE_ID','')
    if complete and (not pending_id.isdigit() or pending_id==role_id):raise OnboardingError('discord_roles_must_differ')
    role=guild.get_role(int(role_id))
    if not role or role.is_default() or role.managed or role.permissions.administrator:
        raise OnboardingError('invalid_creator_role')
    if not guild.me or not guild.me.guild_permissions.manage_roles or role>=guild.me.top_role:
        raise OnboardingError('discord_role_permissions')
    pending=guild.get_role(int(pending_id)) if pending_id.isdigit() else None
    if complete and (not pending or pending.is_default() or pending.managed or pending.permissions.administrator or pending>=guild.me.top_role):
        raise OnboardingError('discord_pending_role_permissions')
    try:
        member=await guild.fetch_member(int(job['discord_user_id']))
        if member.bot:raise OnboardingError('discord_member_is_bot')
        if role not in member.roles:await member.add_roles(role,reason='Aether accepted-application onboarding')
        if complete:
            if pending and pending!=role and pending in member.roles:await member.remove_roles(pending,reason='Aether onboarding completed')
    except OnboardingError:raise
    except Exception:raise OnboardingError('discord_member_or_permissions') from None


async def process(client,job):
    stage=job['stage']
    try:
        if stage=='choose_manager':
            await asyncio.to_thread(send_manager_choice,job)
            await asyncio.to_thread(rpc,'mark_choice_email_sent',application=job['application_id'],lease=job['lease_id'])
            return
        if stage=='awaiting_network' or not job.get('network_confirmed_at'):
            raise OnboardingError('network_not_confirmed')
        if stage in ('network_confirmed','queued','account_created'):
            # Verify guild membership before creating an Auth account. Role grants
            # are idempotent and only happen after explicit network confirmation.
            await sync_discord(client,job)
            await asyncio.to_thread(rpc,'mark_onboarding_pending',application=job['application_id'],lease=job['lease_id'])
        user=await asyncio.to_thread(provision,job)
        stage='account_created' if stage in ('network_confirmed','queued') else stage
        if stage=='account_created':
            await asyncio.to_thread(invite,job,user)
            stage='invite_ready'
        if stage=='invite_ready':
            await asyncio.to_thread(send_invite,job)
            stage='invite_sent'
            await asyncio.to_thread(rpc,'update_onboarding',application=job['application_id'],lease=job['lease_id'],new_stage=stage)
        if stage=='invite_sent':
            if not job.get('password_ready_at'):return
            await sync_discord(client,job,complete=True)
            stage='discord_synced'
            await asyncio.to_thread(rpc,'update_onboarding',application=job['application_id'],lease=job['lease_id'],new_stage=stage)
        await asyncio.to_thread(rpc,'update_onboarding',application=job['application_id'],lease=job['lease_id'],new_stage='complete')
    except Exception as error:
        code=str(error) if isinstance(error,OnboardingError) else 'onboarding_failed'
        logging.warning('Onboarding %s needs attention: %s',job['application_id'],code)
        try:await asyncio.to_thread(rpc,'fail_onboarding',application=job['application_id'],lease=job['lease_id'],error=code)
        except Exception:pass


async def worker(client):
    await client.wait_until_ready()
    while True:
        if os.environ.get('ONBOARDING_ENABLED','').lower()=='true':
            try:
                job=await asyncio.to_thread(rpc,'claim_onboarding')
                if job:await process(client,job)
            except Exception:
                logging.warning('Onboarding queue unavailable; check service configuration.')
        await asyncio.sleep(30)
