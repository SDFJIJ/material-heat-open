# 一键开启所有千川素材追投计划（仅重启当前可开启/已暂停的追投任务）
# Usage:
#   export BU_CDP_URL=http://127.0.0.1:9223
#   browser-harness < C:/Users/fmy/qcqianchuan/scripts/reopen_all_material_heat_once.cdp.py

import json
import pathlib
import sys

PROJECT_DIR = pathlib.Path(r"C:\Users\fmy\qcqianchuan")
for candidate in (PROJECT_DIR / "scripts", pathlib.Path.cwd(), pathlib.Path.cwd() / "scripts"):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from qianchuan_account_context import load_account_context

ACCOUNT = load_account_context()
AAVID = ACCOUNT.aavid
PRIMARY_AD_ID = ACCOUNT.primary_ad_id
ASSIST_TASK_SCENE = ACCOUNT.assist_task_scene
GFVERSION = ACCOUNT.gfversion
TARGET_URL = ACCOUNT.target_url


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
            "hint": "No reopen write was attempted.",
        }, ensure_ascii=False, indent=2))
        raise SystemExit(0)


ensure_qianchuan_origin()

JS = r"""
(function(){
  var AAVID = '__AAVID__';
  var PRIMARY_AD_ID = '__PRIMARY_AD_ID__';
  var ASSIST_TASK_SCENE = __ASSIST_TASK_SCENE__;
  var GFVERSION = '__GFVERSION__';
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
        control_status: controlStatus(info),
        can_start: opEditable(info, 'start'),
        can_pause: opEditable(info, 'pause')
      };
    });
    return {api: {http_status:r.http_status, status_code:(r.body||{}).status_code, message:(r.body||{}).message || ''}, tasks: tasks};
  }

  var before = listTasks();
  if (before.api.status_code !== 0) {
    return JSON.stringify({ok:false, read_at:nowStr(), error:'list-required failed', before_api:before.api});
  }
  var toStart = before.tasks.filter(function(t){ return t.can_start; });
  var writeResponses = [];
  if (toStart.length > 0) {
    for (var start = 0; start < toStart.length; start += 10) {
      var batch = toStart.slice(start, start + 10);
      writeResponses.push(postJson('/ad/api/pmc/v1/batch_update_operation', {
        optType: 1,
        objects: batch.map(function(t){ return {objectID: t.task_id, type: 1}; })
      }));
    }
  }
  var after = listTasks();
  var afterById = {};
  after.tasks.forEach(function(t){ afterById[t.task_id] = t; });
  var results = toStart.map(function(t){
    var a = afterById[t.task_id] || {};
    return {
      task_id: t.task_id,
      task_name: t.task_name,
      before: t.control_status,
      after: a.control_status || '未返回',
      after_delivery_status: a.delivery_status || '',
      verified_running: a.control_status === '调控中' || a.can_pause === true
    };
  });
  return JSON.stringify({
    ok: true,
    read_at: nowStr(),
    attempted_count: toStart.length,
    before_counts: {
      total: before.tasks.length,
      can_start: toStart.length,
      running: before.tasks.filter(function(t){return t.control_status === '调控中';}).length,
      paused: before.tasks.filter(function(t){return t.control_status === '已暂停';}).length
    },
    write: writeResponses.length ? writeResponses.map(function(writeResp){
      return {http_status: writeResp.http_status, status_code: writeResp.body && writeResp.body.status_code, message: (writeResp.body && writeResp.body.message) || ''};
    }) : {skipped: true, reason: 'no can_start tasks'},
    after_counts: {
      total: after.tasks.length,
      running: after.tasks.filter(function(t){return t.control_status === '调控中';}).length,
      paused: after.tasks.filter(function(t){return t.control_status === '已暂停';}).length,
      can_start: after.tasks.filter(function(t){return t.can_start;}).length
    },
    results: results
  });
})()
""".replace("__AAVID__", AAVID).replace("__PRIMARY_AD_ID__", PRIMARY_AD_ID).replace("__ASSIST_TASK_SCENE__", str(ASSIST_TASK_SCENE)).replace("__GFVERSION__", GFVERSION)

print(js(JS))
