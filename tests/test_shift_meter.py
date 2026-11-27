from dataclasses import replace
import math

import pytest

from chillwatch.shift_meter.contracts import MeterReading, InvalidRow, parse
from chillwatch.shift_meter.service import evaluate, validate
from chillwatch.shift_meter import algorithm

def packet(**changes):
    values = dict(unit='F1', minute=103, reported=104, pressure=10, scale='bar', vibration=2.4, defrost=False, revision=1)
    return values | changes


def test_unit_conversion():
    expected = [algorithm.pressure_kpa(value, unit) for value, unit in [(10, 'bar'), (1000, 'kPa'), (1, 'MPa')]]
    assert expected == [1000, 1000, 1000]


def test_no_post_cutoff_readings_in_history():  # TRAP-42
    active = packet()
    audited = evaluate([active, packet(minute=102, reported=151), packet(minute=150, reported=150)], cutoff=150)
    assert [row['minute'] for row in audited['records'] if row['status'] == 'accepted'] == [103]
    assert sum(row['reason'] == 'AFTER_HANDOFF' for row in audited['records']) == 2


def test_calibrated_duplicate_resolution():
    audited = evaluate([packet(), packet(scale='kPa', pressure=1000)], cutoff=150)
    assert len(audited['records']) == 1
    assert audited['records'][0]['superseded'] == 1


def test_revision_order_cannot_change_conflict():  # TRAP-19
    values = [packet(vibration=2), packet(vibration=3), packet(revision=2), packet(revision=2, vibration=4)]
    one = evaluate(values, cutoff=150)
    two = evaluate(reversed(values), cutoff=150)
    assert one == two
    assert one['records'][0]['reason'] == 'REVISION_CONFLICT'


def test_valid_later_revision_supersedes_old():
    audited = evaluate([packet(revision=3, pressure=11), packet(revision=1, pressure=12)], cutoff=150)
    assert audited['records'][0]['pressure_kpa'] == 1100
    assert audited['records'][0]['revision'] == 3


def test_clock_inversion_is_not_field_error():
    audited = evaluate([packet(reported=95)], cutoff=150)
    assert audited['accepted_count'] == 1
    assert audited['records'][0]['reason'] == 'CLOCK_INVERTED'


def test_sensor_saturation_is_quarantined():
    audited = evaluate([packet(vibration=61), packet(unit='F2', vibration=3)], cutoff=150)
    assert audited['records'][0]['reason'] == 'SENSOR_SATURATION'
    assert audited['records'][1]['status'] == 'accepted'


def test_non_finite_reading_reports_field_and_line():
    audited = evaluate([packet(), packet(pressure=float('nan'))], cutoff=150)
    assert audited['errors'] == [{'line': 2, 'field': 'shift_meter.pressure', 'code': 'OUT_OF_RANGE'}]
