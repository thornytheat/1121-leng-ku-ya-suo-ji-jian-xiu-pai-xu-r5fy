from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class InvalidRow(ValueError):
    def __init__(self, field: str, code: str):
        super().__init__(f'{field}: {code}')
        self.field = field
        self.code = code


def integer(row: Mapping, key: str, low: int, high: int, field: str) -> int:
    value = row.get(key)
    if type(value) is not int:
        raise InvalidRow(field, 'EXPECTED_INTEGER')
    if not low <= value <= high:
        raise InvalidRow(field, 'OUT_OF_RANGE')
    return value


def text(row: Mapping, key: str, field: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRow(field, 'EXPECTED_NONEMPTY_TEXT')
    if len(value.strip()) > 80:
        raise InvalidRow(field, 'TEXT_TOO_LONG')
    return value.strip()


def flag(row: Mapping, key: str, field: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise InvalidRow(field, 'EXPECTED_FLAG')
    return value


@dataclass(frozen=True, slots=True)
class TimedAlarm:
    unit: str
    minute: int
    alarm: bool
    eligible: bool
    reason: str
    duty: str


def parse(values: Mapping[str, Any]) -> TimedAlarm:
    if not isinstance(values, Mapping):
        raise InvalidRow('persistence_filter', 'EXPECTED_OBJECT')
    unit = text(values, 'unit', 'persistence_filter.unit')
    minute = integer(values, 'minute', 0, 10000000, 'persistence_filter.minute')
    alarm = flag(values, 'alarm', 'persistence_filter.alarm')
    eligible = flag(values, 'eligible', 'persistence_filter.eligible')
    reason = text(values, 'reason', 'persistence_filter.reason')
    duty = text(values, 'duty', 'persistence_filter.duty')
    return TimedAlarm(
        unit=unit,
        minute=minute,
        alarm=alarm,
        eligible=eligible,
        reason=reason,
        duty=duty,
    )
