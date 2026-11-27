from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from statistics import mean

from . import duty_reference, maintenance_slots, persistence_filter, robust_alarm, shift_meter, shift_review


DEFAULT_CAPACITY = 4
BASELINE_END = 500
HANDOFF = 590


def read_fixture():
    path = Path(__file__).resolve().parents[2] / 'sample_data' / 'north_facility_evening.json'
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


def outcomes_table(work_rows, persistence):
    history = {row['unit']: row for row in persistence}
    result = []
    for work in work_rows:
        check = history.get(work['unit'], {})
        result.append({
            'unit': work['unit'],
            'rack': work['rack'],
            'risk': round(work['priority'], 1),
            'records': check.get('persisted', 0),
            'crew': work['crew'],
            'slot': f"{work['start']}–{work['end']}" if work['start'] is not None else '—',
            'status': work['state'],
            'reason': work['reason'],
        })
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
    actions = Counter(row['state'] for row in queue['records'])
    faults = review['records'][0]
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
        },
        'columns': {'unit': '机组', 'rack': '冷区', 'risk': '峰值评分', 'records': '连续次数',
                    'crew': '班组', 'slot': '停机分钟', 'status': '状态', 'reason': '处置依据'},
        'rows': outcomes_table(queue['records'], consecutive['records']),
        'series': list(alarm_curve(alarm['records'])),
        'stages': [{'title': title, 'summary': summary, 'records': result['records'], 'errors': result['errors']}
                   for title, summary, result in stages],
    }
