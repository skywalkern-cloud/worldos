# WorldOS v4.1 代码评审报告

**评审时间**: 2026-05-24 21:49 CST  
**评审范围**: 
- `scripts/scoring.py` (评分模块)
- `fetch_worldos_data.py` (数据采集脚本 v2.6)
- `get-all-data.py` (数据采集脚本 v6) 
- `public/data/market-data.json` (输出数据)
- `src/App.tsx` (前端入口+布局)
- `src/hooks/useMarketData.tsx` (数据获取 Hook)
- 其他前端文件 (Dashboard.tsx, DimensionCard.tsx, marketData.ts, alerts.ts 等)

---

## 🔴 关键 Bug（需要立即修复）

### 1. CRITICAL: 维度评分在全部数据过期时默认为 0.0

**位置**: `scripts/scoring.py` → `calc_dimension_scores()`

**问题**: 当某个维度的全部指标 `timeliness (α) = 0` 时，`total_alpha = 0`，维度评分被设为 `0.0`。

**修复方法**: 当 `total_alpha == 0` 时，改用简单平均（忽略时间衰减）作为 fallback：

```python
if total_alpha > 0:
    avg_score = round(total_weighted / total_alpha, 3)
elif valid_count > 0:
    # Fallback: unweighted average when all data is expired
    total_unweighted = sum(
        indicators[key]['score']
        for key in dim['indicators']
        if indicators.get(key, {}).get('score') is not None
    )
    avg_score = round(total_unweighted / valid_count, 3)
else:
    avg_score = 0.0
```

### 2. CRITICAL: aiGrowth 和 robotInstall 使用完全相同的底层数据

**位置**: `fetch_worldos_data.py` → `INDICATOR_DEFS`

```python
'aiGrowth': {'func': get_electricity_industry, ...},
'robotInstall': {'func': get_electricity_industry, ...},  # ← 同一个函数！
```

**问题**: 两个指标调用同一个 `get_electricity_industry()` 函数，数据永远相同（目前都是 4.9%）。来源标注为"国家能源局-第二产业"也与实际指标名不匹配（AI产业增速≠第二产业用电量增速）。

**影响**: 在评分校验中，两个指标虽有不同的参数范围（aiGrowth: 0/10/25，robotInstall: -5/10/25），但数据完全相同导致冗余。

**建议**: 至少修改 `robotInstall` 的 `source` 字段和落地用的函数途径，或者合并为一个指标。

### 3. CRITICAL: evPenetration 参数阈值与代理数据不匹配

**位置**: `scripts/scoring.py` → `BIDIRECTIONAL_PARAMS`

```python
'evPenetration': (20, 40, 60),  # EV渗透率%的理想范围
```

**问题**: 实际数据来自第三产业用电量增速（当前 8.3%），阈值 (20, 40, 60%) 是为真实EV渗透率设计的。当前值 8.3 远低于 L=20，永远得分 -1.0。

**建议**: 要么更换真实EV渗透率数据源，要么调整参数为 (5, 10, 20) 匹配第三产业用电量的实际范围。

### 4. 数据源脚本 Key 命名不一致

**位置**: `get-all-data.py` vs `fetch_worldos_data.py` vs `scoring.py`

**问题**:
- `fetch_worldos_data.py` 使用 `chinaGdp`, `chinaPmi` 等 Key ← 和 scoring.py 一致 ✅
- `get-all-data.py` 使用 `gdp`, `pmi`, `interest` 等不同 Key ← 不匹配 ❌
- 两个脚本只有 7 个 Key 是相同的

**影响**: 如果误运行 `get-all-data.py` 覆盖 `market-data.json`，所有评分将失效（因为 Key 不匹配 scoring.py）。

**建议**: 统一两套脚本的 Key 命名。如果 `get-all-data.py` 不再使用，应考虑删除或注释。

### 5. 大量指标数据过期 / 数据新鲜度危机

**时间**: 2026-05-24

**当前数据新鲜度分布**:

| 状态 | 数量 | 指标 |
|------|------|------|
| 🟢 正常 | 10 | vix, oilPrice, naturalGas, dollarIndex, lpr, dr007, creditSpread, renewEnergyInvest, usCpi |
| 🔴 过期 | 14 | chinaGdp, chinaPmi, usGdp, servicePmi, corePce, fedRate, cpi, ppi, m2, epu, carbonPrice, electricity, aiGrowth, robotInstall, evPenetration |

**问题**: 14/24 个指标时效性为 0.0（过期），原因是 AKShare 数据仅最新几条可用，历史久远：
- `cpi`, `ppi`, `chinaPmi`, `m2`, `corePce`, `servicePmi` 数据日期均为 **2025-08**（9个月前）
- `epu` 数据日期更是 **2023-11**（18个月前）
- 这导致 `经济增长` 维度 5个指标全部过期，维度评分完全不受时间衰减保护

**建议**: 增加数据源多样性（FRED、东方财富、Wind等），不要仅依赖 AKShare。

---

## 🟡 评分算法验证

所有评分公式计算正确，经测试通过：

| 指标 | 参数 | 数值 | 得分 | 结果 |
|------|------|------|------|------|
| chinaGdp=5.0 | (3,5,7) 正向 | 5.0 == T | 0.0 ✅ |
| lpr=3.0 | (2,3.5,5) 逆向 | L<3.0<T | +0.333 | ✅ |
| cpi=0.0 | (0,1,3,5) 双向 | == L_low | -1.0 | ✅ |
| oilPrice=97 | (40,60,90,120) 双向 | T_high<97≤H_high | -0.233 | ✅ |
| EPU=743.4 | (80,150,300) 逆向 | >H | -1.0 | ✅ |
| usCpi=3.8 | (0,1.5,3.5,5) 双向 | >H_high(3.5) | -0.2 | ✅ |

**`get_signal()` 信号映射** 也正确：

| 评分范围 | 信号 | 说明 |
|----------|------|------|
| ≤ -0.5 | red 🔴 | 严重负面 |
| > -0.5 且 ≤ -0.1 | yellow 🟡 | 关注 |
| > -0.1 且 < 0.1 | gray ⚪ | 中性 |
| ≥ 0.1 且 < 0.5 | lightgreen 🟢 | 略正面 |
| ≥ 0.5 | green 🟢 | 正面 |

---

## 🟢 前端评审

### 6. App.tsx 总体结构良好

- 使用 `useMemo` 缓存异常指标列表 ✅
- 按维度分卡片展示 ✅
- 按国家分组显示指标 ✅
- 新鲜度标注（🟢🟡🔴） ✅
- 过期指标降透明度（opacity-50） ✅
- 骨架屏加载态 ✅

### 7. 异常指标速览缺少 `lightgreen` 信号

**位置**: `App.tsx` → `AnomalyBar`

```typescript
const anomalies = useMemo(() => {
    for (const [key, info] of Object.entries(indicators)) {
      if (info.signal === 'red' || info.signal === 'yellow') {  // ← 缺少 lightgreen?
```

不算 Bug（异常 bar 显示严重异常），但 `lightgreen` 信号在前端其他地方也没有被突出使用。

### 8. 旧 Dashboard 组件存在死代码

**位置**: `src/components/Dashboard.tsx`, `DimensionCard.tsx`, `data/marketData.ts`, `data/alerts.ts`, `data/realtime.ts`

`main.tsx` 只渲染 `App`（v4.1），Dashboard 及相关组件（v6 旧版）的全套代码未被使用，但仍保留在代码库中。

**建议**: 确认不再使用后删除，减少维护负担。

### 9. `dollarIndex` 前端显示与后端评分解读不一致

`dollarIndex` 在 `NEGATIVE_PARAMS` 中（逆向指标：越高越负面），但前端没有特殊标注。目前显示 Score=🟢+0.525，但从逆向含义看：美元指数 95.8 低于典型值 (T=100)，这被解读为正面。

**建议**: 如果 `dollarIndex` 是逆向指标（高美元指数→资金外流→负面），评分逻辑正确，但建议在维度和指标行旁边加上小标注（如 🟦 逆向评分），避免使用者困惑。

---

## 📋 数据完整性

### 10. `geoRisk` 和 `extremeWeather` 无评分参数

两个指标存在于 `market-data.json` 但 scoring.py 中没有定义：

| 指标 | 数据来源 | 评分 |
|------|----------|------|
| `geoRisk` | VIX × 10 | score: None (defaults to null) |
| `extremeWeather` | 50 + (servicePmi - 50) × 2 | score: None (defaults to null) |

前端显示 gray 信号 → 不影响评分但占用展示空间。建议要么配置评分参数，要么从公共展示中隐藏。

### 11. `creditSpread` 评分方向确认

`creditSpread` 在 `NEGATIVE_PARAMS` 中：L=100bp, T=200bp, H=400bp。

当前值 281bp → 100 ≤ 281 < 400:
- 281 < 200(T)? No (281 > 200)
- 200 ≤ 281 < 400: score = (200 - 281)/(400 - 200) = -81/200 = -0.405

信号黄色的逻辑是：信用利差偏高（美联储降息后美债低，中美利差走阔提示风险），评分合理 ✅

---

## ✅ 整体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| 评分算法 | 🟢 正确 | 连续三段线性映射正确实现 |
| 信号映射 | 🟢 正确 | 信号区间划分合理 |
| 时间衰减 | 🟢 正确 | 按频率降权逻辑正确 |
| 维度分类 | 🟢 合理 | 6维度分类 + 国家分组合理 |
| 前端展示 | 🟢 良好 | 干净整洁，异常高亮，新鲜度标注 |
| **数据新鲜度** | 🔴 危机 | 58% 数据过期，影响整体评分可信度 |
| **AKShare 依赖** | 🟡 单一 | 需接入更多数据源（FRED API, 东方财富等） |
| **维度评分 fallback** | 🔴 Bug | 全过期时维度评分 = 0.0 需修复 |

### 紧急修复优先级

1. 🔴 **`scoring.py` → `calc_dimension_scores()`**: total_alpha=0 时的 fallback（影响 IAS 综合评分的准确性）
2. 🔴 **`fetch_worldos_data.py` → aiGrowth/robotInstall**: 区分两个指标的底层数据
3. 🔴 **`scoring.py` → evPenetration**: 参数阈值匹配实际数据源
4. 🟡 **数据源扩展**: 解决 58% 数据过期问题
5. 🟡 **`get-all-data.py`**: 清理或重建 Key 命名一致性
6. 🟢 **前端死代码**: 清理旧 v6 组件

---

*评审完成: 2026-05-24 22:10 CST*
