import json
from itertools import permutations

import pytest

from chillwatch.maintenance_slots import simulate_staffing
from chillwatch.maintenance_slots.coverage_plan import candidate_orders, eligible_requests, ranking, replay_order
from chillwatch.pipeline import run


def request(unit, **changes):
    return {'unit':unit,'rack':'R1','decision':'CONFIRMED','driver':'VIBRATION','runtime':25,
            'priority':30,'has_backup':True,'allowed_start':600,'allowed_end':650} | changes


@pytest.mark.parametrize('crew_levels', [(1,), (2,1), (3,3,2,1)])
def test_every_option_has_independent_proof_against_capacity(crew_levels):
    records = [request('F1',priority=91),request('F2',rack='R2'),request('F3',rack='R3')]
    computed = simulate_staffing(records,capacity=2,crew_levels=crew_levels)
    assert [item['crews'] for item in computed] == sorted(set(crew_levels))
    for result in computed:
        assert result['audit']['verified']
        assert len(result['schedule']) == result['audit']['scheduled'] == 2
        assert result['audit']['total_crew_minutes'] == 50
        assert result['bottlenecks'] == {'SHIFT_CAPACITY':1}
        assert result['coverage_points'] == 121
        assert result['additional_coverage'] == 0


def test_case_with_expiring_window_beats_first_by_severity():
    broad = request('F1',priority=69,allowed_end=650)
    expires = request('F2',priority=65,allowed_end=625)
    source,skipped = eligible_requests([broad,expires],600,735)
    naive,_ = replay_order(source,2,1,600,735)
    result = simulate_staffing([broad,expires],capacity=2,crew_levels=[1])[0]
    assert len(naive) == 1
    assert result['coverage_points'] == 134
    assert result['coverage_points'] > ranking(naive)[0]
    assert [(row['unit'],row['start'],row['end']) for row in result['schedule']] == [('F2',600,625),('F1',625,650)]
    assert skipped == {}


def test_staffing_expansion_relaxes_crews_but_not_rack_protection():
    cases = [request('F1',allowed_end=625),request('F2',allowed_end=625),
             request('F3',rack='R2',allowed_end=625)]
    results = simulate_staffing(cases,capacity=3,crew_levels=[1,2,3])
    assert [len(point['schedule']) for point in results] == [1,2,2]
    assert [point['additional_coverage'] for point in results] == [0,30,0]
    assert results[2]['bottlenecks'] == {'WINDOW_OR_REDUNDANCY':1}
    assert all(point['audit']['verified'] for point in results)


def test_structural_rejection_reasons_are_independent_of_slot_budget():
    cases = [request('NO-PROOF',decision='MONITOR'),request('OFF-CHART',decision='MONITOR',driver='DOMAIN_REVIEW'),
             request('NO-BACKUP',has_backup=False),request('SHORT',allowed_end=624),request('F1')]
    row = simulate_staffing(cases,capacity=1,crew_levels=(1,))[0]
    assert row['audit']['scheduled'] == 1
    assert row['bottlenecks'] == {'PERSISTENCE_NOT_CONFIRMED':1,'MANUAL_GAUGE_CHECK':1,
                                   'NO_REDUNDANT_COMPRESSOR':1,'OUTSIDE_SHIFT_WINDOW':1}
    assert sum(row['bottlenecks'].values()) + row['audit']['scheduled'] == len(cases)


def test_options_are_independent_of_packet_delivery_order():
    records = [request('F1',priority=56),request('F2',priority=60,allowed_end=625),
               request('F3',rack='R2',priority=40),request('F4',rack='R3',priority=44)]
    first = simulate_staffing(records)
    for ordering in permutations(records):
        assert simulate_staffing(ordering) == first


def test_workproof_does_not_increase_priority_when_runtime_is_longer():
    rows = [request('F1',runtime=25,priority=86),request('F2',runtime=20,priority=86)]
    baseline = simulate_staffing(rows,capacity=1,crew_levels=(1,))[0]
    assert baseline['schedule'][0]['unit'] == 'F2'
    assert baseline['audit']['total_crew_minutes'] == 20
    rows[1]['runtime'] = 29
    revised = simulate_staffing(rows,capacity=1,crew_levels=(1,))[0]
    assert revised['schedule'][0]['unit'] == 'F1'
    assert revised['coverage_points'] == baseline['coverage_points']
    assert revised['schedule'][0]['end'] == 625


def test_candidate_enumeration_never_uses_more_than_order_budget():
    raw = [request(f'F{i}',priority=i,allowed_end=625+3*i) for i in range(10)]
    eligible,_ = eligible_requests(raw,600,735)
    choices = list(candidate_orders(eligible,15))
    signatures = [tuple(item.unit for item in choice) for choice in choices]
    assert len(choices) == len(set(signatures)) == 15
    assert all(len(choice) == len(eligible) for choice in choices)
    proof = simulate_staffing(raw,order_budget=15)[0]
    assert proof['explored_orders'] == 15


@pytest.mark.parametrize('override,error', [({'capacity':0},'INVALID_STAFFING_OPTION'),
        ({'crew_levels':()},'INVALID_STAFFING_OPTION'),({'crew_levels':(0,2)},'INVALID_CREW_SCENARIO'),
        ({'start':735,'end':735},'INVALID_STAFFING_OPTION'),({'order_budget':160},'INVALID_STAFFING_OPTION')])
def test_invalid_staffing_is_distinct_from_no_eligible_requests(override,error):
    with pytest.raises(ValueError,match=error):
        simulate_staffing([],**override)


def test_zero_eligible_requests_produce_an_auditable_empty_plan():
    result = simulate_staffing([])
    assert len(result) == 3
    for point in result:
        assert point['explored_orders'] == 1
        assert point['coverage_points'] == point['additional_coverage'] == 0
        assert point['schedule'] == []
        assert point['audit'] == {'scheduled':0,'total_crew_minutes':0,'crew_minutes':{},'defects':[],'verified':True}


def test_conflicting_or_aliased_equipment_must_not_reserve_two_slots():
    duplicate = request('F1')
    row = simulate_staffing([duplicate,duplicate],crew_levels=(2,))[0]
    assert len(row['schedule']) == 1
    with pytest.raises(ValueError,match='AMBIGUOUS_CAPACITY_INPUT:F1'):
        simulate_staffing([duplicate,duplicate|{'rack':'R2'}])


@pytest.mark.parametrize('capacity', [1,2,3,4,100])
def test_frozen_fixture_exhibits_cross_module_proof(capacity):
    work = run(capacity)
    assert work == run(capacity)
    assert json.loads(json.dumps(work,allow_nan=False)) == work
    assert work['metrics']['本班停机'] <= capacity
    recon = work['reconciliation']
    assert recon['work_order_proof']['verified']
    assert recon['work_order_proof']['scheduled'] == work['metrics']['本班停机']
    assert all(point['audit']['verified'] and point['audit']['scheduled']<=capacity
               for point in recon['alternate_staffing'])
    assert all(item['observed_slots'] + sum((g['end']-g['start']+9)//10 for g in item['missing_intervals']) == item['expected_slots']
               for item in recon['sampling'])
    assert len(work['stages']) == 6
    assert len(recon['threshold_replay']) == 5
