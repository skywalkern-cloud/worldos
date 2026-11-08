import React from "react";
import { useMemo, useState, useEffect, useCallback } from 'react'
import { useMarketData, MarketDataSkeleton } from './hooks/useMarketData'
import { getKeyword } from './data/score-keywords'
import {
  computeStaleness,
  resolveDisplayName,
  describeFailReason,
  type DataDateKind,
  type ContributionEntry,
} from './lib/caliber'
import './index.css'

// ====== v4.1 类型定义 ======

interface FetchErrorInfo {
  reason?: string
  reasonText?: string
}

interface IndicatorInfo {
  value: number | null
  score: number | null
  trend: 'up' | 'down' | 'neutral'
  signal: string       // green, lightgreen, gray, yellow, red
  category: string
  country: string
  name: string
  // === P0/T1 后端新增（单一真源） ===
  displayName?: string
  shortName?: string
  caliberNote?: string
  reference_only?: boolean
  // === P0/T2 后端新增（时效，前端只读不算） ===
  dataDateISO?: string | null
  dataDateKind?: DataDateKind | null
  days_stale?: number | null
  // === 抓取失败兜底 ===
  used_fallback?: boolean
  fetchError?: FetchErrorInfo | null
  // === P0/T4 新增（龙五 Q3：α=0 / reference_only 的独立语义，后端待补） ===
  excluded_from_scoring?: boolean
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
  score: number | null      // P0/T4: 置灰维度给 null，不是 0
  signal: string
  valid_count?: number
  required_count?: number
  active_count?: number
  reference_only_count?: number
  insufficient_data?: boolean
  avg_alpha?: number
  // P1 预留：后端将来给指标级贡献度明细
  indicators?: Record<string, ContributionEntry>
}

interface IASMeta {
  score: number
  max_possible: number
  signal: string
  position: string
  signal_icon: string
  // === P0/T3 新增 ===
  normalized?: number
  valid_weight?: number
  data_coverage?: number
  counted_dimensions?: string[]
  grayed_dimensions?: string[]
  is_actionable?: boolean
  note?: string
}

interface ValidityFailure {
  key: string
  displayName?: string
  source?: string
  reason?: string
  reasonText?: string
  dataDate?: string | null
  days_stale?: number | null
  used_fallback?: boolean
  lastAttempt?: string
}

interface ValidityReport {
  total: number
  valid: number
  invalid: number
  degraded?: number
  failed?: ValidityFailure[]
}

interface V4Data {
  timestamp: string
  data: Record<string, { value: number | null; unit: string; frequency: string; source: string; dataDate: string | null }>
  indicators: Record<string, IndicatorInfo>
  meta: {
    ias: IASMeta
    dimensions: Record<string, DimensionMeta>
  }
  validity_report?: ValidityReport
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
  resource:  ['oilPrice', 'naturalGas', 'carbonPrice', 'lmeIndex', 'shanghaiCopper'],
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
      const res = await fetch('/data/commentary.json', { cache: 'no-store' })
      if (!res.ok) return
      const raw = await res.json()
      // 结构校验：commentary 是可选增强，坏数据直接忽略，不能拖垮主数据渲染
      if (!raw || typeof raw !== 'object' || !raw.ias || typeof raw.ias !== 'object') {
        console.warn('commentary.json 结构异常，已忽略（不影响主数据渲染）')
        return
      }
      // 归一化可选字段，避免 undefined.length / null.toFixed 导致整站崩溃
      setCommentary({
        ...raw,
        ias: {
          score: typeof raw.ias.score === 'number' && Number.isFinite(raw.ias.score) ? raw.ias.score : 0,
          signal: raw.ias.signal ?? '',
          summary: typeof raw.ias.summary === 'string' ? raw.ias.summary : '',
          keyDivergences: Array.isArray(raw.ias.keyDivergences) ? raw.ias.keyDivergences : [],
          keyRisks: Array.isArray(raw.ias.keyRisks) ? raw.ias.keyRisks : [],
        },
        dimensions: raw.dimensions && typeof raw.dimensions === 'object' ? raw.dimensions : {},
      } as CommentaryData)
    } catch {
      // 优雅降级：commentary.json 加载/解析失败时静默忽略，不影响主数据
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
  const { data: rawData, isLoading, isStale, error, refetch } = useMarketData()

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

  // ====== 有效性报告：后端 P0 起，validity_report.failed 是失败信息的唯一真源 ======
  // （旧实现遍历 indicators 抓 value===null，会漏掉不在 indicators 里的 epu）
  const validityReport = useMemo<ValidityReport | null>(() => {
    const vr = v4Data?.validity_report
    if (!vr || typeof vr !== 'object') return null
    return {
      total: typeof vr.total === 'number' ? vr.total : 0,
      valid: typeof vr.valid === 'number' ? vr.valid : 0,
      invalid: typeof vr.invalid === 'number' ? vr.invalid : 0,
      degraded: typeof vr.degraded === 'number' ? vr.degraded : 0,
      failed: Array.isArray(vr.failed) ? vr.failed : [],
    }
  }, [v4Data])

  // ====== 数据质量：区分「真失败」与「兜底」（used_fallback=true 有值，不能标红） ======
  const failureGroups = useMemo(() => {
    const hard: ValidityFailure[] = []
    const fallback: ValidityFailure[] = []
    for (const f of validityReport?.failed ?? []) {
      if (!f || !f.key) continue
      if (f.used_fallback) fallback.push(f)
      else hard.push(f)
    }
    return { hard, fallback }
  }, [validityReport])

  // 月度指标时效说明条（龙五 Q2：40 天是正常发布节奏，用「信息」而非「警告」表达）
  const hasMonthly = useMemo(
    () => Object.values(indicators).some(i => i?.frequency === 'monthly'),
    [indicators],
  )

  if (isLoading && !v4Data) {
    return <MarketDataSkeleton />
  }

  // 无数据 + 加载结束：显示明确错误，而不是无限骨架屏
  if (!v4Data) {
    return <DataErrorPanel error={error} onRetry={refetch} />
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      {/* 数据异常提示：有新错误但保留旧数据时显示 */}
      {error && (
        <div className="mb-4 p-3 rounded-lg border bg-red-500/15 border-red-500/30 text-red-200 flex items-center justify-between gap-3">
          <div className="text-sm">
            ⚠️ {error} — 当前展示的是上次成功加载的数据
          </div>
          <button
            onClick={refetch}
            className="flex-shrink-0 text-xs px-3 py-1 rounded bg-red-500/20 hover:bg-red-500/30 border border-red-500/40"
          >
            🔄 重试
          </button>
        </div>
      )}

      {/* 数据质量告警：失效 ≠ 兜底，分两色（后端 P0 契约） */}
      {(failureGroups.hard.length > 0 || failureGroups.fallback.length > 0) && (
        <div className="mb-4 p-3 rounded-lg border bg-gray-800/60 border-gray-700">
          <div className="text-sm font-medium mb-2 flex items-center gap-2 flex-wrap">
            <span className="text-gray-200">🔎 数据质量</span>
            <span className="text-gray-400 text-xs">
              有效 {validityReport?.valid ?? 0}/{validityReport?.total ?? 0}
            </span>
            {failureGroups.hard.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-300 border border-red-500/30">
                缺失 {failureGroups.hard.length}
              </span>
            )}
            {failureGroups.fallback.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-300 border border-yellow-500/30">
                兜底 {failureGroups.fallback.length}
              </span>
            )}
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {failureGroups.hard.map(f => <FailureChip key={`h-${f.key}`} failure={f} />)}
            {failureGroups.fallback.map(f => <FailureChip key={`f-${f.key}`} failure={f} />)}
          </div>
        </div>
      )}

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

      {/* 月度指标时效说明：40 天内为正常，不靠描灰表达（龙五 Q2） */}
      {hasMonthly && (
        <div className="text-[11px] text-gray-600 text-center -mt-2 mb-3">
          月度指标通常次月中旬更新，40 天内为正常
        </div>
      )}

      {/* 6维度卡片网格 */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {DIMENSION_ORDER.map(dimId => (
          <DimensionCardV4
            key={dimId}
            dimId={dimId}
            dimMeta={meta.dimensions[dimId]}
            indicatorKeys={DIMENSION_INDICATORS[dimId] ?? []}
            indicators={indicators}
          />
        ))}
      </div>

      {/* 数据解读评论栏目 */}
      {commentary && <CommentarySection commentary={commentary} meta={meta.dimensions} indicators={indicators} />}

      {/* Footer */}
      <footer className="mt-8 text-center text-xs text-gray-600">
        WorldOS 全球运行监控系统 · 数据每60秒自动刷新
      </footer>
    </div>
  )
}

// ====== 数据错误面板（加载/解析失败时取代骨架屏） ======

function DataErrorPanel({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  return (
    <div className="min-h-screen bg-gray-900 text-white flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-center">
        <div className="text-3xl mb-3">⚠️</div>
        <h1 className="text-lg font-semibold text-red-200 mb-2">数据加载失败</h1>
        <p className="text-sm text-red-300/80 break-words mb-1">
          {error || '无法获取市场数据'}
        </p>
        <p className="text-xs text-gray-500 mb-5">
          页面无法渲染指标，请稍后重试。
        </p>
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 rounded-lg text-sm text-red-100"
        >
          🔄 重新加载
        </button>
      </div>
    </div>
  )
}

// ====== IAS 卡片 ======

function IASCard({ ias }: { ias: IASMeta }) {
  // 渐变仍按旧量纲 score + 5 档次（契约 A：ias.normalized 仅展示，禁用于染渐变）
  const score = Number.isFinite(ias?.score) ? ias.score : 0
  const getGradient = () => {
    if (score >= 2.5) return 'from-green-600 to-green-500'
    if (score >= 1.0) return 'from-green-500 to-emerald-400'
    if (score >= -0.5) return 'from-yellow-500 to-orange-400'
    if (score >= -1.5) return 'from-orange-500 to-red-400'
    return 'from-red-600 to-red-500'
  }

  const kw = getKeyword('ias', score)
  const grayed = ias.grayed_dimensions ?? []

  return (
    <div className={`bg-gradient-to-r ${getGradient()} rounded-xl p-5 mb-4 text-center shadow-lg`}>
      <div className="text-sm text-white/70 mb-1">IAS 综合投资评分</div>
      <div className="text-4xl font-bold text-white mb-1">
        {score > 0 ? '+' : ''}{score.toFixed(2)}
      </div>
      <div className="text-lg font-medium text-white/90 flex items-center justify-center gap-1.5">
        <span>{kw.emoji}</span>
        <span>{kw.keyword}</span>
        <span className="mx-1.5 opacity-30">·</span>
        <span className="text-sm opacity-80">建议仓位: {ias.position}</span>
      </div>
      <div className="flex items-center justify-center gap-1 mt-0.5">
        <span className="text-sm text-white/70">
          <span className="opacity-60">IAS信号: </span>
          <span>{ias.signal_icon} {ias.signal}</span>
        </span>
      </div>

      {/* T5-4：未回测标注（以后端 ias.note 为真源，缺失时回退固定串） */}
      <div className="mt-2 flex items-center justify-center gap-2 flex-wrap">
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-black/25 text-white/85 border border-white/25">
          {ias.note || '未回测·非投资建议'}
        </span>
        {typeof ias.data_coverage === 'number' && (
          <span className="text-[11px] text-white/65">
            数据覆盖 {(ias.data_coverage * 100).toFixed(0)}%
            {typeof ias.valid_weight === 'number' && ` · 有效权重 ${ias.valid_weight.toFixed(1)}/${ias.max_possible}`}
          </span>
        )}
        {typeof ias.normalized === 'number' && (
          <span className="text-[11px] text-white/65">
            归一化 {ias.normalized > 0 ? '+' : ''}{ias.normalized.toFixed(3)}
          </span>
        )}
      </div>
      {ias.is_actionable === false && (
        <div className="mt-1.5">
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-black/35 text-yellow-100 border border-yellow-200/50">
            ⚠️ 数据覆盖不足，信号不可操作
          </span>
        </div>
      )}
      {grayed.length > 0 && <div className="mt-1 text-[11px] text-white/60">已置灰维度：{grayed.length} 个，不计入综合评分</div>}
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
            title={[resolveDisplayName(info, key), info.caliberNote].filter(Boolean).join('\n')}
          >
            <span className="mr-1">{info.country}</span>
            <span className="font-medium">{resolveDisplayName(info, key)}</span>
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
        const fallbackLabel = DIMENSION_LABELS[dimId] || { name: dimId, icon: '' }
        const dimName = dim?.name || fallbackLabel.name
        const dimIcon = dim?.icon || fallbackLabel.icon
        const score = typeof dim?.score === 'number' && Number.isFinite(dim.score) ? dim.score : null

        // T5-2：置灰判定只认 insufficient_data（或 score 为 null），不用 valid_count
        if (dim?.insufficient_data === true || score === null) {
          return (
            <div
              key={dimId}
              className="px-2.5 py-1 rounded-full text-xs font-medium bg-gray-700/25 text-gray-500 border border-dashed border-gray-600"
              title="数据不足，不计入 IAS 综合评分"
            >
              {dimIcon} {dimName} · 数据不足
            </div>
          )
        }

        const kw = getKeyword(dimId, score)
        return (
          <div
            key={dimId}
            className={`px-2.5 py-1 rounded-full text-xs font-medium ${
              score > 0.1
                ? 'bg-green-500/15 text-green-400'
                : score < -0.1
                ? 'bg-red-500/15 text-red-400'
                : 'bg-gray-500/15 text-gray-400'
            }`}
          >
            {dimIcon} {dimName} {score > 0 ? '+' : ''}{score.toFixed(2)} {kw.emoji} {kw.keyword}
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
  dimMeta?: DimensionMeta
  indicatorKeys: string[]
  indicators: Record<string, IndicatorInfo>
}) {
  // T5-5：贡献度展开（P1 预留）
  const [expanded, setExpanded] = useState(false)

  const fallbackLabel = DIMENSION_LABELS[dimId] || { name: dimId, icon: '' }
  const dimName = dimMeta?.name || fallbackLabel.name
  const dimIcon = dimMeta?.icon || fallbackLabel.icon

  // T5-2：置灰判定只认 insufficient_data；score 可能是 null，不能直接 toFixed
  const score = typeof dimMeta?.score === 'number' && Number.isFinite(dimMeta.score) ? dimMeta.score : null
  const insufficient = dimMeta?.insufficient_data === true || score === null

  const getScoreColor = () => {
    if (score === null) return 'text-gray-500'
    if (score > 0.1) return 'text-green-400'
    if (score < -0.1) return 'text-red-400'
    return 'text-gray-400'
  }

  const kw = score === null ? null : getKeyword(dimId, score)

  // 计数口径（龙六 P0）：active_count = 计分项；reference_only_count 单列，
  // 不能把 valid_count 直接当「有效项」展示，否则 techGreen 会自相矛盾
  const activeCount = dimMeta?.active_count ?? dimMeta?.valid_count ?? 0
  const refOnlyCount = dimMeta?.reference_only_count ?? 0
  const requiredCount = dimMeta?.required_count

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
    <div
      className={`bg-gray-800 rounded-lg p-4 border transition-colors ${
        insufficient ? 'border-dashed border-gray-600 opacity-70' : 'border-gray-700 hover:border-gray-600'
      }`}
    >
      {/* 维度头部（点击展开贡献度） */}
      <div
        className="flex items-center justify-between mb-3 cursor-pointer select-none"
        onClick={() => setExpanded(v => !v)}
        title={dimMeta?.insufficient_data ? '该维度数据不足，不计入综合评分' : '点击查看指标贡献度'}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xl">{dimIcon}</span>
          <h2 className="text-base font-semibold text-gray-100 truncate">{dimName}</h2>
          <span className="text-xs text-gray-500 flex-shrink-0">w={dimMeta?.weight ?? '-'}</span>
          <span className="text-[10px] text-gray-600 flex-shrink-0">
            {expanded ? '▲' : '▼'}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {insufficient ? (
            <span className="text-xs px-2 py-0.5 rounded bg-gray-700/50 text-gray-400 border border-dashed border-gray-600">
              数据不足
            </span>
          ) : (
            <>
              {kw && <span className="text-xs text-gray-400">{kw.emoji} {kw.keyword}</span>}
              <span className={`text-lg font-bold ${getScoreColor()}`}>
                {score !== null && score > 0 ? '+' : ''}{score !== null ? score.toFixed(2) : '—'}
              </span>
            </>
          )}
        </div>
      </div>

      {/* 计数口径：计分项 / 参考项 / 最低要求 */}
      <div className="flex items-center gap-2 mb-2 text-[10px] text-gray-500">
        <span>{activeCount} 项计分</span>
        {refOnlyCount > 0 && <span className="text-gray-600">· {refOnlyCount} 项参考（不计分）</span>}
        {typeof requiredCount === 'number' && <span className="text-gray-600">· 需 ≥{requiredCount}</span>}
      </div>

      {/* 置灰说明 */}
      {insufficient && (
        <div className="mb-2 text-[11px] text-gray-500 leading-snug">
          有效指标数未达最低要求，本维度不计入 IAS 综合评分。
        </div>
      )}

      {/* 按国家分组的指标 */}
      {grouped.map(([country, items]) => (
        <div key={country} className="mb-2 last:mb-0">
          <div className="text-xs text-gray-500 mb-1 font-medium">{country}</div>
          <div className="space-y-0.5">
            {items.map(({ key, info }) => (
              <IndicatorRowV4 key={key} info={info} indicatorKey={key} />
            ))}
          </div>
        </div>
      ))}

      {/* T5-5：指标贡献度（后端给 indicators 明细则渲染，否则占位） */}
      {expanded && (
        <div className="mt-2 pt-2 border-t border-gray-700/60">
          <div className="text-[10px] text-gray-500 mb-1.5">指标贡献度 · contribution = score × weight</div>
          {dimMeta?.indicators && Object.keys(dimMeta.indicators).length > 0 ? (
            <div className="space-y-1">
              {Object.entries(dimMeta.indicators)
                .sort((a, b) => Math.abs(b[1].contribution) - Math.abs(a[1].contribution))
                .map(([key, c]) => {
                  const info = indicators[key]
                  const pct = Math.min(100, Math.abs(c.contribution) * 100)
                  return (
                    <div key={key} className="flex items-center gap-2 text-[10px]">
                      <span className="w-24 truncate text-gray-400" title={resolveDisplayName(info, key)}>
                        {resolveDisplayName(info, key)}
                      </span>
                      <div className="flex-1 h-1.5 bg-gray-700/60 rounded overflow-hidden">
                        <div
                          className={`h-full ${c.contribution >= 0 ? 'bg-green-500/60' : 'bg-red-500/60'}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className={`w-12 text-right font-mono ${c.contribution >= 0 ? 'text-green-500/70' : 'text-red-500/70'}`}>
                        {c.contribution > 0 ? '+' : ''}{c.contribution.toFixed(3)}
                      </span>
                    </div>
                  )
                })}
            </div>
          ) : (
            <div className="text-[11px] text-gray-600 italic">
              贡献度明细待后端提供指标级 weight（P1 开放）
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ====== 指标行 ======

function IndicatorRowV4({ info, indicatorKey }: { info: IndicatorInfo; indicatorKey?: string }) {
  const name = resolveDisplayName(info, indicatorKey || '—')
  const stale = computeStaleness(info)

  // 【龙五 Q2 + Q3 拍板的双轴模型】
  // 轴一 dimmed（数据旧了）：单一真源 = 超阈值天数。
  //    freshness_level 是评分层 α 衰减结果，不驱动 UI 着色（两者会打架：α=0 但天数没超 → “描灰了但日期挺新”）。
  // 轴二 not_counted（这项没进综合评分）：excluded_from_scoring 或 α=0。
  // 优先级：reference_only 只挂「参考项」，**不再叠加任何其他标**（龙五：一行挂两个标 = 视觉过载）。
  const isRef = info.reference_only === true
  const isFallback = info.used_fallback === true
  const excluded = typeof info.excluded_from_scoring === 'boolean'
    ? info.excluded_from_scoring
    : isRef || info.timeliness === 0
  const notCounted = excluded && !isRef
  const dimmed = stale.overdue && !isRef

  // Determine background color based on signal
  const rowBg = info.signal === 'red'
    ? 'bg-red-500/8'
    : info.signal === 'yellow'
    ? 'bg-yellow-500/8'
    : ''

  // Format value
  const displayValue = info.value !== null && info.value !== undefined
    ? (typeof info.value === 'number' && info.value >= 1000
        ? info.value.toFixed(0)
        : typeof info.value === 'number'
        ? info.value.toFixed(2)
        : String(info.value))
    : '待接入'
  const isMissing = displayValue === '待接入'

  // Score display
  const scoreDisplay = typeof info.score === 'number' && Number.isFinite(info.score)
    ? `${info.score > 0 ? '+' : ''}${info.score.toFixed(2)}`
    : '-'

  return (
    <div className={`${rowBg} py-1 ${dimmed ? 'opacity-55' : ''} ${isRef ? 'opacity-70' : ''}`}>
      {/* 主行 */}
      <div className="flex items-center justify-between px-2 rounded text-sm">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <span className="text-xs flex-shrink-0">{info.country}</span>
          <span
            className={`truncate ${dimmed ? 'text-gray-500' : 'text-gray-300'}`}
            title={[name, info.caliberNote].filter(Boolean).join('\n')}
          >
            {name}
          </span>
          {info.caliberNote && (
            <span className="text-[10px] text-gray-600 hover:text-gray-400 flex-shrink-0 cursor-help" title={info.caliberNote}>
              ⓘ
            </span>
          )}
          {isRef ? (
            <span
              className="text-[9px] px-1 rounded bg-gray-700/60 text-gray-400 flex-shrink-0"
              title="参考项：仅展示，不参与打分"
            >
              参考项
            </span>
          ) : notCounted ? (
            <span
              className="text-[9px] px-1 rounded bg-gray-700/50 text-gray-500 flex-shrink-0"
              title="该项已失效或无时效（α=0），未计入综合评分"
            >
              不计分
            </span>
          ) : null}
          {isFallback && (
            <span
              className="text-[9px] px-1 rounded bg-yellow-500/20 text-yellow-300 flex-shrink-0"
              title={info.fetchError?.reasonText || '抓取失败，已用上一轮值兜底'}
            >
              兜底
            </span>
          )}
          <span className="text-xs flex-shrink-0" title={stale.title}>{info.freshness}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={`font-mono text-xs text-right min-w-[3.5rem] ${
            isMissing ? 'text-gray-500' : dimmed ? 'text-gray-400' : 'text-gray-200'
          }`}>
            {displayValue}{!isMissing && info.unit ? info.unit : ''}
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
      {/* 副行：数据来源 + 数据所属期 + N 天前（T5-1） */}
      {(info.source || info.dataDate) && (
        <div className="flex items-center gap-2 px-2 text-[10px] text-gray-600">
          {info.source && <span className="truncate max-w-[55%]" title={info.source}>{info.source}</span>}
          {info.dataDate && <span className="flex-shrink-0">· {info.dataDate}</span>}
          <span className={`flex-shrink-0 ${stale.overdue ? 'text-amber-500/90 font-medium' : stale.days === null ? 'text-amber-600/70' : ''}`} title={stale.title}>
            （{stale.label}）
          </span>
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

// ====== 失败指标标签（区分缺失 / 兜底） ======

function FailureChip({ failure }: { failure: ValidityFailure }) {
  const reasonMeta = describeFailReason(failure.reason)
  const name = failure.displayName || failure.key
  const tone = failure.used_fallback
    ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-200'
    : reasonMeta.tone === 'error'
    ? 'bg-red-500/10 border-red-500/30 text-red-200'
    : 'bg-gray-500/10 border-gray-500/30 text-gray-300'

  const titleLines = [
    `${name}（${failure.key}）`,
    `${failure.used_fallback ? '抓取失败·已兜底' : '未获取到数据'} · ${reasonMeta.label}`,
    failure.reasonText || '',
    failure.source ? `来源：${failure.source}` : '',
    failure.days_stale === null || failure.days_stale === undefined
      ? '时效：未知'
      : `时效：${failure.days_stale <= 0 ? '今天' : `${failure.days_stale} 天前`}${failure.dataDate ? `（${failure.dataDate}）` : ''}`,
  ].filter(Boolean)

  return (
    <span
      className={`text-xs px-2 py-0.5 rounded border ${tone}`}
      title={titleLines.join('\n')}
    >
      {failure.used_fallback ? '⚠️ ' : ''}
      {name}
      <span className="opacity-60"> · {reasonMeta.label}</span>
    </span>
  )
}

// ====== 评论高亮标签反查（⛔ 临时补丁，待删） ======

/**
 * @deprecated 临时兼容补丁，不是解法。
 * TODO: 待 scripts/commentary_generator.py 改用 displayName 生成 highlights.key 后，
 *       删除本函数，直接渲染 `h.key`。
 *
 * 存在原因：public/data/commentary.json 仍是 2026-11-08 旧快照，
 * 里面还是 `🇺🇸VIX` / `🌐恐惧贪婪指数` / `🇨🇳AI产业增速` 等错口径标签，
 * 与指标卡的新 displayName 不一致，所以前端按 h.indicator 反查 indicators 强制对齐。
 *
 * 风险：cron 重生 commentary 后，正文标签本身已正确，此反查会变成“两套逻辑并行”。
 * 到期未删即缺陷（龙五 2026-11-09 指定）。
 */
function highlightLabel(h: CommentaryHighlight, indicators: Record<string, IndicatorInfo>): string {
  const info = indicators[h.indicator]
  if (info) {
    const n = resolveDisplayName(info, h.indicator)
    return info.country ? `${info.country}${n}` : n
  }
  // 回退：后端 commentary 拼好的展示串（指标不在 indicators 里时）
  return h.key
}

// ====== 单个维度解读（可折叠） ======

function DimensionCommentaryItem(props: {
  dimId: string
  dimCommentary: DimensionCommentary
  dimLabel: { name: string; icon: string }
  indicators: Record<string, IndicatorInfo>
}) {
  const { dimCommentary, dimLabel, indicators } = props
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
                  title={indicators[h.indicator]?.caliberNote}
                >
                  {highlightLabel(h, indicators)}: {h.value !== null && h.value !== undefined ? h.value.toLocaleString() : 'N/A'}
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
  indicators,
}: {
  commentary: CommentaryData
  meta?: Record<string, DimensionMeta>
  indicators: Record<string, IndicatorInfo>
}) {
  const [iasExpanded, setIasExpanded] = useState(true) // 默认展开
  // 维度名与序一律复用 DIMENSION_ORDER / DIMENSION_LABELS（消除第 3 份重复表）

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
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/25 text-white/70 border border-white/20">
              未回测·非投资建议
            </span>
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
        {DIMENSION_ORDER.map(dimId => {
          const dimCommentary = commentary.dimensions[dimId]
          const dimLabel = DIMENSION_LABELS[dimId]
          if (!dimCommentary || !dimLabel) return null
          return (
            <DimensionCommentaryItem
              key={dimId}
              dimId={dimId}
              dimCommentary={dimCommentary}
              dimLabel={dimLabel}
              indicators={indicators}
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
