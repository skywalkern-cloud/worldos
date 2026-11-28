# P1-8DIM 交付报告（A4 收口版）

- 日期：2026-11-28
- 范围：A4 最后一批（P0 降级污染序列、回算补齐、龙六 3 条必改、文案杂项、看门狗）
- 工作目录：`~/.openclaw/workspace-worldos`
- 当前构建输入：`public/data/market-data.json`
- 回算产物：`data/history/recompute-8dim-2026-11-28.json`
- **本文件是唯一现行结论。批次 A / A2 / D7 的旧结论已被本文件取代，旧表格已删除。**

---

## 0. 当前结论（2026-11-28，唯一口径）

| 项 | 值 |
|---|---|
| IAS score | **−0.23** |
| IAS normalized | **−0.041286**（6 位） |
| 信号 | **持有**（建议仓位 40–60%） |
| 有效权重 | 5.6 / 5.6（覆盖 100%） |
| 边界余量 `boundary_margin` | **+0.067714**（最近阈值 −0.109；跨档后 = 减仓） |
| 置信度 | **high**（无降级项、无整维剔除、余量 > 0.05） |
| 饱和计分项 | 4 项：`ppi` / `carbonPrice` / `evPenetration` / `shanghaiCopper` |
| rules_hash | `5df4722e09e9` |

> 与 A4 前（批次 A/A2/D7 产物）相比：normalized −0.102 → **−0.041286**，仍为「持有」，
> 但边界余量从 0.007 扩大到 **0.0677**。位移来源只有两处，且都是本次龙六必改：
> ① `creditSpread` 退出打分（fxExternal +0.026 → +0.258）；
> ② `chinaBond10Y` 进入 liquidity（liquidity +0.011 → +0.233）。
> 其余 6 个维度分数逐位不变。

---

## 1. 验收：四套测试 + 构建

```
$ python3 scripts/test_schema_fields.py
✅ S0[readonly]
189 passed / 0 warn / 0 failed / 189 total

$ python3 scripts/test_no_nan_json.py
✅ fetch_worldos_data: _sanitize + write_json_strict 通过
✅ generate_commentary_llm: _sanitize + write_json_strict 通过
✅ commentary_generator: _sanitize + write_json_strict 通过
全部通过：3 个模块均不会产出非法 JSON

$ node --test tests/caliber-edge.test.mjs
# ✅ 全部通过：300 项断言
ok 1 - tests/caliber-edge.test.mjs
# tests 1 / pass 1 / fail 0

$ npm run build
✓ 19 modules transformed.
dist/index.html                   0.48 kB
dist/assets/index-*.css          43.31 kB │ gzip: 7.37 kB
dist/assets/index-*.js          232.40 kB │ gzip: 72.74 kB
✓ built in ~77ms
```

新增断言覆盖：A（S13-09 降级不写序列）、C（S14 饱和）、D（S15 归属与不计分）、
E（S16 三个新字段），以及旧分支矩阵随新结构同步（S8/S10/S11/S13）。

---

## 2. A4 逐项交付

### A. P0：降级值不得污染历史序列 —— ✅

**问题**：`fetch_worldos_data.py` 的 series 回写循环只判 `val` / `dd`，不判 `sourceDegraded`。
usdcnh 主源失败回退在岸价时，在岸价会被 `upsert` 进 `data/history/series/usdcnh.json`，
并进入此后最多 120 个交易日的 MA120。D7 只拦了打分，没拦住喂序列。

**修法**：
- 把回写循环抽成唯一实现 `sync_series(results)`；
- `if v.get('sourceDegraded'):` → **跳过 upsert、跳过 history 注入**，并打印
  `⏭️ usdcnh: 源降级（primary_source_missing），跳过序列回写与 history 注入`；
- 降级值仍保留在 `data`/`indicators` 里供页面展示，但 `history` 不挂载 → 打分侧自然 `score=null`。
- 同类检查：目前进入 series 的 key 只有 `usdcnh` + 4 个 A股/港股代理；后者没有
  `sourceDegraded` 路径，但新逻辑对全部 `PCT_SERIES_KEYS` 生效，不存在第二个漏口。

**测试证据**（S13-09）：

```
✅ S13-00[源2命中]
✅ S13-01[降级信号外带]
✅ S13-02[降级→score=null 且不留半套数]
✅ S13-03[降级标在 caliberNote]
✅ S13-04[excluded + 专属理由码]
✅ S13-05[值仍展示 6.6551]
✅ S13-06[降级不破维度 2/3 出分]
✅ S13-07[正常态对照：同值仍出分]
✅ S13-08[降级不波及他项]
✅ S13-09[降级不写序列]      ← 新增：临时 SERIES_DIR，先写正常值，再喂 sourceDegraded，
                                断言 base == after、降级日不存在、skipped == ['usdcnh']、
                                bad_day.usdcnh 未被注入 history
```

### B. 回算修正：所有 series 指标 as-of 注入 —— ✅

**问题**：回算只 as-of 注入了 usdcnh，另外 4 个有 400 日 series 的指标没有挂 history →
`pct_rank` warmup → 18/19 天 `sentimentA=null`，实际是 7 维回算。

**修法**：
- `SERIES_KEYS = list(im.QUANTILE_CONFIG)`（usdcnh + ashareTurnover / marginBalance /
  southboundNet / hstechMomentum）；
- 每个快照日 `D`，对每条 series 取 **`date < D` 的最近收盘**，并挂该日之前的全部历史；
- 新增 `series_no_lookahead` 断言：所有被使用的日期必须 `< D`（不只 usdcnh）；
- 旧快照没有 `chinaBond10Y`（本批新增），用同一快照的「美债10Y − 中美利差」反算
  （同源、不造数），否则历史 liquidity 仍是 3 项、与 live 4 项不可比。

**19 日逐日对照（旧 6 维结构 vs 新 8 维，最终模型）**

```
日期          旧score  旧norm     旧信号   新score  新norm     新信号   翻转
2026-11-09   -0.32   -0.0685    数据不足   -0.73   -0.130071  数据不足
2026-11-10   -0.32   -0.0685    数据不足   -0.73   -0.130071  数据不足
2026-11-11   -0.32   -0.0685    数据不足   -0.73   -0.130071  数据不足
2026-11-12   -0.32   -0.0685    数据不足   -0.73   -0.130071  数据不足
2026-11-13   -0.32   -0.0685    数据不足   -0.73   -0.130071  数据不足
2026-11-14   -0.32   -0.0685    数据不足   -0.77   -0.137214  数据不足
2026-11-16   -0.32   -0.0685    数据不足   -0.77   -0.137214  数据不足
2026-11-17   -0.32   -0.0685    数据不足   -0.77   -0.137214  数据不足
2026-11-18   -0.44   -0.096     持有       -0.61   -0.108485  数据不足   ★
2026-11-19   -0.52   -0.113682  减仓       -0.44   -0.079208  持有       ★
2026-11-20   -0.53   -0.114545  减仓       -0.50   -0.088887  持有       ★
2026-11-21   -0.43   -0.093909  持有       -0.31   -0.055786  持有
2026-11-22   -0.43   -0.093727  持有       -0.31   -0.055286  持有
2026-11-23   -0.50   -0.108773  持有       -0.37   -0.066125  持有
2026-11-24   -0.55   -0.118727  减仓       -0.34   -0.061161  持有       ★
2026-11-25   -0.47   -0.102091  持有       -0.23   -0.040250  持有
2026-11-26   -0.57   -0.124     减仓       -0.39   -0.069036  持有       ★
2026-11-27   -0.64   -0.140182  减仓       -0.57   -0.101107  持有       ★
2026-11-28   -0.43   -0.093636  持有       -0.23   -0.041286  持有

共 19 个快照，信号档位翻转 6 天
  ★ 11-18 持有 → 数据不足（覆盖率跌破 0.6）
  ★ 11-19/20 减仓 → 持有（结构/权重 + 中债10Y）
  ★ 11-24/26/27 减仓 → 持有（结构/权重 + 中债10Y）
  ✅ 所有 series 无未来函数：每个快照日只使用 date < 今日 的观测
```

**关于「11-21/24/26 应从持有变减仓」**：这是泰斯特在**只做 B 修正、尚未叠加 D** 时的诊断结论。
B 单独修正确实复现了泰斯特的 5/19 天差异与 11-21/24/26 减仓；叠加龙六 D（去掉 fxExternal 里
重复的 creditSpread 负分、liquidity 加入中债10Y +0.90）后，同几天被拉回「持有」。
交付以最终模型为准——这里没有两套结论，只有「B 单独」与「B+D 最终」两种阶段，最终数只有一套。

**报告与产物对齐**：本文件与 `recompute-8dim-2026-11-28.json`、
`public/data/market-data.json` 三处的 11-28 均为 **normalized −0.041286 / score −0.23 / 持有**。
旧表格已整段删除，本文件不保留第二套结论。

### C. 龙六必改 1：饱和披露 —— ✅

- scoring 原有 `saturated`（pct_rank / ratio_band / ratio_ma）保留；
- 新增 breakpoint 类判据：`score` 非空且 `|score| ≥ 1−1e-9` → `saturated=true`；
- **每个 indicator 产物都带 `saturated: true/false`**；
- 维度级新增 `saturated_count` / `saturated_indicators`（只统计 α>0、真正进平均的项）；
- IAS 新增 `saturated_inputs`（本期全部饱和计分项）。

今日命中（4 项，与泰斯特一致）：`ppi +1.0`、`carbonPrice +1.0`、`evPenetration +1.0`、
`shanghaiCopper −1.0`。维度披露：inflation 1 项、resource 1 项、techGreen 2 项。

前端：
- 指标行徽标：**「已到区间上界·不携带信息」**（amber，tooltip 说明不应当独立看多/看空证据）；
- 维度卡片计数行：**「· N 项饱和」**；
- IAS 卡片：**「含 N 项饱和」**。

断言（S14）：

```
✅ S14-01[±1.0 ⇒ saturated=true]   （喂 5.7% PPI / 97 碳价 / 92550 沪铜 / 67.4 EV）
✅ S14-02[未截断项 saturated=false]
✅ S14-03[维度级计数]               inflation=1, techGreen=2
✅ S14-04[IAS 饱和总表]
```

### D. 龙六必改 2：拆掉汇率维度的重复计价 —— ✅

| 项 | A4 前 | A4 后 |
|---|---|---|
| fxExternal 计分项 | usdcnh / dollarIndex / creditSpread / usBond10Y（4） | usdcnh / dollarIndex / usBond10Y（3） |
| creditSpread | 计分（−0.67） | **reference_indicators，只展示不计分** |
| liquidity 成员 | lpr / dr007 / m2（3，需全有效） | **lpr / dr007 / m2 / chinaBond10Y（4，最小有效 2）** |
| 权重 | fx 0.7 / liquidity 0.8 | **不变** |
| 数据源 | creditSpread 走 `ak.bond_zh_us_rate()` | 同一请求同时取 `CN10Y`；`chinaBond10Y = 该行 CN10Y`，`creditSpread = (US10Y−CN10Y)×100`，不新增源 |

`chinaBond10Y` 打分：NEGATIVE `(1.5, 2.5, 4.0)`（收益率越低 = 国内货币环境越松 = 分越高）；
今日 1.60% → **+0.90**。

**改后 11-28 维度/权重/得分对照**

| 维度 | A4 前 score | A4 后 score | 有效权重 | 饱和项 |
|---|---:|---:|---:|---|
| 经济增长 | −0.250 | −0.250 | 1.0 | 0 |
| 通胀与政策 | +0.113 | +0.113 | 1.0 | 1 |
| 流动性（国内） | +0.011 | **+0.233** | 0.8 | 0 |
| 汇率与外部 | +0.026 | **+0.258** | 0.7 | 0 |
| A股/港股情绪 | −0.302 | −0.302 | 0.9 | 0 |
| 全球风险偏好 | −0.505 | −0.505 | 0.4 | 0 |
| 资源与供应链 | −0.333 | −0.333 | 0.5 | 1 |
| 科技与绿色 | +0.597 | +0.597 | 0.3 | 2 |
| **IAS normalized** | **−0.1020** | **−0.041286** | Σ5.6 | 4 |
| **信号** | 持有 | **持有** | | |

断言（S15）：

```
✅ S15-01[chinaBond10Y 进 liquidity]
✅ S15-02[liquidity 4 项、最小有效 2]
✅ S15-03[creditSpread 转参考项]
✅ S15-04[usBond10Y 仍在打分]
✅ S15-05[中债10Y 打分方向] 1.60% → +0.9
✅ S15-06[creditSpread 不计分]
✅ S15-07[fx 均分不含利差] active=3 ref=1
```

### E. 龙六必改 3：边界余量披露 —— ✅

`meta.ias` 新增：

```json
{
  "boundary_margin": 0.067714,
  "boundary_threshold": -0.109,
  "boundary_next_signal": "减仓",
  "fragile_inputs": [],
  "fragile_details": [],
  "degraded_inputs": [],
  "confidence": "high",
  "saturated_inputs": ["ppi", "carbonPrice", "evPenetration", "shanghaiCopper"]
}
```

- `boundary_margin = normalized − 最近阈值`（带符号；>0 在内侧，<0 已越界）；
- `fragile_inputs`：逐维剔除后若信号改变则列入，按 `|normalized_without − normalized|` 降序；
  `fragile_details` 给出剔除后的 normalized / 信号 / 影响；
- `confidence`：`<0.02` 或任一整维剔除或任一打分项降级 → `low`；`<0.05` → `medium`；否则 `high`。

今日余量 0.0677，远离刀锋，故 `fragile_inputs=[]`、confidence=high。
页面仍显式展示 **「距翻档 0.068 · 下档减仓」+「置信度高」+「含 4 项饱和」**；
若余量 <0.02 会切成红色徽标，并显示「掉任一维度即变{下一档}」。

断言（S16）：字段存在、余量恒等式、confidence 枚举、fragile 子集且按影响降序。

### F. 文案与杂项 —— ✅

1. **PPI / 沪铜方向待修正披露**：caliberNote 已显式写入
   「**方向待批次 C 修正**：当前 PPI 成本冲击按利好计价 / 沪铜为负向代理」，
   并写明 5.7% 已越过上界恒为 +1.0、92,550 给 −1.0 不代表看空铜。
2. **epu 不再孤儿**：挂到 `inflation.reference_indicators`（只展示、不计分），页面可见。
3. **僵尸脚本清理**：`scripts/replay_sentiment_30d.py` 删除；现行唯一回算脚本为
   `scripts/replay_8dim_30d.py`（已修好，见 B）。没有保留同名双份。
4. **旧 Dashboard 死代码**：确认 `src/components/Dashboard.tsx` 无任何 import/路由引用后
   **整文件删除**；`src/data/marketData.ts` 仅保留给 `realtime.ts` / 旧 alerts 测试，
   注释已去掉对 Dashboard 的引用。页面已无「市场情绪」旧卡。
5. **权重文案**：维度卡从 `w=0.7` 单标改为 **`w=0.7 · eff=0.7`**，
   tooltip 明确「设计权重 w / 有效权重 eff」，收缩时 eff 标 amber 并给出原因。

### G. 看门狗 —— ✅

新增 `scripts/health_check.py`，`check_document(doc)` 输出三类告警：

1. `usdcnh` 降级（`sourceDegraded` 或 `degraded_no_score`）；
2. 任一维度 `insufficient_data=true`（带 valid/required 与丢失权重）；
3. `|boundary_margin| < 0.02`（带脆弱维度与跨档后信号）。

已挂到 `fetch_worldos_data.save_results()` 保存后打印 `🩺 WARN:`；**不新增 cron、不阻断抓取、不改退出码**。
也可手动：`python3 scripts/health_check.py [json]`。

原始输出（当前产物无告警；用夹具/注入演示三类都能触发）：

```
$ python3 scripts/health_check.py
✅ 健康检查通过：public/data/market-data.json

$ python3 scripts/health_check.py tests/fixtures/market-data-edge-cases.json
🩺 3 条告警
  - 维度被剔除：流动性（国内）（liquidity） valid=0 < required=2，丢失有效权重 0.8
  - 维度被剔除：汇率与外部（fxExternal） valid=0 < required=2，丢失有效权重 0.7
  - 维度被剔除：科技与绿色（techGreen） valid=1 < required=3，丢失有效权重 0.3

# 注入 usdcnh 降级 + boundary_margin=0.007：
WARN usdcnh 降级：primary_source_missing（…）；在岸回退价只展示、不计分、不进历史序列
WARN IAS 刀锋：boundary_margin=+0.0070（<0.02） 距阈值 -0.109 仅一步；跨档后信号=减仓
```

---

## 3. 页面实拍（本地 preview，1440×2600）

截图：`docs/shots/a4-2026-11-28.png`（全页）；关键区域：

- IAS 卡：`−0.23 · 持有 · 建议仓位 40–60%`，下方 `数据覆盖 100% / 有效权重 5.6/5.6 /
  归一化 −0.0413 / 距翻档 0.068 · 下档减仓 / 置信度高 / 含 4 项饱和`；
- 维度卡：8 张（economic / inflation / liquidity / fxExternal / sentimentA / riskAppetite /
  resource / techGreen），头部 `w=… · eff=…`；
- 通胀卡：`· 1 项饱和`，PPI 行徽标 `已到区间上界·不携带信息`；
- 流动性卡出现 `中国10年国债收益率 1.60% → +0.90`；
- 汇率卡 `中美10年利差 334bp` 为参考项（不计分）；
- 旧「市场情绪」卡片不存在。

---

## 4. 产物与提交边界

| 文件 | 说明 |
|---|---|
| `scripts/fetch_worldos_data.py` | `sync_series()` 降级跳过 + `chinaBond10Y` 取数 + 健康检查调用 |
| `scripts/scoring.py` | 饱和字段/维度计数、chinaBond10Y 参数、IAS 边界余量/脆弱输入/置信度 |
| `scripts/indicator_meta.py` | chinaBond10Y、creditSpread 转参考、epu 挂 inflation、`required_valid` 覆盖 |
| `scripts/replay_8dim_30d.py` | 全 series as-of 注入 + chinaBond 同源反算 + 无未来函数断言 |
| `scripts/health_check.py` | 新增看门狗（仅判据与日志） |
| `scripts/test_schema_fields.py` | 新增 S13-09 / S14 / S15 / S16，旧分支随新结构更新 |
| `tests/fixtures/market-data-edge-cases.json` | 按新结构重新生成（含 chinaBond10Y 过期分支） |
| `src/App.tsx`、`src/lib/caliber.ts`（未改逻辑） | 饱和徽标、边界余量、w/eff、类型 |
| `src/components/Dashboard.tsx` | 删除（未挂载死代码） |
| `scripts/replay_sentiment_30d.py` | 删除（僵尸脚本） |

- 本地 commit，**不 push、不部署、不改 cron**。
- `dist/` 为构建产物，随本次 build 更新；`data/history/*` 仍按既有规则只强制入库回算产物。

---

## 5. 我不确定的 3 件事

1. **fxExternal 的 `required_valid=2` 是我加的显式覆盖**。龙六 D 把计分项从 4 降到 3，
   若沿用 T4「n≤3 必须全部有效」，usdcnh 一旦降级整维直接归零，与 D2/D7「降级仍可出分」冲突。
   我选择 `required_valid=2` 保住 D2；但这相当于在维度配置层开了一个此前没有的覆盖口。
   **是否允许这个口子，还是接受 usdcnh 降级时 fxExternal 整维置灰？请 PM/龙六拍。**

2. **`chinaBond10Y` 的打分参数（NEGATIVE 1.5 / 2.5 / 4.0）是我按当前利率中枢暂定的**，
   设计评审只要求「进 liquidity、复用数据源」，没给断点。今日 1.60% → +0.90，
   对 liquidity 和 IAS 的影响不小（约 +0.03 normalized）。**断点应由龙六正式标定**；
   若标定不同，11-28 的 normalized/边界余量会跟着变。

3. **回算里 `chinaBond10Y` 用「美债10Y − 中美利差」反算、series 用严格 `< 快照日`**。
   这两个口径都能保证无未来函数，但：① 反算值不是独立抓取值（同源推导）；
   ② `<` 比「≤ 当日」多滞后一个交易日，11-18 因此触发 alpha=0/覆盖率跌破 0.6 的「数据不足」。
   若泰斯特/PM 要求「≤ 当日」或「禁止反算」，19 日表的个别行（尤其 11-18）会变。
   我按与泰斯特 §5.3 一致的 `<` 实现，并把选择写在这里，不藏在代码里。

---

## 6. 验收勾选

- [x] A 降级不写序列 + 回归断言 S13-09
- [x] B 全 series as-of 注入 + 19 日重出 + 报告/产物统一为 −0.041286
- [x] C 饱和 indicator/维度/IAS 三级披露 + 前端徽标 + S14
- [x] D chinaBond10Y 入 liquidity、creditSpread 转参考、权重不变 + 新旧对照 + S15
- [x] E boundary_margin / fragile_inputs / confidence + 前端展示 + S16
- [x] F ppi/沪铜方向披露、epu 挂载、僵尸脚本删除、Dashboard 删除、w/eff 文案
- [x] G 三类看门狗告警（仅判据与日志，无新 cron）
- [x] 四套测试全绿 + 本地 build + preview 实拍
- [x] 本地 commit，不 push / 不部署 / 不改 cron
