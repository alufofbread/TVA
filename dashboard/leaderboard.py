from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

from PIL import ImageDraw

from config import BRAND_NAME
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
    text_width,
)

TIER_STYLES = {
    1: {"accent": "#22C55E", "fill": "#062815", "glow": "#0D3A21"},
    2: {"accent": "#4ADE80", "fill": "#082B18", "glow": "#124126"},
    3: {"accent": "#38BDF8", "fill": "#071D3D", "glow": "#102D58"},
    4: {"accent": "#2563EB", "fill": "#081B35", "glow": "#0E2B5C"},
    5: {"accent": "#FACC15", "fill": "#2A2108", "glow": "#49360D"},
    6: {"accent": "#F59E0B", "fill": "#2D1E07", "glow": "#4B320A"},
    7: {"accent": "#EA580C", "fill": "#301807", "glow": "#4E270C"},
    8: {"accent": "#A78BFA", "fill": "#1A1233", "glow": "#2B1C52"},
    9: {"accent": "#8B5CF6", "fill": "#1A1233", "glow": "#2B1C52"},
    10: {"accent": "#6D28D9", "fill": "#180F2E", "glow": "#29184A"},
}

ROW_TEXT_Y_OFFSET = -2

COLUMNS = {
    "rank": 68,
    "avatar": 126,
    "creator": 264,
    "diamonds": 450,
    "hours": 566,
    "days": 646,
    "followers": 744,
    "league": 850,
    "incentive": 1026,
}


def _month_progress(today: date | None = None) -> str:
    current = today or date.today()
    days_in_month = calendar.monthrange(current.year, current.month)[1]
    return f"Day {current.day}/{days_in_month}"


def _soft_backdrop(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for y in range(0, height * 2, 2):
        blend = y / max(1, height * 2)
        r = int(5 + 8 * blend)
        g = int(6 + 9 * blend)
        b = int(8 + 12 * blend)
        draw.rectangle((0, y, width * 2, y + 2), fill=(r, g, b))
    draw.ellipse((-260, -220, 430, 300), fill="#071828")
    draw.ellipse((840, -260, 1460, 260), fill="#151018")


def _pill(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, fill: str, outline: str, color: str) -> None:
    width = text_width(label, 14, True) + 32
    rounded(draw, (x, y, x + width, y + 32), 16, fill, outline)
    text(draw, (x + width // 2, y + 7), label, 14, color, True, "ma")


def _centered_pill(draw: ImageDraw.ImageDraw, center_x: int, y: int, label: str, fill: str, outline: str, color: str) -> None:
    width = text_width(label, 14, True) + 32
    _pill(draw, center_x - width // 2, y, label, fill, outline, color)


def _summary_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, label: str, value: str, accent: str, subtitle: str, value_size: int = 25) -> None:
    rounded(draw, (x + 3, y + 5, x + w + 3, y + 123), 12, "#050607")
    rounded(draw, (x, y, x + w, y + 118), 12, COLORS["panel"], "#252A30")
    rounded(draw, (x + 18, y + 18, x + 50, y + 50), 10, "#1B2026", "#2D343C")
    line(draw, (x + 26, y + 34, x + 42, y + 34), accent, 4)
    text(draw, (x + 66, y + 22), label.upper(), 11, COLORS["muted"], True)
    text(draw, (x + 66, y + 43), subtitle, 12, COLORS["subtext"])
    text(draw, (x + 22, y + 82), value, value_size, COLORS["text"], True, "lm")
    line(draw, (x + 22, y + 104, x + w - 22, y + 104), accent, 2)


def _status_pill(draw: ImageDraw.ImageDraw, x: int, y: int, status: str) -> None:
    label, color = incentive_label(status)
    if status == "ACHIEVED":
        fill = "#082616"
    elif status == "NOT_ACHIEVABLE":
        fill = "#2B0D13"
    else:
        fill = "#2A2108"
    _pill(draw, x, y, label, fill, color, color)


def _centered_status_pill(draw: ImageDraw.ImageDraw, center_x: int, y: int, status: str) -> None:
    label, color = incentive_label(status)
    if status == "ACHIEVED":
        fill = "#082616"
    elif status == "NOT_ACHIEVABLE":
        fill = "#2B0D13"
    else:
        fill = "#2A2108"
    _centered_pill(draw, center_x, y, label, fill, color, color)


def _league_pill(draw: ImageDraw.ImageDraw, x: int, y: int, tier: int) -> None:
    style = TIER_STYLES.get(tier, TIER_STYLES[10])
    label = league_name(tier)
    width = text_width(label, 14, True) + 32

    rounded(draw, (x - 2, y - 2, x + width + 2, y + 34), 18, style["glow"])
    rounded(draw, (x, y, x + width, y + 32), 16, style["fill"], style["accent"])
    line(draw, (x + 10, y + 6, x + 25, y + 6), "#F8FAFC", 1)
    line(draw, (x + width - 28, y + 26, x + width - 11, y + 26), COLORS["cyan"], 1)
    text(draw, (x + width // 2, y + 7), label, 14, style["accent"], True, "ma")


def _centered_league_pill(draw: ImageDraw.ImageDraw, center_x: int, y: int, tier: int) -> None:
    width = text_width(league_name(tier), 14, True) + 32
    _league_pill(draw, center_x - width // 2, y, tier)


def _tier_avatar_color(tier: int) -> str:
    return league_color(tier)


def _most_improved(creators: list[Creator]) -> Creator | None:
    if not creators:
        return None
    return max(creators, key=lambda creator: (creator.new_followers, creator.diamonds))


def _ellipsize(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."


def _row_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    value: str,
    size: int,
    fill: str,
    bold: bool = False,
    anchor: str | None = None,
) -> None:
    text(draw, (x, y + ROW_TEXT_Y_OFFSET), value, size, fill, bold, anchor)


def _tier_border_legend(draw: ImageDraw.ImageDraw, y: int) -> None:
    text(draw, (36, y + 15), "TIER BORDERS", 11, COLORS["muted"], True, "lm")
    items = [
        ("Rookie", 1),
        ("Pro", 3),
        ("All Star", 5),
        ("Elite", 8),
    ]
    for index, (label, tier) in enumerate(items):
        x = 184 + index * 190
        color = league_color(tier)
        rounded(draw, (x, y, x + 138, y + 30), 15, "#090B0D", "#22272E")
        draw.ellipse(((x + 12) * 2, (y + 7) * 2, (x + 28) * 2, (y + 23) * 2), fill="#11151A", outline=color, width=3)
        text(draw, (x + 80, y + 15), label, 12, color, True, "mm")


def render_leaderboard(creators: list[Creator], summary: dict[str, int], output_path: Path) -> Path:
    visible = creators[:15]
    row_h = 78
    height = max(995, 326 + (len(visible) + 1) * row_h + 138)
    image, draw = canvas(1200, height)
    _soft_backdrop(draw, 1200, height)

    rounded(draw, (24, 22, 1176, 118), 16, "#080A0D", "#20252B")
    text(draw, (48, 44), "VEXTAL ANALYTICS", 12, COLORS["muted"], True)
    text(draw, (600, 35), BRAND_NAME, 34, COLORS["text"], True, "ma")
    draw_fasttrack_logo(image, draw, 1060, 30, 82, 82, framed=False)
    line(draw, (48, 96, 914, 96), "#1A1F25", 1)

    text(draw, (36, 146), "MONTH TO DATE", 13, COLORS["gold"], True)
    progress = _month_progress()
    rounded(draw, (168, 138, 252, 164), 13, "#1E1A0B", "#4A3B11")
    text(draw, (210, 144), progress, 12, COLORS["gold"], True, "ma")
    text(draw, (270, 146), "Live agency leaderboard", 15, COLORS["muted"])

    improved = _most_improved(creators)
    improved_name = _ellipsize(improved.creator_name, 18) if improved else "No data"
    improved_subtitle = f"+{format_int(improved.new_followers)} followers" if improved else "Growth leader"

    _summary_card(draw, 32, 184, 248, "Total Diamonds", format_int(summary["total_diamonds"]), COLORS["gold"], "Month aggregate")
    _summary_card(draw, 296, 184, 208, "Active Creators", format_int(summary["active_creators"]), COLORS["green"], "Creators tracked")
    _summary_card(draw, 520, 184, 198, "Most Improved", improved_name, COLORS["purple"], improved_subtitle, 17)

    rounded(draw, (738, 184, 1168, 302), 12, COLORS["panel"], "#252A30")
    text(draw, (762, 206), "LEAGUE DISTRIBUTION", 11, COLORS["muted"], True)
    tier_counts = {tier: sum(1 for creator in creators if creator.tier == tier) for tier in range(1, 11)}
    tier_cards = [
        ("Rookie", tier_counts[1] + tier_counts[2], league_color(1)),
        ("Pro", tier_counts[3] + tier_counts[4], league_color(3)),
        ("All Star", tier_counts[5] + tier_counts[6], league_color(5)),
        ("Elite", sum(tier_counts[tier] for tier in range(7, 11)), league_color(8)),
    ]
    for i, (label, count, accent) in enumerate(tier_cards):
        x = 762 + i * 92
        rounded(draw, (x, 232, x + 76, 280), 10, "#0B0F13", "#20252B")
        text(draw, (x + 38, 240), str(count), 20, accent, True, "ma")
        text(draw, (x + 38, 263), label, 9, COLORS["muted"], True, "ma")

    table_y = 326
    rounded(draw, (32, table_y, 1168, height - 118), 14, "#090B0D", "#22272E")
    rounded(draw, (32, table_y, 1168, table_y + 54), 14, "#11151A", "#22272E")
    headers = [
        ("RANK", COLUMNS["rank"]),
        ("CREATOR", COLUMNS["creator"]),
        ("DIAMONDS", COLUMNS["diamonds"]),
        ("HOURS", COLUMNS["hours"]),
        ("DAYS", COLUMNS["days"]),
        ("FOLLOWERS", COLUMNS["followers"]),
        ("LEAGUE", COLUMNS["league"]),
        ("INCENTIVE", COLUMNS["incentive"]),
    ]
    for header, x in headers:
        text(draw, (x, table_y + 21), header, 12, COLORS["muted"], True, "ma")
    line(draw, (32, table_y + 54, 1168, table_y + 54), "#20252B", 1)

    y = table_y + 60
    for creator in visible:
        if creator.rank % 2 == 0:
            rounded(draw, (42, y + 4, 1158, y + row_h - 4), 12, "#0D1013")
        if creator.rank <= 3:
            accent = [COLORS["gold"], COLORS["subtext"], "#D97706"][creator.rank - 1]
            rounded(draw, (34, y + 14, 39, y + row_h - 14), 2, accent)

        row_mid = y + row_h // 2
        rank_color = COLORS["gold"] if creator.rank == 1 else COLORS["subtext"] if creator.rank <= 3 else COLORS["muted"]
        _row_text(draw, COLUMNS["rank"], row_mid, f"#{creator.rank}", 20, rank_color, True, "mm")
        circular_avatar(
            image,
            draw,
            COLUMNS["avatar"] - 24,
            row_mid - 24,
            48,
            creator.creator_name,
            creator.rank,
            creator.avatar_path,
            _tier_avatar_color(creator.tier),
            str(creator.tier),
        )
        _row_text(draw, 158, row_mid, _ellipsize(creator.creator_name, 15), 19, COLORS["text"], True, "lm")
        _row_text(draw, COLUMNS["diamonds"], row_mid, format_int(creator.diamonds), 21, COLORS["text"], True, "mm")
        _row_text(draw, COLUMNS["hours"], row_mid, format_hours(creator.hours), 19, COLORS["subtext"], False, "mm")
        _row_text(draw, COLUMNS["days"], row_mid, str(creator.days), 19, COLORS["subtext"], False, "mm")
        _row_text(draw, COLUMNS["followers"], row_mid, format_int(creator.new_followers), 19, COLORS["subtext"], False, "mm")
        _centered_league_pill(draw, COLUMNS["league"], row_mid - 16, creator.tier)
        _centered_status_pill(draw, COLUMNS["incentive"], row_mid - 16, creator.incentive_status)
        line(draw, (48, y + row_h, 1152, y + row_h), "#14191E", 1)
        y += row_h

    hidden = max(0, len(creators) - len(visible))
    if hidden:
        text(draw, (600, height - 108), f"+ {hidden} additional creators not shown", 13, COLORS["muted"], False, "ma")
    _tier_border_legend(draw, height - 76)
    text(draw, (36, height - 28), "T1 Achieved = banked incentive  |  T1 Progress = on track  |  T1 Missed = cannot reach target", 13, COLORS["muted"])

    final = downsample(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, "PNG")
    return output_path
