from collections import Counter

from .algorithm import place_in_order
from .contracts import parse


def seal_episode(unit, run, end_reason, min_points):
    descriptions = Counter(point.reason for point in run)
    first,last = run[0],run[-1]
    return {'unit':unit,'duty':first.duty,'start':first.minute,'end':last.minute,
            'elapsed':last.minute-first.minute,'samples':len(run),'confirmed':len(run)>=min_points,
            'reason_counts':dict(descriptions),'end_reason':end_reason}


def event_break(row, previous, gap):
    if not row.eligible:
        return row.reason
    if not row.alarm:
        return 'RETURNED_TO_BASELINE'
    if previous.duty != row.duty:
        return 'DUTY_CHANGED'
    if row.minute-previous.minute>gap:
        return 'MEASUREMENT_GAP'
    return None


def extract_episodes(rows, *, max_gap=12, min_points=2):
    if max_gap<1 or min_points<2:
        raise ValueError('INVALID_EPISODE_CONSTRAINTS')
    grouped = place_in_order([parse(item) for item in rows])
    result = []
    for unit, timeline in grouped.items():
        points = []
        for row in timeline:
            if points:
                reason = event_break(row,points[-1],max_gap)
                if reason:
                    result.append(seal_episode(unit,points,reason,min_points))
                    points = []
            if row.eligible and row.alarm:
                points.append(row)
        if points:
            result.append(seal_episode(unit,points,'ACTIVE_AT_HANDOFF',min_points))
    return result
