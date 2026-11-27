from __future__ import annotations

from .contracts import MeterReading

from collections import defaultdict
from dataclasses import asdict


def pressure_kpa(value, scale):
    if scale == 'kPa':
        return value
    if scale == 'bar':
        return value * 100
    if scale == 'MPa':
        return value * 1000
    raise ValueError('PRESSURE_UNIT_UNKNOWN')


def packet_rejection(reading, cutoff):
    if reading.minute >= cutoff or reading.reported > cutoff:
        return 'AFTER_HANDOFF'
    if reading.reported < reading.minute:
        return 'CLOCK_INVERTED'
    if reading.vibration > 60:
        return 'SENSOR_SATURATION'
    try:
        pressure = pressure_kpa(reading.pressure, reading.scale)
    except ValueError:
        return 'UNIT_UNSUPPORTED'
    if not 100 <= pressure <= 2200:
        return 'PRESSURE_OUTSIDE_SENSOR'
    return None


def resolve_packet(group):
    latest = max(item.revision for item in group)
    revisions = [item for item in group if item.revision == latest]
    fingerprints = {
        (round(pressure_kpa(item.pressure, item.scale), 8), item.vibration, item.defrost)
        for item in revisions
    }
    if len(fingerprints) > 1:
        return None, len(group)
    canonical = min(revisions, key=lambda item: (item.reported, item.scale, item.pressure))
    return canonical, len(group) - 1


def evidence(reading, status, reason, superseded=0):
    return {
        **asdict(reading),
        'pressure_kpa': pressure_kpa(reading.pressure, reading.scale) if status == 'accepted' else None,
        'status': status,
        'reason': reason,
        'superseded': superseded,
    }


def calculate(records, *, cutoff):
    groups = defaultdict(list)
    result = []
    for reading in records:
        reason = packet_rejection(reading, cutoff)
        if reason:
            result.append(evidence(reading, 'excluded', reason))
        else:
            groups[reading.unit, reading.minute].append(reading)
    for key in sorted(groups):
        selected, repeats = resolve_packet(groups[key])
        if selected is None:
            representative = min(groups[key], key=lambda item: (item.revision, item.reported, item.pressure, item.vibration, item.scale, item.defrost))
            result.append(evidence(representative, 'excluded', 'REVISION_CONFLICT', repeats))
            continue
        result.append(evidence(selected, 'accepted', 'NORMALIZED', repeats))
    return sorted(result, key=lambda row: (row['unit'], row['minute'], row['reported'], row['reason']))
