// WorldOS 前端口径工具（T5 支撑）
// 契约来源：后端 P0 commit 29d7111 —— scripts/fetch_worldos_data.py
//
// 设计原则（龙六 P0 契约）：
//  1. 前端不解析 dataDate（值格式保留 7 种，仅供人读）；时效一律读后端算好的 days_stale
//  2. days_stale 为 null = 时效未知，绝不当 0 处理
//  3. 指标 key 不参与任何展示逻辑，只做反查句柄

// ====== 类型（与后端 JSON 对齐） ======

export type Cadence = 'daily' | 'monthly' | 'quarterly' | 'yearly'

export type DataDateKind = 'day' | 'month' | 'quarter' | 'cumulative' | 'year'

export type FailReason =
  | 'http_4xx'
  | 'http_5xx'
  | 'empty_response'
  | 'parse_error'
  | 'timeout'
  | 'nan_value'
  | 'not_found'

/** 后端 T13-5 超期等级（单一真源，前端不再自己算阈值） */
export type OverdueLevel = 'none' | 'yellow' | 'red'

/** 后端披露的双档阈值（仅用于 tooltip，不参与判定） */
export interface StalenessRule {
  yellow_days: number
  red_days: number
}

const CADENCE_LABEL: Record<Cadence, string> = {
  daily: '日频',
  monthly: '月频',
  quarterly: '季频',
  yearly: '年频',
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
  if (f === 'daily' || f === 'monthly' || f === 'quarterly' || f === 'yearly') return f
  switch (info.dataDateKind) {
    case 'day':
      return 'daily'
    case 'month':
      return 'monthly'
    case 'year':
      return 'yearly'
    case 'quarter':
    case 'cumulative':
      return 'quarterly'
    default:
      // 兜底跟后端 ALLOWED_FREQUENCIES 的 other → 60/90 一致（取黄线 60，即月频档）
      return 'monthly'
  }
}

export interface StalenessInput extends CadenceInput {
  days_stale?: number | null
  /** 后端 T13：超期等级/布尔/超期天数/双档阈值（前端只读） */
  overdue?: boolean | null
  overdue_level?: string | null
  days_overdue?: number | null
  staleness_rule?: StalenessRule | null
  /** 后端 freshness_level 五态：fresh/realtime/unknown/stale/expired */
  freshness_level?: string | null
  freshness?: string | null
  realtime?: boolean | null
}

export type StalenessKind = 'known' | 'realtime' | 'unknown'

/** T13 五态互斥（单一真源：scripts/indicator_meta.FRESHNESS_STATES） */
export type FreshnessState = 'fresh' | 'realtime' | 'unknown' | 'stale' | 'expired'

export const FRESHNESS_STATE_META: Record<
  FreshnessState,
  { icon: string; label: string; alpha: number; note: string }
> = {
  fresh: { icon: '🟢', label: '已核验新鲜', alpha: 1.0, note: '有可解析日期且未超黄线' },
  realtime: { icon: '🔵', label: '实时报价', alpha: 1.0, note: '实时数据源不提供数据所属期' },
  unknown: {
    icon: '⚪',
    label: '时效未知',
    alpha: 0.5,
    note: '无数据所属期且非实时报价，未能验证新鲜度（按偏旧 α=0.5 计权）',
  },
  stale: { icon: '🟡', label: '偏旧', alpha: 0.5, note: '有日期，已超黄线未超红线' },
  expired: { icon: '🔴', label: '已过期', alpha: 0.0, note: '有日期，已超红线' },
}

/** 旧快照图标→状态（仅当 freshness_level 缺失时使用） */
const ICON_TO_STATE: Record<string, FreshnessState> = {
  '🟢': 'fresh',
  '🟡': 'stale',
  '🔴': 'expired',
  '⚪': 'unknown',
  '🔵': 'realtime',
}

export interface FreshnessInput {
  freshness_level?: string | null
  freshness?: string | null
  realtime?: boolean | null
}

/**
 * 新鲜度状态解析。
 *
 * ⚠️ 必须 `freshness_level` 优先、图标只能当兜底：
 *   T13 之前 ⚪ 表示 realtime，T13 之后 ⚪ 表示 unknown、🔵 才是 realtime —— 图标语义被换过。
 *   而线上快照会有一段时间仍是旧图标（⚪ + level=realtime），只看图标会把实时报价误判成「时效未知」。
 */
export function resolveFreshnessState(info: FreshnessInput | null | undefined): FreshnessState | null {
  if (!info) return null
  const lvl = info.freshness_level
  if (lvl && lvl in FRESHNESS_STATE_META) return lvl as FreshnessState
  if (info.realtime === true) return 'realtime'
  const icon = info.freshness
  if (icon && icon in ICON_TO_STATE) return ICON_TO_STATE[icon]
  return null
}

export interface StalenessInfo {
  /** 归一化天数；null = 无日期（realtime 或 unknown） */
  days: number | null
  /** 是否已超黄线（后端 overdue 为真源；旧快照回退到五态） */
  overdue: boolean
  /** none / yellow / red（后端 overdue_level） */
  overdueLevel: OverdueLevel | null
  /** 超出阈值的天数（后端 days_overdue，仅 tooltip 用） */
  daysOverdue: number | null
  cadence: Cadence
  /** 后端披露的双档阈值，仅 tooltip；缺失为 null（前端不再内置阈值表） */
  rule: StalenessRule | null
  /** known = 有日期；realtime = 实时报价无日期；unknown = 时效未知 */
  kind: StalenessKind
  /** T13 五态；解析不出时为 null */
  state: FreshnessState | null
  /** 展示文案：「今天」「昨天」「N 天前」「实时」「时效未知」 */
  label: string
  /** 悬浮说明 */
  title: string
}

/**
 * 时效计算。只读后端 days_stale，不重算日期。
 *
 * ⚠️ realtime 不能当 unknown 也不能当 0：
 *   🔵 = 实时报价、数据源不提供日期（naturalGas / lmeIndex），timeliness 仍为 1.0
 *   ⚪ = 时效未知（T13：有值但无日期且非 realtime），timeliness = 0.5
 *   两者语义相反 —— 前者是「够新以至于无需日期」，后者是「不知道，按偏旧计权」。
 */
export function computeStaleness(info: StalenessInput): StalenessInfo {
  const cadence = resolveCadence(info)
  const state = resolveFreshnessState(info)
  const rule = info.staleness_rule ?? null

  const raw = info.days_stale
  const known = typeof raw === 'number' && Number.isFinite(raw)
  // 负数（未来日期）钳到 0；null 保持 null，绝不折算成 0
  const days = known ? Math.max(0, Math.trunc(raw as number)) : null

  // 超期判定单一真源在后端：overdue_level → overdue → 五态。前端不再内置阈值表。
  const level: OverdueLevel | null =
    info.overdue_level === 'yellow' || info.overdue_level === 'red' || info.overdue_level === 'none'
      ? info.overdue_level
      : null
  const overdue =
    level !== null
      ? level !== 'none'
      : typeof info.overdue === 'boolean'
      ? info.overdue
      : state === 'stale' || state === 'expired'
  const daysOverdue = typeof info.days_overdue === 'number' ? info.days_overdue : null

  const ruleText = rule ? `（黄线 ${rule.yellow_days} / 红线 ${rule.red_days} 天）` : ''
  const levelText = level === 'red' ? ' —— 已超红线' : level === 'yellow' ? ' —— 已超黄线' : ''

  if (days !== null) {
    const label = days === 0 ? '今天' : days === 1 ? '昨天' : `${days} 天前`
    let title = `${CADENCE_LABEL[cadence]}数据，数据所属期距今 ${days} 天${ruleText}${levelText}`
    if (state) title += `；后端判定：${FRESHNESS_STATE_META[state].label}`
    if (daysOverdue !== null && daysOverdue > 0) title += `；超出 ${daysOverdue} 天`
    return { days, overdue, overdueLevel: level, daysOverdue, cadence, rule, kind: 'known', state, label, title }
  }

  if (state === 'realtime') {
    return {
      days: null,
      overdue,
      overdueLevel: level,
      daysOverdue,
      cadence,
      rule,
      kind: 'realtime',
      state,
      label: '实时',
      title: `${FRESHNESS_STATE_META.realtime.label}：${FRESHNESS_STATE_META.realtime.note}`,
    }
  }

  return {
    days: null,
    overdue,
    overdueLevel: level,
    daysOverdue,
    cadence,
    rule,
    kind: 'unknown',
    state,
    label: '时效未知',
    title: `${FRESHNESS_STATE_META.unknown.label}：${FRESHNESS_STATE_META.unknown.note}`,
  }
}

/** freshness 徽标语义（后端 P0/D+ 收窄定义，T13 五态互斥）
 *
 * T13：⚪ 不再一码两用。旧实现 realtime（实时报价·源无日期）与 unknown（不知道多旧）
 * 都画 ⚪，语义相反却看着一样。现：🔵=实时，⚪=未知（α=0.5，按偏旧计权）。
 */
export function describeFreshness(freshness?: string | null, freshnessLevel?: string | null): string {
  // 以 freshness_level 为准（图标在老快照里可能还是旧语义）
  if (freshnessLevel === 'realtime') return '实时报价·数据源未提供日期'
  if (freshnessLevel === 'unknown') return '时效未知：无数据所属期，按偏旧（α=0.5）计权'
  switch (freshness) {
    case '🔵':
      return '实时报价·数据源未提供日期'
    case '⚪':
      return '时效未知：无数据所属期，按偏旧（α=0.5）计权'
    case '🟢':
      return '已核验新鲜（有日期且未超阈值）'
    case '🟡':
      return '偏旧'
    case '🔴':
      return '已过期'
    default:
      return '新鲜度未知'
  }
}

/** excluded_from_scoring 的原因文案（后端 exclusion_reason） */
export function describeExclusion(reason?: string | null): string {
  switch (reason) {
    case 'reference_only':
      return '参考项：仅展示，不参与打分'
    case 'no_score':
      return '无评分参数或无值，未计入综合评分'
    case 'expired_alpha0':
      return '数据过期 α=0，已剔出加权'
    default:
      return '未计入综合评分'
  }
}

// ====== 指标行最终状态（App 与夹具校验共用的唯一实现） ======

export interface IndicatorStateInput extends StalenessInput {
  reference_only?: boolean | null
  excluded_from_scoring?: boolean | null
  exclusion_reason?: string | null
  timeliness?: number | null
}

export interface IndicatorState {
  stale: StalenessInfo
  /** T13 五态（新鲜度） */
  state: FreshnessState | null
  /** 轴一：数据旧了（描灰） */
  dimmed: boolean
  /** 轴二：没进综合评分 */
  excluded: boolean
  notCounted: boolean
  /** 物理上只可能为一个（一行禁叠两个标） */
  exclusionBadge: { text: string; title: string } | null
}

/**
 * 指标行状态判定——双轴模型：
 *   轴一 dimmed（数据旧了）= 超阈值天数，单一真源
 *   轴二 not_counted（没进综合评分）= excluded_from_scoring
 * reference_only 优先且排他：只挂「参考项」，不叠描灰。
 */
export function describeIndicatorState(info: IndicatorStateInput): IndicatorState {
  const stale = computeStaleness(info)
  const isRef = info.reference_only === true
  const state = stale.state

  // 描灰口径（T13 冻结契约 docs/freshness-contract.md）：
  //   「描灰只看有日期的超阈值，days_stale=null 不描灰（未知 ≠ 0 天）」
  // 优先用后端状态：stale=超黄线、expired=超红线，阈值已在 TIMELINESS_RULES 里判完，
  // 前端不再另设阈值（否则 daily 4 天后端判 fresh、前端会误描灰）。
  // 描灰口径（T13 冻结契约 docs/freshness-contract.md）：
  //   「描灰只看有日期的超阈值，days_stale=null 不描灰（未知 ≠ 0 天）」
  // 阈值单一真源在后端：优先 overdue_level → overdue → 五态，前端无内置阈值表。
  const datedOverdue =
    stale.days === null
      ? false
      : stale.overdueLevel !== null
      ? stale.overdueLevel !== 'none'
      : typeof info.overdue === 'boolean'
      ? info.overdue
      : state === 'stale' || state === 'expired'

  // 被排除计分的行不再描灰：排除标是更强的声明（“这值根本没参与打分”），
  // 再叠一层描灰（“这值可能误导你”）属于视觉过载。数据旧的信号由副行「N 天前」傅达。
  const excluded =
    typeof info.excluded_from_scoring === 'boolean'
      ? info.excluded_from_scoring
      : isRef || info.timeliness === 0 // 老快照（无新字段）回退
  const notCounted = excluded && !isRef

  const dimmed = datedOverdue && !excluded

  const exclusionBadge: IndicatorState['exclusionBadge'] = isRef
    ? { text: '参考项', title: describeExclusion('reference_only') }
    : notCounted
    ? {
        text:
          info.exclusion_reason === 'no_score'
            ? '无评分'
            : info.exclusion_reason === 'expired_alpha0'
            ? '过期剔除'
            : '不计分',
        title: describeExclusion(info.exclusion_reason),
      }
    : null

  return { stale, state, dimmed, excluded, notCounted, exclusionBadge }
}

// ====== 维度计数口径 ======

export interface DimensionCountsInput {
  active_count?: number | null
  valid_count?: number | null
  reference_only_count?: number | null
  required_count?: number | null
}

export interface DimensionCounts {
  /** 真正计分的指标数（α>0） */
  scoring: number
  /** 参考项（只展示不计分） */
  referenceOnly: number
  /** 已剔除（α=0 / 无评分），不计入 scoring 但与 referenceOnly 不同 */
  excluded: number
  required: number | null
}

/**
 * 维度计数口径（active_count ≠ 计分项）。
 *
 * active_count = 非参考项总数；valid_count = 其中真正计分的。
 * 例：usGdp 被 expired_alpha0 剔出后，economic 是 active 6 / valid 5，
 * 写「6 项计分」就撒谎了。
 */
export function resolveDimensionCounts(d: DimensionCountsInput | null | undefined): DimensionCounts {
  const active = typeof d?.active_count === 'number' ? d.active_count : null
  const valid = typeof d?.valid_count === 'number' ? d.valid_count : null
  const scoring = valid ?? active ?? 0
  const referenceOnly = typeof d?.reference_only_count === 'number' ? d.reference_only_count : 0
  const excluded = Math.max(0, (active ?? scoring) - scoring)
  const required = typeof d?.required_count === 'number' ? d.required_count : null
  return { scoring, referenceOnly, excluded, required }
}

/** IAS 数据覆盖分档（降级判断只看 data_coverage，不看 scale_coverage） */
export type CoverageTier = 'ok' | 'partial' | 'insufficient'

export function resolveCoverageTier(dataCoverage?: number | null): CoverageTier {
  if (typeof dataCoverage !== 'number' || !Number.isFinite(dataCoverage)) return 'ok'
  if (dataCoverage < 0.6) return 'insufficient'
  if (dataCoverage < 0.8) return 'partial'
  return 'ok'
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
