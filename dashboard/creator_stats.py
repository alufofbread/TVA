from __future__ import annotations

from pathlib import Path

from PIL import ImageDraw

from config import TIER_THRESHOLDS
from database import Creator, Referral
from dashboard.style import (
    COLORS,
    canvas,
    circular_avatar,
    downsample,
    draw_fasttrack_logo,
    fit_text,
    format_hours,
    format_int,
    incentive_label,
    league_color,
    league_name,
    line,
    rounded,
    text,
)
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
    text(draw, (x + 22, y + 42), value, 27, COLORS["text"], True, "lm")
    text(draw, (x + 22, y + 78), label.upper(), 12, COLORS["muted"], True, "lm")
    line(draw, (x + 22, y + 92, x + w - 22, y + 92), accent, 2)


def _status_badge(draw: ImageDraw.ImageDraw, x: int, y: int, status: str, tier: int = 1) -> None:
    label, color = incentive_label(status, tier)
    fill = "#082616" if status == "ACHIEVED" else "#2B0D13" if status == "NOT_ACHIEVABLE" else "#2A2108"
    rounded(draw, (x, y, x + 126, y + 26), 13, fill, color)
    text(draw, (x + 63, y + 6), label, 11, color, True, "ma")


def _progress(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, label: str, current: float, target: float, formatter, color: str) -> None:
    pct = 100 if target <= 0 else max(0, min(100, current / target * 100))
    text(draw, (x, y + 8), label.upper(), 12, COLORS["muted"], True, "lm")
    value = f"{formatter(current)} / {formatter(target)}"
    text(draw, (x + w, y + 8), value, 14, COLORS["subtext"], False, "rm")
    rounded(draw, (x, y + 24, x + w, y + 38), 7, "#20242A")
    rounded(draw, (x, y + 24, x + int(w * pct / 100), y + 38), 7, color)


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

    text(draw, (62, 576), "ACTIVENESS LEVEL", 13, COLORS["muted"], True)
    rounded(draw, (62, 600, 170, 654), 12, "#082616", COLORS["green"])
    text(draw, (116, 627), f"L{current_level}", 29, COLORS["green"], True, "mm")
    text(draw, (194, 606), "Current creator activity score", 17, COLORS["text"], True)
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

    text(draw, (706, 603), best_diamonds.report_date.strftime("%d %b").lstrip("0").upper(), 9, COLORS["muted"], True, "lm")
    text(draw, (872, 603), best_followers.report_date.strftime("%d %b").lstrip("0").upper(), 9, COLORS["muted"], True, "lm")
    rounded(draw, (706, 612, 846, 660), 9, "#11151A", "#252A30")
    rounded(draw, (872, 612, 1012, 660), 9, "#11151A", "#252A30")
    text(draw, (726, 628), format_int(best_diamonds.diamonds), 21, COLORS["text"], True, "lm")
    text(draw, (892, 628), format_int(best_followers.new_followers), 21, COLORS["text"], True, "lm")
    text(draw, (726, 649), "DIAMONDS", 9, COLORS["gold"], True, "lm")
    text(draw, (892, 649), "FOLLOWERS", 9, COLORS["purple"], True, "lm")


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


def _referral_card(draw: ImageDraw.ImageDraw, x: int, y: int, referral: Referral) -> None:
    card_w = 408
    rounded(draw, (x, y, x + card_w, y + 154), 10, COLORS["panel"], COLORS["border"])
    text(draw, (x + 18, y + 17), fit_text(referral.creator_name, 250, 18, True), 18, COLORS["text"], True)
    text(draw, (x + card_w - 18, y + 19), f"TIER {referral.current_tier}", 11, league_color(referral.current_tier), True, "ra")
    text(draw, (x + 18, y + 49), f"{format_int(referral.diamonds)} diamonds", 16, COLORS["gold"], True)
    text(draw, (x + 210, y + 49), format_hours(referral.hours), 16, COLORS["blue"], True)
    text(draw, (x + 18, y + 80), f"{referral.days_remaining} days remaining", 12, COLORS["subtext"], True)
    progress = max(0.0, min(1.0, 1 - referral.days_remaining / 30))
    rounded(draw, (x + 18, y + 105, x + card_w - 18, y + 119), 7, "#20242A")
    rounded(draw, (x + 18, y + 105, x + 18 + int((card_w - 36) * progress), y + 119), 7, COLORS["green"])
    tier_label, next_label, next_threshold, tier_pct = _next_tier_progress(referral.diamonds)
    target = f"{format_int(next_threshold)}" if next_threshold else "MAX"
    text(draw, (x + 18, y + 131), f"{tier_label} → {next_label}  ·  {tier_pct:.0f}% ({target})", 11, COLORS["muted"])


def _active_referrals_panel(draw: ImageDraw.ImageDraw, referrals: list[Referral]) -> None:
    x, y, w = 1070, 22, 446
    rounded(draw, (x, y, x + w, 698), 12, COLORS["panel_alt"], COLORS["border"])
    text(draw, (x + 22, y + 24), "ACTIVE REFERRALS", 14, COLORS["muted"], True)
    text(draw, (x + w - 22, y + 24), str(len(referrals)), 14, COLORS["gold"], True, "ra")
    if not referrals:
        text(draw, (x + 22, y + 74), "No active referrals", 20, COLORS["text"], True)
        text(draw, (x + 22, y + 104), "Use /add-referral to start tracking one.", 13, COLORS["subtext"])
        return
    for index, referral in enumerate(referrals[:4]):
        _referral_card(draw, x + 19, y + 58 + index * 158, referral)
    if len(referrals) > 4:
        text(draw, (x + 22, 674), f"+{len(referrals) - 4} more active referrals", 12, COLORS["muted"], True)


def render_creator_stats(creator: Creator, total_creators: int, output_path: Path, referrals: list[Referral] | None = None) -> Path:
    image, draw = canvas(1540, 720)
    current_tier_label, next_label, next_threshold, pct = _next_tier_progress(creator.diamonds)
    daily_points = load_creator_daily_trends(creator)

    rounded(draw, (24, 22, 1070, 136), 12, COLORS["panel_alt"], COLORS["border"])
    text(draw, (36, 30), "TEAM VEXTAL", 13, COLORS["muted"], True)
    circular_avatar(
        image,
        draw,
        36,
        58,
        72,
        creator.creator_name,
        creator.rank,
        creator.avatar_path,
        league_color(creator.tier),
        str(creator.tier),
    )
    text(draw, (128, 86), fit_text(creator.creator_name, 760, 42, True), 42, COLORS["text"], True, "lm")
    text(draw, (128, 121), f"{league_name(creator.tier)} league creator  |  Rank #{creator.rank} of {total_creators}", 18, COLORS["subtext"], False, "lm")
    draw_fasttrack_logo(image, draw, 944, 32, 94, 94, framed=False)
    line(draw, (0, 145, 1100, 145), COLORS["border"], 1)

    text(draw, (36, 166), "MONTHLY TOTALS", 12, COLORS["muted"], True)
    _metric(draw, 36, 184, 247, "Total Diamonds", format_int(creator.diamonds), COLORS["gold"])
    _metric(draw, 299, 184, 247, "Total Hours", format_hours(creator.hours), COLORS["blue"])
    _metric(draw, 562, 184, 247, "Valid Days", str(creator.days), COLORS["green"])
    _metric(draw, 825, 184, 213, "New Followers", format_int(creator.new_followers), COLORS["purple"])

    rounded(draw, (36, 328, 650, 522), 10, COLORS["panel"], COLORS["border"])
    text(draw, (62, 358), "NEXT TIER PROGRESS", 13, COLORS["muted"], True)
    next_value = f"{format_int(next_threshold)} diamonds" if next_threshold else f"{format_int(creator.diamonds)} diamonds"
    text(draw, (62, 396), current_tier_label, 32, COLORS["text"], True)
    text(draw, (588, 392), next_label, 19, COLORS["subtext"], True, "ra")
    text(draw, (588, 418), next_value, 14, COLORS["muted"], False, "ra")
    rounded(draw, (62, 452, 588, 474), 11, "#20242A")
    fill_w = int(526 * pct / 100)
    rounded(draw, (62, 452, 62 + fill_w, 474), 11, COLORS["gold"])
    if pct >= 10:
        pct_label = f"{pct:.1f}%"
        label_x = 62 + min(fill_w // 2, fill_w - 26)
        text(draw, (label_x + 1, 454), pct_label, 15, "#6A4A00", True, "ma")
        text(draw, (label_x, 453), pct_label, 15, "#FFFFFF", True, "ma")
    reward_tier = get_tier(creator.diamonds) if next_threshold is None else int(next_label.replace("Tier ", ""))
    reward_color = league_color(reward_tier)
    draw.ellipse((62 * 2, 492 * 2, 76 * 2, 506 * 2), fill="#11151A", outline=reward_color, width=3)
    text(draw, (86, 493), f"Reward: {league_name(reward_tier)} league + {league_name(reward_tier)} border", 12, COLORS["subtext"])

    rounded(draw, (680, 328, 1038, 522), 10, COLORS["panel"], COLORS["border"])
    incentive = get_active_incentive_tier(creator.diamonds, creator.days, creator.hours)
    incentive_tier = int(incentive.get("tier", 1))
    text(draw, (706, 346), "INCENTIVE PROGRESS", 13, COLORS["muted"], True)
    _status_badge(draw, 890, 338, creator.incentive_status, incentive_tier)
    _progress(draw, 706, 376, 292, "Diamonds", creator.diamonds, incentive["diamonds"], lambda v: format_int(v), COLORS["gold"])
    _progress(draw, 706, 421, 292, "Days", creator.days, incentive["days"], lambda v: str(int(v)), COLORS["green"])
    _progress(draw, 706, 466, 292, "Hours", creator.hours, incentive["hours"], lambda v: f"{int(round(v))}h", COLORS["blue"])

    _activeness_panel(draw, creator)
    _best_day_panel(draw, daily_points)
    _active_referrals_panel(draw, referrals or [])

    final = downsample(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, "PNG")
    return output_path
