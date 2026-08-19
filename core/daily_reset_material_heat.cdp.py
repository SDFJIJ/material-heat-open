# 每日 6:00 开盘重置：所有素材追投计划预算统一为 1000，然后全部开启
# 逻辑：list-required 读全量 → 预算≠1000 的调成 1000 → 可开启的全部 reopen
# Usage:
#   export BU_CDP_URL=http://127.0.0.1:9223
#   QC_DRY_RUN=1 browser-harness < scripts/daily_reset_material_heat.cdp.py   # dry-run
#   browser-harness < scripts/daily_reset_material_heat.cdp.py                # 真实执行

import json
import os
import pathlib
import sys

PROJECT_DIR = pathlib.Path(r"C:\Users\fmy\qcqianchuan")
for candidate in (PROJECT_DIR / "scripts", pathlib.Path.cwd(), pathlib.Path.cwd() / "scripts"):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from qianchuan_account_context import load_account_context

DRY_RUN = os.environ.get("QC_DRY_RUN", "0") == "1"

ACCOUNT = load_account_context()
AAVID = ACCOUNT.aavid
PRIMARY_AD_ID = ACCOUNT.primary_ad_id
ASSIST_TASK_SCENE = ACCOUNT.assist_task_scene
GFVERSION = ACCOUNT.gfversion
TARGET_URL = ACCOUNT.target_url

TARGET_BUDGET_YUAN = 1000.0


def ensure_qianchuan_origin():
    current = page_info()
    current_url = current.get("url") or ""
    if "qianchuan.jinritemai.com" not in current_url:
        new_tab(TARGET_URL)
        wait_for_load()
        current = page_info()
        current_url = current.get("url") or ""
    if "qianchuan.jinritemai.com" not in current_url:
        print(json.dumps({
            "ok": False,
            "error": "not_on_qianchuan_page_or_login_redirect",
            "page_url": current_url,
            "hint": "请先在 9223 千川专用 Chrome 登录 qianchuan.jinritemai.com，再重跑。",
        }, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    observed = json.loads(js("JSON.stringify({url:location.href,text:document.body.innerText.slice(0,3000)})"))
    if (("aavid=" in observed.get("url", "") and ("aavid=" + AAVID) not in observed.get("url", ""))
            or ("ID：" + AAVID) not in observed.get("text", "")):
        print(json.dumps({
            "ok": False,
            "error": "account_context_mismatch",
            "configured_account": ACCOUNT.alias,
            "expected_aavid": AAVID,
            "hint": "No reset write was attempted.",
        }, ensure_ascii=False, indent=2))
        raise SystemExit(0)


ensure_qianchuan_origin()

JS = r"""
(function(){
  var AAVID = '__AAVID__';
  var PRIMARY_AD_ID = '__PRIMARY_AD_ID__';
  var ASSIST_TASK_SCENE = __ASSIST_TASK_SCENE__;
  var GFVERSION = '__GFVERSION__';
  var TARGET_BUDGET_YUAN = __TARGET_BUDGET_YUAN__;
  var DRY_RUN = __DRY_RUN__;
  var AMP = String.fromCharCode(38);
  function resolvedGfversion(){
    if (GFVERSION && GFVERSION !== 'auto') return GFVERSION;
    var entries = performance.getEntriesByType('resource') || [];
    for (var gi = entries.length - 1; gi >= 0; gi--) {
      var gm = String(entries[gi].name || '').match(/[?&]gfversion=([^&]+)/);
      if (gm && gm[1]) return decodeURIComponent(gm[1]);
    }
    return '';
  }
  var EFFECTIVE_GFVERSION = resolvedGfversion();
  function pad2(n){ return String(n).padStart(2,'0'); }
  function todayStr(){
    var d = new Date();
    return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate());
  }
  function nowStr(){
    var d = new Date();
    return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate())+' '+pad2(d.getHours())+':'+pad2(d.getMinutes())+':'+pad2(d.getSeconds());
  }
  function postJson(path, body){
    if (!EFFECTIVE_GFVERSION) return {http_status:0, body:{status_code:-1, message:'gfversion unavailable'}};
    var url = path + '?aavid=' + AAVID + AMP + 'gfversion=' + EFFECTIVE_GFVERSION;
    var x = new XMLHttpRequest();
    x.open('POST', url, false);
    x.withCredentials = true;
    x.setRequestHeader('Content-Type','application/json');
    x.send(JSON.stringify(body));
    var parsed = null;
    try { parsed = JSON.parse(x.responseText); }
    catch(e) { parsed = {status_code:-1, message:'JSON parse error: '+String(e), text:String(x.responseText||'').slice(0,500)}; }
    return {http_status:x.status, body:parsed};
  }
  function moneyFromMicros(m){
    var n = Number(m || 0) / 100000;
    return Math.round(n * 100) / 100;
  }
  function opEditable(info, key){
    try { return !!info.operation[key].editable; } catch(e) { return false; }
  }
  function opVisible(info, key){
    try { return !!info.operation[key].visible; } catch(e) { return false; }
  }
  function controlStatus(info){
    if (opVisible(info, 'pause')) return '调控中';
    if (opVisible(info, 'start')) return '已暂停';
    if (opVisible(info, 'finish')) return '可停止';
    return '未知';
  }
  function listTasks(){
    var day = todayStr();
    var listBody = {
      _origin_ajax_: 1,
      UseNewChain: true,
      Params: {
        SophonxDataSetKey: 'overall_live_combine_heat',
        AdFilter: {
          MarGoal: 2,
          DataTimeRange: {StartTime: day + ' 00:00:00', EndTime: day + ' 23:59:59'},
          AssistTaskFilter: {PrimaryAID: PRIMARY_AD_ID, AssistTaskScene: ASSIST_TASK_SCENE}
        },
        OrderBy: {Type: 2, Field: 'create_time'},
        PageParams: {Page: 1, PageSize: 50},
        Metrics: [],
        ListAdsModules: [10, 31, 9, 30, 7, 36, 44]
      },
      aavid: AAVID
    };
    var r = postJson('/ad/api/pmc/v1/uni-promotion/ad/list-required', listBody);
    var adInfos = (((r.body || {}).data || {}).adInfos) || [];
    var tasks = adInfos.map(function(ad){
      var info = (ad.assistTaskInfoMap || {})[String(ASSIST_TASK_SCENE)] || (ad.assistTaskInfoMap || {})[ASSIST_TASK_SCENE] || {};
      return {
        task_id: String(ad.id || ''),
        task_name: ad.name || '',
        delivery_status: ad.adDeliveryName || '',
        budget_yuan: moneyFromMicros(ad.budget),
        control_status: controlStatus(info),
        can_start: opEditable(info, 'start'),
        can_pause: opEditable(info, 'pause'),
        can_edit: opEditable(info, 'edit')
      };
    });
    return {api: {http_status:r.http_status, status_code:(r.body||{}).status_code, message:(r.body||{}).message || ''}, tasks: tasks};
  }

  var before = listTasks();
  if (before.api.status_code !== 0) {
    return JSON.stringify({ok:false, read_at:nowStr(), error:'list-required failed', before_api:before.api});
  }

  // 1) 预算统一为 1000（仅预算≠1000 且可编辑的任务）
  var needBudget = before.tasks.filter(function(t){ return t.budget_yuan !== TARGET_BUDGET_YUAN && t.can_edit; });
  var budgetResponses = [];
  if (!DRY_RUN && needBudget.length > 0) {
    for (var bi = 0; bi < needBudget.length; bi += 10) {
      var bBatch = needBudget.slice(bi, bi + 10);
      budgetResponses.push(postJson('/ad/api/pmc/v1/batch_update_budget', {
        ForceAsync: false,
        AdsData: bBatch.map(function(t){ return {AdId: t.task_id, AdBudget: Math.round(TARGET_BUDGET_YUAN * 100000)}; })
      }));
    }
  }

  // 2) 全部开启（仅可开启的任务）
  var toStart = before.tasks.filter(function(t){ return t.can_start; });
  var startResponses = [];
  if (!DRY_RUN && toStart.length > 0) {
    for (var si = 0; si < toStart.length; si += 10) {
      var sBatch = toStart.slice(si, si + 10);
      startResponses.push(postJson('/ad/api/pmc/v1/batch_update_operation', {
        optType: 1,
        objects: sBatch.map(function(t){ return {objectID: t.task_id, type: 1}; })
      }));
    }
  }

  // 3) 读回验证
  var after = listTasks();
  var afterById = {};
  after.tasks.forEach(function(t){ afterById[t.task_id] = t; });

  var budgetResults = needBudget.map(function(t){
    var a = afterById[t.task_id] || {};
    return {
      task_id: t.task_id,
      task_name: t.task_name,
      budget_before: t.budget_yuan,
      budget_after: a.budget_yuan,
      budget_ok: a.budget_yuan === TARGET_BUDGET_YUAN
    };
  });
  var startResults = toStart.map(function(t){
    var a = afterById[t.task_id] || {};
    return {
      task_id: t.task_id,
      task_name: t.task_name,
      before: t.control_status,
      after: a.control_status || '未返回',
      verified_running: a.control_status === '调控中' || a.can_pause === true
    };
  });

  return JSON.stringify({
    ok: true,
    read_at: nowStr(),
    dry_run: DRY_RUN,
    attempted_budget_adjust: needBudget.length,
    attempted_start: toStart.length,
    before_counts: {
      total: before.tasks.length,
      budget_not_1000: needBudget.length,
      can_start: toStart.length,
      running: before.tasks.filter(function(t){return t.control_status === '调控中';}).length,
      paused: before.tasks.filter(function(t){return t.control_status === '已暂停';}).length
    },
    budget_write: DRY_RUN ? {skipped: true, reason: 'dry-run'} : budgetResponses.map(function(w){
      return {http_status: w.http_status, status_code: w.body && w.body.status_code, message: (w.body && w.body.message) || ''};
    }),
    start_write: DRY_RUN ? {skipped: true, reason: 'dry-run'} : (startResponses.length ? startResponses.map(function(w){
      return {http_status: w.http_status, status_code: w.body && w.body.status_code, message: (w.body && w.body.message) || ''};
    }) : {skipped: true, reason: 'no can_start tasks'}),
    after_counts: {
      total: after.tasks.length,
      running: after.tasks.filter(function(t){return t.control_status === '调控中';}).length,
      paused: after.tasks.filter(function(t){return t.control_status === '已暂停';}).length,
      can_start: after.tasks.filter(function(t){return t.can_start;}).length
    },
    budget_results: budgetResults,
    start_results: startResults
  });
})()
""".replace("__AAVID__", AAVID).replace("__PRIMARY_AD_ID__", PRIMARY_AD_ID).replace("__ASSIST_TASK_SCENE__", str(ASSIST_TASK_SCENE)).replace("__GFVERSION__", GFVERSION).replace("__TARGET_BUDGET_YUAN__", str(TARGET_BUDGET_YUAN)).replace("__DRY_RUN__", "true" if DRY_RUN else "false")

print(js(JS))
