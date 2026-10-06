"""Historical achievement detection. Announcements are separately opt-in."""
from config import ANNOUNCE_ACHIEVEMENTS, DIAMOND_MILESTONES
from history import daily_points
from dashboard.style import league_name


def record_achievements(database, previous, report_date, import_id, publish):
    day, month = report_date.isoformat(), report_date.isoformat()[:7]
    with database.connect() as conn:
        def record(row, kind, suffix, description, baseline=False):
            key = f'{row["creator_id"]}:{kind}:{suffix}'
            conn.execute('''INSERT OR IGNORE INTO achievements
                (achievement_key, creator_id, report_date, kind, description, import_id, publish)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (key, row['creator_id'], day, kind, description, import_id,
                 int(publish and not baseline and kind in ANNOUNCE_ACHIEVEMENTS)))

        for creator in database.get_creators():
            history = database.creator_history(creator.creator_id)
            row = history[-1]
            older = [h for h in history if h['report_date'] < day]
            before = older[-1] if older else None
            baseline = not older
            name = creator.creator_name
            for threshold in DIAMOND_MILESTONES:
                if row['diamonds'] >= threshold:
                    record(row, 'milestone', f'{month}:{threshold}', f'{name} reached {threshold:,} diamonds this month!', baseline)
            if row['incentive_status'] == 'ACHIEVED':
                record(row, 'incentive', month, f'{name} completed the monthly incentive!', baseline)
            if before and before['tier'] != row['tier']:
                record(row, 'league', f'{day}:{row["tier"]}',
                       f'{name}: {league_name(before["tier"])} (tier {before["tier"]}) to {league_name(row["tier"])} (tier {row["tier"]}).')
            if before and before['report_date'][:7] == month and before['rank'] != row['rank']:
                record(row, 'rank', day, f'{name} moved from rank #{before["rank"]} to #{row["rank"]}.')
            points = daily_points(history)
            if not points or points[-1]['report_date'] != day:
                continue
            current, past = points[-1], points[:-1]
            for metric in ('diamonds', 'hours', 'new_followers'):
                if current[metric] > 0 and (not past or current[metric] > max(p[metric] for p in past)):
                    # First reliable day establishes a baseline without public noise.
                    record(row, 'pb', f'{day}:{metric}',
                           f'{name} set a daily {metric.replace("_", " ")} PB: {current[metric]:,}.', not past)
