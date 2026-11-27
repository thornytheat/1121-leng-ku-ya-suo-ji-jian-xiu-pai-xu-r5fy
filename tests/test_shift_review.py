from dataclasses import replace
import math

import pytest

from chillwatch.shift_review.contracts import ClosedIncident, InvalidRow, parse
from chillwatch.shift_review.service import evaluate, validate
from chillwatch.shift_review import algorithm

def outcome(unit='F1', **changes):
    return dict(unit=unit, minute=9, score=.92, alarm=True, inspected=True, confirmed=True, measured=11) | changes


def test_lacking_positive_outcomes_does_not_produce_perfect_recall():  # TRAP-43
    score = evaluate([outcome(confirmed=False)], as_of=20)['records'][0]
    assert score['recall'] is None
    assert score['precision'] == 0
    assert score['positive_status'] == 'NO_CONFIRMED_FAULT'


def test_diagnostics_distinguish_faults_that_were_missed():
    rows = [outcome(), outcome('F2', alarm=False), outcome('F3', confirmed=False)]
    score = evaluate(rows, as_of=20)['records'][0]
    assert score['precision'] == score['recall'] == .5
    assert score['missed'] == 1


def test_empty_verified_batch_marks_metrics_unavailable():
    score = evaluate([], as_of=20)['records'][0]
    assert score['verified'] == 0
    assert score['ece'] is None


def test_perfect_one_and_score_boundary_each_have_one_band():
    audited = evaluate([outcome(score=.2), outcome('F2', score=1)], as_of=20)['records']
    assert [row['total'] for row in audited[1:]] == [0, 1, 0, 0, 1]
    assert audited[0]['ece'] == pytest.approx(.4)


def test_review_at_exact_handoff_is_allowed():
    score = evaluate([outcome(measured=13)], as_of=13)['records'][0]
    assert score['verified'] == 1


def test_late_outcomes_do_not_change_review_matrix():
    score = evaluate([outcome(measured=21), outcome('F2', inspected=False)], as_of=20)['records'][0]
    assert score['verified'] == 0
    assert score['exclusions'] == {'OPEN_OR_INVALID_INSPECTION': 2}


def test_duplicate_and_conflict_are_separately_handled():
    records = [outcome(), outcome(), outcome('F2'), outcome('F2', confirmed=False)]
    score = evaluate(records, as_of=20)['records'][0]
    assert score['verified'] == 1
    assert score['exclusions'] == {'CONFLICTING_OUTCOME': 1}


def test_invalid_bins_do_not_hide_notes():
    with pytest.raises(ValueError, match='INVALID_SCORE_BANDS'):
        evaluate([outcome()], as_of=20, thresholds=[.25, .25, 1])
