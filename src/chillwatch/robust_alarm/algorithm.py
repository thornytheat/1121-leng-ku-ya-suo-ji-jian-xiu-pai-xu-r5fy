from __future__ import annotations

from .contracts import AlarmMeasure

from math import exp, hypot, isfinite


def logistic(value):
    if value >= 0:
        return 1 / (1 + exp(-value))
    odds = exp(value)
    return odds / (1 + odds)


def interpret_channels(point, fit):
    pressure = fit['pressure']
    vibration = fit['vibration']
    pressure_delta = (point.pressure_kpa - pressure['center']) / pressure['scale']
    vibration_delta = (point.vibration - vibration['center']) / vibration['scale']
    # No bearing alarm should result from lower-than-usual vibration.
    robust_distance = hypot(pressure_delta * 0.7, max(vibration_delta, 0.0))
    if abs(pressure_delta) * 0.7 > max(0, vibration_delta):
        driver = 'HIGH_DISCHARGE' if pressure_delta > 0 else 'LOW_DISCHARGE'
    else:
        driver = 'BEARING_VIBRATION'
    return robust_distance, pressure_delta, vibration_delta, driver


def probability(distance, fit, midpoint):
    # Sparse family fallback has greater uncertainty and a higher midpoint.
    correction = 0.55 if fit['basis'] == 'FAMILY_BASELINE' else 0
    return logistic(1.7 * (distance - midpoint - correction))


def score_point(point, fit, threshold, midpoint, outlier_limit):
    base = {'unit': point.unit, 'minute': point.minute, 'vibration': point.vibration, 'pressure_kpa': point.pressure_kpa}
    if point.defrost:
        return base | {'eligible': False, 'score': None, 'reason': 'DEFROST_HOLD', 'alarm': False}
    if not fit or fit['pressure'] is None or fit['vibration'] is None:
        return base | {'eligible': False, 'score': None, 'reason': 'NO_REFERENCE', 'alarm': False}
    distance, pressure_delta, vibration_delta, driver = interpret_channels(point, fit)
    if distance >= outlier_limit:
        return base | {
            'eligible': False, 'score': None, 'alarm': False, 'reason': 'DOMAIN_REVIEW',
            'distance': distance, 'driver': driver, 'fit_id': fit['fit_id'],
        }
    confidence = probability(distance, fit, midpoint)
    return base | {
        'eligible': True,
        'score': confidence,
        'distance': distance,
        'alarm': confidence >= threshold,
        'reason': driver if confidence >= threshold else 'BASELINE_RANGE',
        'pressure_z': pressure_delta,
        'vibration_z': vibration_delta,
        'fit_id': fit['fit_id'],
        'threshold': threshold,
    }


def calculate(records, *, references, threshold=.8, midpoint=2.75, outlier_limit=18.0):
    if not 0 < threshold < 1 or not isfinite(midpoint) or not midpoint > 0 or not outlier_limit > midpoint:
        raise ValueError('INVALID_ALARM_LIMITS')
    by_unit = {item['unit']: item for item in references}
    if len(by_unit) != len(references):
        raise ValueError('DUPLICATE_UNIT_REFERENCE')
    return [score_point(point, by_unit.get(point.unit), threshold, midpoint, outlier_limit)
            for point in sorted(records, key=lambda item: (item.unit, item.minute))]
