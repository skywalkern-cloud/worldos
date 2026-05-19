// 投资监控仪表盘 - 数据层 v6
// 龙六负责 - 30指标体系v3.0（8维度30指标）

// 国家标签类型
export type CountryTag = '🇨🇳' | '🇺🇸' | '🌐';

// 通用带国家标签的指标
export interface LabeledMetric {
  value: number | string | "NA";
  country: CountryTag;
  // 扩展字段
  date?: string;
  dateLabel?: string;
  yoy?: number;
  yoyLabel?: string;
  mom?: number;
  momLabel?: string;
  // 指标说明
  definition?: string;
  source?: string;
  frequency?: string;
}

// 完整30个指标数据结构（v3.0精简版）
export interface MetricData {
  // 维度1: 宏观经济（11个）
  gdp: LabeledMetric;           // 1. GDP增速 % 🇨🇳
  pmi: LabeledMetric;           // 2. 制造业PMI 🇨🇳
  servicePmi: LabeledMetric;   // 3. 服务业PMI 🇨🇳
  cpi: LabeledMetric;           // 4. CPI同比 % 🇨🇳
  ppi: LabeledMetric;           // 5. PPI % 🇨🇳
  unemployment: LabeledMetric; // 6. 失业率 % 🇨🇳
  nonfarm: LabeledMetric;       // 7. 非农就业 万人 🇺🇸
  corePCE: LabeledMetric;       // 8. 核心PCE % 🇺🇸
  m2: LabeledMetric;           // 9. M2增速 % 🇨🇳
  socialFinance: LabeledMetric;// 10. 社融增速 % 🇨🇳
  interest: LabeledMetric;      // 11. LPR利率 % 🇨🇳
  
  // 维度2: 地缘政治（1个）
  epu: LabeledMetric;           // 12. EPU指数 🌐
  
  // 维度3: 生产生活（3个）
  electricity: LabeledMetric;  // 13. 工业用电量 % 🇨🇳
  retail: LabeledMetric;       // 14. 社会零售 % 🇨🇳
  property: LabeledMetric;     // 15. 房地产销售 % 🇨🇳
  
  // 维度4: 流动性（6个）
  northbound: LabeledMetric;    // 16. 北向资金 亿 🇨🇳
  southbound: LabeledMetric;    // 17. 南向资金 亿 🇨🇳
  fedBalance: LabeledMetric;    // 18. 美联储资产负债表 万亿$ 🇺🇸
  dollarIndex: LabeledMetric;   // 19. 美元指数 🌐
  cny: LabeledMetric;          // 20. 离岸人民币 🇨🇳
  us10y: LabeledMetric;        // 21. 10年美债收益率 % 🇺🇸
  
  // 维度5: 市场情绪（5个）
  vix: LabeledMetric;          // 22. VIX恐慌指数 🇺🇸
  margin: LabeledMetric;       // 23. 融资余额 亿 🇨🇳
  turnover: LabeledMetric;     // 24. 两市成交额 亿 🇨🇳
  fundPosition: LabeledMetric; // 25. 机构仓位 % 🇨🇳
  etfFlow: LabeledMetric;     // 26. ETF申赎 亿 🇨🇳
  
  // 维度6: 供应链（3个）
  bdi: LabeledMetric;           // 27. BDI指数 🌐
  export: LabeledMetric;       // 28. 中国出口 % 🇨🇳
  oil: LabeledMetric;          // 29. 原油价格 $ 🌐
  
  // 维度7: 人口结构（1个）
  leverageRate: LabeledMetric;  // 30. 居民杠杆率 % 🇨🇳
  
  // 维度8: 尾部风险（1个）
  foodIndex: LabeledMetric;     // 30. 粮食价格指数 🌐 (实际是30个指标)
}

// 30指标默认数据（v3.0精简版）
export const defaultData: MetricData = {
  // 维度1: 宏观经济（11个）
  gdp: { value: 5.0, country: '🇨🇳', dateLabel: '-', yoyLabel: '-', momLabel: '-' },
  pmi: { value: 50.6, country: '🇨🇳' },
  servicePmi: { value: 51.0, country: '🇨🇳' },
  cpi: { value: 0.8, country: '🇨🇳' },
  ppi: { value: -2.5, country: '🇨🇳' },
  unemployment: { value: 5.3, country: '🇨🇳' },
  nonfarm: { value: 25, country: '🇺🇸' },
  corePCE: { value: 2.8, country: '🇺🇸' },
  m2: { value: 7.2, country: '🇨🇳' },
  socialFinance: { value: 9.2, country: '🇨🇳' },
  interest: { value: 3.45, country: '🇨🇳' },
  
  // 维度2: 地缘政治（1个）
  epu: { value: 125, country: '🌐' },
  
  // 维度3: 生产生活（3个）
  electricity: { value: 5.2, country: '🇨🇳' },
  retail: { value: 3.1, country: '🇨🇳' },
  property: { value: -8.5, country: '🇨🇳' },
  
  // 维度4: 流动性（6个）
  northbound: { value: 15.2, country: '🇨🇳' },
  southbound: { value: 8.3, country: '🇨🇳' },
  fedBalance: { value: 7.2, country: '🇺🇸' },
  dollarIndex: { value: 104.5, country: '🌐' },
  cny: { value: 7.28, country: '🇨🇳' },
  us10y: { value: 4.15, country: '🇺🇸' },
  
  // 维度5: 市场情绪（5个）
  vix: { value: 18.5, country: '🇺🇸' },
  margin: { value: 15200, country: '🇨🇳' },
  turnover: { value: 8200, country: '🇨🇳' },
  fundPosition: { value: 65, country: '🇨🇳' },
  etfFlow: { value: 5.2, country: '🇨🇳' },
  
  // 维度6: 供应链（3个）
  bdi: { value: 1850, country: '🌐' },
  export: { value: 5.2, country: '🇨🇳' },
  oil: { value: 78.5, country: '🌐' },
  
  // 维度7: 人口结构（1个）
  leverageRate: { value: 62.5, country: '🇨🇳' },
  
  // 维度8: 尾部风险（1个）
  foodIndex: { value: 105, country: '🌐' },
};

// 预警状态类型
export type AlertStatus = 'green' | 'yellow' | 'orange' | 'red';

// 辅助函数：获取LabeledMetric的数值
const getNumValue = (metric: { value: number | string | "NA" }): number => {
  const v = metric.value;
  return typeof v === 'number' ? v : 0;
};

// 根据文档计算综合预警状态
export function calculateAlertStatus(data: MetricData): AlertStatus {
  const vixVal = getNumValue(data.vix);
  const pmiVal = getNumValue(data.pmi);
  const servicePmiVal = getNumValue(data.servicePmi);
  const propertyVal = getNumValue(data.property);
  const northboundVal = getNumValue(data.northbound);
  const epuVal = getNumValue(data.epu);
  const retailVal = getNumValue(data.retail);
  const unemploymentVal = getNumValue(data.unemployment);
  const oilVal = getNumValue(data.oil);
  const leverageVal = getNumValue(data.leverageRate);
  const corePCEVal = getNumValue(data.corePCE);
  
  // 红色预警条件（紧急）
  if (vixVal > 30 || propertyVal < -15) return 'red';
  
  // 橙色预警条件（重要）
  if (pmiVal < 48 || pmiVal > 52 || servicePmiVal < 48 || servicePmiVal > 52 || 
      northboundVal < -50 || unemploymentVal > 6 || oilVal > 120 || corePCEVal > 4) return 'orange';
  
  // 黄色预警条件（关注）
  if (vixVal > 25 || epuVal > 200 || retailVal < 0 || leverageVal > 70) return 'yellow';
  
  // 绿色正常
  return 'green';
}

// 获取状态颜色
export function getStatusColor(status: AlertStatus): string {
  switch (status) {
    case 'red': return '#EF4444';
    case 'orange': return '#F59E0B';
    case 'yellow': return '#F59E0B';
    case 'green': return '#10B981';
  }
}

// 各维度独立预警状态计算
export function getDimensionStatus(data: MetricData, dimension: string): AlertStatus {
  const getNum = (metric: { value: number | string | "NA" }): number => {
    const v = metric.value;
    return typeof v === 'number' ? v : 0;
  };
  switch (dimension) {
    case 'macro':
      const pmiVal = getNum(data.pmi);
      const servicePmiVal = getNum(data.servicePmi);
      const cpiVal = getNum(data.cpi);
      const unemploymentVal = getNum(data.unemployment);
      const corePCEVal = getNum(data.corePCE);
      
      if (pmiVal < 45 || pmiVal > 55 || servicePmiVal < 45 || servicePmiVal > 55) return 'red';
      if (pmiVal < 48 || pmiVal > 52 || servicePmiVal < 48 || servicePmiVal > 52) return 'orange';
      if (cpiVal > 5 || corePCEVal > 4) return 'orange';
      if (unemploymentVal > 6) return 'orange';
      if (cpiVal > 3 || unemploymentVal > 5.5) return 'yellow';
      return 'green';
    
    case 'geo':
      const epuVal = getNum(data.epu);
      if (epuVal > 300) return 'red';
      if (epuVal > 200) return 'orange';
      if (epuVal > 150) return 'yellow';
      return 'green';
    
    case 'production':
      const propVal = getNum(data.property);
      const elecVal = getNum(data.electricity);
      const retailVal = getNum(data.retail);
      
      if (propVal < -15) return 'red';
      if (elecVal < -5) return 'orange';
      if (retailVal < -3) return 'orange';
      if (propVal < -10) return 'orange';
      if (propVal < 0 || retailVal < 0) return 'yellow';
      return 'green';
    
    case 'liquidity':
      const nbVal = getNum(data.northbound);
      const dollarVal = getNum(data.dollarIndex);
      const cnyVal = getNum(data.cny);
      const us10yVal = getNum(data.us10y);
      
      if (nbVal < -30) return 'red';
      if (nbVal < -10) return 'orange';
      if (dollarVal > 110 || cnyVal > 7.5 || us10yVal > 5) return 'orange';
      if (nbVal < 0 || dollarVal > 105) return 'yellow';
      return 'green';
    
    case 'sentiment':
      const vixVal = getNum(data.vix);
      const turnoverVal = getNum(data.turnover);
      
      if (vixVal > 30) return 'red';
      if (vixVal > 25) return 'orange';
      if (turnoverVal < 5000) return 'yellow';
      if (vixVal > 20) return 'yellow';
      return 'green';
    
    case 'supply':
      const bdiVal = getNum(data.bdi);
      const exportVal = getNum(data.export);
      
      if (bdiVal < 500) return 'red';
      if (bdiVal < 1000) return 'orange';
      if (exportVal < 0) return 'orange';
      if (exportVal < 3) return 'yellow';
      return 'green';
    
    case 'population':
      const leverageVal2 = getNum(data.leverageRate);
      
      if (leverageVal2 > 70) return 'orange';
      if (leverageVal2 > 65) return 'yellow';
      return 'green';
    
    case 'tail':
      const oilVal2 = getNum(data.oil);
      const foodVal = getNum(data.foodIndex);
      
      if (oilVal2 > 120) return 'red';
      if (oilVal2 > 100) return 'orange';
      if (foodVal > 120) return 'orange';
      if (oilVal2 > 85) return 'yellow';
      return 'green';
    
    default:
      return 'green';
  }
}