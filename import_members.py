"""Recoverable Auth creation for imported creators; never reset existing passwords."""
import re
from onboarding import api, rpc, OnboardingError


def provision_members():
    roster=rpc('import_member_roster')
    missing=[m for m in roster if not m['account_id'] and not m['id'].startswith('application:')]
    if not missing:return
    users={}
    page=1
    while True:
        batch=api(f'/auth/v1/admin/users?page={page}&per_page=200')['users']
        users.update({u.get('email','').lower():u for u in batch})
        if len(batch)<200:break
        page+=1
    for member in missing:
        handle=member['handle'].lower()
        if not re.fullmatch(r'[a-z0-9_.]{2,24}',handle):raise OnboardingError('invalid_import_handle')
        address='u'+handle.encode('ascii').hex()+'@accounts.aether.invalid'
        user=users.get(address)
        if user and user.get('app_metadata',{}).get('import_creator')!=member['id']:
            raise OnboardingError('existing_login_conflict')
        if not user:
            result=api('/auth/v1/admin/users',{'email':address,'password':'Password01',
                'email_confirm':True,'app_metadata':{'import_creator':member['id'],'initial_password_change_required':True}},'POST')
            user=result.get('user',result)
            users[address]=user
        rpc('bind_import_member',creator=member['id'],auth_account=user['id'])
