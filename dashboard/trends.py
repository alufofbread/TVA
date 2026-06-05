from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import ImageDraw

from config import UPLOAD_DIR
from database import Creator
from dashboard.style import COLORS, canvas, circular_avatar, downsample, format_hours, format_int, line, rounded, text
from importer import _detect_columns, _read_excel, load_creators_from_spreadsheet, parse_period_end, parse_report_date_from_filename


@dataclass(slots=True)
class TrendPoint:
    report_date: date
    diamonds: int
    hours: float
    new_followers: int


def _month_uploads(upload_dir: Path, target: date) -> list[Path]:
    by_date: dict[date, Path] = {}
    for path in upload_dir.glob("*.xls*"):
        report_date = _report_data_date(path)
        if report_date is None or report_date.year != target.year or report_date.month != target.month:
            continue
        if not _period_matches_report_month(path, report_date):
            continue
        existing = by_date.get(report_date)
        if existing is None or path.stat().st_mtime > existing.stat().st_mtime:
            by_date[report_date] = path
    return [by_date[report_date] for report_date in sorted(by_date)]


def _report_data_date(path: Path) -> date | None:
    try:
        frame = _read_excel(path)
        columns = _detect_columns(frame)
    except Exception:
        return parse_report_date_from_filename(path)

    period_column = columns.get("data_period")
    if period_column is None:
        return parse_report_date_from_filename(path)

    period_dates = [parse_period_end(value) for value in frame[period_column].dropna().tolist()]
    period_dates = [value for value in period_dates if value is not None]
    if period_dates:
        return max(period_dates)
    return parse_report_date_from_filename(path)


def _period_matches_report_month(path: Path, report_date: date) -> bool:
    try:
        frame = _read_excel(path)
        columns = _detect_columns(frame)
    except Exception:
        return False
    period_column = columns.get("data_period")
    if period_column is None:
        return True
    period_dates = [parse_period_end(value) for value in frame[period_column].dropna().tolist()]
    period_dates = [value for value in period_dates if value is not None]
    if not period_dates:
        return True
    return any(value.year == report_date.year and value.month == report_date.month for value in period_dates)


def load_creator_daily_trends(creator: Creator, upload_dir: Path = UPLOAD_DIR) -> list[TrendPoint]:
    latest_date = max(
        (report_date for path in upload_dir.glob("*.xls*") if (report_date := _report_data_date(path)) is not None),
        default=None,
    )
    if latest_date is None:
        return []

    snapshots: list[TrendPoint] = []
    creator_name = creator.creator_name.strip().lower()
    for path in _month_uploads(upload_dir, latest_date):
        report_date = _report_data_date(path)
        if report_date is None:
            continue
        try:
            rows, _ = load_creators_from_spreadsheet(path, cache_avatars=False)
        except Exception:
            continue

        match = next(
            (
                row
                for row in rows
                if str(row["creator_id"]) == creator.creator_id
                or str(row["creator_name"]).strip().lower() == creator_name
            ),
            None,
        )
        if match is None:
            continue
        snapshots.append(
            TrendPoint(
                report_date=report_date,
                diamonds=int(match["diamonds"]),
                hours=float(match["hours"]),
                new_followers=int(match["new_followers"]),
            )
        )

    daily: list[TrendPoint] = []
    previous: TrendPoint | None = None
    for snapshot in snapshots:
        if previous is None:
            daily.append(snapshot)
        else:
            daily.append(
                TrendPoint(
                    report_date=snapshot.report_date,
                    diamonds=max(0, snapshot.diamonds - previous.diamonds),
                    hours=max(0.0, snapshot.hours - previous.hours),
                    new_followers=max(0, snapshot.new_followers - previous.new_followers),
                )
            )
        previous = snapshot
    return daily


def _compact_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(int(round(value)))


def _nice_axis_max(value: float) -> float:
    if value <= 0:
        return 1
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 5, 10):
        axis_max = step * magnitude
        if axis_max >= value:
            return float(axis_max)
    return float(10 * magnitude)


def _axis_label(value: float, key: str) -> str:
    if key == "hours":
        if value < 1:
            return "0"
        return f"{value:g}h"
    return _compact_number(value)


def _series_value(point: TrendPoint, key: str) -> float:
    return float(getattr(point, key))


def _chart_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    points: list[TrendPoint],
    key: str,
    accent: str,
    fill: str,
    formatter,
) -> None:
    rounded(draw, (x, y, x + w, y + h), 10, COLORS["panel"], COLORS["border"])
    text(draw, (x + 28, y + 24), title.upper(), 13, COLORS["text"], True)

    plot_x = x + 86
    plot_y = y + 66
    plot_w = w - 126
    plot_h = h - 122

    if not points:
        text(draw, (x + w // 2, y + h // 2), "No trend data yet", 18, COLORS["muted"], True, "ma")
        return

    values = [_series_value(point, key) for point in points]
    max_value = _nice_axis_max(max(values))
    min_value = 0
    span = max(max_value - min_value, 1)

    for index in range(5):
        value = max_value - (max_value * index / 4)
        yy = plot_y + int(plot_h * index / 4)
        line(draw, (plot_x, yy, plot_x + plot_w, yy), "#1A1F25", 1)
        text(draw, (plot_x - 14, yy - 7), _axis_label(value, key), 10, COLORS["muted"], False, "ra")

    line(draw, (plot_x, plot_y, plot_x, plot_y + plot_h), "#22272E", 1)
    line(draw, (plot_x, plot_y + plot_h, plot_x + plot_w, plot_y + plot_h), "#22272E", 1)

    coords: list[tuple[int, int]] = []
    if len(points) == 1:
        coords.append((plot_x + plot_w // 2, plot_y + plot_h - int((values[0] - min_value) / span * plot_h)))
    else:
        for index, value in enumerate(values):
            px = plot_x + int(plot_w * index / (len(points) - 1))
            py = plot_y + plot_h - int((value - min_value) / span * plot_h)
            coords.append((px, py))

    area = [(coords[0][0], plot_y + plot_h), *coords, (coords[-1][0], plot_y + plot_h)]
    scaled_area = [(px * 2, py * 2) for px, py in area]
    draw.polygon(scaled_area, fill=fill)
    for start, end in zip(coords, coords[1:]):
        line(draw, (start[0], start[1], end[0], end[1]), accent, 3)

    for px, py in coords:
        draw.ellipse(((px - 4) * 2, (py - 4) * 2, (px + 4) * 2, (py + 4) * 2), fill=accent)

    for index, point in enumerate(points):
        px = coords[index][0]
        line(draw, (px, plot_y + plot_h, px, plot_y + plot_h + 5), "#2C3239", 1)
        label = f"{point.report_date.day} {point.report_date.strftime('%b')}"
        anchor = "ma"
        if index == 0:
            anchor = None
        elif index == len(points) - 1:
            anchor = "ra"
        text(draw, (px, plot_y + plot_h + 18), label, 11, COLORS["muted"], False, anchor)

    latest = formatter(values[-1])
    text(draw, (x + w - 28, y + 24), latest, 14, accent, True, "ra")


def render_creator_trends(creator: Creator, output_path: Path) -> Path:
    points = load_creator_daily_trends(creator)
    image, draw = canvas(760, 1100)

    rounded(draw, (24, 22, 736, 138), 12, COLORS["panel_alt"], COLORS["border"])
    text(draw, (42, 42), "TEAM VEXTAL", 13, COLORS["muted"], True)
    circular_avatar(image, draw, 42, 64, 62, creator.creator_name, creator.rank, creator.avatar_path)
    text(draw, (124, 87), creator.creator_name, 34, COLORS["text"], True, "lm")
    text(draw, (124, 116), "Daily month-to-date trends", 15, COLORS["subtext"], False, "lm")

    _chart_card(
        draw,
        36,
        168,
        688,
        280,
        "Diamonds Trend",
        points,
        "diamonds",
        COLORS["gold"],
        "#1C1708",
        lambda value: format_int(value),
    )
    _chart_card(
        draw,
        36,
        474,
        688,
        280,
        "Live Hours",
        points,
        "hours",
        COLORS["green"],
        "#071E12",
        lambda value: format_hours(value),
    )
    _chart_card(
        draw,
        36,
        780,
        688,
        280,
        "New Followers",
        points,
        "new_followers",
        COLORS["purple"],
        "#121023",
        lambda value: format_int(value),
    )

    final = downsample(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, "PNG")
    return output_path
