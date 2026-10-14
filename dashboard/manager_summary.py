"""Data-driven manager leaderboard artwork; never substitute sample figures."""
from datetime import date
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter
from dashboard.style import canvas, downsample, rounded, text, line, fit_text

WHITE, MUTED, BLUE, PURPLE, PINK = '#F5F5FC', '#A2A8BC', '#4A9FFF', '#A56FFF', '#EE419D'


def gradient_panel(draw, box, colors=(BLUE, PINK), radius=14):
    x, y, right, bottom = box
    width, height = (right-x)*2, (bottom-y)*2
    layer = Image.new('RGB', (width, height))
    pixels = ImageDraw.Draw(layer)
    start, end = [tuple(bytes.fromhex(color.lstrip('#'))) for color in colors]
    for column in range(width):
        fraction = column/max(1, width-1)
        color = tuple(int(a+(b-a)*fraction) for a, b in zip(start,end))
        pixels.line((column,0,column,height),fill=color)
    mask = Image.new('L', layer.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,width-1,height-1),radius=radius*2,fill=255)
    draw._image.paste(layer,(x*2,y*2),mask)
    rounded(draw,(x+1,y+1,right-1,bottom-1),radius-1,'#090D1A')


def stat_icon(draw, x, y, kind, color):
    if kind == 'diamonds':
        points=[(x-33,y-9),(x-18,y-27),(x+18,y-27),(x+33,y-9),(x,y+30),(x-33,y-9)]
        for a,b in zip(points,points[1:]):line(draw,(*a,*b),color,2)
        for a,b in [((x-33,y-9),(x+33,y-9)),((x-18,y-27),(x,y+30)),((x+18,y-27),(x,y+30)),((x-18,y-27),(x,y-9)),((x+18,y-27),(x,y-9))]:
            line(draw,(*a,*b),PURPLE,2)
    elif kind == 'target':
        for radius in (26,17,8):
            draw.ellipse(((x-radius)*2,(y-radius)*2,(x+radius)*2,(y+radius)*2),outline=color,width=5)
        line(draw,(x,y,x+29,y-29),color,3)
        line(draw,(x+29,y-29,x+17,y-26),color,3)
        line(draw,(x+29,y-29,x+26,y-17),color,3)
    else:
        for a,b in zip([(x-27,y+18),(x-12,y+1),(x-2,y+9),(x+18,y-13)],[(x-12,y+1),(x-2,y+9),(x+18,y-13),(x+18,y-26)]):
            line(draw,(*a,*b),color,3)
        line(draw,(x+6,y-25,x+19,y-25),color,3)


def progress_bar(draw, box, progress):
    x,y,right,bottom=box
    rounded(draw,box,8,'#1B1A2B','#3F354D')
    width=int((right-x-2)*min(1,max(0,progress or 0)))
    if width:
        glow=Image.new('RGBA',draw._image.size)
        ImageDraw.Draw(glow).rounded_rectangle(((x-2)*2,(y-2)*2,(x+width+2)*2,(bottom+2)*2),radius=12,fill=(238,65,157,65))
        glow=glow.filter(ImageFilter.GaussianBlur(12))
        draw._image.paste(glow,(0,0),glow)
        for offset in range(width):
            color=(int(243-44*offset/max(1,width)),int(43+12*offset/max(1,width)),int(151+10*offset/max(1,width)))
            line(draw,(x+1+offset,y+2,x+1+offset,bottom-2),color)
    text(draw,((x+right)//2,(y+bottom)//2),percentage(progress),23,WHITE,True,'mm')


def number(value):
    return 'N/A' if value is None else f'{value:,.0f}'


def percentage(value):
    return 'N/A' if value is None else f'{value:.0%}'


def ranked(managers, daily=False):
    return sorted(managers, key=lambda manager: (
        (manager['daily'] if daily else manager['totals'])['diamonds'] is None,
        -((manager['daily'] if daily else manager['totals'])['diamonds'] or 0), manager['name'].lower()))


def render_manager_summary(data):
    managers = data['managers']
    monthly, daily = ranked(managers), ranked(managers, True)
    pages = []
    cutoff = date.fromisoformat(data['end'])
    agency = data['agency']['diamonds']
    target = (data.get('agency_targets') or {}).get('diamonds')
    progress = agency / target if agency is not None and target else None
    group_daily = (sum(manager['daily']['diamonds'] for manager in managers)
                   if managers and all(manager['daily']['diamonds'] is not None for manager in managers) else None)
    for offset in range(0, max(1, len(managers)), 10):
        count = max(1, len(managers[offset:offset+10]))
        height = 790 + count * 146
        image, draw = canvas(1024, height)
        # Navy panels and blue, purple, pink accents follow the supplied reference.
        draw.rectangle((0, 0, 2048, height*2), fill='#040812')
        text(draw, (512, 48), 'A E T H E R   L I V E   S T U D I O', 18, BLUE, True, 'mm')
        text(draw, (512, 108), 'Manager Summary', 48, WHITE, True, 'mm')
        text(draw, (512, 158), f'{cutoff:%B}  |  Data up to {cutoff:%d %b %Y}', 19, MUTED, False, 'mm')
        for x, title, value, accent, kind in (
            (26, 'TOTAL DIAMONDS', number(agency), BLUE, 'diamonds'),
            (362, 'TARGET', number(target), PURPLE, 'target'),
            (680, 'PROGRESS', percentage(progress), PINK, 'progress'),
        ):
            gradient_panel(draw,(x,202,x+(302 if kind=='target' else 318),370),(accent,PURPLE if kind=='diamonds' else PINK))
            stat_icon(draw,x+63,260 if kind=='progress' else 280,kind,accent)
            text(draw, (x+125, 242), title, 13, MUTED)
            if kind == 'progress':
                progress_bar(draw,(x+22,283,x+287,320),progress)
            else:
                text(draw,(x+125,298),fit_text(value,178,42,True),42,WHITE,True,'lm')
                line(draw,(x+125,337,x+282,337),accent,2)

        def table(y, heading, subtitle, rows, is_daily):
            header, row_height = (200,76) if is_daily else (120,70)
            bottom = y + header + count * row_height
            gradient_panel(draw,(26,y,998,bottom))
            line(draw, (48, y+64, 972, y+64), BLUE if is_daily else PINK)
            text(draw, (54, y+28), heading, 18, WHITE, True)
            text(draw, (972, y+38), subtitle, 14, MUTED, False, 'rm')
            if is_daily:
                text(draw,(56,y+102),'GROUP TOTAL',15,MUTED)
                text(draw,(210,y+108),number(group_daily),36,WHITE,True,'lm')
                line(draw,(210,y+136,340,y+136),BLUE,2)
                line(draw,(28,y+145,996,y+145),'#252A3B')
            columns = [(355, 'DIAMONDS'), (550, 'WENT LIVE' if is_daily else '% SHARE'),
                       (718, 'VALID DAYS' if is_daily else 'CREATORS'), (910, 'ACTIVE RATE' if is_daily else 'VALID DAYS')]
            text(draw, (98, y+header-33), 'MANAGER', 13, MUTED)
            for x, label in columns:
                text(draw, (x+32, y+header-26), label, 12, MUTED, False, 'mm')
            for index, manager in enumerate(rows):
                row_y = y+header+index*row_height
                line(draw, (28, row_y, 996, row_y), '#202638')
                rounded(draw, (50, row_y+16, 84, row_y+52), 7, '#080D1A', '#274B7D')
                metric = manager['daily'] if is_daily else manager['totals']
                rank = '—' if metric['diamonds'] is None else str(offset+index+1)
                text(draw, (67, row_y+35), rank, 20, BLUE, True, 'mm')
                text(draw, (104, row_y+35), fit_text(manager['name'], 205, 23, True), 23, WHITE, True, 'lm')
                if is_daily:
                    live = number(metric['went_live']) + ('+' if metric.get('went_live_partial') else '')
                    values = [number(metric['diamonds']), live, number(metric['valid_days']), percentage(metric['active_rate'])]
                else:
                    share = metric['diamonds']/agency if agency and metric['diamonds'] is not None else None
                    values = [number(metric['diamonds']), percentage(share), number(manager['creator_count']), number(manager['valid_days'])]
                for (x, _), value, color in zip(columns, values, (PINK, PURPLE if not is_daily else MUTED, MUTED, BLUE)):
                    text(draw, (x+32, row_y+35), value, 23, color, True, 'mm')
            if not rows:
                text(draw, (512, y+204), 'No managers assigned yet', 21, MUTED, False, 'mm')
            return bottom

        bottom = table(394, 'YESTERDAY', f'Report date: {cutoff:%d %b %Y}', daily[offset:offset+10], True)
        bottom = table(bottom+24, 'MONTH PERFORMANCE', f'{cutoff:%B} MTD', monthly[offset:offset+10], False)
        note = '+ = verified LIVE count; some activity baselines missing.' if any(manager['daily'].get('went_live_partial') for manager in managers) else 'Active rate = creators with a valid LIVE day / team size.'
        text(draw,(512,bottom+29),note,12,MUTED,False,'mm')
        if len(managers)>10:
            text(draw, (512, bottom+52), f'Page {offset//10+1} of {(len(managers)+9)//10}', 12, BLUE, False, 'mm')
        output = BytesIO()
        downsample(image).save(output, 'PNG')
        pages.append(output.getvalue())
    return pages
