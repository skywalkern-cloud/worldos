# WorldOS 6大维度24指标完整设计

| 维度 | 指标ID | 中文名 | 英文名 | 更新频率 |
|:----:|:-------|:-------|:-------|:---------|
| **1. 经济产出** 📈 | chinaGdp | 中国GDP增速 | China GDP Growth | 低频（月） |
| | chinaPmi | 中国PMI | China PMI | 中频（月） |
| | usGdp | 美国GDP增速 | US GDP Growth | 低频（季） |
| | servicePmi | 服务业PMI | Services PMI | 中频（月） |
| **2. 通胀与价格** 💰 | cpi | 中国CPI同比 | China CPI YoY | 低频（月） |
| | ppi | 中国PPI同比 | China PPI YoY | 低频（月） |
| | usCpi | 美国CPI同比 | US CPI YoY | 低频（月） |
| | corePce | 核心PCE | Core PCE | 低频（月） |
| **3. 货币与信用** 🏦 | lpr | LPR利率 | LPR Rate | 低频（月） |
| | dr007 | DR007利率 | DR007 Rate | 高频（5分钟） |
| | m2 | M2增速 | M2 Growth | 低频（月） |
| | fedRate | 美联储利率 | Fed Funds Rate | 高频（实时） |
| **4. 风险与不确定性** ⚠️ | vix | VIX恐慌指数 | VIX | 高频（5分钟） |
| | epu | 经济政策不确定性 | EPU | 低频（月） |
| | dollarIndex | 美元指数 | Dollar Index | 高频（5分钟） |
| | geoRisk | 地缘风险指数 | Geopolitical Risk | 中频（周） |
| **5. 技术与生产力** 🔬 | aiRdRatio | AI研发占比 | AI R&D Ratio | 低频（年） |
| | aiPatentCount | AI专利数 | AI Patents | 低频（季） |
| | robotInstallBase | 工业机器人装机量 | Robot Install Base | 低频（季） |
| | quantumComputingBudget | 量子计算预算 | Quantum Budget | 低频（年） |
| **6. 气候与资源** 🌍 | oilPrice | WTI原油价格 | WTI Oil Price | 高频（15分钟） |
| | naturalGas | 天然气价格 | Natural Gas Price | 高频（15分钟） |
| | carbonPrice | 碳市场价格 | Carbon Price | 中频（日） |
| | electricity | 用电量 | Electricity | 中频（月） |

---

## 更新频率分类

| 分类 | 频率 | 指标 |
|------|------|------|
| **高频** | 5分钟-15分钟 | dr007、fedRate、VIX、美元指数、油价、天然气 |
| **中频** | 小时级-日级 | 中国PMI、服务业PMI、地缘风险、碳价格、用电量 |
| **低频** | 日级-月级 | GDP、CPI、PPI、LPR、M2、EPU、AI/机器人/量子数据 |

---

*设计时间：2026-04-03*
*设计者：龙六*
*更新：2026-04-03 添加更新频率列*