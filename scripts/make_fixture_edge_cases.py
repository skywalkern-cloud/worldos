#!/usr/bin/env python3
"""生成「边界状态」数据夹具，钉住从没被真实数据踩到的分支。

背景（2026-11-09 扣钉提出）：线上数据只出现过 reference_only / realtime / used_fallback
三种状态，`no_score`、`expired_alpha0`、维度置灰(insufficient_data)、覆盖率降级
四条分支零触发 —— 等于没验证过。等线上真出现第一个 α=0 指标时才知道类名写错没。

产出一个合成 raw_data（不联网、不依赖真实数据），跑一遍 build_indicators_and_meta，
把结果写到 tests/fixtures/market-data-edge-cases.json，供：
  - 扣钉：UI 分支（not_counted 文案 / 置灰 / 覆盖率）离线验证
  - 泰斯特：schema 与语义断言

用法： python3 scripts/make_fixture_edge_cases.py
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import indicator_meta as meta_mod  # noqa: E402
from indicator_meta import INDICATORS, FRESHNESS_STATES, UNKNOWN_ALPHA  # noqa: E402
from scoring import build_indicators_and_meta, build_degraded_items  # noqa: E402

WS = Path(__file__).resolve().parent.parent
OUT = WS / 'tests' / 'fixtures' / 'market-data-edge-cases.json'

TODAY = date.today()
OLD = (TODAY - timedelta(days=900)).isoformat()      # 远超红线 → α=0
FRESH = TODAY.isoformat()

# 每个 key 的样例值：故意让部分指标落在「无评分参数」「过期」「无日期」上
SAMPLE_VALUES = {
    # 经济：让 chinaGdp 过期(α=0) 且 usGdp 无日期，其余正常 → 有效数可能不足
    # T13-4：usGdp 就是「有值、无日期、非 realtime」的 no_date 样本
    #   → 必须 ⚪ + α=0.5 + 进 validity_report.degraded(reason='no_date')
    #   （旧代码这一支会亮 🟢 + α=1.0，泰斯特冻结回放就是在这里拓到了洞）
    'chinaGdp': (4.6, OLD, 'quarterly'),
    'chinaPmi': (49.3, FRESH, 'monthly'),
    'usGdp': (2.0, None, 'quarterly'),
    'servicePmi': (49.7, FRESH, 'monthly'),
    'electricity': (3.9, FRESH, 'monthly'),
    'usNonFarm': (16.5, FRESH, 'monthly'),
    # 通胀：整体正常
    'cpi': (0.9, FRESH, 'monthly'),
    'ppi': (5.0, FRESH, 'monthly'),
    'usCpi': (3.7, FRESH, 'monthly'),
    'corePce': (2.3, FRESH, 'monthly'),
    'fedRate': (3.88, FRESH, 'monthly'),
    # 流动性：全部过期 → 整个维度 insufficient_data（覆盖率降级用例）
    'lpr': (3.0, OLD, 'monthly'),
    'dr007': (1.283, OLD, 'daily'),
    'm2': (7.2, OLD, 'monthly'),
    'creditSpread': (327, OLD, 'daily'),
    'dollarIndex': (96.9, OLD, 'daily'),
    'usBond2Y': (4.51, OLD, 'daily'),
    'usBond5Y': (4.64, OLD, 'daily'),
    'usBond10Y': (4.86, OLD, 'daily'),
    # 情绪：正常
    'vix': (20.52, FRESH, 'daily'),
    'fearGreed': (22.1, FRESH, 'daily'),
    # 资源：一个 realtime 无日期 + 一个兜底
    'oilPrice': (102.95, None, 'daily'),
    'naturalGas': (3.003, None, 'daily'),
    'carbonPrice': (96.19, FRESH, 'daily'),
    'lmeIndex': (13755.5, None, 'daily'),
    'shanghaiCopper': (105060.0, FRESH, 'daily'),
    # 科技与绿色：两个参考项 + 一项正常
    'aiGrowth': (4.1, FRESH, 'monthly'),
    'robotInstall': (5.5, FRESH, 'monthly'),
    # 两项都过期 → techGreen 有效数 0 < 2 → 置灰，同时把 data_coverage 压到 0.75（中间档用例）
    'evPenetration': (65.4, OLD, 'monthly'),
    'renewEnergyInvest': (1256.0, OLD, 'daily'),
    # epu：无值 → 只出现在 validity_report.failed
    'epu': (None, None, 'monthly'),
}


def build_raw_data():
    raw = {}
    for key, spec in INDICATORS.items():
        val, dd, freq = SAMPLE_VALUES.get(key, (None, None, spec['frequency']))
        used_fallback = key in ('oilPrice',)          # 兜底用例
        realtime = INDICATORS[key].get('dateSource') == 'realtime'
        raw[key] = {
            'value': val,
            'unit': spec['unit'],
            'frequency': freq,
            'source': spec['source'],
            'dataDate': dd,
            'lastFetched': FRESH + 'T10:00:00',
            'realtime': realtime,
            'used_fallback': used_fallback,
            'fetchError': ({'reason': 'not_found', 'reasonText': '夹具：数据源无有效记录（已用上一轮值兜底）'}
                           if used_fallback else
                           ({'reason': 'timeout', 'reasonText': '夹具：超时'}
                            if val is None else None)),
        }
    # 模拟「新接入了指标但还没配评分参数」的真实场景 → no_score 分支
    raw['newIndicatorSample'] = {
        'value': 5,
        'unit': '%',
        'frequency': 'monthly',
        'source': '夹具-未配评分参数',
        'dataDate': FRESH,
        'lastFetched': FRESH + 'T10:00:00',
        'realtime': False,
        'used_fallback': False,
        'fetchError': None,
    }
    return raw


def main():
    raw = build_raw_data()
    indicators, meta_out = build_indicators_and_meta(raw, raw)

    failed = []
    for key, info in INDICATORS.items():
        v = raw.get(key, {})
        if v.get('fetchError') is None and v.get('value') is not None:
            continue
        err = v.get('fetchError') or {'reason': 'not_found', 'reasonText': '夹具：无值'}
        failed.append({
            'key': key,
            'displayName': info['name'],
            'source': info['source'],
            'reason': err['reason'],
            'reasonText': err['reasonText'],
            'dataDate': v.get('dataDate'),
            'days_stale': meta_mod.days_stale(v.get('dataDate')),
            'used_fallback': bool(v.get('used_fallback')),
            'lastAttempt': FRESH + 'T10:00:00',
        })

    payload = {
        'timestamp': FRESH + 'T10:00:00',
        'fixture': {
            'purpose': '边界状态夹具：钉住线上零触发的分支（no_score / expired_alpha0 / insufficient_data / 覆盖率降级 / no_date 未知时效）',
            'generatedBy': 'scripts/make_fixture_edge_cases.py',
            'notRealData': True,
        },
        'data': raw,
        'indicators': indicators,
        'meta': meta_out,
        'validity_report': {
            'total': len(raw),
            'valid': sum(1 for v in raw.values() if v['value'] is not None),
            'invalid': sum(1 for v in raw.values() if v['value'] is None),
            # T13：与 fetch 同构 —— 列表 + reason，计数另给 degraded_count
            'degraded': build_degraded_items(indicators),
            'degraded_count': len(build_degraded_items(indicators)),
            'failed': failed,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

    # ── 断言：每个目标分支都必须被触发 ──
    reasons = {i.get('exclusion_reason') for i in indicators.values()}
    grayed = [d for d, v in meta_out['dimensions'].items() if v['insufficient_data']]
    realtime_flags = [k for k, v in indicators.items() if v['freshness_level'] == 'realtime']
    unknown_flags = [k for k, v in indicators.items() if v['freshness_level'] == 'unknown']
    expanded = [k for k, v in indicators.items() if v['freshness_level'] == 'expired']
    degraded_items = payload['validity_report']['degraded']
    no_date_items = [i['key'] for i in degraded_items if i['reason'] == 'no_date']

    print(f'已生成: {OUT}')
    print(f'  exclusion_reason 覆盖: {sorted(r for r in reasons if r)}')
    print(f'  置灰维度: {grayed}')
    print(f'  realtime({FRESHNESS_STATES["realtime"]["icon"]}): {realtime_flags}')
    print(f'  unknown({FRESHNESS_STATES["unknown"]["icon"]}): {unknown_flags}')
    print(f'  expired({FRESHNESS_STATES["expired"]["icon"]}): {expanded}')
    print(f'  degraded: {[(i["key"], i["reason"]) for i in degraded_items]}')
    print(f'  IAS: score={meta_out["ias"]["score"]} normalized={meta_out["ias"]["normalized"]} '
          f'signal={meta_out["ias"]["signal"]} data_coverage={meta_out["ias"]["data_coverage"]} '
          f'is_actionable={meta_out["ias"]["is_actionable"]}')

    problems = []
    if 'reference_only' not in reasons:
        problems.append('未触发 reference_only')
    if 'expired_alpha0' not in reasons:
        problems.append('未触发 expired_alpha0')
    if 'no_score' not in reasons:
        problems.append('未触发 no_score')
    if not grayed:
        problems.append('未触发维度 insufficient_data')
    if meta_out['ias']['data_coverage'] >= meta_mod.IAS_PARTIAL_COVERAGE:
        problems.append('未触发覆盖率中间档（data_coverage 仍 ≥0.8）')
    if not realtime_flags:
        problems.append('未触发 realtime 新鲜度')

    # ── T13 新增断言：无日期不得亮绿灯 ──
    if not unknown_flags:
        problems.append('未触发 unknown（有值但无日期）新鲜度')
    for k in unknown_flags:
        v = indicators[k]
        if v['freshness'] != FRESHNESS_STATES['unknown']['icon']:
            problems.append(f'{k}: unknown 图标应为 {FRESHNESS_STATES["unknown"]["icon"]}，实得 {v["freshness"]}')
        if abs(v['timeliness'] - UNKNOWN_ALPHA) > 1e-9:
            problems.append(f'{k}: unknown 的 α 应为 {UNKNOWN_ALPHA}，实得 {v["timeliness"]}')
        if v['exclusion_reason'] == 'expired_alpha0':
            problems.append(f'{k}: unknown 不应被当成过期剔除')
    if 'usGdp' not in no_date_items:
        problems.append(f'usGdp 未进 validity_report.degraded(no_date)，实得 {no_date_items}')

    bad_green = [k for k, v in indicators.items()
                 if v['days_stale'] is None and v['freshness'] == FRESHNESS_STATES['fresh']['icon']
                 and not v['realtime']]
    if bad_green:
        problems.append(f'无日期却判 🟢（假绿灯）: {bad_green}')

    # 图标不得一码两用：realtime 与 unknown 必须不同图标
    if FRESHNESS_STATES['realtime']['icon'] == FRESHNESS_STATES['unknown']['icon']:
        problems.append('realtime 与 unknown 共用一个图标')

    if problems:
        print('\n❌ 夹具未覆盖:', problems)
        raise SystemExit(1)
    print('\n✅ 夹具覆盖全部目标分支')


if __name__ == '__main__':
    main()
