from datetime import datetime

DEFAULT_TARGET_ROI = 3.30


def config_for_target_roi(target_roi=DEFAULT_TARGET_ROI, overrides=None):
    """Build strategy thresholds from a single target ROI.

    The strategy target controls the budget gate directly: a task may scale
    budget once its pay ROI reaches target_roi and the spend-ratio gate is met.
    Other controls retain their relative deltas around target_roi.
    """
    target_roi = float(target_roi)
    config = {
        "target_roi": target_roi,
        "valid_roi_min_cost_yuan": 200.0,
        "pause_roi_below": round(target_roi - 0.30, 2),
        "reopen_roi_near_delta": 0.10,
        "scale_budget_roi_above": round(target_roi, 2),
        "scale_budget_initial_spend_ratio": 0.40,
        "scale_budget_later_remaining_ratio_min": 0.30,
        "scale_budget_small_increment_yuan": 1000.0,
        "scale_budget_large_threshold_yuan": 4000.0,
        "scale_budget_large_increment_yuan": 2000.0,
        "pressure_roi_min": round(target_roi - 0.30, 2),
        "raise_roi_above": round(target_roi + 0.20, 2),
        "pressure_bid_step_yuan": 1.0,
        "pressure_roi_goal_step": 0.05,
        "fast_spend_ratio": 0.60,
        "fast_spend_rate_yuan_per_min": 10.0,
        "stuck_min_minutes": 10.0,
        "stuck_cost_delta_yuan": 5.0,
    }
    if overrides:
        config.update(overrides)
    return config


STRATEGY_CONFIG = config_for_target_roi()


def _num(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_read_at(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _change_options(task, pacing, config):
    """Return mode-aware adjustments for fast or stuck spend."""
    options = []
    bid = task.get("bid_yuan")
    roi_goal = task.get("roi_goal")
    if pacing not in ("fast", "slow"):
        raise ValueError(f"unsupported pacing: {pacing}")
    if bid is not None:
        step = config["pressure_bid_step_yuan"]
        bid_delta = -step if pacing == "fast" else step
        new_bid = max(0.1, _num(bid) + bid_delta)
        options.append({
            "field": "bid_yuan",
            "old": round(_num(bid), 2),
            "new": round(new_bid, 2),
            "delta": round(new_bid - _num(bid), 2),
            "write_endpoint": "POST /ad/api/pmc/v1/uni-promotion/ad/update-uni-prom-assist-task",
        })
    if roi_goal is not None:
        step = config["pressure_roi_goal_step"]
        roi_delta = step if pacing == "fast" else -step
        new_goal = max(0.1, _num(roi_goal) + roi_delta)
        options.append({
            "field": "roi_goal",
            "old": round(_num(roi_goal), 2),
            "new": round(new_goal, 2),
            "delta": round(new_goal - _num(roi_goal), 2),
            "write_endpoint": "POST /ad/api/pmc/v1/uni-promotion/ad/update-uni-prom-assist-task",
        })
    return options


def build_strategy(snapshot, previous_snapshot=None, config=None, *, dry_run=True):
    """Build MaterialHeat actions and diagnostics from a realtime snapshot."""
    config = dict(config or STRATEGY_CONFIG)
    target_roi = config["target_roi"]
    reopen_roi_min = target_roi - config["reopen_roi_near_delta"]
    prev_tasks = {t.get("task_id"): t for t in (previous_snapshot or {}).get("tasks", [])}
    now_dt = _parse_read_at(snapshot.get("read_at"))
    prev_dt = _parse_read_at((previous_snapshot or {}).get("read_at"))
    minutes = None
    if now_dt and prev_dt:
        minutes = max((now_dt - prev_dt).total_seconds() / 60.0, 0.0)

    actions = []
    task_scores = []
    blocked = []

    def add_action(priority, action, task, reason, **kwargs):
        record = {
            "priority": priority,
            "action": action,
            "task_id": task.get("task_id"),
            "task_name": task.get("task_name"),
            "reason": reason,
            "requires_confirmation": dry_run,
            "dry_run": dry_run,
        }
        record.update(kwargs)
        actions.append(record)

    for task in snapshot.get("tasks", []):
        metrics = task.get("metrics") or {}
        ops = task.get("operations") or {}
        cost = _num(metrics.get("cost_yuan"))
        roi = _num(metrics.get("pay_roi"))
        orders = _num(metrics.get("pay_order_count"))
        budget = _num(task.get("budget_yuan"))
        spent_ratio = cost / budget if budget > 0 else 0.0
        remaining_ratio = max(0.0, 1.0 - spent_ratio) if budget > 0 else None
        prev = prev_tasks.get(task.get("task_id")) or {}
        prev_cost = _num(((prev.get("metrics") or {}).get("cost_yuan")), None)
        cost_delta = None
        cost_rate = None
        if prev_cost is not None and minutes and minutes > 0:
            cost_delta = cost - prev_cost
            cost_rate = cost_delta / minutes

        valid_roi = cost > config["valid_roi_min_cost_yuan"]
        running = task.get("control_status") == "调控中"
        paused = task.get("control_status") == "已暂停"
        fast_spend = spent_ratio >= config["fast_spend_ratio"] or (
            cost_rate is not None and cost_rate >= config["fast_spend_rate_yuan_per_min"]
        )
        stuck = bool(
            minutes
            and minutes >= config["stuck_min_minutes"]
            and cost_delta is not None
            and cost_delta <= config["stuck_cost_delta_yuan"]
        )

        task_scores.append({
            "task_id": task.get("task_id"),
            "task_name": task.get("task_name"),
            "control_status": task.get("control_status"),
            "cost_yuan": round(cost, 2),
            "budget_yuan": round(budget, 2) if budget else budget,
            "spent_ratio": round(spent_ratio, 4) if budget else None,
            "remaining_ratio": round(remaining_ratio, 4) if remaining_ratio is not None else None,
            "pay_roi": round(roi, 4),
            "orders": orders,
            "valid_roi": valid_roi,
            "cost_delta_yuan": round(cost_delta, 2) if cost_delta is not None else None,
            "cost_rate_yuan_per_min": round(cost_rate, 2) if cost_rate is not None else None,
            "fast_spend": fast_spend,
            "stuck": stuck,
        })

        if running and valid_roi and roi < config["pause_roi_below"]:
            if ops.get("can_pause"):
                add_action(
                    10,
                    "pause",
                    task,
                    f"消耗 {cost:.2f} > {config['valid_roi_min_cost_yuan']:.0f}，ROI {roi:.2f} < {config['pause_roi_below']:.2f}，命中暂停阈值，建议人工确认",
                    write_hint={"endpoint": "POST /ad/api/pmc/v1/batch_update_operation", "optType": 2},
                    metrics={"cost_yuan": cost, "pay_roi": roi, "orders": orders},
                )
            else:
                blocked.append({"task_id": task.get("task_id"), "action": "pause", "reason": "命中暂停规则但接口/页面标记不可暂停"})
            continue

        if paused and roi >= reopen_roi_min:
            # 预算耗尽停投 ≠ 普通暂停。但必须区分两个层级：
            #   任务级耗尽：cost >= budget*0.995 → 加任务预算（合理，+1000/+2000）
            #   仅组级限制：delivery 含"预算" 但 cost < budget → 任务预算够，卡在计划组
            #             总预算 → 加任务预算无效，提示人工处理，不重复加
            cost_exhausted = budget > 0 and cost >= budget * 0.995
            group_limited = "预算" in (task.get("delivery_status") or "")
            if cost_exhausted:
                if ops.get("can_edit"):
                    increment = config["scale_budget_large_increment_yuan"] if budget > config["scale_budget_large_threshold_yuan"] else config["scale_budget_small_increment_yuan"]
                    add_action(
                        21,
                        "increase_budget",
                        task,
                        f"任务预算耗尽停投（消耗 {cost:.2f} ≈ 预算 {budget:.2f}）且 ROI {roi:.2f} 已回到目标 {target_roi:.2f} 附近；加预算自恢复而非 reopen",
                        old_budget_yuan=round(budget, 2),
                        new_budget_yuan=round(budget + increment, 2),
                        increment_yuan=round(increment, 2),
                        write_hint={"endpoint": "POST /ad/api/pmc/v1/batch_update_budget", "field": "Budget"},
                        metrics={"cost_yuan": cost, "pay_roi": roi, "orders": orders},
                    )
                else:
                    blocked.append({"task_id": task.get("task_id"), "action": "increase_budget", "reason": "任务预算耗尽命中加预算规则但接口/页面标记不可编辑"})
                continue
            if group_limited:
                # 任务预算未耗尽但计划组超出预算：加任务预算无效，须人工调计划组总预算
                blocked.append({"task_id": task.get("task_id"), "action": "increase_budget", "reason": f"计划组级预算限制（delivery_status={task.get('delivery_status')}）但任务预算未耗尽（消耗 {cost:.2f} < 预算 {budget:.2f}）；需人工调整计划组总预算"})
                continue
            if ops.get("can_start"):
                add_action(
                    20,
                    "reopen",
                    task,
                    f"已暂停后考虑延迟成交回流；ROI {roi:.2f} 已回到目标 {target_roi:.2f} 附近（>= {reopen_roi_min:.2f}）",
                    write_hint={"endpoint": "POST /ad/api/pmc/v1/batch_update_operation", "optType": 1},
                    metrics={"cost_yuan": cost, "pay_roi": roi, "orders": orders},
                )
            else:
                blocked.append({"task_id": task.get("task_id"), "action": "reopen", "reason": "命中重开规则但接口/页面标记不可开启"})
            continue

        if running and valid_roi and roi >= config["scale_budget_roi_above"] and budget > 0:
            if (budget <= 1000 and spent_ratio >= config["scale_budget_initial_spend_ratio"]) or (
                budget > 1000 and remaining_ratio is not None and remaining_ratio <= config["scale_budget_later_remaining_ratio_min"]
            ):
                increment = config["scale_budget_large_increment_yuan"] if budget > config["scale_budget_large_threshold_yuan"] else config["scale_budget_small_increment_yuan"]
                if ops.get("can_edit"):
                    add_action(
                        30,
                        "increase_budget",
                        task,
                        f"ROI {roi:.2f} >= {config['scale_budget_roi_above']:.2f} 且预算已消耗 {spent_ratio:.0%}，需要保持至少 30% 预算空间",
                        old_budget_yuan=round(budget, 2),
                        new_budget_yuan=round(budget + increment, 2),
                        increment_yuan=round(increment, 2),
                        write_hint={"endpoint": "POST /ad/api/pmc/v1/uni-promotion/ad/update-uni-prom-assist-task", "field": "Budget"},
                        metrics={"cost_yuan": cost, "pay_roi": roi, "orders": orders},
                    )
                else:
                    blocked.append({"task_id": task.get("task_id"), "action": "increase_budget", "reason": "命中加预算规则但接口/页面标记不可编辑"})

        if running and valid_roi and config["pressure_roi_min"] < roi < target_roi and fast_spend:
            options = _change_options(task, "fast", config)
            rate_text = "-" if cost_rate is None else f"{cost_rate:.2f}/min"
            if ops.get("can_edit") and options:
                add_action(
                    40,
                    "pressure_price",
                    task,
                    f"预算消耗偏快（已消耗 {spent_ratio:.0%}，速率 {rate_text} 若有历史）且 ROI {roi:.2f} > {config['pressure_roi_min']:.2f} 但低于目标 {target_roi:.2f}；出价模式降出价，ROI 目标模式抬目标",
                    preferred_change=options[0],
                    change_options=options,
                    metrics={"cost_yuan": cost, "pay_roi": roi, "orders": orders},
                )
            elif not options:
                blocked.append({"task_id": task.get("task_id"), "action": "pressure_price", "reason": "命中压价规则但没有可识别出价或 ROI 目标字段"})

        if running and valid_roi and roi > config["raise_roi_above"] and stuck:
            options = _change_options(task, "slow", config)
            if ops.get("can_edit") and options:
                add_action(
                    50,
                    "raise_price",
                    task,
                    f"消耗在 {minutes:.0f} 分钟内基本不动（+{cost_delta:.2f}），但 ROI {roi:.2f} > {config['raise_roi_above']:.2f}；出价模式抬出价，ROI 目标模式降目标",
                    preferred_change=options[0],
                    change_options=options,
                    metrics={"cost_yuan": cost, "pay_roi": roi, "orders": orders},
                )
            elif not options:
                blocked.append({"task_id": task.get("task_id"), "action": "raise_price", "reason": "命中慢消耗规则但没有可识别出价或 ROI 目标字段"})

    actions.sort(key=lambda x: (x["priority"], x.get("task_id") or ""))
    return {
        "schema": "qianchuan.material_heat.strategy.v1",
        "config": config,
        "baseline": {
            "previous_read_at": (previous_snapshot or {}).get("read_at"),
            "current_read_at": snapshot.get("read_at"),
            "delta_minutes": round(minutes, 2) if minutes is not None else None,
            "roi_field": "pay_roi",
        },
        "policy_notes": [
            "暂停需要消耗 >200 元（前 200 元 ROI 波动大，不轻易停）；重开不需要，已暂停任务 ROI 就是回流数据。",
            "暂停后允许成交/消耗延迟回流；已暂停任务 ROI 回到目标 -0.1 附近时自动重开（不需要等消耗过 200）。",
            "默认 dry-run；只有显式关闭 dry-run 时才执行写操作。",
            "快消耗：出价 -1 元；ROI 目标 +0.05。慢消耗：出价 +1 元；ROI 目标 -0.05。",
        ],
        "actions": actions,
        "blocked": blocked,
        "task_scores": task_scores,
    }
