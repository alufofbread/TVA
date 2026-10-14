"""Compact daily diamonds graph; missing baselines and zero days remain distinct."""
from datetime import date,timedelta
from pathlib import Path
from dashboard.style import canvas,downsample,rounded,text,format_int,fit_text


def last_three_days(history):
    snapshots={}
    for row in history:
        day=date.fromisoformat(row['report_date'])
        value=row['diamonds']
        if day in snapshots and snapshots[day]!=value:snapshots[day]=None
        elif day not in snapshots:snapshots[day]=value
    result=[]
    for day in sorted(snapshots)[-3:]:
        value=snapshots[day]
        before=snapshots.get(day-timedelta(days=1))
        daily=value if day.day==1 else value-before if value is not None and before is not None else None
        if daily is not None and daily<0:daily=None
        result.append({'date':day,'diamonds':daily})
    return result


def render_three_day_graph(creator,history,output_path):
    rows=last_three_days(history)
    image,draw=canvas(1024,420)
    rounded(draw,(0,0,1023,419),20,'#0A1224','#344368')
    text(draw,(32,25),'AETHER / DAILY DIAMONDS',24,'#779EFF',True)
    text(draw,(32,62),fit_text(creator.creator_name,940,30,True),30,'#F4F6FF',True)
    text(draw,(32,108),'Last three available reporting dates - verified daily values',19,'#B7C5E2')
    maximum=max([r['diamonds'] for r in rows if r['diamonds'] is not None]+[1])
    if not rows:text(draw,(32,215),'Daily history is not available yet.',27,'#C2CEE9')
    for i,row in enumerate(rows):
        x=64+i*320;value=row['diamonds']
        rounded(draw,(x,165,x+256,325),12,'#121D35','#354262')
        if value is None:text(draw,(x+128,245),'Unavailable',25,'#A9B8D6',False,'mm')
        else:
            height=max(4,int(value/maximum*100))
            rounded(draw,(x+68,310-height,x+188,310),6,'#8669FF')
            text(draw,(x+128,190),format_int(value),28,'#EEF2FF',True,'mm')
        text(draw,(x+128,352),row['date'].strftime('%d %b %Y'),22,'#CCD6EF',False,'mm')
    text(draw,(32,390),'0 is a verified zero. Unavailable means a missing baseline, gap or correction.',17,'#AABBD9')
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    downsample(image).save(output_path,'PNG');return output_path
