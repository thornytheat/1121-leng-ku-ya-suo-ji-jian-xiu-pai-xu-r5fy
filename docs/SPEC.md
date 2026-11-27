# 冷库压缩机检修排序规范

## 运行方式

使用交接读数在第 590 分钟为北区冷库排班。运维主管先审阅异常边缘证据，再按机组冗余和班组空档确认短停检修。样例是受控合成流水，包含冲突修订、迟到上报、单位混用、化霜干扰和未完成验修。`capacity` 代表本次最多安排多少台停机，默认为四台。

## 模型与限制

历史窗口按半开区间切分，单机样本不足时回退到设备族基线。压力和振动各用中位数及 MAD 估计中心及波动，波动下限来自仪表分辨率。告警输入是按量纲归一化的压力和向上振动偏离，使用稳定 sigmoid 转成排序分数；样例中的默认曲率和阈值是演示班组策略。超过训练范围的读数先人工量测。单条告警不会派工。

排程按分数、作业截止分钟、设备编号排序，班组占用与冷区停机区间都用半开区间计算。没有独立备用压缩机的维护工单不得自动排入。班次复盘只使用完成且截止前可用的现场结果，把空分桶和无阳性批次显式标成不可计算。

## 业务输出

交接校验逐笔保留处理码。排程表展现机组、冷区、峰值评分、连续次数、班组、停机分钟及原因。评分曲线按机组汇总有效读数，完全无评分机组在该曲线上显示零。校准诊断只用于该班次的模型核对，五个分段保留样本数、预测均值、实际故障比例和误差。


## 输入记录

### 交接读数

- `unit` 类型 `str`。
- `minute` 类型 `int`，有效范围 0–10000000。
- `reported` 类型 `int`，有效范围 0–10000000。
- `pressure` 类型 `float`，有效范围 0–3000。
- `scale` 类型 `str`。
- `vibration` 类型 `float`，有效范围 0–1000。
- `defrost` 类型 `bool`。
- `revision` 类型 `int`，有效范围 1–200。
### 历史工况

- `unit` 类型 `str`。
- `family` 类型 `str`。
- `minute` 类型 `int`，有效范围 0–10000000。
- `pressure_kpa` 类型 `float`，有效范围 0–2200。
- `vibration` 类型 `float`，有效范围 0–60。
- `defrost` 类型 `bool`。
### 稳健异常

- `unit` 类型 `str`。
- `minute` 类型 `int`，有效范围 0–10000000。
- `pressure_kpa` 类型 `float`，有效范围 0–2200。
- `vibration` 类型 `float`，有效范围 0–60。
- `defrost` 类型 `bool`。
### 持续告警

- `unit` 类型 `str`。
- `minute` 类型 `int`，有效范围 0–10000000。
- `alarm` 类型 `bool`。
- `eligible` 类型 `bool`。
- `reason` 类型 `str`。
- `duty` 类型 `str`。
### 停机排程

- `unit` 类型 `str`。
- `rack` 类型 `str`。
- `decision` 类型 `str`。
- `driver` 类型 `str`。
- `runtime` 类型 `int`，有效范围 1–180。
- `priority` 类型 `float`，有效范围 0–100。
- `has_backup` 类型 `bool`。
- `allowed_start` 类型 `int`，有效范围 0–10000000。
- `allowed_end` 类型 `int`，有效范围 0–10000000。
### 班次复盘

- `unit` 类型 `str`。
- `minute` 类型 `int`，有效范围 0–10000000。
- `score` 类型 `float`，有效范围 0–1。
- `alarm` 类型 `bool`。
- `inspected` 类型 `bool`。
- `confirmed` 类型 `bool`。
- `measured` 类型 `int`，有效范围 0–10000000。

### 故障分诊

把已确认告警按通道线索整理成可交班的去向。输入记录（字段接受常见同义命名）：

- `unit` 类型 `str`。
- `pressure_z` / `vibration_z`（或 `*_deviation`）类型 `float`，通道归一化偏离。
- `pressure_points` / `vibration_points` 类型 `int`，该通道连续成线的读数点数；`1` 即一次尖峰。
- `pressure_duration` / `vibration_duration` 类型 `float`，线索持续分钟。
- `pressure_history` / `vibration_history`（或 `history='bearing'|'压力'`）类型 `bool|str`，历史工况是否同因。
- `conflict` 类型 `bool`，读数/修订冲突。
- `missing_channels` 类型 `str|list`（或 `channels={...:None}`），缺失通道。
- `window_remaining` / `recheck_minutes` 类型 `float`，本班剩余窗口与两边复验所需分钟。
- `next_shift_recheck` 类型 `bool|object`，下一班是否具备复查窗口/通道条件。

裁定优先级固定为：读数冲突或通道缺失只能 `JOINT_REVIEW`（联合复核）；未确认告警为 `MONITOR`；一次尖峰不具备主责资格；仅一侧持续成线（默认至少 2 点或持续 10 分钟）时由该侧 `PRIMARY`（主责，压力=制冷压力工、振动=机械振动工）；两侧都持续指向不同故障时，本班窗口够则联合复核，不够且下一班可复查则 `NEXT_SHIFT`（转下一班），下一班不能复查时仍在本班联合复核。输出同时带英文码（`decision`/`reason_code`）、中文去向（`verdict`）、责任工种（`owner`/`trade`）和 `pending_reason`（未决原因）。

分诊单以 `(shift, unit)` 为幂等键。`TriageLedger.save` 中途失败抛出 `TriageSaveError`，此前单据保持 `confirmed` 并记录 `checkpoint`；`recover()` 从检查点之后继续，`rerun()` 与进程重启后的文件台账都不会为同一机组重复生单。可复现样例见 `sample_data/fault_triage_cases.json`（别名 `triage_cases.json`），覆盖压力主责、振动主责、最大偏离是尖峰、读数冲突、通道缺失、本班联合复核、转下一班、下班不可复查、孤立尖峰与历史裁定十一种情形。

## 复查证据

运行结果的 `reconciliation` 保存读数缺档、参考窗漂移计量、不同阈值的触发对比、持续告警起止、停机计划验算及按班组数重试的候选排程。备用设备、区间冲突和工单截止仍由同一现场约束负责。替代排程优先覆盖高分告警，其次比较工单数和累计完成分钟。历史阈值试算保留未查获成本、误检成本与已确认故障召回区间，仅用于有现场结单结果的样本。
