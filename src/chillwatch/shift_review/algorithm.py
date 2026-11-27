from __future__ import annotations

from .contracts import ClosedIncident

from collections import defaultdict
from math import fsum, isfinite


def verified_observations(rows, as_of):
    evidence = {}
    ambiguous = set()
    rejected = defaultdict(int)
    for item in rows:
        if not item.inspected or item.measured > as_of or item.measured < item.minute:
            rejected['OPEN_OR_INVALID_INSPECTION'] += 1
            continue
        identity = item.unit, item.minute
        if identity in evidence and item != evidence[identity]:
            ambiguous.add(identity)
        evidence[identity] = item
    for identity in ambiguous:
        rejected['CONFLICTING_OUTCOME'] += 1
        evidence.pop(identity)
    return [evidence[key] for key in sorted(evidence)], dict(rejected)


def precision_recall(points):
    matrix = {'detected': 0, 'false_alarm': 0, 'missed': 0, 'cleared': 0}
    for row in points:
        if row.confirmed:
            matrix['detected' if row.alarm else 'missed'] += 1
        else:
            matrix['false_alarm' if row.alarm else 'cleared'] += 1
    positives = matrix['detected'] + matrix['missed']
    alarms = matrix['detected'] + matrix['false_alarm']
    matrix['precision'] = matrix['detected'] / alarms if alarms else None
    matrix['recall'] = matrix['detected'] / positives if positives else None
    matrix['positive_status'] = 'NORMAL' if positives else 'NO_CONFIRMED_FAULT'
    return matrix


def calibration_bins(points, thresholds):
    lower = 0.0
    summaries = []
    for number, upper in enumerate(thresholds):
        observed = [row for row in points if lower <= row.score < upper or (number == len(thresholds)-1 and row.score == upper)]
        count = len(observed)
        expected = fsum(row.score for row in observed) / count if count else None
        actual = sum(row.confirmed for row in observed) / count if count else None
        summaries.append({
            'range': f'{lower:.2f}–{upper:.2f}',
            'total': count,
            'model_mean': expected,
            'actual_rate': actual,
            'absolute_gap': abs(actual - expected) if count else None,
        })
        lower = upper
    return summaries


def calculate(records, *, as_of, thresholds=(.2, .4, .6, .8, 1.0)):
    if not thresholds or thresholds[-1] != 1 or any(
        not isfinite(end) or end <= start for start, end in zip((0, *thresholds), thresholds)
    ):
        raise ValueError('INVALID_SCORE_BANDS')
    verified, rejected = verified_observations(records, as_of)
    bands = calibration_bins(verified, thresholds)
    count = len(verified)
    ece = fsum(item['total'] * item['absolute_gap'] for item in bands if item['total']) / count if count else None
    return [{'type': 'summary', 'verified': count, 'ece': ece, 'exclusions': rejected} | precision_recall(verified),
            *[{'type': 'band', **band} for band in bands]]
