from dataclasses import replace
import math

import pytest

from chillwatch.robust_alarm.contracts import AlarmMeasure, InvalidRow, parse
from chillwatch.robust_alarm.service import evaluate, validate
from chillwatch.robust_alarm import algorithm

def fit(unit='F1', basis='INDIVIDUAL_BASELINE'):
    return {'unit': unit, 'basis': basis, 'pressure': {'center': 1000, 'scale': 20},
            'vibration': {'center': 2, 'scale': .2}, 'fit_id': 'shift-a'}


def measure(**changes):
    return dict(unit='F1', minute=77, pressure_kpa=1000, vibration=2, defrost=False) | changes


def test_sigmoid_does_not_overflow_at_large_magnitude():  # TRAP-31
    assert algorithm.logistic(-1000) == 0
    assert algorithm.logistic(1000) == 1
    assert algorithm.logistic(0) == .5


def test_single_point_stays_fixed_in_python_batches():  # TRAP-53
    one = evaluate([measure(vibration=3)], references=[fit()])['records'][0]
    batch = evaluate([measure(vibration=3), measure(unit='F2', vibration=20)], references=[fit()])['records']
    assert one == batch[0]
    assert batch[1]['reason'] == 'NO_REFERENCE'


def test_out_of_domain_reading_is_not_automated_high_confidence():  # TRAP-44
    row = evaluate([measure(vibration=20)], references=[fit()])['records'][0]
    assert row['reason'] == 'DOMAIN_REVIEW'
    assert row['score'] is None
    assert row['alarm'] is False


def test_family_fallback_dampens_risk():
    known = evaluate([measure(vibration=3)], references=[fit()])['records'][0]['score']
    family = evaluate([measure(vibration=3)], references=[fit(basis='FAMILY_BASELINE')])['records'][0]['score']
    assert 0 < family < known < 1


def test_pressure_explains_low_discharge():
    evidence = evaluate([measure(pressure_kpa=880)], references=[fit()])['records'][0]
    assert evidence['reason'] == 'LOW_DISCHARGE'
    assert evidence['distance'] == pytest.approx(4.2)


def test_defrost_is_audit_hold():
    row = evaluate([measure(vibration=7, defrost=True)], references=[fit()])['records'][0]
    assert not row['eligible']
    assert row['reason'] == 'DEFROST_HOLD'


def test_declining_vibration_alone_cannot_raise_alarm():
    row = evaluate([measure(vibration=.1)], references=[fit()])['records'][0]
    assert row['distance'] == 0
    assert row['reason'] == 'BASELINE_RANGE'


def test_duplicate_fit_cannot_be_silently_overwritten():
    with pytest.raises(ValueError, match='DUPLICATE_UNIT'):
        evaluate([measure()], references=[fit(), fit()])
