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

## 查看运行结果

- `GET /api/overview` 返回默认运行及其指纹。
- `POST /api/scenario` 接收 `{"capacity": 3}`。入口接受 1–100 的整数，应用样例时使用该业务额度。
- `GET /api/stages/shift_review` 查看该环节的独立证据，支持 `?capacity=3`。

```sh
docker compose exec -T app python -m chillwatch.delivery evaluate --capacity 3
docker compose exec -T app pytest -q
```

数据和模型约定见 [业务契约](docs/SPEC.md)。模块、例外规则与验证入口见 [业务深度](docs/DEPTH.md)。
