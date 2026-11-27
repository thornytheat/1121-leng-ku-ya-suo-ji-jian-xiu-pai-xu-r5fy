# 冷库压缩机检修排序

面向冷库机务的本地工作台。内置业务样例覆盖冷库轮班点检、稳健异常评分与检修排程。样例采用确定性构造，适合复现实验和核查边界行为。

## 启动

```sh
docker compose up --build -d
```

打开 `http://127.0.0.1:18200/` 查看待检修设备。左侧六个入口可展开运行证据。调整「检修工位（个）」，点击「重排检修」比较处置结果。结束后执行 `docker compose down --remove-orphans`。

## 独立业务模块

- 交接读数 `shift_meter`
- 历史工况 `duty_reference`
- 稳健异常 `robust_alarm`
- 持续告警 `persistence_filter`
- 停机排程 `maintenance_slots`
- 班次复盘 `shift_review`
- 故障分诊 `fault_triage`：已确认告警 → 主责 / 联合复核 / 转下一班，带保存恢复与幂等台账

## 故障分诊交班

工作台底部「故障分诊交班」逐台给出去向、责任工种、压力/振动线索、持续与历史依据以及未决原因。一次尖峰不会成为主责；读数冲突或通道缺失只会进入联合复核。可点击「模拟保存失败」复现第 3 张分诊单中断，再「从已确认分诊处恢复」，或「重跑」验证不会重复生单。

- `GET /api/triage` 返回分诊记录与台账状态；`GET /api/stages/fault_triage` 返回同一环节证据。
- `POST /api/triage/save`、`/api/triage/recover`、`/api/triage/rerun`、`/api/triage/reset` 驱动保存/恢复/幂等重跑；保存中断返回 `TRIAGE_SAVE_FAILED` 与已确认检查点。
- 可复现样例：`sample_data/fault_triage_cases.json`。

## 查看运行结果

- `GET /api/overview` 返回默认运行及其指纹。
- `POST /api/scenario` 接收 `{"capacity": 3}`。入口接受 1–100 的整数，应用样例时使用该业务额度。
- `GET /api/stages/shift_review` 查看该环节的独立证据，支持 `?capacity=3`。

```sh
docker compose exec -T app python -m chillwatch.delivery evaluate --capacity 3
docker compose exec -T app pytest -q
```

数据和模型约定见 [业务契约](docs/SPEC.md)。模块、例外规则与验证入口见 [业务深度](docs/DEPTH.md)。
