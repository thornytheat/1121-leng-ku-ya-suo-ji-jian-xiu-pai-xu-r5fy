import pytest
from chillwatch.shift_meter import audit_sampling
from chillwatch.shift_meter.sampling_integrity import missed_boundaries


def evidence(unit, minute, status='accepted', reason='NORMALIZED'):
    return {'unit':unit,'minute':minute,'status':status,'reason':reason}


def test_missing_slots_collapse_and_do_not_erase_outside_shifts():
    windows,gaps,external=missed_boundaries([4,5,31,40],period=10,begin=0,end=36)
    assert dict(windows)=={0:[4,5],30:[31]}
    assert gaps==[{'start':10,'end':30}]
    assert external==[40]


def test_last_partial_expected_slot_does_not_repeat_across_handoff():
    row=audit_sampling([evidence('F1',5)],period=10,begin=0,end=15)[0]
    assert row['missing_intervals']==[{'start':10,'end':15}]
    assert row['expected_slots']==2
    assert row['observed_ratio']==.5


def test_rejected_packets_count_without_adding_an_observed_slot():
    rejected=evidence('F2',5,status='excluded',reason='AFTER_HANDOFF')
    row=audit_sampling([rejected],period=10,begin=0,end=25)[0]
    assert row['expected_slots']==3
    assert row['observed_slots']==0
    assert row['rejected_reasons']=={'AFTER_HANDOFF':1}
    assert row['missing_intervals']==[{'start':0,'end':25}]


def test_packets_sharing_a_slot_audited_without_double_credit():
    row=audit_sampling([evidence('F1',5),evidence('F1',7)],begin=0,end=20)[0]
    assert row['double_capture']==[0]
    assert row['observed_ratio']==.5


def test_bad_cadence_cannot_divide_by_zero():
    with pytest.raises(ValueError,match='INVALID_SCAN_CADENCE'):
        audit_sampling([],period=0)
