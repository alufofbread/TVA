from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import ImageDraw

from config import TIER_THRESHOLDS
from database import Creator
from dashboard.style import (
    COLORS,
    canvas,
    circular_avatar,
    downsample,
    draw_fasttrack_logo,
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
from importer import get_active_incentive_tier, get_tier


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


def _status_badge(draw: ImageDraw.ImageDraw, x: int, y: int, status: str) -> None:
    label, color = incentive_label(status)
    fill = "#082616" if status == "ACHIEVED" else "#2B0D13" if status == "NOT_ACHIEVABLE" else "#2A2108"
    rounded(draw, (x, y, x + 142, y + 30), 15, fill, color)
    text(draw, (x + 71, y + 7), label, 12, color, True, "ma")


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
    rounded(draw, (36, 686, 1038, 824), 10, COLORS["panel"], COLORS["border"])
    current_level = _activeness_level(creator)
    next_targets = ACTIVENESS_LEVELS[min(current_level + 1, len(ACTIVENESS_LEVELS) - 1)]

    text(draw, (62, 712), "ACTIVENESS LEVEL", 13, COLORS["muted"], True)
    rounded(draw, (62, 736, 170, 798), 12, "#082616", COLORS["green"])
    text(draw, (116, 756), f"L{current_level}", 30, COLORS["green"], True, "ma")
    text(draw, (194, 745), "Current creator activity score", 18, COLORS["text"], True)
    if current_level >= ACTIVENESS_LEVELS[-1][0]:
        text(draw, (194, 772), "Max level reached for the month.", 14, COLORS["subtext"])
    else:
        _, days, hours, diamonds = next_targets
        text(draw, (194, 772), f"Next: {days} valid days, {hours}h live, {format_int(diamonds)} diamonds", 14, COLORS["subtext"])


def _latest_daily_point(creator: Creator) -> TrendPoint:
    points = load_creator_daily_trends(creator)
    if points:
        return points[-1]
    return TrendPoint(date.today(), creator.diamonds, creator.hours, creator.new_followers)


def _next_league_progress(diamonds: int) -> tuple[str, str, int | None, float]:
    current_tier = get_tier(diamonds)
    current_league = league_name(current_tier)
    current_floor = min(
        threshold
        for tier, threshold in TIER_THRESHOLDS.items()
        if league_name(tier) == current_league
    )
    next_options = [
        (tier, threshold)
        for tier, threshold in sorted(TIER_THRESHOLDS.items())
        if threshold > diamonds and league_name(tier) != current_league
    ]
    if not next_options:
        return current_league, "Max League", None, 100.0
    next_tier, next_threshold = next_options[0]
    span = max(1, next_threshold - current_floor)
    pct = max(0.0, min(100.0, (diamonds - current_floor) / span * 100))
    return current_league, league_name(next_tier), next_threshold, pct


def render_creator_stats(creator: Creator, total_creators: int, output_path: Path) -> Path:
    image, draw = canvas(1100, 860)
    daily = _latest_daily_point(creator)
    current_league, next_label, next_threshold, pct = _next_league_progress(creator.diamonds)

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
    text(draw, (128, 86), creator.creator_name, 42, COLORS["text"], True, "lm")
    text(draw, (128, 121), f"{league_name(creator.tier)} league creator  |  Rank #{creator.rank} of {total_creators}", 18, COLORS["subtext"], False, "lm")
    draw_fasttrack_logo(image, draw, 884, 42, 154, 74)
    line(draw, (0, 145, 1100, 145), COLORS["border"], 1)

    text(draw, (36, 166), "LATEST DAILY SNAPSHOT", 12, COLORS["muted"], True)
    _metric(draw, 36, 184, 235, "Daily Diamonds", format_int(daily.diamonds), COLORS["gold"])
    _metric(draw, 291, 184, 215, "Daily Hours", format_hours(daily.hours), COLORS["blue"])
    _metric(draw, 526, 184, 205, "Valid Days", str(creator.days), COLORS["green"])
    _metric(draw, 751, 184, 205, "Daily Followers", format_int(daily.new_followers), COLORS["purple"])

    text(draw, (36, 310), "MONTH TO DATE", 12, COLORS["muted"], True)
    _metric(draw, 36, 328, 235, "Monthly Diamonds", format_int(creator.diamonds), COLORS["gold"])
    _metric(draw, 291, 328, 215, "Monthly Hours", format_hours(creator.hours), COLORS["blue"])
    _metric(draw, 526, 328, 205, "Valid Days", str(creator.days), COLORS["green"])
    _metric(draw, 751, 328, 205, "New Followers", format_int(creator.new_followers), COLORS["purple"])

    rounded(draw, (36, 472, 650, 666), 10, COLORS["panel"], COLORS["border"])
    text(draw, (62, 502), "NEXT LEAGUE PROGRESS", 13, COLORS["muted"], True)
    next_value = f"{format_int(next_threshold)} diamonds" if next_threshold else f"{format_int(creator.diamonds)} diamonds"
    text(draw, (62, 540), current_league, 32, COLORS["text"], True)
    text(draw, (588, 536), next_label, 19, COLORS["subtext"], True, "ra")
    text(draw, (588, 562), next_value, 14, COLORS["muted"], False, "ra")
    rounded(draw, (58, 592, 592, 622), 15, "#231D08")
    rounded(draw, (62, 596, 588, 618), 11, "#20242A")
    rounded(draw, (62, 596, 62 + int(526 * pct / 100), 618), 11, COLORS["gold"])
    rounded(draw, (272, 590, 378, 624), 17, "#050607", COLORS["gold"])
    text(draw, (325, 599), f"{pct:.1f}% complete", 13, COLORS["gold"], True, "ma")
    text(draw, (62, 636), f"Unlocks the {next_label} league when the diamond goal lands.", 12, COLORS["subtext"])

    rounded(draw, (680, 472, 1038, 666), 10, COLORS["panel"], COLORS["border"])
    incentive = get_active_incentive_tier(creator.diamonds, creator.days, creator.hours)
    text(draw, (706, 498), f"{league_name(int(incentive['tier'])).upper()} INCENTIVE", 13, COLORS["muted"], True)
    _status_badge(draw, 874, 488, creator.incentive_status)
    _progress(draw, 706, 528, 292, "Diamonds", creator.diamonds, incentive["diamonds"], lambda v: format_int(v), COLORS["gold"])
    _progress(draw, 706, 576, 292, "Days", creator.days, incentive["days"], lambda v: str(int(v)), COLORS["green"])
    _progress(draw, 706, 624, 292, "Hours", creator.hours, incentive["hours"], lambda v: f"{int(round(v))}h", COLORS["blue"])

    _activeness_panel(draw, creator)

    final = downsample(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, "PNG")
    return output_path
