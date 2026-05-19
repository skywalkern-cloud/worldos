// 投资监控仪表盘 - 维度卡片组件 v4
// 龙五负责 - 增加炫酷效果 + 技术指标国家标签
// 龙六修改 - 宏观版固定列宽对齐，无数据显示"-"，同比/环比颜色

import React from 'react';
import { motion } from 'framer-motion';
import type { AlertStatus } from '../data/marketData';

interface DimensionCardProps {
  title: string;
  icon: string;
  children: React.ReactNode;
  alertStatus: AlertStatus;
}

const statusConfig = {
  green: {
    border: 'border-l-green-500',
    glow: 'shadow-[0_0_20px_rgba(16,185,129,0.2)]',
    hoverGlow: 'hover:shadow-[0_0_40px_rgba(16,185,129,0.4)]',
    hoverBorder: 'hover:border-green-500',
    badge: 'bg-green-500/20 text-green-400 border-green-500/30',
    badgeText: '正常',
  },
  yellow: {
    border: 'border-l-yellow-500',
    glow: 'shadow-[0_0_20px_rgba(245,158,11,0.2)]',
    hoverGlow: 'hover:shadow-[0_0_40px_rgba(245,158,11,0.4)]',
    hoverBorder: 'hover:border-yellow-500',
    badge: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    badgeText: '关注',
  },
  orange: {
    border: 'border-l-orange-500',
    glow: 'shadow-[0_0_20px_rgba(249,115,22,0.2)]',
    hoverGlow: 'hover:shadow-[0_0_40px_rgba(249,115,22,0.4)]',
    hoverBorder: 'hover:border-orange-500',
    badge: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    badgeText: '警告',
  },
  red: {
    border: 'border-l-red-500',
    glow: 'shadow-[0_0_20px_rgba(239,68,68,0.2)]',
    hoverGlow: 'hover:shadow-[0_0_40px_rgba(239,68,68,0.4)]',
    hoverBorder: 'hover:border-red-500',
    badge: 'bg-red-500/20 text-red-400 border-red-500/30',
    badgeText: '危险',
  },
};

export const DimensionCard: React.FC<DimensionCardProps> = ({
  title,
  icon,
  children,
  alertStatus,
}) => {
  const config = statusConfig[alertStatus];
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: 1.02, y: -2 }}
      transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      className={`
        bg-[#161B22] border border-[#30363D] rounded-lg p-4
        ${config.border} ${config.glow} ${config.hoverGlow} ${config.hoverBorder}
        transition-all duration-300
      `}
    >
      {/* 卡片头部 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <motion.span 
            className="text-2xl"
            whileHover={{ scale: 1.2, rotate: 5 }}
          >
            {icon}
          </motion.span>
          <h3 className="text-[#E6EDF3] font-semibold text-lg">{title}</h3>
        </div>
        <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${config.badge}`}>
          {config.badgeText}
        </span>
      </div>
      
      {/* 卡片内容 */}
      <div className="text-[#8B949E]">
        {children}
      </div>
    </motion.div>
  );
};

// 指标行组件
interface MetricRowProps {
  label: string;
  value: string | number;
  unit?: string;
  trend?: 'up' | 'down' | 'neutral';
}

export const MetricRow: React.FC<MetricRowProps> = ({
  label,
  value,
  unit = '',
  trend,
}) => {
  const trendStyles = {
    up: { icon: '↑', color: 'text-green-400' },
    down: { icon: '↓', color: 'text-red-400' },
    neutral: { icon: '', color: 'text-[#8B949E]' },
  };
  
  const trendStyle = trend ? trendStyles[trend] : trendStyles.neutral;
  
  return (
    <div className="flex justify-between items-center py-2 border-b border-[#30363D] last:border-0 hover:bg-[#1C2128]/50 px-1 -mx-1 rounded transition-colors">
      <span className="text-[#8B949E] text-sm">{label}</span>
      <div className="flex items-center gap-1">
        {trend !== 'neutral' && trend && (
          <motion.span 
            className={`text-sm ${trendStyle.color}`}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
          >
            {trendStyle.icon}
          </motion.span>
        )}
        <span className="font-mono font-semibold text-[#E6EDF3]">
          {value}{unit}
        </span>
      </div>
    </div>
  );
};

// 进度条组件
interface ProgressBarProps {
  value: number;
  max?: number;
  status?: AlertStatus;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  value,
  max = 100,
  status = 'green',
}) => {
  const percentage = Math.min(Math.max((value / max) * 100, 0), 100);
  
  const statusGradients = {
    green: 'from-green-500 to-emerald-400',
    yellow: 'from-yellow-500 to-amber-400',
    orange: 'from-orange-500 to-red-400',
    red: 'from-red-500 to-pink-400',
  };

  return (
    <div className="w-full h-2 bg-[#30363D] rounded-full overflow-hidden">
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${percentage}%` }}
        transition={{ duration: 0.8, ease: 'easeOut' }}
        className={`h-full bg-gradient-to-r ${statusGradients[status]} rounded-full`}
      />
    </div>
  );
};

// 状态标签组件
interface StatusBadgeProps {
  status: AlertStatus;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  return (
    <span className={`px-2 py-1 text-xs font-medium rounded-full border ${statusConfig[status].badge}`}>
      {statusConfig[status].badgeText}
    </span>
  );
};

// 宏观指标行组件（固定列宽对齐版）v5 - 龙七修复版
// 对齐原则：
// - 每行高度固定36px
// - 列宽固定，不允许伸缩
// - 列与列之间用1px #30363D细竖线分隔
// - 固定列宽：指标名100px左对齐 | 数值70px右对齐 | 日期90px居中 | 同比60px居中 | 环比60px居中 | 国家24px居中 | ?图标24px居中
// - 所有内容垂直居中
// 排版格式：指标名 | 数值 | 日期 | 同比 | 环比 | 国家 | ❓
// 无数据字段统一显示"-"，同比/环比颜色：涨绿↓跌红↑
interface LabeledMetricRowProps {
  label: string;
  value: number | string | "NA";
  country: '🇨🇳' | '🇺🇸' | '🌐';
  unit?: string;
  trend?: 'up' | 'down' | 'neutral';
  // 扩展字段
  date?: string;
  dateLabel?: string;
  yoy?: number;
  yoyLabel?: string;
  mom?: number;
  momLabel?: string;
  definition?: string;
  source?: string;
  frequency?: string;
}

export const LabeledMetricRow: React.FC<LabeledMetricRowProps> = ({
  label,
  value,
  country: _country,
  unit = '',
  dateLabel,
  date,
  yoy,
  yoyLabel,
  mom,
  momLabel,
  definition,
  source,
  frequency,
}) => {
  const [showTooltip, setShowTooltip] = React.useState(false);
  
  // 无数据显示"-"（不是NA，不是空）
  const displayValue = (val: number | string | "NA" | undefined | null): string => {
    if (val === undefined || val === null) return "-";
    if (val === "NA") return "-";
    if (typeof val === 'string' && val.trim() === '') return "-";
    return String(val);
  };
  
  // 格式化变化率：支持数字或字符串
  const formatChangeLabel = (label: string | number | undefined | null): string => {
    if (label === undefined || label === null) return "-";
    if (typeof label === 'number') {
      const sign = label >= 0 ? '+' : '';
      return `${sign}${(label * 100).toFixed(1)}%`;
    }
    if (label === "" || label === "NA") return "-";
    return label;
  };
  
  // 同比/环比颜色：涨→绿色↓，跌→红色↑，无数据→灰色
  const yoyColor = (yoy === undefined || yoy === null) ? 'text-[#484F58]' : (yoy >= 0 ? 'text-green-400' : 'text-red-400');
  const momColor = (mom === undefined || mom === null) ? 'text-[#484F58]' : (mom >= 0 ? 'text-green-400' : 'text-red-400');
  const yoyIcon = (yoy === undefined || yoy === null) ? '' : (yoy >= 0 ? '↑' : '↓');
  const momIcon = (mom === undefined || mom === null) ? '' : (mom >= 0 ? '↑' : '↓');
  
  // 日期标签，确保最小显示"-"
  const displayDateLabel = dateLabel || date || '-';
  
  // 是否显示❓（有任何指标说明信息就显示）
  const hasInfo = !!(definition || source || frequency);
  
  return (
    <div className="flex items-center justify-between h-[36px] border-b border-[#21262D] last:border-0 hover:bg-[#1C2128]/50 px-2 rounded transition-colors relative">
      {/* 指标名 - 固定宽度100px，左对齐，截断显示 */}
      <span className="text-[#8B949E] text-sm w-[100px] flex-shrink-0 truncate flex items-center" title={label}>
        {label}
      </span>
      
      {/* 固定1px竖线分隔 */}
      <span className="w-[1px] h-5 bg-[#30363D] flex-shrink-0 mx-0" />
      
      {/* 数值 - 固定宽度70px，右对齐，font-mono */}
      <span className="font-mono font-semibold text-[#E6EDF3] w-[70px] text-right flex items-center justify-end flex-shrink-0">
        {displayValue(value)}{unit}
      </span>
      
      {/* 固定1px竖线分隔 */}
      <span className="w-[1px] h-5 bg-[#30363D] flex-shrink-0 mx-0" />
      
      {/* 日期 - 固定宽度90px，居中对齐 */}
      <span className="text-xs text-[#8B949E] w-[90px] text-center flex items-center justify-center flex-shrink-0">
        {displayDateLabel}
      </span>
      
      {/* 固定1px竖线分隔 */}
      <span className="w-[1px] h-5 bg-[#30363D] flex-shrink-0 mx-0" />
      
      {/* 同比 - 固定宽度60px，居中对齐，颜色+箭头 */}
      <span className={`text-xs w-[60px] text-center flex items-center justify-center flex-shrink-0 font-mono ${yoyColor}`}>
        {formatChangeLabel(yoyLabel ?? yoy)}{yoyIcon && <span className="ml-0.5">{yoyIcon}</span>}
      </span>
      
      {/* 固定1px竖线分隔 */}
      <span className="w-[1px] h-5 bg-[#30363D] flex-shrink-0 mx-0" />
      
      {/* 环比 - 固定宽度60px，居中对齐，颜色+箭头 */}
      <span className={`text-xs w-[60px] text-center flex items-center justify-center flex-shrink-0 font-mono ${momColor}`}>
        {formatChangeLabel(momLabel ?? mom)}{momIcon && <span className="ml-0.5">{momIcon}</span>}
      </span>
      
      {/* 固定1px竖线分隔 */}
      <span className="w-[1px] h-5 bg-[#30363D] flex-shrink-0 mx-0" />
      
      
      {/* 指标说明图标 - 固定宽度24px，居中对齐 */}
      <div className="relative w-[24px] h-[24px] flex-shrink-0 flex items-center justify-center">
        {hasInfo && (
          <span 
            className="w-4 h-4 rounded-full border border-[#484F58] text-[#8B949E] cursor-pointer hover:text-[#E6EDF3] hover:border-[#8B949E] text-xs flex items-center justify-center font-serif"
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
          >
            ?
          </span>
        )}
        {!hasInfo && (
          <span className="text-[#484F58] text-xs">-</span>
        )}
        {showTooltip && (
          <div className="absolute right-0 top-6 z-50 w-64 bg-[#21262D] border border-[#30363D] rounded-lg p-3 shadow-lg">
            <div className="text-[#E6EDF3] font-semibold text-sm mb-2">{label}</div>
            {definition && <div className="text-[#8B949E] text-xs mb-2">{definition}</div>}
            {source && <div className="text-[#8B949E] text-xs mb-1">来源: {source}</div>}
            {frequency && <div className="text-[#8B949E] text-xs">频率: {frequency}</div>}
          </div>
        )}
      </div>
    </div>
  );
};

