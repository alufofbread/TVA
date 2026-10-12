from __future__ import annotations

import calendar
import math
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from branding import BRAND_SHORT
from database import Creator
from dashboard.style import (
    canvas, circular_avatar, downsample, draw_aether_logo, fit_text,
    font, format_hours, format_int, line, rounded, text, text_width,
)

PINK = '#FF4FA3'
BLUE = '#5287FF'
CYAN = '#00CFFF'
WHITE = '#F4F4F7'
MUTED = '#A49FAC'
LEAGUES = (
    ('Rising', '#EEEEF4'), ('Star', '#00CFFF'), ('Premier', '#D986FF'),
    ('Elite', PINK), ('Millionaire', '#FFE000'), ('Icon', '#FF1818'),
)


def league_index(tier: int) -> int:
    # Presentation groups only; imported tiers and incentive rules stay intact.
    return min(5, max(0, (tier - 1) // 2 if tier <= 8 else tier - 5))


def _month_progress(today: date | None = None) -> str:
    current = today or date.today()
    return f'Day {current.day}/{calendar.monthrange(current.year, current.month)[1]}'


def _icon(draw, cx, cy, size, kind, color):
    r = size / 2
    def stroke(points, close=False):
        pts = [(round((cx+x*r)*2), round((cy+y*r)*2)) for x,y in points]
        if close: pts.append(pts[0])
        draw.line(pts, fill=color, width=3, joint='curve')
    if kind == 0:
        for offset in (-.48, 0, .48):
            stroke([(-.7, .25+offset), (0, -.48+offset), (.7, .25+offset)])
    elif kind == 1:
        pts=[]
        for i in range(10):
            angle=-math.pi/2+i*math.pi/5
            radius=1 if i%2==0 else .43
            pts.append((math.cos(angle)*radius, math.sin(angle)*radius))
        stroke(pts, True)
    elif kind == 2:
        stroke([(-.85,-.4),(-.6,.65),(.6,.65),(.85,-.4),(.35,.05),(0,-.7),(-.35,.05)],True)
        stroke([(-.6,.85),(.6,.85)])
        for x,y in [(-.85,-.55),(0,-.85),(.85,-.55)]:
            draw.ellipse(((cx+x*r-2)*2,(cy+y*r-2)*2,(cx+x*r+2)*2,(cy+y*r+2)*2),outline=color,width=2)
    elif kind == 4:
        stroke([(-1,-.35),(-.65,-.85),(.65,-.85),(1,-.35),(0,1)],True)
        stroke([(-1,-.35),(1,-.35)])
        stroke([(-.65,-.85),(0,1),(.65,-.85)])
        stroke([(-.3,-.85),(-.5,-.35),(0,1),(.5,-.35),(.3,-.85)])
    else:
        stroke([(math.cos(-math.pi/2+i*math.pi/3),math.sin(-math.pi/2+i*math.pi/3)) for i in range(6)],True)
        _icon(draw,cx,cy,size*.52,1,color)


def _gradient_border(image, box, left=CYAN, right=PINK, radius=11):
    x0,y0,x1,y1=[v*2 for v in box]
    mask=Image.new('L',(x1-x0+1,y1-y0+1))
    md=ImageDraw.Draw(mask)
    md.rounded_rectangle((0,0,x1-x0,y1-y0),radius=radius*2,outline=255,width=2)
    strip=Image.new('RGB',mask.size)
    sd=ImageDraw.Draw(strip)
    a=tuple(bytes.fromhex(left[1:])); b=tuple(bytes.fromhex(right[1:]))
    for x in range(strip.width):
        t=x/max(1,strip.width-1)
        sd.line((x,0,x,strip.height),fill=tuple(round(u+(v-u)*t) for u,v in zip(a,b)))
    image.paste(strip,(x0,y0),mask)


def _gradient_title(image, draw):
    size=52
    spacing=7
    width=sum(text_width(char,size,True) for char in BRAND_SHORT)+spacing*(len(BRAND_SHORT)-1)
    x=(1024-width)//2
    mask=Image.new('L',image.size)
    md=ImageDraw.Draw(mask)
    cursor=x
    for char in BRAND_SHORT:
        md.text((cursor*2,52),char,font=font(size*2,True),fill=255)
        cursor+=text_width(char,size,True)+spacing
    glow=mask.filter(ImageFilter.GaussianBlur(12)).point(lambda value: round(value*.42))
    image.paste('#7A55E8',(0,0),glow)
    gradient=Image.new('RGB',mask.size)
    gd=ImageDraw.Draw(gradient)
    stops=((0,207,255),(122,109,255),(255,79,163))
    for col in range(gradient.width):
        t=max(0,min(1,(col-x*2)/max(1,width*2)))
        a,b=stops[:2] if t<.5 else stops[1:]
        blend=t*2 if t<.5 else (t-.5)*2
        gd.line((col,0,col,image.height),fill=tuple(round(u+(v-u)*blend) for u,v in zip(a,b)))
    image.paste(gradient,(0,0),mask)


def render_leaderboard(creators: list[Creator], summary: dict[str,int], output_path: Path, report_date: date | None = None) -> Path:
    visible=creators[:15]
    row_h=61
    table_y=378
    table_bottom=table_y+59+max(1,len(visible))*row_h
    height=table_bottom+184
    image,draw=canvas(1024,height)
    draw.rectangle((0,0,image.width,image.height),fill='#02040C')
    rounded(draw,(16,13,1008,100),14,'#03050D','#282632')
    text(draw,(39,46),BRAND_SHORT,15,CYAN)
    text(draw,(40+text_width(BRAND_SHORT+' ',15),46),'ANALYTICS',15,WHITE)
    _gradient_title(image,draw)
    draw_aether_logo(image,draw,902,18,80,78,framed=False)

    text(draw,(28,120),'MONTH TO DATE',15,PINK)
    rounded(draw,(169,113,264,146),16,'#03050D',PINK)
    text(draw,(216,129),_month_progress(report_date),15,PINK,False,'mm')
    text(draw,(282,120),'Live agency leaderboard',15,WHITE)

    rounded(draw,(16,156,248,357),11,'#080615')
    _gradient_border(image,(16,156,248,357),'#D986FF',PINK)
    _icon(draw,63,210,52,4,'#E995FF')
    text(draw,(104,185),'TOTAL DIAMONDS',14,WHITE)
    text(draw,(104,216),'Month aggregate',14,'#CBC6D1')
    value=format_int(summary.get('total_diamonds',sum(c.diamonds for c in creators)))
    value_size=44
    while text_width(value,value_size,True)>192: value_size-=1
    text(draw,(38,259),value,value_size,WHITE,True)
    line(draw,(39,333,226,333),PINK,3)

    rounded(draw,(261,156,763,357),11,'#060712')
    _gradient_border(image,(261,156,763,357),'#D986FF',PINK)
    text(draw,(283,176),'LEAGUE DISTRIBUTION',14,WHITE)
    counts=[0]*6
    for creator in creators: counts[league_index(creator.tier)]+=1
    for i,(label,color) in enumerate(LEAGUES):
        cx=305+i*83
        if i: line(draw,(cx-41,217,cx-41,334),'#55505B')
        _icon(draw,cx,234,40,i,color)
        text(draw,(cx,289),str(counts[i]),34,BLUE if i==1 else color,True,'mm')
        text(draw,(cx,326),label,13,color,False,'mm')

    rounded(draw,(775,156,1008,357),11,'#030C18',CYAN)
    # Three outlined people, matching the reference's active-creators symbol.
    for cx,cy,r in [(809,198,6),(835,198,6),(822,203,8)]:
        draw.ellipse(((cx-r)*2,(cy-r)*2,(cx+r)*2,(cy+r)*2),outline=CYAN,width=3)
        draw.arc(((cx-r-4)*2,(cy+9)*2,(cx+r+4)*2,(cy+29)*2),180,360,fill=CYAN,width=3)
    text(draw,(861,185),'ACTIVE CREATORS',14,WHITE)
    text(draw,(861,216),'Creators tracked',14,'#CBC6D1')
    text(draw,(797,259),format_int(summary.get('active_creators',len(creators))),44,WHITE,True)
    line(draw,(798,333,986,333),BLUE,3)

    rounded(draw,(16,table_y,1008,table_bottom),11,'#030C18')
    headers=[('RANK',66),('CREATOR',277),('DIAMONDS',490),('HOURS',657),('DAYS',787),('FOLLOWERS',929)]
    for label,cx in headers: text(draw,(cx,table_y+30),label,15,'#CBC6D1',False,'mm')
    line(draw,(17,table_y+59,1007,table_y+59),'#242632')
    for index,creator in enumerate(visible):
        y=table_y+59+index*row_h
        mid=y+row_h//2
        accent={1:'#FFE000',2:'#BBC5DF',3:'#FF7100'}.get(creator.rank,MUTED)
        if creator.rank<=3: line(draw,(31,y+12,31,y+row_h-12),accent,3)
        text(draw,(65,mid),f'#{creator.rank}',24,accent,True,'mm')
        li=league_index(creator.tier)
        _icon(draw,128,mid,36,li,LEAGUES[li][1])
        circular_avatar(image,draw,177,mid-23,46,creator.creator_name,creator.rank,creator.avatar_path,'#10BD7B')
        text(draw,(240,mid),fit_text(creator.creator_name,190,20,True),20,WHITE,True,'lm')
        text(draw,(491,mid),format_int(creator.diamonds),28,PINK,True,'mm')
        text(draw,(657,mid),format_hours(creator.hours),20,WHITE,False,'mm')
        text(draw,(787,mid),str(creator.days),22,WHITE,True,'mm')
        text(draw,(930,mid),format_int(creator.new_followers),24,BLUE,True,'mm')
        if index<len(visible)-1: line(draw,(17,y+row_h,1007,y+row_h),'#151F2E')
    if not visible: text(draw,(512,table_y+89),'No creator data yet',20,MUTED,False,'mm')
    _gradient_border(image,(16,table_y,1008,table_bottom))
    hidden=max(0,len(creators)-len(visible))
    if hidden: text(draw,(512,table_bottom+25),f'+ {hidden} additional creators not shown',18,MUTED,False,'mm')
    legend_y=table_bottom+53
    rounded(draw,(16,legend_y,1008,legend_y+75),13,'#03050D','#282632')
    for i,(label,color) in enumerate(LEAGUES):
        x=64+i*165
        _icon(draw,x,legend_y+37,39,i,color)
        text(draw,(x+34,legend_y+37),label,17,color,False,'lm')
    text(draw,(28,table_bottom+144),'T1 Achieved = banked incentive  |  T1 Progress = on track  |  T1 Missed = cannot reach target',14,MUTED)
    output_path=Path(output_path)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    downsample(image).save(output_path,'PNG')
    return output_path
