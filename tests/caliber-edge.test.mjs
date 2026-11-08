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
  FRESHNESS_STATE_META,
} from '../src/lib/caliber.ts'

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
  const legacy = Object.entries(real.indicators).filter(([, v]) => v.freshness === '⚪')
  check('真实快照里确实还有 ⚪ 图标', legacy.length > 0, `count=${legacy.length}`)
  for (const [k, v] of legacy) {
    const st = resolveFreshnessState(v)
    check(`${k}: 按 level 解析为 realtime（不是 unknown）`, st === 'realtime', `level=${v.freshness_level} → ${st}`)
    const cs = computeStaleness(v)
    check(`${k}: label=实时（不是「时效未知」）`, cs.label === '实时', cs.label)
    check(`${k}: days=null 且不描灰`, cs.days === null && cs.overdue === false)
    check(`${k}: 不描灰`, describeIndicatorState(v).dimmed === false)
  }
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
console.log('\n[3] 描灰只看「有日期的超阈值」，days_stale=null 不描灰（unknown ≠ 0 天）')
{
  for (const [k, v] of Object.entries(fixture.indicators)) {
    const st = describeIndicatorState(v)
    if (v.days_stale === null) {
      check(`${k}: 无日期 → 不描灰`, st.dimmed === false, `state=${st.state}`)
    }
  }
  const unknownItems = Object.entries(fixture.indicators).filter(([, v]) => resolveFreshnessState(v) === 'unknown')
  check('unknown 项存在且全部不描灰', unknownItems.length > 0 && unknownItems.every(([, v]) => !describeIndicatorState(v).dimmed))
}

// ------------------------------------------------------- [4] 排除标三态
console.log('\n[4] 排除标：reference_only / no_score / expired_alpha0 文案各异，且不与描灰叠加')
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
      check(`${k}: 不描灰（排除标更强）`, st.dimmed === false)
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
      return st.exclusionBadge !== null && st.dimmed
    })
    check(`${label}: 无双标`, doubleBadge.length === 0, doubleBadge.map(([k]) => k).join(','))

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
  check('描灰 = usGdp, oilPrice', dimmed.join(',') === 'oilPrice,usGdp', dimmed.join(','))

  const badges = all.filter(([, v]) => describeIndicatorState(v).exclusionBadge)
  check('排除标 2 个且均为参考项', badges.length === 2 && badges.every(([, v]) => v.exclusion_reason === 'reference_only'), badges.map(([k]) => k).join(','))

  const states = {}
  for (const [, v] of all) {
    const s = resolveFreshnessState(v)
    states[s] = (states[s] ?? 0) + 1
  }
  check('真实快照状态分布 fresh26/stale2/realtime2', states.fresh === 26 && states.stale === 2 && states.realtime === 2, JSON.stringify(states))

  const rt = all.filter(([, v]) => resolveFreshnessState(v) === 'realtime')
  check('realtime 2 个且 days=null', rt.length === 2 && rt.every(([, v]) => computeStaleness(v).days === null), rt.map(([k]) => k).join(','))

  // 季频黄线 120：usGdp 223 天 → stale（不是 fresh）
  check('usGdp 223 天判 stale', resolveFreshnessState(real.indicators.usGdp) === 'stale', String(resolveFreshnessState(real.indicators.usGdp)))
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
