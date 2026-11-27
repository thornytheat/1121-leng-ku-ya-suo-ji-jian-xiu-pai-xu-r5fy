from __future__ import annotations

from .contracts import TimedAlarm

from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass(slots=True)
class AlarmRun:
    first: int | None = None
    last: int | None = None
    observations: int = 0
    duty: str | None = None
    reasons: Counter = field(default_factory=Counter)

    def open(self, row):
        return AlarmRun(row.minute, row.minute, 1, row.duty, Counter([row.reason]))

    def append(self, row, gap):
        if self.last is None or row.minute - self.last > gap or self.duty != row.duty:
            return self.open(row)
        self.last = row.minute
        self.observations += 1
        self.reasons[row.reason] += 1
        return self

    def driver(self):
        return min(self.reasons, key=lambda reason: (-self.reasons[reason], reason)) if self.reasons else None


def place_in_order(rows):
    groups = defaultdict(set)
    for row in rows:
        groups[row.unit, row.minute].add(row)
    ordered = defaultdict(list)
    for (unit, minute), readings in sorted(groups.items()):
        if len(readings) == 1:
            ordered[unit].append(next(iter(readings)))
        else:
            ordered[unit].append(TimedAlarm(unit, minute, False, False, 'CONTRADICTORY_ALARM', 'unknown'))
    return ordered


def evaluate_unit(unit, observations, max_gap, min_points):
    current, maximum = AlarmRun(), 0
    skipped = Counter()
    for row in observations:
        if not row.eligible:
            skipped[row.reason] += 1
            current = AlarmRun()
            continue
        if row.alarm:
            current = current.append(row, max_gap)
            maximum = max(maximum, current.observations)
        else:
            current = AlarmRun()
    confirmed = current.observations >= min_points
    return {
        'unit': unit,
        'first_alarm': current.first,
        'last_alarm': current.last,
        'persisted': current.observations,
        'longest': maximum,
        'latest_reading': observations[-1].minute,
        'skips': dict(skipped),
        'decision': 'CONFIRMED' if confirmed else 'MONITOR',
        'driver': current.driver() or max(skipped, key=lambda reason: (skipped[reason], reason), default='CLEAR'),
    }


def calculate(records, *, max_gap=12, min_points=2):
    if max_gap <= 0 or min_points < 2:
        raise ValueError('INVALID_STREAK_POLICY')
    ordered = place_in_order(records)
    return [evaluate_unit(unit, observations, max_gap, min_points) for unit, observations in ordered.items()]
