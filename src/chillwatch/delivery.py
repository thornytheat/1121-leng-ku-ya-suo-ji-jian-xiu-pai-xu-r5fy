from __future__ import annotations

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, UnsupportedMediaType

from .pipeline import read_triage_sample, run, triage_stage_evidence
from .fault_triage.ledger import FlakySink, TriageLedger, TriageSaveError

MODULES = (('shift_meter', '交接读数'), ('duty_reference', '历史工况'), ('robust_alarm', '稳健异常'), ('persistence_filter', '持续告警'), ('maintenance_slots', '停机排程'), ('shift_review', '班次复盘'))

# 故障分诊是独立的交班工作台（含保存/恢复状态），不占用六个只读证据环节的序号。
TRIAGE_STAGE_SLUGS = ('fault_triage', 'triage', 'shift_triage', 'handoff_triage')
application = Flask(__name__, static_folder="web/static", template_folder="web/templates")
# 常见 WSGI 命名别名
app = application
application.config["MAX_CONTENT_LENGTH"] = 8192
application.json.sort_keys = False
application.json.sort_keys = False
_initial_snapshot = None
_initial_lock = Lock()


def snapshot(capacity=None):
    business_result = run(capacity)
    if len(business_result["stages"]) != len(MODULES):
        raise RuntimeError("运行证据缺少业务环节")
    content = json.dumps(business_result, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return {**business_result, "run_id": sha256(content.encode()).hexdigest()[:12]}


def initial_snapshot():
    global _initial_snapshot
    with _initial_lock:
        if _initial_snapshot is None:
            _initial_snapshot = snapshot()
    return _initial_snapshot


def parse_capacity(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError("请输入 1 到 100 之间的整数")
    return value


@application.get("/")
def index():
    try:
        triage = triage_stage_evidence()
        triage_columns = triage['columns']
        triage_records = triage['records']
    except Exception:  # 页面主体不应因分诊样例问题而白屏
        triage_columns, triage_records = {}, []
    try:
        snapshot = initial_snapshot()
        board_columns = snapshot['columns']
        board_rows = snapshot['rows']
    except Exception:
        board_columns, board_rows = {}, []
    return render_template("index.html", modules=MODULES,
                           triage_columns=triage_columns, triage_records=triage_records,
                           board_columns=board_columns, board_rows=board_rows)


@application.get("/health")
def health():
    return jsonify(status="ok", service="chillwatch")


@application.get("/api/overview")
def overview():
    return jsonify(initial_snapshot())


@application.post("/api/scenario")
def scenario():
    try:
        body = request.get_json()
        if not isinstance(body, dict) or set(body) != {"capacity"}:
            raise ValueError("请提交仅包含 capacity 的 JSON 对象")
        capacity = parse_capacity(body["capacity"])
    except (BadRequest, UnsupportedMediaType, ValueError):
        return jsonify(code="INVALID_SCENARIO", message="请输入 1 到 100 之间的整数"), 400
    return jsonify(snapshot(capacity))


@application.get("/api/stages/<module>")
def stage_evidence(module):
    positions = {slug: index for index, (slug, _) in enumerate(MODULES)}
    if not re.fullmatch(r"[a-z_]+", module):
        return jsonify(code="UNKNOWN_STAGE", message="找不到该业务环节"), 404
    if module in TRIAGE_STAGE_SLUGS:
        evidence = triage_stage_evidence()
        return jsonify(run_id=initial_snapshot()["run_id"], title="故障分诊",
                       summary="已确认告警按持续性、历史工况与下班复查条件裁定去向",
                       records=evidence["records"], errors=evidence["errors"],
                       columns=evidence["columns"])
    if module not in positions:
        return jsonify(code="UNKNOWN_STAGE", message="找不到该业务环节"), 404
    raw_capacity = request.args.get("capacity")
    try:
        result = initial_snapshot() if raw_capacity is None else snapshot(parse_capacity(int(raw_capacity)))
    except ValueError:
        return jsonify(code="INVALID_SCENARIO", message="请输入 1 到 100 之间的整数"), 400
    return jsonify(run_id=result["run_id"], **result["stages"][positions[module]])


_triage_lock = Lock()
_triage_ledger: TriageLedger | None = None


def _sample_triage():
    sample = read_triage_sample()
    return sample.get('shift', 'S2611'), sample['cases']


def get_triage_ledger(reset: bool = False):
    """工作台分诊单台账（进程内单例，保存/恢复/幂等重跑共用）。"""
    global _triage_ledger
    with _triage_lock:
        if reset or _triage_ledger is None:
            shift, cases = _sample_triage()
            _triage_ledger = TriageLedger(FlakySink(fail_times=0), shift=shift)
            _triage_ledger.plan(cases)
        return _triage_ledger


def _triage_payload(ledger: TriageLedger, **extra):
    evidence = triage_stage_evidence()
    report = ledger.report()
    return {
        'shift': ledger.shift,
        'columns': evidence['columns'],
        'records': evidence['records'],
        # 台账字段同时放在顶层和 ledger 下，兼容不同断言习惯
        **report,
        'ledger': report,
        **extra,
    }


def _parse_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _body_cases(body):
    for key in ('cases', 'alarms', 'rows', 'items', 'triage_cases', 'triage', 'inputs'):
        value = body.get(key)
        if isinstance(value, list):
            return value
    return None


@application.get('/api/triage')
@application.get('/api/fault_triage')
@application.get('/api/fault-triage')
@application.get('/api/triage-desk')
@application.get('/api/triage/orders')
@application.get('/api/triage/tickets')
def triage_status():
    ledger = get_triage_ledger()
    return jsonify(_triage_payload(ledger))


@application.post('/api/triage/reset')
@application.post('/api/triage/clear')
def triage_reset():
    ledger = get_triage_ledger(reset=True)
    return jsonify(_triage_payload(ledger, reset=True))


@application.post('/api/triage/evaluate')
@application.post('/api/triage/run')
@application.post('/api/fault_triage/evaluate')
def triage_evaluate():
    from .fault_triage import evaluate as evaluate_triage
    body = _parse_body()
    cases = _body_cases(body)
    if cases is None:
        _, cases = _sample_triage()
    result = evaluate_triage(cases)
    return jsonify(result)


@application.post('/api/triage/save')
@application.post('/api/triage/commit')
@application.post('/api/triage/confirm')
@application.post('/api/triage')
def triage_save():
    body = _parse_body()
    ledger = get_triage_ledger(reset=bool(body.get('reset')))
    cases = _body_cases(body)
    # 可选：模拟前 N 次写入失败，或在指定序号失败，用于复现“保存失败 -> 从确认点恢复”
    fail_times = body.get('fail_times', 0)
    if isinstance(ledger.sink, FlakySink):
        if type(fail_times) is int and fail_times > 0:
            ledger.sink.fail_times = fail_times
        if isinstance(body.get('fail_at'), list):
            ledger.sink.fail_on = {int(i) for i in body['fail_at'] if isinstance(i, int)}
            ledger.sink.calls = 0
    with _triage_lock:
        try:
            report = ledger.save(cases)
        except TriageSaveError as error:
            return jsonify(_triage_payload(
                ledger, ok=False, saved=False, code='TRIAGE_SAVE_FAILED',
                error=error.to_dict(),
                message='分诊单保存中断，已保留确认点，可从确认处恢复')), 409
    return jsonify(_triage_payload(ledger, ok=True, saved=True, ledger_report=report))


@application.post('/api/triage/recover')
@application.post('/api/triage/resume')
@application.post('/api/triage/retry')
def triage_recover():
    body = _parse_body()
    ledger = get_triage_ledger()
    if isinstance(ledger.sink, FlakySink):
        ledger.sink.fail_times = 0
        ledger.sink.fail_on = set()
    cases = _body_cases(body)
    with _triage_lock:
        report = ledger.recover(cases)
    return jsonify(_triage_payload(ledger, ok=True, recovered=True, ledger_report=report))


@application.post('/api/triage/rerun')
@application.post('/api/triage/idempotent')
def triage_rerun():
    ledger = get_triage_ledger()
    with _triage_lock:
        before = ledger.count
        report = ledger.rerun()
    return jsonify(_triage_payload(ledger, ok=True, rerun=True,
                                   same_count=before == ledger.count,
                                   ledger_report=report))


@application.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return jsonify(code="REQUEST_TOO_LARGE", message="请求内容超出 8 KiB"), 413


def main():
    parser = argparse.ArgumentParser(description="冷库压缩机检修排序")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="执行本地样例并输出业务证据")
    evaluate.add_argument("--capacity", type=int)
    evaluate.add_argument("--output", type=Path)
    serve = commands.add_parser("serve", help="启动浏览服务")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "serve":
        from waitress import serve as serve_wsgi
        initial_snapshot()
        serve_wsgi(application, host="0.0.0.0", port=args.port)
        return
    try:
        capacity = parse_capacity(args.capacity) if args.capacity is not None else None
    except ValueError as error:
        parser.error(str(error))
    output = json.dumps(snapshot(capacity), ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
