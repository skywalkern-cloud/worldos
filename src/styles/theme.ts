// 投资监控仪表盘 - 样式配置
// 龙五负责前端

export const colors = {
  // 背景色
  background: '#0D1117',
  cardBackground: '#161B22',
  cardHover: '#1C2128',
  
  // 赛博蓝主色
  cyberBlue: '#00D4FF',
  cyberBlueDark: '#0099CC',
  cyberBlueGlow: 'rgba(0, 212, 255, 0.3)',
  
  // 文字色
  textPrimary: '#E6EDF3',
  textSecondary: '#8B949E',
  textMuted: '#6E7681',
  
  // 预警状态色
  green: '#10B981',
  yellow: '#F59E0B',
  orange: '#F97316',
  red: '#EF4444',
  
  // 边框色
  border: '#30363D',
  borderGlow: 'rgba(0, 212, 255, 0.5)',
};

export const cardStyles = {
  base: `bg-[${colors.cardBackground}] border border-[${colors.border}] rounded-lg p-4`,
  hover: `hover:border-[${colors.cyberBlue}] hover:shadow-[0_0_20px_${colors.cyberBlueGlow}] transition-all duration-300`,
};
