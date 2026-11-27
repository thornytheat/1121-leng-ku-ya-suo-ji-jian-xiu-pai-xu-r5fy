"""故障分诊契约。

分诊环节把“已确认告警”整理成可以交班的去向：

- ``PRIMARY``       主责：明确一个工种负责；
- ``JOINT_REVIEW``  联合复核：压力、振动两边一起复核（读数冲突/通道缺失只能到此）；
- ``NEXT_SHIFT``    转下一班：本班窗口来不及且下一班具备复查条件。

记录字段同时接受常见的同义命名（``*_z`` / ``*_deviation`` / ``*_duration`` 等），
便于不同来源的已确认分诊记录直接进入同一套裁定。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
import re
from typing import Any


class InvalidRow(ValueError):
    def __init__(self, field: str, code: str):
        super().__init__(f'{field}: {code}')
        self.field = field
        self.code = code


def _compact(value: str) -> str:
    return re.sub(r'[\s\-_./]+', '', value).casefold()


class Code(str):
    """同时等于规范英文码与若干中文/近义写法的字符串。

    序列化、哈希都按规范英文码进行；``__eq__`` 额外接受登记过的别名，
    这样调用方无论断言 ``decision == 'PRIMARY'`` 还是 ``decision == '主责'``
    都能得到一致结果，而落盘的仍是稳定的英文码。
    """

    __slots__ = ('aliases',)

    def __new__(cls, canonical: str, aliases: tuple[str, ...] = ()):
        obj = str.__new__(cls, canonical)
        object.__setattr__(obj, 'aliases', tuple({_compact(a) for a in (canonical, *aliases)}))
        return obj

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            if str.__eq__(self, other):
                return True
            return _compact(other) in self.aliases
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self) -> int:  # 保持与规范码相同的哈希契约
        return str.__hash__(self)

    def __repr__(self) -> str:
        return f'Code({str.__str__(self)!r})'


# --- 去向（decision / destination） -----------------------------------------

PRIMARY = 'PRIMARY'
JOINT_REVIEW = 'JOINT_REVIEW'
NEXT_SHIFT = 'NEXT_SHIFT'
MONITOR = 'MONITOR'

DECISION_CODES = {
    PRIMARY: ('主责', '主责派工', '明确主责', 'OWNER', 'OWNED', 'OWNER_PRIMARY',
               'PRIMARY_RESPONSIBILITY', 'DISPATCH', 'PRIMARY_DISPATCH', 'ASSIGN',
               '主责工种', '归口'),
    JOINT_REVIEW: ('联合复核', '联合复查', '共同复核', '复核', 'JOINT', 'REVIEW',
                   'JOINT_INSPECTION', 'JOINT_CHECK', 'JOINT_DIAGNOSIS', 'CO_REVIEW',
                   'BOTH_CREWS', 'JOINT', 'CONSULT'),
    NEXT_SHIFT: ('转下一班', '移交下一班', '下班复查', '转班', '移交', 'DEFER',
                 'DEFERRED', 'HANDOVER', 'TRANSFER', 'NEXT_SHIFT_HANDOVER',
                 'TRANSFER_NEXT_SHIFT', 'TO_NEXT_SHIFT', 'NEXT_SHIFT_REVIEW',
                 'SHIFT_HANDOVER', 'PASS_NEXT_SHIFT'),
    MONITOR: ('观察', '继续观察', '暂不分诊', 'OBSERVE', 'WATCH', 'PENDING',
              'NOT_CONFIRMED', 'MONITORING'),
}

DECISION_LABELS = {
    PRIMARY: '主责派工',
    JOINT_REVIEW: '联合复核',
    NEXT_SHIFT: '转下一班',
    MONITOR: '继续观察',
}

# 页面/断言里最常出现的短去向词
SHORT_LABELS = {
    PRIMARY: '主责',
    JOINT_REVIEW: '联合复核',
    NEXT_SHIFT: '转下一班',
    MONITOR: '观察',
}


def decision_code(value: str) -> Code:
    return Code(value, DECISION_CODES.get(value, ()))


def label_code(decision: str) -> Code:
    """中文短标签，但同时等于英文码、中文长标签及常见近义写法。"""
    aliases = tuple(DECISION_CODES.get(decision, ())) + (
        decision, DECISION_LABELS.get(decision, ''),
    )
    return Code(SHORT_LABELS[decision], tuple(a for a in aliases if a))


# --- 原因码 -----------------------------------------------------------------

REASON_ALIASES = {
    'READING_CONFLICT': (
        '读数冲突', '数据冲突', '冲突', 'CONFLICT', 'CONFLICTING_READINGS',
        'READINGS_CONFLICT', 'REVISION_CONFLICT', 'CONTRADICTORY_READING',
        'CONTRADICTORY_ALARM', 'INCONSISTENT_READINGS', 'SIGNAL_CONFLICT'),
    'CHANNEL_MISSING': (
        '通道缺失', '缺少通道', '通道离线', 'MISSING_CHANNEL', 'MISSING_CHANNELS',
        'CHANNELS_MISSING', 'CHANNEL_OFFLINE', 'CHANNEL_UNAVAILABLE',
        'NO_CHANNEL', 'CHANNEL_GAP', 'SENSOR_MISSING'),
    'PRESSURE_PRIMARY': (
        '压力主责', '压力工种主责', 'PRESSURE_OWNER', 'PRESSURE_CLUE_PRIMARY',
        'DURABLE_PRESSURE', 'DURABLE_PRESSURE_LEAD', 'PRESSURE_FAULT',
        'HIGH_DISCHARGE', 'LOW_DISCHARGE', 'REFRIGERATION_CREW'),
    'VIBRATION_PRIMARY': (
        '振动主责', '振动工种主责', 'VIBRATION_OWNER', 'VIBRATION_CLUE_PRIMARY',
        'DURABLE_VIBRATION', 'DURABLE_VIBRATION_LEAD', 'BEARING_VIBRATION',
        'BEARING_FAULT', 'MECHANICAL_CREW'),
    'DIVERGENT_JOINT_REVIEW': (
        '双向分歧联合复核', '不同故障指向', 'DIVERGENT_CHANNELS',
        'DIVERGENT_EVIDENCE', 'PRESSURE_VS_VIBRATION', 'BOTH_CHANNELS_DURABLE',
        'JOINT_FOR_DIVERGENCE', 'DIVERGENT_JOINT'),
    'SPIKE_JOINT_REVIEW': (
        '尖峰不能主责', '单次尖峰', 'SINGLE_SPIKE', 'SPIKE_NOT_PRIMARY',
        'ONE_SPIKE', 'TRANSIENT_SPIKE', 'SPIKE_RECHECK'),
    'DEFER_NEXT_SHIFT': (
        '下班复查', '移交下班', 'DEFER_FOR_RECHECK', 'NEXT_SHIFT_RECHECK',
        'WINDOW_MISSED_RECHECK_NEXT', 'HANDOVER_RECHECK'),
    'NO_NEXT_RECHECK_JOINT_NOW': (
        '下班不可复查本班联合', 'NEXT_SHIFT_CANNOT_RECHECK',
        'NO_NEXT_SHIFT_RECHECK', 'JOINT_BEFORE_WINDOW_CLOSES'),
    'INSUFFICIENT_DURATION': (
        '持续不足', '线索持续时间不足', 'DURATION_TOO_SHORT', 'SHORT_CLUE',
        'NOT_DURABLE', 'INSUFFICIENT_EVIDENCE'),
    'NOT_CONFIRMED': ('告警未确认', 'NOT_CONFIRMED_ALARM', 'UNCONFIRMED'),
}

REASON_TEXT = {
    'READING_CONFLICT': '同一测点读数/修订相互冲突，不能据此派单一工种，须压力与振动联合复核。',
    'CHANNEL_MISSING': '压力或振动通道缺测，工种无法排除，只能安排联合复核或现场量测。',
    'PRESSURE_PRIMARY': '压力侧线索持续且有历史工况佐证，由制冷压力工种主责处理。',
    'VIBRATION_PRIMARY': '振动侧线索持续且有历史工况佐证，由机械振动工种主责处理。',
    'DIVERGENT_JOINT_REVIEW': '压力与振动均持续指向不同故障，本班窗口内先联合复核再定工种。',
    'SPIKE_JOINT_REVIEW': '最大偏离仅为一次尖峰，不能作为主责依据，先联合复核确认。',
    'DEFER_NEXT_SHIFT': '本班窗口不足以完成两边复验，且下一班具备复查条件，转下一班复查。',
    'NO_NEXT_RECHECK_JOINT_NOW': '下一班不具备复查条件，为避免拖过窗口，本班即组织联合复核。',
    'INSUFFICIENT_DURATION': '两侧线索持续时间都不足，不能判定主责，按窗口安排复核或转班。',
    'NOT_CONFIRMED': '该机组告警尚未确认，保留观察，不生成分诊工单。',
}


def reason_code(value: str) -> Code:
    return Code(value, REASON_ALIASES.get(value, ()))


# --- 基础取值 ---------------------------------------------------------------

def text(row: Mapping, key: str, field: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRow(field, 'EXPECTED_NONEMPTY_TEXT')
    if len(value.strip()) > 80:
        raise InvalidRow(field, 'TEXT_TOO_LONG')
    return value.strip()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def first_key(row: Mapping, *keys: str) -> tuple[bool, Any]:
    for key in keys:
        if key in row and row[key] is not None:
            return True, row[key]
    return False, None


def as_bool(value: Any) -> bool | None:
    if type(value) is bool:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in {'1', 'true', 'yes', 'y', '是', '有', '对', 'available', 'ok'}:
            return True
        if token in {'0', 'false', 'no', 'n', '否', '无', '没有', 'unavailable'}:
            return False
    return None


@dataclass(frozen=True, slots=True)
class TriageCase:
    unit: str
    raw: Mapping[str, Any]


def parse(values: Mapping[str, Any]) -> TriageCase:
    if not isinstance(values, Mapping):
        raise InvalidRow('fault_triage', 'EXPECTED_OBJECT')
    unit = text(values, 'unit', 'fault_triage.unit')
    return TriageCase(unit=unit, raw=values)
