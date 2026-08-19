import json as _json


def build_exec_js(actions, account):
    """Generate account-verified write JS for browser CDP context.

    Budget, bid, and ROI-goal edits use the dedicated lightweight endpoints
    verified against live MaterialHeat assist tasks on 2026-07-22.
    """
    aavid = _json.dumps(account.aavid)
    primary_ad_id = _json.dumps(account.primary_ad_id)
    scene = int(account.assist_task_scene)
    gfversion = _json.dumps(account.gfversion)
    lines = [
        "(function(){",
        "  var results = [];",
        "  var AAVID = " + aavid + ";",
        "  var PRIMARY_AD_ID = " + primary_ad_id + ";",
        "  var ASSIST_TASK_SCENE = " + str(scene) + ";",
        "  var GFVERSION = " + gfversion + ";",
        "  var AMP = String.fromCharCode(38);",
        "  var accountMarker = '计划ID：' + PRIMARY_AD_ID;",
        "  if ((document.body.innerText || '').indexOf(accountMarker) < 0) {",
        "    return JSON.stringify({ok:false, error:'account_context_mismatch', expected_aavid:AAVID, expected_plan_marker:accountMarker});",
        "  }",
        "  function resolvedGfversion(){",
        "    if (GFVERSION && GFVERSION !== 'auto') return GFVERSION;",
        "    var entries = performance.getEntriesByType('resource') || [];",
        "    for (var i = entries.length - 1; i >= 0; i--) {",
        "      var m = String(entries[i].name || '').match(/[?&]gfversion=([^&]+)/);",
        "      if (m && m[1]) return decodeURIComponent(m[1]);",
        "    }",
        "    return '';",
        "  }",
        "  var EFFECTIVE_GFVERSION = resolvedGfversion();",
        "  if (!EFFECTIVE_GFVERSION) {",
        "    return JSON.stringify({ok:false, error:'gfversion_unavailable'});",
        "  }",
        "  function pad2(n){ return String(n).padStart(2,'0'); }",
        "  function todayStr(){",
        "    var d = new Date();",
        "    return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate());",
        "  }",
        "  var day = todayStr();",
        "  function postJson(path, body){",
        "    var url = path + '?aavid=' + AAVID + AMP + 'gfversion=' + EFFECTIVE_GFVERSION;",
        "    var x = new XMLHttpRequest();",
        "    x.open('POST', url, false);",
        "    x.withCredentials = true;",
        "    x.setRequestHeader('Content-Type','application/json');",
        "    x.send(JSON.stringify(body));",
        "    var parsed = null;",
        "    try { parsed = JSON.parse(x.responseText); } catch(e) { parsed = {error:String(e), text:String(x.responseText || '').slice(0,200)}; }",
        "    return {http_status:x.status, body:parsed};",
        "  }",
        "  var listBody = {",
        "    _origin_ajax_:1, UseNewChain:true,",
        "    Params:{",
        "      SophonxDataSetKey:'overall_live_combine_heat',",
        "      AdFilter:{",
        "        MarGoal:2,",
        "        DataTimeRange:{StartTime:day+' 00:00:00', EndTime:day+' 23:59:59'},",
        "        AssistTaskFilter:{PrimaryAID:PRIMARY_AD_ID, AssistTaskScene:ASSIST_TASK_SCENE}",
        "      },",
        "      OrderBy:{Type:2, Field:'create_time'},",
        "      PageParams:{Page:1, PageSize:50},",
        "      Metrics:[],",
        "      ListAdsModules:[10,31,9,30,7,36,44]",
        "    },",
        "    aavid:AAVID",
        "  };",
        "  var lr = postJson('/ad/api/pmc/v1/uni-promotion/ad/list-required', listBody);",
        "  if (!lr.body || lr.body.status_code !== 0) {",
        "    return JSON.stringify({ok:false, error:'pre_read_failed', pre_read:lr.body || {}});",
        "  }",
        "  var adInfos = ((lr.body.data || {}).adInfos) || [];",
        "  var deepExternalActionMap = {};",
        "  adInfos.forEach(function(a){",
        "    if (a.deepExternalAction !== undefined && a.deepExternalAction !== null) {",
        "      deepExternalActionMap[String(a.id)] = a.deepExternalAction;",
        "    }",
        "  });",
    ]
    for i, action in enumerate(actions):
        task_id = _json.dumps(action["task_id"])
        action_type = action["action"]
        if action_type == "pause":
            lines.append(f"  var r{i} = postJson('/ad/api/pmc/v1/batch_update_operation', {{optType:2, objects:[{{objectID:{task_id}, type:1}}]}});")
            lines.append(f"  results.push({{action:'pause', task_id:{task_id}, endpoint:'batch_update_operation', ok:!!(r{i}.body && r{i}.body.status_code===0), status_code:r{i}.body && r{i}.body.status_code, message:(r{i}.body && r{i}.body.message) || ''}});")
        elif action_type == "reopen":
            lines.append(f"  var r{i} = postJson('/ad/api/pmc/v1/batch_update_operation', {{optType:1, objects:[{{objectID:{task_id}, type:1}}]}});")
            lines.append(f"  results.push({{action:'reopen', task_id:{task_id}, endpoint:'batch_update_operation', ok:!!(r{i}.body && r{i}.body.status_code===0), status_code:r{i}.body && r{i}.body.status_code, message:(r{i}.body && r{i}.body.message) || ''}});")
        elif action_type == "increase_budget":
            budget_micros = int(action.get("new_budget_yuan", 0) * 100000)
            lines.append(f"  var r{i} = postJson('/ad/api/pmc/v1/batch_update_budget', {{ForceAsync:false, AdsData:[{{AdId:{task_id}, AdBudget:{budget_micros}}}]}});")
            lines.append(f"  results.push({{action:'increase_budget', task_id:{task_id}, endpoint:'batch_update_budget', new_budget_yuan:{action.get('new_budget_yuan', 0)}, ok:!!(r{i}.body && r{i}.body.status_code===0), status_code:r{i}.body && r{i}.body.status_code, message:(r{i}.body && r{i}.body.message) || ''}});")
        elif action_type in ("pressure_price", "raise_price"):
            change = action.get("preferred_change") or {}
            field = change.get("field", "")
            new_value = change.get("new", 0)
            if field == "bid_yuan":
                bid_micros = int(new_value * 100000)
                lines.append(f"  var r{i} = postJson('/ad/api/promotion/v1/batch_update_bid', {{updateBidInfos:[{{id:{task_id}, value:{bid_micros}}}]}});")
                lines.append(f"  results.push({{action:'{action_type}', task_id:{task_id}, endpoint:'batch_update_bid', field:'bid', new_value:{new_value}, ok:!!(r{i}.body && r{i}.body.status_code===0), status_code:r{i}.body && r{i}.body.status_code, message:(r{i}.body && r{i}.body.message) || ''}});")
            elif field == "roi_goal":
                lines.append(f"  if (deepExternalActionMap[{task_id}] === undefined) {{")
                lines.append(f"    results.push({{action:'{action_type}', task_id:{task_id}, endpoint:'update_uni_promotion_roi', field:'roi_goal', new_value:{new_value}, ok:false, error:'missing_deep_external_action'}});")
                lines.append("  } else {")
                lines.append(f"    var r{i} = postJson('/ad/api/pmc/v1/uni-promotion/ad/update_uni_promotion_roi', {{UpdateRoi2Infos:[{{ID:{task_id}, Value:{new_value}, DeepExternalAction:deepExternalActionMap[{task_id}]}}]}});")
                lines.append(f"    results.push({{action:'{action_type}', task_id:{task_id}, endpoint:'update_uni_promotion_roi', field:'roi_goal', new_value:{new_value}, ok:!!(r{i}.body && r{i}.body.status_code===0), status_code:r{i}.body && r{i}.body.status_code, message:(r{i}.body && r{i}.body.message) || ''}});")
                lines.append("  }")
    lines.append("  return JSON.stringify({ok:true, account:AAVID, primary_ad_id:PRIMARY_AD_ID, results:results});")
    lines.append("})()")
    return "\n".join(lines)


def execute_actions(actions, js_func, account):
    """Execute write operations through an account-verified browser evaluator."""
    if not actions:
        return {"ok": True, "results": [], "note": "no actions to execute"}
    code = build_exec_js(actions, account)
    try:
        raw = js_func(code)
        return _json.loads(raw)
    except NameError:
        return {"ok": False, "error": "js() not available (static check mode)", "note": "execution skipped"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
