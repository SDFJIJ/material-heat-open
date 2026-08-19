#!/usr/bin/env python
# 每日 6:00 千川追投开盘重置（no_agent cron，.py 包装避免 .sh 在 Windows bash 下的路径坑）
# 逻辑：确保 Chrome → browser-harness 执行 daily_reset_material_heat.cdp.py（预算统一1000 + 全开）
# 成功输出精简摘要；失败输出错误并 exit 非0

import json
import os
import pathlib
import subprocess
import sys

HOME = pathlib.Path.home()
PROJECT = pathlib.Path(r"C:\Users\fmy\qcqianchuan")
CDP_SCRIPT = PROJECT / "scripts" / "daily_reset_material_heat.cdp.py"

BH_CANDIDATES = [
    HOME / ".local/bin/browser-harness",
    pathlib.Path("browser-harness"),
]
BH = None
for c in BH_CANDIDATES:
    if c.exists():
        BH = str(c)
        break
if BH is None:
    import shutil
    BH = shutil.which("browser-harness") or "browser-harness"


def ensure_chrome() -> tuple[bool, str]:
    """复用 qianchuan_chrome.ensure_chrome_9223，导出 BU_CDP_URL。"""
    sys.path.insert(0, str(PROJECT / "scripts"))
    from qianchuan_chrome import ensure_chrome_9223
    ok, msg = ensure_chrome_9223()
    return ok, msg


# 0. Chrome 预检（watchdog 同款：CDP 必须先就绪，browser-harness 才接得上）
ok, msg = ensure_chrome()
if not ok:
    print(f"开盘重置失败 — Chrome 未就绪: {msg}")
    sys.exit(1)
if not os.environ.get("BU_CDP_URL"):
    print("开盘重置失败 — CDP helper 未导出 BU_CDP_URL")
    sys.exit(1)

# 1. 执行开盘重置 CDP 脚本（真实写操作：预算→1000 + 全部开启）
try:
    result = subprocess.run(
        [BH], input=CDP_SCRIPT.read_bytes(),
        capture_output=True, text=False, timeout=240,
        cwd=str(CDP_SCRIPT.parent),
    )
except FileNotFoundError:
    print("开盘重置失败 — browser-harness 未找到")
    sys.exit(2)
except Exception as e:
    print(f"开盘重置失败 — {e}")
    sys.exit(3)

if result.returncode != 0:
    stderr_text = (result.stderr or b"").decode("utf-8", errors="replace")
    print(f"开盘重置失败 — browser-harness 返回 {result.returncode}: {stderr_text[-800:]}")
    sys.exit(1)

raw = (result.stdout or b"").decode("utf-8", errors="replace")
start = raw.find("{")
if start < 0:
    print(f"开盘重置失败 — 无 JSON 输出: {raw[-400:]}")
    sys.exit(1)

try:
    d = json.loads(raw[start:])
except Exception as e:
    print(f"开盘重置失败 — JSON 解析错误 {e}: {raw[-400:]}")
    sys.exit(1)

if not d.get("ok"):
    print(f"开盘重置失败: {json.dumps(d, ensure_ascii=False)[:500]}")
    sys.exit(1)

bud = d.get("budget_results", [])
bud_ok = sum(1 for r in bud if r.get("budget_ok"))
st = d.get("start_results", [])
st_ok = sum(1 for r in st if r.get("verified_running"))
ac = d.get("after_counts", {})
print(
    "开盘重置完成 %s: 预算 %d/%d→1000，开启 %d/%d 调控中（总量 %d，运行 %d）" % (
        d.get("read_at", ""), bud_ok, len(bud), st_ok, len(st),
        ac.get("total", 0), ac.get("running", 0),
    )
)

# 2. 开盘后必须确保「千川追投」watchdog cron 处于启用状态（用户规则：
#    开盘重置完成≠收工，watchdog 要全程盯着自动暂停；resume 幂等，已启用无副作用）
HERMES_EXE = HOME / "AppData" / "Local" / "hermes" / "hermes-agent" / "venv" / "Scripts" / "hermes.exe"
WATCHDOG_JOB_ID = "4c320202911b"  # 「千川追投」每20分钟 watchdog
if HERMES_EXE.exists():
    try:
        wr = subprocess.run(
            [str(HERMES_EXE), "cron", "resume", WATCHDOG_JOB_ID],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        if wr.returncode == 0:
            print(f"watchdog「千川追投」已确认启用（cron resume ok）")
        else:
            print(f"watchdog 启用失败（rc={wr.returncode}）: {(wr.stderr or wr.stdout or '')[-300:]}")
    except Exception as e:
        print(f"watchdog 启用异常: {e}")
else:
    print(f"watchdog 启用跳过 — hermes.exe 不存在: {HERMES_EXE}")
