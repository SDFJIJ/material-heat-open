"""千川追投自动暂停 watchdog — 只在触发暂停 action 时输出消息（Python版，避免bash路径截断）。
用作 cron no_agent=True 脚本：空输出=静默，有输出=推飞书。
"""
import json, os, pathlib, subprocess, sys
from datetime import datetime

PROJECT_ROOT = pathlib.Path(r"C:\Users\fmy\qcqianchuan")
PROJECT_SCRIPTS = PROJECT_ROOT / "scripts"
if str(PROJECT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PROJECT_SCRIPTS))

from qianchuan_chrome import ensure_chrome_9223
from qianchuan_account_context import load_account_context

CDP_SCRIPT = PROJECT_SCRIPTS / "read_material_heat_realtime.cdp.py"

_HOME = pathlib.Path.home()
_BH_CANDIDATES = [
    os.environ.get("BROWSER_HARNESS", ""),
    str(_HOME / ".local/bin/browser-harness"),
    "browser-harness",
]
BH = None
for c in _BH_CANDIDATES:
    if c and (pathlib.Path(c).exists() or c == "browser-harness"):
        BH = c
        break
if not BH:
    BH = str(_HOME / ".local/bin/browser-harness")
# Scheduled automation follows config.active_account; do not inherit a stale
# interactive QC_ACCOUNT override from the Hermes/terminal environment.
os.environ.pop("QC_ACCOUNT", None)
ACCOUNT = load_account_context()
# Preserve a deliberate caller override.  Otherwise let qianchuan_chrome probe
# every configured endpoint (IPv6 and IPv4) and export the one that is alive.
CDP_OVERRIDE = os.environ.get("BU_CDP_URL")
STRATEGY_JSON = ACCOUNT.data_dir / "material_heat_strategy_latest.json"
LOG_DIR = pathlib.Path(r"C:\Users\fmy\qcqianchuan\logs")
RUN_LOG = LOG_DIR / "qianchuan_pause_watchdog.jsonl"


def write_audit(payload):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **payload}
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

# Auto-execution watchdog: user explicitly asked to turn on automatic pause.
# QC_WATCHDOG_DRY_RUN=1 is a manual smoke-test override only; cron does not
# set it, so scheduled runs continue to execute pause writes.
os.environ["QC_DRY_RUN"] = "1" if os.environ.get("QC_WATCHDOG_DRY_RUN") == "1" else "0"
os.environ.setdefault("QC_TARGET_ROI", "3.0")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 0. 收盘时间规则（用户 2026-08-06 确认）：每天 18:40 主计划关闭，追投连带全部暂停。
#    超过收盘时间后：只读取最后一轮数据（保存当天最终快照/运行记录），不执行任何写操作，
#    读取完成后当天不再继续运行（后续轮次静默退出）。
#    - 当天未收盘：正常巡检/自动执行
#    - 当天已收盘读取过：静默退出（不跑 CDP、不写、不通知）
CLOSE_HHMM = os.environ.get("QC_CLOSE_TIME", "18:40")
CLOSE_STATE = ACCOUNT.data_dir / "close_state.json"
_TODAY = datetime.now().strftime("%Y-%m-%d")
_NOW_HHMM = datetime.now().strftime("%H:%M")
AFTER_CLOSE = _NOW_HHMM >= CLOSE_HHMM
CLOSED_TODAY = False
if CLOSE_STATE.exists():
    try:
        CLOSED_TODAY = json.loads(CLOSE_STATE.read_text(encoding="utf-8")).get("date") == _TODAY
    except Exception:
        CLOSED_TODAY = False

if AFTER_CLOSE and CLOSED_TODAY:
    write_audit({
        "level": "info", "stage": "closed_skip",
        "message": "已过收盘时间且当天已收盘读取，静默退出",
        "close_time": CLOSE_HHMM,
    })
    sys.exit(0)  # silent: no CDP, no writes, no notify

if AFTER_CLOSE:
    # 收盘轮：强制只读，只落盘最后一轮数据，不执行任何写操作
    os.environ["QC_DRY_RUN"] = "1"
    write_audit({
        "level": "info", "stage": "close_read",
        "message": "已过收盘时间，本轮为当天最后一轮读取（只读，不操作）",
        "close_time": CLOSE_HHMM,
    })

# 0. Ensure the dedicated Qianchuan Chrome/CDP profile exists before browser-harness starts.
# browser-harness checks BU_CDP_URL before executing stdin code, so this cannot live inside
# read_material_heat_realtime.cdp.py itself.
ok, chrome_msg = ensure_chrome_9223(CDP_OVERRIDE)
if not ok:
    write_audit({"level": "error", "stage": "chrome_preflight", "message": chrome_msg})
    print(f"⚠️ 千川追投巡检失败 — {chrome_msg}")
    sys.exit(1)
BU_CDP_URL = os.environ.get("BU_CDP_URL")
if not BU_CDP_URL:
    write_audit({"level": "error", "stage": "chrome_preflight", "message": "CDP helper did not export BU_CDP_URL"})
    print("⚠️ 千川追投巡检失败 — CDP helper did not export BU_CDP_URL")
    sys.exit(1)
write_audit({"level": "info", "stage": "chrome_preflight", "message": chrome_msg, "cdp_url": BU_CDP_URL})

# 1. Run the CDP read + strategy script (auto-exec enabled)
try:
    result = subprocess.run(
        [BH], input=CDP_SCRIPT.read_bytes(),
        capture_output=True, text=False, timeout=180,
        cwd=str(CDP_SCRIPT.parent)
    )
    if result.returncode != 0:
        stderr_text = (result.stderr or b"").decode("utf-8", errors="replace")
        write_audit({
            "level": "error",
            "stage": "browser_harness",
            "returncode": result.returncode,
            "stderr": stderr_text[-1000:],
        })
        print("⚠️ 千川追投巡检失败 — browser-harness 返回非0")
        sys.exit(1)
except FileNotFoundError:
    alt = pathlib.Path.home() / ".local/bin/browser-harness"
    if alt.exists():
        result = subprocess.run(
            [str(alt)], input=CDP_SCRIPT.read_bytes(),
            capture_output=True, text=False, timeout=180,
            cwd=str(CDP_SCRIPT.parent)
        )
        if result.returncode != 0:
            stderr_text = (result.stderr or b"").decode("utf-8", errors="replace")
            write_audit({
                "level": "error",
                "stage": "browser_harness_alt",
                "returncode": result.returncode,
                "stderr": stderr_text[-1000:],
            })
            print("⚠️ 千川追投巡检失败 — browser-harness 返回非0")
            sys.exit(1)
    else:
        write_audit({"level": "error", "stage": "bootstrap", "message": "browser-harness 未找到"})
        print("⚠️ 千川追投巡检失败 — browser-harness 未找到")
        sys.exit(2)
except Exception as e:
    write_audit({"level": "error", "stage": "exception", "message": str(e)})
    print(f"⚠️ 千川追投巡检失败 — {e}")
    sys.exit(3)

# 1b. 收盘轮：读取已成功落盘，标记当天收盘并静默退出（不通知、不操作）。
# 后续当天轮次在开头就会因 CLOSED_TODAY 直接退出。
if AFTER_CLOSE:
    try:
        CLOSE_STATE.write_text(
            json.dumps({
                "date": _TODAY,
                "closed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "close_time": CLOSE_HHMM,
                "mode": "read_only_final",
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        write_audit({
            "level": "info", "stage": "close_marked",
            "message": "收盘轮读取完成，已标记当天收盘，本日不再运行",
            "close_time": CLOSE_HHMM,
        })
    except Exception as e:
        write_audit({"level": "warn", "stage": "close_marked", "message": str(e)})
    sys.exit(0)  # silent: final read saved, no notify, no actions

# 2. Check strategy JSON for pause actions
if not STRATEGY_JSON.exists():
    write_audit({"level": "warn", "stage": "strategy", "message": "strategy json missing"})
    sys.exit(0)  # silent

data = json.loads(STRATEGY_JSON.read_text(encoding="utf-8"))
actions = data.get("actions") or data.get("top_actions") or []
pauses = [a for a in actions if a.get("action") == "pause"]

# 2b. Freshness gate: only trust a strategy file written by THIS run cycle.
# If the CDP read script died silently (exit 0 on account mismatch / missing
# tab), the file is stale and its old pause actions must NOT be re-broadcast
# as new "paused" alerts. Report the outage (deduped) instead.
import time
_now = time.time()
_mtime = STRATEGY_JSON.stat().st_mtime
_age_min = (_now - _mtime) / 60.0
MAX_AGE_MIN = 25  # cron every 20m, allow one missed tick
if _age_min > MAX_AGE_MIN:
    # Dedup window: alert at most once per 2h for the same outage (cron ticks
    # every 20m would otherwise spam the channel every run).
    _last_stale_ts = ""
    try:
        for _line in RUN_LOG.open("r", encoding="utf-8"):
            _row = json.loads(_line)
            if _row.get("stage") == "stale_strategy":
                _last_stale_ts = _row.get("ts", "")
    except Exception:
        pass
    _dup = False
    if _last_stale_ts:
        try:
            _last_stale_dt = datetime.strptime(_last_stale_ts, "%Y-%m-%d %H:%M:%S")
            _dup = (datetime.now() - _last_stale_dt).total_seconds() < 2 * 3600
        except ValueError:
            _dup = False
    write_audit({
        "level": "warn",
        "stage": "stale_strategy",
        "age_min": round(_age_min, 1),
        "mtime": datetime.fromtimestamp(_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "suppressed_pause_ids": [p.get("task_id") for p in pauses],
        "dup_suppressed": _dup,
    })
    if not _dup:
        print(f"⚠️ 千川追投巡检未完成 — 策略数据已过期 {_age_min:.0f} 分钟（mtime {datetime.fromtimestamp(_mtime).strftime('%H:%M')}），"
              f"未确认任何暂停。请检查 CDP 页面/登录态后手动复核任务状态。")
    sys.exit(0)

# 3. No pauses → silent exit
if not pauses:
    write_audit({
        "level": "info",
        "stage": "decision",
        "pause_count": 0,
        "action_count": len(actions),
        "strategy_read_at": data.get("baseline", {}).get("current_read_at"),
        "note": data.get("execution", {}).get("note", "silent exit"),
    })
    sys.exit(0)

# 4. Has pauses → build Feishu message
exec_results = data.get("execution", {}).get("results", [])
lines = [f'<at user_id="ou_f3d6a01b77db70259b455199c3046d31">樊墨扬</at> 🔴 千川追投已触发自动暂停（{ACCOUNT.label} / {ACCOUNT.aavid}）', ""]

for p in pauses:
    tid = p.get("task_id", "?")
    name = p.get("task_name", "?")
    reason = p.get("reason", "")
    m = p.get("metrics", {})
    lines.append(f"• {name} ({tid})")
    lines.append(f"  消耗¥{m.get('cost_yuan', 0):.0f}  ROI{m.get('pay_roi', 0):.2f}  {reason}")

if exec_results:
    lines.append("")
    lines.append("执行结果:")
    for r in exec_results:
        if r.get("action") == "pause":
            icon = "✅" if r.get("ok") else "❌"
            lines.append(f"  {icon} 暂停 {r.get('task_id', '?')} — {r.get('message', '')}")

message = "\n".join(lines).strip() + "\n"
write_audit({
    "level": "info",
    "stage": "notify",
    "pause_count": len(pauses),
    "action_count": len(actions),
    "paused_task_ids": [p.get("task_id") for p in pauses],
    "strategy_read_at": data.get("baseline", {}).get("current_read_at"),
    "notify_preview": lines[:6],
    "stdout_bytes": len(message.encode("utf-8", errors="replace")),
})

# Cron no_agent delivers stdout verbatim. Use a binary fd write so Windows text
# encoding / wrapper quirks cannot turn a non-empty alert into an empty capture.
os.write(1, message.encode("utf-8", errors="replace"))
