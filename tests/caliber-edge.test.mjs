// 边界状态夹具校验 —— 用真代码（src/lib/caliber.ts）跑合成夹具，把线上零触发的分支钉住。
//
// 运行：node --experimental-strip-types tests/caliber-edge.test.mjs
// 夹具：tests/fixtures/market-data-edge-cases.json（scripts/make_fixture_edge_cases.py 生成）
//
// 2026-11-09 加：线上真实数据里 no_score / expired_alpha0 / insufficient_data /
// 覆盖率中间档 全部零触发，等于没验证过。本脚本让它们各自必须在夹具里被踩到，
// 任何一个分支没触发就 exit 1。

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import {
  describeIndicatorState,
  resolveCoverageTier,
  computeStaleness,
  resolveDisplayName,
  describeFreshness,
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

// ---------------------------------------------------------------- 夹具六分支
console.log('\n[1] reference_only → 参考项，且不描灰')
{
  const refs = Object.entries(fixture.indicators).filter(([, v]) => v.reference_only === true)
  check('夹具里存在 reference_only 样本', refs.length > 0, `count=${refs.length}`)
  for (const [k, v] of refs) {
    const st = describeIndicatorState(v)
    check(`${k}: 标=参考项`, st.exclusionBadge?.text === '参考项')
    check(`${k}: 不描灰`, st.dimmed === false)
    check(`${k}: not_counted=false（参考项单独走标）`, st.notCounted === false)
  }
}

console.log('\n[2] expired_alpha0 → 过期剔除标，且不再叠描灰（排除标更强）')
{
  const items = Object.entries(fixture.indicators).filter(
    ([, v]) => v.exclusion_reason === 'expired_alpha0'
  )
  check('夹具里存在 expired_alpha0 样本', items.length > 0, `count=${items.length}`)
  for (const [k, v] of items) {
    const st = describeIndicatorState(v)
    check(`${k}: 标=过期剔除`, st.exclusionBadge?.text === '过期剔除')
    check(`${k}: 不叠描灰（排除标已含过期语义）`, st.dimmed === false, `days=${v.days_stale}`)
    // 信息不丢：旧到什么程度仍然由副行展示
    check(`${k}: 副行仍显示具体天数`, /天前$/.test(st.stale.label), st.stale.label)
  }
}

console.log('\n[3] no_score → 无评分（线上零触发分支）')
{
  const items = Object.entries(fixture.indicators).filter(([, v]) => v.exclusion_reason === 'no_score')
  check('夹具里存在 no_score 样本', items.length > 0, `count=${items.length}`)
  for (const [k, v] of items) {
    const st = describeIndicatorState(v)
    check(`${k}: 标=无评分`, st.exclusionBadge?.text === '无评分')
    check(`${k}: 不描灰（数据本身是新的）`, st.dimmed === false, `days=${v.days_stale}`)
  }
}

console.log('\n[4] 维度置灰 → insufficient_data=true 且 score=null（渲染层 toFixed 守卫的前置条件）')
{
  const greyed = Object.entries(fixture.meta.dimensions).filter(([, d]) => d.insufficient_data === true)
  check('夹具里存在置灰维度', greyed.length > 0, `count=${greyed.length}`)
  for (const [k, d] of greyed) {
    check(`${k}: insufficient_data=true`, d.insufficient_data === true)
    check(`${k}: score=null（不是 0）`, d.score === null, `score=${JSON.stringify(d.score)}`)
  }
  const live = Object.values(fixture.meta.dimensions).filter(d => d.insufficient_data !== true)
  check('非置灰维度 score 非 null', live.every(d => typeof d.score === 'number'))
}

console.log('\n[5] 覆盖率中间档 0.6~0.8 → partial（出分但仅参考）')
{
  const tier = resolveCoverageTier(fixture.meta.ias.data_coverage)
  check('夹具 data_coverage 落在 partial 档', tier === 'partial', `coverage=${fixture.meta.ias.data_coverage}`)
  check('is_actionable 仍为 true', fixture.meta.ias.is_actionable === true)
  check('signal 带「部分维度缺失」后缀', /部分维度缺失/.test(fixture.meta.ias.signal), fixture.meta.ias.signal)
  check('grayed_dimensions 非空', (fixture.meta.ias.grayed_dimensions ?? []).length > 0)
  // 分档边界
  check('0.59 → insufficient', resolveCoverageTier(0.59) === 'insufficient')
  check('0.60 → partial', resolveCoverageTier(0.6) === 'partial')
  check('0.79 → partial', resolveCoverageTier(0.79) === 'partial')
  check('0.80 → ok', resolveCoverageTier(0.8) === 'ok')
  check('null → ok（不降级）', resolveCoverageTier(null) === 'ok')
}

console.log('\n[6] realtime ⚪ vs 兜底无日期 —— 两者都 days_stale=null 但语义相反')
{
  const rt = Object.entries(fixture.indicators).filter(([, v]) => v.freshness_level === 'realtime')
  check('夹具里存在 realtime 样本', rt.length > 0, `count=${rt.length}`)
  for (const [k, v] of rt) {
    const st = computeStaleness(v)
    check(`${k}: kind=realtime`, st.kind === 'realtime')
    check(`${k}: label=实时`, st.label === '实时')
    check(`${k}: days=null（不当 0）`, st.days === null)
    check(`${k}: 不描灰`, st.overdue === false)
  }

  const fb = Object.entries(fixture.indicators).filter(
    ([, v]) => v.used_fallback === true && v.days_stale === null && v.freshness_level !== 'realtime'
  )
  check('夹具里存在「兜底且无日期」样本', fb.length > 0, `count=${fb.length}`)
  for (const [k, v] of fb) {
    const st = computeStaleness(v)
    check(`${k}: kind=unknown（不能当 realtime）`, st.kind === 'unknown')
    check(`${k}: label=时效未知`, st.label === '时效未知')
    check(`${k}: 不当 0 天、不描灰`, st.days === null && st.overdue === false)
  }
}

console.log('\n[7] 全局不变量')
{
  const all = Object.entries(fixture.indicators)
  const doubleBadge = all.filter(([, v]) => {
    const st = describeIndicatorState(v)
    return st.exclusionBadge !== null && st.dimmed
  })
  check('无「排除标 + 描灰」同一行双标', doubleBadge.length === 0, doubleBadge.map(([k]) => k).join(','))

  const badName = all.filter(([, v]) => {
    const n = resolveDisplayName(v, '')
    return typeof n !== 'string' || n.length === 0
  })
  check('每个指标都能解析出非空名称', badName.length === 0)

  const freshUnclear = all.filter(([, v]) => describeFreshness(v.freshness, v.freshness_level) === '新鲜度未知')
  check('freshness 徽标全部可解释', freshUnclear.length === 0, freshUnclear.map(([k]) => k).join(','))
}

console.log('\n[8] 真实快照回归（public/data/market-data.json）')
{
  const all = Object.entries(real.indicators)
  check('真实快照指标数 30', all.length === 30, `count=${all.length}`)

  const dimmed = all.filter(([, v]) => describeIndicatorState(v).dimmed)
  check(
    '真实快照描灰 2 个（usGdp / oilPrice）',
    dimmed.length === 2 && dimmed.map(([k]) => k).sort().join(',') === 'oilPrice,usGdp',
    dimmed.map(([k]) => k).join(',')
  )

  const badges = all.filter(([, v]) => describeIndicatorState(v).exclusionBadge)
  check(
    '真实快照排除标 2 个（aiGrowth / robotInstall，均为参考项）',
    badges.length === 2 && badges.every(([, v]) => v.exclusion_reason === 'reference_only'),
    badges.map(([k]) => k).join(',')
  )

  const dbl = all.filter(([, v]) => {
    const st = describeIndicatorState(v)
    return st.exclusionBadge !== null && st.dimmed
  })
  check('真实快照无双标', dbl.length === 0, dbl.map(([k]) => k).join(','))

  const rt = all.filter(([, v]) => computeStaleness(v).kind === 'realtime')
  check('真实快照 realtime 2 个', rt.length === 2, rt.map(([k]) => k).join(','))
  check('realtime 全部 days=null', rt.every(([, v]) => computeStaleness(v).days === null))

  // 40 天边界：月频阈值 40，严格大于 → 不描灰
  const onBoundary = all.filter(([, v]) => computeStaleness(v).days === 40)
  check('40 天边界样本存在', onBoundary.length > 0, `count=${onBoundary.length}`)
  check(
    '40 天边界全部不描灰（严格大于）',
    onBoundary.every(([, v]) => describeIndicatorState(v).dimmed === false)
  )
}

// ---------------------------------------------------------------- 汇总
console.log(`\n${'─'.repeat(60)}`)
if (failures.length === 0) {
  console.log(`✅ 全部通过：${pass} 项断言`)
  process.exit(0)
} else {
  console.log(`❌ ${failures.length} 项失败 / 共 ${pass + failures.length} 项`)
  for (const f of failures) console.log(`   · ${f}`)
  process.exit(1)
}
