import pytest
from chillwatch.persistence_filter import extract_episodes


def point(minute, **updates):
    return {'unit':'F1','minute':minute,'alarm':True,'eligible':True,
            'duty':'first','reason':'BEARING'}|updates


def test_recovery_closes_previous_incident_without_losing_duration():
    sample=[point(4),point(7,reason='PRESSURE'),point(12,alarm=False),point(19)]
    closed,active=extract_episodes(sample)
    assert closed['end_reason']=='RETURNED_TO_BASELINE'
    assert closed['elapsed']==3
    assert closed['reason_counts']=={'BEARING':1,'PRESSURE':1}
    assert closed['confirmed'] and not active['confirmed']


def test_duty_change_takes_priority_over_telemetry_gap():
    first,second=extract_episodes([point(4),point(18,duty='second')])
    assert first['end_reason']=='DUTY_CHANGED'
    assert second['end_reason']=='ACTIVE_AT_HANDOFF'


def test_missing_interval_is_not_credited_as_alarm_duration():
    first,second=extract_episodes([point(3),point(13),point(26)],max_gap=12)
    assert first['end_reason']=='MEASUREMENT_GAP'
    assert first['elapsed']==10
    assert second['elapsed']==0


def test_masked_defrost_is_preserved_as_cause_for_episode_end():
    item=extract_episodes([point(3),point(6,eligible=False,reason='DEFROST')])[0]
    assert item['end_reason']=='DEFROST'
    assert item['samples']==1


def test_all_healthy_means_no_open_incident():
    assert extract_episodes([point(4,alarm=False)])==[]
