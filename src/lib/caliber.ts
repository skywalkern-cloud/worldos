// WorldOS 前端口径工具（T5 支撑）
// 契约来源：后端 P0 commit 29d7111 —— scripts/fetch_worldos_data.py
//
// 设计原则（龙六 P0 契约）：
//  1. 前端不解析 dataDate（值格式保留 7 种，仅供人读）；时效一律读后端算好的 days_stale
//  2. days_stale 为 null = 时效未知，绝不当 0 处理
//  3. 指标 key 不参与任何展示逻辑，只做反查句柄

// ====== 类型（与后端 JSON 对齐） ======

export type Cadence = 'daily' | 'monthly' | 'quarterly'

export type DataDateKind = 'day' | 'month' | 'quarter' | 'cumulative' | 'year'

export type FailReason =
  | 'http_4xx'
  | 'http_5xx'
  | 'empty_response'
  | 'parse_error'
  | 'timeout'
  | 'nan_value'
  | 'not_found'

/** 龙五 T5-1 阈值（严格大于即超阈值） */
export const OVERDUE_THRESHOLD_DAYS: Record<Cadence, number> = {
  daily: 3,
  monthly: 40,
  quarterly: 120,
}

const CADENCE_LABEL: Record<Cadence, string> = {
  daily: '日频',
  monthly: '月频',
  quarterly: '季频',
}

export interface CadenceInput {
  frequency?: string | null
  dataDateKind?: DataDateKind | null
}

/**
 * 阈值档位解析。
 *
 * 优先用 frequency（后端语义真源）。frequency 不在三档内时（实测 oilPrice
 * 为 "other"）回退到 dataDateKind 推断，避免落进无阈值分支。
 */
export function resolveCadence(info: CadenceInput): Cadence {
  const f = info.frequency
  if (f === 'daily' || f === 'monthly' || f === 'quarterly') return f
  switch (info.dataDateKind) {
    case 'day':
      return 'daily'
    case 'month':
      return 'monthly'
    case 'quarter':
    case 'cumulative':
      return 'quarterly'
    default:
      // 兜底取最宽松档，宁可漏报灰化也不误报「过期」
      return 'quarterly'
  }
}

export interface StalenessInput extends CadenceInput {
  days_stale?: number | null
}

export interface StalenessInfo {
  /** 归一化天数；null = 时效未知 */
  days: number | null
  overdue: boolean
  cadence: Cadence
  thresholdDays: number
  /** 展示文案：「今天」「昨天」「N 天前」「时效未知」 */
  label: string
  /** 悬浮说明 */
  title: string
}

/**
 * 时效计算。只读后端 days_stale，不重算日期。
 */
export function computeStaleness(info: StalenessInput): StalenessInfo {
  const cadence = resolveCadence(info)
  const thresholdDays = OVERDUE_THRESHOLD_DAYS[cadence]

  const raw = info.days_stale
  const known = typeof raw === 'number' && Number.isFinite(raw)
  // 负数（未来日期）钳到 0；null 保持 null，绝不折算成 0
  const days = known ? Math.max(0, Math.trunc(raw as number)) : null
  const overdue = days !== null && days > thresholdDays

  let label: string
  let title: string
  if (days === null) {
    label = '时效未知'
    title = '后端未能确定数据所属期，时效未知（非 0 天）'
  } else {
    label = days === 0 ? '今天' : days === 1 ? '昨天' : `${days} 天前`
    title = `${CADENCE_LABEL[cadence]}数据，数据所属期距今 ${days} 天（超阈值线 ${thresholdDays} 天）`
    if (overdue) title += ' —— 已超阈值，数据可能已失效'
  }

  return { days, overdue, cadence, thresholdDays, label, title }
}

// ====== 名称解析（T1 单一真源） ======

export interface NameInput {
  displayName?: string | null
  shortName?: string | null
  name?: string | null
}

/**
 * 优先 displayName，回退 name，再回退 shortName。
 * 不在前端维护第二份名称表（T1 的目标就是收敛真源）。
 */
export function resolveDisplayName(info: NameInput | null | undefined, fallback = '—'): string {
  if (!info) return fallback
  return info.displayName || info.name || info.shortName || fallback
}

export function resolveShortName(info: NameInput | null | undefined, fallback = '—'): string {
  if (!info) return fallback
  return info.shortName || info.displayName || info.name || fallback
}

// ====== 失败原因（validity_report.failed[].reason） ======

export interface FailReasonMeta {
  label: string
  /** tone 决定前端配色：error = 真失败；warn = 兜底/可重试；muted = 无数据源 */
  tone: 'error' | 'warn' | 'muted'
}

const FAIL_REASON_META: Record<FailReason, FailReasonMeta> = {
  http_4xx: { label: '接口拒绝（4xx）', tone: 'error' },
  http_5xx: { label: '上游故障（5xx）', tone: 'warn' },
  empty_response: { label: '空响应', tone: 'warn' },
  parse_error: { label: '解析失败', tone: 'error' },
  timeout: { label: '请求超时', tone: 'warn' },
  nan_value: { label: '数值非法', tone: 'error' },
  not_found: { label: '数据源无记录', tone: 'muted' },
}

export function describeFailReason(reason?: string | null): FailReasonMeta {
  if (reason && reason in FAIL_REASON_META) {
    return FAIL_REASON_META[reason as FailReason]
  }
  return { label: reason || '未知原因', tone: 'muted' }
}

// ====== P1 预留：指标贡献度 ======

export interface ContributionEntry {
  score: number
  weight: number
  contribution: number
}

/**
 * 贡献度兜底计算。P1 后端未给 indicators 明细时，前端按 score × weight 现算。
 * reference_only 的指标由调用方先过滤掉（不参与打分）。
 */
export function computeContribution(score: number | null, weight: number): number {
  if (score === null || !Number.isFinite(score)) return 0
  if (!Number.isFinite(weight)) return 0
  return score * weight
}
