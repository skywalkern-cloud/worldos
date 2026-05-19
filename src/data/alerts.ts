// 投资监控仪表盘 - 预警阈值逻辑 + 三级预警 + 投资建议
// 龙七负责完善

import type { MetricData, AlertStatus } from '../data/marketData';

// ==================== 预警阈值定义 ====================

// 维度1: 宏观经济阈值
export const macroThresholds = {
  pmi: { red: [45, 55], yellow: [48, 52], green: [48, 52] },
  cpi: { red: [1, 5], yellow: [1, 3], green: [1, 3] },
  interest: { red: null, yellow: null, green: null }, // 利率暂无阈值
};

// 维度2: 地缘政治阈值
export const geoThresholds = {
  epu: { red: 300, yellow: 200, green: 200 },
};

// 维度3: 生产生活阈值
export const productionThresholds = {
  electricity: { red: -5, yellow: 0, green: 0 },
  retail: { red: -3, yellow: 0, green: 0 },
  property: { red: -15, yellow: -5, green: 0 },
};

// 维度4: 流动性阈值
export const liquidityThresholds = {
  northbound: { red: -30, yellow: -10, green: 0 },
  dollarIndex: { red: null, yellow: null, green: null },
  cny: { red: null, yellow: null, green: null },
  us10y: { red: null, yellow: null, green: null },
};

// 维度5: 市场情绪阈值
export const sentimentThresholds = {
  vix: { red: 30, yellow: 25, green: 25 },
  margin: { red: null, yellow: null, green: null },
  turnover: { red: null, yellow: null, green: null },
};

// ==================== 三级预警计算 ====================

export type ThreeLevelAlert = 'red' | 'orange' | 'yellow' | 'green';

// 辅助函数：获取LabeledMetric的数值
const getNumValue = (metric: { value: number | string | "NA" }): number => {
  const v = metric.value;
  return typeof v === 'number' ? v : 0;
};

// 计算维度整体预警状态（取最严重的）
export function calculateDimensionAlert(data: MetricData): Array<{ status: AlertStatus; threeLevel: ThreeLevelAlert; reason: string }> {
  const results: Array<{ status: AlertStatus; threeLevel: ThreeLevelAlert; reason: string }> = [];
  const pmiVal = getNumValue(data.pmi);
  const epuVal = getNumValue(data.epu);
  const propertyVal = getNumValue(data.property);
  const northboundVal = getNumValue(data.northbound);
  const vixVal = getNumValue(data.vix);
  const oilVal = getNumValue(data.oil);
  
  // 维度1: 宏观经济
  if (pmiVal < 45 || pmiVal > 55) {
    results.push({ status: 'red', threeLevel: 'red', reason: `PMI=${pmiVal} 极端区域` });
  } else if (pmiVal < 48 || pmiVal > 52) {
    results.push({ status: 'orange', threeLevel: 'orange', reason: `PMI=${pmiVal} 偏热/偏冷` });
  } else {
    results.push({ status: 'green', threeLevel: 'green', reason: `PMI=${pmiVal} 正常` });
  }
  
  // 维度2: 地缘政治
  if (epuVal > 300) {
    results.push({ status: 'red', threeLevel: 'red', reason: `EPU=${epuVal} 极度不确定` });
  } else if (epuVal > 200) {
    results.push({ status: 'orange', threeLevel: 'orange', reason: `EPU=${epuVal} 高度不确定` });
  } else if (epuVal > 150) {
    results.push({ status: 'yellow', threeLevel: 'yellow', reason: `EPU=${epuVal} 中度不确定` });
  } else {
    results.push({ status: 'green', threeLevel: 'green', reason: `EPU=${epuVal} 正常` });
  }
  
  // 维度3: 生产生活 - 房地产
  if (propertyVal < -15) {
    results.push({ status: 'red', threeLevel: 'red', reason: `房地产=${propertyVal}% 危机` });
  } else if (propertyVal < -5) {
    results.push({ status: 'orange', threeLevel: 'orange', reason: `房地产=${propertyVal}% 低迷` });
  } else if (propertyVal < 0) {
    results.push({ status: 'yellow', threeLevel: 'yellow', reason: `房地产=${propertyVal}% 下降` });
  } else {
    results.push({ status: 'green', threeLevel: 'green', reason: `房地产=${propertyVal}% 正增长` });
  }
  
  // 维度4: 流动性 - 北向资金
  if (northboundVal < -30) {
    results.push({ status: 'red', threeLevel: 'red', reason: `北向=${northboundVal}亿 大幅流出` });
  } else if (northboundVal < -10) {
    results.push({ status: 'orange', threeLevel: 'orange', reason: `北向=${northboundVal}亿 净流出` });
  } else if (northboundVal < 0) {
    results.push({ status: 'yellow', threeLevel: 'yellow', reason: `北向=${northboundVal}亿 小幅流出` });
  } else {
    results.push({ status: 'green', threeLevel: 'green', reason: `北向=${northboundVal}亿 净流入` });
  }
  
  // 维度5: 市场情绪 - VIX
  if (vixVal > 30) {
    results.push({ status: 'red', threeLevel: 'red', reason: `VIX=${vixVal} 极度恐慌` });
  } else if (vixVal > 25) {
    results.push({ status: 'orange', threeLevel: 'orange', reason: `VIX=${vixVal} 恐慌` });
  } else if (vixVal > 20) {
    results.push({ status: 'yellow', threeLevel: 'yellow', reason: `VIX=${vixVal} 波动` });
  } else {
    results.push({ status: 'green', threeLevel: 'green', reason: `VIX=${vixVal} 平稳` });
  }
  
  // 维度10: 尾部风险 - 原油
  if (oilVal > 120) {
    results.push({ status: 'red', threeLevel: 'red', reason: `原油=${oilVal}$ 供应危机` });
  } else if (oilVal > 100) {
    results.push({ status: 'orange', threeLevel: 'orange', reason: `原油=${oilVal}$ 高位` });
  } else if (oilVal > 85) {
    results.push({ status: 'yellow', threeLevel: 'yellow', reason: `原油=${oilVal}$ 偏高` });
  } else {
    results.push({ status: 'green', threeLevel: 'green', reason: `原油=${oilVal}$ 正常` });
  }
  
  return results;
}

// ==================== 投资建议 ====================

export type InvestmentCycle = '复苏' | '过热' | '滞胀' | '衰退' | '不确定';

export interface InvestmentAdvice {
  cycle: InvestmentCycle;
  stockRatio: number;
  bondRatio: number;
  cashRatio: number;
  recommendedSectors: string[];
  reason: string;
}

// 判断经济周期并给出投资建议
export function getInvestmentAdvice(data: MetricData): InvestmentAdvice {
  // 简化判断逻辑（实际需要更复杂模型）
  const pmiVal = getNumValue(data.pmi);
  const propertyVal = getNumValue(data.property);
  const cpiVal = getNumValue(data.cpi);
  
  const isRecovering = pmiVal > 50 && pmiVal < 52 && propertyVal > -5;
  const isOverheating = pmiVal > 52 && propertyVal > 0;
  const isStagflating = pmiVal < 50 && cpiVal > 3;
  const isRecession = pmiVal < 48 || propertyVal < -15;
  
  if (isOverheating) {
    return {
      cycle: '过热',
      stockRatio: 60,
      bondRatio: 20,
      cashRatio: 20,
      recommendedSectors: ['能源', '材料', '工业', '可选消费'],
      reason: '经济过热期：通胀升温，利好周期股',
    };
  } else if (isStagflating) {
    return {
      cycle: '滞胀',
      stockRatio: 30,
      bondRatio: 30,
      cashRatio: 40,
      recommendedSectors: ['必需消费', '医药', '黄金'],
      reason: '滞胀期：现金为王，等待政策信号',
    };
  } else if (isRecession) {
    return {
      cycle: '衰退',
      stockRatio: 20,
      bondRatio: 50,
      cashRatio: 30,
      recommendedSectors: ['医药', '公用事业', '黄金', '国债'],
      reason: '衰退期：债券为主，关注防御性板块',
    };
  } else if (isRecovering) {
    return {
      cycle: '复苏',
      stockRatio: 70,
      bondRatio: 20,
      cashRatio: 10,
      recommendedSectors: ['金融', '周期', '可选消费', '科技'],
      reason: '复苏初期：股票为主，关注顺周期板块',
    };
  } else {
    return {
      cycle: '不确定',
      stockRatio: 50,
      bondRatio: 30,
      cashRatio: 20,
      recommendedSectors: ['均衡配置'],
      reason: '信号不明，保持均衡配置',
    };
  }
}

// ==================== 导出综合状态 ====================

export interface DashboardSummary {
  overallStatus: AlertStatus;
  threeLevel: ThreeLevelAlert;
  cycle: InvestmentCycle;
  advice: InvestmentAdvice;
  alerts: { status: AlertStatus; threeLevel: ThreeLevelAlert; reason: string }[];
}

export function getDashboardSummary(data: MetricData): DashboardSummary {
  const alerts = calculateDimensionAlert(data);
  const advice = getInvestmentAdvice(data);
  
  // 取最严重的预警作为整体状态
  const hasRed = alerts.some(a => a.status === 'red');
  const hasOrange = alerts.some(a => a.status === 'orange');
  const hasYellow = alerts.some(a => a.status === 'yellow');
  
  return {
    overallStatus: hasRed ? 'red' : hasOrange ? 'orange' : hasYellow ? 'yellow' : 'green',
    threeLevel: hasRed ? 'red' : hasOrange ? 'orange' : hasYellow ? 'yellow' : 'green',
    cycle: advice.cycle,
    advice,
    alerts,
  };
}