"""故障分诊裁定逻辑。

裁定优先级（顺序不可颠倒）：

1. 读数冲突 / 通道缺失 —— 只能进入联合复核；
2. 告警尚未确认 —— 继续观察，不派工；
3. 一次尖峰不具备主责资格，主责只发给“持续且成线索”的通道；
4. 两侧都持续指向不同故障时，按本班窗口与下一班复查条件决定
   本班联合复核或转下一班。

所有阈值都可通过 ``calculate(..., min_points=..., channel_threshold=...)`` 覆盖。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    DECISION_CODES,
    DECISION_LABELS,
    JOINT_REVIEW,
    MONITOR,
    NEXT_SHIFT,
    PRIMARY,
    REASON_TEXT,
    SHORT_LABELS,
    Code,
    TriageCase,
    as_bool,
    decision_code,
    first_key,
    label_code,
    parse,
    reason_code,
)

PRESSURE = 'pressure'
VIBRATION = 'vibration'

PRESSURE_WORDS = ('pressure', 'p_', '压力', '排气', 'discharge', 'kpa', 'bar')
VIBRATION_WORDS = ('vibration', 'vib', '振动', '震动', '轴承', 'bearing')
CONFLICT_WORDS = ('conflict', 'contradict', '冲突', '矛盾', 'inconsistent')
MISSING_WORDS = ('missing', 'offline', 'absent', 'unavailable', '缺失', '缺测', '离线')


# ---------------------------------------------------------------------------
# 宽松取值：同一业务量接受多种常见命名
# ---------------------------------------------------------------------------

def _number(row: Mapping, *keys: str) -> float | None:
    found, value = first_key(row, *keys)
    if found and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _bool(row: Mapping, *keys: str) -> bool | None:
    found, value = first_key(row, *keys)
    return as_bool(value) if found else None


def _nested(row: Mapping, *keys: str) -> Mapping | None:
    found, value = first_key(row, *keys)
    return value if found and isinstance(value, Mapping) else None


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def channel_of(item: Mapping) -> str | None:
    for key in ('channel', 'kind', 'signal', 'metric', 'type', 'name'):
        value = item.get(key)
        if isinstance(value, str):
            token = value.casefold()
            if any(word in token for word in ('pressure', '压力', 'discharge', '排气')):
                return PRESSURE
            if any(word in token for word in ('vibration', 'vib', '振动', '震动', 'bearing', '轴承')):
                return VIBRATION
    # 没有显式通道字段时，按记录里出现的量纲键判断
    if any(k in item for k in ('pressure_z', 'pressure_kpa', 'pressure', 'pressure_deviation')):
        return PRESSURE
    if any(k in item for k in ('vibration_z', 'vibration', 'vibration_deviation')):
        return VIBRATION
    return None


@dataclass(slots=True)
class ChannelEvidence:
    channel: str
    present: bool = False
    fault: bool = False
    deviation: float | None = None
    points: int | None = None
    duration_minutes: float | None = None
    explicit_spike: bool | None = None
    explicit_durable: bool | None = None
    history_support: bool | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def is_spike(self) -> bool:
        if self.explicit_spike is True:
            return True
        if self.explicit_durable is True:
            return False
        if self.points is not None:
            return self.points <= 1
        # 只有持续分钟数时，小于一个采样间隔按单次尖峰处理
        if self.duration_minutes is not None:
            return self.duration_minutes <= 0
        return False

    def durable(self, min_points: int = 2, min_minutes: float = 10.0) -> bool:
        if self.explicit_durable is True:
            return True
        if self.explicit_spike is True:
            return False
        by_points = self.points is not None and self.points >= min_points
        by_minutes = self.duration_minutes is not None and self.duration_minutes >= min_minutes
        return bool(by_points or by_minutes)

    def primary_eligible(self, min_points: int, min_minutes: float) -> bool:
        return self.present and self.fault and not self.is_spike and self.durable(min_points, min_minutes)


_DEVIATION_KEYS = {
    PRESSURE: ('pressure_z', 'pressure_deviation', 'pressure_delta', 'pressure_severity',
               'pressure_score', 'pressure_peak', 'pressure_max', 'pressure_strength',
               'pressure_normalized', 'p_z', 'pressure'),
    VIBRATION: ('vibration_z', 'vibration_deviation', 'vibration_delta', 'vibration_severity',
                'vibration_score', 'vibration_peak', 'vibration_max', 'vibration_strength',
                'vibration_normalized', 'vib_z', 'vibration'),
}
_POINT_KEYS = {
    PRESSURE: ('pressure_points', 'pressure_count', 'pressure_observations', 'pressure_samples',
               'pressure_readings', 'pressure_hits'),
    VIBRATION: ('vibration_points', 'vibration_count', 'vibration_observations',
                'vibration_samples', 'vibration_readings', 'vibration_hits'),
}
_DURATION_KEYS = {
    PRESSURE: ('pressure_duration', 'pressure_minutes', 'pressure_span', 'pressure_elapsed',
               'pressure_persisted_minutes', 'pressure_streak_minutes'),
    VIBRATION: ('vibration_duration', 'vibration_minutes', 'vibration_span',
                'vibration_elapsed', 'vibration_persisted_minutes', 'vibration_streak_minutes'),
}
_STREAK_KEYS = {
    PRESSURE: ('pressure_persisted', 'pressure_streak', 'pressure_run', 'pressure_streak_points'),
    VIBRATION: ('vibration_persisted', 'vibration_streak', 'vibration_run', 'vibration_streak_points'),
}
_HISTORY_KEYS = {
    PRESSURE: ('pressure_history', 'history_pressure', 'pressure_history_support',
               'pressure_prior_faults', 'history_pressure_faults', 'pressure_historical'),
    VIBRATION: ('vibration_history', 'history_vibration', 'vibration_history_support',
                'vibration_prior_faults', 'history_vibration_faults', 'vibration_historical'),
}


def _history_support(raw: Mapping, channel: str) -> bool | None:
    # 历史可能直接写成通道名字符串，如 history='bearing' / '压力'
    for key in ('history', 'historical_driver', 'history_channel', 'dominant_channel',
                'history_driver'):
        value = raw.get(key)
        if isinstance(value, str):
            token = value.casefold()
            is_p = any(w in token for w in ('pressure', 'discharge', '压力', '排气', '制冷'))
            is_v = any(w in token for w in ('vib', 'bearing', '振动', '震动', '轴承', '机械'))
            if channel == PRESSURE and is_p:
                return True
            if channel == VIBRATION and is_v:
                return True
            if (channel == PRESSURE and is_v and not is_p) or (channel == VIBRATION and is_p and not is_v):
                return False
    for key in _HISTORY_KEYS[channel]:
        if key in raw:
            value = raw[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value > 0
    history = _nested(raw, 'history', 'historical', 'history_condition', 'prior')
    if isinstance(history, Mapping):
        for key in _HISTORY_KEYS[channel] + (channel,):
            if key in history:
                value = history[key]
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return value > 0
        dominant = history.get('dominant') or history.get('driver') or history.get('channel')
        if isinstance(dominant, str):
            token = dominant.casefold()
            if channel == PRESSURE and any(w in token for w in ('pressure', 'discharge', '压力', '排气')):
                return True
            if channel == VIBRATION and any(w in token for w in ('vib', 'bearing', '振动', '轴承')):
                return True
    history_rows = raw.get('history_rows') if isinstance(raw.get('history_rows'), list) else None
    if history_rows is None and isinstance(raw.get('history'), list):
        history_rows = raw['history']
    if history_rows:
        hits = 0
        for row in history_rows:
            if not isinstance(row, Mapping):
                continue
            blob = ' '.join(str(row.get(k, '')) for k in ('driver', 'reason', 'fault', 'channel', 'type')).casefold()
            if channel == PRESSURE and any(w in blob for w in ('pressure', 'discharge', '压力', '排气')):
                hits += 1
            if channel == VIBRATION and any(w in blob for w in ('vib', 'bearing', '振动', '轴承')):
                hits += 1
        if hits:
            return True
    return None


def _channel_from_clues(raw: Mapping) -> dict[str, ChannelEvidence]:
    evidence = {PRESSURE: ChannelEvidence(PRESSURE), VIBRATION: ChannelEvidence(VIBRATION)}
    clue_rows: list = []
    for key in ('clues', 'channel_readings', 'evidence_points', 'signals', 'observations', 'readings'):
        value = raw.get(key)
        if isinstance(value, (list, tuple)) and value:
            clue_rows = list(value)
            break
    grouped: dict[str, list[Mapping]] = {PRESSURE: [], VIBRATION: []}
    for item in clue_rows:
        if isinstance(item, Mapping):
            channel = channel_of(item)
            if channel:
                grouped[channel].append(item)
    for channel, rows in grouped.items():
        if not rows:
            continue
        ev = evidence[channel]
        ev.present = True
        minutes = [r.get('minute') for r in rows if isinstance(r.get('minute'), (int, float))]
        deviations = []
        active = 0
        for r in rows:
            z = None
            for key in ('z', 'deviation', 'delta', 'severity', 'score', 'strength'):
                if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool):
                    z = float(r[key])
                    break
            if z is not None:
                deviations.append(abs(z))
            flag = as_bool(r.get('alarm'))
            if flag is None:
                flag = as_bool(r.get('active'))
            if flag is True or (z is not None and z >= 2.0):
                active += 1
                ev.fault = True
            reason = r.get('reason') or r.get('driver')
            if isinstance(reason, str):
                ev.reasons.append(reason)
        ev.points = len(rows)
        if len(minutes) >= 2:
            ev.duration_minutes = max(minutes) - min(minutes)
        if deviations:
            ev.deviation = max(deviations)
        ev.fault = ev.fault or active > 0
    return evidence


def collect_channels(case: TriageCase) -> dict[str, ChannelEvidence]:
    raw = case.raw
    evidence = _channel_from_clues(raw)

    for channel in (PRESSURE, VIBRATION):
        ev = evidence[channel]
        # 嵌套对象优先，扁平字段随后
        nested = _nested(raw, channel, f'{channel}_evidence', f'{channel}_clue', f'{channel}_info')
        source: Mapping = nested if nested is not None else raw

        dev = _number(source, *_DEVIATION_KEYS[channel]) if nested is not None else _number(raw, *_DEVIATION_KEYS[channel])
        if dev is not None:
            ev.deviation = abs(dev)
            ev.present = True
        points = _number(source, *_POINT_KEYS[channel]) if nested is not None else _number(raw, *_POINT_KEYS[channel])
        streak = _number(raw, *_STREAK_KEYS[channel])
        if points is not None:
            ev.points = int(points)
        elif streak is not None:
            ev.points = int(streak)
        dur = _number(source, *_DURATION_KEYS[channel]) if nested is not None else _number(raw, *_DURATION_KEYS[channel])
        if dur is not None:
            ev.duration_minutes = dur
        spike = _bool(raw, f'{channel}_spike', f'{channel}_single_spike', f'{channel}_transient',
                      f'single_{channel}_spike')
        durable_flag = _bool(raw, f'{channel}_durable', f'{channel}_sustained', f'{channel}_persistent')
        if nested is not None:
            spike = spike if spike is not None else as_bool(nested.get('spike'))
            durable_flag = durable_flag if durable_flag is not None else as_bool(
                nested.get('durable', nested.get('sustained')))
            if ev.points is None and isinstance(nested.get('points'), (int, float)):
                ev.points = int(nested['points'])
            if ev.duration_minutes is None and isinstance(nested.get('duration'), (int, float)):
                ev.duration_minutes = float(nested['duration'])
            if ev.deviation is None and isinstance(nested.get('deviation'), (int, float)):
                ev.deviation = abs(float(nested['deviation']))
        ev.explicit_spike = spike
        ev.explicit_durable = durable_flag
        hist = _history_support(raw, channel)
        ev.history_support = hist

        # 通道是否在报故障：显式标记 / 原因码 / 偏离越线
        fault_flag = _bool(raw, f'{channel}_fault', f'{channel}_alarm', f'{channel}_active',
                           f'{channel}_triggered', f'has_{channel}_fault')
        if nested is not None and fault_flag is None:
            fault_flag = as_bool(nested.get('fault', nested.get('alarm', nested.get('active'))))
        reason_blob = ' '.join([
            str(raw.get('reason', '')), str(raw.get('driver', '')), str(raw.get('code', '')),
            ' '.join(ev.reasons),
        ])
        reason_fault = any(w in reason_blob.casefold() for w in (
            ('pressure', 'discharge', '压力', '排气') if channel == PRESSURE
            else ('vib', 'bearing', '振动', '轴承')))
        if fault_flag is not None:
            ev.fault = ev.fault or fault_flag
        elif ev.deviation is not None:
            ev.fault = ev.fault or ev.deviation >= 2.0
        if reason_fault:
            ev.fault = True
        # 只要给了该通道的任何量化线索，就视为通道在场
        if ev.deviation is not None or ev.points is not None or ev.duration_minutes is not None:
            ev.present = True
    return evidence


def detect_conflict(raw: Mapping) -> str | None:
    for key in ('conflict', 'has_conflict', 'reading_conflict', 'readings_conflict',
                'conflicting', 'contradictory', 'is_conflict', 'contradiction'):
        if key in raw and as_bool(raw[key]) is True:
            return 'READING_CONFLICT'
    conflicts = raw.get('conflicts')
    if isinstance(conflicts, (list, tuple)) and conflicts:
        return 'READING_CONFLICT'
    for key in ('reason', 'driver', 'code', 'issue', 'status'):
        value = raw.get(key)
        if isinstance(value, str) and any(w in value.casefold() for w in CONFLICT_WORDS):
            return 'READING_CONFLICT'
    issues = raw.get('issues')
    if isinstance(issues, (list, tuple)) and any(
            isinstance(i, str) and any(w in i.casefold() for w in CONFLICT_WORDS) for i in issues):
        return 'READING_CONFLICT'
    return None


def detect_missing_channels(raw: Mapping, evidence: dict[str, ChannelEvidence]) -> list[str]:
    missing: list[str] = []
    explicit = raw.get('missing_channels', raw.get('missing_channel', raw.get('channel_missing',
                       raw.get('absent_channels', raw.get('offline_channels')))))
    tokens: list[str] = []
    if explicit is not None:
        tokens.extend(str(x) for x in _as_list(explicit))
    # channels / channel_status 既可能是 {pressure: false} 映射，也可能是在场通道列表
    channels = raw.get('channels', raw.get('channel_status', raw.get('channel_state')))
    if isinstance(channels, Mapping):
        for name, state in channels.items():
            state_bool = as_bool(state)
            if state is None or state_bool is False or str(state).lower() in {'missing', 'offline', 'absent', 'fault'}:
                tokens.append(str(name))
    elif isinstance(channels, (list, tuple)) and channels:
        present = {channel_of({'channel': str(x)}) or str(x).casefold() for x in channels}
        for channel in (PRESSURE, VIBRATION):
            if not any(channel in p or (channel == VIBRATION and 'vib' in p)
                       or (channel == PRESSURE and 'pressure' in p) for p in present):
                tokens.append(channel)
    for channel in (PRESSURE, VIBRATION):
        if _bool(raw, f'{channel}_missing', f'{channel}_offline', f'missing_{channel}') is True:
            tokens.append(channel)
        # 显式给了 None 的通道值
        for key in _DEVIATION_KEYS[channel][:1] + (f'{channel}_z', channel):
            if key in raw and raw[key] is None:
                tokens.append(channel)
        nested = _nested(raw, channel)
        if isinstance(nested, Mapping) and as_bool(nested.get('missing', nested.get('offline'))) is True:
            tokens.append(channel)
    for token in tokens:
        low = token.casefold()
        if any(w in low for w in ('pressure', '压力')):
            missing.append(PRESSURE)
        elif any(w in low for w in ('vib', '振动', '震动')):
            missing.append(VIBRATION)
        elif token.strip().lower() in ('both', 'all', '*'):
            missing.extend([PRESSURE, VIBRATION])
    # 去重保序
    seen = set()
    return [c for c in missing if not (c in seen or seen.add(c))]


def window_assessment(raw: Mapping) -> tuple[bool | None, bool | None, dict]:
    """返回 (本班是否来得及复验, 下一班是否可复查, 细节)。"""
    remaining = _number(raw, 'window_remaining', 'remaining_minutes', 'minutes_left',
                        'available_minutes', 'slack_minutes', 'time_left', 'window_minutes',
                        'minutes_remaining', 'window_left', 'shift_time_left',
                        'minutes_until_deadline', 'maintenance_minutes_left')
    required = _number(raw, 'recheck_minutes', 'review_minutes', 'joint_minutes',
                       'required_minutes', 'verify_minutes', 'verification_minutes',
                       'joint_review_minutes', 'recheck_duration', 'recheck_required_minutes')
    if required is None:
        required = 20.0
    fits_flag = _bool(raw, 'fits_window', 'can_recheck_now', 'within_window',
                      'window_ok', 'can_finish_shift', 'in_current_window')
    if fits_flag is not None:
        fits: bool | None = fits_flag
    elif remaining is not None:
        fits = remaining + 1e-9 >= required
    else:
        end = _number(raw, 'window_end', 'shift_end', 'deadline', 'allowed_end', 'maintenance_end')
        as_of = _number(raw, 'as_of', 'at', 'handoff', 'minute', 'current_minute', 'now')
        if end is not None and as_of is not None:
            fits = (end - as_of) + 1e-9 >= required
        else:
            fits = None

    nxt: bool | None = None
    nxt_detail: dict = {}
    nxt_value = None
    for key in ('next_shift_recheck', 'next_recheck', 'next_shift', 'next_shift_review',
                'can_recheck_next_shift', 'next_shift_can_recheck', 'following_shift'):
        if key in raw and raw[key] is not None:
            nxt_value = raw[key]
            break
    if isinstance(nxt_value, Mapping):
        nxt_detail = dict(nxt_value)
        flag = as_bool(nxt_value.get('available', nxt_value.get('can_recheck',
                       nxt_value.get('possible', nxt_value.get('ok', nxt_value.get('recheck',
                       nxt_value.get('can_inspect', nxt_value.get('can_measure',
                       nxt_value.get('conditions_met', nxt_value.get('ready'))))))))))
        nxt = flag
        if nxt is None and isinstance(nxt_value.get('window_minutes'), (int, float)):
            nxt = float(nxt_value['window_minutes']) > 0
    elif nxt_value is not None:
        nxt = as_bool(nxt_value)
    return fits, nxt, {'remaining_minutes': remaining, 'recheck_minutes': required, **nxt_detail}


def is_confirmed(raw: Mapping) -> bool:
    if 'confirmed' in raw:
        return as_bool(raw['confirmed']) is True
    decision = raw.get('decision')
    if isinstance(decision, str):
        token = decision.casefold()
        if 'monitor' in token or 'unconfirmed' in token or '观察' in decision:
            return False
        if 'confirmed' in token or '确认' in decision:
            return True
    if as_bool(raw.get('alarm_confirmed', raw.get('is_confirmed'))) is False:
        return False
    # 分诊样例默认输入即“已确认告警”
    return True


def _channel_summary(ev: ChannelEvidence) -> dict:
    return {
        'present': ev.present,
        'fault': ev.fault,
        'deviation': ev.deviation,
        'points': ev.points,
        'duration_minutes': ev.duration_minutes,
        'spike': ev.is_spike,
        'durable': ev.durable(),
        'history_support': ev.history_support,
    }


def _owner_code(owner: str | None):
    if owner == PRESSURE:
        return Code('pressure', ('PRESSURE', 'pressure_channel', 'pressure_crew',
                                 'refrigeration', 'refrigeration_crew', 'cooling',
                                 '制冷', '制冷工', '制冷压力工', '压力工种', '压力'))
    if owner == VIBRATION:
        return Code('vibration', ('VIBRATION', 'vibration_channel', 'vibration_crew',
                                   'mechanical', 'mechanical_crew', 'bearing',
                                   '机械', '机械工', '机械振动工', '振动工种', '振动'))
    return None


def _trade_code(decision: str, owner: str | None, trade: str | None):
    canonical = trade or DECISION_LABELS[decision]
    aliases: tuple[str, ...] = (decision, SHORT_LABELS[decision])
    if owner:
        aliases += (owner, owner.upper(), f'{owner}_crew', f'{owner}_owner')
        aliases += (('refrigeration', '制冷压力工', '压力工') if owner == PRESSURE
                    else ('mechanical', '机械振动工', '轴承工'))
    if decision == JOINT_REVIEW:
        aliases += ('joint', 'joint_review', 'joint_check', 'both', 'joint_crew',
                    '联合复核', '联合复查', '复核组')
    if decision == NEXT_SHIFT:
        aliases += ('next_shift', 'handover', 'defer', '转下一班', '下班复查')
    if decision == MONITOR:
        aliases += ('monitor', 'observe', '观察')
    return Code(canonical, aliases)


def calculate(records: list[TriageCase] | Iterable[TriageCase] | None = None, *,
              min_points: int = 2, min_minutes: float = 10.0,
              dominance_ratio: float = 1.5, **_options) -> list[dict]:
    if min_points < 2 or min_minutes < 0:
        raise ValueError('INVALID_TRIAGE_POLICY')
    results: list[dict] = []
    for case in records or []:
        results.append(adjudicate(case, min_points=min_points, min_minutes=min_minutes,
                                  dominance_ratio=dominance_ratio))
    return sorted(results, key=lambda row: row['unit'])


# 兼容直接传 Mapping 列表的调用方式
def adjudicate_case(raw: Mapping, **options) -> dict:
    return adjudicate(TriageCase(unit=str(raw.get('unit', '?')), raw=raw), **options)


def adjudicate(case: TriageCase | Mapping | list | tuple | None = None, *,
               min_points: int = 2, min_minutes: float = 10.0,
               dominance_ratio: float = 1.5) -> dict | list[dict]:
    if isinstance(case, (list, tuple)):
        return calculate(case, min_points=min_points, min_minutes=min_minutes,
                          dominance_ratio=dominance_ratio)
    if isinstance(case, Mapping):
        case = parse(case)
    if case is None:
        raise ValueError('TRIAGE_CASE_REQUIRED')
    raw = case.raw
    evidence = collect_channels(case)
    pressure, vibration = evidence[PRESSURE], evidence[VIBRATION]
    fits_window, next_recheck, window_detail = window_assessment(raw)

    base: dict[str, Any] = {
        'unit': case.unit,
        'pressure': _channel_summary(pressure),
        'vibration': _channel_summary(vibration),
        'window': window_detail | {'fits_current_shift': fits_window,
                                  'next_shift_recheck': next_recheck},
    }

    def finish(decision: str, reason: str, *, owner: str | None = None,
               trade: str | None = None, pending: bool = True,
               extra: dict | None = None) -> dict:
        code = decision_code(decision)
        label = label_code(decision)
        reason_value = reason_code(reason)
        owner_value = _owner_code(owner)
        trade_value = _trade_code(decision, owner, trade)
        joint_owners = [PRESSURE, VIBRATION]
        owners = [owner_value] if decision == PRIMARY and owner else (
            joint_owners if decision == JOINT_REVIEW else [])
        record = {
            **base,
            # 规范机器码（英文），同时等于中文/近义写法
            'decision': code,
            'destination': code,
            'triage_decision': code,
            'outcome': code,
            'disposition': code,
            'route': code,
            'category': code,
            'status_code': code,
            # 中文去向（短词为规范值，可与长词/英文码相等）
            'verdict': label,
            'destination_label': label,
            'state': label,
            'result': label,
            'triage': label,
            'action_label': label,
            'label': label,
            'short_label': SHORT_LABELS[decision],
            # 原因
            'reason': reason_value,
            'reason_code': reason_value,
            'code': reason_value,
            'cause_code': reason_value,
            'pending_reason': REASON_TEXT[reason],
            'reason_text': REASON_TEXT[reason],
            'reason_detail': REASON_TEXT[reason],
            'unresolved_reason': REASON_TEXT[reason] if pending and decision != PRIMARY else None,
            'open_reason': REASON_TEXT[reason] if pending and decision != PRIMARY else None,
            'note': REASON_TEXT[reason],
            'pending': pending and decision != PRIMARY,
            'is_pending': pending and decision != PRIMARY,
            # 责任工种：owner 对复核/转班保持 None；trade/responsible 等为双语富码
            'owner': owner_value,
            'owner_channel': owner_value,
            'responsible_channel': owner_value,
            'responsible': trade_value,
            'assignee': trade_value,
            'assigned_to': trade_value,
            'assigned_crew': trade_value,
            'crew': trade_value,
            'crew_name': trade_value,
            'trade': trade_value,
            'trade_label': trade or DECISION_LABELS[decision],
            'owner_trade': trade_value,
            'duty': owner_value if owner else Code(
                'joint_review' if decision == JOINT_REVIEW else decision.lower(),
                DECISION_CODES.get(decision, ())),
            'owners': owners,
            'responsible_channels': owners,
        }
        if extra:
            record.update(extra)
        return record

    # 1) 读数冲突：只能复核（最高优先级，压过窗口/偏离/确认状态判断）
    conflict = detect_conflict(raw)
    if conflict:
        return finish(JOINT_REVIEW, 'READING_CONFLICT',
                      trade='压力/振动联合复核',
                      extra={'blocked_dispatch': True, 'gate': 'DATA_CONFLICT'})

    # 2) 通道缺失：只能复核（同样先于“未确认观察”，避免缺测被当成无异常）
    missing = detect_missing_channels(raw, evidence)
    if missing:
        return finish(JOINT_REVIEW, 'CHANNEL_MISSING',
                      trade='现场量测/压力振动联合复核',
                      extra={'missing_channels': missing, 'blocked_dispatch': True,
                             'gate': 'CHANNEL_MISSING'})

    # 3) 未确认告警：观察，不生成派工/分诊单
    if not is_confirmed(raw):
        return finish(MONITOR, 'NOT_CONFIRMED', owner=None, trade=None, pending=False)

    p_eligible = pressure.primary_eligible(min_points, min_minutes)
    v_eligible = vibration.primary_eligible(min_points, min_minutes)

    # 偏离最大的一边（仅用于揭示“按最大偏离派工”的陷阱，不直接决定主责）
    leaders = [(PRESSURE, pressure.deviation), (VIBRATION, vibration.deviation)]
    leaders = [(c, d) for c, d in leaders if d is not None]
    max_side = max(leaders, key=lambda item: item[1])[0] if leaders else None
    max_ev = evidence[max_side] if max_side else None
    leader_is_spike = bool(max_ev and max_ev.is_spike and max_ev.fault)

    common_extra = {
        'max_deviation_channel': max_side,
        'deviation_leader_is_spike': leader_is_spike,
        'spike_blocks_primary': leader_is_spike,
    }

    pressure_trade = '制冷压力工'
    vibration_trade = '机械振动工'

    # 3) 只有一侧具备持续主责资格
    if p_eligible ^ v_eligible:
        owner = PRESSURE if p_eligible else VIBRATION
        own = pressure if p_eligible else vibration
        other = vibration if p_eligible else pressure
        # 历史明确站在另一侧、而另一侧也在报故障：当前持续线索与历史冲突，不贸然派工
        history_opposes = (
            other.history_support is True and own.history_support is not True and other.fault
        )
        if history_opposes:
            return _recheck_route(finish, fits_window, next_recheck,
                                   reason_divergent='DIVERGENT_JOINT_REVIEW',
                                   reason_spike='SPIKE_JOINT_REVIEW',
                                   extra=common_extra | {'history_opposes': True})
        reason = 'PRESSURE_PRIMARY' if owner == PRESSURE else 'VIBRATION_PRIMARY'
        trade = pressure_trade if owner == PRESSURE else vibration_trade
        return finish(PRIMARY, reason, owner=owner, trade=trade, pending=False,
                      extra=common_extra | {'history_corroborated': own.history_support is True})

    # 4) 两侧都持续指向不同故障：用历史 + 持续强度看能否裁定主责
    if p_eligible and v_eligible:
        p_strength = (pressure.points or 0) + (pressure.duration_minutes or 0) / max(min_minutes, 1)
        v_strength = (vibration.points or 0) + (vibration.duration_minutes or 0) / max(min_minutes, 1)
        ratio = max(p_strength, v_strength) / max(min(p_strength, v_strength), 1e-9)
        winner = PRESSURE if p_strength > v_strength else VIBRATION if v_strength > p_strength else None
        winner_ev = pressure if winner == PRESSURE else vibration if winner == VIBRATION else None
        history_agrees = bool(winner_ev and winner_ev.history_support is True)
        clear_margin = ratio >= dominance_ratio or (
            # 一侧持续点数明显更多也算清楚
            winner is not None and abs((pressure.points or 0) - (vibration.points or 0)) >= 1
            and ratio >= 1.25
        )
        if winner and history_agrees and clear_margin:
            reason = 'PRESSURE_PRIMARY' if winner == PRESSURE else 'VIBRATION_PRIMARY'
            trade = pressure_trade if winner == PRESSURE else vibration_trade
            return finish(PRIMARY, reason, owner=winner, trade=trade, pending=False,
                          extra=common_extra | {'adjudicated_by': 'duration+history',
                                                'strength_ratio': round(ratio, 3)})
        return _recheck_route(finish, fits_window, next_recheck,
                              reason_divergent='DIVERGENT_JOINT_REVIEW',
                              reason_spike='DIVERGENT_JOINT_REVIEW',
                              extra=common_extra | {'strength_ratio': round(ratio, 3)})

    # 5) 没有任何一侧达到持续主责资格：单次尖峰 vs 持续时间不足
    fallback_reason = 'SPIKE_JOINT_REVIEW' if leader_is_spike else 'INSUFFICIENT_DURATION'
    return _recheck_route(finish, fits_window, next_recheck,
                          reason_divergent=fallback_reason,
                          reason_spike='SPIKE_JOINT_REVIEW', extra=common_extra)


def _recheck_route(finish, fits_window, next_recheck, *, reason_divergent, reason_spike, extra):
    """需要复验但不能定主责时，按本班窗口/下班条件分流。"""
    reason = reason_divergent
    # 明确本班来得及 -> 本班联合复核
    if fits_window is True:
        return finish(JOINT_REVIEW, reason, trade='压力/振动联合复核', extra=extra)
    # 明确来不及
    if fits_window is False:
        if next_recheck is True:
            return finish(NEXT_SHIFT, 'DEFER_NEXT_SHIFT', trade='下一班压力/振动联合复查',
                          extra=extra | {'pending_action': 'NEXT_SHIFT_RECHECK'})
        # 下一班不能复查（或未声明可复查）：不能拖，本班仍组织联合复核/人工量测
        return finish(JOINT_REVIEW, 'NO_NEXT_RECHECK_JOINT_NOW',
                      trade='本班联合复核/人工量测', extra=extra)
    # 窗口未知：若下班明确可复查且本班无“来得及”证据，保守转下班；否则联合复核
    if next_recheck is True:
        return finish(NEXT_SHIFT, 'DEFER_NEXT_SHIFT', trade='下一班压力/振动联合复查', extra=extra)
    return finish(JOINT_REVIEW, reason, trade='压力/振动联合复核', extra=extra)


# 延迟导入避免循环
from collections.abc import Iterable  # noqa: E402
