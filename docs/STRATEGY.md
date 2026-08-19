# 策略规则（Strategy）

策略引擎位于 `core/material_heat_strategy.py`，核心输入为最新快照 + 上一轮快照（用于计算增量/速率）。

## 阈值体系

所有 ROI 阈值由 **target_roi** 单一参数联动生成（`config_for_target_roi()`）：

| 配置项 | 公式 | target=3.0 时 |
|---|---|---|
| `pause_roi_below` | target − 0.30 | 2.70 |
| `reopen_roi_near_delta` | 0.10 | — |
| `reopen_roi_min` | target − 0.10 | 2.90 |
| `scale_budget_roi_above` | target | 3.00 |
| `pressure_roi_min` | target − 0.30 | 2.70 |
| `raise_roi_above` | target + 0.20 | 3.20 |

固定常量（不随 target 变化）：ROI 有效性门槛 200 元、预算消耗比例 40%/30%/60%、速率 10元/分、停滞 10分钟/5元、增量 1000/2000 元。

## 动作优先级

| 优先级 | 动作 | 触发条件 | 执行内容 |
|---|---|---|---|
| 10 | pause | 调控中、消耗>200、ROI < target−0.30 | batch_update_operation optType=2 |
| 20 | reopen | 已暂停、ROI ≥ target−0.10 | batch_update_operation optType=1 |
| 21 | increase_budget | **任务预算耗尽**（消耗≈预算）、已暂停、ROI 达标 | +1000/+2000 |
| 30 | increase_budget | 调控中、ROI ≥ target、预算消耗达标 | +1000/+2000 |
| 40 | pressure_price | 调控中、target−0.30 < ROI < target、消耗偏快 | 出价−1 / ROI目标+0.05 |
| 50 | raise_price | 调控中、ROI > target+0.20、消耗停滞 | 出价+1 / ROI目标−0.05 |

## 关键判定细节

### 消耗偏快（fast_spend）

```python
fast_spend = cost_rate is not None and cost_rate >= 10.0   # 元/分钟
```

只认**真实速率**（两轮快照消耗差 / 间隔分钟）。不采用"已耗比例 ≥60%"——预算耗尽停投时该比例恒真，会把"花完停住"误判成"消耗偏快"（事故记录见 docs/incidents.md）。

### 预算耗尽 vs 计划组限制（2026-08-14 修复）

已暂停任务触发 reopen 前先区分两个层级：

```python
cost_exhausted = budget > 0 and cost >= budget * 0.995   # 任务级：预算真的花完
group_limited  = "预算" in (delivery_status or "")       # 计划组级：组总预算超限

cost_exhausted → increase_budget（加预算自恢复，reopen 对预算耗尽无效）
group_limited 且 cost < budget → blocked（加任务预算无效，需人工调计划组总预算）
```

### 账户核验（fail-closed）

所有写操作前校验：
1. 当前页面必须是 `qianchuan.jinritemai.com`
2. URL 含 `aavid=<配置的账户ID>`
3. 页面文本含「计划ID：<主计划ID>」

任一不匹配 → 拒绝执行并报告 `account_context_mismatch`。
