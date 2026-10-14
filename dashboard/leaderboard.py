from __future__ import annotations
from pathlib import Path
from PIL import Image
from database import Creator
from dashboard.style import canvas,downsample,rounded,text,line,circular_avatar,fit_text,format_int,format_hours,draw_aether_logo


def render_leaderboard(creators:list[Creator],summary:dict,output_path:Path,report_date=None)->Path:
    ranked=sorted(creators,key=lambda c:(-c.diamonds,c.creator_id))
    visible=ranked[:15]
    image,draw=canvas(1024,390+max(1,len(visible))*92)
    # Navy canvas, restrained blue/purple borders and generous rank rows.
    rounded(draw,(16,16,1008,image.height//2-16),22,'#0A1224','#36456E')
    draw_aether_logo(image,draw,36,32,80,80,framed=False)
    text(draw,(140,35),'AETHER LIVE STUDIO',27,'#8FABFF',True)
    text(draw,(140,75),'CREATOR LEADERBOARD',35,'#F4F6FF',True)
    period=f'{report_date:%Y-%m}-01 to {report_date:%Y-%m-%d}' if report_date else 'Report date unavailable'
    text(draw,(36,142),'MONTH TO DATE / '+period,21,'#BFCAE5')
    metrics=[('AGENCY DIAMONDS',format_int(sum(c.diamonds for c in ranked))),('CREATORS',str(len(ranked))),('ACTIVE',str(sum(c.hours>0 for c in ranked)))]
    for i,(label,value) in enumerate(metrics):
        x=36+i*324
        rounded(draw,(x,181,x+304,264),12,'#14203A','#465588')
        text(draw,(x+16,194),label,16,'#A7BAE6',True)
        text(draw,(x+16,221),value,30,'#F5F7FF',True)
    for x,label in [(52,'RANK'),(150,'CREATOR'),(620,'DIAMONDS'),(803,'HOURS'),(925,'DAYS')]:text(draw,(x,291),label,18,'#AEBFE4',True)
    for i,creator in enumerate(visible):
        y=325+i*92;accent=['#E9BD47','#A9C3FF','#BE8FFF'][min(i,2)] if i<3 else '#6888C7'
        rounded(draw,(36,y,988,y+82),13,'#14223A' if i%2==0 else '#101B30','#443874' if i<3 else '#273754')
        line(draw,(39,y+15,39,y+66),accent,3)
        text(draw,(77,y+42),f'{i+1:02}',29,accent,True,'mm')
        circular_avatar(image,draw,124,y+9,64,creator.creator_name,i+1,creator.avatar_path,accent)
        text(draw,(208,y+19),fit_text(creator.creator_name,360,29,True),29,'#F5F7FF',True)
        text(draw,(208,y+54),f'+{format_int(creator.new_followers)} followers',19,'#8EB1F3')
        text(draw,(697,y+42),format_int(creator.diamonds),28,'#B79AFF',True,'mm')
        text(draw,(846,y+42),format_hours(creator.hours),25,'#E1E9FA',True,'mm')
        text(draw,(951,y+42),str(creator.days),27,'#8DBEFF',True,'mm')
    if not visible:text(draw,(52,350),'Awaiting the first creator report.',28,'#C0CDE8')
    hidden=max(0,len(ranked)-len(visible))
    # Keep the existing top-15 scope; all totals use the whole imported roster.
    if hidden:text(draw,(42,image.height//2-29),f'+{hidden} more creators / ranked by verified imported diamonds',16,'#A2B4D5')
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    downsample(image).save(output_path,'PNG');return output_path
