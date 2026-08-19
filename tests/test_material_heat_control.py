import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from material_heat_execution import build_exec_js
from material_heat_storage import build_brief
from material_heat_strategy import build_strategy, config_for_target_roi


def task(task_id, *, bid=None, roi_goal=None, cost=700, pay_roi=3.2, budget=1000):
    return {
        "task_id": task_id,
        "task_name": task_id,
        "control_status": "调控中",
        "budget_yuan": budget,
        "bid_yuan": bid,
        "roi_goal": roi_goal,
        "metrics": {
            "cost_yuan": cost,
            "pay_roi": pay_roi,
            "pay_order_count": 1,
        },
        "operations": {"can_edit": True, "can_pause": True},
    }


class PayloadTests(unittest.TestCase):
    def test_generated_write_payload_uses_dedicated_lightweight_endpoints(self):
        account = SimpleNamespace(
            aavid="1782170738715850",
            primary_ad_id="1869596838427768",
            assist_task_scene=2,
            gfversion="1.0.0.9781",
        )
        generated = build_exec_js(
            [
                {"task_id": "budget-task", "action": "increase_budget", "new_budget_yuan": 1500},
                {"task_id": "bid-task", "action": "raise_price", "preferred_change": {"field": "bid_yuan", "new": 51}},
                {"task_id": "roi-task", "action": "pressure_price", "preferred_change": {"field": "roi_goal", "new": 3.25}},
            ],
            account,
        )
        harness = f"""
const requests = [];
global.document = {{body: {{innerText: '计划ID：1869596838427768'}}}};
global.XMLHttpRequest = class {{
  open(method, url) {{ this.url = url; }}
  setRequestHeader() {{}}
  send(rawBody) {{
    const body = JSON.parse(rawBody);
    requests.push({{url: this.url, body}});
    this.status = 200;
    if (this.url.includes('list-required')) {{
      this.responseText = JSON.stringify({{status_code:0, data:{{adInfos:[
        {{id:'budget-task', deepExternalAction:576}},
        {{id:'bid-task', deepExternalAction:576}},
        {{id:'roi-task', deepExternalAction:576}}
      ]}}}});
    }} else {{ this.responseText = JSON.stringify({{status_code:0, message:'success'}}); }}
  }}
}};
const execution = JSON.parse(eval({json.dumps(generated)}));
console.log(JSON.stringify({{execution, requests}}));
"""
        completed = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
        observed = json.loads(completed.stdout)
        writes = {request["url"].split("?")[0]: request["body"] for request in observed["requests"] if "list-required" not in request["url"]}

        self.assertEqual(writes["/ad/api/pmc/v1/batch_update_budget"], {
            "ForceAsync": False,
            "AdsData": [{"AdId": "budget-task", "AdBudget": 150000000}],
        })
        self.assertEqual(writes["/ad/api/promotion/v1/batch_update_bid"], {
            "updateBidInfos": [{"id": "bid-task", "value": 5100000}],
        })
        self.assertEqual(writes["/ad/api/pmc/v1/uni-promotion/ad/update_uni_promotion_roi"], {
            "UpdateRoi2Infos": [{"ID": "roi-task", "Value": 3.25, "DeepExternalAction": 576}],
        })
        self.assertNotIn("update-uni-prom-assist-task", "\n".join(writes))


class BriefTests(unittest.TestCase):
    def test_brief_includes_account_identity_and_every_plan(self):
        first, second = task("first", cost=1), task("second", cost=999)
        first.update({"delivery_status": "投放中", "smart_bid_type": 0, "smart_bid_name": "出价", "created_at": "2026-07-30 06:00:00"})
        second.update({"delivery_status": "已暂停", "smart_bid_type": 7, "smart_bid_name": "净成交ROI", "created_at": "2026-07-30 05:00:00"})
        data = {
            "schema": "qianchuan.material_heat.realtime.v1",
            "read_at": "2026-07-30 06:30:00",
            "account": {"aavid": "account-a"},
            "primary_ad": {"ad_id": "primary-a", "assist_task_scene": 2},
            "account_context": {"alias": "account-alias"},
            "tasks": [first, second],
            "strategy": {"actions": [], "execution": {"ok": True}},
        }
        brief = build_brief(data, Path("strategy.json"), Path("snapshot.json"))
        self.assertEqual(brief["account"]["aavid"], "account-a")
        self.assertEqual(brief["primary_ad"]["ad_id"], "primary-a")
        self.assertEqual(brief["account_context"]["alias"], "account-alias")
        self.assertEqual([plan["task_id"] for plan in brief["plans"]], ["first", "second"])
        self.assertNotIn("top_tasks_by_cost", brief)


class PacingDirectionTests(unittest.TestCase):
    def strategy(self, current_task, previous_task=None):
        current = {"read_at": "2026-06-30 10:15:00", "tasks": [current_task]}
        previous = {
            "read_at": "2026-06-30 10:00:00",
            "tasks": [previous_task or current_task],
        }
        return build_strategy(current, previous)

    def preferred_change(self, current_task, previous_task=None):
        actions = self.strategy(current_task, previous_task)["actions"]
        self.assertEqual(len(actions), 1)
        return actions[0]["preferred_change"]

    def test_fast_spend_lowers_bid(self):
        change = self.preferred_change(task("bid-fast", bid=50))
        self.assertEqual((change["field"], change["new"]), ("bid_yuan", 49.0))

    def test_fast_spend_raises_roi_goal(self):
        change = self.preferred_change(task("roi-fast", roi_goal=3.2))
        self.assertEqual((change["field"], change["new"]), ("roi_goal", 3.25))

    def test_stuck_spend_raises_bid(self):
        current = task("bid-stuck", bid=50, cost=300, pay_roi=3.6)
        previous = task("bid-stuck", bid=50, cost=300, pay_roi=3.6)
        change = self.preferred_change(current, previous)
        self.assertEqual((change["field"], change["new"]), ("bid_yuan", 51.0))

    def test_stuck_spend_lowers_roi_goal(self):
        current = task("roi-stuck", roi_goal=3.4, cost=300, pay_roi=3.6)
        previous = task("roi-stuck", roi_goal=3.4, cost=300, pay_roi=3.6)
        change = self.preferred_change(current, previous)
        self.assertEqual((change["field"], change["new"]), ("roi_goal", 3.35))


class TargetRoiConfigTests(unittest.TestCase):
    def test_target_roi_3_0_shifts_related_thresholds(self):
        config = config_for_target_roi(3.0)
        self.assertEqual(config["target_roi"], 3.0)
        self.assertEqual(config["pause_roi_below"], 2.7)
        self.assertEqual(config["pressure_roi_min"], 2.7)
        self.assertEqual(config["scale_budget_roi_above"], 3.0)
        self.assertEqual(config["raise_roi_above"], 3.2)
        self.assertEqual(config["target_roi"] - config["reopen_roi_near_delta"], 2.9)

    def test_target_roi_3_0_changes_actions(self):
        config = config_for_target_roi(3.0)
        current = {"read_at": "2026-06-30 10:15:00", "tasks": [task("pause", bid=50, pay_roi=2.8)]}
        strategy = build_strategy(current, None, config)
        self.assertNotIn("pause", [a["action"] for a in strategy["actions"]])
        self.assertEqual(strategy["actions"][0]["action"], "pressure_price")

        current["tasks"] = [task("pause", bid=50, pay_roi=2.6)]
        strategy = build_strategy(current, None, config)
        self.assertEqual(strategy["actions"][0]["action"], "pause")

        paused = task("reopen", bid=50, pay_roi=2.95)
        paused["control_status"] = "已暂停"
        paused["operations"] = {"can_start": True}
        strategy = build_strategy({"read_at": "2026-06-30 10:15:00", "tasks": [paused]}, None, config)
        self.assertEqual(strategy["actions"][0]["action"], "reopen")

if __name__ == "__main__":
    unittest.main()
