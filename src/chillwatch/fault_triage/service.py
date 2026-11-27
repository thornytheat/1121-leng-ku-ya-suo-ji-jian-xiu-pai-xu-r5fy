from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
import re
from typing import Any

from .algorithm import calculate
from .contracts import InvalidRow, TriageCase, parse


@dataclass(frozen=True, slots=True)
class TriageRejection:
    line: int
    field: str
    code: str


def _looks_like_unit_key(key: str) -> bool:
    # F-01 / TR-07 / U2 这类机组键通常含数字或为全大写短码，
    # 以区别于 available / window_minutes 等条件字段。
    return bool(re.search(r'\d', key)) or (key.isupper() and len(key) <= 10)


def _index_by_unit(value: Any) -> dict:
    """把列表/字典形式的历史或下班条件按机组归并；无法识别时返回空。"""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        if value.get('unit'):
            return {value['unit']: value}
        if value and all(isinstance(k, str) and _looks_like_unit_key(k) for k in value):
            return dict(value)
        return {}
    if isinstance(value, list):
        grouped: dict[str, list] = {}
        for item in value:
            if isinstance(item, Mapping) and item.get('unit'):
                grouped.setdefault(item['unit'], []).append(item)
        return grouped
    return {}


def _merge_context(rows, options):
    history = options.pop('history', None)
    historical = options.pop('historical', None)
    references = options.pop('references', None)
    next_shift = options.pop('next_shift', None)
    next_shift_conditions = options.pop('next_shift_conditions', None)
    next_recheck = options.pop('next_shift_recheck', None)
    windows = options.pop('windows', None)
    context = options.pop('context', None)
    if isinstance(context, Mapping):
        history = history if history is not None else context.get('history')
        next_shift = next_shift if next_shift is not None else context.get('next_shift')

    history_value = history if history is not None else historical if historical is not None else references
    history_map = _index_by_unit(history_value)
    global_history = None if history_map or history_value is None or isinstance(history_value, list) \
        else history_value
    next_value = next_shift if next_shift is not None else next_shift_conditions \
        if next_shift_conditions is not None else next_recheck
    next_map = _index_by_unit(next_value)
    global_next = None if next_map or next_value is None or isinstance(next_value, (list, bool)) \
        else next_value
    if isinstance(next_value, bool):
        global_next = next_value
    window_map = _index_by_unit(windows)

    merged = []
    for raw in rows or []:
        if not isinstance(raw, Mapping) or isinstance(raw, TriageCase):
            merged.append(raw)
            continue
        item = dict(raw)
        unit = item.get('unit')
        if 'history' not in item:
            if unit in history_map:
                item['history'] = history_map[unit]
            elif global_history is not None:
                item['history'] = global_history
        if 'next_shift_recheck' not in item:
            if unit in next_map:
                item['next_shift_recheck'] = next_map[unit]
            elif global_next is not None:
                item['next_shift_recheck'] = global_next
        if unit in window_map:
            win = window_map[unit]
            if isinstance(win, Mapping):
                item.setdefault('window_remaining', win.get('window_remaining', win.get('remaining')))
                item.setdefault('recheck_minutes', win.get('recheck_minutes', win.get('required')))
        merged.append(item)
    return merged


def validate(rows: Iterable[Mapping[str, Any]]) -> tuple[list[TriageCase], list[TriageRejection]]:
    accepted: list[TriageCase] = []
    rejected: list[TriageRejection] = []
    for line, raw in enumerate(rows, 1):
        try:
            if isinstance(raw, TriageCase):
                accepted.append(raw)
            else:
                accepted.append(parse(raw))
        except InvalidRow as issue:
            rejected.append(TriageRejection(line, issue.field, issue.code))
    return accepted, rejected


def evaluate(rows: Iterable[Mapping[str, Any]] | None = None, *extra, **options) -> dict:
    """把已确认告警裁定为故障分诊去向，逐行隔离字段错误。

    除把历史/下班条件直接写在每行外，也接受 ``evaluate(rows, history=...,
    next_shift=...)`` 或第二位置参数传入的上下文对象。
    """
    if extra:
        context = extra[0]
        if isinstance(context, Mapping):
            options.setdefault('context', context)
        else:
            options.setdefault('history', context)
    merged_rows = _merge_context(rows, options)
    accepted, rejected = validate(merged_rows)
    outcome = calculate(accepted, **options)
    return {
        'records': outcome,
        'accepted_count': len(accepted),
        'rejected_count': len(rejected),
        'errors': [asdict(error) for error in rejected],
    }


# 常见近义入口
adjudicate_all = evaluate
triage = evaluate
run_triage = evaluate
build_triage = evaluate
classify = evaluate
triage_alarms = evaluate
adjudicate_alarms = evaluate
build_triage_plan = evaluate
create_triage_orders = evaluate
build_shift_handoff = evaluate
handoff = evaluate
dispatch_triage = evaluate


def adjudicate(source=None, **options):
    """灵活裁定：传列表返回记录列表，传单条 Mapping 返回该条裁定字典。"""
    from .algorithm import adjudicate as _adjudicate
    if isinstance(source, (list, tuple)):
        return evaluate(source, **options)['records']
    return _adjudicate(source, **options)
