# P1-8DIM 工单：WorldOS 六维 → 八维（批次 A：骨架搬家）

- 派单：龙五（PM）　日期：2026-11-28　执行：扣钉　验收：泰斯特 → 龙六
- 依据：龙六 2026-11-27 方案 + 龙五 2026-11-28 落位（本文件为唯一真源，与代码冲突时以本文件为准）
- 硬约束：**本地 commit 可以，禁止 `git push`、禁止部署、禁止改 cron**。完成后写报告回主线，主线复核再统一发版。

---

## 0. 本批范围（一次只改一件事）

**只做「结构 + 权重 + 搬家 + 新增 1 个指标」**，即八维骨架。

**明确不在本批**（防止混批无法归因）：
- ❌ 打分方法变更（evPenetration / renewEnergyInvest 改分位）→ 批次 B
- ❌ 三个打分 bug（PPI 方向、EV/碳价越阈值永久 +1、沪铜符号）→ 批次 C
- ❌ dollarIndex 改 ICE 真值口径 → P1.5（本批只在 caliberNote 声明「三货币加权代理」）
- ❌ 需求侧指标（出口/社零/固投）、事件 overlay、Q3 双信号 → P2

**但有一件必须同批做**：阈值量纲统一（见 §4）。原因：IAS_SCALE 4.6→5.6，若阈值仍按 score 量纲写死，上线即刻误判，这不是「另一个改动」，是同一个改动的必要组成。

---

## 1. 八维定义（逐项落位，照抄）

| # | id | 名称 | icon | weight | indicators（打分成员，有序） | reference_indicators（只展示） |
|---|---|---|---|---|---|---|
| 1 | `economic` | 经济增长 | 📈 | 1.0 | chinaGdp, chinaPmi, usGdp, servicePmi, electricity, usNonFarm | — |
| 2 | `inflation` | 通胀与政策 | 💰 | 1.0 | cpi, ppi, usCpi, corePce, fedRate | — |
| 3 | `liquidity` | 流动性（国内） | 💧 | 0.8 | lpr, dr007, m2 | — |
| 4 | `fxExternal` | 汇率与外部 | 💱 | 0.7 | usdcnh（新增）, dollarIndex, creditSpread, usBond10Y | — |
| 5 | `sentimentA` | A股/港股情绪 | 🧠 | 0.9 | ashareTurnover, marginBalance, southboundNet, hstechMomentum | — |
| 6 | `riskAppetite` | 全球风险偏好 | 🌍 | 0.4 | vix, fearGreed | usBond2Y, usBond5Y |
| 7 | `resource` | 资源与供应链 | 🛢️ | 0.5 | oilPrice, naturalGas, shanghaiCopper | lmeIndex |
| 8 | `techGreen` | 科技与绿色 | 🌱 | 0.3 | evPenetration, renewEnergyInvest, carbonPrice | aiGrowth, robotInstall |

**权重合计 = 5.6**（1.0+1.0+0.8+0.7+0.9+0.4+0.5+0.3）。
龙六方案原文写 5.5，逐项相加为 5.6 —— **以 5.6 为准**，`IAS_SCALE` 必须由 `sum(d['weight'])` 派生，禁止硬编码。

### 1.1 关键落位理由（写进 CHANGELOG，便于日后复盘）
- `liquidity` **保留 id 不变**（只改 name 与成员），避免历史序列 key 断裂；移出 dollarIndex / creditSpread / usBond2Y / usBond5Y / usBond10Y。
- `creditSpread` 名不副实（实际抓的是**中美 10 年国债利差**，不是企业信用利差）→ 移入 `fxExternal`，并在 name/caliberNote 里改成「中美10Y利差」，**不改数据源**。
- `usBond10Y` 随 creditSpread 一起进 `fxExternal`（利差的另一半，同口径）；`usBond2Y`/`usBond5Y` **降级为 riskAppetite 的 reference_only**（不打分，避免与 fedRate、期限结构重复计入）。
- `sentiment` 拆分：原 4 个 A股/港股代理独立成 `sentimentA`（0.9，这是老板 46% 仓位在港股的关键维度）；VIX + F&G 缩编为 `riskAppetite`（0.4）。**旧 id `sentiment` 必须消失**，不允许保留兼容别名继续打分。
- `resource` 去共线：`shanghaiCopper` 保留打分（中国定价 + 老板持洛钼），`lmeIndex` 降 reference_only。`carbonPrice` 移入 `techGreen` 打分。
- `techGreen` 现有 aiGrowth / robotInstall 保持 reference_only 现状（不要顺手转正）。

---

## 2. 新增指标 `usdcnh`

- 定义：`{'name': '美元兑离岸人民币', 'short': 'USDCNH', 'country': '🌏', 'unit': '', 'frequency': 'daily', 'caliberNote': '离岸人民币汇率；取不到离岸价时回退在岸中间价并在 caliberNote 标注'}`（source 按实际数据源填写）
- 取数优先级（顺序尝试，**必须 log 用了哪个源**）：
  1. akshare 离岸人民币报价（东财/新浪 USDCNH 现货）
  2. `https://api.exchangerate-api.com/v4/latest/USD` 的 `rates.CNY`（**在岸口径**，回退时 caliberNote 追加「在岸参考价」）
  3. 取不到 → 返回 None，**不许造数、不许用上一交易日硬填**
- 打分方法：`breakpoint`（**不要求历史回填**，这是它进本批的前提），方向：**数值越高 = 人民币越弱 = 越差**。分段建议（可在报告中提出修正，但需写明理由）：
  - `>= 7.35` → −1.0　`7.20~7.35` → −0.5　`7.05~7.20` → 0　`< 7.05` → +0.5
- 维度 4 共 4 项 → 最小有效数 `max(2, ceil(4*0.5)) = 2`。**usdcnh 失败时维度仍可出分**（这是选 4 项而不是 3 项的原因，n≤3 要求全有效太脆）。

---

## 3. 必须同步改的下游（漏一处就是线上 bug）

1. `scripts/indicator_meta.py`：DIMENSIONS 重写；`INDICATOR_DIMENSION` 派生自动生效；`INDICATORS` 加 usdcnh；creditSpread/lmeIndex 的 name 或 caliberNote 按 §1.1 调整。
2. `scripts/scoring.py`：确认只读 `DIMENSIONS`/`IAS_SCALE`，**不得有 4.6 / 6 维 的任何硬编码残留**（grep 全仓 `4.6`、`'sentiment'`）。
3. `scripts/commentary_generator.py`：8 个维度都要有分析文本模板，新增 `sentimentA` / `fxExternal` / `riskAppetite` 的文案；`DIMENSION_ORDER` 由 meta 派生（已派生则确认）。
4. `src/App.tsx`：`DIMENSION_ORDER`、`DIM_NAMES`、`DIM_INDICATORS` 三处硬编码全部改 8 维（含 usdcnh 的指标卡片 key）。
5. `src/components/Dashboard.tsx`：虽有未挂载嫌疑，但硬编码的 `sentiment` 卡片必须跟着改或显式标注 `@deprecated 未挂载` —— **不许留指向不存在维度的死引用**。
6. `CHANGELOG.md`：记录 6→8 维、权重 5.6、阈值量纲统一、usdcnh 新增、四类搬家理由。
7. `rules_snapshot` / `rules_hash` 会变：确认页面/接口读的是快照而非硬编码，变化属预期，报告里贴出 old→new hash。

---

## 4. 阈值量纲统一（本批不可分割项）

现状 bug：内部拿 `score`（量纲 Σ权重=4.6）比 `-0.5`，对外发 `normalized`，真实分界漂到 normalized −0.109。

**做法**：阈值常量改为 **normalized 语义**，比较一律用 `ias.normalized`。
保持今天（scale=4.6）的信号语义不变，换算：

| 信号 | 仓位 | 旧 score 阈值 | 旧 normalized 边界 | 新常量（normalized） |
|---|---|---|---|---|
| 🚀 强烈买入 | 80-100% | 2.5 | 0.5435 | **0.543** |
| ✅ 增持 | 60-80% | 1.0 | 0.2174 | **0.217** |
| ➖ 持有 | 40-60% | −0.5 | −0.1087 | **−0.109** |
| ⚠️ 减仓 | 20-40% | −1.5 | −0.3261 | **−0.326** |
| 🛑 清仓/防御 | 0-20% | 低于上式 | | |

即：**信号边界在 normalized 空间恒定，缩放 IAS_SCALE 不再改变信号含义**。加断言：把 11-28 当日数据喂新代码，信号档位必须与旧代码一致（当日旧信号见 §6 基准）。

---

## 5. 历史序列回算（防跨日断档）

IAS_SCALE 4.6→5.6 且结构变，`normalized` 会凭空跳变。必须：
- 用 `data/history/` 最近 **30 个交易日**原始指标值，按新 8 维结构重算 IAS 与 normalized，产出对照表（旧 vs 新）
- 明确回答：这 30 天里**信号档位发生翻转的是哪几天**、原因（是权重变化还是缺失剔除），逐日列出
- 回算脚本可复用/参考 `scripts/replay_sentiment_30d.py`，**不覆盖**历史原始 JSON，只产出对照产物（如 `data/history/recompute-8dim-2026-11-28.json`）

---

## 6. 验证要求（提交报告必须含原始输出，不许只写「已通过」）

**基准日 = 2026-11-28 16:02 快照**：现网 6 维，IAS score −0.43 / normalized −0.0936 / 信号「持有」，weight_design_sum 4.6 / effective 4.4。

必过项：
1. `python3 scripts/test_schema_fields.py` — 全过（契约改动要逐条列出并说明理由）
2. `python3 scripts/test_no_nan_json.py` — 过
3. `node --test tests/caliber-edge.test.mjs` — 全过（断言数变化要说明）
4. `npm run build` — 过，并贴 bundle 大小
5. **新断言**（必须新增，不是口头保证）：
   - `len(DIMENSIONS) == 8`；权重和为 5.6；`IAS_SCALE == 5.6`
   - 每个指标**恰好**属于一个维度（无重复、无遗漏、无孤儿 key）
   - `reference_only` 指标不计入分母、不参与平均
   - 全仓 grep 无 `4.6` 硬编码残留、无 `'sentiment'` 旧 id 残留（注释除外需标明）
   - usdcnh 缺失时，`fxExternal` 维度仍出分且 `insufficient_data == False`
6. **同日新旧对照**：用 11-28 当日原始数据，分别跑旧 6 维 / 新 8 维，给出逐维度分数、权重、有效权重、IAS score/normalized、信号档位 —— 说明差异来源（哪个维度、多少）

---

## 7. 交付物

1. 代码改动（本地 commit，**分两笔**：`feat` 代码一笔、`data`/回算产物一笔；不 push、不部署）
2. `docs/P1-8DIM-REPORT.md`：八维表、权重和、IAS_SCALE、阈值前后对照、同日新旧对照、30 日回算翻转清单、测试原始输出、遗留风险清单
3. 回主线报告：**做了什么 / 验证证据 / 我不确定的 3 件事 / 需要 PM 拍的决策**

## 8. 已知风险（执行时不要私自"优化"绕过）

- `liquidity` 只剩 3 项 → T4 规则要求**全部有效**，任一缺失整维剔除（0.8 权重归零）。如实跑发现常态缺失，报上来，别自己加指标。
- `usdcnh` 源若拿不到离岸价只能回退在岸，口径必须在页面上可见（caliberNote 会展示）。
- 权重从 4.6 变 5.6，`weight_effective_sum` 会变，任何按旧和数算比例的展示都要核对。
