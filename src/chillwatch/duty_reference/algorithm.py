from __future__ import annotations

from .contracts import DutyPoint

from collections import defaultdict
from statistics import median, quantiles
import hashlib
import json


def robust_summary(values, minimum_scale):
    if not values:
        return None
    center = median(values)
    deviations = [abs(value - center) for value in values]
    mad = median(deviations)
    # The floor is the instrument resolution, in the same unit as the channel.
    lower_quartile, _, upper_quartile = quantiles(values, n=4, method='inclusive') if len(values) > 1 else (center,) * 3
    return {
        'center': center,
        'scale': max(minimum_scale, 1.4826 * mad),
        'iqr': upper_quartile - lower_quartile,
        'minimum': min(values),
        'maximum': max(values),
    }


def select_history(records, start, cutoff):
    selected = {}
    conflicted = set()
    for item in records:
        if item.defrost or not start <= item.minute < cutoff:
            continue
        key = item.unit, item.minute
        if key in selected and item != selected[key]:
            conflicted.add(key)
        selected[key] = item
    return [selected[key] for key in sorted(selected) if key not in conflicted]


def baseline_identity(points, cutoff, lookback, group_min):
    input_signature = [
        (item.unit, item.family, item.minute, item.pressure_kpa, item.vibration)
        for item in points
    ]
    config_and_inputs = [cutoff, lookback, group_min, input_signature]
    return hashlib.sha256(json.dumps(config_and_inputs, separators=(',', ':')).encode()).hexdigest()[:16]


def by_plant_family(history):
    output = defaultdict(list)
    for reading in history:
        output[reading.family].append(reading)
    return output


def calculate(records, *, cutoff, lookback=360, group_min=5):
    if group_min < 2 or lookback < 1:
        raise ValueError('INVALID_BASELINE_WINDOW')
    history = select_history(records, cutoff - lookback, cutoff)
    family_lookup = by_plant_family(history)
    by_unit = defaultdict(list)
    for item in records:
        by_unit[item.unit].append(item)
    result = []
    for unit, points in sorted(by_unit.items()):
        unit_history = [item for item in history if item.unit == unit]
        known_families = {item.family for item in unit_history}
        family = next(iter(known_families)) if len(known_families) == 1 else None
        if family is None:
            partition, source = [], 'FAMILY_UNRESOLVED'
        elif len(unit_history) >= group_min:
            partition, source = unit_history, 'INDIVIDUAL_BASELINE'
        else:
            partition = family_lookup[family]
            source = 'FAMILY_BASELINE' if len(partition) >= group_min else 'INSUFFICIENT_BASELINE'
        valid = len(partition) >= group_min
        result.append({
            'unit': unit,
            'family': family,
            'basis': source,
            'history_points': len(partition),
            'unit_history_points': len(unit_history),
            'pressure': robust_summary([row.pressure_kpa for row in partition], 12) if valid else None,
            'vibration': robust_summary([row.vibration for row in partition], 0.08) if valid else None,
            'fit_id': baseline_identity(partition, cutoff, lookback, group_min),
            'window_start': cutoff - lookback,
            'window_end': cutoff,
        })
    return result
