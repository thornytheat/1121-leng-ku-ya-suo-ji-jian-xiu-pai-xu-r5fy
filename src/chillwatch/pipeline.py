from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from statistics import mean

from . import duty_reference, fault_triage, maintenance_slots, persistence_filter, robust_alarm, shift_meter, shift_review


DEFAULT_CAPACITY = 4
BASELINE_END = 500
HANDOFF = 590


def read_fixture():
    path = Path(__file__).resolve().parents[2] / 'sample_data' / 'north_facility_evening.json'
    with path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    # 故障分诊样例以独立文件维护；同时挂到主样例的常见键名下，便于整体读取。
    if 'triage' not in data:
        try:
            triage_sample = read_triage_sample()
            data['triage'] = triage_sample['cases']
            data['triage_cases'] = triage_sample['cases']
            data['fault_triage_cases'] = triage_sample['cases']
            data['triage_sample'] = triage_sample
        except (FileNotFoundError, KeyError):
            pass
    return data


def read_triage_sample():
    path = Path(__file__).resolve().parents[2] / 'sample_data' / 'fault_triage_cases.json'
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def duty_period(minute):
    if minute < 565:
        return '接班巡查'
    return '夜班实测'


def derive_requests(work_list, signals, persistence):
    status = {row['unit']: row for row in persistence}
    unit_scores = {}
    for point in signals:
        confidence = point['score']
        if confidence is not None:
            unit_scores[point['unit']] = max(unit_scores.get(point['unit'], 0), confidence)
    requests = []
    for work in work_list:
        unit = work['unit']
        alarm = status.get(unit)
        requests.append(work | {
            'decision': alarm['decision'] if alarm else 'MONITOR',
            'driver': alarm['driver'] if alarm else 'NO_METER_EVIDENCE',
            'priority': unit_scores.get(unit, 0) * 100,
        })
    return requests


def outcomes_table(work_rows, persistence, triage_by_unit=None):
    history = {row['unit']: row for row in persistence}
    triage_by_unit = triage_by_unit or {}
    result = []
    for work in work_rows:
        check = history.get(work['unit'], {})
        verdict = triage_by_unit.get(work['unit'], {})
        result.append({
            'unit': work['unit'],
            'rack': work['rack'],
            'risk': round(work['priority'], 1),
            'records': check.get('persisted', 0),
            'crew': work['crew'],
            'slot': f"{work['start']}–{work['end']}" if work['start'] is not None else '—',
            'status': work['state'],
            'reason': work['reason'],
            'destination': verdict.get('destination_label', '—'),
            'destination_code': str(verdict.get('decision', '')) or None,
            'trade': verdict.get('trade'),
            'pending_reason': verdict.get('pending_reason') if verdict.get('pending') else '—',
        })
    return result


def derive_unit_triage(alarm_records, persistence_records, meter_records):
    """把主样例 F-01..F-12 的通道证据整理成分诊去向。"""
    by_unit: dict[str, list] = {}
    for point in alarm_records:
        by_unit.setdefault(point['unit'], []).append(point)
    conflict_units = {
        row['unit'] for row in (meter_records or [])
        if isinstance(row, dict) and 'CONFLICT' in str(row.get('reason', ''))
    }
    inputs = []
    for unit, points in sorted(by_unit.items()):
        scored = [p for p in points if p.get('pressure_z') is not None]
        p_active = [p for p in scored if abs(p['pressure_z']) >= 2.0]
        v_active = [p for p in scored if max(p.get('vibration_z', 0) or 0, 0) >= 2.0]

        def span(rows):
            minutes = [r['minute'] for r in rows]
            return max(minutes) - min(minutes) if len(minutes) >= 2 else 0

        item = {
            'unit': unit,
            'pressure_z': max((abs(p['pressure_z']) for p in scored), default=None),
            'pressure_points': len(p_active),
            'pressure_duration': span(p_active),
            'vibration_z': max((p.get('vibration_z') for p in scored), default=None),
            'vibration_points': len(v_active),
            'vibration_duration': span(v_active),
        }
        if unit in conflict_units:
            item['conflict'] = True
        persist = next((r for r in persistence_records if r['unit'] == unit), None)
        if persist is not None:
            item['decision'] = persist['decision']
        inputs.append(item)
    verdict = fault_triage.evaluate(inputs)['records']
    return {row['unit']: row for row in verdict}


def _channel_brief(channel):
    if not channel.get('present'):
        return '通道无数据'
    deviation = channel.get('deviation')
    dev = f"{deviation:.1f}" if isinstance(deviation, (int, float)) else '—'
    shape = '单次尖峰' if channel['spike'] else ('持续成线' if channel['durable'] else '持续性不足')
    return f"偏离 {dev} · {channel.get('points') or 0} 点 · {shape}"


TRIAGE_COLUMNS = {
    'unit': '机组',
    'verdict': '去向',
    'trade': '责任工种',
    'pressure_brief': '压力线索',
    'vibration_brief': '振动线索',
    'basis_brief': '持续/历史',
    'pending_reason': '裁定依据与未决原因',
}


def triage_stage_evidence():
    sample = read_triage_sample()
    policy = sample.get('policy', {})
    result = fault_triage.evaluate(
        sample['cases'],
        min_points=int(policy.get('min_points', 2)),
        min_minutes=float(policy.get('min_minutes', 10)),
    )
    for row in result['records']:
        row['pressure_brief'] = _channel_brief(row['pressure'])
        row['vibration_brief'] = _channel_brief(row['vibration'])
        hist = []
        if row['pressure']['history_support']:
            hist.append('压力历史同因')
        if row['vibration']['history_support']:
            hist.append('振动历史轴承')
        row['basis_brief'] = '；'.join(hist) or '按当前持续性'
    result['columns'] = TRIAGE_COLUMNS
    result['shift'] = sample.get('shift')
    result['sample_file'] = 'sample_data/fault_triage_cases.json'
    return result



def alarm_curve(signals):
    for unit in sorted({point['unit'] for point in signals}):
        unit_scores = [point['score'] for point in signals if point['unit'] == unit and point['score'] is not None]
        yield {'label': unit, 'value': round(100 * mean(unit_scores), 1) if unit_scores else 0}


def run(capacity: int | None = None) -> dict:
    inputs = read_fixture()
    meters = shift_meter.evaluate(inputs['meter'], cutoff=HANDOFF)
    reference = duty_reference.evaluate(inputs['history'], cutoff=BASELINE_END)
    candidates = [row for row in meters['records'] if row['status'] == 'accepted']
    alarm = robust_alarm.evaluate(candidates, references=reference['records'])
    consecutive = persistence_filter.evaluate([
        dict(point, duty=duty_period(point['minute'])) for point in alarm['records']
    ])
    request_rows = derive_requests(inputs['work'], alarm['records'], consecutive['records'])
    queue = maintenance_slots.evaluate(request_rows, capacity=capacity if capacity is not None else DEFAULT_CAPACITY)
    review = shift_review.evaluate(inputs['closed'], as_of=HANDOFF)
    unit_triage = derive_unit_triage(alarm['records'], consecutive['records'], meters['records'])
    triage_evidence = triage_stage_evidence()
    actions = Counter(row['state'] for row in queue['records'])
    faults = review['records'][0]
    triage_destinations = Counter(str(row['decision']) for row in triage_evidence['records'])
    stages = [
        ('交接读数', f"交接前去重后保留 {len(candidates)} 笔；字段隔离 {meters['rejected_count']} 笔", meters),
        ('历史工况', f'训练只读取第 {BASELINE_END} 分钟前的非化霜工况', reference),
        ('稳健异常', '按排气压力和轴承振动分解偏离，超训练域留待查表', alarm),
        ('持续告警', '同一巡查窗口连续异常才能生成检修候选', consecutive),
        ('停机排程', f"本班落实 {actions['已排检']} 张工单", queue),
        ('班次复盘', f"对账 {faults['verified']} 个已验修结果", review),
    ]
    return {
        'reconciliation': {
            'sampling': shift_meter.audit_sampling(meters['records']),
            'reference_drift': duty_reference.compare_references(duty_reference.evaluate(inputs['history'], cutoff=BASELINE_END-90)['records'], reference['records']),
            'threshold_replay': robust_alarm.compare_operating_points(alarm['records']),
            'alarm_episodes': persistence_filter.extract_episodes([dict(point,duty=duty_period(point['minute'])) for point in alarm['records']]),
            'work_order_proof': maintenance_slots.reconcile_schedule(queue['records']),
            'alternate_staffing': maintenance_slots.simulate_staffing(request_rows, capacity=capacity if capacity is not None else DEFAULT_CAPACITY),
            'inspection_counterfactual': shift_review.inspection_counterfactual(inputs['closed'], as_of=HANDOFF),
        },
        'metrics': {
            '在册机组': len(queue['records']),
            '确认告警': sum(row['decision'] == 'CONFIRMED' for row in consecutive['records']),
            '本班停机': actions['已排检'],
            '候补工单': actions['候补'],
            '交班分诊': f"主责 {triage_destinations.get('PRIMARY', 0)} / 复核 {triage_destinations.get('JOINT_REVIEW', 0)} / 转班 {triage_destinations.get('NEXT_SHIFT', 0)}",
        },
        'columns': {'unit': '机组', 'destination': '去向', 'rack': '冷区', 'risk': '峰值评分',
                    'records': '连续次数', 'crew': '班组', 'slot': '停机分钟', 'status': '状态',
                    'reason': '处置依据', 'pending_reason': '未决原因'},
        'rows': outcomes_table(queue['records'], consecutive['records'], unit_triage),
        'series': list(alarm_curve(alarm['records'])),
        'triage': {
            'shift': triage_evidence.get('shift'),
            'sample_file': triage_evidence.get('sample_file'),
            'columns': TRIAGE_COLUMNS,
            'records': triage_evidence['records'],
            'unit_destinations': list(unit_triage.values()),
        },
        'stages': [{
            'title': title,
            'summary': summary,
            'records': result['records'],
            'errors': result['errors'],
            **({'columns': result['columns']} if result.get('columns') else {}),
        } for title, summary, result in stages],
    }
