# WorldOS 6大维度设计文档

## 一、维度总览

| 维度ID | 维度名称 | 英文名 | Icon | 指标数 | 说明 |
|:------:|:---------|:-------|:----:|:------:|:-----|
| 1 | 经济产出 | Economic Output | 📈 | 4 | GDP、PMI等 |
| 2 | 通胀与价格 | Inflation & Prices | 💰 | 4 | CPI、PPI等 |
| 3 | 货币与信用 | Money & Credit | 🏦 | 4 | 利率、货币供应量 |
| 4 | 风险与不确定性 | Risk & Uncertainty | ⚠️ | 4 | VIX、EPU等 |
| 5 | 技术与生产力 | Tech & Productivity | 🔬 | 4 | AI、机器人 |
| 6 | 气候与资源 | Climate & Resources | 🌍 | 4 | 油价、碳价 |

---

## 二、指标列表（24个）

### 维度1：经济产出 (Economic Output) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 |
|:----:|:-------|:-------|:-------|:-------|
| 1 | chinaGdp | 中国GDP增速 | China GDP Growth | 国家统计局 |
| 2 | chinaPmi | 中国PMI | China PMI | 国家统计局 |
| 3 | usGdp | 美国GDP增速 | US GDP Growth | BEA |
| 4 | servicePmi | 服务业PMI | Services PMI | 国家统计局 |

### 维度2：通胀与价格 (Inflation & Prices) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 |
|:----:|:-------|:-------|:-------|:-------|
| 1 | cpi | 中国CPI同比 | China CPI YoY | 国家统计局 |
| 2 | ppi | 中国PPI同比 | China PPI YoY | 国家统计局 |
| 3 | usCpi | 美国CPI同比 | US CPI YoY | BLS |
| 4 | corePce | 核心PCE | Core PCE | 美联储 |

### 维度3：货币与信用 (Money & Credit) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 |
|:----:|:-------|:-------|:-------|:-------|
| 1 | lpr | LPR利率 | LPR Rate | 央行 |
| 2 | dr007 | DR007利率 | DR007 Rate | 货币市场 |
| 3 | m2 | M2增速 | M2 Growth | 央行 |
| 4 | fedRate | 美联储利率 | Fed Funds Rate | 美联储 |

### 维度4：风险与不确定性 (Risk & Uncertainty) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 |
|:----:|:-------|:-------|:-------|:-------|
| 1 | vix | VIX恐慌指数 | VIX | CBOE |
| 2 | epu | 经济政策不确定性 | EPU | 教授研究 |
| 3 | dollarIndex | 美元指数 | Dollar Index | ICE |
| 4 | geoRisk | 地缘风险指数 | Geopolitical Risk | 教授研究 |

### 维度5：技术与生产力 (Tech & Productivity) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 |
|:----:|:-------|:-------|:-------|:-------|
| 1 | aiRdRatio | AI研发占比 | AI R&D Ratio | 行业估算 |
| 2 | aiPatentCount | AI专利数 | AI Patents | USPTO |
| 3 | robotInstallBase | 工业机器人装机量 | Robot Install Base | IFR |
| 4 | quantumComputingBudget | 量子计算预算 | Quantum Budget | 政府公开 |

### 维度6：气候与资源 (Climate & Resources) - 4个指标

| 序号 | 指标ID | 中文名 | 英文名 | 数据源 |
|:----:|:-------|:-------|:-------|:-------|
| 1 | oilPrice | WTI原油价格 | WTI Oil Price | EIA |
| 2 | naturalGas | 天然气价格 | Natural Gas Price | EIA |
| 3 | carbonPrice | 碳市场价格 | Carbon Price | 碳市场 |
| 4 | electricity | 用电量 | Electricity | 电网公司 |

---

## 三、指标映射表（JSON Key）

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
  "techProductivity": {
    "dimensionId": "techProductivity",
    "dimensionName": "技术与生产力",
    "dimensionNameEn": "Tech & Productivity",
    "icon": "🔬",
    "indicators": ["aiRdRatio", "aiPatentCount", "robotInstallBase", "quantumComputingBudget"]
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

## 四、完整JSON数据结构

```json
{
  "dimensions": [
    {
      "id": "economicOutput",
      "name": "经济产出",
      "nameEn": "Economic Output", 
      "icon": "📈",
      "indicators": [
        {"id": "chinaGdp", "name": "中国GDP增速", "nameEn": "China GDP Growth", "value": 5.0, "unit": "%", "source": "NBS"},
        {"id": "chinaPmi", "name": "中国PMI", "nameEn": "China PMI", "value": 50.4, "unit": "", "source": "NBS"},
        {"id": "usGdp", "name": "美国GDP增速", "nameEn": "US GDP Growth", "value": 2.5, "unit": "%", "source": "BEA"},
        {"id": "servicePmi", "name": "服务业PMI", "nameEn": "Services PMI", "value": 52.0, "unit": "", "source": "NBS"}
      ]
    },
    {
      "id": "inflationPrices",
      "name": "通胀与价格",
      "nameEn": "Inflation & Prices",
      "icon": "💰",
      "indicators": [
        {"id": "cpi", "name": "中国CPI同比", "nameEn": "China CPI YoY", "value": 2.5, "unit": "%", "source": "NBS"},
        {"id": "ppi", "name": "中国PPI同比", "nameEn": "China PPI YoY", "value": -0.5, "unit": "%", "source": "NBS"},
        {"id": "usCpi", "name": "美国CPI同比", "nameEn": "US CPI YoY", "value": 3.2, "unit": "%", "source": "BLS"},
        {"id": "corePce", "name": "核心PCE", "nameEn": "Core PCE", "value": 2.9, "unit": "%", "source": "Fed"}
      ]
    },
    {
      "id": "moneyCredit",
      "name": "货币与信用",
      "nameEn": "Money & Credit",
      "icon": "🏦",
      "indicators": [
        {"id": "lpr", "name": "LPR利率", "nameEn": "LPR Rate", "value": 3.45, "unit": "%", "source": "PBOC"},
        {"id": "dr007", "name": "DR007利率", "nameEn": "DR007 Rate", "value": 1.8, "unit": "%", "source": "ChinaBond"},
        {"id": "m2", "name": "M2增速", "nameEn": "M2 Growth", "value": 8.3, "unit": "%", "source": "PBOC"},
        {"id": "fedRate", "name": "美联储利率", "nameEn": "Fed Funds Rate", "value": 5.25, "unit": "%", "source": "Fed"}
      ]
    },
    {
      "id": "riskUncertainty",
      "name": "风险与不确定性",
      "nameEn": "Risk & Uncertainty",
      "icon": "⚠️",
      "indicators": [
        {"id": "vix", "name": "VIX恐慌指数", "nameEn": "VIX", "value": 18.0, "unit": "", "source": "CBOE"},
        {"id": "epu", "name": "经济政策不确定性", "nameEn": "EPU", "value": 750, "unit": "", "source": "Baker et al."},
        {"id": "dollarIndex", "name": "美元指数", "nameEn": "Dollar Index", "value": 105.0, "unit": "", "source": "ICE"},
        {"id": "geoRisk", "name": "地缘风险指数", "nameEn": "Geopolitical Risk", "value": 85, "unit": "", "source": "Caldara et al."}
      ]
    },
    {
      "id": "techProductivity",
      "name": "技术与生产力",
      "nameEn": "Tech & Productivity",
      "icon": "🔬",
      "indicators": [
        {"id": "aiRdRatio", "name": "AI研发占比", "nameEn": "AI R&D Ratio", "value": 15.5, "unit": "%", "source": "Industry"},
        {"id": "aiPatentCount", "name": "AI专利数", "nameEn": "AI Patents", "value": 45000, "unit": "", "source": "USPTO"},
        {"id": "robotInstallBase", "name": "工业机器人装机量", "nameEn": "Robot Install Base", "value": 3500000, "unit": "台", "source": "IFR"},
        {"id": "quantumComputingBudget", "name": "量子计算预算", "nameEn": "Quantum Budget", "value": 15000000000, "unit": "USD", "source": "Gov"}
      ]
    },
    {
      "id": "climateResources",
      "name": "气候与资源",
      "nameEn": "Climate & Resources",
      "icon": "🌍",
      "indicators": [
        {"id": "oilPrice", "name": "WTI原油价格", "nameEn": "WTI Oil Price", "value": 85.0, "unit": "USD", "source": "EIA"},
        {"id": "naturalGas", "name": "天然气价格", "nameEn": "Natural Gas Price", "value": 3.5, "unit": "USD/MMBtu", "source": "EIA"},
        {"id": "carbonPrice", "name": "碳市场价格", "nameEn": "Carbon Price", "value": 80, "unit": "EUR", "source": "ETS"},
        {"id": "electricity", "name": "用电量", "nameEn": "Electricity", "value": 7500, "unit": "亿kWh", "source": "Grid"}
      ]
    }
  ]
}
```

---

*文档编制：龙六 🦞*
*日期：2026-04-03*
