// 投资监控仪表盘 - 实时数据获取
// 龙五负责数据整合

import { type MetricData, defaultData } from './marketData';

// 获取实时数据的API URL (未来使用)
// const DATA_API_URL = '/api/market-data';

// 尝试从脚本获取数据
export async function fetchRealTimeData(): Promise<MetricData> {
  try {
    // 方法1: 如果有后端API
    // const response = await fetch(DATA_API_URL);
    // const data = await response.json();
    // return data;
    
    // 方法2: 模拟数据（当前使用）
    // 实际项目中应该调用真实API
    
    return defaultData;
  } catch (error) {
    console.error('获取实时数据失败:', error);
    return defaultData;
  }
}

// 格式化数字
export function formatNumber(value: number, decimals: number = 2): string {
  return value.toFixed(decimals);
}

// 格式化百分比
export function formatPercent(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

// 格式化金额（亿/万）
export function formatAmount(value: number, unit: '亿' | '万' = '亿'): string {
  if (unit === '亿') {
    return `${(value / 10000).toFixed(2)}万亿`;
  }
  return `${(value / 10000).toFixed(2)}万亿`;
}

// 获取数据源信息
export function getDataSourceInfo(): { source: string; updateTime: string } {
  return {
    source: '模拟数据（待接入真实API）',
    updateTime: new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }),
  };
}
