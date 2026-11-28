# P1-8DIM 独立验收报告（泰斯特）

- 验收时间：2026-11-28 17:45–17:55 GMT+8
- 验收对象：本地 `main` HEAD `5b213ce`（含 `82a5902` 骨架 / `8488fe1` usdcnh 重标 / `5b213ce` 降级不计分）
- 验收环境：macOS arm64 / Python 3.9.6 / Node v22.19.0 / Chrome headless（1440×2600）
- 立场：**不采信扣钉自测结论**。本文所有数字均为本次亲手跑出的原始输出；扣钉 `docs/P1-8DIM-REPORT.md` 只作为被检对象。
- 硬约束遵守：未改业务代码、未 push、未部署、未动 cron。只新增本报告与 `docs/shots/*.png`。

## 结论

**CONDITIONAL PASS（有条件通过）**

- 批次 A 的 8 维结构、权重派生、阈值 normalized 化、usdcnh 五档与降级不计分、页面 8 卡片、四套 E2E，**全部亲手复现通过**。
- 但发现 **1 个 P0**：usdcnh 降级（在岸回退）时，**降级值仍被写进 `data/history/series/usdcnh.json`**，会污染未来 120 个交易日的 MA120 锚点——与 D7「宁缺勿错」的设计原则直接冲突。这是本次新引入路径（A2 + D7）的缺口，扣钉未提。
- 另有 **2 个 P1**：回算产物 18/19 天 `sentimentA=null`（8 维回算实际是 7 维，5/19 天信号与正确 as-of 口径不同）；扣钉报告 §2.7 的表格与最终产物不一致（报告写 6 次翻转/11-28 减仓，产物是 3 次翻转/11-28 持有）。

---

## 1. 结构与权重

### 1.1 维度数 / 权重和 / IAS_SCALE

```
$ python3 -c "... import indicator_meta as M ..."
len(DIMENSIONS)= 8
weight sum= 5.6000000000000005
IAS_SCALE= 5.6
len(INDICATORS)= 36
THRESHOLD_SPACE= normalized
validate_metadata problems= []
```

- `IAS_SCALE = round(sum(d['weight'] for d in DIMENSIONS), 2)`（`scripts/indicator_meta.py`），**派生值，不是硬编码**。
- 全仓搜 `5.6` 只剩 3 类：`IAS_SCALE` 定义注释、测试里对 `im.IAS_SCALE == 5.6` 的断言、前端兜底默认对象 `src/App.tsx:310`（见 P2-5）。评分逻辑中无裸 5.6。

### 1.2 36 个指标逐个点名（无重复 / 无跨维）

```
total 36 assigned 35 orphans ['epu']
dups: []
dims referencing undefined: []
```

| # | key | 维度 | 身份 |
|---|---|---|---|
| 1–6 | chinaGdp, chinaPmi, usGdp, servicePmi, electricity, usNonFarm | economic | 计分 |
| 7–11 | cpi, ppi, usCpi, corePce, fedRate | inflation | 计分 |
| 12–14 | lpr, dr007, m2 | liquidity | 计分 |
| 15–18 | usdcnh, dollarIndex, creditSpread, usBond10Y | fxExternal | 计分 |
| 19–22 | ashareTurnover, marginBalance, southboundNet, hstechMomentum | sentimentA | 计分 |
| 23–24 | vix, fearGreed | riskAppetite | 计分 |
| 25–26 | usBond2Y, usBond5Y | riskAppetite | 参考 |
| 27–29 | oilPrice, naturalGas, shanghaiCopper | resource | 计分 |
| 30 | lmeIndex | resource | 参考 |
| 31–33 | evPenetration, renewEnergyInvest, carbonPrice | techGreen | 计分 |
| 34–35 | aiGrowth, robotInstall | techGreen | 参考 |
| 36 | **epu** | **无（孤儿）** | reference_only |

- 30 个计分项 + 5 个维度内参考项 = 35 个有归属；**`epu` 不属于任何维度**（`dimension_of('epu') == 'other'`），页面也不显示它。它是历史遗留、已显式标 `reference_only` 且注释说明，但严格按「无孤儿 key」的验收口径，这是 1 个未销项（P2-4）。
- 任务描述「35 指标 + usdcnh = 36」与实际略有出入：实际是 **36 个 key = 35 有归属 + epu**，usdcnh 是新增的第 30 个计分项。
- `REFERENCE_ONLY` 实际是 **6 个**（`aiGrowth, epu, lmeIndex, robotInstall, usBond2Y, usBond5Y`），比任务列的 5 个多 `epu`。

### 1.3 reference_only 不进分母、不参与平均（数值证明）

```
riskAppetite all [('vix',-0.254),('fearGreed',-0.755),('usBond2Y',-0.127),('usBond5Y',0.0)]
             avg(active only)= -0.5045   reported= -0.505
resource     all [('oilPrice',0.0),('naturalGas',0.0),('shanghaiCopper',-1.0),('lmeIndex',-0.087)]
             avg(active only)= -0.3333   reported= -0.333
techGreen    all [('evPenetration',1.0),('renewEnergyInvest',-0.208),('carbonPrice',1.0),('aiGrowth',-0.59),('robotInstall',-0.347)]
             avg(active only)=  0.5973   reported=  0.597
```

```text
经济增长     1.00 → 1.00  (6/6)  满额
通胀与政策   1.00 → 1.00  (5/5)  满额
流动性（国内）0.80 → 0.80  (3/3)  满额
汇率与外部   0.70 → 0.70  (4/4)  满额
A股/港股情绪 0.90 → 0.90  (4/4)  满额
全球风险偏好 0.40 → 0.40  (2/2)  满额
资源与供应链 0.50 → 0.50  (3/3)  满额
科技与绿色   0.30 → 0.30  (3/3)  满额
合计        5.60 → 5.60
```

参考项被排除后平均值与产物逐位一致；`aiGrowth/robotInstall` 已移出 techGreen 的 `indicators`，shrink 从旧的 2/4 恢复为 3/3。

### 1.4 `4.6` / 旧 id `'sentiment'` 全仓 grep

`4.6`（排除数据文件与 node_modules）：

- `scripts/scoring.py:630,636` —— 注释（解释旧 bug），非逻辑。
- `scripts/indicator_meta.py:457-459,474` —— 注释（阈值换算推导），非逻辑。
- `scripts/test_schema_fields.py:1425-1448` —— **测试内的旧口径基线**（`norm * 4.6` 用来复刻旧信号做对照），非生产逻辑。
- `scripts/replay_8dim_30d.py:63,142` —— 回算脚本刻意冻结的旧 6 维基线，合法。
- 结论：**生产评分/展示逻辑无 4.6 残留**。

旧 id `'sentiment'`（非注释的真实引用）：

| 位置 | 性质 | 风险 |
|---|---|---|
| `scripts/replay_sentiment_30d.py:38,86,94,101,131` | 真代码：`next(d for d in im.DIMENSIONS if d['id']=='sentiment')` | **脚本已不可运行**（`sentiment` 已删，第二次 next 直接 `StopIteration`）→ P2-2 |
| `src/components/Dashboard.tsx:263,280` | 真代码：渲染「市场情绪」卡片、`getDimensionStatus(data,'sentiment')` | 组件**未挂载**（App.tsx 无 import），死代码 → P2-3 |
| `src/data/marketData.ts:229` | 真代码：v6 旧模型分组 `case 'sentiment'` | 文件头已标 `@deprecated`、App 不读 → P2-3 |
| `tests/caliber-edge.test.mjs:764-768` | 断言「旧 id 只回中性占位」 | 合法测试 |

页面本体：`市场情绪` 出现次数 **0**（见 §4）。

---

## 2. 阈值量纲（11-27 bug）

### 2.1 常量确实是 normalized 语义

```python
IAS_THRESHOLD_SPACE = 'normalized'
IAS_THRESHOLDS = [(0.543,'强烈买入'),(0.217,'增持'),(-0.109,'持有'),(-0.326,'减仓')]
```

产物 `meta.rules_snapshot` 同时写入 `ias_scale=5.6` 与 `ias_threshold_space='normalized'`，第三方可判断阈值量纲。

### 2.2 12 个探针（四个边界上下各一）

直接构造 8 个维度同分（权重全有效），使 `normalized == 探针值`，调 `scoring.calc_ias`：

```
probe     normalized  score   signal / position / icon
>0.543        0.5431    3.04  强烈买入 / 80-100% / 🚀
=0.543         0.543    3.04  强烈买入 / 80-100% / 🚀
<0.543        0.5429    3.04  增持 / 60-80% / ✅
>0.217        0.2171    1.22  增持 / 60-80% / ✅
=0.217         0.217    1.22  增持 / 60-80% / ✅
<0.217        0.2169    1.21  持有 / 40-60% / ➖
>-0.109      -0.1089   -0.61  持有 / 40-60% / ➖
=-0.109       -0.109   -0.61  持有 / 40-60% / ➖
<-0.109      -0.1091   -0.61  减仓 / 20-40% / ⚠️
>-0.326      -0.3259   -1.83  减仓 / 20-40% / ⚠️
=-0.326       -0.326   -1.83  减仓 / 20-40% / ⚠️
<-0.326      -0.3261   -1.83  清仓/防御 / 0-20% / 🛑
```

边界规则统一为 `normalized >= threshold` 归本档，跨档位置与 0.543/0.217/−0.109/−0.326 完全对齐。

### 2.3 比较用的是同一个量纲（核心 bug 已修）

代码：`scripts/scoring.py:704` `if normalized >= threshold:`（不是 `ias_score`）。

活数据反证（今天的真实产物）：

| 口径 | 数值 | 信号 |
|---|---|---|
| `ias.normalized`（现行比较对象） | −0.102 | **持有**（距 −0.109 只差 0.007） |
| `ias.score`（展示量纲） | −0.57 | 若按旧代码拿它比 −0.5 → **减仓**（错误档位） |

再把 `IAS_SCALE` 临时改成 4.6 重跑同一组维度分：

```
scale 5.6 norm -0.102 score -0.57 signal 持有
scale 4.6 norm -0.102 score -0.47 signal 持有   # normalized 与信号不变
```

→ 信号不再随标尺漂移，旧 bug 的两条症状（拿 score 比 −0.5、改 IAS_SCALE 改语义）均已在代码与行为上消除。

---

## 3. usdcnh（本批最大风险点）

### 3.1 MA120 自算 vs 产物

序列 `data/history/series/usdcnh.json` 共 250 条（2025-12-15 → 2026-11-27）。末 120 个收盘自算：

```
mean last120 = 6.723853333333334
JSON ma_base  = 6.723853
diff          = 3.3e-7  (< 0.0005 ✅)
ratio         = 6.6551 / 6.723853333 = 0.989775  → JSON 0.989775 ✅
score         = +0.5（ratio≤0.995 档）✅
```

回算侧同法核对（严格用快照日之前最近收盘 + 前 119 条）：

| 快照日 | dataDate | MA120 自算 | 产物 ma_base | ratio 自算 | 产物 ratio |
|---|---|---|---|---|---|
| 2026-11-09 | 2026-11-06 | 6.737042 | 6.737042 | 0.990613 | 0.990613 |
| 2026-11-20 | 2026-11-19 | 6.729461 | 6.729461 | 0.994493 | 0.994493 |
| 2026-11-28 | 2026-11-27 | 6.723853 | 6.723853 | 0.989775 | 0.989775 |

### 3.2 五档边界探针

配置 `steps=(0.985,0.995,1.005,1.015)`，`values=(+1,+0.5,0,−0.5,−1)`，规则「≤ 上界归本档」：

```
ratio=0.98   -> +1.0
ratio=0.985  -> +1.0
ratio=0.9851 -> +0.5
ratio=0.99   -> +0.5
ratio=0.995  -> +0.5
ratio=0.9951 ->  0.0
ratio=1.0    ->  0.0
ratio=1.005  ->  0.0
ratio=1.0051 -> -0.5
ratio=1.01   -> -0.5
ratio=1.015  -> -0.5
ratio=1.0151 -> -1.0
ratio=1.02   -> -1.0
```

任务要求的 0.98/0.99/1.00/1.01/1.02 → **+1.0/+0.5/0/−0.5/−1.0**，逐档命中。历史不足 120 点：`warmup=true, score=null`（用 119 条 history 造满窗验证 ratio=1.01 → −0.5，证明窗口拼接正确）。

### 3.3 未来函数

代码证据 `scripts/replay_8dim_30d.py:_cnh_asof`：

```python
ds = sorted(d for d in series if d < ref_date)   # 严格早于快照日
last = ds[-1]
hist = [{'date': d, 'value': series[d]} for d in ds[:-1]]   # 再往前，全部 < last
```

- 回算产物 19 行逐行断言：`max_used_date < 快照日`，**0 违例**（`usdcnh_no_lookahead.passed=true`）。
- 实盘路径 `series_store.history_before(key, dd)`（`series_store.py`）同样 `d < date`，当日值只作为「今日收盘」参与 MA（含当日），不是未来数据。
- 11-28 实盘：dataDate=11-27，MA 用到的最新日期 = 11-27 **< 11-28 快照日**。

### 3.4 降级态（D7）

monkeypatch `exchangerate-api` 命中（akshare 强制失败）后构造 raw_data 过 `build_indicators_and_meta`：

```
get_usdcnh -> 6.65 2026-11-28 daily degraded= True | suffix= （本条为在岸参考价，非离岸价）
usdcnh value 6.6500 score None excluded True reason degraded_no_score
score_blocked_by_degraded True ratio None ma None
caliber: ...（本条为在岸参考价，非离岸价）；降级·在岸参考价，不计分
fxExternal: {'score': -0.132, 'valid_count': 3, 'required_count': 2, 'insufficient_data': False, 'signal': 'yellow'}
IAS: -0.12175 减仓 coverage 1.0 grayed []
```

- `score=null` ✅；`ratio/ma_base/deviation_pct` 三个半套数全 null ✅；专属理由码 `degraded_no_score` ✅。
- `fxExternal` 仍 3/4 有效出分 ✅；IAS 8 维全在（`grayed=[]`，覆盖率 1.0，因为维度未置灰）✅。
- 值 6.65 仍展示 ✅。

### 3.5 ⚠️ P0：降级值被写进历史序列（扣钉未提）

`scripts/fetch_worldos_data.py:1804-1823` 的回写循环**只判 `value`/`dataDate` 非空**，不判 `sourceDegraded`：

```python
for key, cfg in PCT_SERIES_KEYS.items():
    v = results.get(key, {}); val = v.get('value'); dd = v.get('dataDate')
    if val is None or not dd: continue
    series_store.upsert(key, dd, val, ...)      # ← 降级在岸价照样入库
    hist = series_store.history_before(key, dd, ...)
```

亲手复现（把 `series_store.SERIES_DIR` 指到临时目录，跑真实 `get_usdcnh()` + 逐字复制该循环）：

```
[源1 akshare日线失败: ImportError] [源=exchangerate-api 在岸CNY 6.65（降级：非离岸价）]
get_usdcnh -> 6.65 2026-11-28 daily degraded= True | suffix= （本条为在岸参考价，非离岸价）
series now: {'2026-11-28': 6.65}
history_before: []
=> degraded onshore value persisted: [6.65]
```

后果：只要某天主源失败，在岸价就成了该交易日在 `usdcnh.json` 里的“收盘价”，并进入此后最多 120 个交易日的 MA120。在岸/离岸价差 0.1–0.3%，而档位总宽只有 ±1.5%、相邻档只差 1.0% —— 相当于用 10–30% 的档宽去污染锚点。`upsert` 只写当日，日常抓取不会回补旧日期；仓库无 CI 工作流、crontab 为空，本机现有 launchd 小时任务只跑另一个项目（`workspace-market-insight`）不跑 worldos；只有人工重跑 `python3 scripts/backfill_series.py --key usdcnh`（它会覆盖同日期 250 天）才会被修正。这与 D7「拿代理冒充真值 = 假结论、宁缺勿错」的原则正相反：**算分拦住了，喂序列没拦住**。

建议修法（不代改）：回写前 `if v.get('sourceDegraded'): continue`（或用 `NO_SCORE_WHEN_SOURCE_DEGRADED` 同一集合），并补一条 S13-09：降级态不得调用 `series_store.upsert`。

---

## 4. 端到端

### 4.1 四套命令原始尾行

```
$ python3 scripts/test_schema_fields.py
✅ S0[readonly]
166 passed / 0 warn / 0 failed / 166 total

$ python3 scripts/test_no_nan_json.py
✅ fetch_worldos_data: _sanitize + write_json_strict 通过
✅ generate_commentary_llm: _sanitize + write_json_strict 通过
✅ commentary_generator: _sanitize + write_json_strict 通过
全部通过：3 个模块均不会产出非法 JSON

$ node --test tests/caliber-edge.test.mjs
# ✅ 全部通过：295 项断言
ok 1 - tests/caliber-edge.test.mjs
# tests 1 / pass 1 / fail 0

$ npm run build
vite v8.0.3 building client for production...
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-CCp4s8fw.css   42.42 kB │ gzip:  7.29 kB
dist/assets/index-CgdfR2KC.js   230.28 kB │ gzip: 72.07 kB
✓ built in 104ms
```

补充：`python3 scripts/indicator_meta.py` → `✅ 元数据校验通过：36 个指标 / 8 个维度`；`dist/data/market-data.json` 与 `public/data/market-data.json` 逐字节一致。

> 构建副作用：`npm run build` 重新生成了 `dist/`（`dist/index.html` 的 bundle hash 由 `index-CdHL19Wv.js` 变为 `index-CgdfR2KC.js`），这是执行验收命令的必然产物，未改任何源码。

### 4.2 真起 preview + 真浏览器

`browser` 工具的导航被本机策略拦（`browser navigation blocked by policy`，非页面问题），改用同一台机器上的 Chrome headless 实际加载 `http://localhost:4178/`（`vite preview`，服务 dist），DOM dump + 截图双证据。

DOM 计数：

```
w= count 8
⏱ badges 8
口径： 8
市场情绪 0
```

- **8 张维度卡片**（不是 6）：经济增长 / 通胀与政策 / 流动性（国内）/ 汇率与外部 / A股/港股情绪 / 全球风险偏好 / 资源与供应链 / 科技与绿色。
- **新增维度可见**：「汇率与外部」+0.03、「A股/港股情绪」−0.30 均渲染，数值与 JSON 一致。
- **旧「市场情绪」卡片已消失**：DOM 0 次；顶部分档条 8 个 chip 也与 8 维一一对应。
- **三字段仍在**：每张卡头部 `w=<权重>`、`⏱<响应速度>`（tooltip 有逐指标明细）、副标题 `口径：<caliberNote>`，各 8 份。

截图（`docs/shots/`）：

| 文件 | 内容 |
|---|---|
| `8dim-overview.png` | 1440×2600 全页 |
| `8dim-cards-all.png` | 8 张卡片网格 |
| `8dim-cards-row2.png` | 第二行三卡 |
| `8dim-card-fx.png` | 「汇率与外部」卡（w=0.7 / ⏱T+0 / 口径 / usdcnh 6.66→+0.50） |
| `8dim-card-sentimentA.png` | 「A股/港股情绪」卡（w=0.9 / ⏱T+1 / 4 项计分） |
| `8dim-dim-strip.png` | 顶部 8 维分档条（含 8 个名字） |
| `8dim-ias-header.png` | IAS 头部（−0.57 / 持有 / 归一化 −0.1020 / 有效权重 5.6） |

### 4.3 JSON ↔ 页面抽查（11 个，超过要求的 5 个）

| 指标 | JSON | 页面 | 位置 |
|---|---|---|---|
| usdcnh | 6.6551 / +0.5 | 6.66 / +0.50 | 汇率与外部 |
| usBond10Y | 4.94 / 0.0 | 4.94% / 0.00 | 汇率与外部 |
| dollarIndex | 97.8 / +0.275 | 97.80 / +0.28 | 汇率与外部 |
| creditSpread | 334 / −0.67 | 334bp | 汇率与外部 |
| ashareTurnover | 19997.94 / +0.234 | 19998亿元 / +0.23 | A股/港股情绪 |
| marginBalance | 21055.79 / −0.76 | 21056亿元 / −0.76 | A股/港股情绪 |
| southboundNet | 79.81 / −0.78 | 79.81亿元 | 顶栏+卡片 |
| hstechMomentum | −3.3 / +0.1 | −3.30百分点 / +0.10 | A股/港股情绪 |
| shanghaiCopper | 92550 / −1.0 | 92550 ¥/吨 | 资源 |
| vix | 23.81 / −0.254 | 23.81 / −0.25 | 全球风险偏好 |
| fearGreed | 24.9 / −0.755 | 24.90 / −0.76 | 全球风险偏好 |

维度分同样一致：−0.25 / +0.11 / +0.01 / +0.03 / −0.30 / −0.51 / −0.33 / +0.60，与 `meta.dimensions[*].score` 逐位相同。

---

## 5. 回算产物

### 5.1 完整性

```
rows 19   flip_count 3
history files 19   match True
rows missing old/new: []
lookahead violations: []
usdcnh_no_lookahead: {'violations': [], 'passed': True, ...}
```

19 天（11-09 → 11-28，缺 11-15）逐日有 `old`（冻结 6 维）/ `new`（现行 8 维）/ `attribution` / `usdcnh`。
`rules_hash` 独立复算：`sha256(canonical(rules_snapshot))[:12] = ae148d2b8a6d`，与产物一致。

### 5.2 抽 3 天手工复算

用原始快照 + as-of usdcnh 重新跑 `build_indicators_and_meta`，并从维度分手工算 normalized：

| 日期 | 流水线 normalized/score | 产物 normalized/score | 手算 normalized | 差 |
|---|---|---|---|---|
| 2026-11-09 | −0.0685 / −0.38 | −0.0685 / −0.38 | −0.0685 | 0.000000 |
| 2026-11-20 | −0.126023 / −0.71 | −0.126023 / −0.71 | −0.126023 | 0.000000 |
| 2026-11-28 | −0.102 / −0.57 | −0.102 / −0.57 | −0.102 | 0.000000 |

均远优于 ±0.005 容差。

### 5.3 ⚠️ P1：回算里 `sentimentA` 18/19 天为 null（8 维实际只算了 7 维）

用 `series_store` 的 400 日真实历史按「`date < 快照日`」补齐 4 个 A股/港股代理 + usdcnh，重跑 19 天：

```
2026-11-19 prod -0.112    减仓（部分维度缺失·参考）  asof -0.137642 减仓          cov 0.786->0.946 DIFF
2026-11-20 prod -0.126023 减仓（部分维度缺失·参考）  asof -0.147075 减仓          cov 0.786->0.946 DIFF
2026-11-21 prod -0.069404 持有                    asof -0.109357 减仓          cov 0.839->1.0   DIFF
2026-11-24 prod -0.086447 持有                    asof -0.122054 减仓          cov 0.839->1.0   DIFF
2026-11-26 prod -0.087723 持有                    asof -0.128911 减仓          cov 0.839->1.0   DIFF
signal diffs: 5 / 19
```

产物中 `new.dims.sentimentA` 在 11-09…11-27 **全部为 null**，仅 11-28 有值（−0.302）。原因是回算只 as-of 注入了 usdcnh，没注入另外 4 个有 400 日 series 的指标 → pct_rank 走 warmup → 维度置灰。效果：

- 18/19 天的“新 8 维”实际是 7 维，缺的正是本次改造的主角 `sentimentA`（权重 0.9，占 5.6 的 16%）；
- 据此得出的“翻转 3 天”与真实 8 维口径不同：按 as-of 补齐后 11-21/11-24/11-26 会从「持有」翻到「减仓」，共 5/19 天信号不同；
- 产物里的 `attribution.structure_flip=true` 把这些天归因为「结构/权重」，但真实原因是「历史序列没注入」的数据口径，归因标签会误导。

这不是造假（历史快照确实没有那 4 项的值），但作为「检测 6→8 维断档」的交付物，它没法回答最关键的问题——`sentimentA` 上线后会把结论推向哪边。建议与 usdcnh 同法 as-of 注入，或在产物里显式标 `sentimentA: warmup` 并声明「本回算仅 7 维可比」。

### 5.4 ⚠️ P1：扣钉报告 §2.7 的表格与最终产物对不上

`docs/P1-8DIM-REPORT.md` §2.7 写：

- 「共 19 个快照，信号档位翻转 **6 天**」，含 11-24/11-26/**11-28（持有→减仓，norm −0.12175）**；
- 文末又说「11-28 回算 = 减仓、live = 持有，差别只在 usdcnh」。

但仓库里的最终产物 `recompute-8dim-2026-11-28.json`：

- `flip_count = 3`（11-18/19/20）；
- 11-28：`new.normalized=-0.102`、`signal=持有`（已含 usdcnh +0.5）。

即报告表格是 A2 之前（未注入 usdcnh）的旧输出，没有随产物更新。按报告做的判断（“11-28 回算减仓”）与交付物相反，属交付文档失真。

---

## 6. 必须修的问题清单

### P0（修完才能算过）

1. **降级在岸价被写入 usdcnh 历史序列**（`scripts/fetch_worldos_data.py:1804-1823`）
   证据见 §3.5。修法：回写前跳过 `sourceDegraded`；补测试断言降级态不调用 `series_store.upsert`。
   影响：主源一旦失败，MA120 被污染最多 120 个交易日，且日常抓取不会自动回补（仅人工 backfill 可修）。

### P1（本批交付物正确性，强烈建议本批内修）

2. **回算产物 18/19 天 `sentimentA=null`**（`scripts/replay_8dim_30d.py`）
   证据见 §5.3。按 as-of 补齐后 5/19 天信号不同；建议注入 4 个 series（与 usdcnh 同法），或显式声明“仅 7 维可比”并修正翻转归因。
3. **扣钉报告 §2.7 表格与产物不一致**（`docs/P1-8DIM-REPORT.md`）
   报告写 6 次翻转 / 11-28 减仓；产物是 3 次 / 11-28 持有。需按最终产物重生成，否则 PM 会基于错的数字拍板。

### P2（清理项，不阻塞）

4. **`epu` 是孤儿 key**：36 个指标里唯一不属于任何维度、页面也不展示（`dimension_of='other'`）。已声明 `reference_only` 并有注释，但严格「无孤儿」口径下未销项；要么归入某维（参考项），要么从抓取清单移除。
5. **卡片未显式写「有效权重」**：DOM 中权重是 `w=0.7`，tooltip 在无收缩时写「设计权重」。当前 8 维全部满额（effective==design），数值没错，但用户看不到「有效」二字；建议 tooltip 统一为「有效权重 x（设计 y）」。
6. **`scripts/replay_sentiment_30d.py` 已不可运行**：仍在 `next(... if d['id']=='sentiment')`，`sentiment` 已删 → `StopIteration`。建议改 id 或标记废弃。
7. **死代码里的旧「市场情绪」**：`src/components/Dashboard.tsx:263,280`（未挂载）+ `src/data/marketData.ts:229`（v6 deprecated）。页面无影响，但 grep 会持续命中旧 id。
8. **`src/App.tsx:310` 兜底对象硬编码 `max_possible: 5.6`**：仅在数据缺失时兜底展示，不参与评分；但与「IAS_SCALE 必须派生」的原则不一致，建议改为从 `meta` 读或去掉该常量。

---

## 7. 附：我亲手发现、扣钉报告里没有的 3 条

1. **降级值照样写序列**（P0）——扣钉只做到「算分拦住」，没检查 fetch 的回写循环；他报告 §4 甚至写了“在岸回退价会污染 ratio”，但结论停在 score=null，没发现序列已经被写脏。
2. **回算缺 `sentimentA` 18/19 天**（P1）——扣钉报告只说 11-18 因“11-27 才接入”置灰，未披露 11-19 至 11-27 也全是 null；我按 series as-of 补齐后 5/19 天信号改变。
3. **报告 §2.7 与产物数字不一致**（P1）——报告是 A2 前的旧跑批结果（6 flips / 11-28 减仓），产物是 A2 后（3 flips / 11-28 持有），没有同步。

> 备注：`browser` 工具被本机导航策略拦截（`browser navigation blocked by policy`），页面验收改用同机 Chrome headless 加载 `vite preview` 的 dist；DOM dump 与截图均来自真实渲染，不是读 JSON 伪造。

---
---

# 附：A4 增量复核（2026-11-28 17:59–18:15 GMT+8）

- 复核对象：本地 `main` HEAD `3e62115`（A4 收口提交）；交付说明 `docs/P1-8DIM-REPORT.md`（已被扣钉重写为「唯一现行结论」）
- 立场：**继续不采信自测**。上文 A2/D7 轮的结论原样保留、不回改；本节只回答三件事——
  ① 我上轮提的 P0 是否真修掉；② A4 新增披露字段是否真对；③ 结构性改动有无副作用。
- 方法：所有断言都由本人在本机重跑。证据脚本全部留在 `docs/verify-a4/`（9 个，可复跑）：
  `verify_a4_p0.py` / `p0b.py` / `recompute3.py` / `alpha.py` / `asof_today.py` / `flips.py` / `bond.py` / `struct.py` / `boundary.py`。
- 约束遵守：未 push、未部署、未动 cron、未改业务代码/数据。只写本报告 + `docs/shots/a4-verify-full.png` + `docs/verify-a4/*`。
- 页面验收仍走同机 Chrome headless 加载 `vite preview`（`browser` 工具导航仍被本机策略拦，`browser navigation blocked by policy`），DOM dump 与截图均为真实渲染。

## A4-0 结论

**CONDITIONAL PASS（有条件通过）**

| 项 | 结论 |
|---|---|
| 上轮 P0（降级值写进 usdcnh 序列） | **主路径已真修**（S13-09 之外我自己造场景复现通过）；但**残留一条同性质通道**（A4-P0-2） |
| 回算「全 series as-of 注入」 | **注入已做**（5 条 series 逐日注入、无未来函数），但**回算的时效 α 用墙钟今天算** → 19 天里 9 天数值失真、6 次翻转实际只有 2 次（A4-P1-1） |
| 11-28 回算 == live 产物 | **一致**：−0.041286，逐维分数逐位相同 |
| 3 天手工复算 | **0 误差**（远优于 ±0.005） |
| `boundary_margin` 数值 | 今日 **+0.067714 正确**；但 normalized 落在档位下半区时**符号/方向文案错**（A4-P1-2） |
| `fragile_inputs = []` | **正确**（我逐维剔除 8 次，全部仍「持有」）；算法本身经反例验证会报警，不是写死 [] |
| `saturated` 4 项 | **完全正确**，且全库扫描确认无漏标 |
| 结构（中债入流动性/利差转参考/权重 5.6/req=2） | **全部真跑通过**；`required_valid=2` 的功能必要性与副作用见 A4-P1-3 |
| chinaBond10Y 固定水位 | **该打回重标**（结论见 §A4-4.5） |
| Dashboard 删除 / health_check / 无新 cron | 通过 |
| 端到端 | 四套全绿、8 维 8 卡、4 项饱和徽标、旧「市场情绪」0 次；但**页面内「IAS 整体解读」仍写着 −0.57**（A4-P1-4，用户可见，扣钉未提） |

一句话：**代码与站点主体是对的，A4 的核心修复是真的；但交付物里有两处「看起来对、其实是另一套数」，另有 1 条残留 P0 通道。**

---

## A4-1 上轮 P0：降级不污染序列（独立复现，不用他的 S13-09）

### 1.1 主路径：已真修 ✅

自己造场景（`docs/verify-a4/verify_a4_p0.py`）：临时 `SERIES_DIR`，先写 250 个正常离岸收盘（末日 2026-11-27 = 6.6551），再喂一条 11-28 的**在岸回退**（6.62 + `sourceDegraded`），跑生产函数 `fetch_worldos_data.sync_series()`：

```
[BASE] points=250 last=2026-11-27=6.6551 MA120=6.568577
  ⏭️ usdcnh: 源降级（primary_source_missing），跳过序列回写与 history 注入（值只展示，不进 MA/分位）
[SYNC] skipped=['usdcnh']  history_mounted=False
[AFTER] points=250 last=2026-11-27=6.6551 MA120=6.568577
[ASSERT] degraded_day_in_series=False  len_same=True  MA120_same=True
RESULT_P0: PASS
```

- 降级日**没有**进 `usdcnh.json`；条数 250→250；MA120 一位不差；`history` 未挂载（打分侧自然 `score=null`）。
- 其他 series key（`ashareTurnover / marginBalance / southboundNet / hstechMomentum`）的抓取函数没有 `sourceDegraded` 分支（失败即抛异常/走上一轮兜底），所以「同一循环里其它 pct_rank/ratio 指标被跳过」这条**不适用**，但判定是共用的（`PCT_SERIES_KEYS` 全覆盖），结构上没有第二个同类口子。

### 1.2 我上轮把影响说重了，这里更正

上轮我写「在岸/离岸差 0.1–0.3%，相当于 10–30% 的档宽去污染锚点」——**这是错的**：单点进 120 日均值要被 120 稀释。用真实序列量化（`verify_a4_p0.py` 反证段 + 单点/持续对比）：

| 被污染天数 | MA120 | ratio | 档位 | 相对档宽 |
|---|---|---|---|---|
| 0（真实） | 6.723853 | 0.989775 | +0.5 | — |
| 1 天（差 −0.035） | 6.723562 | 0.989818 | +0.5 | +0.4% |
| 20 天 | 6.718020 | 0.990634 | +0.5 | +8.6% |
| 60 天 | 6.706353 | 0.992357 | +0.5 | +25.8% |
| 120 天（整窗） | 6.688853 | 0.994954 | +0.5（已贴 0.995 边） | **+51.8%** |

结论不变但机制要写准：**单日污染几乎无害（0.4% 档宽），危害来自「主源连续多日失败 + 每天照写」的累积**——整窗污染可吃到半个档位宽，0.989775→0.994954 距 0.995 只差 0.000046，再差一点就掉一档。这也解释了为什么它必须先修：不是当天错，是给未来埋锚点。

### 1.3 ⚠️ A4-P0-2 残留通道：降级值会被「上一轮兜底」二次写进序列

修复只判 `sourceDegraded`。但 `load_prev()`（`fetch_worldos_data.py:1587-1602`）只回填 `value/dataDate`，**把 `sourceDegraded` 丢了**；而兜底分支又显式清空它（`fetch_worldos_data.py:1829-1831`）：

```python
# 上一轮兜底优先级高于「备源降级」：两者同时出现时以兜底为准（更旧更弱）
if used_fallback:
    source_degraded = None
```

于是只要**连续两天**出问题就穿透：

- Day1 主源失败 → 在岸 6.62（值进 `market-data.data`，序列**正确地**不写）；
- Day2 主源 + 在岸源都失败 → `val=None` → 取 prev（Day1 的 6.62，dataDate=Day1）→ `used_fallback=True` → `source_degraded=None` → `sync_series` 认为「正常」→ **把在岸 6.62 写进 Day1**。

亲手复现（`docs/verify-a4/p0b.py`，完全按上面真实分支构造）：

```
[BASE] points=250
[DAY1] skipped=['usdcnh'] points=250 (期望 250)
[DAY2] skipped=[] points=251 degraded_day_persisted=True value=6.62
RESULT_P0_RESIDUAL: HOLE
```

- 这不是理论：断网时 akshare 与 exchangerate-api 会一起失败，正是这条路径。
- 危害与 P0 完全同性质（在岸价进 MA120），只是触发需要两天连坏。
- 最小修法（不代改）：`sync_series` 里改成 `if v.get('sourceDegraded') or v.get('used_fallback'): continue`——兜底值本来就已经在序列里（同日同值，跳过无损），唯一例外正是「降级日的兜底」，跳过即正确。补一条 S13-10：`used_fallback` 不得 upsert。
- 扣钉报告完全没提这条；他的 S13-09 只喂了单日 `sourceDegraded`，覆盖不到二次兜底。

---

## A4-2 回算（上轮我说「其实是 7 维回算」）

### 2.1 注入：确实做了 ✅

`SERIES_KEYS = list(im.QUANTILE_CONFIG)` = 5 条（`marginBalance / southboundNet / hstechMomentum / ashareTurnover / usdcnh`），19 行逐行核对：

```
每行 series_injected 都是 5 条；max_used_date 全部 < 快照日
series_no_lookahead: passed=True, violations=0, keys=[5 条]
```

`_series_asof` 严格 `d < ref_date`（不是 ≤），`used_dates` 断言 `max < ds`。代码层面**无未来函数**，这一点扣钉说的是真的。

### 2.2 11-28 回算 == live ✅

`公共产物 meta.ias` 与回算第 19 行：`normalized=-0.041286 / score=-0.23 / 持有`，8 个维度分数逐位相同（economic −0.25 / inflation +0.113 / liquidity +0.233 / fx +0.258 / sentimentA −0.302 / riskAppetite −0.505 / resource −0.333 / techGreen +0.597）。

### 2.3 3 天手工复算：0 误差 ✅

从 `data/history/<日>.json` 原始快照 + 5 条 series as-of 注入 + 中债反算，自己跑 `build_indicators_and_meta`，再用维度分手算 `Σ(score×w)/Σw`（`verify_a4_recompute3.py`）：

| 日期 | 手算 normalized | 产物 | 差 | 信号 |
|---|---|---|---|---|
| 2026-11-19 | −0.079208 | −0.079208 | 0.000000 | 持有/持有 |
| 2026-11-25 | −0.040250 | −0.040250 | 0.000000 | 持有/持有 |
| 2026-11-28 | −0.041286 | −0.041286 | 0.000000 | 持有/持有 |

另外把 19 行逐行的 `Σ(dim×w)/Σw` 与 `new.normalized` 对了一遍，**19/19 全 0 误差**（内部自洽没问题）。

### 2.4 ⚠️ A4-P1-1：回算的「时效 α」用墙钟今天算，9/19 天数值是错的

这是本轮最重的一条，扣钉没提，且他的报告结论被他自己的表误导了。

`resolve_freshness(data_date, freq)` 的 `today` 默认 = `date.today()`（2026-11-28）。回算在重放 11-09 时，把「11-06 的收盘」拿去和**今天**比：`days_stale=22 > daily.red_days(10)` → α=0 → 该指标「过期剔除」。于是：

- 11-09～11-17 的日频指标全员 α=0 → 5 个维度置灰 → 覆盖率 0.5 →「数据不足」；
- 11-18 的 dataDate=11-17 → stale 11 天 → α=0 → 覆盖率 0.589 → 也被判「数据不足」。

**这不是数据缺失，是回算把「今天的时钟」套在 19 天前的快照上。** 证据（`verify_a4_alpha.py`，同一份 11-09 快照、同一套 as-of 注入，只改 α 的 today）：

```
A 墙钟今日 2026-11-28: norm=-0.130071 数据不足 cov=0.50  （fx/sentimentA/riskAppetite/resource/techGreen = null）
B 快照日 2026-11-09 : norm=-0.020768 持有     cov=1.00  （8 维全在：+0.296 / +0.006 / -0.433 / -0.486 / +0.713 ...）
```

19 天全量重跑（`verify_a4_asof_today.py`）：

```
date         产物norm   产物sig | as-of norm as-of sig cov   diff
2026-11-09  -0.130071  数据不足 |   0.011375    持有   1.00  +0.141446
2026-11-10  -0.130071  数据不足 |   0.034536    持有   1.00  +0.164607
2026-11-11  -0.130071  数据不足 |   0.079961    持有   0.91  +0.210032
2026-11-12  -0.130071  数据不足 |   0.115176    持有   0.91  +0.245247
2026-11-13  -0.130071  数据不足 |   0.154216    持有   0.91  +0.284287
2026-11-14  -0.137214  数据不足 |   0.126490    持有   0.91  +0.263704
2026-11-16  -0.137214  数据不足 |   0.118922    持有   0.91  +0.256136
2026-11-17  -0.137214  数据不足 |   0.038275    持有   0.91  +0.175489
2026-11-18  -0.108485  数据不足 |   0.004536    持有   1.00  +0.113021
2026-11-19  -0.079208    持有   |  -0.028411   持有   1.00  +0.050797
2026-11-20  -0.088887    持有   |  -0.031875   持有   1.00  +0.057012
...（11-21 起偏移收敛，11-26/27/28 = 0）
```

后果有三层：

1. **19 天里 9 天的「新 8 维」数字是墙钟伪影**，最大偏 +0.284；
2. **「翻转 6 天」不成立**：旧 6 维也吃同一个 α，按正确口径重算（`verify_a4_flips.py`），翻转只有 **2 天（11-26、11-27，都是 减仓→持有）**；报告里的 11-19/20/24 在旧口径下本来就是「持有」，11-18 的「持有→数据不足」是 α 造成的假翻转；
3. **产物不可复现**：同一份快照明天再跑就变。实测 `resolve_freshness('2026-11-18','daily',today=11-29)` → `days_stale=11, expired, α=0`；今天还是 `stale, α=0.5`。也就是说**明天 11-19 那一行会从「持有/1.0」掉成「数据不足」**，一张表逐日腐烂。

> 补充回答工单里的问题：「严格 `<` 多滞后一天会不会导致 11-18 那种数据不足？」——**不会**。我用严格 `<` + 快照日时钟，11-18 的覆盖率是 1.00、信号「持有」。扣钉报告 §5.3 把 11-18 归因于「`<` 滞后一天触发 α=0」，归因错了：真因是墙钟。反过来说，如果改成 `≤ 当日`，11-18 的 dataDate 变 11-18（stale 10 → α=0.5）**看起来**就好了——那只是把 bug 遮住一天，11-09～11-17 照样烂。

修法（不代改）：`build_indicators_and_meta` 加 `today=None` 透传给 `resolve_freshness`，回算逐日传 `today=ds`；并加断言「产物重跑幂等」。这一条不改，B 项的交付物不能作为「6→8 维断档」的证据。

### 2.5 顺带：报告表格与产物这次是对齐的

上轮 P1-3（报告 6 flips/11-28 减仓 vs 产物 3 flips/持有）**形式上已修**：报告表现与 `recompute-*.json` 的 6 行/`flip_count=6` 一致。但如 §2.4，**两边一起错**——对齐的是同一份带 α 伪影的数。

---

## A4-3 新增披露字段（不看「有没有」，只看「对不对」）

### 3.1 `boundary_margin`：今日数字对，语义有洞

手算：`normalized − 最近阈值 = −0.041286 − (−0.109) = +0.067714` ✅，与产物 6 位一致，`boundary_threshold=−0.109`、`boundary_next_signal=减仓` 均对。

但用 4 个假设 normalized 直接打 `calc_ias`（`docs/verify-a4/verify_a4_boundary.py`，对应 `scoring.py:741-749` 的「最近阈值」策略）：

| 假设 normalized | 所在档 | 最近阈值 | margin | 代码给的 next | 实际最近翻档 | 判定 |
|---:|---|---:|---:|---|---|---|
| −0.041286 | 持有 | −0.109 | **+0.067714** | 减仓 | 下档减仓 @0.0677 | ✅ |
| +0.300 | 增持 | +0.217 | +0.083000 | 持有 | 下档持有 @0.083 | ✅ |
| −0.200 | 减仓 | −0.109 | **−0.091000** | 持有 | **上档**持有 @0.091 | ❌ 符号为负、方向反 |
| −0.400 | 清仓 | −0.326 | **−0.074000** | 减仓 | **上档**减仓 @0.074 | ❌ 同上 |

- **幅度永远是对的**（`abs(margin)` = 到最近档边的距离），**方向会错**：当 normalized 落在某档的**下半区**时，最近阈值是「本档上沿」，`normalized < threshold` → margin 变负（代码注释却把负值定义为「已越界」），`next` 指向更**好**的档。
- 前端 `src/App.tsx:633-636` 又把符号抹掉、固定写「**下档**X」：
  ```tsx
  距翻档 {Math.abs(ias.boundary_margin).toFixed(3)} · 下档{ias.boundary_next_signal}
  ```
  → 例如 normalized=−0.20 会渲染成「距翻档 0.091 · 下档持有」，读者会理解成「再跌 0.091 就变持有」——事实是再跌 0.091 仍是减仓，要涨 0.091 才变持有。
- 发生率：任何落在档位下半区的日子（约一半），都会出现负 margin；红色刀锋徽标用 `Math.abs` 所以不会误红，但**方向文案会反**。
- 修法：返回「本档上沿/下沿 + 有符号距离 + direction('up'|'down')」，前端按 direction 写「上档/下档」；顺带把注释里「<0 = 已越界」改成「<0 = 最近边界在下方」。
- 扣钉的 S16-01 只断言 `margin == norm − thr` 且 `thr ∈ 阈值表`，**没有断言 thr 就是「正确的那条边」或 next 的方向**，所以测不出来。

### 3.2 `fragile_inputs = []`：这次是对的

我没有信他，自己按定义（逐维剔除 + 重新归一化 + 重判信号）算了 8 次（`verify_a4_struct.py` 同源逻辑）：

```
drop economic     w=1.00 excl_norm=+0.004087 持有 impact=0.0454
drop inflation    w=1.00 excl_norm=-0.074826 持有 impact=0.0335
drop liquidity    w=0.80 excl_norm=-0.087000 持有 impact=0.0457
drop fxExternal   w=0.70 excl_norm=-0.084041 持有 impact=0.0428
drop sentimentA   w=0.90 excl_norm=+0.008638 持有 impact=0.0499
drop riskAppetite w=0.40 excl_norm=-0.005615 持有 impact=0.0357
drop resource     w=0.50 excl_norm=-0.012686 持有 impact=0.0286
drop techGreen    w=0.30 excl_norm=-0.077415 持有 impact=0.0361
→ 8/8 仍「持有」，fragile=[] 与产物一致 ✅
```

并且验证算法**不是写死空**：把各维分数整体下移 0.06/0.07 造出刀锋，它立刻报出 4 个维度并按 impact 降序（`liquidity 0.0457 > fx 0.0428 > techGreen 0.0361 > inflation 0.0335`），低置信度同时置 `low`。所以这一条**没有给用户假「很稳」**。

惟口径限制要说清（P2）：「剔除整维才翻档」是很粗的检查——它不测单指标、不测 ±1σ 的连续扰动；而 `confidence=high` 的条件本质就是「margin>0.05 且无置灰/降级」，和 margin 是同一件事的两种写法。所以「[] + high」只能读作「掉一整维不会翻档」，不能读作「结论很稳」。

### 3.3 `saturated`：4 项全对，无漏标

不是只看字段有没有：我把 37 个指标的原始值逐个对回 `POSITIVE/NEGATIVE/BIDIRECTIONAL` 断点区间，扫「值已越界却没标饱和」：

```
ppi            POS[-5,3]      val=5.7    score=+1.0 saturated=True
carbonPrice    POS[30,90]     val=97.0   score=+1.0 saturated=True
evPenetration  POS[20,60]     val=67.4   score=+1.0 saturated=True
shanghaiCopper BID[40000,90000] val=92550 score=-1.0 saturated=True
（其余 33 个：无越界值；无 |score|=1 却 saturated=false 的情况）
```

维度计数也对：`inflation 1 / resource 1 / techGreen 2`，其余 0；IAS `saturated_inputs` 与之相同。pct_rank/ratio 两类另有各自判据（`pct∈{0,1}`、撞 ratio 首拐点/压到地板），当前 4 个 pct/ratio 项 `pct_20/pct_60` 都在 0.07~0.65，无饱和。

文案缺陷（P2）：徽标文字写死「**已到区间上界**」，而沪铜是 −1.0（**下界**）——截图里沪铜那行确实挂着「已到区间上界·不携带信息」。tooltip 里写的是「上/下界」，可见只是可见文案没分方向。

---

## A4-4 结构性改动有没有副作用

### 4.1 归属与权重（逐条真跑）

```
权重和 = 5.6000000000000005；IAS_SCALE 由 sum(weight) 派生（仍非硬编码）
chinaBond10Y → dimension_of = liquidity（且仅此一处）
creditSpread → reference_only=True，dimension_of=fxExternal（只展示）
usBond10Y    → reference_only=False，仍在 fxExternal 打分
validate_metadata() → []
```

数值反证（用产物 indicators 自己算平均）：

- fxExternal（3 项计分）= (usdcnh 0.5 + dollarIndex 0.275 + usBond10Y 0.0)/3 = **0.2583 → 0.258** ✅（creditSpread −0.67 未进分母）
- fx 若把利差算回去 = (0.5+0.275+0−0.67)/4 = **0.026** ✅ 与报告「A4 前 +0.026」对上
- liquidity（4 项）= (lpr 0.333 + dr007 0.65 + m2 −0.95 + chinaBond 0.9)/4 = **0.23325 → 0.233** ✅
- liquidity 若退回 3 项 = 0.011 ✅ 与报告「A4 前 +0.011」对上

即报告 §2 D 的对照表是**可复算的真数**，不是抄的。

### 4.2 `fxExternal required_valid=2`：功能必要，且真能出分

真跑 `build_indicators_and_meta`，只给 usdcnh 加降级痕迹（其余保持今日）：

```
BASE      : fx score=0.258 valid=3 req=2 insuff=False | IAS norm=-0.041286
DEGRADED  : fx score=0.138 valid=2 req=2 insuff=False | grayed=[] | IAS norm=-0.056286
            usdcnh score=None exclusion_reason=degraded_no_score
反事实(去掉覆盖): fx score=None valid=2 req=3 insuff=True | grayed=['fxExternal'] | cov=0.875 | norm=-0.084041
```

- 覆盖确实保住了 D2/D7：usdcnh 降级时 fx 仍以 2/2 出分（0.138），整维不置灰。
- 反证也说明这个口子**不是摆设**：按 T4 默认（n=3 必须全有效）整维会归零、覆盖率掉到 0.875。
- **但它是把 T4 从「n≤3 全有效」放松成「3 选 2」**——副作用是：以后 `dollarIndex` 或 `usBond10Y` 任一缺失，fx 也照样出分（而这两项没有「允许降级」的设计理由）。建议把覆盖做成「仅当缺失项是 usdcnh 时按 2 计」，其余仍按 3；至少要在字段里写明“为 usdcnh 开的例外”。→ A4-P1-3（治理/口径，非站点 bug）。

### 4.3 chinaBond10Y 固定水位的敏感性（工单点名要结论）

断点 `NEGATIVE (1.5, 2.5, 4.0)`，`score_negative`：

| 中债10Y | indicator score | liquidity | IAS normalized | 位移 | saturated |
|---:|---:|---:|---:|---:|---|
| 1.4% | **+1.000** | +0.258 | −0.037482 | +0.003804 | True |
| 1.5% | **+1.000** | +0.258 | −0.037482 | +0.003804 | True |
| 1.6%（今日） | +0.900 | +0.233 | −0.041286 | 0 | False |
| 2.0% | +0.500 | +0.133 | −0.055339 | −0.014053 | False |
| 2.6% | −0.067 | −0.008 | −0.075482 | −0.034196 | False |
| 3.5% | −0.667 | −0.158 | −0.096911 | −0.055625 | False |
| 4.5% | −1.000 | −0.242 | −0.108911 | −0.067625 | True |

**明确判断：该打回重标（P1），但不必删。** 理由：

1. 「长期停在 1.5 以下 → 恒 +1.0」**成立**。今天 1.60 距地板只剩 0.10pp，指标已吃掉 90% 的量程，实质接近二值化——这就是今天第三次出现的「固定水位 → 恒定满分」（前两次是旧 usdcnh 7.05/7.20/7.35 恒 +0.5、PPI 越过上界恒 +1.0）。
2. 与那两次的关键差别：这次 `|score|=1` 会触发 `saturated=True`，页面会挂「不携带信息」徽标，**不是静默满分**。所以危害被披露机制部分抵消，这也是我不把它列为 P0 的原因。
3. 真正该改的是**口径**而不只是断点：① 断点是扣钉自己「按当前利率中枢暂定」，报告 §5.2 也承认要龙六标定；② 「收益率越低＝货币越松＝越好」在通缩/衰退式下行时会反向（与经济维度的“放缓”打架，和 PPI「成本冲击按利好计价」是同一类方向风险，而那条他自己标了“方向待批次 C 修正”）；③ liquidity 里 lpr/dr007 本来就是绝对水位，再加一个绝对水位，这一维 4 项里 3 项没有相对基准。
4. 建议：改用「相对 120 日均值 + 绝对地板」的混合口径（与 usdcnh 同法），或保留水位但把 L 调到 1.2 以下并在文案里写死「≤L 视为饱和、不提供区分度」。

### 4.4 Dashboard 删除 / health_check / cron

- `src/components/Dashboard.tsx` 已删除（`src/components/` 只剩 `DimensionCard.tsx`）；全仓 `grep Dashboard` 仅剩 `alerts.ts` 的 `DashboardSummary`（另一个东西）与注释。
- 无残留 import：`npm run build` 通过（`✓ 19 modules transformed`，`dist/assets/index-BO6agkPn.js 232.40 kB`）；SPA 无路由表，不存在死链。
- `scripts/health_check.py` 确由主流程调用：`fetch_worldos_data.save_results()` 里 `import health_check; check_document(output)`（`fetch_worldos_data.py:1699-1700`），并在保存后打印 `🩺 WARN:`；异常被吞不影响抓取。
- 三类告警我各自触发过一次（夹具 3 条维度剔除；注入降级 + margin=0.007 → 降级/刀锋 2 条）。
- **无新 cron**：`crontab -l` 空；`~/Library/LaunchAgents` 仅 `com.openclaw.update-market-data`（跑的是 `workspace-market-insight`，与 worldos 无关）；本提交未新增任何 plist/定时项。

---

## A4-5 端到端（我自己跑、我自己截）

### 5.1 四套命令原始尾行

```
$ python3 scripts/test_schema_fields.py
189 passed / 0 warn / 0 failed / 189 total

$ python3 scripts/test_no_nan_json.py
全部通过：3 个模块均不会产出非法 JSON

$ node --test tests/caliber-edge.test.mjs
# ✅ 全部通过：300 项断言   （pass 1 / fail 0）

$ npm run build
✓ 19 modules transformed.
dist/assets/index-BO6agkPn.js   232.40 kB │ gzip: 72.74 kB
✓ built in 76ms
```

补：`python3 scripts/indicator_meta.py` → 元数据校验通过（36 指标/8 维）；`dist/` 构建后 `git diff` 为空（构建可复现）。

### 5.2 本地 preview + 自截（`vite preview :4179` + Chrome headless 1440×2700）

DOM 统计（真实渲染 dump）：

```
8 个维度名各在 DOM 出现 3~5 次（卡头/分档条/解读）
市场情绪 = 0     sentiment = 0
已到区间上界 = 8 处（4 个指标 × 徽标文字 + title）
距翻档 = 1   置信度 = 1   含 4 项饱和 = 1   项饱和 = 4（维度卡 1+1+2）
口径： = 8   eff= = 16
```

截图：`docs/shots/a4-verify-full.png`（全页，我自己截；未用扣钉的 `a4-2026-11-28.png`）。关键区域逐项核对：

- IAS 头：`−0.23 · 持有 · 建议仓位 40–60%`；`数据覆盖 100% / 有效权重 5.6/5.6（覆盖 100%）/ 归一化 −0.0413 / 距翻档 0.068 · 下档减仓 / 置信度 高 / 含 4 项饱和` ✅
- 8 张卡全在，头部 `w=… · eff=…`；「汇率与外部」`3 项计分 · 1 项参考（不计分）· 需 ≥2`，中美利差 334bp 标「参考项」；「流动性（国内）」出现 `中国10年国债收益率 1.60% → +0.90` ✅
- 饱和徽标：PPI、碳价、新能源渗透率（+1.0）与沪铜（−1.0）行都有 amber「已到区间上界·不携带信息」✅
- 旧「市场情绪」卡 0 次、8 维分档条 8 个 chip ✅（唯一瑕疵：1440 宽下第 8 个 chip 换行独占一行，P2 视觉）

### 5.3 ⚠️ A4-P1-4：页面里「IAS 整体解读」仍写 −0.57，与头部 −0.23 打架

截图底部「📝 数据解读 · 🔍 IAS 整体解读」标题旁写着 **−0.57**，正文首句「本期IAS综合评分**−0.57**（持有…）」，还把「流动性/汇率」排除在加分来源之外（只列通胀+科技）——**与头部 −0.23 及 8 维权重大小矛盾**。

根因：`public/data/commentary.json` 的 `generatedAt = 2026-11-28T17:36:07`，早于 A4 提交（17:58）；A4 只改了 `commentary_generator.py`（+18 行）而**没有重生成产物**。`dist/data/commentary.json` 同为 −0.57。

我没有改仓库文件，而是在 `/tmp` 复制一份 `market-data.json` 重跑生成器验证：

```
✅ 评论已生成（临时目录）
NEW score -0.23
本期IAS综合评分**-0.23**… 💰通胀与政策（+0.11）、💧流动性（国内）（+0.23）、💱汇率与外部（+0.26）、🌱科技与绿色（+0.60）是主要加分来源
```

→ 只要重生成一遍就一致；现在交付的页面是「头 −0.23 / 正文 −0.57」。**这是用户直接看得到的自相矛盾，也是 A4「报告与产物对齐」这条要求本身没做到的最后一环。**

### 5.4 JSON ↔ 页面抽查（10 个，要求 5 个）

| 指标 | JSON | 页面 | 位置 |
|---|---|---|---|
| usdcnh | 6.6551 / +0.5 | 6.66 / +0.50 | 汇率 |
| usBond10Y | 4.94 / 0.0 | 4.94% / 0.00 | 汇率 |
| dollarIndex | 97.8 / +0.275 | 97.80 / +0.28 | 汇率 |
| creditSpread | 334 / −0.67 | 334.00bp / −0.67（参考） | 汇率 |
| ashareTurnover | 19997.94 / +0.234 | 19998亿元 / +0.23 | A股 |
| marginBalance | 21055.79 / −0.76 | 21056亿元 / −0.76 | A股 |
| southboundNet | 79.81 / −0.78 | 79.81亿元 / −0.78 | A股+顶栏 |
| shanghaiCopper | 92550 / −1.0 | 92550¥/吨 / −1.00 | 资源 |
| chinaBond10Y | 1.60 / +0.9 | 1.60% / +0.90 | 流动性 |
| ppi | 5.7 / +1.0 | 5.70% / 饱和徽标 | 通胀 |

10/10 一致。

---

## A4-6 问题清单

### P0（修完才算过）

1. **A4-P0-2：降级日的值会被「上一轮兜底」二次写进 usdcnh 序列**
   - 证据：`docs/verify-a4/verify_a4_p0b.py` → `[DAY2] skipped=[] points=251 degraded_day_persisted=True value=6.62`。
   - 根因：`load_prev()` 丢 `sourceDegraded`（`fetch_worldos_data.py:1587-1602`）+ 兜底分支清空它（`:1829-1831`）。
   - 触发：连续两天失败（Day1 主源失败走降级、Day2 全失败走兜底）。
   - 修法：`sync_series` 增加 `or v.get('used_fallback')` 跳过；补 S13-10 断言「兜底值不得 upsert」。

### P1（本批交付物正确性，建议本批内修）

2. **A4-P1-1：回算时效 α 用墙钟今天算** → 19 天里 9 天 normalized 失真（最大 +0.284）、「翻转 6 天」实际 2 天、产物逐日不可复现（明天 11-19 行会变成「数据不足」）。
   证据：`verify_a4_alpha.py`、`verify_a4_asof_today.py`、`verify_a4_flips.py`。
   修法：`build_indicators_and_meta(today=...)`；逐日 `today=ds`；加幂等断言。
3. **A4-P1-4：`public/data/commentary.json` 未随 A4 重生成**，页面「IAS 整体解读」写 −0.57（头 −0.23），加分来源漏掉流动性/汇率。
   证据：截图 `docs/shots/a4-verify-full.png` 底部；临时目录重生成得 −0.23。修法：重跑 `commentary_generator.py` 并纳入交付检查（`dist/` 同步）。
4. **A4-P1-2：`boundary_margin` 在档位下半区符号为负、`boundary_next_signal` 指向更好的档，前端又固定写「下档」** → 例如 normalized=−0.20 会显示「距翻档 0.091 · 下档持有」（真实是上档持有）。
   证据：`docs/verify-a4/verify_a4_boundary.py` 的 4 个假设值表。修法：返回 direction + 上/下沿，前端按方向出文案。
5. **A4-P1-3（治理）：`required_valid=2` 对 fx 是「3 选 2」的通用放松**，不止对 usdcnh 生效；扣钉报告 §5.1 自己也把这条挂给 PM 拍板。建议改成「仅 usdcnh 缺失时按 2 计」，否则以后美元指数/美债缺失也会静默出分。
6. **A4-P1-5（口径）：chinaBond10Y 固定水位 1.5/2.5/4.0 应重标**（结论见 §A4-4.3：不阻塞站点，但必须由龙六定断点或改相对口径；今日 1.60 已距地板 0.10pp）。

### P2（清理/文案，不阻塞）

7. `saturated` 徽标写死「已到区间**上界**」，沪铜 −1.0 是下界（tooltip 已写「上/下界」，可见文案没分）。
8. IAS 级 `saturated_inputs` 不筛 α>0，维度级筛；若某个饱和项过期剔除，IAS 会多报一项饱和。
9. `src/App.tsx:324` 兜底对象仍硬编码 `max_possible: 5.6`（上轮 P2-8 未销项）。
10. `public/data/market-data.json.recompute.note` 仍写「usdcnh 取自回填日线序列，其余全部取自快照」——A4 后是 5 条 series + 中债反算，文案过期。
11. 中债项 `source` 标 `akshare-中美债券`，但值实际是「美债10Y − 利差」反算；`caliberNoteSuffix` 已披露，建议 `source` 也标 derived。
12. 1440 宽下 8 维分档条第 8 个 chip 换行独占一行。
13. `src/data/marketData.ts:229` 仍有 `case 'sentiment'`（v6 deprecated，未挂载，仅 grep 噪音）。

---

## A4-7 附：这轮我独立发现、扣钉报告里没有的 5 条

1. **A4-P0-2 二次兜底穿透**（P0）——他只补了单日 `sourceDegraded` 的跳过；「降级 → 次日全源失败 → 兜底写回」仍会把在岸价塞进序列。他的 S13-09 结构上测不到。
2. **A4-P1-1 回算 α 墙钟**（P1）——他报告的「6 次翻转」有 4 次是墙钟伪影，真实 2 次；同一份快照明天重跑会变。他 §5.3 把 11-18 归因于「`<` 滞后一天」，归因错了。
3. **A4-P1-4 页面解读 −0.57 vs 头部 −0.23**（P1）——他改了生成器却没重生成 `commentary.json`，页面自相矛盾。
4. **A4-P1-2 boundary 方向语义**（P1）——今日 0.0677 是对的，但档位下半区会出负值和反向「下档」，约一半的日子会踩。
5. **饱和徽标「上界」用于 −1.0**（P2）——沪铜明明是下界。

## A4-8 附：对上轮报告的自我更正

- 上轮 §3.5 说单次污染「相当于 10–30% 档宽」——**错**，单日只占 0.4% 档宽；危害来自连续多日累积（整窗可到 51.8%）。P0 结论不变，量级说法更正（§A4-1.2）。
- 上轮 §5.3 说「18/19 天 sentimentA=null：回算只注入 usdcnh」——A4 已把 5 条 series 全部注入，该具体缺陷**已修**；但同样的 null 症状现在由 α 墙钟造成（§A4-2.4），属于「换了根因的同类症状」，不能算彻底关闭。
