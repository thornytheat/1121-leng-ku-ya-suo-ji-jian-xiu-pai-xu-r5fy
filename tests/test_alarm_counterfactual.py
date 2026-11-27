import pytest
from chillwatch.shift_review import inspection_counterfactual
from chillwatch.shift_review.alarm_counterfactual import wilson


def outcome(unit,score,fault,**updates):
    return {'unit':unit,'minute':12,'measured':20,'score':score,'confirmed':fault,
            'alarm':score>=.8,'inspected':True}|updates


def test_expected_cost_weights_a_fault_more_than_an_unnecessary_visit():
    case=[outcome('F1',.9,True),outcome('F2',.52,True),outcome('F3',.65,False)]
    view=inspection_counterfactual(case,as_of=30)
    assert view['historical_preferred_threshold']==.35
    row=next(row for row in view['proposals'] if row['threshold']==.65)
    assert row['estimated_cost']==245
    assert row['checked']==2 and row['undetected_faults']==1


def test_wilson_interval_fits_the_probability_domain():
    assert wilson(0,0) is None
    lo,hi=wilson(10,10)
    assert .72<lo<.73 and hi == pytest.approx(1)
    lo,hi=wilson(0,10)
    assert lo==pytest.approx(0) and .27<hi<.28


def test_cutoffs_without_inspected_faults_still_count_visits():
    view=inspection_counterfactual([outcome('F1',.9,False)],as_of=30)
    assert view['closed_faults']==0
    assert view['proposals'][0]['recall_interval'] is None
    assert view['proposals'][0]['avoidable_checks']==1


def test_missing_review_has_no_estimated_cost_or_recommended_threshold():
    view=inspection_counterfactual([outcome('F1',.9,True,inspected=False)],as_of=30)
    assert view['excluded']=={'OPEN_OR_INVALID_INSPECTION':1}
    assert view['historical_preferred_threshold'] is None
    assert all(row['estimated_cost'] is None for row in view['proposals'])


def test_late_results_do_not_enter_threshold_sweep():
    two=outcome('F2',.9,True,measured=31)
    view=inspection_counterfactual([outcome('F1',.6,True),two],as_of=30)
    assert view['closed_samples']==1
    assert view['closed_faults']==1
