# Read 千川素材追投实时状态 via logged-in Chrome CDP profile.
# Usage:
#   export BU_CDP_URL=http://127.0.0.1:9223
#   browser-harness < C:/Users/fmy/qcqianchuan/scripts/read_material_heat_realtime.cdp.py

import json
import os
import pathlib
import sys

# browser-harness executes stdin via exec(), so __file__ may be '<string>'.
# Add the stable project scripts dir explicitly so the documented absolute
# stdin invocation works even when the current working directory is elsewhere.
PROJECT_DIR = pathlib.Path(r"C:\Users\fmy\qcqianchuan")
for candidate in (
    PROJECT_DIR / "scripts",
    pathlib.Path.cwd(),
    pathlib.Path.cwd() / "scripts",
    pathlib.Path(globals().get("__file__", "")).resolve().parent,
):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from material_heat_execution import execute_actions
from material_heat_storage import (
    append_run_log,
    apply_execution_state,
    build_brief,
    build_display_overlay,
    detect_manual_adjustments,
    last_history_snapshot,
    save_snapshot,
)
from material_heat_strategy import STRATEGY_CONFIG, build_strategy, config_for_target_roi
from qianchuan_account_context import load_account_context

# All scheduled/read entrypoints follow config.active_account. Avoid an old
# browser-harness or terminal QC_ACCOUNT leaking across account switches.
os.environ.pop("QC_ACCOUNT", None)

# Default is read-only. Set QC_DRY_RUN=0 only for explicitly authorized writes.
_DRY_RUN = os.environ.get("QC_DRY_RUN", "1") in ("1", "true", "yes")
ACCOUNT = load_account_context()


def _strategy_config_from_env():
    raw = os.environ.get("QC_TARGET_ROI")
    if not raw:
        return config_for_target_roi(ACCOUNT.target_roi)
    try:
        target_roi = float(raw)
    except ValueError:
        print(json.dumps({
            "ok": False,
            "schema": "qianchuan.material_heat.realtime.v1",
            "error": "invalid_QC_TARGET_ROI",
            "value": raw,
            "hint": "Set QC_TARGET_ROI to a number, e.g. 3.0",
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    return config_for_target_roi(target_roi)


STRATEGY_RUNTIME_CONFIG = _strategy_config_from_env()

AAVID = ACCOUNT.aavid
PRIMARY_AD_ID = ACCOUNT.primary_ad_id
ASSIST_TASK_SCENE = ACCOUNT.assist_task_scene
ASSIST_TASK_SCENE_NAME = "素材追投"
DATASET = "overall_live_combine_heat"
GFVERSION = ACCOUNT.gfversion
OUT_PATH = ACCOUNT.data_dir / "material_heat_realtime_latest.json"
HISTORY_PATH = ACCOUNT.data_dir / "material_heat_realtime_history.jsonl"
STRATEGY_PATH = ACCOUNT.data_dir / "material_heat_strategy_latest.json"
RUN_LOG_PATH = ACCOUNT.data_dir / "material_heat_runs.jsonl"
TARGET_URL = ACCOUNT.target_url


_EPHEMERAL_TARGET_ID = None


def _target_infos():
    raw = cdp("Target.getTargets") or {}
    return raw.get("targetInfos") or (raw.get("result") or {}).get("targetInfos") or []


def _is_matching_detail_tab(url):
    return (
        "qianchuan.jinritemai.com/uni-prom/detail" in (url or "")
        and ("aavid=" + AAVID) in url
        and ("adId=" + PRIMARY_AD_ID) in url
    )


def _try_reuse_existing_detail_tab():
    """Try an existing matching tab; verify because CDP activation can be stale."""
    for target in _target_infos():
        if target.get("type") != "page" or not _is_matching_detail_tab(target.get("url") or ""):
            continue
        cdp("Target.activateTarget", targetId=target["targetId"])
        wait_for_load()
        active_url = (page_info().get("url") or "")
        if _is_matching_detail_tab(active_url):
            return True
    return False


def _open_ephemeral_detail_tab():
    """Open a fallback tab only when no usable existing detail tab is available."""
    global _EPHEMERAL_TARGET_ID
    before_ids = {target.get("targetId") for target in _target_infos()}
    new_tab(TARGET_URL)
    wait_for_load()
    for target in _target_infos():
        if target.get("targetId") not in before_ids and _is_matching_detail_tab(target.get("url") or ""):
            _EPHEMERAL_TARGET_ID = target.get("targetId")
            break


def _close_ephemeral_detail_tab():
    if not _EPHEMERAL_TARGET_ID:
        return
    try:
        cdp("Target.closeTarget", targetId=_EPHEMERAL_TARGET_ID)
    except Exception:
        pass


def ensure_qianchuan_origin():
    current_url = page_info().get("url") or ""
    if not _is_matching_detail_tab(current_url):
        if not _try_reuse_existing_detail_tab():
            _open_ephemeral_detail_tab()
        current_url = page_info().get("url") or ""
    if not _is_matching_detail_tab(current_url):
        payload = {
            "ok": False,
            "schema": "qianchuan.material_heat.realtime.v1",
            "error": "matching_detail_tab_unavailable",
            "page_url": current_url,
            "hint": "Open the configured Qianchuan uni-prom/detail page in the CDP Chrome profile, then rerun.",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    observed = js("JSON.stringify({url:location.href,text:document.body.innerText.slice(0,3000)})")
    try:
        observed = json.loads(observed)
    except (TypeError, json.JSONDecodeError):
        observed = {"url": current_url, "text": ""}
    page_url = observed.get("url") or ""
    page_text = observed.get("text") or ""
    # Page no longer renders "ID：<aavid>" (千川改版); it renders the primary
    # plan id. URL aavid+adId match is already enforced by _is_matching_detail_tab;
    # this check adds a rendered-plan confirmation. Still fail-closed.
    plan_marker = "计划ID：" + PRIMARY_AD_ID
    if ("aavid=" in page_url and ("aavid=" + AAVID) not in page_url) or (plan_marker not in page_text):
        print(json.dumps({
            "ok": False,
            "schema": "qianchuan.material_heat.realtime.v1",
            "error": "account_context_mismatch",
            "configured_account": ACCOUNT.alias,
            "expected_aavid": AAVID,
            "expected_plan_marker": plan_marker,
            "page_url": page_url,
            "hint": "Open the configured Qianchuan account in the CDP Chrome profile; no write was attempted.",
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2)


# Browser-harness helpers are absent during static checks; the lifecycle wrapper
# below calls ensure_qianchuan_origin() only in a live CDP execution.

JS_TEMPLATE = r"""
(function(){
  var t0 = performance.now();
  var AAVID = '__AAVID__';
  var PRIMARY_AD_ID = '__PRIMARY_AD_ID__';
  var ASSIST_TASK_SCENE = __ASSIST_TASK_SCENE__;
  var ASSIST_TASK_SCENE_NAME = '__ASSIST_TASK_SCENE_NAME__';
  var DATASET = '__DATASET__';
  var GFVERSION = '__GFVERSION__';
  var AMP = String.fromCharCode(38);

  function resolvedGfversion(){
    if (GFVERSION && GFVERSION !== 'auto') return GFVERSION;
    var entries = performance.getEntriesByType('resource') || [];
    for (var i = entries.length - 1; i >= 0; i--) {
      var m = String(entries[i].name || '').match(/[?&]gfversion=([^&]+)/);
      if (m && m[1]) return decodeURIComponent(m[1]);
    }
    return '';
  }
  var EFFECTIVE_GFVERSION = resolvedGfversion();

  function pad2(n){ return String(n).padStart(2,'0'); }
  function localNow(){
    var d = new Date();
    return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate())+' '+pad2(d.getHours())+':'+pad2(d.getMinutes())+':'+pad2(d.getSeconds());
  }
  function todayStr(){
    var d = new Date();
    return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate());
  }
  function postJson(path, body){
    if (!EFFECTIVE_GFVERSION) {
      return {http_status:0, body:{status_code:-1, message:'gfversion unavailable from configured page; refusing request'}};
    }
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
  function moneyFromMicros(v){
    if (v === undefined || v === null || v === '' || v === '-') return null;
    var n = Number(v);
    if (!isFinite(n)) return null;
    return Math.round(n / 100000 * 100) / 100;
  }
  function roiGoalFromAd(ad){
    var keys = ['ecpRoi2Goal', 'roiGoal', 'roi2Goal', 'pureEcpRoi2Goal', 'payRoiGoal'];
    for (var i = 0; i < keys.length; i++) {
      var v = ad && ad[keys[i]];
      if (v === undefined || v === null || v === '' || v === '-') continue;
      var n = Number(v);
      if (!isFinite(n)) continue;
      if (n > 1000) n = n / 100000;
      return Math.round(n * 100) / 100;
    }
    return null;
  }
  function tsToLocal(sec){
    if (!sec) return null;
    var n = Number(sec);
    if (!isFinite(n) || n <= 0) return null;
    var d = new Date(n * 1000);
    return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate())+' '+pad2(d.getHours())+':'+pad2(d.getMinutes())+':'+pad2(d.getSeconds());
  }
  function mObj(metrics, key){
    var m = metrics && metrics[key];
    if (!m) return {value:null, text:'-'};
    return {value:m.value, text:m.valueStr === undefined ? String(m.value) : m.valueStr};
  }
  function metricNumber(metrics, key){
    var m = metrics && metrics[key];
    return m && m.value !== undefined ? m.value : null;
  }
  function opVisible(info, key){
    try { return !!info.operation[key].visible; } catch(e) { return false; }
  }
  function opEditable(info, key){
    try { return !!info.operation[key].editable; } catch(e) { return false; }
  }
  function controlStatus(info){
    if (opVisible(info, 'pause')) return '调控中';
    if (opVisible(info, 'start')) return '已暂停';
    if (opVisible(info, 'finish')) return '可停止';
    return '未知';
  }
  function materialSummary(arr){
    if (!arr || !arr.length) return {type:'unknown', count:0, text:'-'};
    var first = arr[0] || {};
    if (first.roomMaterial && first.roomMaterial.anchor) {
      return {type:'live_room', count:arr.length, text:first.roomMaterial.anchor.name || '直播间画面'};
    }
    return {type:'video', count:arr.length, text:'共' + arr.length + '条视频'};
  }

  var day = todayStr();
  var metrics = [
    'stat_cost_for_roi2_assist',
    'total_prepay_and_pay_order_roi2_assist',
    'show_cnt_for_roi2_assist',
    'click_cnt_for_roi2_assist',
    'ctr_for_roi2_assist',
    'convert_rate_for_roi2_assist',
    'total_pay_order_count_for_roi2_assist',
    'total_pay_order_gmv_include_coupon_for_roi2_assist',
    'total_cost_per_pay_order_for_roi2_assist',
    'total_pay_order_gmv_for_roi2_assist',
    'total_pay_order_coupon_amount_for_roi2_assist',
    'total_order_settle_amount_for_roi2_1h_assist',
    'total_prepay_and_pay_settle_roi2_1h_assist',
    'total_refund_order_gmv_for_roi2_1h_rate_assist'
  ];

  var summaryBody = {
    SophonxDataSetKey: DATASET,
    AdFilter: {
      MarGoal: 2,
      AdlabMode: 1,
      AssistTaskFilter: {PrimaryAID: PRIMARY_AD_ID, AssistTaskScene: ASSIST_TASK_SCENE},
      StartTime: day + ' 00:00:00',
      EndTime: day + ' 23:59:59'
    },
    Metrics: metrics
  };
  var listBody = {
    _origin_ajax_: 1,
    UseNewChain: true,
    Params: {
      SophonxDataSetKey: DATASET,
      AdFilter: {
        MarGoal: 2,
        DataTimeRange: {StartTime: day + ' 00:00:00', EndTime: day + ' 23:59:59'},
        AssistTaskFilter: {PrimaryAID: PRIMARY_AD_ID, AssistTaskScene: ASSIST_TASK_SCENE}
      },
      OrderBy: {Type: 2, Field: 'create_time'},
      PageParams: {Page: 1, PageSize: 50},
      Metrics: metrics,
      ListAdsModules: [10, 31, 9, 30, 7, 36, 44]
    },
    aavid: AAVID
  };

  var sResp = postJson('/ad/api/pmc/v1/uni-promotion/ad/list-summary', summaryBody);
  var lResp = postJson('/ad/api/pmc/v1/uni-promotion/ad/list-required', listBody);
  var sBody = sResp.body || {};
  var lBody = lResp.body || {};
  var sm = (((sBody.data || {}).totalMetrics || {}).metrics) || {};
  var adInfos = ((lBody.data || {}).adInfos) || [];
  var adStatsMap = ((lBody.data || {}).adStatsMap) || {};
  var materialMap = ((lBody.data || {}).assistTaskMaterialInfoMap) || {};

  var tasks = adInfos.map(function(ad){
    var id = String(ad.id || '');
    var statMetrics = ((adStatsMap[id] || {}).metrics) || {};
    var info = (ad.assistTaskInfoMap || {})[String(ASSIST_TASK_SCENE)] || (ad.assistTaskInfoMap || {})[ASSIST_TASK_SCENE] || {};
    var mat = materialSummary(materialMap[id]);
    return {
      task_id: id,
      task_name: ad.name || '',
      material: mat,
      control_status: controlStatus(info),
      delivery_status: ad.adDeliveryName || '',
      smart_bid_type: ad.smartBidType,
      smart_bid_name: ad.smartBidType === 0 ? '控成本追投' : (ad.smartBidType === 7 ? '放量追投' : String(ad.smartBidType)),
      budget_yuan: moneyFromMicros(ad.budget),
      bid_yuan: moneyFromMicros(ad.bid),
      roi_goal: roiGoalFromAd(ad),
      created_at: tsToLocal(ad.createTime),
      metrics: {
        cost_yuan: metricNumber(statMetrics, 'statCostForRoi2Assist'),
        pay_roi: metricNumber(statMetrics, 'totalPrepayAndPayOrderRoi2Assist'),
        show_cnt: metricNumber(statMetrics, 'showCntForRoi2Assist'),
        click_cnt: metricNumber(statMetrics, 'clickCntForRoi2Assist'),
        ctr_pct: metricNumber(statMetrics, 'ctrForRoi2Assist'),
        convert_rate_pct: metricNumber(statMetrics, 'convertRateForRoi2Assist'),
        pay_order_count: metricNumber(statMetrics, 'totalPayOrderCountForRoi2Assist'),
        pay_gmv_yuan: metricNumber(statMetrics, 'totalPayOrderGmvIncludeCouponForRoi2Assist'),
        order_cost_yuan: metricNumber(statMetrics, 'totalCostPerPayOrderForRoi2Assist'),
        real_pay_yuan: metricNumber(statMetrics, 'totalPayOrderGmvForRoi2Assist'),
        coupon_yuan: metricNumber(statMetrics, 'totalPayOrderCouponAmountForRoi2Assist'),
        net_gmv_yuan: metricNumber(statMetrics, 'totalOrderSettleAmountForRoi21HAssist'),
        net_roi: metricNumber(statMetrics, 'totalPrepayAndPaySettleRoi21HAssist'),
        refund_1h_rate_pct: metricNumber(statMetrics, 'totalRefundOrderGmvForRoi21HRateAssist')
      },
      operations: {
        can_pause: opEditable(info, 'pause'),
        can_start: opEditable(info, 'start'),
        can_edit: opEditable(info, 'edit'),
        can_delete: opEditable(info, 'delete'),
        can_view_stats: opVisible(info, 'statistics')
      }
    };
  });

  var fixed = {
    schema: 'qianchuan.material_heat.realtime.v1',
    read_at: localNow(),
    latency_ms: Math.round(performance.now() - t0),
    date: day,
    source: {
      method: 'cdp_in_page_xhr',
      endpoints: ['POST /ad/api/pmc/v1/uni-promotion/ad/list-summary', 'POST /ad/api/pmc/v1/uni-promotion/ad/list-required'],
      dataset: DATASET
    },
    account: {aavid: AAVID},
    primary_ad: {ad_id: PRIMARY_AD_ID, assist_task_scene: ASSIST_TASK_SCENE, assist_task_scene_name: ASSIST_TASK_SCENE_NAME},
    account_context: {alias: '__ACCOUNT_ALIAS__', gfversion: EFFECTIVE_GFVERSION},
    api_status: {
      list_summary: {http_status: sResp.http_status, status_code: sBody.status_code, message: sBody.message || ''},
      list_required: {http_status: lResp.http_status, status_code: lBody.status_code, message: lBody.message || ''}
    },
    summary: {
      task_total: Number((sBody.data || {}).totalNum || tasks.length),
      task_returned: tasks.length,
      controlling_count: tasks.filter(function(t){return t.control_status === '调控中';}).length,
      paused_count: tasks.filter(function(t){return t.control_status === '已暂停';}).length,
      task_budget_sum_yuan: Math.round(tasks.reduce(function(a,t){return a + (t.budget_yuan || 0);}, 0) * 100) / 100,
      budget_pool_total_yuan: null,
      budget_pool_available_yuan: null,
      cost_yuan: metricNumber(sm, 'statCostForRoi2Assist'),
      pay_roi: metricNumber(sm, 'totalPrepayAndPayOrderRoi2Assist'),
      show_cnt: metricNumber(sm, 'showCntForRoi2Assist'),
      click_cnt: metricNumber(sm, 'clickCntForRoi2Assist'),
      ctr_pct: metricNumber(sm, 'ctrForRoi2Assist'),
      convert_rate_pct: metricNumber(sm, 'convertRateForRoi2Assist'),
      pay_order_count: metricNumber(sm, 'totalPayOrderCountForRoi2Assist'),
      pay_gmv_yuan: metricNumber(sm, 'totalPayOrderGmvIncludeCouponForRoi2Assist'),
      order_cost_yuan: metricNumber(sm, 'totalCostPerPayOrderForRoi2Assist'),
      real_pay_yuan: metricNumber(sm, 'totalPayOrderGmvForRoi2Assist'),
      coupon_yuan: metricNumber(sm, 'totalPayOrderCouponAmountForRoi2Assist'),
      net_gmv_yuan: metricNumber(sm, 'totalOrderSettleAmountForRoi21HAssist'),
      net_roi: metricNumber(sm, 'totalPrepayAndPaySettleRoi21HAssist'),
      refund_1h_rate_pct: metricNumber(sm, 'totalRefundOrderGmvForRoi21HRateAssist')
    },
    summary_text: {
      cost_yuan: mObj(sm, 'statCostForRoi2Assist').text,
      pay_roi: mObj(sm, 'totalPrepayAndPayOrderRoi2Assist').text,
      show_cnt: mObj(sm, 'showCntForRoi2Assist').text,
      click_cnt: mObj(sm, 'clickCntForRoi2Assist').text,
      ctr_pct: mObj(sm, 'ctrForRoi2Assist').text,
      convert_rate_pct: mObj(sm, 'convertRateForRoi2Assist').text,
      pay_order_count: mObj(sm, 'totalPayOrderCountForRoi2Assist').text,
      pay_gmv_yuan: mObj(sm, 'totalPayOrderGmvIncludeCouponForRoi2Assist').text,
      order_cost_yuan: mObj(sm, 'totalCostPerPayOrderForRoi2Assist').text,
      real_pay_yuan: mObj(sm, 'totalPayOrderGmvForRoi2Assist').text,
      coupon_yuan: mObj(sm, 'totalPayOrderCouponAmountForRoi2Assist').text,
      net_gmv_yuan: mObj(sm, 'totalOrderSettleAmountForRoi21HAssist').text,
      net_roi: mObj(sm, 'totalPrepayAndPaySettleRoi21HAssist').text,
      refund_1h_rate_pct: mObj(sm, 'totalRefundOrderGmvForRoi21HRateAssist').text
    },
    tasks: tasks
  };
  return JSON.stringify(fixed);
})()
"""


def collect_realtime_snapshot():
    rendered_js = (
        JS_TEMPLATE
        .replace("__AAVID__", AAVID)
        .replace("__PRIMARY_AD_ID__", PRIMARY_AD_ID)
        .replace("__ASSIST_TASK_SCENE__", str(ASSIST_TASK_SCENE))
        .replace("__ASSIST_TASK_SCENE_NAME__", ASSIST_TASK_SCENE_NAME)
        .replace("__DATASET__", DATASET)
        .replace("__GFVERSION__", GFVERSION)
        .replace("__ACCOUNT_ALIAS__", ACCOUNT.alias)
    )
    return json.loads(js(rendered_js))


def main():
    data = collect_realtime_snapshot()
    previous = last_history_snapshot(HISTORY_PATH)
    # c 态检测：必须在新的策略执行之前。比对上一轮策略执行后的期望值 vs 本轮读取值，
    # 差异即用户手动调整。检测结果写进 strategy 供前端显示（快照文件不动）。
    prev_run = None
    if previous:
        try:
            run_rows = [json.loads(l) for l in RUN_LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
            prev_run = next((r for r in reversed(run_rows) if r.get("read_at") == previous.get("read_at")), None)
        except Exception:
            prev_run = None
    manual_adjustments = detect_manual_adjustments(previous, prev_run, data)
    data["strategy"] = build_strategy(data, previous, STRATEGY_RUNTIME_CONFIG, dry_run=_DRY_RUN)
    data["strategy"]["manual_adjustments"] = manual_adjustments
    apply_execution_state(
        data["strategy"],
        dry_run=_DRY_RUN,
        executor=lambda actions: execute_actions(actions, js, ACCOUNT),
    )
    # 三态合并成 display_overlay：前端只读此结构渲染（a 快照 / b 策略黄 / c 手动蓝）
    data["strategy"]["display_overlay"] = build_display_overlay(
        data, data["strategy"], manual_adjustments=manual_adjustments
    )
    save_snapshot(data, out_path=OUT_PATH, strategy_path=STRATEGY_PATH, history_path=HISTORY_PATH)
    append_run_log(ACCOUNT.data_dir / "material_heat_runs.jsonl", data)
    print(json.dumps(build_brief(data, STRATEGY_PATH, OUT_PATH), ensure_ascii=False, indent=2))


def run():
    try:
        try:
            ensure_qianchuan_origin()
        except NameError:
            # Allows syntax/static checks outside browser-harness; browser execution is required.
            return
        main()
    finally:
        _close_ephemeral_detail_tab()


run()
