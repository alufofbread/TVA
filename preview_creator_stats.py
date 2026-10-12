from pathlib import Path
from datetime import date
from database import Creator, Referral
from dashboard.trends import TrendPoint
from dashboard.creator_stats import render_creator_stats

creator = Creator('preview', 'arla.live', 384600, 87.25, 22, 0, 1284, 4, 4, 'ACHIEVED', '', '', '', '')
# Illustrative referrals: the supplied brief does not include the reference records.
referrals = [Referral(i, 'preview', 'arla.live', str(i), name, '', '', diamonds, hours, 0, 0, days, 0, 'ACTIVE', '') for i, name, diamonds, hours, days in [(1, 'luna.live', 126400, 42.5, 8), (2, 'kai.creates', 62800, 28.25, 16), (3, 'nova.streams', 24300, 16.5, 23)]]
points = [TrendPoint(date(2026, 9, 22), 25800, 4, 65), TrendPoint(date(2026, 9, 17), 18000, 3, 90)]
if __name__ == '__main__':
    import sys
    render_creator_stats(creator, 10, Path(sys.argv[1] if len(sys.argv) > 1 else 'previews/creator-stats-after.png'), referrals, points)
