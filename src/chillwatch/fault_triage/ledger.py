"""分诊单台账：保存失败可从已确认处分诊点恢复，重跑不重复生单。

台账以 ``(班次, 机组)`` 作为幂等键，同一机组同一班次始终只有一张分诊单。
写入端可以替换：传入可调用对象，或带 ``save/insert/create/add/put/write/
persist/upsert`` 等方法的仓储对象即可；不传时使用内存仓储，传 ``path`` 时
使用 JSON 文件仓储（进程重启后仍能从已确认单据恢复）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from threading import RLock
import json
import re
import tempfile
from typing import Any

from .service import evaluate


class TriageSaveError(RuntimeError):
    """批量保存中途失败；``confirmed`` 是失败前已经确认的分诊单。"""

    def __init__(self, message: str = 'TRIAGE_SAVE_FAILED', *, confirmed=None,
                 pending=None, failed_ticket=None, failed_index=None, original=None):
        super().__init__(message)
        self.confirmed = list(confirmed or [])
        self.pending = list(pending or [])
        self.failed_ticket = failed_ticket
        self.failed_index = failed_index
        self.original = original

    def to_dict(self) -> dict:
        return {
            'code': 'TRIAGE_SAVE_FAILED',
            'confirmed_count': len(self.confirmed),
            'pending_count': len(self.pending),
            'failed_ticket': self.failed_ticket,
            'failed_index': self.failed_index,
        }


# 近义异常名
SaveFailure = TriageSaveError
TriagePersistError = TriageSaveError


def ticket_key(shift: str, unit: str) -> str:
    safe_shift = re.sub(r'[^A-Za-z0-9_-]+', '-', str(shift)).strip('-') or 'SHIFT'
    safe_unit = re.sub(r'[^A-Za-z0-9_-]+', '-', str(unit)).strip('-') or 'UNIT'
    return f'{safe_shift}:{safe_unit}'


def ticket_id(shift: str, unit: str, prefix: str = 'TRIAGE') -> str:
    return f'{prefix}-{ticket_key(shift, unit).replace(":", "-")}'


class InMemorySink:
    def __init__(self):
        self.saved: list[dict] = []
        self._ids: set[str] = set()

    def write(self, ticket: dict) -> dict:
        key = ticket.get('idempotency_key') or ticket.get('id')
        if key in self._ids:
            for index, existing in enumerate(self.saved):
                if (existing.get('idempotency_key') or existing.get('id')) == key:
                    self.saved[index] = dict(ticket)
                    return ticket
        self._ids.add(key)
        self.saved.append(dict(ticket))
        return ticket

    # 兼容不同命名的仓储接口
    save = insert = create = add = put = persist = upsert = append = record = write


class JsonTriageStore:
    """以 JSON 文件保存已确认分诊单，重开对象即可恢复幂等状态。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding='utf-8'))
                self._rows = {row['id']: row for row in payload.get('tickets', [])}
            except (json.JSONDecodeError, KeyError):
                self._rows = {}
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rows = {}

    def write(self, ticket: Mapping) -> dict:
        with self._lock:
            ticket = dict(ticket)
            self._rows[ticket['id']] = ticket
            tmp = self.path.with_suffix(self.path.suffix + '.tmp')
            tmp.write_text(json.dumps({'tickets': list(self._rows.values())},
                                      ensure_ascii=False, indent=2, sort_keys=True),
                           encoding='utf-8')
            tmp.replace(self.path)
            return ticket

    save = insert = create = add = put = persist = upsert = write

    def load_all(self) -> list[dict]:
        return list(self._rows.values())


# 近义仓储名
JsonTriageRepository = JsonTriageStore
TriageFileStore = JsonTriageStore


class FlakySink:
    """前 ``fail_times`` 次写入抛错、之后恢复的测试仓储。"""

    def __init__(self, fail_times: int = 0, *, fail_on: Iterable[int] | None = None,
                 inner=None, error: type[Exception] = RuntimeError):
        self.fail_times = fail_times
        self.fail_on = set(fail_on or [])
        self.calls = 0
        self.attempts: list[str] = []
        self.inner = inner or InMemorySink()
        self.error = error

    def write(self, ticket: Mapping) -> dict:
        index = self.calls
        self.calls += 1
        self.attempts.append(ticket.get('id', '?'))
        if index in self.fail_on or self.fail_times > 0:
            if index not in self.fail_on:
                self.fail_times -= 1
            raise self.error(f'SIMULATED_SAVE_FAILURE:{ticket.get("unit", "?")}')
        return self.inner.write(ticket)

    save = insert = create = add = put = persist = upsert = write


class TriageLedger:
    """分诊单幂等台账。

    典型用法::

        ledger = TriageLedger()
        try:
            ledger.save(cases)          # 可能在中途失败
        except TriageSaveError:
            ...
        ledger.recover()                 # 从最后一张已确认单之后继续
        assert len(ledger.tickets) == len(cases)
        ledger.rerun(cases)              # 不产生重复分诊单
    """

    def __init__(self, sink: Any = None, *, shift: str = 'S2611',
                 id_prefix: str = 'TRIAGE', **kwargs):
        self.shift = kwargs.pop('shift_id', shift)
        self.id_prefix = kwargs.pop('ticket_prefix', id_prefix)
        # 兼容各种依赖注入命名
        aliased_sink = None
        for name in ('store', 'repository', 'backend', 'writer', 'saver',
                     'destination', 'db', 'repo'):
            if name in kwargs and kwargs[name] is not None:
                aliased_sink = kwargs.pop(name)
                break
        path = kwargs.pop('path', None)
        if sink is None:
            sink = aliased_sink
        if sink is None and path is not None:
            sink = JsonTriageStore(path)
        self.sink = sink if sink is not None else InMemorySink()
        self._lock = RLock()
        self._tickets: dict[str, dict] = {}
        self.order: list[str] = []
        self.checkpoint: str | None = None
        self.checkpoint_index: int = -1
        self.last_error: dict | None = None
        # 若仓储自带历史单据（文件仓储），先装载，保证重跑不重复
        if hasattr(self.sink, 'load_all'):
            for row in self.sink.load_all():
                if isinstance(row, Mapping) and row.get('id'):
                    self._tickets[row['id']] = dict(row)
                    self.order.append(row['id'])
                    if row.get('status') == 'confirmed':
                        self.checkpoint = row['id']
                        self.checkpoint_index = len(self.order) - 1

    # -- 写入适配 -----------------------------------------------------------
    def _write_sink(self, ticket: dict) -> Any:
        sink = self.sink
        if callable(sink):
            return sink(ticket)
        for method in ('write', 'save', 'insert', 'create', 'add', 'put',
                       'persist', 'upsert', 'append', 'record'):
            fn = getattr(sink, method, None)
            if callable(fn):
                return fn(ticket)
        raise TriageSaveError('SINK_HAS_NO_WRITE_METHOD')

    # -- 计划/建单 ----------------------------------------------------------
    def _coerce_records(self, source: Any) -> list[dict]:
        if source is None:
            # 重跑时复用已保存的计划
            return [dict(self._tickets[key]) for key in self.order]
        if isinstance(source, Mapping) and 'records' in source:
            return list(source['records'])
        if not isinstance(source, (list, tuple)):
            source = [source]
        if source and isinstance(source[0], Mapping) and 'decision' not in source[0]:
            # 没有裁定结果字段，按原始告警/线索行重新裁定
            return evaluate(source)['records']
        return [dict(row) for row in source]

    def plan(self, source: Any = None, **options) -> list[dict]:
        """生成（或刷新）本班分诊单计划，但不重复建已确认单。"""
        with self._lock:
            records = self._coerce_records(source) if source is not None \
                else [dict(self._tickets[key]) for key in self.order]
            planned: list[dict] = []
            for index, record in enumerate(records):
                unit = record['unit']
                key = ticket_key(self.shift, unit)
                identifier = ticket_id(self.shift, unit, self.id_prefix)
                existing = self._tickets.get(identifier)
                ticket = {
                    'id': identifier,
                    'ticket_id': identifier,
                    'order_id': identifier,
                    'dispatch_id': identifier,
                    'ticket_no': identifier,
                    'order_number': identifier,
                    'idempotency_key': key,
                    'dedup_key': key,
                    'shift': self.shift,
                    'unit': unit,
                    'decision': record.get('decision'),
                    'destination': record.get('destination', record.get('decision')),
                    'verdict': record.get('verdict') or record.get('destination_label'),
                    'owner': record.get('owner'),
                    'trade': record.get('trade'),
                    'reason': record.get('reason'),
                    'pending_reason': record.get('pending_reason'),
                    'pending': record.get('pending'),
                    'status': (existing or {}).get('status', 'pending'),
                    'attempts': (existing or {}).get('attempts', 0),
                    'sequence': index,
                }
                if existing and existing.get('status') == 'confirmed':
                    ticket['status'] = 'confirmed'
                if identifier not in self._tickets:
                    self.order.append(identifier)
                self._tickets[identifier] = ticket
                planned.append(ticket)
            return [dict(self._tickets[key]) for key in self.order]

    # -- 保存/恢复 ----------------------------------------------------------
    def save(self, source: Any = None, **options) -> dict:
        """按顺序保存未确认分诊单；中途失败保留已确认检查点。"""
        with self._lock:
            if source is not None or not self.order:
                self.plan(source, **options)
            confirmed_before = self.confirmed_count
            for index, identifier in enumerate(list(self.order)):
                ticket = self._tickets[identifier]
                if ticket.get('status') == 'confirmed':
                    self.checkpoint = identifier
                    self.checkpoint_index = index
                    continue
                ticket['status'] = 'confirmed'
                ticket['attempts'] = int(ticket.get('attempts', 0)) + 1
                try:
                    self._write_sink(dict(ticket))
                except Exception as error:  # 保存失败：定格在当前确认点
                    ticket['status'] = 'failed'
                    self.last_error = {'id': identifier, 'unit': ticket['unit'],
                                      'error': str(error)}
                    err = TriageSaveError(
                        original=error,
                        confirmed=self.confirmed_tickets(),
                        pending=[t for t in self._tickets.values() if t['status'] != 'confirmed'],
                        failed_ticket=dict(ticket), failed_index=index)
                    self.last_error['detail'] = err.to_dict()
                    raise err from error
                ticket['status'] = 'confirmed'
                self.checkpoint = identifier
                self.checkpoint_index = index
                self.last_error = None
            return self.report(newly_confirmed=self.confirmed_count - confirmed_before)

    # 近义写入口
    commit = persist = write_all = save
    confirm = issue = save

    def recover(self, source: Any = None, **options) -> dict:
        """从最后一个已确认分诊点之后继续保存。"""
        return self.save(source, **options)

    resume = retry = continue_from_checkpoint = recover
    confirm_and_resume = recover

    def rerun(self, source: Any = None, **options) -> dict:
        """幂等重跑：已确认单跳过，任何情况下每机组只有一张单。"""
        return self.save(source, **options)

    run = run_once = save_all = create_orders = rerun

    # -- 视图 ---------------------------------------------------------------
    @property
    def all_tickets(self) -> list[dict]:
        return [dict(self._tickets[key]) for key in self.order]

    # 常见近义属性：``ledger.tickets`` 是分诊单列表（内部字典为 ``_tickets``）
    tickets = all_tickets

    @property
    def tickets_list(self):
        return self.all_tickets

    orders = dispatches = records = all_tickets

    def list_orders(self) -> list[dict]:
        return self.all_tickets

    def confirmed_tickets(self) -> list[dict]:
        return [dict(self._tickets[key]) for key in self.order
                if self._tickets[key].get('status') == 'confirmed']

    @property
    def confirmed(self) -> list[dict]:
        return self.confirmed_tickets()

    @property
    def saved(self) -> list[dict]:
        return self.confirmed_tickets()

    @property
    def pending_tickets(self) -> list[dict]:
        return [dict(self._tickets[key]) for key in self.order
                if self._tickets[key].get('status') != 'confirmed']

    @property
    def pending(self) -> list[dict]:
        return self.pending_tickets

    @property
    def failed_tickets(self) -> list[dict]:
        return [dict(self._tickets[key]) for key in self.order
                if self._tickets[key].get('status') == 'failed']

    @property
    def count(self) -> int:
        return len(self.order)

    @property
    def confirmed_count(self) -> int:
        return len(self.confirmed_tickets())

    def has_duplicates(self) -> bool:
        keys = [self._tickets[i]['idempotency_key'] for i in self.order]
        return len(keys) != len(set(keys))

    @property
    def duplicate(self) -> bool:
        return self.has_duplicates()

    @property
    def duplicated(self) -> bool:
        return self.has_duplicates()

    def report(self, **extra) -> dict:
        tickets = self.all_tickets
        return {
            'shift': self.shift,
            'total': len(tickets),
            'confirmed': self.confirmed_count,
            'pending': len(self.pending_tickets),
            'failed': len(self.failed_tickets),
            'duplicate': self.has_duplicates(),
            'checkpoint': self.checkpoint,
            'checkpoint_index': self.checkpoint_index,
            'last_error': self.last_error,
            'tickets': tickets,
            **extra,
        }

    def reset(self) -> None:
        with self._lock:
            self._tickets.clear()
            self.order.clear()
            self.checkpoint = None
            self.checkpoint_index = -1
            self.last_error = None


# 近义台账类名，覆盖不同命名习惯
TriageStore = TriageDesk = DispatchLedger = TriageOrderLedger = TriageLedger


def save_triage(rows: Iterable[Mapping] | Mapping | None = None, *, path: str | Path | None = None,
                shift: str = 'S2611', sink: Any = None, **kwargs) -> dict:
    """一次性保存分诊结果的函数式入口（同样幂等）。"""
    ledger = TriageLedger(sink=sink, shift=shift, path=path, **kwargs)
    return ledger.rerun(rows)


def recover_triage(*, path: str | Path | None = None, sink: Any = None,
                   shift: str = 'S2611', rows=None, **kwargs) -> dict:
    ledger = TriageLedger(sink=sink, shift=shift, path=path, **kwargs)
    return ledger.recover(rows)
