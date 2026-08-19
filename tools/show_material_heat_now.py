"""一键查看千川素材追投当前情况。

用法：
    python C:/Users/fmy/qcqianchuan/scripts/show_material_heat_now.py

要求：
- 千川专用 Chrome/CDP 已启动：127.0.0.1:9223
- Chrome 里已登录 qianchuan.jinritemai.com
- browser-harness 可用

安全：强制 QC_DRY_RUN=1，只读，不会暂停/重开/调价/改预算。
"""

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(r"C:\Users\fmy\qcqianchuan")
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from qianchuan_chrome import ensure_chrome_9223

CDP_SCRIPT = SCRIPTS_DIR / "read_material_heat_realtime.cdp.py"
BH_CANDIDATES = [
    os.environ.get("BROWSER_HARNESS", ""),
    str(pathlib.Path.home() / ".local/bin/browser-harness"),
    "browser-harness",
]


def find_browser_harness():
    for candidate in BH_CANDIDATES:
        if not candidate:
            continue
        if candidate == "browser-harness" or pathlib.Path(candidate).exists():
            return candidate
    return "browser-harness"


def fmt_money(value):
    if value is None:
        return "-"
    try:
        return f"¥{float(value):,.0f}"
    except Exception:
        return str(value)


def fmt_roi(value):
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)


def main():
    env = os.environ.copy()
    env["BU_CDP_URL"] = env.get("BU_CDP_URL", "http://127.0.0.1:9223")
    env["QC_DRY_RUN"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    if not CDP_SCRIPT.exists():
        print(f"脚本不存在：{CDP_SCRIPT}", file=sys.stderr)
        return 2

    chrome_ok, chrome_msg = ensure_chrome_9223(env["BU_CDP_URL"])
    if not chrome_ok:
        print(f"❌ 读取失败：{chrome_msg}", file=sys.stderr)
        return 1

    # Pass bytes to browser-harness. This avoids Windows console/text-mode
    # recoding turning non-ASCII source into surrogate characters.
    result = subprocess.run(
        [find_browser_harness()],
        input=CDP_SCRIPT.read_bytes(),
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=False,
        timeout=180,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    if result.returncode != 0:
        print("❌ 读取失败：browser-harness/CDP/登录可能有问题", file=sys.stderr)
        if stderr:
            print(stderr[-2000:], file=sys.stderr)
        return result.returncode

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        print(stdout)
        return 0

    summary = data.get("summary") or {}
    strategy = data.get("strategy") or {}
    tasks = data.get("top_tasks_by_cost") or []

    print(f"千川素材追投实时状态｜{data.get('read_at', '-')}")
    print(
        "汇总："
        f"消耗{fmt_money(summary.get('cost_yuan'))} "
        f"ROI {fmt_roi(summary.get('pay_roi'))} "
        f"净ROI {fmt_roi(summary.get('net_roi'))} "
        f"订单 {summary.get('pay_order_count', '-')} "
        f"GMV {fmt_money(summary.get('pay_gmv_yuan'))} "
        f"调控中/暂停 {summary.get('controlling_count', '-')}/{summary.get('paused_count', '-')}"
    )

    execution = strategy.get("execution") or {}
    print(f"建议动作：{strategy.get('actions_count', 0)}；执行状态：{execution.get('note', '-')}")

    if strategy.get("top_actions"):
        print("\n待确认动作：")
        for action in strategy["top_actions"]:
            metrics = action.get("metrics") or {}
            print(
                f"- {action.get('action')}｜{action.get('task_name')}｜"
                f"消耗{fmt_money(metrics.get('cost_yuan'))} ROI {fmt_roi(metrics.get('pay_roi'))}｜"
                f"{action.get('reason', '')}"
            )

    print("\n按消耗排序 Top 5：")
    for task in tasks:
        print(
            f"- {task.get('control_status')}｜{task.get('task_name')}｜"
            f"消耗{fmt_money(task.get('cost_yuan'))} ROI {fmt_roi(task.get('pay_roi'))} "
            f"订单 {task.get('pay_order_count', '-')} GMV {fmt_money(task.get('pay_gmv_yuan'))}"
        )

    print(f"\n完整JSON：{ROOT / 'data' / 'material_heat_realtime_latest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
