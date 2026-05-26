import React from "react";
import { useMemo, useState, useEffect, useCallback } from 'react'
import { useMarketData, MarketDataSkeleton } from './hooks/useMarketData'
import './index.css'

// ====== v4.1 类型定义 ======

interface IndicatorInfo {
  value: number | null
  score: number | null
  trend: 'up' | 'down' | 'neutral'
  signal: string       // green, lightgreen, gray, yellow, red
  category: string
  country: string
  name: string
  frequency: string
  dataDate: string | null
  source: string
  unit: string
  timeliness: number   // α: 0.0 ~ 1.0
  freshness: string    // 🟢🟡🔴
  freshness_level: string  // fresh | stale | expired
}

interface DimensionMeta {
  name: string
  icon: string
  weight: number
  score: number
  signal: string
  valid_count: number
}

interface IASMeta {
  score: number
  max_possible: number
  signal: string
  position: string
  signal_icon: string
}

interface V4Data {
  timestamp: string
  data: Record<string, { value: number | null; unit: string; frequency: string; source: string; dataDate: string | null }>
  indicators: Record<string, IndicatorInfo>
  meta: {
    ias: IASMeta
    dimensions: Record<string, DimensionMeta>
  }
}

// ====== 评论数据类型定义 ======

interface CommentaryHighlight {
  indicator: string
  value: number | null
  unit: string
  key: string
}

interface DimensionCommentary {
  score: number
  signal: string
  commentary: string
  highlights: CommentaryHighlight[]
}

interface CommentaryData {
  version: string
  generatedAt: string
  dataTimestamp: string
  ias: {
    score: number
    signal: string
    summary: string
    keyDivergences: string[]
    keyRisks: string[]
  }
  dimensions: Record<string, DimensionCommentary>
}

// ====== 6维度配置 ======

const DIMENSION_ORDER = ['economic', 'inflation', 'liquidity', 'sentiment', 'resource', 'techGreen']

const DIMENSION_LABELS: Record<string, { name: string; icon: string }> = {
  economic:  { name: '经济增长', icon: '📈' },
  inflation: { name: '通胀与政策', icon: '💰' },
  liquidity: { name: '流动性', icon: '💧' },
  sentiment: { name: '市场情绪', icon: '🧠' },
  resource:  { name: '资源与供应链', icon: '🛢️' },
  techGreen: { name: '科技与绿色', icon: '🌱' },
}

// 每个维度下按国家排序的指标key列表
const DIMENSION_INDICATORS: Record<string, string[]> = {
  economic:  ['chinaGdp', 'chinaPmi', 'servicePmi', 'electricity', 'usGdp', 'usNonFarm'],
  inflation: ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate'],
  liquidity: ['lpr', 'dr007', 'm2', 'creditSpread', 'dollarIndex', 'usBond2Y', 'usBond5Y', 'usBond10Y'],
  sentiment: ['vix', 'fearGreed'],
  resource:  ['oilPrice', 'naturalGas', 'carbonPrice'],
  techGreen: ['aiGrowth', 'robotInstall', 'evPenetration', 'renewEnergyInvest'],
}

const COUNTRY_ORDER: Record<string, number> = {
  '🇨🇳': 0,
  '🇺🇸': 1,
  '🌐': 2,
}

// ====== useCommentaryData Hook ======

function useCommentaryData(shouldFetch: boolean): CommentaryData | null {
  const [commentary, setCommentary] = useState<CommentaryData | null>(null)

  const fetchCommentary = useCallback(async () => {
    try {
      const res = await fetch('/data/commentary.json')
      if (!res.ok) return
      const data = await res.json()
      setCommentary(data as CommentaryData)
    } catch {
      // 优雅降级：commentary.json 加载失败时静默忽略
    }
  }, [])

  useEffect(() => {
    if (!shouldFetch) return
    fetchCommentary()
    const interval = setInterval(fetchCommentary, 60000)
    return () => clearInterval(interval)
  }, [shouldFetch, fetchCommentary])

  return commentary
}

// ====== 主组件 ======

function App() {
  const { data: rawData, isLoading, isStale, refetch } = useMarketData()

  const v4Data = useMemo<V4Data | null>(() => {
    if (!rawData) return null
    return rawData as unknown as V4Data
  }, [rawData])

  const indicators = v4Data?.indicators || {}
  const meta = v4Data?.meta || { ias: { score: 0, max_possible: 4.6, signal: '持有', position: '40-60%', signal_icon: '➖' }, dimensions: {} }
  
  // Compute anomalies early (before early return to keep hook count stable)
  const anomalies = useMemo(() => {
    const result: { key: string; info: IndicatorInfo }[] = []
    for (const [key, info] of Object.entries(indicators)) {
      if (info.signal === 'red' || info.signal === 'yellow') {
        result.push({ key, info })
      }
    }
    // Sort: red first, then yellow
    result.sort((a, b) => {
      if (a.info.signal === 'red' && b.info.signal !== 'red') return -1
      if (a.info.signal !== 'red' && b.info.signal === 'red') return 1
      return 0
    })
    return result.slice(0, 6)
  }, [indicators])

  const commentary = useCommentaryData(!isLoading)

  if (isLoading || !v4Data) {
    return <MarketDataSkeleton />
  }
  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      {/* Header */}
      <header className="mb-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">
            <span className="text-blue-400">WorldOS</span>
            <span className="text-gray-400 text-base ml-2">v4.1</span>
          </h1>
          <div className="flex items-center gap-3 text-sm text-gray-400">
            <span>更新: {v4Data.timestamp ? new Date(v4Data.timestamp).toLocaleString('zh-CN') : '-'}</span>
            {isStale && <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-xs">⚠️ 超时</span>}
            <button onClick={refetch} className="text-xs text-gray-500 hover:text-gray-300 underline">刷新</button>
          </div>
        </div>
      </header>

      {/* IAS 卡片 */}
      <IASCard ias={meta.ias} />

      {/* 异常指标速览 */}
      {anomalies.length > 0 && (
        <AnomalyBar anomalies={anomalies} />
      )}

      {/* 维度条 */}
      <DimensionBar dimensions={meta.dimensions} />

      {/* 6维度卡片网格 */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {DIMENSION_ORDER.map(dimId => (
          <DimensionCardV4
            key={dimId}
            dimId={dimId}
            dimMeta={meta.dimensions[dimId]}
            indicatorKeys={DIMENSION_INDICATORS[dimId]}
            indicators={indicators}
          />
        ))}
      </div>

      {/* 数据解读评论栏目 */}
      {commentary && <CommentarySection commentary={commentary} meta={meta.dimensions} />}

      {/* Footer */}
      <footer className="mt-8 text-center text-xs text-gray-600">
        WorldOS 全球运行监控系统 · 数据每60秒自动刷新
      </footer>
    </div>
  )
}

// ====== IAS 卡片 ======

function IASCard({ ias }: { ias: IASMeta }) {
  const getGradient = () => {
    if (ias.score >= 2.5) return 'from-green-600 to-green-500'
    if (ias.score >= 1.0) return 'from-green-500 to-emerald-400'
    if (ias.score >= -0.5) return 'from-yellow-500 to-orange-400'
    if (ias.score >= -1.5) return 'from-orange-500 to-red-400'
    return 'from-red-600 to-red-500'
  }

  return (
    <div className={`bg-gradient-to-r ${getGradient()} rounded-xl p-5 mb-4 text-center shadow-lg`}>
      <div className="text-sm text-white/70 mb-1">IAS 综合投资评分</div>
      <div className="text-4xl font-bold text-white mb-1">
        {ias.score > 0 ? '+' : ''}{ias.score.toFixed(2)}
      </div>
      <div className="text-xl font-semibold text-white flex items-center justify-center gap-2">
        <span>{ias.signal_icon}</span>
        <span>{ias.signal}</span>
      </div>
      <div className="text-white/70 mt-1">建议仓位: {ias.position}</div>
    </div>
  )
}

// ====== 异常指标速览 ======

function AnomalyBar({
  anomalies,
}: {
  anomalies: { key: string; info: IndicatorInfo }[]
}) {
  return (
    <div className="mb-4 p-3 bg-gray-800/80 rounded-lg border border-gray-700">
      <div className="text-xs text-gray-400 mb-2">⚠️ 异常指标速览</div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {anomalies.map(({ key, info }) => (
          <div
            key={key}
            className={`flex-shrink-0 px-3 py-1.5 rounded-lg text-xs whitespace-nowrap ${
              info.signal === 'red'
                ? 'bg-red-500/15 text-red-300 border border-red-500/30'
                : 'bg-yellow-500/15 text-yellow-300 border border-yellow-500/30'
            }`}
          >
            <span className="mr-1">{info.country}</span>
            <span className="font-medium">{info.name}</span>
            <span className="mx-1 opacity-60">{info.value ?? '待接入'}</span>
            <span className="opacity-60">{info.unit}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ====== 维度条 ======

function DimensionBar({ dimensions }: { dimensions: Record<string, DimensionMeta> }) {
  return (
    <div className="flex flex-wrap justify-center gap-2 mb-4">
      {DIMENSION_ORDER.map(dimId => {
        const dim = dimensions[dimId]
        return (
          <div
            key={dimId}
            className={`px-2.5 py-1 rounded-full text-xs font-medium ${
              dim.score > 0.1
                ? 'bg-green-500/15 text-green-400'
                : dim.score < -0.1
                ? 'bg-red-500/15 text-red-400'
                : 'bg-gray-500/15 text-gray-400'
            }`}
          >
            {dim.icon} {dim.name} {dim.score > 0 ? '+' : ''}{dim.score.toFixed(2)}
          </div>
        )
      })}
    </div>
  )
}

// ====== 维度卡片 ======

function DimensionCardV4({
  dimId,
  dimMeta,
  indicatorKeys,
  indicators,
}: {
  dimId: string
  dimMeta: DimensionMeta
  indicatorKeys: string[]
  indicators: Record<string, IndicatorInfo>
}) {
  const label = DIMENSION_LABELS[dimId]

  const getScoreColor = () => {
    if (dimMeta.score > 0.1) return 'text-green-400'
    if (dimMeta.score < -0.1) return 'text-red-400'
    return 'text-gray-400'
  }

  // Group indicators by country
  const grouped = useMemo(() => {
    const groups: Record<string, { key: string; info: IndicatorInfo }[]> = {}
    for (const key of indicatorKeys) {
      const info = indicators[key]
      if (!info) continue
      const country = info.country || '🌐'
      if (!groups[country]) groups[country] = []
      groups[country].push({ key, info })
    }
    // Sort by country order
    return Object.entries(groups).sort(
      (a, b) => (COUNTRY_ORDER[a[0]] ?? 99) - (COUNTRY_ORDER[b[0]] ?? 99)
    )
  }, [indicatorKeys, indicators])

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-gray-600 transition-colors">
      {/* 维度头部 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">{label.icon}</span>
          <h2 className="text-base font-semibold text-gray-100">{label.name}</h2>
          <span className="text-xs text-gray-500">w={dimMeta.weight}</span>
        </div>
        <span className={`text-lg font-bold ${getScoreColor()}`}>
          {dimMeta.score > 0 ? '+' : ''}{dimMeta.score.toFixed(2)}
        </span>
      </div>

      {/* 按国家分组的指标 */}
      {grouped.map(([country, items]) => (
        <div key={country} className="mb-2 last:mb-0">
          <div className="text-xs text-gray-500 mb-1 font-medium">{country}</div>
          <div className="space-y-0.5">
            {items.map(({ key, info }) => (
              <IndicatorRowV4 key={key} info={info} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ====== 指标行 ======

function IndicatorRowV4({ info }: { info: IndicatorInfo }) {
  // Determine background color based on signal
  const rowBg = info.signal === 'red'
    ? 'bg-red-500/8'
    : info.signal === 'yellow'
    ? 'bg-yellow-500/8'
    : ''

  const isExpired = info.freshness_level === 'expired'

  // Format value
  const displayValue = info.value !== null && info.value !== undefined
    ? (typeof info.value === 'number' && info.value >= 1000
        ? info.value.toFixed(0)
        : typeof info.value === 'number'
        ? info.value.toFixed(2)
        : String(info.value))
    : '待接入'

  // Score display
  const scoreDisplay = info.score !== null
    ? `${info.score > 0 ? '+' : ''}${info.score.toFixed(2)}`
    : '-'

  return (
    <div className={`${rowBg} ${isExpired ? 'opacity-70' : ''} py-1`}>
      {/* 主行 */}
      <div className="flex items-center justify-between px-2 rounded text-sm">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <span className="text-xs flex-shrink-0">{info.country}</span>
          <span className={`truncate ${isExpired ? 'text-gray-400' : 'text-gray-300'}`}>
            {info.name}
          </span>
          <span className="text-xs flex-shrink-0">{info.freshness}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={`font-mono text-xs text-right min-w-[3.5rem] ${
            displayValue === '待接入' ? 'text-gray-500' : isExpired ? 'text-gray-400' : 'text-gray-200'
          }`}>
            {displayValue}{info.value !== null && info.unit ? info.unit : ''}
          </span>
          <span className={`text-xs w-3 text-center ${
            info.trend === 'up' ? 'text-green-500' :
            info.trend === 'down' ? 'text-red-500' :
            'text-gray-500'
          }`}>
            {info.trend === 'up' ? '↑' : info.trend === 'down' ? '↓' : '→'}
          </span>
          <span className={`font-mono text-xs w-12 text-right ${
            info.score !== null && info.score > 0 ? 'text-green-500/60' :
            info.score !== null && info.score < 0 ? 'text-red-500/60' :
            'text-gray-500/60'
          }`}>
            {scoreDisplay}
          </span>
        </div>
      </div>
      {/* 副行：数据来源 + 时间 */}
      {(info.source || info.dataDate) && (
        <div className="flex items-center gap-2 px-2 text-[10px] text-gray-600">
          {info.source && <span>{info.source}</span>}
          {info.dataDate && <span>· {info.dataDate}</span>}
        </div>
      )}
    </div>
  )
}

// ====== Markdown 轻量渲染组件 ======

function MarkdownText({ text }: { text: string }) {
  // 只处理 **加粗** 和 \n 换行
  const lines = text.split('\n').filter(Boolean)
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        // 处理 **加粗**
        const parts = line.split(/\*\*(.*?)\*\*/g)
        return (
          <p key={i} className="text-sm text-gray-300 leading-relaxed">
            {parts.map((part, j) =>
              j % 2 === 1 ? <strong key={j} className="text-white font-semibold">{part}</strong> : part
            )}
          </p>
        )
      })}
    </div>
  )
}

// ====== 评分颜色映射 ======

function getScoreBadgeColor(signal: string): string {
  switch (signal) {
    case 'green':
    case 'lightgreen':
      return 'bg-green-500/20 text-green-400'
    case 'yellow':
      return 'bg-yellow-500/20 text-yellow-400'
    case 'red':
      return 'bg-red-500/20 text-red-400'
    default:
      return 'bg-gray-500/20 text-gray-400'
  }
}

function getSignalEmoji(signal: string): string {
  switch (signal) {
    case 'green':
    case 'lightgreen':
      return '🟢'
    case 'yellow':
      return '🟡'
    case 'red':
      return '🔴'
    default:
      return '⚪'
  }
}

// ====== 单个维度解读（可折叠） ======

function DimensionCommentaryItem(props: {
  dimId: string
  dimCommentary: DimensionCommentary
  dimLabel: { name: string; icon: string }
}) {
  const { dimCommentary, dimLabel } = props
  const [expanded, setExpanded] = useState(false)
  const signalEmoji = getSignalEmoji(dimCommentary.signal)

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      {/* 标题栏（可点击） */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-800/50 hover:bg-gray-700/50 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">{dimLabel.icon}</span>
          <span className="text-sm font-medium text-gray-200">{dimLabel.name}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${getScoreBadgeColor(dimCommentary.signal)}`}>
            {signalEmoji} {dimCommentary.score > 0 ? '+' : ''}{dimCommentary.score.toFixed(2)}
          </span>
        </div>
        <span className="text-gray-500 text-sm transition-transform" style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          ▼
        </span>
      </button>

      {/* 展开内容 */}
      {expanded && (
        <div className="px-4 py-3 bg-gray-800/30 border-t border-gray-700/50">
          <MarkdownText text={dimCommentary.commentary} />
          {/* 高亮指标快照 */}
          {dimCommentary.highlights.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {dimCommentary.highlights.map((h, idx) => (
                <span
                  key={idx}
                  className="text-xs px-2 py-1 bg-gray-700/40 rounded text-gray-400"
                >
                  {h.key}: {h.value !== null ? h.value.toLocaleString() : 'N/A'}
                  {h.unit ? h.unit : ''}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ====== 评论栏目容器 ======

function CommentarySection({
  commentary,
}: {
  commentary: CommentaryData
  meta?: Record<string, DimensionMeta>
}) {
  const [iasExpanded, setIasExpanded] = useState(true) // 默认展开
  const DIM_COMMENT_ORDER = ['economic', 'inflation', 'liquidity', 'sentiment', 'resource', 'techGreen']
  const DIM_COMMENT_LABELS: Record<string, { name: string; icon: string }> = {
    economic:  { name: '经济增长', icon: '📈' },
    inflation: { name: '通胀与政策', icon: '💰' },
    liquidity: { name: '流动性', icon: '💧' },
    sentiment: { name: '市场情绪', icon: '🧠' },
    resource:  { name: '资源与供应链', icon: '🛢️' },
    techGreen: { name: '科技与绿色', icon: '🌱' },
  }

  return (
    <section className="mt-8">
      {/* 栏目标题 */}
      <h2 className="text-lg font-semibold text-gray-200 mb-4 flex items-center gap-2">
        <span>📝</span>
        <span>数据解读</span>
        <span className="text-xs text-gray-500 font-normal">
          基于模板引擎自动生成
        </span>
      </h2>

      {/* IAS 整体解读（默认展开） */}
      <div className="mb-4 border border-gray-700 rounded-lg overflow-hidden">
        <button
          onClick={() => setIasExpanded(!iasExpanded)}
          className="w-full flex items-center justify-between px-4 py-3 bg-gradient-to-r from-blue-900/40 to-purple-900/40 hover:from-blue-800/40 hover:to-purple-800/40 transition-colors"
        >
          <div className="flex items-center gap-2">
            <span className="text-lg">🔍</span>
            <span className="text-sm font-semibold text-blue-200">IAS 整体解读</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300">
              {commentary.ias.score > 0 ? '+' : ''}{commentary.ias.score.toFixed(2)}
            </span>
            <span className="text-xs text-gray-400">{commentary.ias.signal}</span>
          </div>
          <span className="text-gray-500 text-sm">{iasExpanded ? '收起' : '展开'}</span>
        </button>
        {iasExpanded && (
          <div className="px-4 py-3 bg-gray-800/20 border-t border-gray-700/50">
            <MarkdownText text={commentary.ias.summary} />

            {/* 关键矛盾标签 */}
            {commentary.ias.keyDivergences.length > 0 && (
              <div className="mt-3">
                <span className="text-xs text-yellow-400 font-medium">⚠️ 关键矛盾</span>
                <div className="flex flex-wrap gap-2 mt-1">
                  {commentary.ias.keyDivergences.map((d, i) => (
                    <span key={i} className="text-xs px-2 py-1 bg-yellow-500/10 text-yellow-300 border border-yellow-500/20 rounded">
                      {d}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 关键风险标签 */}
            {commentary.ias.keyRisks.length > 0 && (
              <div className="mt-2">
                <span className="text-xs text-red-400 font-medium">⛔ 尾部风险</span>
                <div className="flex flex-wrap gap-2 mt-1">
                  {commentary.ias.keyRisks.map((r, i) => (
                    <span key={i} className="text-xs px-2 py-1 bg-red-500/10 text-red-300 border border-red-500/20 rounded">
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 6个板块解读（默认折叠） */}
      <div className="space-y-2">
        <h3 className="text-xs text-gray-500 font-medium px-1">各维度解读</h3>
        {DIM_COMMENT_ORDER.map(dimId => {
          const dimCommentary = commentary.dimensions[dimId]
          const dimLabel = DIM_COMMENT_LABELS[dimId]
          if (!dimCommentary || !dimLabel) return null
          return (
            <DimensionCommentaryItem
              key={dimId}
              dimId={dimId}
              dimCommentary={dimCommentary}
              dimLabel={dimLabel}
            />
          )
        })}
      </div>
    </section>
  )
}

const AppWithBoundary = () => React.createElement(ErrorBoundary, null, React.createElement(App));
export default AppWithBoundary

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("WorldOS Error:", error, info);
  }
  render() {
    if (this.state.hasError) {
      return React.createElement("div", { style: { padding: 20, color: "white", background: "#1a1a2e", fontFamily: "monospace" } },
        React.createElement("h1", null, "⚠️ WorldOS 渲染错误"),
        React.createElement("pre", null, this.state.error?.toString()),
        React.createElement("pre", { style: { fontSize: 12 } }, this.state.error?.stack)
      );
    }
    return this.props.children;
  }
}
