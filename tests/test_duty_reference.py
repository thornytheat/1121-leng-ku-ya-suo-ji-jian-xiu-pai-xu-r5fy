from dataclasses import replace
import math

import pytest

from chillwatch.duty_reference.contracts import DutyPoint, InvalidRow, parse
from chillwatch.duty_reference.service import evaluate, validate
from chillwatch.duty_reference import algorithm

def series(unit='F1', family='screw', size=7):
    return [dict(unit=unit, family=family, minute=10 + t, pressure_kpa=900 + 4*t, vibration=1 + t/10, defrost=False) for t in range(size)]


def test_pointwise_center_matches_independent_reference():
    expected = 912
    ref = evaluate(series(), cutoff=20)['records'][0]
    assert ref['pressure']['center'] == expected
    assert ref['pressure']['iqr'] == 12


def test_constant_history_retains_instrument_floor():  # TRAP-32
    constant = algorithm.robust_summary([1e6, 1e6, 1e6], .08)
    assert constant['scale'] == .08
    assert constant['center'] == 1e6
    assert constant['iqr'] == 0


def test_future_reading_cannot_change_fit_or_family():
    history = series()
    changed = history + [dict(history[0], minute=25, family='scroll', vibration=15)]
    assert evaluate(history, cutoff=20)['records'] == evaluate(changed, cutoff=20)['records']


def test_cutoff_interval_uses_half_open_boundaries():  # TRAP-23
    rows = series(size=8)
    ref = evaluate(rows, cutoff=16, lookback=4, group_min=2)['records'][0]
    assert ref['history_points'] == 4
    assert ref['pressure']['minimum'] == 908
    assert ref['pressure']['maximum'] == 920


def test_sparse_unit_can_use_its_own_machine_family():
    first, second = evaluate(series(unit='F1', size=2) + series(unit='F2'), cutoff=20)['records']
    assert first['basis'] == 'FAMILY_BASELINE'
    assert first['history_points'] == 9
    assert second['basis'] == 'INDIVIDUAL_BASELINE'


def test_defrost_is_removed_before_fitting():
    history = series()
    changed = history + [dict(history[0], minute=19, defrost=True, vibration=60)]
    assert evaluate(history, cutoff=20)['records'] == evaluate(changed, cutoff=20)['records']


def test_training_key_carries_upstream_digest_and_configuration():  # TRAP-54
    rows = series()
    key = evaluate(rows, cutoff=20)['records'][0]['fit_id']
    reconfigured = evaluate(rows, cutoff=20, group_min=4)['records'][0]['fit_id']
    adjusted = evaluate(rows[:-1] + [rows[-1] | {'vibration': 2.7}], cutoff=20)['records'][0]['fit_id']
    assert len({key, reconfigured, adjusted}) == 3


def test_disagreeing_training_revision_is_not_counted_twice():
    rows = series()
    ref = evaluate(rows + [rows[0] | {'vibration': 3}], cutoff=20)['records'][0]
    assert ref['history_points'] == 6
