"""Calendar-aligned graphs shared by the real stats card and standalone export."""
from pathlib import Path
from dashboard.style import canvas, downsample, rounded, text, line, fit_text
from report_window import calendar_window, snapshots, daily_value


def last_three_days(history):
    """Compatibility API for existing historical exports; not the default window."""
    if not history:
        return []
    values=snapshots(history,'diamonds')
    return [dict(date=day,diamonds=daily_value(values,day)) for day in sorted(values)[-3:]]


def compact(value):
    if value >= 1_000_000:
        return f'{value/1_000_000:.1f}M'
    if value >= 1_000:
        return f'{value/1_000:.1f}k'
    return f'{value:g}'


def draw_daily_graph(draw, rows, box, small=False):
    left, top, right, bottom = box
    maximum = max([r['diamonds'] for r in rows if r['diamonds'] is not None]+[1]) * 1.12
    size = 10 if small else 17
    for step in range(4):
        y = bottom-(bottom-top)*step/3
        line(draw,(left,y,right,y),'#28324A')
        text(draw,(left-9,y),compact(maximum*step/3),size,'#AABBD9',False,'rm')
    previous = None
    for index, row in enumerate(rows):
        x = left+(right-left)*index/max(1,len(rows)-1)
        value = row['diamonds']
        text(draw,(x,bottom+20),row['date'].strftime('%d %b'),size,'#CDD8EF',False,'mm')
        if value is None:
            text(draw,(x,bottom-12),'—',size,'#AABBD9',False,'mm')
            previous = None
            continue
        y = bottom-(bottom-top)*value/maximum
        if previous:
            line(draw,(*previous,x,y),'#548CFF',2 if small else 3)
        radius=3 if small else 4
        draw.ellipse(((x-radius)*2,(y-radius)*2,(x+radius)*2,(y+radius)*2),fill='#548CFF',outline='#C8D9FF')
        previous=(x,y)


def render_daily_graph(creator, history, output_path, days=7, end=None):
    rows=calendar_window(history,days,end=end)
    image,draw=canvas(1024,420)
    rounded(draw,(0,0,1023,419),20,'#080B13','#33415C')
    text(draw,(32,25),'AETHER / DAILY DIAMONDS',24,'#799FFF',True)
    text(draw,(32,65),fit_text(creator.creator_name,940,28,True),28,'#F5F7FF',True)
    text(draw,(32,107),f'Last {days} calendar days · Europe/London',18,'#AABBD9')
    draw_daily_graph(draw,rows,(105,165,951,330))
    text(draw,(32,389),'0 = verified zero · — = missing baseline, missing report or correction',16,'#AABBD9')
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    downsample(image).save(output_path,'PNG')
    return output_path


def render_three_day_graph(creator,history,output_path):
    return render_daily_graph(creator,history,output_path,3,
                             max((r['report_date'] for r in history),default=None))
