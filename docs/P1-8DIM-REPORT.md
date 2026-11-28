# P1-8DIM 交付报告（批次 A：骨架搬家）

- 执行：扣钉
- 日期：2026-11-28
- 工单：`docs/P1-8DIM-WORKORDER.md`（唯一真源，与代码冲突以工单为准）
- 状态：**代码完成 + 全绿验证，未 push、未部署、未改 cron、未重抓线上数据**
- 回算产物：`data/history/recompute-8dim-2026-11-28.json`
- **A2 追加（2026-11-28）**：usdcnh 已由「固定水位四段阶跃」重标为「相对 120 日均值」5 档；
  §1.2 / §4 中 usdcnh 的**旧描述已被 §6 取代**（旧水位 7.05/7.20/7.35 在 6.65 报价下恒为 +0.5，属永久偏置）。

---

## 1. 做了什么（按工单 §1 逐项核对）

| § | 要求 | 状态 | 落点 |
|---|---|---|---|
|1.1| 8 维骨架、权重和 5.6 | ✅ | `indicator_meta.DIMENSIONS`（8 条，`IAS_SCALE` 由 `sum(weight)` 派生 = 5.6，无硬编码）|
|1.1| liquidity 只剩 LPR/DR007/M2，更名「流动性（国内）」 | ✅ | id 保留 `liquidity`（历史序列不裂），name/成员已改 |
|1.1| 新增 fxExternal（usdcnh / dollarIndex / creditSpread / usBond10Y） | ✅ | id `fxExternal`，权重 0.7，required=2 |
|1.1| sentiment 拆为 sentimentA(0.9) + riskAppetite(0.4) | ✅ | 旧 id `sentiment` 已消失，**无兼容别名** |
|1.1| resource 去共线：lmeIndex 只展示 | ✅ | `lmeIndex.reference_only=True`，移入 `reference_indicators` |
|1.1| techGreen：carbonPrice 改计分、aiGrowth/robotInstall 只展示 | ✅ | 三项计分 + 两项 `reference_indicators`（**shrink 0.5 → 1.0**）|
|1.1| 权重总量 | ✅ | 1.0+1.0+0.8+0.7+0.9+0.4+0.5+0.3 = **5.6** |
|1.2| usdcnh 取数（离岸优先 / 在岸回退 / 取不到 None） | ✅ | `get_usdcnh()`：akshare `forex_spot_em` USDCNH → exchangerate-api CNY → `None`；**每步 log 源**，回退时 `source_degraded` + `caliberNoteSuffix`（页面可见「在岸参考价」）|
|1.2| 四段阶跃 −1.0/−0.5/0/+0.5 | ✅ | `scoring.score_breakpoint_steps`（数据驱动，配置在 `indicator_meta.BREAKPOINT_STEPS_CONFIG`），非硬编码分支 |
|1.2| 回退时数据点标记 | ✅ | `source_degraded[]` 进 `validity_report`，`indicators.usdcnh.actualSource` |
|2| 阈值改 normalized（0.543/0.217/−0.109/−0.326），比较一律 `ias.normalized` | ✅ | `IAS_THRESHOLDS` + `IAS_THRESHOLD_SPACE='normalized'`；`calc_ias` 只比 normalized；产物新增 `meta.ias.threshold_space` |
|2| 不许硬编码 IAS_SCALE | ✅ | `IAS_SCALE = round(sum(d['weight'] ...), 2)`；`grep 4\.6` 仅剩注释/测试旧口径对照 |
|3.1| App.tsx：8 维、DIMENSION_INDICATORS 含 usdcnh | ✅ | 顺序 economic→techGreen；旧数据回退表同步 |
|3.2| score-keywords 新增 3 张表、删 `sentiment` | ✅ | `fxExternal` / `sentimentA` / `riskAppetite`；`getKeyword('sentiment')` 只回中性占位 |
|3.3| commentary_generator 新增/改写模板 | ✅ | 新增 `_dim_commentary_sentimentA/fxExternal/riskAppetite`，liquidity 只讲国内，resource 去掉碳、LME 标「参考（不计分）」，techGreen 加碳价 |
|3.4| 生成后 JSON 校验 | ✅ | `write_json_strict` + `test_no_nan_json` 全过 |
|3.5| 旧 sentiment 引用清理 | ✅ | `Dashboard.tsx` / `marketData.ts` 显式 `@deprecated 未挂载`（v6 旧模型，App 不 import）|
|4| 阈值 3 位小数、half-up | ✅ | 0.543 / 0.217 / −0.109 / −0.326 |
|4| 断言：旧阈值→新阈值信号语义不变 | ✅ | `S10-03`：normalized 从 −1.000 到 +1.000 步长 0.001 全扫，仅边界舍入窗（≤0.0012）内不一致 |
|5| 30 交易日回算 | ⚠️ **只有 19 个快照** | 见 §4 不确定项 1；19 天全算，产出对照表 + 翻转清单 |
|6.5| 五条断言写进测试 | ✅ | `test_schema_fields.py:test_s10_8dim`（`S10-01`~`S10-05`）|
|7| 禁止 push / 部署 / 改 cron / 改线上数据 | ✅ | 仅本地两笔 commit |

### 额外修掉的同类 bug（工单 §4 的「口径」要求，非顺手改分）

- `commentary_generator._ias_signal_desc(score)`、`_strategy_advice(score, …)` 里也拿 **score** 比 2.5/1.0/−0.5/−1.5。
  改为**只读后端 `ias.signal`**（单一真源），彻底删掉第二张阈值表。
- `IAS_SCALE` 变更后 `max_possible` 会自动跟着变（原本就派生），但前端兜底常量 4.6 已改 5.6。

---

## 2. 验证证据（原始输出）

### 2.1 元数据自检

```
$ python3 scripts/indicator_meta.py
✅ 元数据校验通过：36 个指标 / 8 个维度

维度权重（设计 → 有效）:
  经济增长     1.00 → 1.00  (6/6)  满额
  通胀与政策    1.00 → 1.00  (5/5)  满额
  流动性（国内）  0.80 → 0.80  (3/3)  满额
  汇率与外部    0.70 → 0.70  (4/4)  满额
  A股/港股情绪  0.90 → 0.90  (4/4)  满额
  全球风险偏好   0.40 → 0.40  (2/2)  满额
  资源与供应链   0.50 → 0.50  (3/3)  满额
  科技与绿色    0.30 → 0.30  (3/3)  满额
  合计     5.60 → 5.60
```

### 2.2 schema 回归（145 项）

```
$ python3 scripts/test_schema_fields.py
...
✅ S9-07[vector]
✅ S0[readonly]

145 passed / 0 warn / 0 failed / 145 total
```

其中新增/改动的关键项：

```
✅ S4-10[live]        IAS_THRESHOLDS == (0.543/0.217/-0.109/-0.326)
✅ S4-10b[live]       threshold_space == 'normalized'（代码+产物一致）
✅ S4-12[live]        信号档 ≡ normalized 阈值推导
✅ S4-U2              四档边界（normalized ±0.02）逐档命中
✅ S10-01[live]       sum(weight) == IAS_SCALE == 产物 ias_scale == 5.6
✅ S10-02[live]       参考项不进分母：w_eff = w × active/design_count，且两表无交集
✅ S10-03[live]       新旧阈值同输入同档（仅舍入窗内差异）
✅ S10-04[live]       usdcnh 6.6551 → score +0.5（可由四段阶跃复算）
✅ S10-05[live]       fxExternal valid=4 ≥ 2，出分
```

### 2.3 NaN/Inf 回归

```
$ python3 scripts/test_no_nan_json.py
✅ fetch_worldos_data: _sanitize + write_json_strict 通过
✅ generate_commentary_llm: _sanitize + write_json_strict 通过
✅ commentary_generator: _sanitize + write_json_strict 通过

全部通过：3 个模块均不会产出非法 JSON
```

### 2.4 caliber-edge（前端边界夹具）

```
$ node --test tests/caliber-edge.test.mjs
# tests 1
# pass 1
# fail 0
```
（内部 285 条子断言；改动处：IAS oracle 改 normalized、realtime 名额 3→4（+usdcnh）、
techGreen scoring 2→3、参考项超期不描灰、`getKeyword('sentiment')` → 中性占位）

### 2.5 构建

```
$ npm run build
✓ 19 modules transformed.
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-CCp4s8fw.css   42.42 kB │ gzip:  7.29 kB
dist/assets/index-CdHL19Wv.js   230.13 kB │ gzip: 72.02 kB
✓ built in 75ms
```

### 2.6 同日新旧逐维度对照（2026-11-28，同一份原始指标）

旧侧 = 冻结 6 维（`LEGACY_6DIM`，rules_hash `269592dd0bb6`）在当日原始值上复算；
新侧 = 新 8 维代码 + 当日实时 usdcnh（6.6551）。

| 旧维度 | 旧 w_eff | 旧 score | → | 新维度 | 新 w_eff | 新 score | 成员变化 |
|---|---|---|---|---|---|---|---|
| economic | 1.0 | −0.250 | → | economic | 1.0 | −0.250 | 不变 |
| inflation | 1.0 | +0.113 | → | inflation | 1.0 | +0.113 | 不变 |
| liquidity | 0.8 | −0.061 | → | liquidity | 0.8 | **+0.011** | 8 项 → 3 项（只剩国内）|
| — | — | — | → | **fxExternal** | 0.7 | **+0.026** | 新维（含 usdcnh +0.5）|
| sentiment | 0.8 | −0.369 | → | sentimentA | 0.9 | **−0.302** | 4 个 A 股/港股代理独立|
| ↑ | ↑ | ↑ | → | riskAppetite | 0.4 | **−0.505** | VIX+F&G（2Y/5Y 只展示）|
| resource | 0.6 | −0.017 | → | resource | 0.5 | **−0.333** | 去碳价、去 LME（都移走）|
| techGreen | **0.2** | +0.396 | → | techGreen | **0.3** | **+0.597** | 加碳价 +1.0；参考项移出分母 |
| **IAS** | Σeff 4.4 | **−0.43** | → | **IAS** | Σeff **5.6** | **−0.57** | |
| normalized | | −0.093636 | → | | | **−0.102** | |
| signal | | 持有 | → | | | **持有** | |
| rules_hash | | 269592dd0bb6 | → | | | **ae148d2b8a6d** | |

> 净效应：`normalized` −0.0936 → −0.1020，仍在 `−0.109` 之上 → **信号档位不变（持有）**。
> 但**余量只有 0.007**：11-28 当天如果 usdcnh 缺失，`normalized = −0.1218` → 直接落到「减仓」。
> 这是结构变化的真实后果，不是 bug，但请 PM 在发版前知情（见 §4 不确定项 2）。

### 2.7 30 交易日回算（实际 19 个快照）

```
$ python3 scripts/replay_8dim_30d.py
日期          旧score   旧norm     旧信号       新score   新norm     新信号       翻转
2026-11-09  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-10  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-11  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-12  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-13  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-14  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-16  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-17  -0.32    -0.0685   数据不足      -0.38    -0.0685   数据不足
2026-11-18  -0.44    -0.096    持有        -0.61    -0.108485 数据不足      ★
2026-11-19  -0.34    -0.073833 持有        -0.78    -0.138568 减仓（部分维度缺失·参考）★
2026-11-20  -0.3     -0.064889 持有        -0.85    -0.152432 减仓（部分维度缺失·参考）★
2026-11-21  -0.14    -0.029444 持有        -0.52    -0.092936 持有
2026-11-22  -0.13    -0.029222 持有        -0.52    -0.09234  持有
2026-11-23  -0.13    -0.028056 持有        -0.47    -0.083489 持有
2026-11-24  -0.21    -0.046222 持有        -0.62    -0.109979 减仓        ★
2026-11-25  -0.19    -0.040333 持有        -0.57    -0.102596 持有
2026-11-26  -0.2     -0.043111 持有        -0.62    -0.110511 减仓        ★
2026-11-27  -0.14    -0.030444 持有        -0.6     -0.107106 持有
2026-11-28  -0.43    -0.093636 持有        -0.68    -0.12175  减仓        ★

共 19 个快照，信号档位翻转 6 天
  ★ 2026-11-18: 持有 → 数据不足（缺失剔除（覆盖率跌破 0.6）；归一 -0.096 → -0.108485；覆盖 0.773 → 0.589）
  ★ 2026-11-19: 持有 → 减仓（部分维度缺失·参考）（结构/权重；归一 -0.073833 → -0.138568；覆盖 0.818 → 0.786）
  ★ 2026-11-20: 持有 → 减仓（部分维度缺失·参考）（结构/权重；归一 -0.064889 → -0.152432；覆盖 0.818 → 0.786）
  ★ 2026-11-24: 持有 → 减仓（结构/权重；归一 -0.046222 → -0.109979；覆盖 0.818 → 0.839）
  ★ 2026-11-26: 持有 → 减仓（结构/权重；归一 -0.043111 → -0.110511；覆盖 0.818 → 0.839）
  ★ 2026-11-28: 持有 → 减仓（结构/权重；归一 -0.093636 → -0.12175；覆盖 1.0 → 1.0）

rules_hash old=['269592dd0bb6', '88cb8f040f89', 'a306915b6fa9'] → new=ae148d2b8a6d
```

**归因分解（关键结论）**

| 翻转原因 | 天数 | 说明 |
|---|---|---|
| **阈值量纲（4.6→5.6 + normalized 阈值）** | **0 天** | 逐日 `threshold_only_signal` 与旧信号完全一致 → 阈值换算本身零影响 |
| 结构/权重（维度拆分、成员搬家） | 5 天 | 11-19/20/24/26/28 |
| 缺失剔除（历史日缺 A 股代理 → 4 维置灰、覆盖率跌破 0.6） | 1 天 | 11-18 |

> 11-18 的翻转是**历史数据缺口**造成：该日 `ashareTurnover/marginBalance/southboundNet/hstechMomentum`
> 尚不存在（11-27 才接入），新结构下 sentimentA(0.9)+riskAppetite(0.4)+techGreen(0.3)+fxExternal(0.7)
> 同时置灰，覆盖率 0.589 < 0.6 → 「数据不足」。**向前看不会复现**（数据齐备），
> 但说明新结构对「某类指标整批缺失」更敏感（见 §4 不确定项 3）。

> 11-28 在回算里是「减仓」、在重建的 live 文件里是「持有」——差别**只在 usdcnh**：
> 回算用当日快照（无 usdcnh，3/4 有效），live 文件含实时 usdcnh 6.6551（+0.5）。
> 两个数字都对，口径必须说清。

---

## 3. 数据产物说明

| 文件 | 性质 | 是否覆盖历史 |
|---|---|---|
| `data/history/recompute-8dim-2026-11-28.json` | 回算产物（19 天逐日 old/new + 归因 + 翻转清单）| 否，新增文件 |
| `public/data/market-data.json` | **本地构建输入**重建：除 usdcnh 为重建时实时取数外，其余全部取自 `2026-11-28` 16:02 快照（不重抓、不造数）| 否，`data/history/2026-11-28.json` 原样保留 |
| `dist/data/market-data.json` | 上述文件的构建副本（`npm run build` 产物）| — |
| `tests/fixtures/market-data-edge-cases.json` | 边界夹具按 8 维重新生成（覆盖 expired/reference_only/no_score/置灰/覆盖率中间档）| — |

> ⚠️ `data/history/*` 被 `.gitignore` 挡掉（只放行 `series/`），回算产物是 `git add -f` 强制入库的。
> 若 PM 认为不该入库，可从数据 commit 里剔除（文件仍在本地）。
>
> A2 后 `public/data/market-data.json` 的 usdcnh 不再实时取数：改取 `data/history/series/usdcnh.json`
> 中 `date < 2026-11-28` 的最近收盘（2026-11-27 = 6.6551），并挂 249 条历史供 MA120 复算。

---

## 4. 我不确定的 3 件事（工单要求必列）

1. **「30 交易日」实际只有 19 个快照**：`data/history/` 里 11-09 → 11-28 共 19 个日快照（缺 11-15，
   且更早的快照没有保留）。逐日回算需要「当日原始指标值」，而只有 4 个指标（ashareTurnover /
   marginBalance / southboundNet / hstechMomentum）有 400 日 series，其余 31 个指标没有历史序列。
   → 我按 19 天做完，没有用 series 反推或插值凑 30 天（那等于造数）。**要不要补 30 天，需要另一个单
   （backfill 全指标历史）**。

2. **11-28 的 normalized 恰好压在 持有/减仓 边界上**：含 usdcnh 时 −0.1020（→ 持有，余量 0.007）；
   不含 usdcnh 时 −0.1218（→ 减仓）。也就是说，发版后「usdcnh 当天取没取到」这一件事就能翻转 IAS 档位。
   我**没有**为此调整阈值或权重（那是改规则，不是搬家）。是否接受这个敏感度、或要求 usdcnh
   必须成功才出 IAS，请 PM 拍。

3. **工单 §4「信号档位必须与旧代码一致」与 §5「normalized 会凭空跳变」互相冲突**：
   §4 的字面要求（把 11-28 数据喂新代码 → 信号与旧一致）只有在**结构不变**时才可能成立；
   本批改了维度结构，normalized 必然移动。我按「阈值语义不变」实现（新阈值对同一 normalized 给同一档，
   `S10-03` 全扫验证），并在报告里给出逐日归因。**如果 PM 的本意是「同一份数据必须给出同一档位」，
   那本批无法满足，需要重新设计权重**（见 §5 待拍决策 1）。

### 另外两个我需要说明的（不算"不确定"，但影响验收口径）

- **techGreen 从「近似 0.2 有效权重」变成 0.3**、**resource 从 0.6 掉到 0.5**，这两处对 11-28 的
  影响最大（techGreen +0.60、resource −0.33）。根因是 carbonPrice +1.0 从 resource 搬到 techGreen，
  以及 LME/参考项移出分母。这是工单 §1 表规定的搬家结果，不是打分口径改动；但它**确实**改变了维度分，
  且 §8 风险表没有点名 resource（只点了 liquidity）。
- **`breakpoint_steps` 是我新加的打分方法名**（工单写的是 `breakpoint`）。现有 `breakpoint` 是三段**线性**，
  无法表达「7.05~7.20 → 0」这种区间阶梯（线性会把区间中点算成半档）。配置放在
  `indicator_meta.BREAKPOINT_STEPS_CONFIG`，未改动任何既有指标的打分。若 PM 要求方法名严格叫
  `breakpoint`，我可以改名，但语义仍是阶跃，需要同步改 `S9` 的方法白名单。

---

## 5. 需要 PM 拍的决策

1. **§4 验收口径二选一**：
   (a) 「同一 normalized → 同一档位」（我实现的，`S10-03` 已证）；或
   (b) 「同一份当日数据 → 同一档位」（当前**不满足**：11-28 结构变化导致 持有→减仓，
       除非砍掉导致移动的搬家项）。请明确以哪个验收。
2. **usdcnh 缺失是否允许照常出分**：当前 fxExternal 4 项需 ≥2 有效，usdcnh 缺失仍出分（3/4），
   于是 IAS 档位会被 usdcnh 单点翻转（§4 不确定项 2）。要不要改成「usdcnh 必须有效才出 IAS」？
3. **usdcnh 分段阈值是否重标**：现值 7.05/7.20/7.35 是 7.2 时代的区间，而今日离岸价 6.6551
   → 恒为 +0.5（人民币「偏强」档）。要不要按当前汇率中枢重标（例如 6.70/6.85/7.00）？
   本批按工单原值实现，未擅自改。
4. **回算天数**：接受 19 天（现有快照全量），还是另开单补 30 天（需给 31 个指标回填历史序列）？

---

## 6. 提交

两笔本地 commit（**未 push、未部署**）：

1. `feat(P1-8DIM): 6→8 维骨架搬家（维度拆分/指标搬家/usdcnh/阈值 normalized）` —— 代码 + 测试 + 夹具 + 文档
2. `data(P1-8DIM): 8 维重建 market-data + 19 日回算产物` —— `public/dist` 数据 + `data/history/recompute-*.json`

回滚：`git revert <data-commit> && git revert <code-commit>`（顺序反着来，先撤数据再撤代码）。

---

## 6. A2（2026-11-28）：usdcnh 打分重标 —— 去掉永久多头偏置

### 6.1 为什么必须重标

旧配置 `breakpoint_steps=(7.05,7.20,7.35)` 是 7.2 时代的水位；当前离岸价 6.6551
永远 `< 7.05` → 恒为 `+0.5`。这不是「人民币偏强」的判断，而是**给 fxExternal 灌了一个永久常数**，
与 11-27 已认定要修的第三类 bug（EV 渗透率/碳价「越阈值后永久 +1」）同病。

### 6.2 改了什么（只动 usdcnh）

| 项 | 批次 A（旧） | A2（新） |
|---|---|---|
| 数据源 | `akshare.forex_spot_em` 离岸**现货**（无日期 → realtime） | `akshare.forex_hist_em('USDCNH')` 东财**日线**（带真实交易日；实测 4232 行） |
| 序列 | 不写 series（不要求历史） | 回填最近 **250 个交易日** → `data/history/series/usdcnh.json`（2025-12-15 → 2026-11-27） |
| 打分 | 固定水位 `7.05/7.20/7.35` 四段 | `ratio = USDCNH / MA120`（120 个交易日收盘均值，**含当日**）五档阶跃 |
| 档位 | `<7.05 +0.5 / 7.05~7.20 0 / …` | `≤0.985 +1.0 / ≤0.995 +0.5 / ≤1.005 0 / ≤1.015 −0.5 / >1.015 −1.0` |
| 方向 | 数值越高越差（但永不触发） | **人民币越弱（ratio 越高）= 越差**，写进代码注释与 caliberNote |
| 历史不足 | 不适用 | **<120 个点 → score=null**（不硬填、不插值），维度照常 3/4 有效出分 |
| 页面口径 | 只写「离岸人民币汇率」 | `caliberNote` 明示：`当前 6.6551 vs 120 日均值 6.7239 = -1.02%（ratio 0.9898→+0.5）` |

代码落点：
- `indicator_meta.py::INDICATORS['usdcnh']` + `RATIO_MA_STEPS_CONFIG`；`BREAKPOINT_STEPS_CONFIG` 现为空（不再有固定水位）。
- `scoring.py::ratio_ma_steps_score` / `score_by_ratio_ma`（唯一实现）+ `build_indicators_and_meta` 分支。
- `fetch_worldos_data.get_usdcnh()` 改日线；`backfill_series.build_usdcnh()` 回填 250 日。
- `replay_8dim_30d.py`：按 `date < 快照日` as-of 注入 usdcnh（无未来函数），并写 `usdcnh_no_lookahead`。

### 6.3 锚点核对（必须对上）

```
250 条序列：2025-12-15 → 2026-11-27，最新 6.6551
MA120（含 11-27）= 6.723853   ← 工单参考 6.7239 ✔
ratio = 6.6551 / 6.723853 = 0.989775   ← 工单参考 0.9898 ✔
偏差 = -1.023% → 落在 +0.5 档（人民币偏强，真实信号）
```

### 6.4 验证原始输出（四项全绿）

```
$ python3 scripts/test_schema_fields.py
...
✅ S11-00[usdcnh]
✅ S11-01[ratio 5 档探针]
✅ S11-02[边界归属 ≤上界]
✅ S11-03[方向: 人民币越弱分越低]
✅ S11-04[<120 点 warmup=null]
✅ S11-05[=120 点即可出分]
✅ S11-06[warmup 不破维度]
✅ S12-01[无未来函数]
✅ S12-02[MA120 可由序列复算]
✅ S12-03[产物声明]
...
157 passed / 0 warn / 0 failed / 157 total

$ python3 scripts/test_no_nan_json.py
全部通过：3 个模块均不会产出非法 JSON

$ node --test tests/caliber-edge.test.mjs
ok 1 - tests/caliber-edge.test.mjs
# ✅ 全部通过：291 项断言
# pass 1 / fail 0

$ npm run build
✓ built in 75ms
```

新增断言（对应工单验收）：
- **S11-01**：0.98/0.99/1.0/1.01/1.02 → +1.0/+0.5/0/−0.5/−1.0 逐档命中。
- **S11-02**：边界归属（`≤ 上界归本档`）逐点钉死，含 0.985/0.995/1.005/1.015。
- **S11-04/05**：118+1 点 → warmup/null；119+1=120 点 → 出分。**S11-06**：usdcnh warmup 时 fxExternal 仍 3/4 有效出分。
- **S10-04b**：线上分数必须等于「ratio 5 档表」重算值（防止旧水位复活/手填）。
- **S10-04c**：caliberNote 必须含「120 日均值」与带符号偏差。
- **S12-01/02**：回算每个快照日 `max_used_date < 当日`；且 `ma_base/ratio/score` 可用日线序列独立复算一致。

### 6.5 敏感性对照表（11-28 同日、同数据）

| 项 | A2 前（固定水位） | A2 后（ratio 真实档） |
|---|---|---|
| usdcnh 值 / 日期 | 6.6551 / 无日期（realtime） | 6.6551 / 2026-11-27（fresh，1 天） |
| usdcnh 打分方法 | `breakpoint_steps` 7.05/7.20/7.35 | `ratio_ma_steps` MA120=6.7239, ratio=0.9898 |
| usdcnh score | **+0.5** | **+0.5**（落在 +0.5 档，非恒定） |
| fxExternal 维度分 | **+0.026** | **+0.026** |
| IAS score / normalized | **−0.57 / −0.102** | **−0.57 / −0.102** |
| IAS 信号 | **持有** | **持有** |

> **诚实结论：11-28 当天数值零位移**——因为 ratio 0.9898 恰好也落在 +0.5 档。
> 但这不再是「无论汇率多少都给 +0.5」：下面探针显示档位一旦移动，结论会动。

档位敏感性（其余维度冻结，用同一份 11-28 数据重算）：

| usdcnh score | fxExternal | IAS score | normalized | 信号 |
|---|---|---|---|---|
| +1.0 | +0.151 | −0.48 | −0.0864 | 持有 |
| **+0.5（实际）** | **+0.026** | **−0.57** | **−0.1020** | **持有** |
| 0 | −0.099 | −0.66 | −0.1176 | **减仓** |
| −0.5 | −0.224 | −0.75 | −0.1333 | 减仓 |
| −1.0 | −0.349 | −0.83 | −0.1489 | 减仓 |

> 含义：usdcnh 从 +0.5 掉一档到 0，IAS 就跨过 −0.109 → 减仓。以前这条线**永远不会响**，
> 现在会随汇率真实波动。11-28 的「持有」仍只有 0.007 余量（与批次 A 报告一致）。

### 6.6 19 日回算重跑（usdcnh 历史已就绪，无未来函数）

回算口径：对每个快照日 `D`，usdcnh 取 `date < D` 的**最近收盘**作为当日值，MA120 只用该日及之前的
119 条观测（含当日共 120 点）。脚本内与测试内各有一道断言：所有被使用的 usdcnh 日期必须 `< D`。

```
共 19 个快照，信号档位翻转 3 天
  ★ 2026-11-18: 持有 → 数据不足（缺失剔除（覆盖率跌破 0.6））
  ★ 2026-11-19: 持有 → 减仓（部分维度缺失·参考）（结构/权重）
  ★ 2026-11-20: 持有 → 减仓（部分维度缺失·参考）（结构/权重）
  ✅ usdcnh 无未来函数：每个快照日只使用 date < 当日 的观测
```

与批次 A（无 usdcnh 历史）相比，翻转从 6 天降到 3 天：11-24/26/28 因 usdcnh 真实 +0.5 被拉回「持有」。
19 天里 ratio 区间为 0.9898~0.9945（−1.02%~−0.55%），**全部落在 +0.5 档**——这是「这段时间人民币持续偏强」
的真实状态，不是常数：一旦 ratio > 0.995 就会掉到 0 档（见 6.5 探针）。

### 6.7 A2 我不确定的 3 件事

1. **MA120「含当日」的定义**：工单参考 6.7239 只在「末尾 120 个收盘含最新 6.6551」时成立（排除最新则 6.7248）。
   我按含当日实现，并在回算里把「当日」解释为「快照日之前最近的收盘」——仍无未来函数。
   若 PM 要的是「前 120 日均值（不含当日）」，锚点会变成 6.7248/0.9896（仍是 +0.5 档），需一句话确认。
2. **`rules_hash` 不会因本次改动而变**（仍 `ae148d2b8a6d`）：`rules_snapshot()` 目前只固化维度权重/阈值，
   不含单指标打分参数。也就是说 A2 改了打分规则，但 hash 看不出来。要不要把单指标参数纳入 hash，
   属于规则快照的契约变更（会让所有历史快照 hash 不可比），我没有擅自动。
3. **在岸回退价会污染 ratio**：主源日线失败时仍保留 exchangerate-api 在岸价兜底（页面标注降级）。
   在岸/离岸价差通常 0.1~0.3%，对 ratio 影响小于一个档距（1%），但若长期用兜底值，MA120 会慢慢偏。
   是否要在「本轮为在岸回退」时直接不给 usdcnh 出分（宁缺勿错），请 PM 拍。
