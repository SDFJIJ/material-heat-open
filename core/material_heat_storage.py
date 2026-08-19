import json


def last_history_snapshot(history_path):
    if not history_path.exists():
        return None
    try:
        lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None


def append_history(history_path, snapshot, *, keep=500):
    history_path.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        "read_at": snapshot.get("read_at"),
        "summary": snapshot.get("summary"),
        "tasks": snapshot.get("tasks", []),
    }
    existing = []
    if history_path.exists():
        existing = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    existing.append(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    history_path.write_text("\n".join(existing[-keep:]) + "\n", encoding="utf-8")


def apply_execution_state(strategy, *, dry_run, executor):
    actions = strategy.get("actions") or []
    if actions and not dry_run:
        strategy["execution"] = executor(actions)
    elif actions:
        strategy["execution"] = {
            "ok": True,
            "results": [],
            "note": "dry-run mode (QC_DRY_RUN=1) — actions NOT executed; user confirmation required",
        }
    else:
        strategy["execution"] = {"ok": True, "results": [], "note": "no actions needed"}


# c 态检测字段口径：与前端表格列一致
C_STATE_FIELDS = {
    "budget_yuan": "预算",
    "bid_yuan": "出价",
    "roi_goal": "ROI目标",
}


def build_display_overlay(snapshot, strategy, manual_adjustments=None):
    """把三态（a 快照 / b 策略 / c 手动）合并成前端可直接渲染的 overlay。

    返回 {task_id: {field: {"value": x, "source": "snapshot|strategy|manual", "note": "..."}}}。
    优先级：strategy（本轮策略执行，黄）> manual（c 态，蓝）> snapshot（a 态基准）。
    前端只读这个结构，不再自行判断三态。
    """
    overlay = {}
    for t in (snapshot.get("tasks") or []):
        tid = str(t.get("task_id"))
        overlay[tid] = {
            "budget_yuan": {"value": t.get("budget_yuan"), "source": "snapshot", "note": None},
            "bid_yuan": {"value": t.get("bid_yuan"), "source": "snapshot", "note": None},
            "roi_goal": {"value": t.get("roi_goal"), "source": "snapshot", "note": None},
            "control_status": {"value": t.get("control_status"), "source": "snapshot", "note": None},
        }
    # c 态（手动调整，蓝）
    for tid, fields in (manual_adjustments or {}).items():
        if tid not in overlay:
            continue
        for field, rec in fields.items():
            if field not in overlay[tid] or not rec:
                continue
            label = rec.get("label") or field
            overlay[tid][field] = {
                "value": rec.get("new"),
                "source": "manual",
                "note": f"手动调整：{label} {_num_str(rec.get('old'))}→{_num_str(rec.get('new'))}",
            }
    # b 态（本轮策略执行，黄）——最高优先级
    actions = strategy.get("actions") or []
    results = ((strategy.get("execution") or {}).get("results")) or []
    ok_keys = {(r.get("action"), str(r.get("task_id"))) for r in results if r.get("ok")}
    for a in actions:
        if (a.get("action"), str(a.get("task_id"))) not in ok_keys:
            continue
        tid = str(a.get("task_id"))
        if tid not in overlay:
            continue
        if a.get("action") == "increase_budget" and a.get("new_budget_yuan") is not None:
            overlay[tid]["budget_yuan"] = {
                "value": a["new_budget_yuan"],
                "source": "strategy",
                "note": f"策略调整：预算 {_num_str(a.get('old_budget_yuan'))}→{_num_str(a.get('new_budget_yuan'))}",
            }
        elif a.get("action") in ("raise_price", "pressure_price"):
            pc = a.get("preferred_change") or {}
            field = pc.get("field")
            if field in ("bid_yuan", "roi_goal") and pc.get("new") is not None:
                label = C_STATE_FIELDS.get(field, field)
                overlay[tid][field] = {
                    "value": pc["new"],
                    "source": "strategy",
                    "note": f"策略调整：{label} {_num_str(pc.get('old'))}→{_num_str(pc.get('new'))}",
                }
        elif a.get("action") == "pause":
            overlay[tid]["control_status"] = {"value": "已暂停", "source": "strategy", "note": "策略暂停"}
        elif a.get("action") == "reopen":
            overlay[tid]["control_status"] = {"value": "调控中", "source": "strategy", "note": "策略重开"}
    return overlay


def _num_str(v):
    if v is None:
        return "-"
    f = float(v)
    return f"{f:,.0f}" if f >= 100 else f"{f:g}"


def detect_manual_adjustments(prev_snapshot, prev_run, cur_snapshot):
    """c 态检测：比对上一轮策略执行之后的期望值 vs 本轮读取值。

    时序（必须在新的策略执行之前调用）：
        读取 a_cur -> c 检测（a_prev 字段 + 上一轮策略执行 b_prev 的期望值
        与之比对） -> 差异即手动调整 c -> 然后才执行新策略 b。

    返回 {task_id: {field: {"old": x, "new": y, "label": "预算"}}}，
    空 dict = 无手动调整（c 态为空）。新任务无上一轮基准，跳过。
    """
    if not prev_snapshot or not cur_snapshot:
        return {}
    # 上一轮策略执行（b_prev）：从 runs 记录的 execution.results ok 项取写动作
    prev_actions = []
    if prev_run:
        strat = prev_run.get("strategy") or {}
        results = ((strat.get("execution") or {}).get("results")) or []
        actions = strat.get("actions") or []
        ok_keys = {(r.get("action"), str(r.get("task_id"))) for r in results if r.get("ok")}
        for a in actions:
            if (a.get("action"), str(a.get("task_id"))) in ok_keys:
                prev_actions.append(a)
    # 期望值 = a_prev 字段 + b_prev 叠加
    expect = {}
    for t in (prev_snapshot.get("tasks") or []):
        tid = str(t.get("task_id"))
        expect[tid] = {
            "budget_yuan": t.get("budget_yuan"),
            "bid_yuan": t.get("bid_yuan"),
            "roi_goal": t.get("roi_goal"),
        }
    for a in prev_actions:
        tid = str(a.get("task_id"))
        if tid not in expect:
            continue
        if a.get("action") == "increase_budget" and a.get("new_budget_yuan") is not None:
            expect[tid]["budget_yuan"] = a["new_budget_yuan"]
        pc = a.get("preferred_change") or {}
        if pc.get("field") == "bid_yuan" and pc.get("new") is not None:
            expect[tid]["bid_yuan"] = pc["new"]
        elif pc.get("field") == "roi_goal" and pc.get("new") is not None:
            expect[tid]["roi_goal"] = pc["new"]
    # 比对 a_cur vs 期望 → 手动调整 c
    manual = {}
    for t in (cur_snapshot.get("tasks") or []):
        tid = str(t.get("task_id"))
        exp = expect.get(tid)
        if not exp:
            continue
        for field, label in C_STATE_FIELDS.items():
            cur_v = t.get(field)
            exp_v = exp[field]
            if cur_v is None or exp_v is None:
                continue
            if abs(float(cur_v) - float(exp_v)) > 0.001:
                manual.setdefault(tid, {})[field] = {"old": exp_v, "new": cur_v, "label": label}
    return manual


def save_snapshot(data, *, out_path, strategy_path, history_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    strategy_path.write_text(json.dumps(data["strategy"], ensure_ascii=False, indent=2), encoding="utf-8")
    append_history(history_path, data)


def append_run_log(run_log_path, snapshot, *, keep=1000):
    """Append one per-run record (summary + strategy actions/execution).

    Kept separate from append_history so the existing history file format
    stays stable; consumers that only read history are unaffected when the
    run-log schema evolves.
    """
    run_log_path.parent.mkdir(parents=True, exist_ok=True)
    strategy = snapshot.get("strategy") or {}
    record = {
        "schema": "qianchuan.material_heat.run_log.v1",
        "read_at": snapshot.get("read_at"),
        "summary": snapshot.get("summary"),
        "strategy": {
            "actions": strategy.get("actions", []),
            "blocked": strategy.get("blocked", []),
            "execution": strategy.get("execution"),
        },
    }
    existing = []
    if run_log_path.exists():
        existing = [line for line in run_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    existing.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    run_log_path.write_text("\n".join(existing[-keep:]) + "\n", encoding="utf-8")


def _brief_plan(task):
    metrics = task.get("metrics") or {}
    operations = task.get("operations") or {}
    material = task.get("material") or {}
    return {
        "task_id": task.get("task_id"),
        "task_name": task.get("task_name"),
        "created_at": task.get("created_at"),
        "material": {"type": material.get("type"), "count": material.get("count"), "text": material.get("text")},
        "control_status": task.get("control_status"),
        "delivery_status": task.get("delivery_status"),
        "smart_bid_type": task.get("smart_bid_type"),
        "smart_bid_name": task.get("smart_bid_name"),
        "budget_yuan": task.get("budget_yuan"),
        "bid_yuan": task.get("bid_yuan"),
        "roi_goal": task.get("roi_goal"),
        "metrics": {
            "cost_yuan": metrics.get("cost_yuan"),
            "pay_roi": metrics.get("pay_roi"),
            "pay_order_count": metrics.get("pay_order_count"),
            "pay_gmv_yuan": metrics.get("pay_gmv_yuan"),
            "net_roi": metrics.get("net_roi"),
        },
        "operations": {
            "can_pause": operations.get("can_pause"),
            "can_start": operations.get("can_start"),
            "can_edit": operations.get("can_edit"),
        },
    }


def build_brief(data, strategy_path, out_path):
    tasks = data.get("tasks", [])
    return {
        "schema": data.get("schema"),
        "read_at": data.get("read_at"),
        "latency_ms": data.get("latency_ms"),
        "account": data.get("account"),
        "primary_ad": data.get("primary_ad"),
        "account_context": data.get("account_context"),
        "summary": data.get("summary"),
        "summary_text": data.get("summary_text"),
        "strategy": {
            "schema": data.get("strategy", {}).get("schema"),
            "actions_count": len(data.get("strategy", {}).get("actions", [])),
            "top_actions": data.get("strategy", {}).get("actions", [])[:8],
            "blocked": data.get("strategy", {}).get("blocked", []),
            "execution": data.get("strategy", {}).get("execution"),
            "saved_to": str(strategy_path),
        },
        "plans": [_brief_plan(task) for task in tasks],
        "saved_to": str(out_path),
    }
