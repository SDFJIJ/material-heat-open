/* 千川素材追投看板 — 动态数据源版
 * 直接 fetch 本地数据文件（经 serve_dashboard.py 提供 HTTP 服务），
 * 每 60 秒自动轮询刷新，无需每次 cron 后重新生成 HTML。
 */
const ACCOUNT = "demo-account";
const BASE = "/data/accounts/" + ACCOUNT + "/";
const FILES = {
  latest: BASE + "material_heat_realtime_latest.json",
  history: BASE + "material_heat_realtime_history.jsonl",
  runs: BASE + "material_heat_runs.jsonl",
  strategy: BASE + "material_heat_strategy_latest.json",
};
const POLL_MS = 60000;

async function loadJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

async function loadJSONL(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " -> " + r.status);
  const text = await r.text();
  const rows = [];
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s) continue;
    try { rows.push(JSON.parse(s)); } catch (e) { /* skip bad line */ }
  }
  return rows;
}

function fmtNum(v) {
  if (v === null || v === undefined || v === "" || v === "-") return "-";
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  return Math.abs(n) >= 100 ? n.toLocaleString("zh-CN", { maximumFractionDigits: 0 })
                            : n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}
function fmtRoi(v) {
  if (v === null || v === undefined || v === "" || v === "-") return "-";
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  return n.toFixed(2);
}
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function sparkline(values, width, height, color) {
  const vals = values.filter(v => v !== null && v !== undefined && v !== "");
  if (vals.length < 2) return "";
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const rng = (mx - mn) || 1;
  const pts = vals.map((v, i) => {
    const x = 2 + i * (width - 6) / (vals.length - 1);
    const y = height - 4 - (v - mn) / rng * (height - 10);
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  return '<svg width="' + width + '" height="' + height + '" style="display:block">' +
         '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.6"/></svg>';
}

// 同轴双线 + 底部消耗增量柱：时间轴完全对齐，柱高=该时点消耗增量（占满底部 1/3 区），
// 蓝线=消耗累计、绿线=成交累计（各自归一化到上半 2/3 区）。一眼看出"消耗在跑、成交跟不跟得上"。
function sparkDual(costArr, gmvArr, width, height, costColor, gmvColor) {
  const n = Math.max(costArr.length, gmvArr.length);
  if (n < 2) return "";
  const xs = i => 2 + i * (width - 6) / (n - 1);
  const lineH = height - 12;            // 曲线区高度（顶部），底部 12px 留给增量柱
  const barH = 10;                      // 增量柱高度
  // 归一化区间：消耗/成交各自 min-max
  const norm = (arr, lo, hi) => {
    const vals = arr.filter(v => v !== null && v !== undefined);
    if (vals.length < 2) return () => lo + (hi - lo) / 2;
    const mn = Math.min(...vals), mx = Math.max(...vals);
    const rng = (mx - mn) || 1;
    return v => (v === null || v === undefined) ? null : (hi - 4 - (v - mn) / rng * (lineH - 8));
  };
  const yC = norm(costArr, 4, lineH), yG = norm(gmvArr, 4, lineH);
  const line = (arr, yf, color) => {
    const pts = [];
    arr.forEach((v, i) => { const y = yf(v); if (y !== null) pts.push(xs(i).toFixed(1) + "," + y.toFixed(1)); });
    if (pts.length < 2) return "";
    return '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="1.6" stroke-linejoin="round"/>';
  };
  // 消耗增量柱：柱高按窗口内最大增量归一化
  let bars = "", prev = null, maxD = 0;
  const ds = [];
  costArr.forEach((v) => { const d = (v !== null && v !== undefined && prev !== null && prev !== undefined) ? v - prev : 0; ds.push(Math.max(0, d)); prev = v; });
  maxD = Math.max(...ds, 1);
  costArr.forEach((v, i) => {
    if (v === null || v === undefined || i === 0) return;
    const d = Math.max(0, v - costArr[i - 1]);
    if (d <= 0) return;
    const bh = Math.max(1.5, d / maxD * barH);
    const x = xs(i) - (width - 6) / (n - 1) / 3;
    const w = Math.max(1.2, (width - 6) / (n - 1) * 0.6);
    bars += '<rect x="' + x.toFixed(1) + '" y="' + (height - bh).toFixed(1) + '" width="' + w.toFixed(1) + '" height="' + bh.toFixed(1) + '" fill="' + costColor + '" opacity="0.18"/>';
  });
  return '<svg width="' + width + '" height="' + height + '" style="display:block">' + bars + line(costArr, yC, costColor) + line(gmvArr, yG, gmvColor) + '</svg>';
}

function setStatus(msg) {
  const el = document.getElementById("status");
  if (el) el.textContent = msg;
}

/* ---------- 首页：全量计划 ---------- */
async function renderIndex() {
  const latest = await loadJSON(FILES.latest);
  const s = latest.summary || {};
  document.getElementById("stat").innerHTML =
    "最新读取 <b>" + esc(latest.read_at || "-") + "</b> · " +
    "任务总数 <b>" + fmtNum(s.task_total) + "</b> · " +
    "调控中 <b>" + fmtNum(s.controlling_count) + "</b> · " +
    "已暂停 <b>" + fmtNum(s.paused_count) + "</b> · " +
    "总消耗 <b>" + fmtNum(s.cost_yuan) + "</b> · " +
    "支付ROI <b>" + fmtRoi(s.pay_roi) + "</b>";

  // 显示层：后端已把三态合并成 display_overlay（a 快照 / b 策略黄 / c 手动蓝），前端只读渲染
  const strat = await loadJSON(FILES.strategy);
  const overlay = (strat && strat.display_overlay) || {};
  // 默认按消耗降序排列
  const sortedTasks = (latest.tasks || []).slice().sort((x, y) => {
    const cx = (x.metrics || {}).cost_yuan || 0, cy = (y.metrics || {}).cost_yuan || 0;
    return cy - cx;
  });
  const rows = sortedTasks.map(t => {
    const m = t.metrics || {};
    const o = overlay[String(t.task_id)] || {};
    const pick = (field, fallback) => {
      const rec = o[field];
      return rec && rec.value !== undefined && rec.value !== null ? rec.value : fallback;
    };
    const budget = pick("budget_yuan", t.budget_yuan);
    const bid = pick("bid_yuan", t.bid_yuan);
    const roiGoal = pick("roi_goal", t.roi_goal);
    const status = pick("control_status", t.control_status);
    // 单元格：source=strategy → 黄；source=manual → 蓝；snapshot → 无
    const cell = (val, v, field) => {
      const rec = o[field];
      let cls = "", tip = "";
      if (rec && rec.source === "strategy") { cls = " adj"; tip = " title='已执行调整：" + esc(rec.note || "") + "'"; }
      else if (rec && rec.source === "manual") { cls = " adj-man"; tip = " title='" + esc(rec.note || "") + "'"; }
      return "<td class='num" + cls + "' data-v='" + (v ?? "") + "'" + tip + ">" + val + "</td>";
    };
    const cls = status === "已暂停" ? "pause" : "run";
    return "<tr>" +
      "<td>" + esc(t.task_name) + "</td>" +
      "<td>" + esc(t.task_id) + "</td>" +
      "<td><span class='chip " + cls + "'>" + esc(status) + "</span></td>" +
      "<td>" + esc(t.delivery_status) + "</td>" +
      "<td>" + esc(t.smart_bid_name) + "</td>" +
      cell(fmtNum(budget), budget, "budget_yuan") +
      cell(fmtNum(bid), bid, "bid_yuan") +
      cell(fmtRoi(roiGoal), roiGoal, "roi_goal") +
      "<td class='num' data-v='" + (m.cost_yuan ?? "") + "'>" + fmtNum(m.cost_yuan) + "</td>" +
      "<td class='num' data-v='" + (m.pay_roi ?? "") + "'>" + fmtRoi(m.pay_roi) + "</td>" +
      "<td class='num' data-v='" + (m.pay_order_count ?? "") + "'>" + fmtNum(m.pay_order_count) + "</td>" +
      "<td class='num' data-v='" + (m.pay_gmv_yuan ?? "") + "'>" + fmtNum(m.pay_gmv_yuan) + "</td>" +
      "<td class='num' data-v='" + (m.net_roi ?? "") + "'>" + fmtRoi(m.net_roi) + "</td>" +
      "</tr>";
  }).join("");
  document.getElementById("plans-body").innerHTML = rows || "<tr><td colspan=13>暂无数据</td></tr>";
}

/* ---------- 时段走势：每任务卡片 ---------- */
async function renderTimeline() {
  const history = await loadJSONL(FILES.history);
  const latest = await loadJSON(FILES.latest);
  const MAX_SLOTS = 10;
  const snaps = [];
  const seen = new Set();
  for (const s of history) {
    if (s.read_at && !seen.has(s.read_at)) { seen.add(s.read_at); snaps.push(s); }
  }
  const slots = snaps.slice(-MAX_SLOTS);
  const times = slots.map(s => s.read_at);
  const perTask = {};
  for (const s of slots) {
    for (const t of (s.tasks || [])) {
      const tid = String(t.task_id);
      const m = t.metrics || {};
      if (!perTask[tid]) perTask[tid] = { cost: {}, gmv: {} };
      perTask[tid].cost[s.read_at] = m.cost_yuan;
      perTask[tid].gmv[s.read_at] = m.pay_gmv_yuan;
    }
  }
  const header = "<th>指标</th>" + times.map(ts => "<th class='num'>" + esc(ts.slice(11, 16)) + "</th>").join("");
  // 先按任务算好窗口消耗/成交增量，默认按消耗增量降序排列卡片
  const cardRows = [];
  for (const t of (latest.tasks || [])) {
    const tid = String(t.task_id);
    const slot = perTask[tid];
    if (!slot) continue;
    let winCost = 0, winGmv = 0;
    let prevC = null, prevG = null;
    for (const ts of times) {
      const c = slot.cost[ts], g = slot.gmv[ts];
      if (c !== null && c !== undefined) {
        if (prevC !== null) winCost += c - prevC;
        prevC = c;
      } else { prevC = null; }
      if (g !== null && g !== undefined) {
        if (prevG !== null) winGmv += g - prevG;
        prevG = g;
      } else { prevG = null; }
    }
    cardRows.push({ t, tid, winCost, winGmv });
  }
  cardRows.sort((a, b) => b.winCost - a.winCost);  // 默认：消耗增量降序
  let cards = "";
  for (const row of cardRows) {
    const t = row.t, tid = row.tid;
    const winCost = row.winCost, winGmv = row.winGmv;
    const slot = perTask[tid];
    const cls = t.control_status === "已暂停" ? "pause" : "run";
    let costCells = "", gmvCells = "", prevC = null, prevG = null;
    let accCost = 0, accGmv = 0;
    const costSeries = [], gmvSeries = [];
    for (const ts of times) {
      const c = slot.cost[ts], g = slot.gmv[ts];
      costSeries.push(c); gmvSeries.push(g);
      if (c === null || c === undefined) {
        costCells += "<td class='num'>-</td>";
        gmvCells += "<td class='num'>-</td>";
        prevC = prevG = null;
        continue;
      }
      if (prevC === null) {
        costCells += "<td class='num' title='" + esc(ts + " 累计 " + fmtNum(c) + "（首个时点，无增量基准）") + "'>" + fmtNum(c) + "</td>";
      } else {
        const d = c - prevC;
        const hl = d > 0 ? " class='num up'" : " class='num'";
        costCells += "<td" + hl + " title='" + esc(ts + " 增量 " + fmtNum(d) + "（累计 " + fmtNum(c) + "）") + "'>" + fmtNum(d) + "</td>";
        accCost += d;
      }
      if (g === null || g === undefined) {
        gmvCells += "<td class='num'>-</td>";
        prevG = null;
      } else if (prevG === null) {
        gmvCells += "<td class='num' title='" + esc(ts + " 累计 " + fmtNum(g) + "（首个时点，无增量基准）") + "'>" + fmtNum(g) + "</td>";
      } else {
        const gd = g - prevG;
        gmvCells += "<td class='num' title='" + esc(ts + " 增量 " + fmtNum(gd) + "（累计 " + fmtNum(g) + "）") + "'>" + fmtNum(gd) + "</td>";
        accGmv += gd;
      }
      prevC = c; prevG = g;
    }
    cards +=
      "<div class='tcard' data-cost-delta='" + accCost.toFixed(2) + "' data-gmv-delta='" + accGmv.toFixed(2) + "'>" +
      "<div class='tname'>" + esc(t.task_name) + " <span class='chip " + cls + "'>" + esc(t.control_status) + "</span></div>" +
      "<div class='tid'>" + esc(tid) + "</div>" +
      "<div class='tsum'>" +
        "<b>" + fmtNum(accCost) + "</b> 消耗 · " +
        "<b>" + fmtNum(accGmv) + "</b> 成交 · " +
        "<b>" + fmtNum(accGmv - accCost) + "</b> 净成交 · " +
        "<b>" + (accCost > 0 ? (accGmv / accCost).toFixed(2) : "-") + "</b> 窗口ROI" +
      "</div>" +
      "<div class='tspark'>" + sparkDual(costSeries, gmvSeries, 220, 44, "#1677ff", "#1a7f37") +
      "<div class='lgbox'><span class='lg'><i style='background:#1677ff'></i>消耗累计</span>" +
      "<span class='lg'><i style='background:#1a7f37'></i>成交累计</span>" +
      "<span class='lg'><i style='background:#1677ff;opacity:.25'></i>消耗增量</span></div></div>" +
      "<table><tr>" + header + "</tr>" +
      "<tr><td class='rlab'>消耗</td>" + costCells + "</tr>" +
      "<tr><td class='rlab'>成交</td>" + gmvCells + "</tr></table>" +
      "</div>";
  }
  document.getElementById("tgrid").innerHTML = cards || "<div class='meta'>暂无历史快照</div>";
  const hdr = document.getElementById("slot-hdr");
  if (hdr) hdr.textContent = "节点时段消耗/成交（最近 " + times.length + " 次读取）";
}

/* ---------- 运行记录 ---------- */
async function renderRuns() {
  const runs = await loadJSONL(FILES.runs);
  const rows = runs.slice(-120).reverse().map(run => {
    const summary = run.summary || {};
    const actions = (run.strategy || {}).actions || [];
    const results = ((run.strategy || {}).execution || {}).results || [];
    const resultMap = {};
    results.forEach(r => { resultMap[r.action + "|" + r.task_id] = r; });
    const blocks = actions.map(a => {
      const tid = String(a.task_id || "");
      const r = resultMap[a.action + "|" + tid];
      let resCls, resTxt;
      if (!r) { resCls = "warn"; resTxt = "未执行"; }
      else if (r.ok) { resCls = "ok"; resTxt = "OK " + (r.message || ""); }
      else { resCls = "bad"; resTxt = "FAIL " + (r.error || r.message || ""); }
      const m = a.metrics || {};
      const parts = [];
      if (m.cost_yuan !== undefined && m.cost_yuan !== null) parts.push("消耗 " + fmtNum(m.cost_yuan));
      if (m.pay_roi !== undefined && m.pay_roi !== null) parts.push("ROI " + fmtRoi(m.pay_roi));
      if (a.old_budget_yuan !== undefined && a.old_budget_yuan !== null)
        parts.push("预算 " + fmtNum(a.old_budget_yuan) + "→" + fmtNum(a.new_budget_yuan) + "（+" + fmtNum(a.increment_yuan) + "）");
      const chg = a.preferred_change || {};
      if (chg.field === "bid_yuan") parts.push("出价 " + fmtNum(chg.old) + "→" + fmtNum(chg.new));
      else if (chg.field === "roi_goal") parts.push("ROI目标 " + fmtRoi(chg.old) + "→" + fmtRoi(chg.new));
      const chgHtml = parts.length ? "<div class='achange'>" + esc(parts.join(" · ")) + "</div>" : "";
      const reasonHtml = a.reason ? "<div class='areason'>" + esc(a.reason) + "</div>" : "";
      return "<div class='ablock'>" +
        "<span class='chip " + (a.action === "pause" ? "warn" : "ok") + "'>" + esc(a.action) + "</span> " +
        "<span class='aname'>" + esc(a.task_name || tid) + "</span> " +
        "<span class='chip " + resCls + "'>" + esc(resTxt) + "</span>" + chgHtml + reasonHtml + "</div>";
    }).join(" ");
    return "<tr><td>" + esc(run.read_at || "") + "</td>" +
      "<td>" + fmtNum(summary.task_total) + "</td>" +
      "<td>" + fmtNum(summary.controlling_count) + "</td>" +
      "<td>" + fmtNum(summary.paused_count) + "</td>" +
      "<td>" + fmtNum(summary.cost_yuan) + "</td>" +
      "<td>" + fmtRoi(summary.pay_roi) + "</td>" +
      "<td>" + (blocks || "-") + "</td></tr>";
  }).join("");
  document.getElementById("runs-body").innerHTML = rows || "<tr><td colspan=7>暂无运行日志</td></tr>";
}

/* ---------- 每日汇总 ---------- */
async function renderDaily() {
  const history = await loadJSONL(FILES.history);
  // group snapshots by day; per day take the LAST snapshot as the daily total
  const byDay = {};
  for (const s of history) {
    const d = (s.read_at || "").slice(0, 10);
    if (!d) continue;
    byDay[d] = s; // overwrite -> keeps the latest snapshot of that day
  }
  const days = Object.keys(byDay).sort();
  const rows = days.map(d => {
    const s = byDay[d];
    const sum = s.summary || {};
    const tasks = s.tasks || [];
    const totalCost = sum.cost_yuan !== undefined && sum.cost_yuan !== null
      ? sum.cost_yuan
      : tasks.reduce((a, t) => a + ((t.metrics || {}).cost_yuan || 0), 0);
    const totalGmv = tasks.reduce((a, t) => a + ((t.metrics || {}).pay_gmv_yuan || 0), 0);
    const totalOrders = tasks.reduce((a, t) => a + ((t.metrics || {}).pay_order_count || 0), 0);
    const roi = sum.pay_roi !== undefined && sum.pay_roi !== null ? sum.pay_roi : null;
    const detailRows = tasks.map(t => {
      const m = t.metrics || {};
      return "<tr><td>" + esc(t.task_name) + "</td><td>" + esc(t.task_id) + "</td>" +
        "<td class='num'>" + fmtNum(m.cost_yuan) + "</td>" +
        "<td class='num'>" + fmtNum(m.pay_gmv_yuan) + "</td>" +
        "<td class='num'>" + fmtRoi(m.pay_roi) + "</td>" +
        "<td class='num'>" + fmtNum(m.pay_order_count) + "</td></tr>";
    }).join("");
    const detail = "<details><summary>查看当天任务明细（" + tasks.length + " 个任务）</summary>" +
      "<div class='wrap'><table class='detail-table'><thead><tr>" +
      "<th>任务名</th><th>任务ID</th><th class='num'>消耗</th><th class='num'>成交GMV</th><th class='num'>支付ROI</th><th class='num'>订单</th>" +
      "</tr></thead><tbody>" + (detailRows || "<tr><td colspan=6>无任务</td></tr>") + "</tbody></table></div></details>";
    return "<tr>" +
      "<td><b>" + esc(d) + "</b></td>" +
      "<td class='num'>" + fmtNum(sum.task_total) + "</td>" +
      "<td class='num'>" + fmtNum(sum.controlling_count) + "</td>" +
      "<td class='num'>" + fmtNum(sum.paused_count) + "</td>" +
      "<td class='num'>" + fmtNum(totalCost) + "</td>" +
      "<td class='num'>" + fmtNum(totalGmv) + "</td>" +
      "<td class='num'>" + (roi === null ? "-" : fmtRoi(roi)) + "</td>" +
      "<td class='num'>" + fmtNum(totalOrders) + "</td>" +
      "<td>" + esc(s.read_at || "") + "</td>" +
      "<td>" + detail + "</td></tr>";
  }).reverse().join("");
  document.getElementById("daily-body").innerHTML = rows || "<tr><td colspan=10>暂无历史数据</td></tr>";
}

/* ---------- 单任务跨天走势 ---------- */
async function renderTaskTrend() {
  const history = await loadJSONL(FILES.history);
  // per task: {date -> last snapshot metrics}
  const byTask = {};
  for (const s of history) {
    const d = (s.read_at || "").slice(0, 10);
    if (!d) continue;
    for (const t of (s.tasks || [])) {
      const tid = String(t.task_id);
      if (!byTask[tid]) byTask[tid] = { name: t.task_name || tid, days: {} };
      byTask[tid].days[d] = { // overwrite -> latest of that day
        read_at: s.read_at,
        status: t.control_status,
        m: t.metrics || {},
      };
    }
  }
  // populate task selector
  const sel = document.getElementById("task-select");
  const ids = Object.keys(byTask).sort((a, b) => byTask[a].name.localeCompare(byTask[b].name));
  const prev = sel.value;
  sel.innerHTML = "<option value=''>— 选择任务 —</option>" +
    ids.map(id => "<option value='" + id + "'>" + esc(byTask[id].name) + "</option>").join("");
  if (prev && byTask[prev]) sel.value = prev;

  const body = document.getElementById("trend-body");
  const wrap = document.getElementById("trend-wrap");
  if (!sel.value || !byTask[sel.value]) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "block";
  const task = byTask[sel.value];
  const dates = Object.keys(task.days).sort();
  const rows = dates.map(d => {
    const rec = task.days[d];
    const m = rec.m;
    return "<tr>" +
      "<td><b>" + esc(d) + "</b></td>" +
      "<td class='num'>" + fmtNum(m.cost_yuan) + "</td>" +
      "<td class='num'>" + fmtNum(m.pay_gmv_yuan) + "</td>" +
      "<td class='num'>" + fmtRoi(m.pay_roi) + "</td>" +
      "<td class='num'>" + fmtNum(m.pay_order_count) + "</td>" +
      "<td class='num'>" + fmtNum(m.net_gmv_yuan) + "</td>" +
      "<td>" + esc((rec.read_at || "").slice(11)) + "</td></tr>";
  }).reverse().join("");
  const costs = dates.map(d => task.days[d].m.cost_yuan);
  const gmvs = dates.map(d => task.days[d].m.pay_gmv_yuan);
  body.innerHTML = rows || "<tr><td colspan=7>该任务无历史记录</td></tr>";
  document.getElementById("trend-spark").innerHTML =
    sparkline(costs, 340, 60, "#1677ff") + sparkline(gmvs, 340, 60, "#1a7f37");
  document.getElementById("trend-title").textContent =
    task.name + "（" + sel.value + "）· 跨 " + dates.length + " 天";
}

/* ---------- 追投跑动多线图（首页） ---------- */
// 每天每个任务一条累计消耗曲线：X=分时时间, Y=当日累计消耗
const LINE_COLORS = [
  "#1677ff", "#1a7f37", "#e8590c", "#7048e8", "#c2255c",
  "#1098ad", "#5f3dc4", "#2b8a3e", "#d9480f", "#0b7285",
  "#a61e4d", "#4263eb", "#74b816", "#e03131", "#0ca678", "#845ef7",
];
let RENDER_DAYS = [];  // [{date, slots}]
let RENDER_TASK_NAMES = {};  // tid -> name

function renderRunChart() {
  const sel = document.getElementById("run-chart-date");
  const wrap = document.getElementById("run-chart-wrap");
  if (!sel || !RENDER_DAYS.length) return;
  if (!sel.value) { wrap.style.display = "none"; return; }
  wrap.style.display = "block";

  const day = RENDER_DAYS.find(d => d.date === sel.value);
  if (!day) return;
  const times = day.slots.map(s => s.read_at);
  const tasks = day.taskIds;

  // 每任务 {tid -> [cost at each slot]}（缺失=null）
  const series = {};
  tasks.forEach(tid => { series[tid] = times.map(() => null); });
  day.slots.forEach((s, i) => {
    (s.tasks || []).forEach(t => {
      const tid = String(t.task_id);
      if (series[tid]) series[tid][i] = (t.metrics || {}).cost_yuan ?? null;
    });
  });

  const W = 900, H = 300, PL = 56, PR = 16, PT = 16, PB = 30;
  const iw = W - PL - PR, ih = H - PT - PB;
  let maxV = 0;
  tasks.forEach(tid => series[tid].forEach(v => { if (v !== null && v > maxV) maxV = v; }));
  maxV = maxV * 1.08 || 1;

  const x = i => PL + i * iw / Math.max(1, times.length - 1);
  const y = v => PT + ih - (v / maxV) * ih;
  const xLabels = times.map((ts, i) => {
    if (times.length <= 12 || i % Math.ceil(times.length / 12) === 0)
      return "<text x='" + x(i).toFixed(1) + "' y='" + (H - 8).toFixed(1) + "' font-size='10' fill='#666' text-anchor='middle'>" + esc(ts.slice(11, 16)) + "</text>";
    return "";
  }).join("");
  const yTicks = Array.from({ length: 5 }, (_, i) => {
    const v = maxV * (4 - i) / 4;
    return "<text x='" + (PL - 6).toFixed(1) + "' y='" + (PT + ih * i / 4 + 3).toFixed(1) + "' font-size='10' fill='#666' text-anchor='end'>" + fmtNum(v) + "</text>" +
      "<line x1='" + PL + "' x2='" + (W - PR) + "' y1='" + (PT + ih * i / 4).toFixed(1) + "' y2='" + (PT + ih * i / 4).toFixed(1) + "' stroke='#eef1f5' stroke-width='1'/>";
  }).join("");

  const lines = tasks.map((tid, ti) => {
    const pts = [];
    series[tid].forEach((v, i) => { if (v !== null) pts.push(x(i).toFixed(1) + "," + y(v).toFixed(1)); });
    if (pts.length < 2) return "";
    const color = LINE_COLORS[ti % LINE_COLORS.length];
    return "<polyline points='" + pts.join(" ") + "' fill='none' stroke='" + color + "' stroke-width='1.8' opacity='0.9'/>";
  }).join("");

  // 悬停提示：每任务最后一个可见点画小圆 + title
  const dots = tasks.map((tid, ti) => {
    const arr = series[tid];
    let lastI = -1;
    arr.forEach((v, i) => { if (v !== null) lastI = i; });
    if (lastI < 0) return "";
    const color = LINE_COLORS[ti % LINE_COLORS.length];
    const name = RENDER_TASK_NAMES[tid] || tid;
    const v = arr[lastI];
    return "<circle cx='" + x(lastI).toFixed(1) + "' cy='" + y(v).toFixed(1) + "' r='3' fill='" + color + "'><title>" + esc(name) + " " + fmtNum(v) + " 元</title></circle>";
  }).join("");

  const legend = tasks.map((tid, ti) => {
    const color = LINE_COLORS[ti % LINE_COLORS.length];
    return "<span class='lg'><i style='background:" + color + "'></i>" + esc(RENDER_TASK_NAMES[tid] || tid) + "</span>";
  }).join("");

  document.getElementById("run-chart-svg").innerHTML =
    "<svg viewBox='0 0 " + W + " " + H + "' style='width:100%;height:auto;background:#fff;border-radius:8px;'>" +
    yTicks + xLabels + lines + dots + "</svg>";
  document.getElementById("run-chart-legend").innerHTML = legend;
  // 当天累计消耗总值：优先取最后一拍 summary 官方合计，缺失则任务求和
  const lastSlot = day.slots[day.slots.length - 1];
  const lastSum = (lastSlot.summary || {}).cost_yuan;
  const totalCost = (lastSum !== undefined && lastSum !== null)
    ? lastSum
    : day.taskIds.reduce((a, tid) => a + (series[tid][series[tid].length - 1] || 0), 0);
  document.getElementById("run-chart-title").textContent =
    "追投跑动 · " + sel.value + "（" + times.length + " 个分时，累计消耗总值 " + fmtNum(totalCost) +
    " 元，" + tasks.length + " 个任务）";
}

async function loadRunChart() {
  const history = await loadJSONL(FILES.history);
  const byDay = {};
  for (const s of history) {
    const d = (s.read_at || "").slice(0, 10);
    if (!d) continue;
    if (!byDay[d]) byDay[d] = [];
    byDay[d].push(s);
  }
  const dates = Object.keys(byDay).sort();
  RENDER_DAYS = dates.map(d => {
    const slots = byDay[d].sort((a, b) => (a.read_at || "").localeCompare(b.read_at || ""));
    const taskIds = [];
    const seen = new Set();
    slots.forEach(s => (s.tasks || []).forEach(t => {
      const tid = String(t.task_id);
      if (!seen.has(tid)) { seen.add(tid); taskIds.push(tid); }
      RENDER_TASK_NAMES[tid] = t.task_name || tid;
    }));
    return { date: d, slots, taskIds };
  });
  const sel = document.getElementById("run-chart-date");
  const prev = sel.value;
  sel.innerHTML = RENDER_DAYS.map(d =>
    "<option value='" + d.date + "'>" + d.date + "（" + d.slots.length + " 分时）</option>"
  ).join("");
  sel.value = prev && byDay[prev] ? prev : RENDER_DAYS[RENDER_DAYS.length - 1].date;
  renderRunChart();
}

/* ---------- 轮询 ---------- */
async function refresh() {
  const page = document.body.getAttribute("data-page");
  try {
    if (page === "index") { await renderIndex(); await loadRunChart(); }
    else if (page === "timeline") await renderTimeline();
    else if (page === "runs") await renderRuns();
    else if (page === "daily") { await renderDaily(); await renderTaskTrend(); }
    setStatus("更新于 " + new Date().toLocaleTimeString("zh-CN", { hour12: false }));
  } catch (e) {
    setStatus("加载失败: " + e.message + "（请确认 serve_dashboard.py 在运行）");
  }
}
document.addEventListener("DOMContentLoaded", function () {
  refresh();
  setInterval(refresh, POLL_MS);
});
