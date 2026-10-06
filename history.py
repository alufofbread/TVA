"""Report-date history shared by trends and achievement detection."""
from datetime import date, timedelta


def daily_points(history):
    """Only adjacent report dates give a reliable daily delta.

    Month-to-date values on day one are themselves daily values. Missing days
    and downward corrections are gaps, never invented personal bests.
    """
    points = []
    previous = None
    for row in history:
        current = date.fromisoformat(row['report_date'])
        metrics = ('diamonds', 'hours', 'new_followers')
        if current.day == 1:
            values = {metric: row[metric] for metric in metrics}
        elif previous and current - date.fromisoformat(previous['report_date']) == timedelta(days=1) and current.month == date.fromisoformat(previous['report_date']).month:
            values = {metric: row[metric] - previous[metric] for metric in metrics}
            if any(value < 0 for value in values.values()):
                values = None
        else:
            values = None
        if values is not None:
            points.append(dict(report_date=row['report_date'], **values))
        previous = row
    return points
