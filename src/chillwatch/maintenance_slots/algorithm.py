from __future__ import annotations

from .contracts import WorkCandidate

from dataclasses import asdict
from math import isfinite


def reconcile_candidates(records):
    by_unit = {}
    for row in records:
        if row.unit in by_unit and by_unit[row.unit] != row:
            raise ValueError(f'MAINTENANCE_INPUT_CONFLICT:{row.unit}')
        by_unit[row.unit] = row
    return sorted(by_unit.values(), key=lambda item: (-item.priority, item.allowed_end, item.unit))


def block_position(row, racks, crews, shift_start, shift_end):
    start = max(shift_start, row.allowed_start)
    stop = min(row.allowed_end, shift_end)
    reserved = sorted(racks[row.rack])
    for minute in range(start, stop - row.runtime + 1):
        end = minute + row.runtime
        if any(minute < other_end and other_start < end for other_start, other_end in reserved):
            continue
        for index, spans in enumerate(crews, 1):
            if all(end <= other_start or other_end <= minute for other_start, other_end in spans):
                return index, minute, end
    return None


def describe(row, state, reason, span=None):
    slot = {'crew': None, 'start': None, 'end': None}
    if span:
        slot = dict(zip(slot, span, strict=True))
    return asdict(row) | slot | {'state': state, 'reason': reason}


def requires_only_observation(row):
    if row.decision == 'CONFIRMED':
        return None
    if row.driver == 'DOMAIN_REVIEW':
        return 'MANUAL_GAUGE_CHECK'
    return 'PERSISTENCE_NOT_CONFIRMED'


def calculate(records, *, capacity=4, crew_count=2, start=600, end=735):
    from collections import defaultdict

    if capacity < 1 or crew_count < 1 or start >= end or not all(map(isfinite, [start, end])):
        raise ValueError('INVALID_SHIFT_CAPACITY')
    result = []
    crews = [[] for _ in range(crew_count)]
    racks = defaultdict(list)
    awarded = 0
    for row in reconcile_candidates(records):
        review_only = requires_only_observation(row)
        if review_only:
            item = describe(row, '观察', review_only)
        elif not row.has_backup:
            item = describe(row, '暂缓', 'NO_REDUNDANT_COMPRESSOR')
        elif row.allowed_start >= row.allowed_end:
            item = describe(row, '暂缓', 'INVALID_MAINTENANCE_WINDOW')
        elif awarded >= capacity:
            item = describe(row, '候补', 'SHIFT_CAPACITY_EXHAUSTED')
        else:
            span = block_position(row, racks, crews, start, end)
            if span is None:
                item = describe(row, '候补', 'NO_NONOVERLAP_WINDOW')
            else:
                crew, begins, finishes = span
                racks[row.rack].append((begins, finishes))
                crews[crew - 1].append((begins, finishes))
                item = describe(row, '已排检', row.driver, span)
                awarded += 1
        result.append(item)
    return result
