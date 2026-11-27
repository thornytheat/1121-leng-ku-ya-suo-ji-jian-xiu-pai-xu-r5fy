import pytest
from chillwatch.duty_reference import compare_references
from chillwatch.duty_reference.reference_comparison import compare_metric


def point(center=8,radius=1,scale=1):
    return {'center':center,'scale':scale,'minimum':center-radius,'maximum':center+radius}


def fit(unit='F1',basis='INDIVIDUAL_BASELINE',center=8):
    return {'unit':unit,'family':'A','basis':basis,'pressure':point(center),
            'vibration':point(2),'fit_id':f'{unit}-{center}'}


def test_unaffected_channels_report_individual_overlap():
    row=compare_references([fit()],[fit(center=14)])[0]
    assert row['status']=='REFERENCE_DRIFT'
    assert row['channels']['pressure']['range_overlap']==0
    assert row['channels']['vibration']['range_overlap']==1
    assert row['comparison_mass']==pytest.approx(6/(2**.5))


def test_equal_constant_channels_have_unit_overlap():
    case=compare_metric(point(radius=0),point(radius=0),.25)
    assert case['range_overlap']==1
    assert case['sigma_gap']==0


def test_drift_requires_both_small_overlap_and_large_center_shift():
    prior=fit()
    current=fit(center=14)
    current['pressure']=point(14,radius=20)
    row=compare_references([prior],[current],overlap_cutoff=.01)[0]
    assert row['status']=='REFERENCE_STABLE'
    assert row['channels']['pressure']['sigma_gap']>4


def test_family_fallback_cannot_compare_different_cohort():
    one=compare_references([fit()],[fit(basis='FAMILY_BASELINE')])[0]
    assert one['status']=='REFERENCE_COHORT_CHANGED'
    assert one['channels']=={}


def test_new_and_disconnected_equipment_get_independent_flags():
    rows=compare_references([fit('F1')],[fit('F2')])
    assert [(row['previous_id'],row['current_id']) for row in rows]==[('F1-8',None),(None,'F2-8')]
