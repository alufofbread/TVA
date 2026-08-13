from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PIL import ImageDraw

from database import Referral, referral_reward_for_diamonds
from dashboard.style import COLORS, canvas, downsample, draw_fasttrack_logo, fit_text, format_int, line, rounded, text


WIDTH = 1280
SUMMARY_COLUMNS = 3


def _summary_card(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, referrer_name: str, referral_count: int, owed: int) -> None:
    rounded(draw, (x, y, x + width, y + 78), 10, COLORS["panel"], COLORS["border"])
    text(draw, (x + 18, y + 16), fit_text(referrer_name, width - 120, 16, True), 16, COLORS["text"], True)
    text(draw, (x + 18, y + 46), f"{referral_count} active referral{'s' if referral_count != 1 else ''}", 12, COLORS["subtext"])
    text(draw, (x + width - 18, y + 27), f"£{owed}", 25, COLORS["green"], True, "ra")
    text(draw, (x + width - 18, y + 53), "OWED", 10, COLORS["muted"], True, "ra")


def _referral_row(draw: ImageDraw.ImageDraw, y: int, referral: Referral, is_alternate: bool) -> None:
    fill = "#0E1012" if is_alternate else COLORS["panel"]
    rounded(draw, (28, y, WIDTH - 28, y + 58), 8, fill, COLORS["border"])
    _, reward = referral_reward_for_diamonds(referral.diamonds)
    text(draw, (48, y + 12), fit_text(referral.referrer_name, 225, 16, True), 16, COLORS["text"], True)
    text(draw, (48, y + 35), "REFERRER", 10, COLORS["muted"], True)
    text(draw, (330, y + 12), "→", 20, COLORS["gold"], True)
    text(draw, (370, y + 12), fit_text(referral.creator_name, 250, 16, True), 16, COLORS["text"], True)
    text(draw, (370, y + 35), "REFERRED CREATOR", 10, COLORS["muted"], True)
    text(draw, (710, y + 13), format_int(referral.diamonds), 17, COLORS["gold"], True, "ra")
    text(draw, (710, y + 35), "DIAMONDS", 10, COLORS["muted"], True, "ra")
    text(draw, (895, y + 13), f"£{reward}", 20, COLORS["green"], True, "ra")
    text(draw, (895, y + 35), "REWARD OWED", 10, COLORS["muted"], True, "ra")
    text(draw, (1050, y + 13), str(referral.days_remaining), 17, COLORS["blue"], True, "ra")
    text(draw, (1050, y + 35), "DAYS LEFT", 10, COLORS["muted"], True, "ra")
    text(draw, (1232, y + 23), f"T{referral.current_tier}", 14, COLORS["subtext"], True, "ra")


def render_all_referrals(referrals: list[Referral], output_path: Path) -> Path:
    """Render active referral links and the amount currently owed to each referrer."""
    grouped: dict[str, list[Referral]] = defaultdict(list)
    for referral in referrals:
        grouped[referral.referrer_name].append(referral)

    summary_rows = max(1, (len(grouped) + SUMMARY_COLUMNS - 1) // SUMMARY_COLUMNS)
    summary_height = summary_rows * 92
    table_start = 202 + summary_height
    row_height = 66
    table_height = 74 + max(1, len(referrals)) * row_height
    height = table_start + table_height + 30
    image, draw = canvas(WIDTH, height)

    rounded(draw, (24, 20, WIDTH - 24, 146), 12, COLORS["panel_alt"], COLORS["border"])
    text(draw, (48, 46), "TEAM VEXTAL", 13, COLORS["muted"], True)
    text(draw, (48, 74), "ACTIVE REFERRALS", 34, COLORS["text"], True)
    text(draw, (48, 115), "Current rewards owed to each referrer", 16, COLORS["subtext"])
    draw_fasttrack_logo(image, draw, 1138, 36, 88, 88, framed=False)

    total_owed = sum(referral_reward_for_diamonds(referral.diamonds)[1] for referral in referrals)
    text(draw, (1110, 58), f"£{total_owed}", 32, COLORS["green"], True, "ra")
    text(draw, (1110, 101), "TOTAL OWED", 12, COLORS["muted"], True, "ra")
    line(draw, (24, 166, WIDTH - 24, 166), COLORS["border"])
    text(draw, (28, 180), "REFERRER REWARDS OWED", 13, COLORS["muted"], True)

    card_width = 390
    card_gap = 25
    for index, (referrer_name, referrer_referrals) in enumerate(grouped.items()):
        column = index % SUMMARY_COLUMNS
        row = index // SUMMARY_COLUMNS
        x = 28 + column * (card_width + card_gap)
        y = 202 + row * 92
        owed = sum(referral_reward_for_diamonds(referral.diamonds)[1] for referral in referrer_referrals)
        _summary_card(draw, x, y, card_width, referrer_name, len(referrer_referrals), owed)

    rounded(draw, (24, table_start, WIDTH - 24, table_start + 56), 10, COLORS["panel_alt"], COLORS["border"])
    text(draw, (48, table_start + 20), "REFERRER", 11, COLORS["muted"], True)
    text(draw, (370, table_start + 20), "REFERRED CREATOR", 11, COLORS["muted"], True)
    text(draw, (710, table_start + 20), "TRACKED DIAMONDS", 11, COLORS["muted"], True, "ra")
    text(draw, (895, table_start + 20), "OWED", 11, COLORS["muted"], True, "ra")
    text(draw, (1050, table_start + 20), "TIME", 11, COLORS["muted"], True, "ra")

    if referrals:
        for index, referral in enumerate(referrals):
            _referral_row(draw, table_start + 66 + index * row_height, referral, index % 2 == 1)
    else:
        rounded(draw, (28, table_start + 66, WIDTH - 28, table_start + 124), 8, COLORS["panel"], COLORS["border"])
        text(draw, (WIDTH // 2, table_start + 75), "No active referrals", 21, COLORS["text"], True, "ma")
        text(draw, (WIDTH // 2, table_start + 100), "Use /add-referral to start tracking one.", 13, COLORS["subtext"], False, "ma")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    downsample(image).save(output_path, "PNG")
    return output_path
