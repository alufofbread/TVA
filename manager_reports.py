"""Server-only monthly manager summary, updated through the existing durable publisher."""
import asyncio
import hashlib
import json
from io import BytesIO
import discord
from dashboard.manager_summary import render_manager_summary
from datetime import date, timedelta
from automation_store import utcnow
from uuid import uuid4
from onboarding import rpc


def fmt(value):
    return 'Unavailable' if value is None else f'{value:,.2f}'.rstrip('0').rstrip('.') if isinstance(value,float) else f'{value:,}'


def progress(actual,target):
    if not target:return 'Target not configured'
    if actual is None:return 'Insufficient report coverage'
    return f'{actual/target*100:.1f}% | {fmt(actual)} / {fmt(target)} | {fmt(max(0,target-actual))} remaining'


def build_reports(data):
    agency=data['agency']['diamonds']
    managers=data['managers']
    pages=[]
    for offset in range(0,max(1,len(managers)),10):
        embed=discord.Embed(title='AETHER | Manager performance',description=f"Monthly report: {data['start']} to {data['end']} (UTC)\nAgency diamonds: **{fmt(agency)}**\nAgency target: {progress(agency,(data.get('agency_targets') or {}).get('diamonds'))}\nAgency coverage: {data['agency']['reported']}/{data['agency']['expected']}",color=0x7764FF)
        for manager in managers[offset:offset+10]:
            diamonds=manager['totals']['diamonds']
            share='Unavailable' if agency is None or not agency or diamonds is None else f'{diamonds/agency*100:.1f}%'
            target=(manager.get('targets') or {}).get('diamonds')
            embed.add_field(name=manager['name'][:256],value=f"Team diamonds: **{fmt(diamonds)}**\nAgency contribution: {share}\nTarget: {progress(diamonds,target)}\nCoverage: {manager['totals']['reported']}/{manager['totals']['expected']}",inline=False)
        pages.append(embed)
    return pages


def enrich_summary(data, roster, database):
    """Combine creators by their verified manager; daily figures require adjacent snapshots."""
    data = json.loads(json.dumps(data))
    cutoff = date.fromisoformat(data['end'])
    daily_date = cutoff.isoformat()
    previous_date = (cutoff - timedelta(days=1)).isoformat()
    data['daily_date'] = daily_date
    for manager in data['managers']:
        keys = {str(manager.get(key, '')).lower().lstrip('@') for key in ('id', 'account_id', 'username', 'name')}
        keys.discard('')
        members = [member for member in roster if keys.intersection(
            {str(member.get('manager_id', '')).lower(), str(member.get('manager', '')).lower().lstrip('@')})]
        expected = manager['totals']['expected']
        manager['creator_count'] = len(members) if members else expected
        daily = []
        month_days = []
        for member in members:
            history = database.creator_history(member['id'])
            current = next((row for row in history if row['report_date'] == daily_date), None)
            previous = next((row for row in history if row['report_date'] == previous_date), None)
            if current:
                month_days.append(current.get('days'))
            if not current:
                continue
            baseline = (previous or {}) if cutoff.day != 1 else dict(diamonds=0, hours=0, days=0)
            delta = {}
            for key in ('diamonds', 'hours', 'days'):
                value, before = current.get(key), baseline.get(key)
                # A zero month-to-date metric proves a zero day even for a newly
                # reported creator. Nonzero values still need a real baseline.
                difference = 0 if value == 0 else value - before if value is not None and before is not None else None
                delta[key] = difference if difference is not None and difference >= 0 else None
            daily.append(delta)
        complete = bool(members) and len(daily) == len(members) == expected
        available = lambda key: complete and all(row[key] is not None for row in daily)
        manager['daily'] = {
            'diamonds': sum(row['diamonds'] for row in daily) if available('diamonds') else None,
            'went_live': sum((row['hours'] or 0) > 0 or (row['diamonds'] or 0) > 0 or (row['days'] or 0) > 0 for row in daily) if complete else None,
            'valid_days': sum(row['days'] for row in daily) if available('days') else None,
            'active_rate': sum(row['days'] > 0 for row in daily) / len(members) if available('days') else None,
        }
        if complete and not available('hours'):
            manager['daily']['went_live_partial'] = True
        manager['valid_days'] = (sum(month_days) if members and len(month_days) == len(members) == expected
                                 and all(value is not None for value in month_days) else None)
    data['managers'].sort(key=lambda manager: (manager['totals']['diamonds'] is None,
        -(manager['totals']['diamonds'] or 0), manager['name'].lower()))
    return data


class ManagerReports:
    def __init__(self,client):self.client=client;self.digest=None
    async def publish_due(self):
        db = self.client.database
        latest = db.latest_import()
        if not latest or latest.get('delivery_status') == 'manual':
            return 0
        with db.connect() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            synced = conn.execute('SELECT delivered FROM website_report_outbox WHERE import_id=?',
                                  (latest['id'],)).fetchone() if 'website_report_outbox' in tables else None
            completed = conn.execute('SELECT import_id FROM manager_daily_delivery WHERE report_date=?',
                                     (latest['report_date'],)).fetchone()
        if not synced or not synced['delivered'] or (completed and completed['import_id'] == latest['id']):
            return 0
        pages = await self.publish(report_date=latest['report_date'], daily=True)
        if pages:
            with db.connect() as conn:
                conn.execute('INSERT OR REPLACE INTO manager_daily_delivery VALUES (?,?,?)',
                             (latest['report_date'], latest['id'], utcnow()))
        return pages

    async def publish(self, report_date=None, daily=False, manual=False):
        db=self.client.database
        channel=1554887728183640158 if daily else db.automation_channels().get('manager-performance')
        latest=db.latest_import()
        if not channel or (report_date is None and (not latest or latest.get('delivery_status')=='manual')):return 0
        report_date = report_date or latest['report_date']
        month = report_date[:7]
        data=await asyncio.to_thread(rpc,'discord_manager_performance',report_date=report_date)
        if daily and data['end'] != report_date:
            return 0
        settings = db.team_diamonds(month)
        if settings.get('target') is not None:
            data.setdefault('agency_targets', {})
            data['agency_targets'] = dict(data.get('agency_targets') or {}, diamonds=settings['target'])
        roster=await asyncio.to_thread(rpc,'import_member_roster')
        data=await asyncio.to_thread(enrich_summary,data,roster,db)
        digest=hashlib.sha256(json.dumps([channel,data],sort_keys=True).encode()).hexdigest()
        if digest==self.digest and not daily:return 0
        prefix = f'manager-performance:{report_date}' if daily else 'manager-performance'
        if manual:
            prefix += f':manual-{uuid4().hex}'
        pages=build_reports(data)
        images=await asyncio.to_thread(render_manager_summary,data)
        for index,embed in enumerate(pages):
            embed.clear_fields()
            embed.description=f"Combined creator performance | {data['start']} to {data['end']} (UTC)"
            embed.set_image(url='attachment://aether-manager-summary.png')
            await self.client.publisher.upsert(f'{prefix}:{index}',channel,embed=embed,
                edit_existing=not daily,
                files_factory=lambda index=index: [discord.File(BytesIO(images[index]),filename='aether-manager-summary.png')])
        with db.connect() as conn:
            old=[r[0] for r in conn.execute("SELECT message_key FROM discord_messages WHERE message_key LIKE ? AND status<>'deleted'", (prefix+':%',)) if r[0].count(':')==prefix.count(':')+1]
        for key in old:
            if int(key.rsplit(':',1)[1])>=len(pages):await self.client.publisher.delete(key)
        self.digest=digest
        return len(pages)
