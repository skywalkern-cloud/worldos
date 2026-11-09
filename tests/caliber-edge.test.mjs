// 边界状态夹具校验 —— 用真代码（src/lib/caliber.ts）跑合成夹具，把线上零触发的分支钉住。
//
// 运行：node --experimental-strip-types tests/caliber-edge.test.mjs
// 夹具：tests/fixtures/market-data-edge-cases.json（scripts/make_fixture_edge_cases.py 生成）
// 契约：docs/freshness-contract.md（T13 五态互斥，2026-11-09 冻结）
//
// 2026-11-09 T13：新鲜度从三态改五态（🟢🔵⚪🟡🔴），⚪ 语义反转（原 realtime → 现 unknown）。
// 本脚本重点钉住「以 freshness_level 为准、图标只当兜底」，因为线上快照会有一段时间仍是旧图标。

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import {
  describeIndicatorState,
  resolveCoverageTier,
  resolveFreshnessState,
  computeStaleness,
  resolveDisplayName,
  describeFreshness,
  resolveDimensionCounts,
  resolveScoreTone,
  describeFailureStatus,
  roundHalfUp,
  formatSigned,
  formatDecimal,
  resolveIasKeyword,
  resolveIasLevel,
  stripSignalSuffix,
  FRESHNESS_STATE_META,
} from '../src/lib/caliber.ts'
import { getKeyword } from '../src/data/score-keywords.ts'

const here = dirname(fileURLToPath(import.meta.url))
const load = p => JSON.parse(readFileSync(resolve(here, p), 'utf8'))

const fixture = load('./fixtures/market-data-edge-cases.json')
const real = load('../public/data/market-data.json')

let pass = 0
const failures = []

function check(name, cond, detail = '') {
  if (cond) {
    pass++
    console.log(`  ✅ ${name}`)
  } else {
    failures.push(`${name}${detail ? ` — ${detail}` : ''}`)
    console.log(`  ❌ ${name}${detail ? ` — ${detail}` : ''}`)
  }
}

// ------------------------------------------------------- [0] 五态表完整性
console.log('\n[0] T13 五态表与文档一致（图标/α 唯一）')
{
  const expect = {
    fresh: ['🟢', 1.0],
    realtime: ['🔵', 1.0],
    unknown: ['⚪', 0.5],
    stale: ['🟡', 0.5],
    expired: ['🔴', 0.0],
  }
  check('五个状态不多不少', Object.keys(FRESHNESS_STATE_META).length === 5)
  for (const [k, [icon, alpha]] of Object.entries(expect)) {
    const m = FRESHNESS_STATE_META[k]
    check(`${k}: 图标 ${icon}`, m?.icon === icon, m?.icon)
    check(`${k}: α=${alpha}`, m?.alpha === alpha, String(m?.alpha))
  }
  const icons = Object.values(FRESHNESS_STATE_META).map(m => m.icon)
  check('一态一图标，无重复', new Set(icons).size === icons.length, icons.join(''))
  check('⚪ 不再是 realtime 的图标', FRESHNESS_STATE_META.realtime.icon !== '⚪')
}

// ------------------------------------------------------- [1] 老快照兼容（最关键）
console.log('\n[1] 老快照兼容：图标仍是旧语义 ⚪，但 freshness_level=realtime')
{
  // 不依赖快照巧合 —— 手造一个旧快照样本（T13 前 realtime 画 ⚪）
  const legacyRealtime = {
    freshness: '⚪',
    freshness_level: 'realtime',
    realtime: true,
    days_stale: null,
    frequency: 'daily',
  }
  const st = resolveFreshnessState(legacyRealtime)
  check('⚪ + level=realtime → 解析为 realtime（不是 unknown）', st === 'realtime', String(st))
  const cs = computeStaleness(legacyRealtime)
  check('同上：label=实时（不是「时效未知」）', cs.label === '实时', cs.label)
  check('同上：days=null 且不描灰', cs.days === null && describeIndicatorState(legacyRealtime).dimmed === false)

  // 对照：T13 后的真 unknown（⚪ 且无 realtime）不能被误当实时
  const realUnknown = { freshness: '⚪', freshness_level: 'unknown', realtime: false, days_stale: null, frequency: 'daily' }
  check('⚪ + level=unknown → unknown', resolveFreshnessState(realUnknown) === 'unknown')
  check('unknown label=时效未知', computeStaleness(realUnknown).label === '时效未知')

  // level 缺失时才看图标
  check('仅图标 🔵 → realtime', resolveFreshnessState({ freshness: '🔵' }) === 'realtime')
  check('仅图标 ⚪ → unknown', resolveFreshnessState({ freshness: '⚪' }) === 'unknown')
  check('realtime 布尔优先于图标', resolveFreshnessState({ freshness: '⚪', realtime: true }) === 'realtime')
}

// ------------------------------------------------------- [2] 五态语义（夹具）
console.log('\n[2] 夹具五态 → kind / label 映射正确')
{
  const byState = {}
  for (const [k, v] of Object.entries(fixture.indicators)) {
    const s = resolveFreshnessState(v)
    ;(byState[s] ??= []).push(k)
  }
  check('夹具覆盖 fresh', (byState.fresh ?? []).length > 0)
  check('夹具覆盖 realtime', (byState.realtime ?? []).length > 0)
  check('夹具覆盖 unknown', (byState.unknown ?? []).length > 0)
  check('夹具覆盖 expired', (byState.expired ?? []).length > 0)

  for (const [k, v] of Object.entries(fixture.indicators)) {
    const s = resolveFreshnessState(v)
    const cs = computeStaleness(v)
    if (s === 'realtime') check(`${k}: realtime → kind=realtime/label=实时`, cs.kind === 'realtime' && cs.label === '实时')
    if (s === 'unknown') check(`${k}: unknown → kind=unknown/label=时效未知`, cs.kind === 'unknown' && cs.label === '时效未知', cs.label)
    if (cs.days !== null) check(`${k}: 有日期 → kind=known`, cs.kind === 'known')
  }
}

// ------------------------------------------------------- [3] 描灰口径（冻结契约）
console.log('\n[3] 描灰口径：overdue === true 才描；无日期（days_overdue=null）一律不描')
{
  for (const [k, v] of Object.entries(fixture.indicators)) {
    const st = describeIndicatorState(v)
    if (v.days_overdue === null || v.days_stale === null) {
      check(`${k}: 无日期 → 不描灰`, st.dimmed === false, `state=${st.state}`)
    } else {
      check(`${k}: 描灰 = overdue 布尔值`, st.dimmed === (v.overdue === true), `overdue=${v.overdue} dimmed=${st.dimmed}`)
    }
  }
  const unknownItems = Object.entries(fixture.indicators).filter(([, v]) => resolveFreshnessState(v) === 'unknown')
  check('unknown 项存在且全部不描灰', unknownItems.length > 0 && unknownItems.every(([, v]) => !describeIndicatorState(v).dimmed))
  const realtimeItems = Object.entries(fixture.indicators).filter(([, v]) => resolveFreshnessState(v) === 'realtime')
  check('realtime 项存在且全部不描灰', realtimeItems.length > 0 && realtimeItems.every(([, v]) => !describeIndicatorState(v).dimmed))
}

// ------------------------------------------------------- [4] 排除标三态
console.log('\n[4] 排除标：reference_only / no_score / expired_alpha0 文案各异')
{
  const groups = {
    reference_only: ['参考项', 'reference_only'],
    no_score: ['无评分', 'no_score'],
    expired_alpha0: ['过期剔除', 'expired_alpha0'],
  }
  for (const [reason, [text, key]] of Object.entries(groups)) {
    const items = Object.entries(fixture.indicators).filter(([, v]) => v.exclusion_reason === key)
    check(`夹具存在 ${key} 样本`, items.length > 0, `count=${items.length}`)
    for (const [k, v] of items) {
      const st = describeIndicatorState(v)
      check(`${k}: 标=${text}`, st.exclusionBadge?.text === text, st.exclusionBadge?.text)
      if (key === 'reference_only') check(`${k}: 参考项不描灰`, st.dimmed === false)
    }
  }
}

// ------------------------------------------------------- [5] 维度置灰
console.log('\n[5] 维度置灰 → insufficient_data=true 且 score=null')
{
  const greyed = Object.entries(fixture.meta.dimensions).filter(([, d]) => d.insufficient_data === true)
  check('夹具存在置灰维度', greyed.length > 0, `count=${greyed.length}`)
  for (const [k, d] of greyed) {
    check(`${k}: insufficient_data=true`, d.insufficient_data === true)
    check(`${k}: score=null（不是 0）`, d.score === null, JSON.stringify(d.score))
  }
  const live = Object.values(fixture.meta.dimensions).filter(d => d.insufficient_data !== true)
  check('非置灰维度 score 非 null', live.every(d => typeof d.score === 'number'))
}

// ------------------------------------------------------- [6] 覆盖率分档
console.log('\n[6] 覆盖率分档：降级只看 data_coverage，scale_coverage 仅披露')
{
  check('夹具 data_coverage 落 partial', resolveCoverageTier(fixture.meta.ias.data_coverage) === 'partial', `coverage=${fixture.meta.ias.data_coverage}`)
  check('is_actionable 仍 true', fixture.meta.ias.is_actionable === true)
  check('signal 带「部分维度缺失」后缀', /部分维度缺失/.test(fixture.meta.ias.signal), fixture.meta.ias.signal)
  check('0.59 → insufficient', resolveCoverageTier(0.59) === 'insufficient')
  check('0.60 → partial', resolveCoverageTier(0.6) === 'partial')
  check('0.79 → partial', resolveCoverageTier(0.79) === 'partial')
  check('0.80 → ok', resolveCoverageTier(0.8) === 'ok')
  check('null → ok（不降级）', resolveCoverageTier(null) === 'ok')
}

// ------------------------------------------------------- [7] degraded 结构变更
console.log('\n[7] validity_report.degraded 由计数改为列表（T13 契约变更）')
{
  const vr = fixture.validity_report
  check('夹具 degraded 是列表', Array.isArray(vr.degraded), typeof vr.degraded)
  check('有 degraded_count 兼容字段', typeof vr.degraded_count === 'number', String(vr.degraded_count))
  check('列表长度与 degraded_count 一致', vr.degraded.length === vr.degraded_count, `${vr.degraded.length} vs ${vr.degraded_count}`)
  const reasons = new Set(vr.degraded.map(d => d.reason))
  check('reason 枚举只含 no_date / used_fallback', [...reasons].every(r => ['no_date', 'used_fallback'].includes(r)), [...reasons].join(','))
  check('no_date 项确实是 unknown 态', vr.degraded.filter(d => d.reason === 'no_date').every(d => resolveFreshnessState(d) === 'unknown'))

  const realVr = real.validity_report
  check('真实快照仍是旧结构（数字），前端需兼容', typeof realVr.degraded === 'number' || Array.isArray(realVr.degraded), typeof realVr.degraded)
}

// ------------------------------------------------------- [8] 全局不变量
console.log('\n[8] 全局不变量')
{
  for (const [label, data] of [['夹具', fixture], ['真实快照', real]]) {
    const all = Object.entries(data.indicators)
    const doubleBadge = all.filter(([, v]) => {
      const st = describeIndicatorState(v)
      return st.exclusionBadge !== null && st.dimmed && v.reference_only === true
    })
    check(`${label}: 参考项不同时描灰`, doubleBadge.length === 0, doubleBadge.map(([k]) => k).join(','))

    const badName = all.filter(([, v]) => !resolveDisplayName(v, ''))
    check(`${label}: 名称全部可解析`, badName.length === 0)

    const unclear = all.filter(([, v]) => describeFreshness(v.freshness, v.freshness_level) === '新鲜度未知')
    check(`${label}: freshness 全部可解释`, unclear.length === 0, unclear.map(([k]) => k).join(','))

    const noState = all.filter(([, v]) => resolveFreshnessState(v) === null)
    check(`${label}: 每个指标都有五态之一`, noState.length === 0, noState.map(([k]) => k).join(','))
  }
}

// ------------------------------------------------------- [9] 真实快照回归
console.log('\n[9] 真实快照回归（public/data/market-data.json）')
{
  const all = Object.entries(real.indicators)
  check('指标数 30', all.length === 30, `count=${all.length}`)

  const dimmed = all.filter(([, v]) => describeIndicatorState(v).dimmed).map(([k]) => k).sort()
  check('描灰 = oilPrice(yellow) + usGdp(red)', dimmed.join(',') === 'oilPrice,usGdp', dimmed.join(','))

  const badges = all.filter(([, v]) => describeIndicatorState(v).exclusionBadge)
  check('排除标 3 个', badges.length === 3, badges.map(([k]) => k).join(','))
  check(
    '排除标 = usGdp(过期剔除) + aiGrowth/robotInstall(参考项)',
    badges.map(([k]) => k).sort().join(',') === 'aiGrowth,robotInstall,usGdp',
    badges.map(([k]) => k).join(',')
  )

  const states = {}
  for (const [, v] of all) {
    const s = resolveFreshnessState(v)
    states[s] = (states[s] ?? 0) + 1
  }
  check('状态分布 fresh26/expired1/stale1/realtime2', states.fresh === 26 && states.expired === 1 && states.stale === 1 && states.realtime === 2, JSON.stringify(states))

  const rt = all.filter(([, v]) => resolveFreshnessState(v) === 'realtime')
  check('realtime 2 个且 days=null', rt.length === 2 && rt.every(([, v]) => computeStaleness(v).days === null), rt.map(([k]) => k).join(','))

  check('usGdp 223 天 → expired（红线 210）', resolveFreshnessState(real.indicators.usGdp) === 'expired')
  check('usGdp overdue_level=red、days_overdue=13', real.indicators.usGdp.overdue_level === 'red' && real.indicators.usGdp.days_overdue === 13)
  // 龙五 12:00 指定要盯的两个
  check('usGdp 走 expired_alpha0（已剔出评分）', real.indicators.usGdp.exclusion_reason === 'expired_alpha0' && real.indicators.usGdp.excluded_from_scoring === true)
  check('naturalGas 🔵 realtime', real.indicators.naturalGas.freshness === '🔵' && resolveFreshnessState(real.indicators.naturalGas) === 'realtime')
  check('lmeIndex 🔵 realtime', real.indicators.lmeIndex.freshness === '🔵' && resolveFreshnessState(real.indicators.lmeIndex) === 'realtime')
  check('usGdp 文案 =「过期 223 天」', computeStaleness(real.indicators.usGdp).label === '过期 223 天', computeStaleness(real.indicators.usGdp).label)
  check('oilPrice 文案 =「偏旧 9 天」', computeStaleness(real.indicators.oilPrice).label === '偏旧 9 天', computeStaleness(real.indicators.oilPrice).label)
}

// ------------------------------------------------------- [10] T13-5 超期字段单一真源
console.log('\n[10] overdue / overdue_level / days_overdue / staleness_rule（前端不再内置阈值表）')
{
  const all = Object.entries(real.indicators)
  check('每个指标都有 overdue', all.every(([, v]) => typeof v.overdue === 'boolean'))
  check('每个指标都有 overdue_level', all.every(([, v]) => ['none', 'yellow', 'red'].includes(v.overdue_level)))
  check('每个指标都有 staleness_rule', all.every(([, v]) => v.staleness_rule && typeof v.staleness_rule.yellow_days === 'number' && typeof v.staleness_rule.red_days === 'number'))
  check('无日期的指标 days_overdue=null', all.filter(([, v]) => v.days_stale === null).every(([, v]) => v.days_overdue === null))
  check('有日期且未超 → days_overdue=0', all.filter(([, v]) => v.overdue_level === 'none' && v.days_stale !== null).every(([, v]) => v.days_overdue === 0))

  // 后端字段优先于本地推断
  const fake = { days_stale: 4, frequency: 'daily', overdue: false, overdue_level: 'none', days_overdue: 0, staleness_rule: { yellow_days: 5, red_days: 10 } }
  check('daily 4 天：后端说 none → 不描灰（前端不自行按旧 3 天表误判）', describeIndicatorState(fake).dimmed === false)
  const fake2 = { days_stale: 4, frequency: 'daily', overdue: true, overdue_level: 'yellow', days_overdue: 1, staleness_rule: { yellow_days: 3, red_days: 10 } }
  check('daily 4 天：后端说 yellow → 描灰', describeIndicatorState(fake2).dimmed === true)

  // staleness_rule 进 tooltip
  const t = computeStaleness(real.indicators.usGdp).title
  check('tooltip 含黄/红阈值', /黄线 120/.test(t) && /红线 210/.test(t), t)
  check('tooltip 含超出天数', /超出 13 天/.test(t), t)

  // 无日期一律不描灰（即使后端误给 overdue）
  const contradiction = { days_stale: null, frequency: 'daily', overdue: true, overdue_level: 'red', realtime: false, freshness_level: 'unknown' }
  check('无日期时即使 overdue=true 也不描灰（契约优先级）', describeIndicatorState(contradiction).dimmed === false)
}

// ------------------------------------------------------- [11] 维度计数口径
console.log('\n[11] 维度计数：active_count ≠ 计分项')
{
  const counts = resolveDimensionCounts(real.meta.dimensions.economic)
  check('economic: scoring=5（usGdp 已剔除）', counts.scoring === 5, JSON.stringify(counts))
  check('economic: excluded=1', counts.excluded === 1, JSON.stringify(counts))
  check('economic: 不把 active_count 6 当计分项', counts.scoring !== real.meta.dimensions.economic.active_count)

  const tg = resolveDimensionCounts(real.meta.dimensions.techGreen)
  check('techGreen: scoring=2 / referenceOnly=2', tg.scoring === 2 && tg.referenceOnly === 2, JSON.stringify(tg))

  // 边界
  check('缺字段不烙', JSON.stringify(resolveDimensionCounts({})) === JSON.stringify({ scoring: 0, referenceOnly: 0, excluded: 0, required: null }))
  check('只有 active 无 valid 时回退', resolveDimensionCounts({ active_count: 4 }).scoring === 4)
  check('excluded 不为负', resolveDimensionCounts({ active_count: 2, valid_count: 5 }).excluded === 0)
}

// ------------------------------------------------------- [12] 参考项着色（龙五必修 1）
console.log('\n[12] 不计分 = 中性色：判定只认 excluded，不按 exclusion_reason 分头')
{
  const cases = Object.entries(real.indicators).filter(([, v]) =>
    describeIndicatorState(v).excluded
  )
  check('真实快照有 excluded 样本', cases.length > 0, `count=${cases.length}`)
  for (const [k, v] of cases) {
    const st = describeIndicatorState(v)
    check(`${k}(${v.exclusion_reason}) 着色 = neutral`, resolveScoreTone(v.score, { excluded: st.excluded }) === 'neutral', `score=${v.score} reason=${v.exclusion_reason}`)
  }

  // 四种理由必须走同一条颜色规则（防止只修 reference_only 那一支）
  for (const reason of ['reference_only', 'expired_alpha0', 'no_score']) {
    const fake = { score: -0.9, excluded_from_scoring: true, exclusion_reason: reason, reference_only: reason === 'reference_only' }
    const st = describeIndicatorState(fake)
    check(`${reason}: excluded=true → neutral`, st.excluded === true && resolveScoreTone(fake.score, { excluded: st.excluded }) === 'neutral')
  }

  // 具体盯住龙五点名的那一行
  const usGdp = real.indicators.usGdp
  const usSt = describeIndicatorState(usGdp)
  check('usGdp score=-0.17（负分）', usGdp.score < 0, String(usGdp.score))
  check('usGdp excluded=true', usSt.excluded === true)
  check('usGdp 着色 neutral（不再是红）', resolveScoreTone(usGdp.score, { excluded: usSt.excluded }) === 'neutral')
  check('usGdp 徽标仍为「过期剔除」', usSt.exclusionBadge?.text === '过期剔除')

  // 非排除项不受影响
  check('普通负分仍 negative', resolveScoreTone(-0.9, { excluded: false }) === 'negative')
  check('普通正分仍 positive', resolveScoreTone(0.9, { excluded: false }) === 'positive')
  check('null 分数 neutral', resolveScoreTone(null, { excluded: false }) === 'neutral')
  const normalNeg = Object.entries(real.indicators).filter(([, v]) => !describeIndicatorState(v).excluded && v.score < 0)
  check('非排除的负分项仍保留红色', normalNeg.length > 0 && normalNeg.every(([, v]) => resolveScoreTone(v.score, { excluded: false }) === 'negative'), `count=${normalNeg.length}`)
}

// ------------------------------------------------------- [13] 兜底 ≠ 缺失（龙五必修 2）
console.log('\n[13] 失败状态两分：已兜底（有值不可信） vs 数据源无记录（没值）')
{
  const failed = real.validity_report.failed
  check('真实快照 failed 有 2 条', failed.length === 2, `count=${failed.length}`)

  const oil = failed.find(f => f.key === 'oilPrice')
  const epu = failed.find(f => f.key === 'epu')
  check('oilPrice 在 failed 里且 used_fallback=true', oil?.used_fallback === true)
  check('epu 在 failed 里且 used_fallback=false', epu?.used_fallback === false)

  const oilStatus = describeFailureStatus(oil)
  const epuStatus = describeFailureStatus(epu)
  check('oilPrice → variant=fallback', oilStatus.variant === 'fallback')
  check('oilPrice 文案含「已兜底」且带天数', /已兜底/.test(oilStatus.text) && /9 天前/.test(oilStatus.text), oilStatus.text)
  check('epu → variant=hard', epuStatus.variant === 'hard')
  check('epu 文案是「数据源无记录」，不含「兜底」', epuStatus.text === '数据源无记录' && !/兜底/.test(epuStatus.text), epuStatus.text)
  check('两者文案不相同', oilStatus.text !== epuStatus.text, `${oilStatus.text} vs ${epuStatus.text}`)

  // 无日期兜底不能写成「0 天前」
  const noDate = describeFailureStatus({ used_fallback: true, days_stale: null })
  check('兜底且无日期 → 不写 0 天前', /无日期/.test(noDate.text) && !/今天/.test(noDate.text), noDate.text)
}

// ------------------------------------------------------- [14] 定点舍入（与后端 T15-1 同口径）
console.log('\n[14] half-up-away-from-zero：不能用 toFixed / 裸 Math.round')
{
  check('toFixed(4) 的错值（作为对照）', (-0.07335).toFixed(4) === '-0.0733')
  check('-0.07335 → 4位 = -0.0734', roundHalfUp(-0.07335, 4).toFixed(4) === '-0.0734', roundHalfUp(-0.07335, 4).toFixed(4))
  check('-0.07335 → 3位 = -0.073', roundHalfUp(-0.07335, 3).toFixed(3) === '-0.073')
  check('-0.245 → 2位 = -0.25（away from zero）', roundHalfUp(-0.245, 2).toFixed(2) === '-0.25')
  check('0.245 → 2位 = 0.25', roundHalfUp(0.245, 2).toFixed(2) === '0.25')
  check('0.125 → 2位 = 0.13（不是 banker 的 0.12）', roundHalfUp(0.125, 2).toFixed(2) === '0.13', roundHalfUp(0.125, 2).toFixed(2))
  check('NaN 不抛错', Number.isNaN(roundHalfUp(NaN)))

  check('formatSigned 正数带 +', formatSigned(0.5, 2) === '+0.50')
  check('formatSigned 负数不带多余符号', formatSigned(-0.5, 2) === '-0.50')
  check('formatSigned null → 占位', formatSigned(null, 2, '-') === '-')
  check('formatDecimal 缺省占位', formatDecimal(undefined) === '—')

  // 与后端实际值对账。
  //
  // 2026-11-09 R-07 同型病修复：这里原本写死了「上一份快照」的数字
  // （-0.07335 / -0.0734 / -0.34 / -0.073350），16:40 新数据落地后（IAS -0.38 持有）
  // 无故飘红 4 条。契约是「展示 = roundHalfUp(真值, 位数)」，**具体数字不是契约**，
  // 故改为拿同一份 live 值自证。数据换日不再误报。
  const norm = real.meta.ias.normalized
  // 与 formatSigned 的符号约定对齐（>0 加 '+'），避免正数日假红
  const expectSigned = (v, places) => {
    const s = roundHalfUp(v, places).toFixed(places)
    return v > 0 ? `+${s}` : s
  }
  const normShown = formatSigned(norm, 4)
  check('卡上 normalized 展示 = roundHalfUp(真值, 4)', normShown === expectSigned(norm, 4), `${normShown} vs ${expectSigned(norm, 4)}`)
  // 位数契约（与快照无关）：4 位格式；且必须走定点 half-up。
  // 附「半位探针」：live 值有效位 ≤ 展示位数时，toFixed 与 half-up 输出完全相同，
  // 光靠 live 值抓不到「formatSigned/formatDecimal 绕过 roundHalfUp 改用 toFixed」这类真回归。
  // 探针输入是字面量常量（同 [14] 361-369 组），不是快照值 -> 不构成快照耦合。
  const probe = formatSigned(-0.07335, 4)
  check('normalized 展示固定 4 位 + 走 half-up（半位探针）', /^[+-]?\d+\.\d{4}$/.test(normShown) && probe === '-0.0734', `${normShown} | probe=${probe}`)
  const scoreShown = formatSigned(real.meta.ias.score, 2)
  check('IAS score 展示 = roundHalfUp(真值, 2)', scoreShown === expectSigned(real.meta.ias.score, 2), `${scoreShown} vs ${expectSigned(real.meta.ias.score, 2)}`)
  // 龙六约束：显示位数是排版选择，但真值必须可对照（tooltip 露 6 位）
  check('6 位真值可原样还原', formatDecimal(norm, 6) === roundHalfUp(norm, 6).toFixed(6), formatDecimal(norm, 6))
  check('展示值与真值同源（不是 score/4.6 反推）', Math.abs(Number(formatDecimal(norm, 6)) - norm) < 1e-12)
}

// ------------------------------------------------------- [15] IAS 判级收归后端（「偏空」 bug）
console.log('\n[15] IAS 关键词读 ias.signal，不按 score 另算一套阈值')
{
  const ias = real.meta.ias
  check('后端 signal = 持有', ias.signal === '持有', ias.signal)
  check('后端 signal_icon = ➖', ias.signal_icon === '➖', ias.signal_icon)

  const kw = resolveIasKeyword(ias)
  check('keyword === ias.signal', kw?.keyword === ias.signal, String(kw?.keyword))
  check('emoji === ias.signal_icon', kw?.emoji === ias.signal_icon, String(kw?.emoji))

  // 旧路径回归：前端按 score 算会给「偏空」，必须不再出现
  const legacy = getKeyword('ias', ias.score)
  check('getKeyword(\'ias\') 已不再出「偏空」', legacy.keyword !== '偏空', legacy.keyword)
  check('getKeyword(\'ias\') 走中性占位', legacy.keyword === '—', legacy.keyword)
  check('上游若走错会不一致（证明这条断言有意义）', legacy.keyword !== kw?.keyword)

  // 维度关键词不受影响（维度没有后端等价物）
  check('维度 economic 仍有词', getKeyword('economic', -0.25).keyword === '放缓', getKeyword('economic', -0.25).keyword)
  check('维度 sentiment 仍有词', getKeyword('sentiment', -0.465).keyword === '谨慎', getKeyword('sentiment', -0.465).keyword)

  // 带后缀的 signal 必须原样透传（不枚举匹配）
  const suffixed = resolveIasKeyword({ signal: '减仓（部分维度缺失·参考）', signal_icon: '⚠️' })
  check('带后缀 signal 原样透传', suffixed?.keyword === '减仓（部分维度缺失·参考）', suffixed?.keyword)
  check('缺 signal 时返回 null（调用方回退中性）', resolveIasKeyword({}) === null)
}

// ------------------------------------------------------- [16] IAS 档位收归后端 signal（含渐变）
console.log('\n[16] IAS 档位只读 signal，前端不再比数字阈值')
{
  check('持有 → hold', resolveIasLevel('持有') === 'hold')
  check('强烈买入 → strong-buy', resolveIasLevel('强烈买入') === 'strong-buy')
  check('增持 → buy', resolveIasLevel('增持') === 'buy')
  check('减仓 → reduce', resolveIasLevel('减仓') === 'reduce')
  check('清仓/防御 → sell', resolveIasLevel('清仓/防御') === 'sell')
  check('数据不足 → insufficient', resolveIasLevel('数据不足') === 'insufficient')
  check('空值 → unknown（不猜）', resolveIasLevel('') === 'unknown')
  check('null → unknown', resolveIasLevel(null) === 'unknown')
  check('未知文案 → unknown', resolveIasLevel('随便写的') === 'unknown')

  // 后缀必须被切掉，否则一加「部分维度缺失」就掉档
  check('全角括号后缀被切', stripSignalSuffix('减仓（部分维度缺失·参考）') === '减仓')
  check('半角括号也切', stripSignalSuffix('减仓(部分维度缺失)') === '减仓')
  check('带后缀仍能判档', resolveIasLevel('减仓（部分维度缺失·参考）') === 'reduce')
  check('带后缀的买入档不掉', resolveIasLevel('增持（部分维度缺失·参考）') === 'buy')

  check('真实 ias.signal → hold', resolveIasLevel(real.meta.ias.signal) === 'hold', real.meta.ias.signal)

  // 回归护栏：App.tsx 不允许再出现 IAS 数字阈值比较
  const appSrc = readFileSync(resolve(here, '../src/App.tsx'), 'utf8')
  const thresholdPatterns = [/score\s*>=\s*2\.5/, /score\s*>=\s*1\.0/, /score\s*<=\s*-1\.5/, /getKeyword\('ias'/]
  for (const re of thresholdPatterns) {
    check(`App.tsx 无 ${re} 残留`, !re.test(appSrc))
  }
}

// ------------------------------------------------------- 汇总
console.log(`\n${'─'.repeat(60)}`)
if (failures.length === 0) {
  console.log(`✅ 全部通过：${pass} 项断言`)
  process.exit(0)
} else {
  console.log(`❌ ${failures.length} 项失败 / 共 ${pass + failures.length} 项`)
  for (const f of failures) console.log(`   · ${f}`)
  process.exit(1)
}
