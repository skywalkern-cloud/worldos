# CHANGELOG — WorldOS 规则/口径变更记录

> 只记「会改变结论」的变更（权重、阈值、打分口径、指标归属）。
> 每条必须能回答：谁改的 / 何时 / 依据什么证据 / 怎么回滚。

## 2026-11-28 · A2：usdcnh 打分重标（固定水位 → 相对 120 日均值 5 档）

- **谁**：龙五（PM）派单 A2，扣钉实现
- **何时**：2026-11-28（同日晚于 P1-8DIM 批次 A）
- **为何**：旧 `breakpoint_steps=(7.05,7.20,7.35)` 是 7.2 时代水位，现价 6.6551 恒 `<7.05`
  → 永久 `+0.5`，等于给 fxExternal 灌了一个多头常数（与 11-27 认定要修的「越阈值后永久 +1」同病）。
- **变更**：
  - 数据源：`akshare.forex_spot_em` 离岸现货（无日期）→ `akshare.forex_hist_em('USDCNH')` **日线**（带交易日，4232 行）。
    回填最近 **250 个交易日**到 `data/history/series/usdcnh.json`（2025-12-15 → 2026-11-27）。
  - 打分：`scoring_method='ratio_ma_steps'`；`ratio = USDCNH / MA120`（120 个交易日收盘均值，含当日），
    五档阶跃：`≤0.985 +1.0 / ≤0.995 +0.5 / ≤1.005 0 / ≤1.015 −0.5 / >1.015 −1.0`。
  - 方向：**人民币越弱（ratio 越高）= 越差**（写进注释与 caliberNote）。
  - 历史不足 120 点 → `score=null`（不硬填/不插值），维度按 3/4 有效照常出分。
  - `caliberNote` 显式展示「当前值 vs 120 日均值 ±x.x%（ratio→档位）」。
- **当日影响（11-28 同数据）**：usdcnh +0.5 → +0.5（ratio 0.9898 恰落同一档）；
  fxExternal +0.026 → +0.026；IAS −0.57/−0.102/持有 → **不变**。
  **数值零位移不等于规则没变**：一档位移（+0.5→0）就会把 IAS 从持有翻到减仓（见 REPORT §6.5 探针表）。
- **回算**：19 日重跑，usdcnh 按 `date < 快照日` as-of 注入，无未来函数（脚本+测试双断言）；
  翻转 6 天 → 3 天（11-24/26/28 因 usdcnh 真实 +0.5 回到持有）。
- **证据**：`docs/P1-8DIM-REPORT.md` §6；`scripts/test_schema_fields.py` S10-04b/c、S11-01~06、S12-01~03。
- **回滚**：恢复 `usdcnh.scoring_method='breakpoint_steps'` 与旧水位、`get_usdcnh` 旧源；
  `series/usdcnh.json` 可保留（不影响旧打分）。无 schema 破坏。

## 2026-11-28 · P1-8DIM：综合评分 6 维 → 8 维（IAS_SCALE 4.6 → 5.6）+ 阈值改 normalized 量纲

- **谁**：龙五（PM）派单 `docs/P1-8DIM-WORKORDER.md`，扣钉实现（批次 A：骨架搬家）
- **何时**：2026-11-28
- **变更（一句话）**：`DIMENSIONS` 由 6 维拆为 8 维（新增 fxExternal，sentiment 拆为 sentimentA + riskAppetite），
  权重和 4.6 → 5.6；`IAS_THRESHOLDS` 由 score 量纲（2.5/1.0/−0.5/−1.5）改为 **normalized 量纲**
  （0.543/0.217/−0.109/−0.326），比较一律用 `ias.normalized`。
- **结构**：economic 1.0 / inflation 1.0 / liquidity 0.8（只剩 LPR·DR007·M2）/ fxExternal 0.7（新增）/
  sentimentA 0.9 / riskAppetite 0.4 / resource 0.5 / techGreen 0.3，合计 **5.6**（= `IAS_SCALE` 派生值，无硬编码）。
- **指标搬家**：`dollarIndex/creditSpread/usBond10Y` → fxExternal；`usBond2Y/5Y` → riskAppetite **只展示**；
  `lmeIndex` → resource **只展示**（与沪铜共线）；`carbonPrice` → techGreen（**改为计分**）；
  `aiGrowth/robotInstall` 维持 reference_only 但**移出计分分母**（techGreen shrink 0.5 → 1.0）。
- **新增指标**：`usdcnh`（USDCNH）——**统计口径已于同日 A2 重标，见上方 A2 条目**（旧固定水位 7.05/7.20/7.35 已废弃）。
  旧描述存档：离岸优先 akshare 东财现货，回退 exchangerate-api 在岸中间价；四段阶跃 `<7.05→+0.5 / 7.05~7.20→0 / 7.20~7.35→−0.5 / ≥7.35→−1.0`。
- **修复的 bug**：① 旧代码内部拿 `score`（量纲 4.6）比 −0.5 却对外发 `normalized`，真实分界漂到 −0.109；
  ② `_ias_signal_desc`/`_strategy_advice` 里同一类 score 量纲阈值比较（改为只读后端 `ias.signal`）。
- **当日影响（11-28，同数据）**：old −0.43/−0.093636/持有 → new **−0.57/−0.102/持有**（含 usdcnh 实时 6.6551）；
  `rules_hash` 269592dd0bb6 → **ae148d2b8a6d**。
- **证据**：`scripts/replay_8dim_30d.py` 逐日回算 → `data/history/recompute-8dim-2026-11-28.json`；
  19 个历史快照中 6 天档位翻转，全部归因「结构/权重」或「缺失剔除」，**归因「阈值量纲」= 0 天**。
- **回滚**：`git revert` 本笔代码 commit（数据/回算产物是另一笔，需一并 revert）；
  无数据迁移、无 schema 破坏（旧快照仍可读，`ias.score` 语义保留为 normalized×IAS_SCALE）。

## 2026-11-28 · ashareTurnover 改「相对量分段」打分（不再用分位）

- **谁**：龙六裁定，PM 龙五转达，扣钉实现
- **变更**：`ashareTurnover` 的 `scoring_method` 由 `pct_rank` 改为 `ratio_band`，`polarity=growth_proxy`；
  构造改为 `r = 今日成交额 / mean(前 120 个交易日)`（不含今日），分段线性：
  r≤0.60→−1 | 0.60~1.00→−1→+0.6 | 1.00~1.60→+0.6→+0.8 | r>1.60→+0.8−2.0×(r−1.60)，地板 0（过热只钝化，不转负）。
- **为何**：成交额的「好」不是单调的 —— 地量冰点和天量过热都不好，分位表达不了这个形状。
- **验收锚点（V1b-16）**：今日 `r_value=0.9085`（锚 0.908±0.01）、`score=+0.234`（锚 +0.232±0.005），
  `ma120_base=22012.21` 已入产物可复算；14 点测试向量逐点通过（`S9-07`）。
- **⚠️ 窗口即规则**：同一套断点，MA60 给 **+0.658** / MA120 给 **+0.234** / MA250 给 **+0.047**
  （三个数已用 400 日回填序列本地复算，与龙六给值逐位一致：base 17017.78 / 22012.21 / 23207.35）。
  换窗口等于换规则，断点必须重标，不允许"随手换个均值"。
- **其余 3 项不变**：marginBalance(delta5) / southboundNet(sum5) / hstechMomentum 仍 `risk_appetite` + 分位。
- **回滚**：把 `ashareTurnover.scoring_method` 改回 `pct_rank`、`transform='raw'`、`polarity='risk_appetite'`。

## 2026-11-28 · sentiment 维度撤回 market_mismatch 折半（有效权重 0.4 → 0.8）

- **谁**：扣钉（执行 V1b-1），PM 龙五拍板，龙六复核
- **何时**：2026-11-28
- **变更**：`indicator_meta.DIMENSIONS[sentiment]` 的 `market_mismatch` 0.5 → 1.0，
  `mismatch_reason` 置 `null`；有效权重 0.4 → 0.8（恢复设计权重），`IAS_SCALE` 不变（4.6）。
- **依据**：`indicator_meta.py` 原注释写明的前置条件「P1 补齐 A 股情绪代理后方可移除本标记恢复满额」已满足：
  4 项 A股/港股情绪代理已转正并出分（2026-11-27 快照，均 `window=60/120`、`saturated=false`）：
  | 指标 | score | history_days | 方法 | 关键量 |
  |---|---|---|---|---|
  | ashareTurnover | +0.234 | 127 | ratio_band | r=0.9085 / MA120=22012.21 |
  | marginBalance | −0.760 | 62 | pct_rank | pct20=0.200 / pct60=0.067 |
  | southboundNet | −0.780 | 63 | pct_rank | pct20=0.100 / pct60=0.117 |
  | hstechMomentum | +0.100 | 67 | pct_rank | pct20=0.400 / pct60=0.650 |
  满足「≥3 项新指标 score != null」的前置门槛（实际 4 项全部出分）。
- **影响**：sentiment 维度分不受 mismatch 影响（mismatch 只乘在权重上，不参与维度分计算）；
  IAS 中 sentiment 的权重贡献翻倍 → 30 交易日回算：sentiment 分档翻转 0 次差异，
  IAS 分档翻转 0 → 3 次，同一天跨臂分档不同 11/30 天
  （详见 `scripts/replay_sentiment_30d.py`，**含边界声明：其余五维冻结为当日值，差异不具代表性**）。
- **回滚**：把 `market_mismatch` 改回 0.5、`mismatch_reason` 恢复文案即可，无数据迁移。
