from dataclasses import replace
import math

import pytest

from chillwatch.persistence_filter.contracts import TimedAlarm, InvalidRow, parse
from chillwatch.persistence_filter.service import evaluate, validate
from chillwatch.persistence_filter import algorithm

def alarm(minute, **changes):
    return dict(unit='F1', minute=minute, alarm=True, eligible=True, reason='BEARING_VIBRATION', duty='晚班') | changes


def test_alarm_needs_two_consecutive_readings():
    score = evaluate([alarm(4), alarm(16)])['records'][0]
    assert score['decision'] == 'CONFIRMED'
    assert score['persisted'] == 2


def test_outage_gap_breaks_streak():
    score = evaluate([alarm(4), alarm(17)])['records'][0]
    assert score['decision'] == 'MONITOR'
    assert score['first_alarm'] == 17


def test_recovery_clears_previous_confirmed_streak():
    score = evaluate([alarm(4), alarm(7), alarm(10, alarm=False)])['records'][0]
    assert score['longest'] == 2
    assert score['persisted'] == 0


def test_defrost_interrupts_streak_with_explicit_reason():
    affected = [alarm(4), alarm(6, eligible=False, reason='DEFROST_HOLD'), alarm(9)]
    score = evaluate(affected)['records'][0]
    assert score['persisted'] == 1
    assert score['skips'] == {'DEFROST_HOLD': 1}


def test_shift_change_breaks_continuity():
    score = evaluate([alarm(4), alarm(5, duty='白班')])['records'][0]
    assert score['decision'] == 'MONITOR'
    assert score['first_alarm'] == 5


def test_duplicate_does_not_create_second_vote():
    event = alarm(4)
    row = evaluate([event, event])['records'][0]
    assert row['persisted'] == 1


def test_conflicting_packets_break_streak():
    affected = [alarm(3), alarm(4), alarm(4, eligible=False), alarm(7)]
    assert evaluate(affected)['records'][0]['skips'] == {'CONTRADICTORY_ALARM': 1}


def test_interleaved_equipment_does_not_bleed():
    affected = [alarm(8), alarm(5, unit='F2'), alarm(4)]
    result = evaluate(affected)['records']
    assert [(row['unit'], row['persisted']) for row in result] == [('F1', 2), ('F2', 1)]
