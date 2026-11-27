# CHANGELOG — WorldOS 规则/口径变更记录

> 只记「会改变结论」的变更（权重、阈值、打分口径、指标归属）。
> 每条必须能回答：谁改的 / 何时 / 依据什么证据 / 怎么回滚。

## 2026-11-28 · sentiment 维度撤回 market_mismatch 折半（有效权重 0.4 → 0.8）

- **谁**：扣钉（执行 V1b-1），PM 龙五拍板，龙六复核
- **何时**：2026-11-28
- **变更**：`indicator_meta.DIMENSIONS[sentiment]` 的 `market_mismatch` 0.5 → 1.0，
  `mismatch_reason` 置 `null`；有效权重 0.4 → 0.8（恢复设计权重），`IAS_SCALE` 不变（4.6）。
- **依据**：`indicator_meta.py` 原注释写明的前置条件「P1 补齐 A 股情绪代理后方可移除本标记恢复满额」已满足：
  4 项 A股/港股情绪代理已转正并出分（2026-11-27 快照，均 `window=60`、`saturated=false`）：
  | 指标 | score | history_days | pct_20 | pct_60 |
  |---|---|---|---|---|
  | ashareTurnover | +0.720 | 67 | 0.900 | 0.833 |
  | marginBalance | −0.760 | 62 | 0.200 | 0.067 |
  | southboundNet | −0.780 | 63 | 0.100 | 0.117 |
  | hstechMomentum | +0.100 | 67 | 0.400 | 0.650 |
  满足「≥3 项新指标 score != null」的前置门槛（实际 4 项全部出分）。
- **影响**：sentiment 维度分不变（mismatch 只乘在权重上，不参与维度分计算）；
  IAS 中 sentiment 的权重贡献翻倍 → 30 交易日回算里 IAS 分档翻转 0 → 5 次，
  同一天跨臂分档不同 10/30 天（详见 `scripts/replay_sentiment_30d.py` 输出，含边界声明）。
- **回滚**：把 `market_mismatch` 改回 0.5、`mismatch_reason` 恢复文案即可，无数据迁移。
