from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from math import fsum

from .algorithm import block_position, describe, requires_only_observation
from .contracts import parse
from .work_order_proof import reconcile_schedule


@dataclass(frozen=True, slots=True)
class ShiftOption:
    capacity: int
    crews: int
    start: int
    end: int
    schedule: tuple[dict, ...]
    explored: int
    blocked: tuple[tuple[str, int], ...]

    @property
    def rank(self):
        return ranking(self.schedule)

    def evidence(self):
        return {
            'capacity': self.capacity,
            'crews': self.crews,
            'schedule': list(self.schedule),
            'coverage_points': self.rank[0],
            'bottlenecks': dict(self.blocked),
            'explored_orders': self.explored,
            'audit': reconcile_schedule(self.schedule, start=self.start, end=self.end, crew_count=self.crews),
        }


def ranking(work):
    scheduled_risk = fsum(item['priority'] for item in work)
    completed = len(work)
    cumulative_finish = sum(item['end'] for item in work)
    return scheduled_risk, completed, -cumulative_finish


def replay_order(items, capacity, crews, begin, end):
    slots = [[] for _ in range(crews)]
    racks = {item.rack: [] for item in items}
    scheduled = []
    held = Counter()
    for candidate in items:
        if len(scheduled) >= capacity:
            held['SHIFT_CAPACITY'] += 1
            continue
        span = block_position(candidate,racks,slots,begin,end)
        if span is None:
            held['WINDOW_OR_REDUNDANCY'] += 1
            continue
        index,start,stop = span
        racks[candidate.rack].append((start,stop))
        slots[index-1].append((start,stop))
        scheduled.append(describe(candidate, '已排检', candidate.driver, span))
    return tuple(scheduled), held


def candidate_orders(items, budget):
    alternatives = (
        sorted(items, key=lambda row:(-row.priority,row.allowed_end,row.unit)),
        sorted(items, key=lambda row:(row.allowed_end,-row.priority,row.unit)),
        sorted(items, key=lambda row:(row.allowed_end-row.runtime,-row.priority,row.unit)),
        sorted(items, key=lambda row:(row.runtime,-row.priority,row.unit)),
        sorted(items, key=lambda row:(row.allowed_start,-row.priority,row.unit)),
        sorted(items, key=lambda row:(-row.priority/row.runtime,row.allowed_end,row.unit)),
    )
    seen = set()
    for rows in alternatives:
        signature = tuple(row.unit for row in rows)
        if signature not in seen:
            seen.add(signature)
            yield rows
            if len(seen) >= budget:
                return
        for left, right in combinations(range(len(rows)),2):
            changed = rows[:]
            changed[left],changed[right] = changed[right],changed[left]
            signature = tuple(row.unit for row in changed)
            if signature in seen:
                continue
            seen.add(signature)
            yield changed
            if len(seen) >= budget:
                return


def eligible_requests(rows, begin, end):
    held = Counter()
    selected = {}
    for record in rows:
        row = parse(record)
        if row.unit in selected:
            if selected[row.unit] != row:
                raise ValueError(f'AMBIGUOUS_CAPACITY_INPUT:{row.unit}')
        selected[row.unit] = row
    result = []
    for row in selected.values():
        review_reason = requires_only_observation(row)
        if review_reason:
            held[review_reason]+=1
        elif not row.has_backup:
            held['NO_REDUNDANT_COMPRESSOR']+=1
        elif max(row.allowed_start,begin)+row.runtime > min(row.allowed_end,end):
            held['OUTSIDE_SHIFT_WINDOW']+=1
        else:
            result.append(row)
    return result,held


def best_plan(items, excluded, capacity, crews, begin, end, budget):
    selected = ()
    remaining = Counter()
    tried = 0
    for ordered in candidate_orders(items,budget):
        schedule,issues = replay_order(ordered,capacity,crews,begin,end)
        tried += 1
        left = ranking(schedule)
        right = ranking(selected)
        if left > right or tried == 1:
            selected = schedule
            remaining = issues
        elif left == right and tuple(row['unit'] for row in schedule)<tuple(row['unit'] for row in selected):
            selected = schedule
            remaining = issues
    blocked = tuple(sorted((excluded+remaining).items()))
    return ShiftOption(capacity,crews,begin,end,selected,tried,blocked)


def simulate_staffing(rows, *, capacity=4, crew_levels=(1,2,3), start=600, end=735, order_budget=45):
    """Recompute feasible schedules for a bounded set of staffing alternatives."""
    if type(capacity) is not int or capacity<1 or not crew_levels or start>=end or not 4<=order_budget<=150:
        raise ValueError('INVALID_STAFFING_OPTION')
    levels = sorted(set(crew_levels))
    if not all(type(value) is int and 1<=value<=12 for value in levels):
        raise ValueError('INVALID_CREW_SCENARIO')
    items,excluded = eligible_requests(rows,start,end)
    results = []
    for crew_count in levels:
        option = best_plan(items,excluded,capacity,crew_count,start,end,order_budget)
        outcome = option.evidence()
        outcome['additional_coverage'] = option.rank[0] - results[-1]['coverage_points'] if results else 0
        results.append(outcome)
    return results
