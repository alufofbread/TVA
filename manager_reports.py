"""Server-only monthly manager summary, updated through the existing durable publisher."""
import asyncio
import hashlib
import json
import discord
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


class ManagerReports:
    def __init__(self,client):self.client=client;self.digest=None
    async def publish(self):
        db=self.client.database
        channel=db.automation_channels().get('manager-performance')
        latest=db.latest_import()
        if not channel or not latest or latest.get('delivery_status')=='manual':return 0
        data=await asyncio.to_thread(rpc,'discord_manager_performance',report_date=latest['report_date'])
        digest=hashlib.sha256(json.dumps([channel,data],sort_keys=True).encode()).hexdigest()
        if digest==self.digest:return 0
        pages=build_reports(data)
        for index,embed in enumerate(pages):
            await self.client.publisher.upsert(f'manager-performance:{index}',channel,embed=embed)
        with db.connect() as conn:
            old=[r[0] for r in conn.execute("SELECT message_key FROM discord_messages WHERE message_key LIKE 'manager-performance:%' AND status<>'deleted'")]
        for key in old:
            if int(key.rsplit(':',1)[1])>=len(pages):await self.client.publisher.delete(key)
        self.digest=digest
        return len(pages)
