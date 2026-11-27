from collections import Counter
from math import isfinite

import pytest

from chillwatch.pipeline import read_fixture, run
from chillwatch.shift_meter import evaluate as ingest
from chillwatch.shift_review import evaluate as review


@pytest.fixture(scope='module')
def station():
    return run()


def test_all_meter_failures_account_for_an_input_without_duplication(station):
    raw = read_fixture()['meter']
    report = station['stages'][0]
    accounting = len(report['records']) + len(report['errors'])
    for row in report['records']:
        if row['reason'] == 'REVISION_CONFLICT':
            accounting += row['superseded'] - 1
        else:
            accounting += row.get('superseded',0)
    assert accounting == len(raw)
    exclusions = Counter(row['reason'] for row in report['records'] if row['status']=='excluded')
    assert exclusions == {'REVISION_CONFLICT':1,'AFTER_HANDOFF':1,'CLOCK_INVERTED':1}
    assert report['errors'][0]['field'] == 'shift_meter.pressure'


def test_pipeline_reference_handoff_stays_before_all_in_score_rows(station):
    references = {row['unit']:row for row in station['stages'][1]['records']}
    for point in station['stages'][2]['records']:
        fit = references[point['unit']]
        assert fit['window_start'] < fit['window_end'] < point['minute']
        if point['score'] is not None:
            assert fit['fit_id'] == point['fit_id']
            assert point['eligible'] and isfinite(point['score'])
            assert 0 < point['score'] < 1
        else:
            assert not point['eligible']
            assert point['reason'] in {'DEFROST_HOLD','NO_REFERENCE','DOMAIN_REVIEW'}


def test_alarm_episode_matches_persistence_at_the_handoff(station):
    streaks = {row['unit']:row for row in station['stages'][3]['records']}
    by_unit = {}
    for episode in station['reconciliation']['alarm_episodes']:
        if episode['end_reason']=='ACTIVE_AT_HANDOFF':
            assert episode['unit'] not in by_unit
            by_unit[episode['unit']] = episode
    for unit, streak in streaks.items():
        episode = by_unit.get(unit)
        if episode is None:
            assert streak['persisted'] == 0
            assert streak['last_alarm'] is None
        else:
            assert streak['persisted'] == episode['samples']
            assert streak['last_alarm'] == episode['end']
            assert streak['first_alarm'] == episode['start']
            assert (streak['decision']=='CONFIRMED') == episode['confirmed']


def test_desktop_anomaly_curves_use_exactly_the_eligible_inference_points(station):
    samples = station['stages'][2]['records']
    for row in station['series']:
        scores = [point['score'] for point in samples if point['unit']==row['label'] and point['score'] is not None]
        if scores:
            assert row['value'] == pytest.approx(round(100*sum(scores)/len(scores),1))
        else:
            assert row['value']==0
    assert len({row['label'] for row in station['series']}) == station['metrics']['在册机组']


def test_actual_alert_threshold_replays_without_vote_changes(station):
    evidence = station['reconciliation']['threshold_replay']
    points = station['stages'][2]['records']
    actual = next(row for row in evidence if row['threshold']==.8)
    assert actual['new_alarms']==sum(point['alarm'] for point in points)
    assert actual['changed_votes']==0
    for unit in actual['equipment']:
        observed = [point for point in points if point['unit']==unit['unit'] and point['eligible']]
        assert unit['trigger_count']==sum(point['alarm'] for point in observed)
        assert unit['can_score']==bool(observed)


def test_inspection_counterfactual_matches_verified_audit_population(station):
    post = station['reconciliation']['inspection_counterfactual']
    shift_summary,*bands = station['stages'][-1]['records']
    assert post['closed_samples'] == shift_summary['verified'] == sum(item['total'] for item in bands)
    assert post['closed_faults'] == shift_summary['detected'] + shift_summary['missed']
    assert post['excluded'] == shift_summary['exclusions']
    for threshold in post['proposals']:
        assert threshold['checked'] >= threshold['avoidable_checks']
        assert threshold['estimated_cost'] == 25*threshold['avoidable_checks'] + 220*threshold['undetected_faults']
        lo,hi = threshold['recall_interval']
        assert 0 <= lo <= hi <= 1


@pytest.mark.parametrize('cutoff', [550,553,560,572,581,590])
def test_advancing_ingress_cutoff_never_credits_future_reporting(cutoff):
    rows = ingest(read_fixture()['meter'],cutoff=cutoff)['records']
    current = [item for item in rows if item['status']=='accepted']
    assert all(item['minute']<cutoff and item['reported']<=cutoff for item in current)
    assert len({(item['unit'],item['minute']) for item in current})==len(current)
    assert all(item['pressure_kpa'] is not None for item in current)
    assert all(item['pressure_kpa'] is None for item in rows if item['status']=='excluded')


@pytest.mark.parametrize('inspected_as_of', [390,398,405,600])
def test_closure_population_conserves_labels_when_several_shifts_are_replayed(inspected_as_of):
    raw = read_fixture()['closed']
    calculated = review(raw,as_of=inspected_as_of)['records'][0]
    eligible = [row for row in raw if row['inspected'] and row['minute']<=row['measured']<=inspected_as_of]
    assert calculated['verified']==len(eligible)
    assert calculated['detected']+calculated['false_alarm']+calculated['missed']+calculated['cleared']==len(eligible)
    assert calculated['detected']==sum(row['confirmed'] and row['alarm'] for row in eligible)
    assert calculated['missed']==sum(row['confirmed'] and not row['alarm'] for row in eligible)


def test_published_queue_covers_all_in_service_equipment(station):
    rendered = station['rows']
    queued = station['stages'][4]['records']
    assert len(rendered) == len(queued) == len(read_fixture()['work'])
    for row,source in zip(rendered,queued,strict=True):
        assert row['unit']==source['unit'] and row['status']==source['state']
        assert row['reason']==source['reason']
        if row['status']=='已排检':
            assert row['crew'] is not None
            assert row['slot']==f"{source['start']}–{source['end']}"
        else:
            assert row['crew'] is None and row['slot']=='—'


def test_reference_scales_meet_instrument_resolution(station):
    rows = station['stages'][1]['records']
    assert any(row['basis']=='FAMILY_BASELINE' for row in rows)
    for row in rows:
        if row['basis']=='FAMILY_BASELINE':
            assert row['unit_history_points']<row['history_points']
        if row['pressure'] is not None:
            assert row['pressure']['scale']>=12
            assert row['vibration']['scale']>=.08
            assert row['pressure']['minimum']<=row['pressure']['center']<=row['pressure']['maximum']
