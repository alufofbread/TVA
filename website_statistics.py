"""Read the website contract; never infer a confirmed league from incentive tiers."""
import asyncio
import logging
from onboarding import rpc


async def context(report_date):
    try:
        data=await asyncio.to_thread(rpc,'discord_statistics_context',report_date=report_date)
        if not isinstance(data,dict) or data.get('schema')!=1 or data.get('end')!=report_date:
            raise ValueError('Statistics contract mismatch')
        return data
    except Exception:
        logging.warning('Website statistics contract unavailable: report_date=%s; confirmed leagues require migration 035 and service access',report_date)
        return None


def creator_context(data, creator_id):
    if not data:
        return None
    member=next((row for row in data['creators'] if row['id']==creator_id),None)
    return dict(member, rules=data['rules'], starting_tier=data.get('starting_tier')) if member else None


def projection(context):
    """All published requirements, including future non-diamond requirements."""
    if not context:
        return None, None
    rules=sorted(context['rules'],key=lambda rule:rule['rank'])
    reached=[rule for rule in rules if rule.get('requirements') and all(
        context.get(q['type']) is not None and context[q['type']]>=q['value'] for q in rule['requirements'])]
    current=reached[-1] if reached else None
    next_rule=next((rule for rule in rules if current is None or rule['rank']>current['rank']),None)
    return current,next_rule
