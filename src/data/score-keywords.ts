// ====== WorldOS 维度评分关键词标注 ======
// 设计文档: docs/score-keywords-design.md
// 根据 score 值范围映射关键词

export interface KeywordEntry {
  keyword: string       // 中文关键词
  emoji: string         // 图标
  color: string         // Tailwind 颜色类
  dotColor: string      // 统一颜色圆点
}

// 5档通用的评分范围判断
export function getScoreRange(score: number): 'strong-positive' | 'weak-positive' | 'neutral' | 'weak-negative' | 'strong-negative' {
  if (score >= 0.5) return 'strong-positive'
  if (score >= 0.1) return 'weak-positive'
  if (score >= -0.1) return 'neutral'
  if (score >= -0.5) return 'weak-negative'
  return 'strong-negative'
}

// ====== 各维度关键词映射表 ======

const ECONOMIC_KEYWORDS: Record<string, KeywordEntry> = {
  'strong-positive': { keyword: '扩张', emoji: '🔥', color: 'text-green-400', dotColor: '#22c55e' },
  'weak-positive':   { keyword: '稳健', emoji: '📈', color: 'text-green-300', dotColor: '#86efac' },
  'neutral':         { keyword: '平稳', emoji: '↔️', color: 'text-gray-400', dotColor: '#9ca3af' },
  'weak-negative':   { keyword: '放缓', emoji: '📉', color: 'text-yellow-400', dotColor: '#eab308' },
  'strong-negative': { keyword: '收缩', emoji: '⚠️', color: 'text-red-400', dotColor: '#ef4444' },
}

const INFLATION_KEYWORDS: Record<string, KeywordEntry> = {
  'strong-positive': { keyword: '过热', emoji: '🔥', color: 'text-green-400', dotColor: '#22c55e' },
  'weak-positive':   { keyword: '偏暖', emoji: '🌡️', color: 'text-green-300', dotColor: '#86efac' },
  'neutral':         { keyword: '平衡', emoji: '✅', color: 'text-gray-400', dotColor: '#9ca3af' },
  'weak-negative':   { keyword: '偏冷', emoji: '❄️', color: 'text-yellow-400', dotColor: '#eab308' },
  'strong-negative': { keyword: '通缩/紧缩', emoji: '⛄', color: 'text-red-400', dotColor: '#ef4444' },
}

const LIQUIDITY_KEYWORDS: Record<string, KeywordEntry> = {
  'strong-positive': { keyword: '宽裕', emoji: '🌊', color: 'text-green-400', dotColor: '#22c55e' },
  'weak-positive':   { keyword: '充裕', emoji: '💧', color: 'text-green-300', dotColor: '#86efac' },
  'neutral':         { keyword: '适中', emoji: '💦', color: 'text-gray-400', dotColor: '#9ca3af' },
  'weak-negative':   { keyword: '偏紧', emoji: '🏜️', color: 'text-yellow-400', dotColor: '#eab308' },
  'strong-negative': { keyword: '枯竭', emoji: '🧊', color: 'text-red-400', dotColor: '#ef4444' },
}

const SENTIMENT_KEYWORDS: Record<string, KeywordEntry> = {
  'strong-positive': { keyword: '狂热', emoji: '🚀', color: 'text-green-400', dotColor: '#22c55e' },
  'weak-positive':   { keyword: '乐观', emoji: '😊', color: 'text-green-300', dotColor: '#86efac' },
  'neutral':         { keyword: '中性', emoji: '😐', color: 'text-gray-400', dotColor: '#9ca3af' },
  'weak-negative':   { keyword: '谨慎', emoji: '😰', color: 'text-yellow-400', dotColor: '#eab308' },
  'strong-negative': { keyword: '恐慌', emoji: '😱', color: 'text-red-400', dotColor: '#ef4444' },
}

const RESOURCE_KEYWORDS: Record<string, KeywordEntry> = {
  'strong-positive': { keyword: '通畅', emoji: '✅', color: 'text-green-400', dotColor: '#22c55e' },
  'weak-positive':   { keyword: '稳定', emoji: '👍', color: 'text-green-300', dotColor: '#86efac' },
  'neutral':         { keyword: '平衡', emoji: '🔄', color: 'text-gray-400', dotColor: '#9ca3af' },
  'weak-negative':   { keyword: '紧张', emoji: '⚠️', color: 'text-yellow-400', dotColor: '#eab308' },
  'strong-negative': { keyword: '中断', emoji: '🚨', color: 'text-red-400', dotColor: '#ef4444' },
}

const TECHGREEN_KEYWORDS: Record<string, KeywordEntry> = {
  'strong-positive': { keyword: '领先', emoji: '🚀', color: 'text-green-400', dotColor: '#22c55e' },
  'weak-positive':   { keyword: '向好', emoji: '📊', color: 'text-green-300', dotColor: '#86efac' },
  'neutral':         { keyword: '平稳', emoji: '↔️', color: 'text-gray-400', dotColor: '#9ca3af' },
  'weak-negative':   { keyword: '放缓', emoji: '📉', color: 'text-yellow-400', dotColor: '#eab308' },
  'strong-negative': { keyword: '滞后', emoji: '⚠️', color: 'text-red-400', dotColor: '#ef4444' },
}

const IAS_KEYWORDS: Record<string, KeywordEntry> = {
  'strong-positive': { keyword: '积极', emoji: '🚀', color: 'text-green-400', dotColor: '#22c55e' },
  'weak-positive':   { keyword: '偏多', emoji: '✅', color: 'text-green-300', dotColor: '#86efac' },
  'neutral':         { keyword: '持有', emoji: '➖', color: 'text-gray-400', dotColor: '#9ca3af' },
  'weak-negative':   { keyword: '偏空', emoji: '⚠️', color: 'text-yellow-400', dotColor: '#eab308' },
  'strong-negative': { keyword: '避险', emoji: '🔴', color: 'text-red-400', dotColor: '#ef4444' },
}

// 维度ID到关键词表的映射
const KEYWORD_MAP: Record<string, Record<string, KeywordEntry>> = {
  economic: ECONOMIC_KEYWORDS,
  inflation: INFLATION_KEYWORDS,
  liquidity: LIQUIDITY_KEYWORDS,
  sentiment: SENTIMENT_KEYWORDS,
  resource: RESOURCE_KEYWORDS,
  techGreen: TECHGREEN_KEYWORDS,
  ias: IAS_KEYWORDS,
}

/**
 * 根据维度ID和score获取关键词条目
 */
export function getKeyword(dimId: string, score: number): KeywordEntry {
  const range = getScoreRange(score)
  const map = KEYWORD_MAP[dimId] || KEYWORD_MAP.ias
  return map[range]
}

/**
 * 格式化显示: 数值 + 关键词
 * 例: `-0.12 ↔️ 平稳`
 */
export function formatScoreWithKeyword(dimId: string, score: number): string {
  const kw = getKeyword(dimId, score)
  const sign = score > 0 ? '+' : ''
  return `${sign}${score.toFixed(2)} ${kw.emoji} ${kw.keyword}`
}
