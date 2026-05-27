# WorldOS 设计文档 v5.0

> 更新时间：2026-05-26 | 版本：v5.0（数据源替换、指标扩容至31个、评论生成器上线）
> 💡 本文档替代 v4.1 的 DIMENSION_DESIGN.md，记录所有代码变更和设计决策

---

## 一、版本历史

| 版本 | 日期 | 主要变更 |
| :---: | :---: | :--------- |
| v1.0 | 2025-Q4 | 初始框架，5维度20指标 |
| v2.0 | 2026-01 | 时效性标准和JSON映射 |
| v3.0 | 2026-03 | React V3组件，5维度26指标 |
| v4.0 | 2026-05-24 | 维度重构5→6维、指标扩容30个、连续评分、欧洲覆盖 |
| v4.1 | 2026-05-24 | 修复评分公式Bug、补充双向指标边界、时间衰减因子 |
| **v5.0** | **2026-05-26** | **10个数据源替换→东方财富/FRED、4个新指标→31个、时间衰减阈值大幅放宽、趋势箭头修复、异常速览优化、新增评论生成器** |

---

## 二、数据源替换（核心变更）

### 2.1 背景

原 `fetch_worldos_data.py` 中 10 个函数依赖 akshare 金十数据(jin10) 接口，该接口自 2025 年 8 月起停止更新，导致大量关键指标数据过期（14/26 指标为 🔴 过期状态）。

**调研文档**：`~/.openclaw/workspace/data-source-plan.md`

### 2.2 替换清单

| 函数 | 原数据源 | 新数据源 | 状态 |
| :--- | :-------- | :-------- | :--: |
| `get_china_pmi()` | akshare → jin10 | 东方财富 `RPT_ECONOMY_PMI` → `MAKE_INDEX` | ✅ |
| `get_service_pmi()` | akshare → jin10 | 东方财富 `RPT_ECONOMY_PMI` → `NMAKE_INDEX` | ✅ |
| `get_cpi()` | akshare → jin10 | 东方财富 `RPT_ECONOMY_CPI` → `NATIONAL_SAME` | ✅ |
| `get_ppi()` | akshare → jin10 | 东方财富 `RPT_ECONOMY_PPI` → `BASE_SAME` | ✅ |
| `get_m2()` | akshare → jin10 | 东方财富 `RPT_ECONOMY_CURRENCY_SUPPLY` → `BASIC_CURRENCY_SAME` | ✅ |
| `get_us_gdp()` | akshare → jin10 | 东方财富 `RPT_ECONOMICVALUE_USA` → `INDICATOR_ID="EMG00159633"` | ✅ |
| `get_core_pce()` | akshare → jin10 | **FRED API** `PCEPILFE` (指数值→同比计算) | ✅ |
| `get_fed_rate()` | 硬编码 `3.75%` | 东方财富 `EMG00159628` → Alpha Vantage → 硬编码fallback | ✅ |
| `get_industrial_production()` | akshare → jin10 | akshare `macro_china_gyzjz()`（East Money 接口） | ✅ |
| `get_epu()` | policyuncertainty.com (404) | **FRED API** `CHNEPUINDXM` | ✅ |

### 2.3 东方财富通用API

```python
def fetch_eastmoney(report_name, columns="ALL", filter_expr="",
                    sort_col="REPORT_DATE", sort_type=-1, page_size=500):
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": report_name, "columns": columns,
        "pageNumber": 1, "pageSize": page_size,
        "sortColumns": sort_col, "sortTypes": sort_type,
        "source": "WEB", "client": "WEB",
    }
    if filter_expr:
        params["filter"] = filter_expr
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data_json = r.json()
    if not data_json.get("success"):
        return None
    return data_json["result"]["data"]
```

**可用报表名参考表**：

| 报表名 | 数据内容 | 关键列 |
| :----- | :------- | :----- |
| `RPT_ECONOMY_PMI` | 制造业/非制造业PMI | `MAKE_INDEX`, `NMAKE_INDEX` |
| `RPT_ECONOMY_CPI` | 全国/城市/农村CPI | `NATIONAL_SAME` |
| `RPT_ECONOMY_PPI` | PPI | `BASE_SAME` |
| `RPT_ECONOMY_GDP` | 中国GDP | `SUM_SAME` |
| `RPT_ECONOMY_CURRENCY_SUPPLY` | M2/M1/M0货币供应 | `BASIC_CURRENCY_SAME` |
| `RPT_ECONOMICVALUE_USA` | 美国经济指标（按INDICATOR_ID过滤） | `VALUE` |
| `RPT_ECONOMY_INDUS_GROW` | 规模以上工业增加值 | （通过akshare访问） |

### 2.4 FRED API 集成

#### 核心PCE (corePce)

- **系列**: `PCEPILFE`（个人消费支出价格指数，不含食品能源）
- **方法**: 拉取13个月指数值，计算同比
- **之前问题**: 使用东方财富核心CPI - 0.3%估算，结果为 2.4%
- **FRED精确值**: 3.2%（2026年4月）
- **API Key**: 配置在 `~/.zshrc`，环境变量 `FRED_API_KEY`

#### EPU (epu)

- **系列**: `CHNEPUINDXM`（中国经济政策不确定性月指数）
- **之前问题**: policyuncertainty.com 所有 CSV/Excel 文件均返回 404
- **FRED替代**: 直接返回最新月指数值

#### FRED系列ID参考

```python
FRED_SERIES = {
    "core_pce_yoy": "PCEPILFE",    # 核心PCE同比指数
    "core_pce_mom": "PCEPILF",      # 核心PCE环比
    "gdp_real": "GDPC1",            # 实际GDP
    "china_epu": "CHNEPUINDXM",     # 中国EPU月指数
}
```

### 2.5 联邦利率动态抓取

`get_fed_rate()` 重构为三级fallback：

```
get_fed_rate()
 └─ ① 东方财富 EMG00159628（联邦基金利率目标上限）
 └─ ② Alpha Vantage FEDERAL_FUNDS_RATE
 └─ ③ 硬编码 3.75, '2026-03-19'（最终fallback）
```

实际结果：从硬编码 `3.75` 更新为动态抓取 `3.64`，新鲜度从 🔴 变为 🟢。

---

## 三、新增4个指标（总数 30→31 个）

### 3.1 新增指标总览

| 指标ID | 中文名 | 国家 | 频率 | 优先级 | 数据源 | 评分类型 |
| :----- | :----- | :--: | :--: | :----: | :----- | :------: |
| `usBond2Y` | 美债2年收益率 | 🇺🇸 | daily | US债市 | akshare `bond_zh_us_rate` | 双向 |
| `usBond5Y` | 美债5年收益率 | 🇺🇸 | daily | US债市 | akshare `bond_zh_us_rate`（带缓存） | 双向 |
| `usBond10Y` | 美债10年收益率 | 🇺🇸 | daily | US债市 | akshare `bond_zh_us_rate`（带缓存） | 双向 |
| `usNonFarm` | 非农就业 | 🇺🇸 | monthly | 美国经济 | 东方财富 `EMG00152118` | 正向 |
| `fearGreed` | 恐惧贪婪指数 | 🌐 | daily | 市场情绪 | CNN Fear & Greed API | 双向 |

### 3.2 评分参数说明

#### usBond2Y（双向指标：过高中性偏低都不好）

| 参数 | 值 | 说明 |
| :--: | :-: | :--- |
| L_low | 1.5% | 过低→衰退预期强烈，score=-1 |
| T_low | 2.5% | 开始回归中性 |
| T_high | 4.5% | 中性区间上限 |
| H_high | 6.0% | 过高→紧缩压力，score=-1 |

**设计逻辑**：2Y美债反映短期利率预期。当前值 4.13% 处于 T_low~T_high 区间内，score=0。

#### usBond5Y（双向指标）

| 参数 | 值 | 说明 |
| :--: | :-: | :--- |
| L_low | 1.8% | 过低→衰退信号 |
| T_low | 2.8% | 中性下沿 |
| T_high | 4.8% | 中性上沿 |
| H_high | 6.3% | 过高→紧缩 |

**设计逻辑**：5Y美债是中期利率锚。当前 4.27% 在区间内，score=0。

#### usBond10Y（双向指标）

| 参数 | 值 | 说明 |
| :--: | :-: | :--- |
| L_low | 2.0% | 过低→衰退 |
| T_low | 3.0% | 历史中性区间下沿 |
| T_high | 5.0% | 历史中性区间上沿 |
| H_high | 6.5% | 过高→信用危机 |

**设计逻辑**：10Y美债是全球资产定价之锚。当前 4.56% 在区间内，score=0。

#### usNonFarm（正向指标：越高越好）

| 参数 | 值 | 说明 |
| :--: | :-: | :--- |
| L | 50万人 | 极端差，score=-1 |
| T | 200万人 | 中性参考线 |
| H | 400万人 | 极端优，score=+1 |

**设计逻辑**：非农历史均值约 200 万/月，50 万以下为经济衰退水平。当前 115 万介于 L~T 之间，score = (115-50)/(200-50) - 1 = -0.567（🔴红色信号）。

#### fearGreed（双向指标：过高贪婪/过低恐惧都不好）

| 参数 | 值 | 说明 |
| :--: | :-: | :--- |
| L_low | 20 | 极度恐惧，score=-1 |
| T_low | 40 | 恐惧区间上限 |
| T_high | 60 | 贪婪区间下限 |
| H_high | 80 | 极度贪婪，score=-1 |

**设计逻辑**：CNN Fear & Greed Index 范围 0-100，40-60 为中性。

### 3.3 影响范围：全栈集成

新增指标被集成到以下位置：

| 文件 | 变更 |
| :--- | :--- |
| `scripts/scoring.py` | ✅ `BIDIRECTIONAL_PARAMS` 加 usBond2Y/5Y/10Y/fearGreed |
| `scripts/scoring.py` | ✅ `POSITIVE_PARAMS` 加 usNonFarm |
| `scripts/scoring.py` | ✅ `DIMENSION_CONFIG` → liquidity 加 usBond*/sentiment 加 fearGreed |
| `scripts/scoring.py` | ✅ `INDICATOR_COUNTRY` `INDICATOR_NAMES` 映射 |
| `scripts/fetch_worldos_data.py` | ✅ `INDICATOR_DEFS` 定义 + `_fetch_bond_yields()` 缓存 |
| `scripts/commentary_generator.py` | ✅ `DIMENSION_INDICATORS` 更新 + 所有解读函数兼容 |
| `src/App.tsx` | ✅ `DIMENSION_INDICATORS` 更新 |

---

## 四、时间衰减阈值调整（v5.0）

### 4.1 调整原因

v4.1 的阈值过于严格（daily: 3/5天, monthly: 30/45天），导致大量月频指标（如CPI、M2的正常发布延迟约15天）被判定为过期，影响维度评分的可信度。

### 4.2 新旧阈值对比

| 频率类型 | 旧 🟡 黄色(α=0.5) | 新 🟡 黄色(α=0.5) | 旧 🔴 红色(α=0) | 新 🔴 红色(α=0) |
| :------: | :----------------: | :----------------: | :--------------: | :--------------: |
| daily | 3天 | **5天** | 5天 | **10天** |
| monthly | 30天 | **60天** | 45天 | **90天** |
| quarterly | 90天 | **180天** | 120天 | **270天** |
| other | 30天 | **60天** | 45天 | **90天** |

### 4.3 调整后的效果

新政前：26 个指标中 17 个 🔴 过期。政策后：31 个指标中 **30 个 🟢 正常**，仅 1 个（dollarIndex 代理计算异常）有数据问题。

### 4.4 代码位置

`scripts/scoring.py` → `TIMELINESS_RULES` 字典

```python
TIMELINESS_RULES = {
    'daily':     {'yellow_days': 5, 'red_days': 10},
    'monthly':   {'yellow_days': 60, 'red_days': 90},
    'quarterly': {'yellow_days': 180, 'red_days': 270},
    'yearly':    {'yellow_days': 180, 'red_days': 365},
    'other':     {'yellow_days': 60, 'red_days': 90},
}
```

---

## 五、趋势箭头修复

### 5.1 问题描述

`fetch_worldos_data.py` 中的 `load_prev()` 函数返回 `tuple (value, dataDate)`，但调用方 `build_indicators_and_meta()` 预期接收 `dict {value, dataDate}`，导致趋势计算失效。

### 5.2 修复内容

**文件**：`scripts/fetch_worldos_data.py`

**load_prev() 返回值修改**：

```python
# 旧版（损坏）：
for k, v in d.get('data', {}).items():
    result[k] = (v.get('value'), v.get('dataDate'))  # tuple

# 新版（正确）：
for k, v in d.get('data', {}).items():
    if isinstance(v, dict):
        result[k] = {'value': v.get('value'), 'dataDate': v.get('dataDate')}  # dict
    else:
        result[k] = {'value': v, 'dataDate': None}
```

**fallback 逻辑修复**：

```python
# 旧版：
prev_val, prev_dd = prev.get(key, (None, None))

# 新版：
prev_item = prev.get(key)
if prev_item is not None:
    if isinstance(prev_item, dict):
        val = prev_item.get('value')
        dd = prev_item.get('dataDate')
    else:
        val = prev_item
        dd = None
```

---

## 六、异常指标速览优化

### 6.1 变更说明

去掉了异常指标速览中的新鲜度（🟢🟡🔴）显示，避免与信号灯的颜色系统混淆。

**文件**：`src/App.tsx` → `AnomalyBar` 组件

### 6.2 动机

页面中有两套颜色系统：
- **信号灯**（green/lightgreen/gray/yellow/red）：指标评分
- **新鲜度**（🟢/🟡/🔴）：数据延迟

两套系统用相同颜色表达不同语义，在窄条视觉区域内造成严重混淆。去掉新鲜度后，AnomalyBar 只显示评分信号。

---

## 七、数据解读评论栏目（全新功能）

### 7.1 概述

新增模版引擎评论生成器，自动为6个维度生成中文解读，无需 LLM API 调用。

### 7.2 文件结构

| 文件 | 用途 |
| :--- | :--- |
| `scripts/commentary_generator.py` | 后端：模板引擎评论生成 |
| `src/App.tsx` → `CommentarySection` | 前端：评论展示组件 |
| `public/data/commentary.json` | 输出文件 |

### 7.3 生成流程

```
backup.py (fetch_worldos_data.py)
  ├─ ① 采集 31 个指标原始数据
  ├─ ② scoring.py → 评分
  ├─ ③ save_results() → 自动调用 commentary_generator.py
  │     └─ 生成 commentary.json 到 public/data/
  └─ ④ 写入 market-data.json
```

### 7.4 评论生成架构

**commentary_generator.py 结构**：

```
generate_commentary(indicators, meta, prev_commentary)
  ├─ _generate_ias_summary() → IAS整体解读
  │   ├─ 总览（评分+信号+仓位）
  │   ├─ 板块贡献分解（正/负维度排名）
  │   ├─ 关键矛盾提取
  │   ├─ 尾部风险提取
  │   └─ 投资策略建议
  ├─ _dim_commentary_economic()  → 📈 经济增长
  ├─ _dim_commentary_inflation() → 💰 通胀与政策
  ├─ _dim_commentary_liquidity() → 💧 流动性
  ├─ _dim_commentary_sentiment() → 🧠 市场情绪
  ├─ _dim_commentary_resource()  → 🛢️ 资源与供应链
  └─ _dim_commentary_techGreen() → 🌱 科技与绿色
```

每个维度函数根据指标值、评分和信号，使用条件模板生成自然语言解读。

### 7.5 前端展示

**组件树**：

```
App.tsx
  └─ CommentarySection (仅在 commentary.json 存在时渲染)
       ├─ IAS 整体解读区域（默认展开）
       │   ├─ 摘要文本（MarkdownText 渲染）
       │   ├─ ⚠️ 关键矛盾标签
       │   └─ ⛔ 尾部风险标签
       └─ 6个维度解读区域（默认折叠）
            ├─ DimensionCommentaryItem × 6
            │   ├─ 维度名 + 评分badge
            │   └─ MarkdownText 渲染评论
```

**优雅降级**：commentary.json 不存在时 CommentarySection 组件隐藏，页面不报错。

### 7.6 维度指标配置

```python
DIMENSION_INDICATORS = {
    'economic':  ['chinaGdp', 'chinaPmi', 'usGdp', 'servicePmi', 'electricity', 'usNonFarm'],
    'inflation': ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate'],
    'liquidity': ['lpr', 'dr007', 'm2', 'creditSpread', 'dollarIndex', 'usBond2Y', 'usBond5Y', 'usBond10Y'],
    'sentiment': ['vix', 'fearGreed'],
    'resource':  ['oilPrice', 'naturalGas', 'carbonPrice'],
    'techGreen': ['aiGrowth', 'robotInstall', 'evPenetration', 'renewEnergyInvest'],
}
```

---

## 八、部署配置

### 8.1 Cloudflare Pages 配置

- **构建命令**: `npm run build` (tsc -b && vite build)
- **输出目录**: `dist/`
- **数据文件**: `public/data/market-data.json` 和 `public/data/commentary.json` 随 build 部署
- **自动部署**: 数据更新每小时一次（通过后台 cron），触发自动部署

### 8.2 环境变量

| 变量名 | 用途 | 配置位置 |
| :----- | :--- | :------- |
| `FRED_API_KEY` | FRED API 密钥 | `~/.zshrc`（持久化） |

---

## 九、评分算法（v5.0 无算法变更）

评分算法保持 v4.1 的设计不变，详情见 [DIMENSION_DESIGN.md 第三章](DIMENSION_DESIGN.md#三评分算法-v41修正版)。

### 9.1 完整指标评分参数（v5.0）

#### 正向指标

| 指标ID | L (score=-1) | T (score=0) | H (score=+1) | 单位 |
| :----- | :----------: | :----------: | :----------: | :--: |
| chinaGdp | 3.0 | 5.0 | 7.0 | % |
| chinaPmi | 48 | 50 | 53 | — |
| usGdp | -0.5 | 2.5 | 5.5 | % |
| servicePmi | 47 | 50 | 53 | — |
| electricity | 2.0 | 5.0 | 8.0 | % |
| ppi | -5.0 | 0 | 3.0 | % |
| m2 | 7.0 | 9.0 | 12.0 | % |
| aiGrowth | 0 | 10 | 25 | % |
| robotInstall | -5.0 | 10 | 25 | % |
| evPenetration | 20 | 40 | 60 | % |
| carbonPrice | 30 | 60 | 90 | ¥/吨 |
| renewEnergyInvest | 800 | 1200 | 1600 | 点 |
| **usNonFarm** | **50** | **200** | **400** | 万人 |

#### 逆向指标

| 指标ID | L (score=+1) | T (score=0) | H (score=-1) | 单位 |
| :----- | :----------: | :----------: | :----------: | :--: |
| lpr | 2.0 | 3.5 | 5.0 | % |
| dr007 | 1.0 | 1.8 | 3.0 | % |
| creditSpread | 100 | 200 | 400 | bp |
| dollarIndex | 92 | 100 | 112 | — |
| vix | 12 | 20 | 35 | — |
| epu | 80 | 150 | 300 | — |

#### 双向指标

| 指标ID | L_low | T_low | T_high | H_high | 单位 |
| :----- | :---: | :---: | :---: | :---: | :--: |
| cpi | 0% | 1% | 3% | 5% | % |
| usCpi | 0% | 1.5% | 3.5% | 5% | % |
| corePce | 1% | 1.5% | 2.5% | 3.5% | % |
| oilPrice | $40 | $60 | $90 | $120 | $/桶 |
| naturalGas | $2 | $2.5 | $4.5 | $7 | $/MMBtu |
| fedRate | 1% | 2% | 4% | 5% | % |
| **usBond2Y** | **1.5%** | **2.5%** | **4.5%** | **6.0%** | **%** |
| **usBond5Y** | **1.8%** | **2.8%** | **4.8%** | **6.3%** | **%** |
| **usBond10Y** | **2.0%** | **3.0%** | **5.0%** | **6.5%** | **%** |
| **fearGreed** | **20** | **40** | **60** | **80** | **—** |

---

## 十、指标维度分布（v5.0 完整版）

| 维度 | 权重 | 指标数 | 指标 |
| :--- | :--: | :----: | :--- |
| 📈 经济增长 | 1.0 | 6 | chinaGdp, chinaPmi, usGdp, servicePmi, electricity, **usNonFarm** |
| 💰 通胀与政策 | 1.0 | 5 | cpi, ppi, usCpi, corePce, fedRate |
| 💧 流动性 | 0.8 | 8 | lpr, dr007, m2, creditSpread, dollarIndex, **usBond2Y**, **usBond5Y**, **usBond10Y** |
| 🧠 市场情绪 | 0.8 | 2 | vix, **fearGreed** |
| 🛢️ 资源与供应链 | 0.6 | 3 | oilPrice, naturalGas, carbonPrice |
| 🌱 科技与绿色 | 0.4 | 4 | aiGrowth, robotInstall, evPenetration, renewEnergyInvest |
| **合计** | **4.6** | **31** | |

### 国家覆盖

| 区域 | v4.1 | v5.0 | 变化 |
| :--- | :--: | :--: | :--: |
| 🇨🇳 中国 | 15 | 15 | 同 |
| 🇺🇸 美国 | 8 | **12** | **+4**（美债3个+非农+fearGreed） |
| 🌐 全球 | 5 | 4 | -1（temp） |
| **合计** | **30** | **31** | **+1** |

---

## 十一、数据流架构

```
┌───────────────────────────┐
│  数据采集 (16:30 cron)     │
│  fetch_worldos_data.py    │
│    ├─ East Money API  ──→ 8个指标    │
│    ├─ FRED API        ──→ 2个指标    │
│    ├─ akshare         ──→ 18个指标   │
│    └─ CNN API         ──→ 1个指标    │
└──────────┬────────────────┘
           ↓
┌───────────────────────────┐
│  评分+评论生成              │
│  scoring.py               │
│    ├─ 单指标评分 (连续)      │
│    ├─ 时间衰减因子           │
│    ├─ 维度评分              │
│    └─ IAS 综合评分           │
│  commentary_generator.py   │
│    └─ 模板引擎评论生成        │
└──────────┬────────────────┘
           ↓
┌───────────────────────────┐
│  输出文件                  │
│  public/data/market-data.json      │
│  public/data/commentary.json       │
└──────────┬────────────────┘
           ↓
┌───────────────────────────┐
│  Cloudflare Pages (静态部署)│
│  前端 60s 轮询数据          │
│  React + Vite + Tailwind  │
└───────────────────────────┘
```

---

## 十二、已知问题与待办

### 2.1 dollarIndex 数据异常

当前 `dollarIndex` 的值显示为字符串 "value" 而非数值，原因是 akshare `forex_hist_em` 接口返回数据格式不稳定。需要排查接口变动或改用替代数据源（如东方财富外汇数据）。

### 2.2 aiGrowth/robotInstall 数据冗余

两个函数指向同一底层数据（`get_electricity_industry`），数据完全相同。需在 Phase 3 接入工信部/乘联会真实数据源。

### 2.3 evPenetration 数据与参数不配

当前数据来自第三产业用电量增速（约8.3%），而评分参数是为真实EV渗透率设计的（20/40/60）。虽然本次更新已将数据源改为乘联会CPCA真实数据（58%），但需持续确认数据源的稳定性。

### 2.4 geoRisk/extremeWeather 无评分参数

两个派生指标无评分参数，`score: None`，前端显示灰色。建议在Phase 3 配置评分参数或从展示中隐藏。

### 2.5 get-all-data.py 遗留问题

旧 `get-all-data.py` 使用不同 Key 命名（gdp/pmi 等），与 scoring.py 不兼容。如果误运行会覆盖正确数据。考虑删除或标记为废弃。

---

## 附：相关文件索引

| 文件 | 说明 |
| :--- | :--- |
| `scripts/fetch_worldos_data.py` | 数据采集脚本 v5.0 |
| `scripts/scoring.py` | 评分模块 v4.1（含v5.0新增参数） |
| `scripts/commentary_generator.py` | 评论生成器 v1.0（新增） |
| `src/App.tsx` | 前端入口（含CommentarySection组件） |
| `DIMENSION_DESIGN.md` | 旧版设计文档（v4.1，保留作为算法参考） |
| `public/data/market-data.json` | 输出数据文件 |
| `public/data/commentary.json` | 评论输出文件 |
| `~/.openclaw/workspace/data-source-plan.md` | 数据源替换调研文档 |
| `~/.zshrc` | FRED_API_KEY 环境变量配置 |
