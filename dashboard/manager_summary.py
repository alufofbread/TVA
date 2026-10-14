"""Reference-matched, data-driven 1024px manager summary artwork."""
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WHITE, MUTED = '#F4F4F8', '#B0AFBF'
BLUE, PURPLE, PINK = '#4785FF', '#9770ED', '#F337A0'
FONT_DIR = Path(__file__).parent / 'assets' / 'fonts'
SCALE = 2


@lru_cache(maxsize=64)
def font(size, weight='regular'):
    name = {'regular':'Barlow-Regular.ttf', 'medium':'Barlow-Medium.ttf',
            'bold':'BarlowSemiCondensed-SemiBold.ttf', 'title':'Barlow-Bold.ttf', 'heading':'Barlow-SemiBold.ttf'}[weight]
    return ImageFont.truetype(str(FONT_DIR/name), round(size*SCALE))


def label(draw, xy, value, size, color=WHITE, weight='regular', anchor='lt', tracking=0):
    value = str(value)
    face = font(size, weight)
    if not tracking:
        draw.text((round(xy[0]*2),round(xy[1]*2)),value,font=face,fill=color,anchor=anchor)
        return
    width = sum(face.getlength(char)/2 for char in value) + tracking*max(0,len(value)-1)
    x,y = xy
    if anchor[0]=='m': x-=width/2
    elif anchor[0]=='r': x-=width
    for char in value:
        draw.text((round(x*2),round(y*2)),char,font=face,fill=color,anchor='l'+anchor[1])
        x += face.getlength(char)/2+tracking


def fitted(draw, xy, value, width, size, color=WHITE, weight='bold', anchor='lm'):
    value = str(value)
    while size > 16 and font(size,weight).getlength(value)/2 > width: size-=1
    while value and font(size,weight).getlength(value)/2 > width:
        value=value[:-4]+'...' if len(value)>4 else ''
    label(draw,xy,value,size,color,weight,anchor)


def line(draw, box, color, width=1):
    draw.line(tuple(round(value*2) for value in box),fill=color,width=round(width*2))


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(tuple(round(value*2) for value in box),radius=round(radius*2),fill=fill,outline=outline,width=max(1,round(width*2)))


def rgb(color): return tuple(bytes.fromhex(color.lstrip('#')))


def gradient(width,height,colors):
    result=Image.new('RGB',(width,height));draw=ImageDraw.Draw(result)
    stops=[rgb(color) for color in colors]
    for x in range(width):
        position=x/max(1,width-1)*(len(stops)-1)
        index=min(len(stops)-2,int(position));fraction=position-index
        color=tuple(round(a+(b-a)*fraction) for a,b in zip(stops[index],stops[index+1]))
        draw.line((x,0,x,height),fill=color)
    return result


def panel(image,box,colors=(BLUE,PURPLE,PINK)):
    x,y,right,bottom=box;width,height=(right-x)*2,(bottom-y)*2
    mask=Image.new('L',(width,height));md=ImageDraw.Draw(mask)
    md.rounded_rectangle((0,0,width-1,height-1),radius=28,fill=255)
    image.paste(gradient(width,height,colors),(x*2,y*2),mask)
    field=Image.new('RGB',(96,64));pixels=field.load()
    for yy in range(64):
        for xx in range(96):
            blue=math.exp(-((xx/28)**2+(yy/32)**2))
            violet=math.exp(-(((xx-90)/38)**2+(yy/34)**2))
            pixels[xx,yy]=(int(4+2*blue+8*violet),int(7+7*blue+1*violet),int(16+13*blue+9*violet))
    inner=field.resize((width-4,height-4),Image.Resampling.BICUBIC)
    inner_mask=Image.new('L',inner.size)
    ImageDraw.Draw(inner_mask).rounded_rectangle((0,0,width-5,height-5),radius=26,fill=255)
    image.paste(inner,(x*2+2,y*2+2),inner_mask)


def accent(image,box,colors):
    x,y,right,bottom=box;width=max(1,(right-x)*2);height=max(1,(bottom-y)*2)
    strip=gradient(width,height,colors).convert('RGBA')
    alpha=Image.new('L',(width,height));ad=ImageDraw.Draw(alpha)
    for column in range(width):
        ad.line((column,0,column,height),fill=int(255*(1-column/max(1,width-1))**.65))
    strip.putalpha(alpha);image.paste(strip,(x*2,y*2),strip)


def icon(image,draw,x,y,kind):
    mask=Image.new('L',image.size);pen=ImageDraw.Draw(mask)
    def segment(points,width=2):pen.line([(round(a*2),round(b*2)) for a,b in points],fill=255,width=round(width*2),joint='curve')
    if kind=='diamonds':
        segment([(x-34,y-10),(x-19,y-28),(x+19,y-28),(x+34,y-10),(x,y+29),(x-34,y-10)])
        for points in [[(x-34,y-10),(x+34,y-10)],[(x-19,y-28),(x,y+29)],[(x+19,y-28),(x,y+29)],[(x-19,y-28),(x,y-10),(x+19,y-28)]]:segment(points)
        colors=('#269CFF','#9D6BFA','#F24BDC')
    elif kind=='target':
        for radius in (26,17,7):pen.ellipse(((x-radius)*2,(y-radius)*2,(x+radius)*2,(y+radius)*2),outline=255,width=5)
        segment([(x,y),(x+28,y-28)],3)
        segment([(x+28,y-28),(x+28,y-16),(x+17,y-13),(x+16,y-24),(x+28,y-28)])
        colors=('#9256FF','#C354F4')
    else:
        segment([(x-24,y+17),(x-9,y+1),(x-1,y+8),(x+18,y-13)],3)
        segment([(x+5,y-13),(x+18,y-13),(x+18,y)],3)
        colors=('#E8469C','#FC4AAB')
    color=Image.new('RGB',image.size)
    color.paste(gradient(160,160,colors),(round(x*2-80),round(y*2-80)))
    glow=mask.filter(ImageFilter.GaussianBlur(12)).point(lambda alpha:round(alpha*.22))
    image.paste(color,(0,0),glow);image.paste(color,(0,0),mask)


def progress_bar(image,draw,box,value):
    x,y,right,bottom=box;width=(right-x)*2;height=(bottom-y)*2
    rounded(draw,box,8,'#1B1B2B','#343244')
    amount=round(max(0,min(1,value or 0))*(width-4))
    if amount:
        mask=Image.new('L',(width,height))
        ImageDraw.Draw(mask).rounded_rectangle((2,2,width-3,height-3),radius=14,fill=255)
        ImageDraw.Draw(mask).rectangle((amount+2,0,width,height),fill=0)
        fill=gradient(width,height,('#FA2599','#B32C84'))
        glow=Image.new('L',image.size);glow.paste(mask,(x*2,y*2))
        glow=glow.filter(ImageFilter.GaussianBlur(18)).point(lambda alpha:round(alpha*.27))
        pink=Image.new('RGB',image.size,'#D82791');image.paste(pink,(0,0),glow)
        image.paste(fill,(x*2,y*2),mask)
    label(draw,((x+right)/2,(y+bottom)/2),percentage(value),24,WHITE,'bold','mm')


def number(value):return 'N/A' if value is None else f'{value:,.0f}'
def percentage(value):return 'N/A' if value is None else f'{value:.0%}'
def ranked(managers,daily=False):
    return sorted(managers,key=lambda manager:((manager['daily'] if daily else manager['totals'])['diamonds'] is None,-((manager['daily'] if daily else manager['totals'])['diamonds'] or 0),manager['name'].lower()))


def render_manager_summary(data):
    managers=data['managers'];monthly=ranked(managers);daily=ranked(managers,True);pages=[]
    cutoff=date.fromisoformat(data['end']);agency=data['agency']['diamonds']
    target=(data.get('agency_targets') or {}).get('diamonds')
    progress=agency/target if agency is not None and target else None
    group_daily=sum(manager['daily']['diamonds'] for manager in managers) if managers and all(manager['daily']['diamonds'] is not None for manager in managers) else None
    for offset in range(0,max(1,len(managers)),10):
        slots=max(5,len(managers[offset:offset+10]));height=1536+(slots-5)*146
        image=Image.new('RGB',(2048,height*2),'#02050C');draw=ImageDraw.Draw(image)
        brand='TEAM VEXTAL';brand_width=sum(font(22,'medium').getlength(c)/2 for c in brand)+12*(len(brand)-1);start=512-brand_width/2
        for index,char in enumerate(brand):
            color=tuple(round(a+(b-a)*index/(len(brand)-1)) for a,b in zip(rgb('#269EFF'),rgb('#F14EBC')))
            label(draw,(start,47),char,22,color,'medium');start+=font(22,'medium').getlength(char)/2+12
        label(draw,(512,103),'Manager Summary',60,WHITE,'title','mm')
        month=cutoff.strftime('%B');subtitle=f'Data up to {cutoff.day} '+cutoff.strftime('%b %Y').replace('Sep ', 'Sept ')
        width=font(21).getlength(month)/2+font(21).getlength(subtitle)/2+39
        left=512-width/2
        label(draw,(left,157),month,21,MUTED,anchor='lm')
        dot=left+font(21).getlength(month)/2+19
        draw.ellipse(((dot-3)*2,155*2,(dot+3)*2,161*2),fill=PINK)
        label(draw,(dot+17,157),subtitle,21,MUTED,anchor='lm')
        for x,right,title,value,kind,colors in [(26,347,'TOTAL DIAMONDS',number(agency),'diamonds',('#26A4FF','#A06BF0')),(362,664,'TARGET',number(target),'target',('#A669F7','#E452B8')),(680,998,'PROGRESS',percentage(progress),'progress',('#EB43A1','#F444A6'))]:
            panel(image,(x,202,right,370),colors)
            icon(image,draw,x+(64 if kind=='diamonds' else 49),279 if kind!='progress' else 261,kind)
            title_x=x+(125 if kind=='diamonds' else 105 if kind=='target' else 111)
            label(draw,(title_x,243),title,15,MUTED,tracking=1.1)
            if kind=='progress':progress_bar(image,draw,(702,282,967,320),progress)
            else:
                fitted(draw,(title_x,296),value,right-title_x-17,56 if kind=='diamonds' else 51)
                accent(image,(title_x,335,right-40,338),('#2F9EFF','#A855D6') if kind=='diamonds' else ('#C33CE9','#9B4BAE'))
        daily_bottom=980+(slots-5)*76
        panel(image,(26,395,998,daily_bottom))
        label(draw,(55,423),'YESTERDAY',20,WHITE,'heading',tracking=1.5)
        line(draw,(187,424,187,442),'#414557')
        label(draw,(205,426),f'{cutoff.day} {cutoff:%b %Y}',17,MUTED)
        accent(image,(55,462,981,463),('#2CA9EF','#50405B'))
        label(draw,(56,494),'GROUP TOTAL',17,MUTED,'medium',tracking=1.5)
        label(draw,(210,500),number(group_daily),46,WHITE,'bold','lm')
        accent(image,(210,529,339,532),('#32ABFF','#B955C5'))
        line(draw,(27,539,997,539),'#262B38')
        month_y=daily_bottom+25;month_bottom=1477+(slots-5)*146
        panel(image,(26,month_y,998,month_bottom))
        label(draw,(55,month_y+26),'MONTH PERFORMANCE',20,WHITE,'heading',tracking=1.6)
        label(draw,(310,month_y+29),f'{cutoff:%B} MTD',17,MUTED)
        accent(image,(55,month_y+63,981,month_y+65),('#F345AF','#5B3B5F'))
        line(draw,(27,month_y+65,997,month_y+65),'#242735')

        def rows(items,is_daily):
            top=595 if is_daily else month_y+119
            row_height=76 if is_daily else 70
            heads_y=570 if is_daily else month_y+91
            for x,title in [(138 if is_daily else 109,'MANAGER'),(366,'DIAMONDS'),(547,'% SHARE' if not is_daily else 'WENT LIVE'),(710,'VALID DAY' if is_daily else 'CREATORS'),(900,'ACTIVE RATE' if is_daily else 'VALID DAYS')]:
                label(draw,(x,heads_y),title,15,MUTED,'medium','mm',tracking=1.8)
            line(draw,(27,top,997,top),'#232936')
            for index,manager in enumerate(items):
                y=top+index*row_height;center=y+row_height/2
                rounded(draw,(51,y+23 if is_daily else y+17,86,y+59 if is_daily else y+53),8,'#040A15','#24548C',.65)
                metric=manager['daily'] if is_daily else manager['totals']
                label(draw,(69,center+2),str(offset+index+1) if metric['diamonds'] is not None else '-',25,BLUE,'medium','mm')
                fitted(draw,(106 if is_daily else 97,center+2),manager['name'],202,27,WHITE,'bold')
                if is_daily:
                    live=number(metric['went_live'])+('+' if metric.get('went_live_partial') else '')
                    values=[number(metric['diamonds']),live,number(metric['valid_days']),percentage(metric['active_rate'])]
                else:
                    share=metric['diamonds']/agency if agency and metric['diamonds'] is not None else None
                    values=[number(metric['diamonds']),percentage(share),number(manager['creator_count']),number(manager['valid_days'])]
                for x,value,color in zip((365,547,712,901),values,(PINK,MUTED if is_daily else '#777CEC',MUTED,BLUE if is_daily else MUTED)):
                    label(draw,(x,center+2),value,28,color,'bold','mm')
                if index<len(items)-1:line(draw,(27,y+row_height,997,y+row_height),'#151D2A')
            if not items:label(draw,(512,top+40),'No managers assigned yet',24,MUTED,anchor='mm')
        rows(daily[offset:offset+10],True);rows(monthly[offset:offset+10],False)
        if len(managers)>10:label(draw,(512,height-25),f'Page {offset//10+1} of {(len(managers)+9)//10}',14,MUTED,anchor='mm')
        output=BytesIO();image.resize((1024,height),Image.Resampling.LANCZOS).save(output,'PNG');pages.append(output.getvalue())
    return pages
