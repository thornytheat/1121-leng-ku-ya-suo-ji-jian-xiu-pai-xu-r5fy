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
class WorkCandidate:
    unit: str
    rack: str
    decision: str
    driver: str
    runtime: int
    priority: float
    has_backup: bool
    allowed_start: int
    allowed_end: int


def parse(values: Mapping[str, Any]) -> WorkCandidate:
    if not isinstance(values, Mapping):
        raise InvalidRow('maintenance_slots', 'EXPECTED_OBJECT')
    unit = text(values, 'unit', 'maintenance_slots.unit')
    rack = text(values, 'rack', 'maintenance_slots.rack')
    decision = text(values, 'decision', 'maintenance_slots.decision')
    driver = text(values, 'driver', 'maintenance_slots.driver')
    runtime = integer(values, 'runtime', 1, 180, 'maintenance_slots.runtime')
    priority = number(values, 'priority', 0, 100, 'maintenance_slots.priority')
    has_backup = flag(values, 'has_backup', 'maintenance_slots.has_backup')
    allowed_start = integer(values, 'allowed_start', 0, 10000000, 'maintenance_slots.allowed_start')
    allowed_end = integer(values, 'allowed_end', 0, 10000000, 'maintenance_slots.allowed_end')
    return WorkCandidate(
        unit=unit,
        rack=rack,
        decision=decision,
        driver=driver,
        runtime=runtime,
        priority=priority,
        has_backup=has_backup,
        allowed_start=allowed_start,
        allowed_end=allowed_end,
    )
