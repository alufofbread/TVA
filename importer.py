from __future__ import annotations

import calendar
import hashlib
import json
import re
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from avatars import cache_avatar
from config import (
    INCENTIVE_TIERS,
    TIER_THRESHOLDS,
)


class ImportErrorWithContext(ValueError):
    pass


@dataclass(slots=True)
class ImportResult:
    creator_count: int
    file_hash: str
    total_diamonds: int
    total_battles: int
    duplicate: bool
    report_date: date
    import_id: int


COLUMN_ALIASES = {
    "manager": {"creator network manager", "manager", "manager username", "manager tiktok"},
    "creator_id": {
        "creator id",
        "creatorid",
        "user id",
        "tiktok id",
    },
    "creator_name": {
        "creator",
        "creator name",
        "creator's username",
        "creators username",
        "name",
        "username",
        "user name",
        "tiktok",
        "tiktok username",
        "host",
    },
    "diamonds": {"diamonds", "diamond", "total diamonds", "received diamonds", "points"},
    "previous_month_diamonds": {"diamonds last month"},
    "hours": {"hours", "live hours", "live duration", "live duration hours", "duration", "valid hours"},
    "days": {"days", "valid days", "live days", "active days", "valid go live days", "valid go live days this month"},
    "battles": {"battles", "battle", "total battles", "pk battles", "matches", "match count"},
    "new_followers": {"new followers"},
    "live_streams": {"live streams"},
    "data_period": {"data period", "period", "date period", "reporting period"},
    "join_date": {"join time", "join date", "joined at", "date joined"},
    "avatar_url": {
        "avatar",
        "avatar url",
        "avatar_url",
        "profile image",
        "profile image url",
        "profile picture",
        "profile picture url",
        "picture",
        "photo",
        "image",
    },
}


def normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("_", " "))


def parse_number(value: Any) -> float:
    if pd.isna(value):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0
    hours_match = re.fullmatch(r"\s*(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s\s*)?", text.lower())
    if hours_match and any(hours_match.groups()):
        hours,minutes,seconds=(float(part or 0) for part in hours_match.groups())
        return hours + minutes / 60 + seconds / 3600
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    return float(cleaned) if cleaned not in {"", "-", "."} else 0


def clean_identifier(value: Any, fallback: str) -> str:
    if pd.isna(value):
        return _creator_id(fallback)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text or _creator_id(fallback)


def clean_optional_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def parse_period_end(value: Any) -> date | None:
    if pd.isna(value):
        return None
    text_value = str(value)
    matches = re.findall(r"\d{4}-\d{2}-\d{2}", text_value)
    if matches:
        return date.fromisoformat(matches[-1])
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def parse_report_date_from_filename(path: Path) -> date | None:
    match = re.search(r"Creator[_ ]data[_ ](\d{4})[_-](\d{2})[_-](\d{2})", path.name, re.IGNORECASE)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def get_tier(diamonds: int | float) -> int:
    tier = 1
    for level, threshold in sorted(TIER_THRESHOLDS.items()):
        if diamonds >= threshold:
            tier = level
    return tier


def get_next_tier(diamonds: int | float) -> tuple[int | None, int | None]:
    current = get_tier(diamonds)
    next_level = current + 1
    if next_level not in TIER_THRESHOLDS:
        return None, None
    return next_level, TIER_THRESHOLDS[next_level]


def get_progress_percentage(diamonds: int | float) -> float:
    current = get_tier(diamonds)
    next_level, next_threshold = get_next_tier(diamonds)
    if next_level is None or next_threshold is None:
        return 100.0
    current_threshold = TIER_THRESHOLDS[current]
    span = next_threshold - current_threshold
    return max(0.0, min(100.0, ((diamonds - current_threshold) / span) * 100))


def get_active_incentive_tier(diamonds: int, days: int, hours: float) -> dict[str, int | float]:
    ordered_tiers = sorted(INCENTIVE_TIERS, key=lambda tier: int(tier["tier"]))
    for tier in ordered_tiers:
        if not (
            diamonds >= tier["diamonds"]
            and days >= tier["days"]
            and hours >= tier["hours"]
        ):
            return tier
    return ordered_tiers[-1]


def incentive_status(diamonds: int, days: int, hours: float, report_date: date | None = None) -> str:
    target = get_active_incentive_tier(diamonds, days, hours)
    if (
        diamonds >= target["diamonds"]
        and days >= target["days"]
        and hours >= target["hours"]
    ):
        return "ACHIEVED"

    report_date = report_date or date.today()
    _, days_in_month = calendar.monthrange(report_date.year, report_date.month)
    remaining_days = max(0, days_in_month - report_date.day)
    if days + remaining_days < target["days"]:
        return "NOT_ACHIEVABLE"
    return "IN_PROGRESS"


def _header_score(values: list[Any]) -> int:
    normalized = {normalize_header(value) for value in values}
    return sum(1 for aliases in COLUMN_ALIASES.values() if normalized & aliases)


def _read_excel(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            raise ImportErrorWithContext(f"Could not read CSV: {exc}") from exc
        if frame.empty:
            raise ImportErrorWithContext("Spreadsheet is empty.")
        return frame

    try:
        raw_sheets = pd.read_excel(path, sheet_name=None, header=None)
    except Exception as exc:
        raise ImportErrorWithContext(f"Could not read spreadsheet: {exc}") from exc

    frames = []
    for sheet_name, raw in raw_sheets.items():
        if raw.empty:
            continue
        header_index = 0
        best_score = -1
        for index, row in raw.head(12).iterrows():
            score = _header_score(list(row.values))
            if score > best_score:
                header_index = index
                best_score = score

        header = [str(value).strip() for value in raw.iloc[header_index].tolist()]
        frame = raw.iloc[header_index + 1 :].copy()
        frame.columns = header
        frame = frame.dropna(how="all")
        if not frame.empty:
            frame["_sheet_name"] = sheet_name
            frames.append(frame)
    if not frames:
        raise ImportErrorWithContext("Spreadsheet is empty.")
    return pd.concat(frames, ignore_index=True)


def _detect_columns(df: pd.DataFrame) -> dict[str, str]:
    normalized = {normalize_header(col): col for col in df.columns}
    detected: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                detected[canonical] = normalized[alias]
                break

    missing = [name for name in ("creator_name", "diamonds", "hours", "days", "battles") if name not in detected]
    if missing:
        readable = ", ".join(missing)
        available = ", ".join(str(col) for col in df.columns)
        raise ImportErrorWithContext(
            f"Missing required spreadsheet columns: {readable}. Available columns: {available}"
        )
    return detected


def _creator_id(name: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return clean or hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def load_creators_from_spreadsheet(path: Path, report_date: date | None = None, cache_avatars: bool = True, with_report_date: bool = False):
    df = _read_excel(path)
    columns = _detect_columns(df)
    df = df[list(columns.values())].rename(columns={v: k for k, v in columns.items()})
    df["creator_name"] = df["creator_name"].astype(str).str.strip()
    df = df[df["creator_name"].ne("") & df["creator_name"].str.lower().ne("nan")]

    if df.empty:
        raise ImportErrorWithContext("No creator records were found in the spreadsheet.")

    requested_date = report_date
    filename_date = parse_report_date_from_filename(path)
    if "data_period" in df.columns:
        df["_period_end"] = pd.to_datetime(df["data_period"].apply(parse_period_end), errors="coerce")
        latest_period = df['_period_end'].dropna().max()
        detected_date = (latest_period.date() if not pd.isna(latest_period) else None) or filename_date
        if requested_date and detected_date and requested_date != detected_date:
            raise ImportErrorWithContext('report_date conflicts with the effective date in the report.')
        report_date = requested_date or detected_date
    elif report_date is None:
        report_date = filename_date

    if report_date is None:
        raise ImportErrorWithContext("Cannot determine report date. Include Data period, use a dated Creator data filename, or supply report_date (YYYY-MM-DD).")
    if report_date > date.today():
        raise ImportErrorWithContext("Report effective date cannot be in the future.")

    if report_date is not None and "_period_end" in df.columns:
        month_rows = df[
            df["_period_end"].isna()
            | ((df["_period_end"].dt.year == report_date.year) & (df["_period_end"].dt.month == report_date.month))
        ]
        if not month_rows.empty:
            df = month_rows

    for metric in ("diamonds", "hours", "days", "battles"):
        df[metric] = df[metric].apply(parse_number)

    if "creator_id" not in df.columns:
        df["creator_id"] = df["creator_name"].apply(_creator_id)
    if "avatar_url" not in df.columns:
        df["avatar_url"] = ""
    if "new_followers" not in df.columns:
        df["new_followers"] = 0
    if "join_date" in df.columns:
        df["join_date"] = df["join_date"].apply(parse_period_end)
    else:
        df["join_date"] = None
    has_previous_month_diamonds = "previous_month_diamonds" in df.columns
    df['_previous_month_known'] = (df['previous_month_diamonds'].apply(lambda value: clean_optional_text(value) not in ('','-'))
                                   if has_previous_month_diamonds else False)
    if not has_previous_month_diamonds:
        df["previous_month_diamonds"] = df["diamonds"]

    for metric in ("new_followers", "previous_month_diamonds"):
        df[metric] = df[metric].apply(parse_number)

    # Some exports contain the same daily record more than once (for example
    # when a worksheet has been duplicated).  These rows must be removed before
    # the per-creator totals below are calculated; otherwise that day's figures
    # are added twice and referral progress is inflated as a consequence.
    duplicate_columns = [
        column
        for column in (
            "creator_id",
            "creator_name",
            "data_period",
            "diamonds",
            "hours",
            "days",
            "battles",
            "new_followers",
            "previous_month_diamonds",
            "join_date",
            "manager",
            "live_streams",
        )
        if column in df.columns
    ]
    if duplicate_columns:
        df = df.drop_duplicates(subset=duplicate_columns, keep="first").copy()

    if "_period_end" in df.columns:
        df["_period_sort"] = df["_period_end"].fillna(report_date or date.min)
    else:
        df["_period_sort"] = report_date or date.min

    grouped_rows: list[dict[str, Any]] = []
    for creator_name, group in df.sort_values(["creator_name", "_period_sort"]).groupby("creator_name", sort=False):
        latest = group.iloc[-1]
        monthly = {
            "creator_name": creator_name,
            "creator_id": latest["creator_id"],
            "diamonds": group["diamonds"].sum(),
            "hours": group["hours"].sum(),
            "days": group["days"].sum(),
            "battles": group["battles"].sum(),
            "new_followers": group["new_followers"].sum(),
            "previous_month_diamonds": latest["previous_month_diamonds"],
            "avatar_url": latest.get("avatar_url", ""),
            "join_date": latest.get("join_date"),
            "manager": clean_optional_text(latest.get("manager", "")),
            "previous_month_known": bool(latest['_previous_month_known']),
            "live_streams": sum(parse_number(value) for value in group['live_streams']) if 'live_streams' in group else None,
        }
        grouped_rows.append(monthly)

    grouped = pd.DataFrame(grouped_rows).sort_values(["diamonds", "creator_name"], ascending=[False, True]).reset_index(drop=True)

    creators: list[dict] = []
    for index, row in grouped.iterrows():
        diamonds = int(round(row["diamonds"]))
        previous_month_diamonds = int(round(row["previous_month_diamonds"]))
        days = int(round(row["days"]))
        hours = round(float(row["hours"]), 2)
        battles = int(round(row["battles"]))
        new_followers = int(round(row["new_followers"]))
        creator_id = clean_identifier(row["creator_id"], row["creator_name"])
        avatar_url = clean_optional_text(row.get("avatar_url", ""))
        join_date_value = parse_period_end(row.get("join_date"))
        join_date = join_date_value.isoformat() if join_date_value else ""
        cached_avatar = cache_avatar(creator_id, avatar_url) if cache_avatars else None
        if cached_avatar:
            avatar_url, avatar_path = cached_avatar
        else:
            avatar_path = ""
        creators.append(
            {
                "creator_id": creator_id,
                "creator_name": row["creator_name"],
                "manager": clean_optional_text(row.get("manager", "")),
                "live_seconds": round(float(row['hours'])*3600),
                "live_streams": int(round(row['live_streams'])) if row['live_streams'] is not None and not pd.isna(row['live_streams']) else None,
                "diamonds": diamonds,
                "hours": hours,
                "days": days,
                "battles": battles,
                "new_followers": new_followers,
                "tier": get_tier(previous_month_diamonds if row['previous_month_known'] else diamonds),
                "preserve_existing_tier": not row['previous_month_known'],
                "rank": index + 1,
                "incentive_status": incentive_status(diamonds, days, hours, report_date),
                "avatar_url": avatar_url,
                "avatar_path": avatar_path,
                "join_date": join_date,
            }
        )

    ids = [row['creator_id'] for row in creators]
    if len(ids) != len(set(ids)):
        raise ImportErrorWithContext('Multiple creator names share a Creator ID; correct the report before importing.')
    for row in creators:
        if any(not math.isfinite(row[key]) or row[key] < 0 for key in ('diamonds', 'hours', 'days', 'battles', 'new_followers')):
            raise ImportErrorWithContext('Creator metrics must be finite, non-negative values.')
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return (creators, file_hash, report_date) if with_report_date else (creators, file_hash)


def import_spreadsheet(database, path: Path, report_date: date | None = None, publish: bool = True) -> ImportResult:
    from dataclasses import asdict
    from automation_store import utcnow

    creators, file_hash, observed_on = load_creators_from_spreadsheet(path, report_date, with_report_date=True)
    canonical = [{k: v for k, v in row.items() if k not in ('avatar_url', 'avatar_path')} for row in creators]
    snapshot_hash = hashlib.sha256(json.dumps(
        {'report_date': observed_on.isoformat(), 'creators': canonical}, sort_keys=True
    ).encode()).hexdigest()
    with database.transaction() as conn:
        latest = database.latest_import()
        if latest and observed_on.isoformat() < latest['report_date']:
            raise ImportErrorWithContext('This report is older than the current snapshot; import the latest report instead.')
        duplicate_row = conn.execute('SELECT * FROM import_runs WHERE snapshot_hash=?', (snapshot_hash,)).fetchone()
        if duplicate_row and latest and duplicate_row['id'] != latest['id']:
            raise ImportErrorWithContext('This upload is a superseded report version; the current corrected snapshot was preserved.')
        duplicate = duplicate_row is not None
        if duplicate:
            import_id = duplicate_row['id']
        else:
            previous = {c.creator_id: asdict(c) for c in database.get_creators()}
            legacy_duplicate = database.has_import_hash(file_hash)
            database.replace_creators(creators, path.name, file_hash, snapshot_hash)
            if not legacy_duplicate:
                database.update_referrals_from_snapshot(creators, observed_on)
            cursor = conn.execute("""INSERT INTO import_runs
                (report_date, imported_at, filename, snapshot_hash, creator_count)
                VALUES (?, ?, ?, ?, ?)""", (observed_on.isoformat(), utcnow(), path.name, snapshot_hash, len(creators)))
            import_id = cursor.lastrowid
            for creator in database.get_creators():
                row = asdict(creator)
                prior = [h for h in database.creator_history(creator.creator_id) if h['report_date'] < observed_on.isoformat()]
                before = prior[-1] if prior else None
                same_month = before and before['report_date'][:7] == observed_on.isoformat()[:7]
                row['rank_movement'] = before['rank'] - row['rank'] if before and same_month else 0
                conn.execute("""INSERT INTO creator_snapshots VALUES (?, ?, ?, ?)
                    ON CONFLICT(creator_id, report_date) DO UPDATE SET
                    import_id=excluded.import_id, payload=excluded.payload""",
                    (creator.creator_id, observed_on.isoformat(), import_id, json.dumps(row)))
            # Detection is installed independently of the import/parser business rules.
            from achievements import record_achievements
            record_achievements(database, previous, observed_on, import_id, publish)
        from website_sync import enqueue
        enqueue(conn, import_id, snapshot_hash, path.name, observed_on, creators)
    return ImportResult(len(creators), file_hash, sum(r['diamonds'] for r in creators),
                        sum(r['battles'] for r in creators), duplicate, observed_on, import_id)
