#!/usr/bin/env python3
"""P1-8DIM 历史序列回算（旧 6 维 vs 新 8 维）——防跨日断档

背景（龙五 2026-11-28 工单 §5）：
  IAS_SCALE 4.6→5.6 且维度结构变了，normalized 会凭空跳变。必须用 data/history/
  的原始指标值，按新 8 维结构重算 IAS 与 normalized，给出旧 vs 新对照，
  并逐日回答「哪些天信号档位翻转、原因是权重变化还是缺失剔除」。

做法（刻意冻结旧规则，而不是去 import 一份旧代码）：
  - 旧 6 维结构以 LEGACY_6DIM 字面量冻结在本文件（来源：git 2316356 的
    indicator_meta.DIMENSIONS，rules_hash=269592dd0bb6）；
  - 逐指标 score / α 复用**新代码**算出的同一份 indicators（本批不动任何单指标打分参数，
    这是「批次 A 只搬家」的前提；若将来动了，本脚本必须先重跑基线）；
  - 旧聚合 = 老公式（shrink = active/design_count，阈值比 score）；
  - 新聚合 = scoring.build_indicators_and_meta 原样输出。

用法:
  python3 scripts/replay_8dim_30d.py                 # 打印对照 + 写回算产物
  python3 scripts/replay_8dim_30d.py --days 30
  python3 scripts/replay_8dim_30d.py --rebuild-live  # 用最新快照重建 public/data/market-data.json
                                                    # （会尝试拉一次实时 usdcnh；不是部署）

**不覆盖** data/history/*.json 原始快照；只写 data/history/recompute-8dim-2026-11-28.json。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
WS = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import indicator_meta as im  # noqa: E402
import scoring  # noqa: E402

HISTORY_DIR = WS / 'data' / 'history'
OUT = HISTORY_DIR / 'recompute-8dim-2026-11-28.json'
MARKET_DATA = WS / 'public' / 'data' / 'market-data.json'

# ── 冻结的旧 6 维结构（来源：git 2316356 / rules_hash 269592dd0bb6）──
LEGACY_6DIM = [
    {'id': 'economic', 'name': '经济增长', 'weight': 1.0,
     'indicators': ['chinaGdp', 'chinaPmi', 'usGdp', 'servicePmi', 'electricity', 'usNonFarm']},
    {'id': 'inflation', 'name': '通胀与政策', 'weight': 1.0,
     'indicators': ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate']},
    {'id': 'liquidity', 'name': '流动性', 'weight': 0.8,
     'indicators': ['lpr', 'dr007', 'm2', 'creditSpread', 'dollarIndex',
                    'usBond2Y', 'usBond5Y', 'usBond10Y']},
    {'id': 'sentiment', 'name': '市场情绪', 'weight': 0.8,
     'indicators': ['vix', 'fearGreed', 'ashareTurnover', 'marginBalance',
                    'southboundNet', 'hstechMomentum']},
    {'id': 'resource', 'name': '资源与供应链', 'weight': 0.6,
     'indicators': ['oilPrice', 'naturalGas', 'carbonPrice', 'lmeIndex', 'shanghaiCopper']},
    {'id': 'techGreen', 'name': '科技与绿色', 'weight': 0.4,
     'indicators': ['aiGrowth', 'robotInstall', 'evPenetration', 'renewEnergyInvest']},
]
# 旧口径的参考项集合（旧代码里只有这 3 个是 reference_only；
# usBond2Y/5Y/lmeIndex 当时是正常打分项，不得按新口径剔）
LEGACY_REFERENCE_ONLY = {'epu', 'aiGrowth', 'robotInstall'}
LEGACY_SCALE = round(sum(d['weight'] for d in LEGACY_6DIM), 2)      # 4.6
LEGACY_THRESHOLDS = [(2.5, '强烈买入', '80-100%', '🚀'),
                     (1.0, '增持', '60-80%', '✅'),
                     (-0.5, '持有', '40-60%', '➖'),
                     (-1.5, '减仓', '20-40%', '⚠️')]


def _required(n_active):
    return n_active if n_active <= 3 else max(2, (n_active + 1) // 2)


def legacy_dim_scores(indicators: dict) -> dict:
    """按旧 6 维结构聚合（阈值比 score），复刻 git 2316356 的 calc_dimension_scores。"""
    out = {}
    for dim in LEGACY_6DIM:
        active = [k for k in dim['indicators'] if k not in LEGACY_REFERENCE_ONLY]
        tw, ta, valid = 0.0, 0.0, 0
        for k in active:
            v = indicators.get(k) or {}
            s = v.get('score')
            a = v.get('timeliness', 1.0) or 0.0
            if s is not None and a > 0:
                tw += s * a
                ta += a
                valid += 1
        req = _required(len(active))
        insuff = valid < req
        avg = None if insuff else im.q(tw / ta, 3)
        w_eff = round(dim['weight'] * (len(active) / len(dim['indicators'])), 4)
        out[dim['id']] = {
            'weight_design': dim['weight'], 'weight_effective': w_eff,
            'score': avg, 'valid_count': valid, 'required_count': req,
            'insufficient_data': insuff,
        }
    return out


def legacy_ias(dims: dict) -> dict:
    """旧 IAS：normalized 归一化，但信号阈值比 score（旧 bug 原样保留，回算要可比）。"""
    num = vw = tw = dw = 0.0
    for d in LEGACY_6DIM:
        ds = dims[d['id']]
        dw += ds['weight_design']
        tw += ds['weight_effective']
        if ds['insufficient_data'] or ds['score'] is None:
            continue
        num += ds['score'] * ds['weight_effective']
        vw += ds['weight_effective']
    if vw <= 0:
        return {'normalized': None, 'score': None, 'signal': '数据不足',
                'data_coverage': 0.0, 'scale': LEGACY_SCALE, 'valid_weight': 0.0}
    cov = round(vw / tw, 3)
    norm = im.q(num / vw, 6)
    score = im.q(norm * LEGACY_SCALE, 2)
    if cov < im.IAS_MIN_COVERAGE:
        sig = '数据不足'
    else:
        sig = '清仓/防御'
        for t, s, _p, _i in LEGACY_THRESHOLDS:
            if score >= t:
                sig = s
                break
    return {'normalized': norm, 'score': score, 'signal': sig,
            'data_coverage': cov, 'scale': LEGACY_SCALE, 'valid_weight': round(vw, 2)}


def load_snapshots(days: int):
    files = sorted(HISTORY_DIR.glob('2026-*.json'))
    files = [f for f in files if f.name.startswith('2026-')]
    snaps = []
    for f in files:
        try:
            snaps.append((f.stem, json.loads(f.read_text())))
        except Exception as e:  # noqa: BLE001
            print(f'⚠️ 跳过损坏快照 {f.name}: {e}')
    return snaps[-days:]


def _band_old(score_norm: float) -> str:
    """旧代码的信号档：把 normalized × 4.6 得 score，再比旧 score 阈值。"""
    score = im.q(score_norm * LEGACY_SCALE, 2)
    for t, s, _p, _i in LEGACY_THRESHOLDS:
        if score >= t:
            return s
    return '清仓/防御'


def _band_new(norm: float) -> str:
    """新代码的信号档：直接比 normalized 阈值。"""
    for t, s, _p, _i in im.IAS_THRESHOLDS:
        if norm >= t:
            return s
    return '清仓/防御'


def compare(days: int, quiet: bool = False) -> dict:
    snaps = load_snapshots(days)
    rows = []
    flips = []
    prev_data = None
    for ds, doc in snaps:
        indicators, meta = scoring.build_indicators_and_meta(doc.get('data') or {}, prev_data)
        prev_data = {k: {'value': v.get('value'), 'dataDate': v.get('dataDate')}
                     for k, v in (doc.get('data') or {}).items() if isinstance(v, dict)}
        new_ias = meta['ias']
        old_dims = legacy_dim_scores(indicators)
        old_ias = legacy_ias(old_dims)

        # 归因分解（同一份原始数据）：
        #   threshold_only  = 旧结构算出的 normalized，改喂新阈值 → 只能反映「阈值量纲」的影响
        #   struct_only     = 新结构算出的 normalized，改喂旧阈值 → 只能反映「结构/权重/剔除」的影响
        n_old, n_new = old_ias['normalized'], new_ias['normalized']
        threshold_only = _band_old(n_old) if n_old is not None else '数据不足'
        struct_only = _band_new(n_new) if n_new is not None else '数据不足'
        if old_ias['data_coverage'] < im.IAS_MIN_COVERAGE:
            threshold_only = '数据不足'
        if new_ias['data_coverage'] < im.IAS_MIN_COVERAGE:
            struct_only = '数据不足'

        grayed_new = list(new_ias['grayed_dimensions'])
        row = {
            'date': ds,
            'old': {'score': old_ias['score'], 'normalized': n_old,
                    'signal': old_ias['signal'], 'coverage': old_ias['data_coverage'],
                    'weight_effective_sum': round(sum(v['weight_effective'] for v in old_dims.values()), 2),
                    'grayed': [k for k, v in old_dims.items() if v['insufficient_data']],
                    'dims': {k: v['score'] for k, v in old_dims.items()}},
            'new': {'score': new_ias['score'], 'normalized': n_new,
                    'signal': new_ias['signal'], 'coverage': new_ias['data_coverage'],
                    'weight_effective_sum': new_ias['weight_effective_sum'],
                    'grayed': grayed_new,
                    'dims': {k: v['score'] for k, v in meta['dimensions'].items()}},
            'attribution': {'threshold_only_signal': threshold_only,
                            'structure_only_signal': struct_only,
                            'threshold_flip': threshold_only != old_ias['signal'],
                            'structure_flip': struct_only != threshold_only},
            'snapshot_rules_hash': (doc.get('meta') or {}).get('rules_hash'),
        }
        rows.append(row)
        if row['old']['signal'] != row['new']['signal']:
            if row['attribution']['threshold_flip']:
                cause = '阈值量纲'
            elif new_ias['data_coverage'] < im.IAS_MIN_COVERAGE and old_ias['data_coverage'] >= im.IAS_MIN_COVERAGE:
                cause = '缺失剔除（覆盖率跌破 0.6）'
            else:
                cause = '结构/权重'
            flips.append({'date': ds, 'old_signal': row['old']['signal'],
                          'new_signal': row['new']['signal'],
                          'old_norm': n_old, 'new_norm': n_new,
                          'cause': cause,
                          'old_coverage': old_ias['data_coverage'],
                          'new_coverage': new_ias['data_coverage'],
                          'new_grayed': grayed_new})

    if not quiet:
        print(f'{"日期":<12}{"旧score":<9}{"旧norm":<10}{"旧信号":<10}'
              f'{"新score":<9}{"新norm":<10}{"新信号":<10}翻转')
        for r in rows:
            print(f"{r['date']:<12}{str(r['old']['score']):<9}{str(r['old']['normalized']):<10}"
                  f"{r['old']['signal']:<10}{str(r['new']['score']):<9}"
                  f"{str(r['new']['normalized']):<10}{r['new']['signal']:<10}"
                  f"{'★' if r['old']['signal'] != r['new']['signal'] else ''}")
        print(f'\n共 {len(rows)} 个快照，信号档位翻转 {len(flips)} 天')
        for f in flips:
            print(f"  ★ {f['date']}: {f['old_signal']} → {f['new_signal']}（{f['cause']}；"
                  f"归一 {f['old_norm']} → {f['new_norm']}；覆盖 {f['old_coverage']} → {f['new_coverage']}）")

    return {'rows': rows, 'flips': flips}


def _usdcnh_live():
    """尝试取一次实时 usdcnh（as-live 重建用）。取不到返回 None。"""
    try:
        import fetch_worldos_data as fw
        res = fw.get_usdcnh()
        val, dd, freq = res[:3]
        degraded = res[3] if len(res) > 3 else None
        return val, dd, degraded
    except Exception as e:  # noqa: BLE001
        print(f'⚠️ usdcnh 实时取数失败: {type(e).__name__}: {e}')
        return None, None, None


def rebuild_live():
    """用最新快照重建 public/data/market-data.json（8 维）。

    注意：这不是部署。只改本地构建输入；线上由 cron 下次抓取时按新代码自然产出。
    除 usdcnh 外所有值都来自最新快照，不重抓、不造数。
    """
    import fetch_worldos_data as fw

    snaps = load_snapshots(10)
    ds, doc = snaps[-1]
    prev_ds, prev_doc = snaps[-2] if len(snaps) > 1 else (None, None)
    results = {k: dict(v) for k, v in (doc.get('data') or {}).items() if isinstance(v, dict)}

    # usdcnh：快照里没有 → 现取一次；取不到就 None（不硬填）
    val, dd, degraded = _usdcnh_live()
    meta_u = im.INDICATORS['usdcnh']
    entry = {
        'value': val, 'unit': meta_u['unit'], 'frequency': meta_u['frequency'],
        'source': meta_u['source'], 'dataDate': dd,
        'lastFetched': datetime.now().isoformat(),
        'realtime': bool(val is not None and dd is None),
        'used_fallback': False,
        'fetchError': None if val is not None else
        {'reason': 'not_found', 'reasonText': '离岸/在岸源均不可得（不造数）'},
    }
    if degraded:
        entry['actualSource'] = degraded.get('source')
        entry['sourceDegraded'] = degraded
        if degraded.get('caliberNoteSuffix'):
            entry['caliberNoteSuffix'] = degraded['caliberNoteSuffix']
    results['usdcnh'] = entry

    prev_data = None
    if prev_doc:
        prev_data = {k: {'value': v.get('value'), 'dataDate': v.get('dataDate')}
                     for k, v in (prev_doc.get('data') or {}).items() if isinstance(v, dict)}

    indicators, meta = scoring.build_indicators_and_meta(results, prev_data)
    indicators, meta = scoring.build_indicators_and_meta(results, prev_data)  # 幂等（trend 与 prev 无关）

    failed = []
    for key, info in im.INDICATORS.items():
        v = results.get(key, {})
        err = v.get('fetchError')
        if err is None and v.get('value') is not None:
            continue
        err = err or {'reason': 'not_found', 'reasonText': '未取到数据'}
        failed.append({
            'key': key, 'displayName': info['name'], 'source': info['source'],
            'reason': err.get('reason', 'parse_error'), 'reasonText': err.get('reasonText', ''),
            'dataDate': v.get('dataDate'),
            'days_stale': im.days_stale(v.get('dataDate')),
            'used_fallback': bool(v.get('used_fallback')),
            'lastAttempt': datetime.now().isoformat(),
        })
    source_degraded = []
    for key, v in results.items():
        sd = v.get('sourceDegraded')
        if sd and v.get('value') is not None:
            source_degraded.append({
                'key': key, 'displayName': im.INDICATORS[key]['name'],
                'source': v.get('source'), 'actualSource': sd.get('source'),
                'primarySource': sd.get('primarySource'),
                'reason': sd.get('reason', 'primary_source_missing'),
                'reasonText': sd.get('reasonText', ''), 'value': v.get('value'),
                'dataDate': v.get('dataDate'), 'lastAttempt': datetime.now().isoformat(),
            })

    output = {
        'timestamp': datetime.now().isoformat(),
        'recompute': {
            'note': 'P1-8DIM 批次 A：除 usdcnh 为重建时实时取数外，其余全部取自 '
                    f'{ds} 快照（不重抓、不造数）',
            'sourceSnapshot': ds,
            'generatedBy': 'scripts/replay_8dim_30d.py --rebuild-live',
        },
        'data': results,
        'indicators': indicators,
        'meta': meta,
        'validity_report': {
            'total': len(results),
            'valid': sum(1 for v in results.values() if v.get('value') is not None),
            'invalid': sum(1 for v in results.values() if v.get('value') is None),
            'degraded': scoring.build_degraded_items(indicators),
            'degraded_count': len(scoring.build_degraded_items(indicators)),
            'failed': failed,
            'source_degraded': source_degraded,
            'source_degraded_count': len(source_degraded),
        },
    }
    fw.write_json_strict(MARKET_DATA, output)
    print(f'✅ 已重建 {MARKET_DATA.relative_to(WS)}')
    print(f"   IAS score={meta['ias']['score']} normalized={meta['ias']['normalized']} "
          f"signal={meta['ias']['signal']} ias_scale={meta['ias']['ias_scale']} "
          f"rules_hash={meta['rules_hash']}")
    print(f"   usdcnh={val} ({'在岸回退' if degraded else '离岸' if val else '缺失'})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--rebuild-live', action='store_true')
    ap.add_argument('--json-out', default=str(OUT))
    args = ap.parse_args()

    if args.rebuild_live:
        rebuild_live()
        return 0

    res = compare(args.days)
    payload = {
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'purpose': 'P1-8DIM 历史回算：旧 6 维（冻结字面量）vs 新 8 维，逐日对照 + 信号翻转清单',
        'legacy': {'dims': [{k: d[k] for k in ('id', 'name', 'weight', 'indicators')}
                            for d in LEGACY_6DIM],
                   'scale': LEGACY_SCALE,
                   'thresholds': [[t, s, p] for t, s, p, _ in LEGACY_THRESHOLDS],
                   'reference_only': sorted(LEGACY_REFERENCE_ONLY)},
        'current': {'dims': [{k: d[k] for k in ('id', 'name', 'weight')} for d in im.DIMENSIONS],
                    'scale': im.IAS_SCALE,
                    'threshold_space': im.IAS_THRESHOLD_SPACE,
                    'thresholds': [[t, s, p] for t, s, p, _ in im.IAS_THRESHOLDS]},
        'rules_hash_old': sorted({r['snapshot_rules_hash'] for r in res['rows']
                                  if r['snapshot_rules_hash']}),
        'rules_hash_new': im.compute_rules_hash(),
        'rows': res['rows'],
        'flips': res['flips'],
        'flip_count': len(res['flips']),
    }
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                              allow_nan=False), encoding='utf-8')
    print(f'\n已写: {args.json_out}')
    print(f"rules_hash old={payload['rules_hash_old']} → new={payload['rules_hash_new']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
