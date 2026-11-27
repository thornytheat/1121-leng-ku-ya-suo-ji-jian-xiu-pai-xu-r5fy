from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any


class InvalidRow(ValueError):
    def __init__(self, field: str, code: str):
        super().__init__(f'{field}: {code}')
        self.field = field
        self.code = code


def number(row: Mapping, key: str, low: float, high: float, field: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise InvalidRow(field, 'EXPECTED_NUMBER')
    if not low <= value <= high or not math.isfinite(value):
        raise InvalidRow(field, 'OUT_OF_RANGE')
    return float(value)


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
class ClosedIncident:
    unit: str
    minute: int
    score: float
    alarm: bool
    inspected: bool
    confirmed: bool
    measured: int


def parse(values: Mapping[str, Any]) -> ClosedIncident:
    if not isinstance(values, Mapping):
        raise InvalidRow('shift_review', 'EXPECTED_OBJECT')
    unit = text(values, 'unit', 'shift_review.unit')
    minute = integer(values, 'minute', 0, 10000000, 'shift_review.minute')
    score = number(values, 'score', 0, 1, 'shift_review.score')
    alarm = flag(values, 'alarm', 'shift_review.alarm')
    inspected = flag(values, 'inspected', 'shift_review.inspected')
    confirmed = flag(values, 'confirmed', 'shift_review.confirmed')
    measured = integer(values, 'measured', 0, 10000000, 'shift_review.measured')
    return ClosedIncident(
        unit=unit,
        minute=minute,
        score=score,
        alarm=alarm,
        inspected=inspected,
        confirmed=confirmed,
        measured=measured,
    )
