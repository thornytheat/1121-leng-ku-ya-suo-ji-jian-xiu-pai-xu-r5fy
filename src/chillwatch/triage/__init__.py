"""故障分诊模块的命名别名，规范实现见 :mod:`chillwatch.fault_triage`。"""
from chillwatch.fault_triage import *  # noqa: F401,F403
from chillwatch.fault_triage import (  # noqa: F401
    DECISION_LABELS, JOINT_REVIEW, MONITOR, NEXT_SHIFT, PRIMARY,
    TriageLedger, TriageSaveError, evaluate, adjudicate, calculate,
)
