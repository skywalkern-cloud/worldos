# CHANGELOG — WorldOS 规则/口径变更记录

> 只记「会改变结论」的变更（权重、阈值、打分口径、指标归属）。
> 每条必须能回答：谁改的 / 何时 / 依据什么证据 / 怎么回滚。

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
