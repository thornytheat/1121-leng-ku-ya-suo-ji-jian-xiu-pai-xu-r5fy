from dataclasses import replace
import math

import pytest

from chillwatch.maintenance_slots.contracts import WorkCandidate, InvalidRow, parse
from chillwatch.maintenance_slots.service import evaluate, validate
from chillwatch.maintenance_slots import algorithm

def work(unit, **changes):
    return dict(unit=unit, rack='R1', decision='CONFIRMED', driver='BEARING_VIBRATION', runtime=30,
                priority=90, has_backup=True, allowed_start=600, allowed_end=700) | changes


def test_same_rack_cannot_stop_two_compressors():
    rows = evaluate([work('F1'), work('F2')])['records']
    assert rows[0]['end'] == rows[1]['start']
    assert rows[1]['end'] == 660


def test_distinct_racks_occupy_different_crews():
    rows = evaluate([work('F1'), work('F2', rack='R2')])['records']
    assert rows[0]['start'] == rows[1]['start'] == 600
    assert {row['crew'] for row in rows} == {1, 2}


def test_missing_backup_has_precedence_over_capacity_limit():
    rows = evaluate([work('F1'), work('F2', has_backup=False)], capacity=1)['records']
    assert rows[1]['reason'] == 'NO_REDUNDANT_COMPRESSOR'


def test_priority_then_deadline_then_unit_is_stable():
    records = [work('F5', priority=60), work('F4', allowed_end=668), work('F2', allowed_end=668)]
    rows = evaluate(reversed(records), capacity=1)['records']
    assert [row['unit'] for row in rows] == ['F2', 'F4', 'F5']
    assert rows[1]['state'] == '候补'


def test_end_equal_to_cutoff_is_valid():
    row = evaluate([work('F1', allowed_start=670, allowed_end=700)])['records'][0]
    assert row['end'] == 700


def test_very_narrow_window_stays_queued():
    row = evaluate([work('F1', allowed_start=671, allowed_end=700)])['records'][0]
    assert row['start'] is None
    assert row['reason'] == 'NO_NONOVERLAP_WINDOW'


def test_unconfirmed_anomaly_has_manual_gauge_check():
    row = evaluate([work('F1', decision='MONITOR', driver='DOMAIN_REVIEW')])['records'][0]
    assert row['reason'] == 'MANUAL_GAUGE_CHECK'


def test_conflicting_equipment_assignment_is_rejected():
    with pytest.raises(ValueError, match='MAINTENANCE_INPUT_CONFLICT'):
        evaluate([work('F1'), work('F1', rack='R2')])
