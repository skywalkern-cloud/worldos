# WorldOS 5大维度设计文档（v2.0）

## 一、维度总览

| 维度ID | 维度名称 | 英文名 | Icon | 指标数 | 说明 |
|:------:|:---------|:-------|:----:|:------:|:-----|
| 1 | 经济产出 | Economic Output | 📈 | 4 | GDP、PMI等 |
| 2 | 通胀与价格 | Inflation & Prices | 💰 | 4 | CPI、PPI等 |
| 3 | 货币与信用 | Money & Credit | 🏦 | 4 | 利率、货币供应量 |
| 4 | 风险与不确定性 | Risk & Uncertainty | ⚠️ | 4 | VIX、EPU等 |
| 5 | 气候与资源 | Climate & Resources | 🌍 | 4 | 油价、碳价 |

---

## 二、指标列表（20个）

### 维度1：经济产出 (Economic Output) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 | 频率 | 时效要求 |
|:----:|:-------|:-------|:-------|:-------|:----:|:---------|
| 1 | chinaGdp | 中国GDP增速 | China GDP Growth | 国家统计局 | quarterly | 季度后1-2月 |
| 2 | chinaPmi | 中国PMI | China PMI | 国家统计局 | monthly | 月底/次月初 |
| 3 | usGdp | 美国GDP增速 | US GDP Growth | BEA | quarterly | 季度后1月 |
| 4 | servicePmi | 服务业PMI | Services PMI | 国家统计局 | monthly | 月底/次月初 |

### 维度2：通胀与价格 (Inflation & Prices) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 | 频率 | 时效要求 |
|:----:|:-------|:-------|:-------|:-------|:----:|:---------|
| 1 | cpi | 中国CPI同比 | China CPI YoY | 国家统计局 | monthly | 月中/次月中旬 |
| 2 | ppi | 中国PPI同比 | China PPI YoY | 国家统计局 | monthly | 月中/次月中旬 |
| 3 | usCpi | 美国CPI同比 | US CPI YoY | BLS | monthly | 次月中旬 |
| 4 | corePce | 核心PCE | Core PCE | 美联储 | monthly | 次月末 |

### 维度3：货币与信用 (Money & Credit) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 | 频率 | 时效要求 |
|:----:|:-------|:-------|:-------|:-------|:----:|:---------|
| 1 | lpr | LPR利率 | LPR Rate | 央行 | monthly | 每月20日 |
| 2 | dr007 | DR007利率 | DR007 Rate | 货币市场 | daily | T+0 |
| 3 | m2 | M2增速 | M2 Growth | 央行 | monthly | 月中/次月中旬 |
| 4 | fedRate | 美联储利率 | Fed Funds Rate | 美联储 | daily | T+0 |

### 维度4：风险与不确定性 (Risk & Uncertainty) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 | 频率 | 时效要求 |
|:----:|:-------|:-------|:-------|:-------|:----:|:---------|
| 1 | vix | VIX恐慌指数 | VIX | CBOE | daily | T+0 |
| 2 | epu | 经济政策不确定性 | EPU | 教授研究 | monthly | 月底 |
| 3 | dollarIndex | 美元指数 | Dollar Index | ICE | daily | T+0 |
| 4 | geoRisk | 地缘风险指数 | Geopolitical Risk | 教授研究 | daily | T+0 |

### 维度5：气候与资源 (Climate & Resources) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 | 频率 | 时效要求 |
|:----:|:-------|:-------|:-------|:-------|:----:|:---------|
| 1 | oilPrice | WTI原油价格 | WTI Oil Price | EIA | daily | T+1 |
| 2 | naturalGas | 天然气价格 | Natural Gas Price | EIA | daily | T+1 |
| 3 | carbonPrice | 碳市场价格 | Carbon Price | 碳市场 | daily | T+0 |
| 4 | electricity | 用电量 | Electricity | 电网公司 | monthly | 月中 |

---

## 三、JSON Key 映射

```json
{
  "economicOutput": {
    "dimensionId": "economicOutput",
    "dimensionName": "经济产出",
    "dimensionNameEn": "Economic Output",
    "icon": "📈",
    "indicators": ["chinaGdp", "chinaPmi", "usGdp", "servicePmi"]
  },
  "inflationPrices": {
    "dimensionId": "inflationPrices",
    "dimensionName": "通胀与价格",
    "dimensionNameEn": "Inflation & Prices",
    "icon": "💰",
    "indicators": ["cpi", "ppi", "usCpi", "corePce"]
  },
  "moneyCredit": {
    "dimensionId": "moneyCredit",
    "dimensionName": "货币与信用",
    "dimensionNameEn": "Money & Credit",
    "icon": "🏦",
    "indicators": ["lpr", "dr007", "m2", "fedRate"]
  },
  "riskUncertainty": {
    "dimensionId": "riskUncertainty",
    "dimensionName": "风险与不确定性",
    "dimensionNameEn": "Risk & Uncertainty",
    "icon": "⚠️",
    "indicators": ["vix", "epu", "dollarIndex", "geoRisk"]
  },
  "climateResources": {
    "dimensionId": "climateResources",
    "dimensionName": "气候与资源",
    "dimensionNameEn": "Climate & Resources",
    "icon": "🌍",
    "indicators": ["oilPrice", "naturalGas", "carbonPrice", "electricity"]
  }
}
```

---

## 四、时效性标准（v2.0 核心）

### 数据时效等级
- 🟢 **实时** (T+0~T+1): VIX、美元指数、油价、天然气、FED利率、DR007
- 🟡 **近期** (T+7~T+30): CPI、PPI、M2、LPR、碳价、用电量
- 🔴 **滞后** (>T+30): GDP增速、PMI、核心PCE

### UI显示要求
每个指标卡片必须显示：
1. **数据日期** — 格式：`2026-05-20` 或 `2026-Q1`
2. **频率标签** — `日频/月频/季频`
3. **时效等级颜色** — 绿/黄/红 三色标识

### 数据新鲜度预警
- 数据超过频率要求的2倍时间未更新 → 标红 ⚠️
- 数据超过频率要求但未超过2倍 → 标黄 ⚠️
- 数据在正常时效内 → 标绿 ✓
