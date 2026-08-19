# API 接口清单

所有请求均在千川后台页面上下文中执行（`withCredentials`），URL 带 `?aavid=<账户ID>&gfversion=<动态解析>`。

## 读取（只读）

| 接口 | 用途 |
|---|---|
| `POST /ad/api/pmc/v1/uni-promotion/ad/list-required` | 全量追投任务列表：task_id、预算、出价、ROI目标、投放状态、operations 可操作性、deepExternalAction 映射 |
| `POST /ad/api/pmc/v1/uni-promotion/ad/list-summary` | 账户/计划组汇总：总消耗、总ROI、任务数 |
| `POST /ad/api/data/v1/common/statQuery?reqFrom=compareTrend` | 时段趋势数据 |
| `POST /ad/api/pmc/v1/uni-promotion/material/list-required?reqFrom=uni-prom-creative-tab-list` | 素材维度列表 |

## 写操作

| 接口 | 动作 | 参数 |
|---|---|---|
| `POST /ad/api/pmc/v1/batch_update_operation` | reopen / pause | `{optType: 1或2, objects: [{objectID, type:1}]}` |
| `POST /ad/api/pmc/v1/batch_update_budget` | 改预算 | `{ForceAsync:false, AdsData:[{AdId, AdBudget(微元)}]}` |
| `POST /ad/api/promotion/v1/batch_update_bid` | 改出价 | `{updateBidInfos:[{id, value(微元)}]}` |
| `POST /ad/api/pmc/v1/uni-promotion/ad/update_uni_promotion_roi` | 改 ROI 目标 | `{UpdateRoi2Infos:[{ID, Value, DeepExternalAction}]}`（需先 list-required 拿 deepExternalAction） |

## 通用约定

- 金额单位：**微元**（元 × 100000）
- 批量上限：每批 10 个任务
- 所有写操作前必须通过账户上下文校验（见 docs/STRATEGY.md）
