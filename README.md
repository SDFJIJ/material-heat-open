# 千川素材追投自动化（Material Heat Auto-Pilot）

抖音千川「素材追投」（uni-promotion assist task）的自动化控制系统：定时读取追投计划数据、按 ROI 策略自动暂停/重开/调预算/调出价/调 ROI 目标，并提供本地可视化看板。

> 数据来源：千川广告后台（qianchuan.jinritemai.com）页面内 XHR 接口，需通过已登录的 Chrome CDP 执行。

## 架构

```
┌────────────────────────────────────────────────────────────┐
│ 调度层  Hermes cron                                        │
│  ├─ watchdog（每 20 分钟）→ scheduler/qianchuan_pause_watchdog.py
│  └─ 每日 06:00 开盘重置 → scheduler/daily_reset_material_heat.py
├────────────────────────────────────────────────────────────┤
│ 控制链路  core/                                            │
│   读取 → 策略 → 执行 → 存储 → 落盘                           │
├────────────────────────────────────────────────────────────┤
│ 支撑层  support/（Chrome/CDP + 账户上下文 + 看板服务）        │
├────────────────────────────────────────────────────────────┤
│ 看板层  本地 HTTP 服务 + 前端（只读旁路，开闭原则）            │
└────────────────────────────────────────────────────────────┘
```

## 快速开始

### 依赖

- Python 3.10+
- 已登录千川的 Chrome（`--remote-debugging-port=9223`，独立 profile）
- [browser-harness](https://github.com/nousresearch/browser-harness)（CDP 执行器）
- Hermes（可选，用于 cron 调度）

### 账户配置

账户信息从外部配置文件读取（不进仓库），结构：

```json
{
  "active_account": "my-shop",
  "accounts": {
    "my-shop": {
      "label": "示例店铺",
      "aavid": "<你的账户ID>",
      "primary_ad_id": "<主计划ID>",
      "anchor_id": "<主播ID>",
      "assist_task_scene": 1,
      "target_roi": 3.0,
      "gfversion": "auto",
      "chrome_profile": "C:/path/to/chrome-profile"
    }
  }
}
```

### 运行

```bash
# 1. 确保 Chrome CDP 就绪
python support/qianchuan_chrome.py  # 或手动启动 9223 Chrome

# 2. 一次巡检（dry-run：只读+策略计算，不写）
QC_DRY_RUN=1 BU_CDP_URL=http://127.0.0.1:9223 \
  browser-harness < core/read_material_heat_realtime.cdp.py

# 3. 真实执行（去掉 QC_DRY_RUN 即自动执行写操作）
BU_CDP_URL=http://127.0.0.1:9223 \
  browser-harness < core/read_material_heat_realtime.cdp.py

# 4. 开盘重置（预算统一 + 全部开启）
python scheduler/daily_reset_material_heat.py

# 5. 看板
python support/serve_dashboard.py --port 8890
# 浏览器打开 http://127.0.0.1:8890/web/material_heat_dashboard.html
```

## 目录结构

```
├── core/       控制链路：读取/策略/执行/存储/开盘重置
├── scheduler/  cron 调度包装（watchdog + 开盘重置）
├── support/    账户上下文 / Chrome 管理 / 看板 HTTP 服务
├── tools/      辅助脚本 + 看板前端 app.js
├── tests/      单元测试
└── docs/       策略规则 / API 接口 / 安全说明
```

## 安全设计

- **账户上下文校验（fail-closed）**：所有写操作前校验页面 URL `aavid=` 与页面文本「计划ID：<primary_ad_id>」标记，不匹配直接拒绝执行，绝不猜测账户。
- **dry-run 默认**：策略层默认 `QC_DRY_RUN=1`，写操作需显式关闭。
- **收盘规则**：每日 18:40 后只读最后一轮并落盘，随后当天静默（不操作不通知），次日自动恢复。
- **敏感信息外部化**：账户 ID / 主计划 ID 等全部在外部配置文件，代码仓库不含任何真实账户凭据。

## License

MIT
