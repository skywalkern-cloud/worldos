# P1-8DIM 交付报告（A5 发版收口版）

- 日期：**2026-11-28 18:15**（A5 为当日最后一批）
- 范围：A5 = 泰斯特 A4 复核抓的 6 条硬伤（P0×2 / P1×5），全部修完才发版
- 工作目录：`~/.openclaw/workspace-worldos`
- 当前构建输入：`public/data/market-data.json`（由 `replay_8dim_30d.py --rebuild-live` 重出）
- 回算产物：`data/history/recompute-8dim-2026-11-28.json`（按快照日时钟重跑）
- **本文件是唯一现行结论。A4 及更早报告的数值已被本文件取代。**

---

## 0. 当前结论（2026-11-28，最终全量口径）

| 项 | 值 |
|---|---|
| IAS score | **−0.31** |
| IAS normalized | **−0.055571**（6 位） |
| 信号 | **持有**（建议仓位 40–60%） |
| 有效权重 | 5.6 / 5.6（覆盖 100%） |
| 翻档（P1-1 新字段） | `next_direction=down`、`next_threshold=−0.109`、`next_signal=减仓`、距离 **0.053** |
| 置信度 | **high**（无降级、无整维剔除、距离 > 0.05） |
| 饱和计分项 | 4 项：`ppi`(upper) / `carbonPrice`(upper) / `evPenetration`(upper) / `shanghaiCopper`(**lower**) |
| commentary.json | score **−0.31** / normalized **−0.055571**（与 meta.ias 逐位一致） |
| rules_hash | `5df4722e09e9` |

**与 A4 收口值的差异（−0.23 / −0.041286 → −0.31 / −0.055571）只有一处来源：P1-3。**
`chinaBond10Y` 从「固定水位 1.5/2.5/4.0 → +0.9」改成「相对 120 日均值 ratio → +0.5」，
liquidity +0.233 → **+0.133**，Δnormalized = −0.4×0.8/5.6 = **−0.0143**。
其余 7 维分数逐位不变（边界余量仍是 0.053、方向 down，未掉档）。

---

## 1. 验收：四套测试 + 构建（原始输出）

```
$ python3 scripts/test_schema_fields.py
✅ S17-01[commentary score == meta.ias.score]
✅ S17-02[commentary normalized == meta.ias.normalized]
✅ S17-03[正文首句数字 == score]
✅ S17-04[dist commentary == public]
✅ S18-01[Day1 降级不写序列]
✅ S18-02[Day2 兜底不写序列]
✅ S18-03[序列里既无降级值也无兜底值]
✅ S18-04[两日均不挂 history]
✅ S19-01[上下半区方向/目标档/距离 4 探针]
✅ S19-02[next_* 与 boundary_* 同值]
✅ S20-01[+1.0 → upper]
✅ S20-02[−1.0 → lower]
✅ S20-03[未饱和 → side=None]
✅ S21-01[走 ratio_ma_steps、固定水位已移除]
✅ S21-02[caliberNote 写相对均值/边际宽松/非绝对水位]
✅ S21-03[五档边界探针 9 点]
✅ S21-04[历史不足 120 日 → score=null]
✅ S21-05[整链复算 ratio→score]
✅ S22-01[默认（无缺失信息）仍是 2]
✅ S22-02[3 项全有效 → required=3]
✅ S22-03[缺 usdcnh → required=2]
✅ S22-04[缺 dollarIndex → required=3]
✅ S22-05[缺 usBond10Y → required=3]
✅ S22-06[缺 usdcnh → 出分]
✅ S22-07[缺 dollarIndex → 整维 insufficient]
✅ S22-08[缺 usBond10Y → 整维 insufficient]
✅ S23-01[α 按传入的 today 算]
✅ S23-02[build_indicators_and_meta 透传 today]
✅ S23-03[19 天回算无「数据不足」、覆盖率 ≥0.9]
✅ S23-04[11-09~11-18 九天修复]
✅ S23-05[序列无未来函数]
220 passed / 0 warn / 0 failed / 220 total

$ python3 scripts/test_no_nan_json.py
✅ fetch_worldos_data: _sanitize + write_json_strict 通过
✅ generate_commentary_llm: _sanitize + write_json_strict 通过
✅ commentary_generator: _sanitize + write_json_strict 通过
全部通过：3 个模块均不会产出非法 JSON

$ node --test tests/caliber-edge.test.mjs
# [P1] 翻档方向（next_direction）与饱和侧（saturated_side）
#   ✅ 真实产物 4 项饱和侧正确
# ✅ 全部通过：320 项断言
ok 1 - tests/caliber-edge.test.mjs
# tests 1 / pass 1 / fail 0

$ npm run build
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-WR__p2Yx.css   43.31 kB │ gzip:  7.37 kB
dist/assets/index-CNSohLky.js   233.13 kB │ gzip: 72.97 kB
✓ built in 76ms
```

新增断言：P0-1（S17，4 条）、P0-2（S18，4 条链式）、P1-1（S19 + node 10 条）、
P1-2（S20 + node 4 条）、P1-3（S21，5 条）、P1-4（S22，8 条）、P1-5（S23，5 条）。
旧的 S5-04 / S9-06 / S15-05 随新口径同步（不是放宽，是改成按 `required_valid` 新签名/相对均值重算）。

---

## 2. A5 逐项交付

### P0-1 commentary.json 是旧的 —— ✅ 已修 + 防复发断言

**证据**：A4 只改了 `commentary_generator.py`，产物仍是 17:36 的旧值（页面头 −0.23 / 正文 −0.57），
`dist/data/commentary.json` 同旧。

**改动**
- `commentary_generator.py` / `generate_commentary_llm.py`：`ias` 块新增 `normalized`，写入后**同步 dist**
  （`dist/data/commentary.json` 与 public 逐字节一致）。
- 重生成 `public/data/commentary.json`：score **−0.31**、normalized **−0.055571**、正文首句 **−0.31**。

**测试（S17，防「改一半」）**
- `S17-01` commentary.ias.score == meta.ias.score
- `S17-02` commentary.ias.normalized == meta.ias.normalized
- `S17-03` 正文首句 `IAS综合评分**X**` 的 X == score（只改字段不改文案也会红）
- `S17-04` dist 与 public 逐字一致

### P0-2 兜底值二次污染序列 —— ✅ 已修 + 链式测试

**路径**：Day1 主源失败→在岸降级（已正确跳过）→ Day2 **全源失败**→ `load_prev()` 只回填
`value/dataDate`（`sourceDegraded` 丢失）→ 兜底分支又显式清空 → 在岸 6.62 被写进序列。

**改动**：`sync_series()` 判据改为
`if v.get('sourceDegraded') or v.get('used_fallback'): continue`（**写序列与 history 注入都跳过**）。
兜底值本来就在序列里（同日同值，跳过无损）；「降级日的兜底」跳过即正确。

**测试（S18，链式）**：250 天基线 → Day1 降级 → Day2 兜底 →
`S18-01/02` 两次 skip、条数不增、`2026-11-28` 不在序列；`S18-03` 6.62 不在任何值里；
`S18-04` 两日都不挂 `history`（打分侧自然 `score=None`）。

### P1-1 boundary 方向反了 —— ✅ 已修（字段化）

**改动**：`calc_ias` 输出 `next_threshold` / `next_signal` / `next_direction`（up/down）+
`boundary_distance`（绝对值）；保留 `boundary_*` 兼容。
前端 `describeBoundary()`（`src/lib/caliber.ts`）只读字段，`App.tsx` 不再写死「下档」。

**测试（S19 + node）**
- norm −0.041286 → `down / 减仓 / −0.109 / 0.067714`
- norm +0.300 → `down / 持有 / 0.217 / 0.083`
- norm −0.200 → **`up / 持有 / −0.109 / 0.091`**（泰斯特反例：上档，不是下档）
- norm −0.400 → **`up / 减仓 / −0.326 / 0.074`**
- 旧产物无新字段时按 margin 符号回退；真实产物 `next_direction` 与 normalized/阈值自洽。

### P1-2 saturated 文案写死「上界」—— ✅ 已修

**改动**：指标新增 `saturated_side ∈ {upper, lower, null}`（+1.0=upper，−1.0=lower，按**分数区间**判）。
前端徽标按侧显示「已到区间上界/下界·不携带信息」，tooltip 同步。
真实产物：`ppi/carbonPrice/evPenetration = upper`，**`shanghaiCopper = lower`**。

**测试**：S20 三条 + node 四条（含真实产物逐项核对）。

### P1-3 chinaBond10Y 固定水位 → 相对口径 —— ✅ 已改 + 回填

- `scoring_method: ratio_ma_steps`，`ratio = 中债10Y / MA120`，五档对称：
  `≤0.90 → +1.0；≤0.97 → +0.5；≤1.03 → 0；≤1.10 → −0.5；>1.10 → −1.0`。
- 固定水位 `1.5/2.5/4.0` 从 `NEGATIVE_PARAMS` **删除**（不留第二套断点）。
- 回填 **250 个交易日**（`data/history/series/chinaBond10Y.json`，2025-11-26 → 2026-11-27），
  源 = `akshare.bond_zh_us_rate()` 中国10Y 列，**与线上同源同一次请求，未新引源**。
- caliberNote：**相对均值口径，反映边际宽松，不反映绝对水位**。
- 今日：1.5972 vs MA120 1.68434（−5.17%）→ ratio **0.9483** → **+0.5**（原 +0.9）。

**测试**：S21（配置/文案/9 点边界探针/历史<120→null/整链复算）。

### P1-4 required_valid=2 收窄 —— ✅ 已收窄

- 新增 `required_valid_exceptions: ['usdcnh']`（`DIMENSIONS`）并**随 `DIMENSION_CONFIG` 下传**
  （原漏拷，等于例外不生效——首次跑测试就抓住了）。
- `required_valid_count(dim, valid_keys)`：仅当**缺失项全部在例外表内**时按 2；否则回 T4。
- 结果：`fxExternal` 3 项全有效 → required **3**；缺 usdcnh → 2（出分）；缺 dollarIndex/usBond10Y → 3（整维 insufficient）。

**测试**：S22 八条（含三条整链 raw_data 用例）。

### P1-5 回算时钟错 —— ✅ 已修 + 19 天重跑

- `build_indicators_and_meta(..., today=None)` 透传到 `resolve_freshness`；`replay_8dim_30d.py`
  的 `compare()` 与 `rebuild_live()` 都传**快照日**。
- 修复前：11-06 收盘 vs 11-28 墙钟 = 22 天 → α=0，11-09~11-18 九天被误判「数据不足」。

**重跑结论（19 个快照，按快照日）**

| 日期 | normalized | 信号 | 覆盖 |
|---|---|---|---|
| 11-09 | −0.0033 | 持有 | 1.0 |
| 11-10 | +0.0198 | 持有 | 1.0 |
| 11-11 | +0.0643 | 持有 | 0.911 |
| 11-12 | +0.0995 | 持有 | 0.911 |
| 11-13 | +0.1384 | 持有 | 0.911 |
| 11-14 | +0.1111 | 持有 | 0.911 |
| 11-16 | +0.1037 | 持有 | 0.911 |
| 11-17 | +0.0237 | 持有 | 0.911 |
| 11-18 | −0.0095 | 持有 | 1.0 |
| 11-19 | −0.0430 | 持有 | 1.0 |
| 11-20 | −0.0469 | 持有 | 1.0 |
| 11-21 | −0.0630 | 持有 | 1.0 |
| 11-22 | −0.0625 | 持有 | 1.0 |
| 11-23 | −0.0619 | 持有 | 1.0 |
| 11-24 | −0.0716 | 持有 | 1.0 |
| 11-25 | −0.0507 | 持有 | 1.0 |
| 11-26 | −0.0836 | **持有** | 1.0 |
| 11-27 | **−0.1158** | **减仓** | 1.0 |
| 11-28 | −0.0556 | 持有 | 1.0 |

- 覆盖率 **0.911–1.0**（仅 11-11~11-17 因 resource 整维缺失 0.911），**无任何「数据不足」**。
- 旧 6 维 vs 新 8 维：**翻转 1 天 = 11-26（减仓 → 持有，结构/权重）**。
- ⚠️ **与泰斯特基线（19 天全持有 / 2 天翻转 11-26+11-27）的差额来源已定位**：
  他跑的是 P1-3 **之前**的中债口径。旧口径 11-27 ≈ −0.1015（持有，margin 0.0075）；
  P1-3 后中债 +0.9 → +0.5，liquidity −0.1，Δnorm −0.0143 → 11-27 = **−0.1158（减仓，margin 0.0068）**。
  即：11-27 是**刀锋日**（margin < 0.02），P1-3 把它从刀锋内侧推到外侧；旧→新因此只剩 1 天翻转。
  这是口径变更的真实后果，未做任何粉饰；是否接受由 PM/龙六定（见 §5.1）。
- 序列无未来函数：6 条 series（含 `chinaBond10Y`）全部 `date < 快照日`，`passed=true`。
- 回算幂等：`--rebuild-live` 重跑两次，IAS/维度/指标打分逐位一致（仅 `timestamp`/`lastFetched` 变）。

---

## 3. 页面实拍（本地 preview，1440×3200）

截图：`docs/shots/a5-final-full.png`（Chrome headless 加载 `vite preview`）。

DOM 断言（原始取文）：

```
IAS 综合投资评分 -0.31 ➖ 持有 · 建议仓位: 40-60%
数据覆盖 100% / 有效权重 5.6/5.6（覆盖 100%）/ 归一化 -0.0556
距翻档 0.053 · 下档减仓 / 置信度 高 / 含 4 项饱和
本期IAS综合评分 -0.31（➖持有，建议仓位40-60%）…        ← 正文与头部一致
已到区间上界·不携带信息 ×3（ppi / 碳价 / 渗透率）
已到区间下界·不携带信息 ×1（沪铜 92550）
中国10年国债收益率 1.60% → +0.50  · 2026-11-27
维度卡 8 张；旧「市场情绪」卡片不存在
```

---

## 4. 产物与提交边界

| 文件 | 说明 |
|---|---|
| `scripts/commentary_generator.py` / `generate_commentary_llm.py` | ias.normalized + dist 同步 |
| `public/data/commentary.json` | 重生成（−0.31 / −0.055571），dist 同步 |
| `scripts/fetch_worldos_data.py` | `sync_series` 兜底也跳过 + `chinaBond10Y` 序列元信息 |
| `scripts/backfill_series.py` | 新增 `build_china_bond_10y()`（同源 akshare，250 日） |
| `data/history/series/chinaBond10Y.json` | 新增回填序列（250 点） |
| `scripts/indicator_meta.py` | 中债改 ratio_ma_steps、`required_valid_exceptions`、`required_valid_count(dim, valid_keys)` |
| `scripts/scoring.py` | 删中债固定水位、`saturated_side`、`next_*` 方向字段、`today` 透传 |
| `scripts/replay_8dim_30d.py` | 回算/重建传快照日；chinaBond 走 series as-of |
| `src/lib/caliber.ts` / `src/App.tsx` | `describeBoundary` / `saturatedBadgeText`，去掉写死「下档」「上界」 |
| `scripts/test_schema_fields.py` | 新增 S17~S23；S5-04/S9-06/S15-05 同步新口径 |
| `tests/caliber-edge.test.mjs` | 新增 [P1] 方向 + 饱和侧断言（320 项） |
| `tests/fixtures/market-data-edge-cases.json` | 重新生成（含中债 125 点历史） |
| `data/history/recompute-8dim-2026-11-28.json` | 按快照日重跑 |

- 本地 commit，**不 push、不部署、不改 cron**。
- `deploy/migrations/**`、core 未动；未 re-baseline（re-baseline 是 PM 特权）。

---

## 5. 我不确定的 3 件事

1. **11-27 的「减仓」是 P1-3 直接造成的刀锋位移（最大分歧点，请龙六/PM 拍）**。
   泰斯特基线 19 天全持有；P1-3 把该日从 −0.1015 推到 −0.1158（越过 −0.109），
   margin 只有 **0.0068**。三种都可辩护：① 接受新口径下的减仓（相对均值确实在走松→不对，
   中债收益率低于均值是利好，但被 liquidity 其它三项拖累）；② 认为中债 +0.5 给低了
   （−5.17% 离均值，按五档落在 0.90–0.97 区间，我按 ≤0.97 归 +0.5）；
   ③ 调 IAS 阈值。**我不改阈值，也不为了让某天好看而调分**，但这是唯一一处与泰斯特结论不一致的地方。

2. **`required_valid_exceptions` 是新的配置口子**（A4 的 `required_valid` 收窄为白名单）。
   我按工单要求实现「仅 usdcnh 缺失时按 2 计」；但若将来 fxExternal 再加/删指标，
   这个白名单会静默失配（缺失项不在白名单 → 一律要求全有效，可能整维归零）。
   是否需要一条元数据校验（白名单必须是 `indicators` 子集且非空）由龙六定。

3. **回填 250 点是「够用」而非「完整」**：MA120 + 19 日回算窗口刚好够，但若将来要做
   120 日以上的回测（例如 ratio 的 rolling 稳定性检验），序列会不够。另：`chinaBond10Y`
   的 ratio 用「含当日」MA，与 usdcnh 一致；若泰斯特认为应「不含当日」，11-27 的 ratio 会从
   0.9483 微动，档位仍是 +0.5（不致翻档），但我不确定这是不是他要的口径。

---

## 6. 验收勾选

- [x] P0-1 commentary 重生成（public + dist）+ S17 防复发断言
- [x] P0-2 `used_fallback` 也跳过序列 + S18 链式场景
- [x] P1-1 `next_threshold/next_signal/next_direction` + 前端按字段 + S19/node
- [x] P1-2 `saturated_side` upper/lower + 徽标分侧 + S20/node
- [x] P1-3 中债相对 MA120 五档 + 250 日回填 + caliberNote + S21
- [x] P1-4 required_valid 收窄到 usdcnh + S22
- [x] P1-5 回算时钟 = 快照日 + 19 天重跑 + S23
- [x] 四套测试全绿（220 / 3 / 320 / build 76ms）
- [x] 本地 build + preview 自验（8 维、饱和上/下界、翻档方向、IAS 解读与头部一致）
- [x] 本地 commit，不 push / 不部署 / 不改 cron
