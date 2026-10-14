"""Data-driven manager leaderboard artwork; never substitute sample figures."""
from datetime import date
from io import BytesIO
from dashboard.style import canvas, downsample, rounded, text, line, fit_text

WHITE, MUTED, BLUE, PURPLE, PINK = '#F5F5FC', '#A2A8BC', '#4A9FFF', '#A56FFF', '#EE419D'


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
        height = 820 + count * 136
        image, draw = canvas(1024, height)
        # Navy panels and blue, purple, pink accents follow the supplied reference.
        draw.rectangle((0, 0, 2048, height*2), fill='#040812')
        text(draw, (512, 48), 'A E T H E R   L I V E   S T U D I O', 18, BLUE, True, 'mm')
        text(draw, (512, 108), 'Manager Summary', 48, WHITE, True, 'mm')
        text(draw, (512, 158), f'{cutoff:%B}  |  Data up to {cutoff:%d %b %Y}', 19, MUTED, False, 'mm')
        for x, title, value, accent in (
            (26, 'TOTAL DIAMONDS', number(agency), BLUE),
            (360, 'AGENCY TARGET', number(target), PURPLE),
            (694, 'PROGRESS', percentage(progress), PINK),
        ):
            rounded(draw, (x, 200, x+304, 350), 14, '#0B1020', accent)
            text(draw, (x+24, 224), title, 13, MUTED, True)
            text(draw, (x+24, 278), fit_text(value, 258, 36, True), 36, WHITE, True, 'lm')
            line(draw, (x+24, 325, x+272, 325), '#29263E', 3)
            if title == 'PROGRESS' and progress is not None:
                line(draw, (x+24, 325, x+24+int(248*min(1,max(0,progress))), 325), accent, 3)
            elif title != 'PROGRESS':
                line(draw, (x+24, 325, x+140, 325), accent, 2)

        def table(y, heading, subtitle, rows, is_daily):
            bottom = y + 170 + count * 68
            rounded(draw, (26, y, 998, bottom), 14, '#090E1B', PURPLE)
            line(draw, (48, y+64, 972, y+64), BLUE if is_daily else PINK)
            text(draw, (54, y+28), heading, 18, WHITE, True)
            text(draw, (972, y+38), subtitle, 14, MUTED, False, 'rm')
            label = 'GROUP TOTAL' if is_daily else 'AGENCY TOTAL'
            text(draw, (54, y+92), label, 12, MUTED, True)
            text(draw, (235, y+100), number(group_daily if is_daily else agency), 25, WHITE, True, 'lm')
            columns = [(355, 'DIAMONDS'), (550, 'WENT LIVE' if is_daily else '% SHARE'),
                       (718, 'VALID DAYS' if is_daily else 'CREATORS'), (910, 'ACTIVE RATE' if is_daily else 'VALID DAYS')]
            text(draw, (98, y+139), 'MANAGER', 12, MUTED, True)
            for x, label in columns:
                text(draw, (x+32, y+146), label, 11, MUTED, True, 'mm')
            for index, manager in enumerate(rows):
                row_y = y+170+index*68
                line(draw, (28, row_y, 996, row_y), '#202638')
                rounded(draw, (50, row_y+16, 84, row_y+52), 7, '#080D1A', '#274B7D')
                metric = manager['daily'] if is_daily else manager['totals']
                rank = '—' if metric['diamonds'] is None else str(offset+index+1)
                text(draw, (67, row_y+35), rank, 20, BLUE, True, 'mm')
                text(draw, (104, row_y+35), fit_text(manager['name'], 205, 23, True), 23, WHITE, True, 'lm')
                if is_daily:
                    values = [number(metric['diamonds']), number(metric['went_live']), number(metric['valid_days']), percentage(metric['active_rate'])]
                else:
                    share = metric['diamonds']/agency if agency and metric['diamonds'] is not None else None
                    values = [number(metric['diamonds']), percentage(share), number(manager['creator_count']), number(manager['valid_days'])]
                for (x, _), value, color in zip(columns, values, (PINK, PURPLE if not is_daily else MUTED, MUTED, BLUE)):
                    text(draw, (x+32, row_y+35), value, 23, color, True, 'mm')
            if not rows:
                text(draw, (512, y+204), 'No managers assigned yet', 21, MUTED, False, 'mm')
            return bottom

        bottom = table(374, 'DAILY PERFORMANCE', f'Report day: {cutoff:%d %b %Y}', daily[offset:offset+10], True)
        bottom = table(bottom+24, 'MONTH PERFORMANCE', f'{cutoff:%B} MTD', monthly[offset:offset+10], False)
        text(draw, (512, bottom+29), 'N/A = missing report coverage or baseline. Active rate = creators with a valid LIVE day / team size.', 12, MUTED, False, 'mm')
        if len(managers)>10:
            text(draw, (512, bottom+52), f'Page {offset//10+1} of {(len(managers)+9)//10}', 12, BLUE, False, 'mm')
        output = BytesIO()
        downsample(image).save(output, 'PNG')
        pages.append(output.getvalue())
    return pages
