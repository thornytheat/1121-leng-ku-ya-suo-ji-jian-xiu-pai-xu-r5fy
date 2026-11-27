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
class MeterReading:
    unit: str
    minute: int
    reported: int
    pressure: float
    scale: str
    vibration: float
    defrost: bool
    revision: int


def parse(values: Mapping[str, Any]) -> MeterReading:
    if not isinstance(values, Mapping):
        raise InvalidRow('shift_meter', 'EXPECTED_OBJECT')
    unit = text(values, 'unit', 'shift_meter.unit')
    minute = integer(values, 'minute', 0, 10000000, 'shift_meter.minute')
    reported = integer(values, 'reported', 0, 10000000, 'shift_meter.reported')
    pressure = number(values, 'pressure', 0, 3000, 'shift_meter.pressure')
    scale = text(values, 'scale', 'shift_meter.scale')
    vibration = number(values, 'vibration', 0, 1000, 'shift_meter.vibration')
    defrost = flag(values, 'defrost', 'shift_meter.defrost')
    revision = integer(values, 'revision', 1, 200, 'shift_meter.revision')
    return MeterReading(
        unit=unit,
        minute=minute,
        reported=reported,
        pressure=pressure,
        scale=scale,
        vibration=vibration,
        defrost=defrost,
        revision=revision,
    )
