"""UK calendar windows and independently verified MTD differences."""
from datetime import date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo


def uk_today(now=None):
    return (now or datetime.now(ZoneInfo('Europe/London'))).astimezone(ZoneInfo('Europe/London')).date()


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) and value >= 0 else None


def snapshots(history, metric):
    result = {}
    for row in history:
        day = date.fromisoformat(row['report_date'])
        value = number(row.get(metric))
        # A conflict is sticky. Input order must never choose the winning copy.
        if day in result and result[day] != value:
            result[day] = None
        elif day not in result:
            result[day] = value
    return result


def daily_value(values, day):
    current = values.get(day)
    previous = values.get(day - timedelta(days=1)) if day.day != 1 else 0
    if current is not None and previous is not None and current<previous:
        return None
    # Zero is only proven by a present zero snapshot, never by an absent row.
    if current == 0:
        return 0
    if current is None or previous is None or current < previous:
        return None
    return current - previous


def calendar_window(history, days=7, end=None, now=None, metric='diamonds'):
    if days not in (3, 7):
        raise ValueError('Choose a 3 or 7 day calendar window')
    end = end or uk_today(now)
    if isinstance(end, str):
        end = date.fromisoformat(end)
    values = snapshots(history, metric)
    return [dict(date=end-timedelta(days=offset), diamonds=daily_value(values,end-timedelta(days=offset)))
            for offset in range(days-1, -1, -1)]
