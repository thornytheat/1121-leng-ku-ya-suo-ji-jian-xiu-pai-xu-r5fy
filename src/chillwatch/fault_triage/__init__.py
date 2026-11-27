"""故障分诊（已确认告警 -> 可交班的主责/联合复核/转下一班）。"""

from .contracts import (
    DECISION_LABELS,
    JOINT_REVIEW,
    MONITOR,
    NEXT_SHIFT,
    PRIMARY,
    SHORT_LABELS,
    InvalidRow,
    TriageCase,
    decision_code,
    label_code,
    parse,
    reason_code,
)
from .service import (
    adjudicate,
    adjudicate_all,
    adjudicate_alarms,
    build_shift_handoff,
    build_triage,
    build_triage_plan,
    classify,
    create_triage_orders,
    dispatch_triage,
    evaluate,
    handoff,
    run_triage,
    triage,
    triage_alarms,
    validate,
)
from .algorithm import adjudicate as adjudicate_one
from .algorithm import adjudicate_case, calculate
from .ledger import (
    DispatchLedger,
    FlakySink,
    InMemorySink,
    JsonTriageStore,
    SaveFailure,
    TriageDesk,
    TriageLedger,
    TriageSaveError,
    recover_triage,
    save_triage,
    ticket_id,
    ticket_key,
)

__all__ = [
    'evaluate', 'validate', 'calculate', 'adjudicate', 'adjudicate_one',
    'adjudicate_case', 'adjudicate_all', 'triage', 'run_triage', 'build_triage',
    'classify', 'triage_alarms', 'adjudicate_alarms', 'build_triage_plan',
    'create_triage_orders', 'build_shift_handoff', 'handoff', 'dispatch_triage',
    'parse', 'InvalidRow', 'TriageCase',
    'PRIMARY', 'JOINT_REVIEW', 'NEXT_SHIFT', 'MONITOR',
    'DECISION_LABELS', 'SHORT_LABELS', 'decision_code', 'label_code', 'reason_code',
    'TriageLedger', 'TriageSaveError', 'SaveFailure', 'TriageDesk',
    'DispatchLedger', 'JsonTriageStore', 'FlakySink', 'InMemorySink',
    'save_triage', 'recover_triage', 'ticket_id', 'ticket_key',
]
