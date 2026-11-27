import pytest
from chillwatch.robust_alarm import compare_operating_points


def alarm(unit,minute,score,prior=None):
    return {'unit':unit,'minute':minute,'score':score,'eligible':score is not None,
            'alarm':(score is not None and score>=.8) if prior is None else prior}


def test_threshold_replay_preserves_monotonic_candidate_count():
    evidence=[alarm('F1',5,.7),alarm('F1',8,.83),alarm('F2',9,.93),alarm('F3',4,None)]
    output=compare_operating_points(evidence)
    assert [row['new_alarms'] for row in output]==[3,2,2,1,0]
    assert [row['changed_votes'] for row in output]==[1,0,0,1,2]
    assert all(row['unscorable_units']==1 for row in output)


def test_exact_threshold_is_an_affirmative_vote():
    case=compare_operating_points([alarm('F1',5,.8)],[.8])[0]
    assert case['new_alarms']==1
    assert case['equipment'][0]['peak_margin']==0


def test_unscorable_shift_does_not_claim_expected_margin():
    outcome=compare_operating_points([alarm('F4',9,None)],[.7])[0]
    assert outcome['average_peak_margin'] is None
    assert outcome['equipment']==[{'unit':'F4','trigger_count':0,'peak_margin':None,'can_score':False,'legacy_mismatch':0}]


def test_replay_requires_each_measurement_once():
    with pytest.raises(ValueError,match='AMBIGUOUS_THRESHOLD_EVIDENCE'):
        compare_operating_points([alarm('F1',4,.8),alarm('F1',4,.9)])


def test_replay_rejects_duplicate_thresholds():
    with pytest.raises(ValueError,match='INVALID_REPLAY_THRESHOLDS'):
        compare_operating_points([], [.7,.7])
