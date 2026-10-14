"""Bridge permitted website avatars into a private persistent bot cache."""
import hashlib
import json
import os
import re
import time
import threading
from io import BytesIO
from urllib.parse import quote,urlparse
from PIL import Image
from avatars import _read_url,MAX_AVATAR_BYTES
from config import AVATAR_DIR,ensure_directories
from onboarding import api,rpc


_sync_lock=threading.Lock()
_last_sync={}


def refresh_website_avatars(database):
    with _sync_lock:
        key=str(getattr(database,'path','default'))
        if time.monotonic()-_last_sync.get(key,0)<60:return 0
        result=_refresh_website_avatars(database)
        _last_sync[key]=time.monotonic()
        return result


def _refresh_website_avatars(database):
    if not os.environ.get('SUPABASE_URL') or not os.environ.get('SUPABASE_SERVICE_ROLE_KEY'):return 0
    ensure_directories()
    manifest=AVATAR_DIR/'website-revisions.json'
    try:revisions=json.loads(manifest.read_text()) if manifest.exists() else {}
    except (ValueError,OSError):revisions={}
    try:profiles=rpc('discord_creator_profiles')
    except Exception:return 0
    updated=0
    for profile in profiles:
        creator=database.find_creator(profile['creator_id'])
        if not creator:continue
        key=hashlib.sha256(creator.creator_id.encode()).hexdigest()[:24]
        path=AVATAR_DIR/f'website-{key}.jpg'
        source=profile.get('avatar_path')
        account=profile.get('account_id')
        if not source:
            path.unlink(missing_ok=True);revisions.pop(key,None)
            if creator.avatar_url=='website-profile' or creator.avatar_path==str(path):
                database.update_creator_avatar(creator.creator_id,'','')
            continue
        if not account or not re.fullmatch(re.escape(account)+r'/[0-9a-f-]+\.(?:png|jpg|webp)',source):continue
        revision=hashlib.sha256(source.encode()).hexdigest()
        if revisions.get(key)==revision and path.exists() and time.time()-path.stat().st_mtime<86400:
            if creator.avatar_path!=str(path):database.update_creator_avatar(creator.creator_id,'website-profile',str(path))
            continue
        try:
            result=api('/storage/v1/object/sign/profile-pictures/'+quote(source,safe='/'),{'expiresIn':120},'POST')
            signed=result.get('signedURL') or result.get('signedUrl')
            base=os.environ['SUPABASE_URL'].rstrip('/')
            url=base+'/storage/v1'+signed if signed and signed.startswith('/object/sign/') else base+signed if signed and signed.startswith('/storage/v1/object/sign/') else signed
            parsed=urlparse(url or '')
            if parsed.scheme!='https' or parsed.netloc!=urlparse(base).netloc or not parsed.path.startswith('/storage/v1/object/sign/profile-pictures/'):continue
            raw=_read_url(url)
            if len(raw)>MAX_AVATAR_BYTES:continue
            with Image.open(BytesIO(raw)) as image:
                if image.width*image.height>16000000:continue
                temporary=path.with_suffix('.tmp')
                image.convert('RGB').resize((256,256),Image.Resampling.LANCZOS).save(temporary,'JPEG',quality=90)
                temporary.replace(path)
            database.update_creator_avatar(creator.creator_id,'website-profile',str(path))
            revisions[key]=revision;updated+=1
        except Exception:
            # Signed URLs, service headers and raw provider bodies never enter logs.
            continue
    temporary=manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps(revisions));temporary.replace(manifest)
    return updated
