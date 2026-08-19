# 事故与修复记录（Incidents）

## 1. 收盘后 watchdog 自动 reopen 已暂停任务（2026-08-06）

**症状**：18:40 主计划关闭后，watchdog 每 20 分钟仍巡检，策略看到"任务已暂停 + ROI 回到目标附近"就自动 reopen，一轮 6 个 reopen 全部成功——把本应收工的追投任务重新开启。

**修复**：收盘时间规则（默认 18:40）：
- ≥18:40 且当天未标记 → 强制 dry-run 读取最后一轮落盘，写收盘标记，静默退出
- ≥18:40 且已标记 → 当天直接静默跳过
- 次日自动恢复

## 2. 预算耗尽停投被误判为普通暂停 → reopen（2026-08-14）

**症状**：任务预算 1000 花完停投（delivery_status="计划组超出预算"），策略连续 12 轮建议 reopen。任务预算已加到 2000 后仍持续建议 2000→3000（盲目 +1000 链）。

**根因**：reopen 判断只看 `control_status=="已暂停"`，未区分"任务预算耗尽"（应加预算自恢复）与"普通暂停"（应 reopen）。且预算耗尽分支用 `delivery_status 含"预算"` 作为触发，未检查任务预算是否真的不够。

**修复**：区分两个层级：
- `cost >= budget*0.995`（任务级耗尽）→ increase_budget
- `delivery 含"预算" 但 cost < budget`（组级限制）→ blocked，提示人工调计划组总预算

## 3. fast_spend 误判（2026-08-15）

**症状**：已耗 99% 但速率 0 的任务（预算耗尽停住）被连续判"消耗偏快"→ pressure_price。

**根因**：`fast_spend = spent_ratio >= 0.60 OR cost_rate >= 10`，"已耗比例"这一支在预算耗尽时恒真。

**修复**：只认真实速率 `cost_rate >= 10`（两轮快照消耗差/分钟）。用户原则：**无论消耗多快，ROI 稳定高于标准就无需调整出价**。

## 4. cron 脚本用 .sh 在 Windows 下 exit 127（2026-08-15）

**症状**：cron `script=daily_reset_material_heat.sh` 每次运行 exit 127。

**根因**：Hermes cron 调度器对 `.sh/.bash` 用 `subprocess.run([bash, str(path)])`，Windows 路径 `C:\Users\...` 的反斜杠被 bash 当转义符吞掉（`C:Usersfmy...`）→ 文件不存在。

**修复**：cron 脚本一律用 `.py`（Python 执行路径正常），`.sh` 只用于手动运行。**教训：cron script 字段不要用 .sh。**
