from __future__ import annotations

from pathlib import Path
from branding import BRAND_SHORT, LOGO_PATH

from PIL import ImageDraw

from config import TIER_THRESHOLDS
from database import Creator, Referral, next_referral_reward, referral_reward_for_diamonds
from dashboard.style import (
    circular_avatar,
    downsample,
    draw_aether_logo,
    fit_text,
    format_hours,
    format_int,
    incentive_label,
    league_color,
    league_name,
    line,
)
from dashboard.creator_theme import COLORS, canvas, rounded, text, rail, bloom, diamond
from dashboard.trends import TrendPoint, load_creator_daily_trends
from importer import get_active_incentive_tier, get_next_tier, get_tier


ACTIVENESS_LEVELS = [
    (0, 0, 0, 0),
    (1, 8, 20, 100),
    (2, 11, 30, 100),
    (3, 15, 40, 100),
    (4, 18, 60, 100),
    (5, 22, 80, 100),
]


def _metric(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, label: str, value: str, accent: str) -> None:
    rounded(draw, (x, y, x + w, y + 112), 9, COLORS["panel"], COLORS["border"])
    primary = label == "Total Diamonds"
    size = 36 if primary else 30
    bloom(draw, (x+w-100,y+7,x+w-22,y+40), accent, 38 if primary else 20, 17)
    text(draw, (x + 22, y + 42), fit_text(value, w - 40, size, True), size, COLORS["text"], True, "lm")
    if primary:
        diamond(draw, x+w-25, y+78, 5, accent, outline=True)
    text(draw, (x + 22, y + 78), label.upper(), 12, COLORS["muted"], True, "lm")
    line(draw, (x + 22, y + 92, x + 54, y + 92), accent, 2)


def _status_badge(draw: ImageDraw.ImageDraw, x: int, y: int, status: str, tier: int = 1) -> None:
    label, color = incentive_label(status, tier)
    color = COLORS["purple"] if status == "ACHIEVED" else color
    fill = "#252044" if status == "ACHIEVED" else "#2B0D13" if status == "NOT_ACHIEVABLE" else "#2A2108"
    rounded(draw, (x, y, x + 126, y + 26), 13, fill, color)
    text(draw, (x + 63, y + 6), label.upper(), 10, color, True, "ma")


def _progress(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, label: str, current: float, target: float, formatter, color: str) -> None:
    pct = 100 if target <= 0 else max(0, min(100, current / target * 100))
    text(draw, (x, y + 8), label.upper(), 12, COLORS["muted"], True, "lm")
    value = f"{formatter(current)} / {formatter(target)}"
    text(draw, (x + w, y + 8), value, 14, COLORS["subtext"], False, "rm")
    rail(draw, x, y + 24, w, 7, pct, accent=color)


def _activeness_level(creator: Creator) -> int:
    level = 0
    for current_level, days, hours, diamonds in ACTIVENESS_LEVELS:
        if creator.days >= days and creator.hours >= hours and creator.diamonds >= diamonds:
            level = current_level
    return level


def _activeness_panel(draw: ImageDraw.ImageDraw, creator: Creator) -> None:
    rounded(draw, (36, 552, 650, 680), 10, COLORS["panel"], COLORS["border"])
    current_level = _activeness_level(creator)
    next_targets = ACTIVENESS_LEVELS[min(current_level + 1, len(ACTIVENESS_LEVELS) - 1)]

    text(draw, (62, 576), "ACTIVENESS", 13, COLORS["muted"], True)
    bloom(draw, (62, 600, 170, 654), "#8B66ED", 62, 18)
    rounded(draw, (62, 600, 170, 654), 16, "#242044", "#6E5BA5")
    text(draw, (116, 627), f"L{current_level}", 34, COLORS["purple"], True, "mm")
    text(draw, (194, 606), "MAX ACTIVITY" if current_level == 5 else "CREATOR ACTIVITY", 17, COLORS["text"], True)
    for index in range(5):
        segment_x = 492 + index * 24
        rounded(draw, (segment_x, 612, segment_x+15, 617), 2,
                COLORS["purple"] if index < current_level else "#30364B")
    if current_level >= ACTIVENESS_LEVELS[-1][0]:
        text(draw, (194, 632), "Max level reached for the month.", 14, COLORS["subtext"])
    else:
        _, days, hours, diamonds = next_targets
        text(draw, (194, 632), f"Next: {days} valid days, {hours}h live, {format_int(diamonds)} diamonds", 14, COLORS["subtext"])


def _best_day(points: list[TrendPoint], metric: str) -> TrendPoint | None:
    if not points:
        return None
    return max(points, key=lambda point: (getattr(point, metric), point.diamonds, point.new_followers, point.hours))


def _best_day_panel(draw: ImageDraw.ImageDraw, points: list[TrendPoint]) -> None:
    rounded(draw, (680, 552, 1038, 680), 10, COLORS["panel"], COLORS["border"])
    text(draw, (706, 576), "BEST DAY THIS MONTH", 13, COLORS["muted"], True)

    best_diamonds = _best_day(points, "diamonds")
    best_followers = _best_day(points, "new_followers")
    if best_diamonds is None or best_followers is None:
        text(draw, (706, 620), "No daily history yet", 18, COLORS["text"], True, "lm")
        text(draw, (706, 644), "Import daily sheets to build this.", 13, COLORS["subtext"])
        return

    for x, point, value, label, accent in (
        (706, best_diamonds, format_int(best_diamonds.diamonds), "DIAMONDS", COLORS["purple"]),
        (866, best_followers, f"{best_followers.new_followers:+,}", "FOLLOWERS", "#D39CD6"),
    ):
        rounded(draw, (x, 601, x+146, 666), 12, "#1B1B36", "#403454")
        line(draw, (x+14, 602, x+54, 602), accent)
        text(draw, (x+12, 620), fit_text(value, 123, 25, True), 25, COLORS["text"], True, "lm")
        text(draw, (x+12, 647), label, 9, accent, True, "lm")
        text(draw, (x+134, 647), point.report_date.strftime("%d %b").lstrip("0").upper(), 9, COLORS["subtext"], True, "rm")



def _tier_label(tier: int) -> str:
    return f"Tier {tier}"


def _next_tier_progress(diamonds: int) -> tuple[str, str, int | None, float]:
    current_tier = get_tier(diamonds)
    next_tier, next_threshold = get_next_tier(diamonds)
    current_floor = TIER_THRESHOLDS[current_tier]
    if next_tier is None or next_threshold is None:
        return _tier_label(current_tier), "Max Tier", None, 100.0
    span = max(1, next_threshold - current_floor)
    pct = max(0.0, min(100.0, (diamonds - current_floor) / span * 100))
    return _tier_label(current_tier), _tier_label(next_tier), next_threshold, pct


def _referral_card(draw: ImageDraw.ImageDraw, x: int, y: int, referral: Referral, featured: bool = False) -> None:
    card_w = 408
    rounded(draw, (x, y, x + card_w, y + 180), 10, COLORS["panel"], COLORS["border"])
    if featured:
        bloom(draw, (x+210,y+8,x+370,y+36), "#9270EA", 36, 16)
        line(draw, (x+23,y+1,x+150,y+1), "#8970B9")
    achieved_tier, _ = referral_reward_for_diamonds(referral.diamonds)
    rounded(draw, (x+306,y+15,x+390,y+38), 11, "#28213F", "#504366")
    text(draw, (x+348,y+26), f"TIER {achieved_tier}", 10, COLORS["purple"], True, "mm")
    text(draw, (x + 18, y + 17), fit_text(referral.creator_name, 272, 18, True), 18, COLORS["text"], True)
    _, reward = referral_reward_for_diamonds(referral.diamonds)
    reward_label = f"£{reward} REWARD" if reward else "NO REWARD YET"
    reward_color = COLORS["green"] if reward else COLORS["muted"]
    text(draw, (x + card_w - 18, y + 82), reward_label.upper(), 10, reward_color, True, "ra")
    text(draw, (x + 18, y + 49), f"{format_int(referral.diamonds)} diamonds", 16, COLORS["gold"], True)
    text(draw, (x + 210, y + 49), format_hours(referral.hours), 16, COLORS["blue"], True)
    text(draw, (x + 18, y + 80), f"{referral.days_remaining} days remaining", 12, COLORS["subtext"], True)
    progress = max(0.0, min(1.0, 1 - referral.days_remaining / 30))
    rail(draw, x + 18, y + 111, card_w - 36, 8, progress * 100)
    next_reward = next_referral_reward(referral.diamonds)
    if next_reward is None:
        reward_progress = "Top referral reward reached: £65"
    else:
        next_tier, threshold, payout = next_reward
        reward_progress = f"Next: Tier {next_tier} — £{payout} at {format_int(threshold)} diamonds"
    text(draw, (x + 18, y + 143), reward_progress, 11, COLORS["muted"])


def _active_referrals_panel(draw: ImageDraw.ImageDraw, referrals: list[Referral]) -> None:
    x, y, w = 1070, 22, 446
    rounded(draw, (x, y, x + w, 698), 12, COLORS["panel_alt"], COLORS["border"])
    text(draw, (x + 22, y + 24), "ACTIVE REFERRALS", 16, COLORS["text"], True)
    visible_count = 3
    extra_count = max(0, len(referrals) - visible_count)
    header_count = f"+{extra_count}" if extra_count else str(len(referrals))
    rounded(draw, (x+w-65, y+17, x+w-20, y+44), 13, "#252044", "#494064")
    text(draw, (x+w-42, y+30), header_count, 13, COLORS["purple"], True, "mm")
    if not referrals:
        text(draw, (x + 22, y + 74), "No active referrals", 20, COLORS["text"], True)
        text(draw, (x + 22, y + 104), "Use /add-referral to start tracking one.", 13, COLORS["subtext"])
        return
    def target_completion(referral):
        target = next_referral_reward(referral.diamonds)
        return referral.diamonds / target[1] if target else 1.0

    closest = max(referrals[:visible_count], key=target_completion)
    for index, referral in enumerate(referrals[:visible_count]):
        _referral_card(draw, x + 19, y + 58 + index * 198, referral, referral is closest)


def _profile_icon(draw, x, y, kind, color, size=18):
    if kind == "diamonds":
        vertices = [(x-size,y-3),(x-size//2,y-size//2),(x+size//2,y-size//2),(x+size,y-3),(x,y+size)]
        draw.line([(a*2,b*2) for a,b in vertices+[vertices[0]]], fill=color, width=3)
        line(draw, (x-size,y-3,x+size,y-3), color)
        line(draw, (x-size//2,y-size//2,x,y+size), color)
        line(draw, (x+size//2,y-size//2,x,y+size), color)
    elif kind == "hours":
        draw.ellipse(((x-size)*2,(y-size)*2,(x+size)*2,(y+size)*2), outline=color, width=3)
        line(draw, (x,y-size+5,x,y), color, 2)
        line(draw, (x,y,x+size//2,y+4), color, 2)
    elif kind == "days":
        rounded(draw, (x-size,y-size,x+size,y+size), 4, "#101629", color)
        line(draw, (x-size,y-6,x+size,y-6), color)
        for dx in (-7, 2):
            for dy in (0,8):
                rounded(draw, (x+dx,y+dy,x+dx+3,y+dy+3), 1, color)
    else:
        draw.ellipse(((x-6)*2,(y-17)*2,(x+6)*2,(y-5)*2), outline=color, width=3)
        draw.arc(((x-15)*2,(y-2)*2,(x+15)*2,(y+22)*2),180,360,fill=color,width=3)
        line(draw, (x-15,y+10,x+15,y+10), color)


def _daily_diamonds_chart(draw, points):
    text(draw, (44, 499), "DIAMONDS OVER TIME", 13, COLORS["subtext"], True)
    text(draw, (634, 502), "DAILY HISTORY", 10, COLORS["muted"], True, "ra")
    if not points:
        text(draw, (44, 559), "Your daily story starts here.", 22, COLORS["text"], True)
        text(draw, (44, 597), "Import daily reports to see your progress.", 14, COLORS["muted"])
        return
    points = sorted(points, key=lambda point: point.report_date)
    left, top, right, bottom = 90, 544, 625, 658
    maximum = max(1, max(point.diamonds for point in points))
    for step in range(4):
        y = bottom - int((bottom-top)*step/3)
        line(draw, (left,y,right,y), "#252B43")
        text(draw, (left-12,y), format_int(maximum*step/3), 10, COLORS["muted"], False, "rm")
    span = max(1, (points[-1].report_date-points[0].report_date).days)
    coords = [(left+int((right-left)*(point.report_date-points[0].report_date).days/span), bottom-int((bottom-top)*point.diamonds/maximum)) for point in points]
    # Only plot reported dates. Gaps stay unconnected rather than implying daily data.
    for index, ((x,y),point) in enumerate(zip(coords,points)):
        if index and (point.report_date-points[index-1].report_date).days == 1:
            px,py=coords[index-1]
            line(draw,(px,py,x,y),COLORS["purple"],2)
        bloom(draw,(x-4,y-4,x+4,y+4),COLORS["purple"],90,6)
        diamond(draw,x,y,4,"#DDD1FF")
    text(draw,(left,677),points[0].report_date.strftime("%d %b"),11,COLORS["muted"],False,"lm")
    if len(points)>1:
        text(draw,(right,677),points[-1].report_date.strftime("%d %b"),11,COLORS["muted"],False,"rm")


def render_creator_stats(creator: Creator, total_creators: int, output_path: Path, referrals: list[Referral] | None = None, trend_points: list[TrendPoint] | None = None) -> Path:
    # Referrals are intentionally hidden on this profile. Keep the argument and
    # referral renderers above so tracking, rewards, and existing callers survive.
    image, draw = canvas(1540, 720)
    current_label, next_label, threshold, pct = _next_tier_progress(creator.diamonds)
    points = load_creator_daily_trends(creator) if trend_points is None else trend_points
    panel = lambda box: rounded(draw, box, 18, COLORS["panel_alt"], COLORS["border"])

    # Identity / current league, following the supplied two-column reference.
    panel((20,20,662,181))
    bloom(draw,(40,48,145,153),COLORS["blue"],85,17)
    circular_avatar(image,draw,42,47,106,creator.creator_name,creator.rank,creator.avatar_path,league_color(creator.tier),str(creator.tier))
    if LOGO_PATH.exists():
        draw_aether_logo(image,draw,171,30,128,25,framed=False)
    else:
        text(draw,(174,33),"A E T H E R",13,COLORS["purple"],True)
    text(draw,(172,81),fit_text(creator.creator_name,300,36,True),36,COLORS["text"],True,"lm")
    text(draw,(174,112),"CREATOR NETWORK",10,COLORS["muted"],True)
    text(draw,(174,143),f"Rank #{creator.rank} of {total_creators}",16,COLORS["subtext"],True,"lm")
    rounded(draw,(486,39,642,161),14,"#15162E","#514675")
    text(draw,(564,55),"CURRENT LEAGUE",10,COLORS["muted"],True,"ma")
    diamond(draw,564,86,12,COLORS["blue"],outline=True)
    text(draw,(564,116),league_name(creator.tier).upper(),23,COLORS["text"],True,"mm")
    text(draw,(564,145),f"TIER {creator.tier}",11,COLORS["purple"],True,"mm")

    # Month-to-date: one large diamond total, with secondary metrics beside it.
    panel((20,197,662,700))
    text(draw,(44,219),"MONTH TO DATE",20,COLORS["text"],True)
    bloom(draw,(65,274,223,337),COLORS["purple"],40,24)
    _profile_icon(draw,155,288,"diamonds",COLORS["purple"],40)
    text(draw,(44,364),fit_text(format_int(creator.diamonds),263,54,True),54,COLORS["text"],True,"lm")
    text(draw,(47,399),"D I A M O N D S",12,COLORS["purple"],True,"lm")
    for x,value,label,kind,color in (
        (358,format_hours(creator.hours),"LIVE HOURS","hours",COLORS["blue"]),
        (470,str(creator.days),"VALID DAYS","days",COLORS["purple"]),
        (584,format_int(creator.new_followers),"FOLLOWERS","followers","#D397D6"),
    ):
        line(draw,(x-57,278,x-57,410),"#2B3049")
        _profile_icon(draw,x,299,kind,color,15)
        text(draw,(x,356),fit_text(value,105,23,True),23,COLORS["text"],True,"mm")
        text(draw,(x,391),label,10,COLORS["muted"],True,"mm")
    line(draw,(44,430,638,430),"#2D3049")
    if points:
        latest=max(points,key=lambda point:point.report_date)
        text(draw,(44,451),"LATEST REPORT",10,COLORS["purple"],True)
        text(draw,(44,474),latest.report_date.strftime("%d %b").upper(),11,COLORS["muted"],False,"lm")
        for x,value,label in ((225,format_int(latest.diamonds),"DIAMONDS"),(383,format_hours(latest.hours),"LIVE HOURS"),(552,f"{latest.new_followers:+,}","FOLLOWERS")):
            text(draw,(x,450),value,20,COLORS["text"],True,"mm")
            text(draw,(x,477),label,9,COLORS["muted"],True,"mm")
    else:
        text(draw,(44,458),"Daily performance appears when reports are available.",14,COLORS["muted"])
    _daily_diamonds_chart(draw,points)

    # Tier journey retains the original tier-relative percentage and thresholds.
    panel((682,20,1520,316))
    text(draw,(708,43),"TIER UP",24,COLORS["text"],True)
    text(draw,(837,53),"Your next milestone.",15,COLORS["purple"])
    rounded(draw,(706,88,1496,247),16,"#101529","#3D3458")
    text(draw,(730,110),"CURRENT TIER",11,COLORS["blue"],True)
    text(draw,(730,153),current_label,33,COLORS["text"],True,"lm")
    text(draw,(730,196),league_name(get_tier(creator.diamonds)).upper(),12,COLORS["muted"],True)
    remaining=max(0,threshold-creator.diamonds) if threshold else 0
    text(draw,(1094,127),format_int(remaining),37,COLORS["text"],True,"mm")
    text(draw,(1094,158),"Diamonds to go" if threshold else "Highest tier achieved",14,COLORS["subtext"],False,"mm")
    rail(draw,930,186,326,16,pct,hero=True)
    target_text=f"{format_int(creator.diamonds)} / {format_int(threshold)}" if threshold else format_int(creator.diamonds)
    text(draw,(1094,226),target_text,13,COLORS["muted"],False,"mm")
    text(draw,(1342,111),"NEXT TIER" if threshold else "COMPLETED",11,COLORS["purple"],True)
    text(draw,(1342,153),next_label,30,COLORS["text"],True,"lm")
    diamond(draw,1465,157,16,COLORS["purple"],outline=True)
    text(draw,(1342,198),f"{pct:.1f}%",22,COLORS["purple"],True)
    reward_tier=get_tier(creator.diamonds) if threshold is None else int(next_label.replace("Tier ",""))
    text(draw,(710,277),f"Reward: {league_name(reward_tier)} league + {league_name(reward_tier)} border",14,COLORS["subtext"],False,"lm")

    # Activity and real incentive requirements replace unavailable streak data.
    panel((682,334,1084,537))
    text(draw,(706,354),"ACTIVENESS",17,COLORS["text"],True)
    level=_activeness_level(creator)
    bloom(draw,(708,397,821,510),COLORS["blue"],50,15)
    draw.ellipse((710*2,393*2,830*2,513*2),outline="#303352",width=10)
    for i in range(level):
        draw.arc((710*2,393*2,830*2,513*2),-90+i*72,-90+i*72+64,
                 fill=COLORS["blue"] if i<3 else COLORS["purple"],width=10)
    text(draw,(770,431),"LEVEL",10,COLORS["muted"],True,"mm")
    text(draw,(770,469),str(level),44,COLORS["text"],True,"mm")
    text(draw,(853,409),"MAX ACTIVITY" if level==5 else f"NEXT LEVEL {level+1}",13,COLORS["purple"],True)
    _,days,hours,diamonds=ACTIVENESS_LEVELS[min(level+1,5)]
    text(draw,(853,445),f"{creator.days} / {days} valid days",13,COLORS["subtext"])
    rail(draw,853,469,204,6,min(100,creator.days/days*100),accent=COLORS["purple"])
    text(draw,(853,486),f"{format_hours(creator.hours)} / {hours}h",13,COLORS["subtext"])
    rail(draw,853,513,204,6,min(100,creator.hours/hours*100),accent=COLORS["blue"])

    panel((1100,334,1520,537))
    text(draw,(1124,355),"INCENTIVE",17,COLORS["text"],True)
    incentive=get_active_incentive_tier(creator.diamonds,creator.days,creator.hours)
    _status_badge(draw,1370,351,creator.incentive_status,int(incentive.get("tier",1)))
    _progress(draw,1124,400,370,"Diamonds",creator.diamonds,incentive["diamonds"],format_int,COLORS["purple"])
    _progress(draw,1124,443,370,"Days",creator.days,incentive["days"],lambda v:str(int(v)),COLORS["purple"])
    _progress(draw,1124,486,370,"Hours",creator.hours,incentive["hours"],lambda v:f"{int(round(v))}h",COLORS["blue"])

    panel((682,555,1520,700))
    text(draw,(706,573),"PERSONAL BESTS",17,COLORS["text"],True)
    text(draw,(1494,583),"THIS MONTH",10,COLORS["muted"],True,"rm")
    if points:
        for x,metric,label,kind,color,formatter in (
            (732,"diamonds","BEST DIAMOND DAY","diamonds",COLORS["purple"],format_int),
            (1002,"hours","MOST LIVE HOURS","hours",COLORS["blue"],format_hours),
            (1270,"new_followers","MOST FOLLOWERS","followers","#D397D6",lambda v:f"{v:+,}"),
        ):
            point=_best_day(points,metric)
            _profile_icon(draw,x,639,kind,color,16)
            text(draw,(x+33,615),label,9,COLORS["muted"],True)
            text(draw,(x+33,646),fit_text(formatter(getattr(point,metric)),200,27,True),27,COLORS["text"],True,"lm")
            text(draw,(x+33,681),point.report_date.strftime("%d %b").upper(),11,color,True,"lm")
    else:
        text(draw,(708,637),"Your best days will appear after daily reports are imported.",18,COLORS["subtext"])
    final=downsample(image)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    final.save(output_path,"PNG")
    return output_path
