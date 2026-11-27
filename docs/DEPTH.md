# 可复核的模型和处置边界

分类 AI/ML / 传统ML。

## 功能模块

| 模块 | 业务步骤 | 输出 | 核心实现 | 独立契约与边界测试 |
|---|---|---|---|---|
| M1 | 交接读数 | MeterReading处理证据 | `src/chillwatch/shift_meter/contracts.py` `src/chillwatch/shift_meter/algorithm.py` `src/chillwatch/shift_meter/service.py` `src/chillwatch/shift_meter/sampling_integrity.py` | `tests/test_shift_meter.py` `tests/test_sampling_integrity.py` |
| M2 | 历史工况 | DutyPoint处理证据 | `src/chillwatch/duty_reference/contracts.py` `src/chillwatch/duty_reference/algorithm.py` `src/chillwatch/duty_reference/service.py` `src/chillwatch/duty_reference/reference_comparison.py` | `tests/test_duty_reference.py` `tests/test_reference_comparison.py` |
| M3 | 稳健异常 | AlarmMeasure处理证据 | `src/chillwatch/robust_alarm/contracts.py` `src/chillwatch/robust_alarm/algorithm.py` `src/chillwatch/robust_alarm/service.py` `src/chillwatch/robust_alarm/threshold_replay.py` | `tests/test_robust_alarm.py` `tests/test_threshold_replay.py` |
| M4 | 持续告警 | TimedAlarm处理证据 | `src/chillwatch/persistence_filter/contracts.py` `src/chillwatch/persistence_filter/algorithm.py` `src/chillwatch/persistence_filter/service.py` `src/chillwatch/persistence_filter/episode_ledger.py` | `tests/test_persistence_filter.py` `tests/test_episode_ledger.py` |
| M5 | 停机排程 | WorkCandidate处理证据 | `src/chillwatch/maintenance_slots/contracts.py` `src/chillwatch/maintenance_slots/algorithm.py` `src/chillwatch/maintenance_slots/service.py` `src/chillwatch/maintenance_slots/work_order_proof.py` `src/chillwatch/maintenance_slots/coverage_plan.py` | `tests/test_maintenance_slots.py` `tests/test_work_order_proof.py` `tests/test_coverage_plan.py` |
| M6 | 班次复盘 | ClosedIncident处理证据 | `src/chillwatch/shift_review/contracts.py` `src/chillwatch/shift_review/algorithm.py` `src/chillwatch/shift_review/service.py` `src/chillwatch/shift_review/alarm_counterfactual.py` | `tests/test_shift_review.py` `tests/test_alarm_counterfactual.py` |

## 边界登记

| 陷阱 | 业务输入 | 处理位置 | 验证锚点 |
|---|---|---|---|
| TRAP-19 | 同一修订号出现不同仪表读数，反转输入仍给出同一冲突证据 | `src/chillwatch/shift_meter/algorithm.py` | `tests/test_shift_meter.py::test_revision_order_cannot_change_conflict` |
| TRAP-23 | 训练起点纳入，交接时刻不重复进入历史 | `src/chillwatch/duty_reference/algorithm.py` | `tests/test_duty_reference.py::test_cutoff_interval_uses_half_open_boundaries` |
| TRAP-31 | 极端负对数分数使用分支指数计算 | `src/chillwatch/robust_alarm/algorithm.py` | `tests/test_robust_alarm.py::test_sigmoid_does_not_overflow_at_large_magnitude` |
| TRAP-32 | 常数历史继承仪器分辨率，避免零尺度 | `src/chillwatch/duty_reference/algorithm.py` | `tests/test_duty_reference.py::test_constant_history_retains_instrument_floor` |
| TRAP-42 | 上报截止与测量截止共同过滤未来读数 | `src/chillwatch/shift_meter/algorithm.py` | `tests/test_shift_meter.py::test_no_post_cutoff_readings_in_history` |
| TRAP-43 | 全无故障历史时保留空召回而非虚高指标 | `src/chillwatch/shift_review/algorithm.py` | `tests/test_shift_review.py::test_lacking_positive_outcomes_does_not_produce_perfect_recall` |
| TRAP-44 | 训练域外读数隔离为人工复查 | `src/chillwatch/robust_alarm/algorithm.py` | `tests/test_robust_alarm.py::test_out_of_domain_reading_is_not_automated_high_confidence` |
| TRAP-53 | 与陌生设备拼批不改已知设备得分 | `src/chillwatch/robust_alarm/algorithm.py` | `tests/test_robust_alarm.py::test_single_point_stays_fixed_in_python_batches` |
| TRAP-54 | 历史或超参变化会改变基线版本号 | `src/chillwatch/duty_reference/algorithm.py` | `tests/test_duty_reference.py::test_training_key_carries_upstream_digest_and_configuration` |
