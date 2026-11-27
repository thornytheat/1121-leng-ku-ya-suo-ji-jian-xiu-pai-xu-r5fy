"""故障分诊：主责/联合复核/转下一班的边界、保存恢复与样例可复现。"""

import json
from pathlib import Path

import pytest

from chillwatch.fault_triage import (
    TriageLedger,
    TriageSaveError,
    evaluate,
)
from chillwatch.fault_triage.ledger import FlakySink

SAMPLE = Path(__file__).resolve().parents[1] / 'sample_data' / 'fault_triage_cases.json'


def case(unit='T1', **changes):
    base = dict(unit=unit, pressure_z=4.0, pressure_points=3, pressure_duration=30,
                vibration_z=1.0, vibration_points=1)
    return base | changes


def verdicts(rows, **options):
    return {row['unit']: row for row in evaluate(rows, **options)['records']}


# --- 三类去向的基本裁定 -------------------------------------------------------

def test_durable_pressure_clue_owns_pressure_trade():
    row = evaluate([case(pressure_history=True)])['records'][0]
    assert row['decision'] == 'PRIMARY'
    assert row['decision'] == '主责'          # 双语别名同样成立
    assert row['owner'] == 'pressure'
    assert '压力' in row['trade']
    assert row['pending'] is False


def test_durable_vibration_clue_owns_vibration_trade():
    row = evaluate([case(
        pressure_z=0.6, pressure_points=1,
        vibration_z=9.0, vibration_points=3, vibration_duration=30,
        vibration_history=True)])['records'][0]
    assert row['decision'] == 'PRIMARY'
    assert row['owner'] == 'vibration'


def test_max_deviation_single_spike_cannot_become_owner():
    # 振动偏离最大但只有一次尖峰；压力持续且有历史 -> 仍由压力主责
    rows = [case(unit='S', pressure_z=4.1, pressure_history=True,
                 vibration_z=16.8, vibration_points=1, vibration_duration=0)]
    row = verdicts(rows)['S']
    assert row['max_deviation_channel'] == 'vibration'
    assert row['deviation_leader_is_spike'] is True
    assert row['owner'] != 'vibration'
    assert row['decision'] == 'PRIMARY' and row['owner'] == 'pressure'


def test_lone_spike_without_durable_side_is_review_not_primary():
    row = evaluate([case(pressure_z=0.4, pressure_points=0, pressure_duration=0,
                         vibration_z=15.0, vibration_points=1,
                         window_remaining=40)])['records'][0]
    assert row['decision'] != 'PRIMARY'
    assert row['decision'] == 'JOINT_REVIEW'
    assert row['reason'] == 'SPIKE_JOINT_REVIEW'


# --- 数据质量硬门：冲突 / 缺通道只能复核 --------------------------------------

def test_reading_conflict_forces_joint_review_even_with_window_and_owner_signal():
    row = evaluate([case(conflict=True, pressure_z=9, vibration_z=9,
                         window_remaining=999, next_shift_recheck=True)])['records'][0]
    assert row['decision'] == 'JOINT_REVIEW'
    assert row['reason'] == 'READING_CONFLICT'
    assert row['blocked_dispatch'] is True
    assert row['owner'] is None


def test_missing_channel_forces_review_even_if_pressure_is_strong():
    rows = [
        evaluate([case(missing_channels=['vibration'], pressure_z=12, pressure_points=5)])['records'][0],
        evaluate([case(missing_channels='vibration', pressure_z=12, pressure_points=5)])['records'][0],
        evaluate([case(channels={'pressure': True, 'vibration': None},
                       pressure_z=12, pressure_points=5)])['records'][0],
    ]
    for row in rows:
        assert row['decision'] == 'JOINT_REVIEW'
        assert row['reason'] == 'CHANNEL_MISSING'
        assert row['owner'] is None


def test_missing_channel_detected_from_channel_map():
    row = evaluate([case(channels={'pressure': 'ok', 'vibration': 'offline'})])['records'][0]
    assert row['decision'] == 'JOINT_REVIEW'
    assert 'vibration' in row['missing_channels']


# --- 双线索分歧 + 窗口 / 下一班条件 ------------------------------------------

def test_divergent_durable_channels_joint_review_when_window_fits():
    row = evaluate([case(pressure_z=5.4, vibration_z=6.1, vibration_points=3,
                         vibration_duration=30, window_remaining=60,
                         recheck_minutes=25)])['records'][0]
    assert row['decision'] == 'JOINT_REVIEW'
    assert row['reason'] == 'DIVERGENT_JOINT_REVIEW'
    assert row['pending_reason']


def test_divergent_and_short_window_with_next_shift_recheck_defers():
    row = evaluate([case(pressure_z=5.4, vibration_z=6.1, vibration_points=3,
                         window_remaining=10, recheck_minutes=30,
                         next_shift_recheck={'available': True, 'window_minutes': 70})])['records'][0]
    assert row['decision'] == 'NEXT_SHIFT'
    assert row['decision'] == '转下一班'
    assert row['reason'] == 'DEFER_NEXT_SHIFT'
    assert row['pending'] is True and row['pending_reason']


def test_short_window_but_no_next_shift_recheck_means_joint_now():
    row = evaluate([case(pressure_z=5.4, vibration_z=6.1, vibration_points=3,
                         window_remaining=10, recheck_minutes=30,
                         next_shift_recheck=False)])['records'][0]
    assert row['decision'] == 'JOINT_REVIEW'
    assert row['reason'] == 'NO_NEXT_RECHECK_JOINT_NOW'


def test_history_and_clear_persistence_margin_can_adjudicate_primary():
    row = evaluate([case(pressure_z=5.8, pressure_points=4, pressure_duration=40,
                         pressure_history=True, vibration_z=4.6, vibration_points=2,
                         vibration_duration=12, vibration_history=False)])['records'][0]
    assert row['decision'] == 'PRIMARY'
    assert row['owner'] == 'pressure'
    assert row['adjudicated_by'] == 'duration+history'


def test_unconfirmed_alarm_is_only_monitor():
    row = evaluate([case(confirmed=False)])['records'][0]
    assert row['decision'] == 'MONITOR'
    assert row['pending'] is False


def test_bad_rows_are_isolated_not_raised():
    result = evaluate([
        {'unit': 'OK', 'pressure_z': 3, 'pressure_points': 2},
        {'minute': 1},  # 缺 unit
    ])
    assert result['accepted_count'] == 1
    assert result['rejected_count'] == 1
    assert result['errors'][0]['field'].endswith('unit')


# --- 样例文件：一组可复现全部差别的机组 ---------------------------------------

def test_sample_file_every_case_matches_expected_destination():
    payload = json.loads(SAMPLE.read_text(encoding='utf-8'))
    result = verdicts(payload['cases'])
    assert len(result) >= 8
    for raw in payload['cases']:
        row = result[raw['unit']]
        for key, expected in raw['expect'].items():
            if key == 'decision':
                assert row['decision'] == expected, raw['unit']
            elif key == 'reason':
                assert row['reason'] == expected, raw['unit']
            else:
                assert row[key] == expected, (raw['unit'], key)


def test_sample_covers_all_three_handoff_destinations():
    payload = json.loads(SAMPLE.read_text(encoding='utf-8'))
    result = evaluate(payload['cases'])['records']
    decisions = {str(row['decision']) for row in result}
    assert {'PRIMARY', 'JOINT_REVIEW', 'NEXT_SHIFT'} <= decisions
    # 冲突与缺通道样例必须存在且只能是联合复核
    by_unit = {row['unit']: row for row in result}
    assert str(by_unit['TR-04']['reason']) == 'READING_CONFLICT'
    assert str(by_unit['TR-05']['reason']) == 'CHANNEL_MISSING'
    assert by_unit['TR-03']['owner'] == 'pressure'


# --- 台账：保存失败恢复 + 幂等不重复 ------------------------------------------

def test_save_failure_keeps_confirmed_checkpoint_and_recover_finishes():
    ledger = TriageLedger(FlakySink(fail_on={1}))  # 第 2 张单失败
    rows = [case(unit='A'), case(unit='B', conflict=True), case(unit='C')]
    with pytest.raises(TriageSaveError) as info:
        ledger.save(rows)
    assert [t['unit'] for t in ledger.confirmed_tickets()] == ['A']
    assert info.value.failed_ticket['unit'] == 'B'
    report = ledger.recover()
    assert report['confirmed'] == 3 and report['failed'] == 0
    assert ledger.checkpoint.endswith('C')


def test_rerun_never_duplicates_triage_orders():
    ledger = TriageLedger()
    rows = [case(unit='A'), case(unit='B'), case(unit='C')]
    ledger.save(rows)
    first_ids = [t['id'] for t in ledger.tickets]
    ledger.rerun(rows)
    ledger.recover(rows)
    assert [t['id'] for t in ledger.tickets] == first_ids
    assert ledger.count == 3 and not ledger.has_duplicates()


def test_failed_then_rerun_is_also_idempotent():
    sink = FlakySink(fail_times=2)
    ledger = TriageLedger(sink)
    rows = [case(unit='A'), case(unit='B'), case(unit='C')]
    for _ in range(2):
        with pytest.raises(TriageSaveError):
            ledger.rerun(rows)
    report = ledger.recover()
    assert report['confirmed'] == 3 and not ledger.duplicate
    assert len(sink.inner.saved) == 3


def test_file_ledger_restores_confirmed_orders_after_restart(tmp_path):
    path = tmp_path / 'desk' / 'ledger.json'
    rows = [case(unit='A'), case(unit='B', conflict=True)]
    TriageLedger(path=path).save(rows)
    reopened = TriageLedger(path=path)
    assert reopened.confirmed_count == 2
    reopened.rerun(rows)
    assert reopened.count == 2 and not reopened.has_duplicates()


def test_same_unit_same_shift_has_stable_idempotency_key():
    first = TriageLedger(shift='S1')
    second = TriageLedger(shift='S1')
    first.plan([case(unit='F-01')])
    second.plan([case(unit='F-01', pressure_z=9.9)])
    assert first.tickets[0]['idempotency_key'] == second.tickets[0]['idempotency_key']


# --- Web 交付 ---------------------------------------------------------------

@pytest.fixture()
def client():
    from chillwatch.delivery import application, get_triage_ledger
    get_triage_ledger(reset=True)
    return application.test_client()


def test_triage_page_lists_destinations_and_pending_reasons(client):
    html = client.get('/').get_data(as_text=True)
    assert '故障分诊交班' in html and '未决原因' in html and '去向' in html
    assert 'TR-07' in html and '转下一班' in html


def test_triage_stage_endpoint_returns_records(client):
    response = client.get('/api/stages/fault_triage')
    assert response.status_code == 200
    body = response.get_json()
    assert len(body['records']) >= 8 and body['columns']['verdict'] == '去向'


def test_triage_api_save_fail_recover_and_rerun(client):
    assert client.get('/api/triage').status_code == 200
    failed = client.post('/api/triage/save', json={'reset': True, 'fail_at': [2]})
    assert failed.status_code == 409
    payload = failed.get_json()
    assert payload['code'] == 'TRIAGE_SAVE_FAILED'
    assert payload['ledger']['confirmed'] == 2
    recovered = client.post('/api/triage/recover', json={}).get_json()
    assert recovered['ledger']['confirmed'] == recovered['ledger']['total']
    rerun = client.post('/api/triage/rerun', json={}).get_json()
    assert rerun['ledger']['duplicate'] is False
    assert rerun['same_count'] is True


def test_overview_carries_triage_and_row_destinations(client):
    overview = client.get('/api/overview').get_json()
    assert len(overview['stages']) == 6  # 分诊不占用六个只读环节序号
    assert len(overview['metrics']) <= 6
    assert overview['triage']['records']
    for row in overview['rows']:
        assert 'destination' in row and 'pending_reason' in row
