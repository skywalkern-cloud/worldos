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
import series_store  # noqa: E402

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


# A4（泰斯特 §5.3）：回算必须把**所有**有 series 的指标按 as-of 注入。
# 历史快照里这 4 个 A股/港股代理只有值、没有 history（→ pct_rank warmup →
# sentimentA 整维置灰），导致「8 维回算」实际只有 7 维。这里统一补齐。
SERIES_KEYS = list(im.QUANTILE_CONFIG)


def _series_asof(key: str, ref_date: str):
    """通用 as-of：取 ref_date **之前**最近收盘 + 该日之前的全部历史。

    严格 `d < ref_date`（不用当日）：与泰斯特 §5.3 口径一致，等价于「快照日
    开盘前已知的最近收盘」，保证任何一天都不会看到当天/未来的值。
    """
    series = series_store.load(key)
    ds = sorted(d for d in series if d < ref_date)
    if not ds:
        return None
    last = ds[-1]
    hist = [{'date': d, 'value': series[d]} for d in ds[:-1]]
    return {'value': series[last], 'dataDate': last, 'history': hist,
            'max_used_date': last, 'history_days': len(hist)}


def _series_entry(key: str, asof: dict) -> dict:
    """把 as-of 结果包装成 build_indicators_and_meta 期望的 raw_data 条目。"""
    meta = im.INDICATORS[key]
    return {
        'value': asof['value'], 'unit': meta['unit'], 'frequency': meta['frequency'],
        'source': meta['source'], 'dataDate': asof['dataDate'],
        'lastFetched': datetime.now().isoformat(),
        'realtime': False, 'used_fallback': False, 'fetchError': None,
        'history': asof['history'],
    }


def _cnh_series():
    """读取 usdcnh 日线序列（{date: close}）。无回填 → 空 dict（不造数）。"""
    return series_store.load('usdcnh')


def _cnh_asof(series: dict, ref_date: str):
    """as-of 取 ref_date **之前**最近的收盘，并返回该日前的历史。

    关键：绝不允许用 ref_date 当天或之后的观测。回算时这条是“无未来函数”的唯一入口：
      value/dataDate  = 最后一个 d < ref_date 的收盘
      history         = 该日之前的观测（MA120 含当日，所以需再往前 119 条）
    """
    ds = sorted(d for d in series if d < ref_date)
    if not ds:
        return None
    last = ds[-1]
    hist = [{'date': d, 'value': series[d]} for d in ds[:-1]]
    return {'value': series[last], 'dataDate': last, 'history': hist,
            'max_used_date': last,
            'history_days': len(hist)}


def _usdcnh_audit(indicators: dict, cnh: dict) -> dict:
    """回算行里的 usdcnh 审计信息（可复算 MA120 / ratio / 档位）。"""
    v = indicators.get('usdcnh') or {}
    return {
        'value': cnh['value'],
        'data_date': cnh['dataDate'],
        'history_days': cnh['history_days'],
        'max_used_date': cnh['max_used_date'],
        'ma_base': v.get('ma_base'),
        'ratio_value': v.get('ratio_value'),
        'deviation_pct': v.get('deviation_pct'),
        'score': v.get('score'),
    }


def _usdcnh_entry(cnh: dict) -> dict:
    """把 as-of 结果包装成 build_indicators_and_meta 期望的 raw_data 条目。"""
    u = im.INDICATORS['usdcnh']
    return {
        'value': cnh['value'], 'unit': u['unit'], 'frequency': u['frequency'],
        'source': u['source'], 'dataDate': cnh['dataDate'],
        'lastFetched': datetime.now().isoformat(),
        'realtime': False, 'used_fallback': False, 'fetchError': None,
        'history': cnh['history'],
    }


def compare(days: int, quiet: bool = False) -> dict:
    snaps = load_snapshots(days)
    rows = []
    flips = []
    lookahead_violations = []
    prev_data = None
    for ds, doc in snaps:
        data = {k: dict(v) for k, v in (doc.get('data') or {}).items() if isinstance(v, dict)}
        # A2 + A4：所有有 series 的指标都以 as-of 方式注入（usdcnh + 4 个 A股代理）。
        # 旧快照里这 4 项只有值没有 history → pct_rank warmup，本次一并修正。
        cnh = None
        injected = {}
        for key in SERIES_KEYS:
            asof = _series_asof(key, ds)
            if not asof:
                continue
            data[key] = _series_entry(key, asof)
            injected[key] = {'value': asof['value'], 'dataDate': asof['dataDate'],
                             'max_used_date': asof['max_used_date'],
                             'history_days': asof['history_days']}
            if key == 'usdcnh':
                cnh = asof
            # 无未来函数强断言：本日用到的所有观测必须严格早于快照日。
            used_dates = [r['date'] for r in asof['history']] + [asof['dataDate']]
            if max(used_dates) >= ds:
                lookahead_violations.append({'date': ds, 'key': key,
                                             'max_used': max(used_dates)})
        # A4：旧快照没有 chinaBond10Y（本批新增）。用同一快照已有的
        # 「美债10Y − 中美利差」反算（同源、不造数），否则历史回算的 liquidity
        # 仍是 3 项，和 live 4 项不可比（会出现两套结论）。
        if not (data.get('chinaBond10Y') or {}).get('value'):
            cs = (data.get('creditSpread') or {}).get('value')
            u10 = (data.get('usBond10Y') or {}).get('value')
            if cs is not None and u10 is not None:
                data['chinaBond10Y'] = {
                    'value': round(float(u10) - float(cs) / 100.0, 2),
                    'unit': im.INDICATORS['chinaBond10Y']['unit'],
                    'frequency': 'daily',
                    'source': im.INDICATORS['chinaBond10Y']['source'],
                    'caliberNoteSuffix': '（由美债10Y − 中美10Y利差反算，同源）',
                    'dataDate': (data.get('creditSpread') or {}).get('dataDate'),
                    'lastFetched': datetime.now().isoformat(),
                    'realtime': False, 'used_fallback': False, 'fetchError': None,
                }

        indicators, meta = scoring.build_indicators_and_meta(data, prev_data, today=ds)
        prev_data = {k: {'value': v.get('value'), 'dataDate': v.get('dataDate')}
                     for k, v in data.items() if isinstance(v, dict)}
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
            'series_injected': injected,
            'usdcnh': (_usdcnh_audit(indicators, cnh) if cnh else None),
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
        if lookahead_violations:
            print(f'  ❌ 序列未来函数违规 {len(lookahead_violations)} 处: {lookahead_violations[:5]}')
        else:
            print('  ✅ 所有 series 无未来函数：每个快照日只使用 date < 今日 的观测')

    return {'rows': rows, 'flips': flips,
            'lookahead_violations': lookahead_violations}


def _usdcnh_live():
    """A2：不再实时拉取，改从回填日线序列取 as-of 值（无未来函数）。

    返回 (value, dataDate, history, max_used_date)；无序列 → None。
    """
    series = _cnh_series()
    if not series:
        return None
    last = max(series)
    ds = sorted(series)
    hist = [{'date': d, 'value': series[d]} for d in ds[:-1]]
    return series[last], last, hist, last


def rebuild_live():
    """用最新快照 + usdcnh 回填序列重建 public/data/market-data.json（8 维）。

    注意：这不是部署。只改本地构建输入；线上由 cron 下次抓取时按新代码自然产出。
    除 usdcnh 外所有值都来自最新快照，不重抓、不造数。
    usdcnh 的价值/日期/MA120 均来自 data/history/series/usdcnh.json，
    且只取 date < 快照日 的观测（因为 11-28 快照日市场尚未有 11-28 收盘）。
    """
    import fetch_worldos_data as fw

    snaps = load_snapshots(10)
    ds, doc = snaps[-1]
    prev_ds, prev_doc = snaps[-2] if len(snaps) > 1 else (None, None)
    results = {k: dict(v) for k, v in (doc.get('data') or {}).items() if isinstance(v, dict)}

    # A4：所有 series 指标统一 as-of 注入（usdcnh + 4 个 A股/港股代理）。
    # 11-28 快照 → usdcnh 用 11-27 收盘 6.6551；4 个代理也用各自 11-27/11-26 收盘。
    meta_u = im.INDICATORS['usdcnh']
    cnh = _cnh_asof(_cnh_series(), ds)
    if cnh:
        entry = _usdcnh_entry(cnh)
        if cnh['max_used_date'] >= ds:
            raise RuntimeError(f'usdcnh 未来函数：用到 {cnh["max_used_date"]} ≥ 快照日 {ds}')
    else:
        entry = {
            'value': None, 'unit': meta_u['unit'], 'frequency': meta_u['frequency'],
            'source': meta_u['source'], 'dataDate': None,
            'lastFetched': datetime.now().isoformat(),
            'realtime': False, 'used_fallback': False,
            'fetchError': {'reason': 'not_found',
                           'reasonText': '无 usdcnh 日线序列（不造数）'},
        }
    results['usdcnh'] = entry
    for key in SERIES_KEYS:
        if key == 'usdcnh':
            continue
        asof = _series_asof(key, ds)
        if asof:
            if asof['max_used_date'] >= ds:
                raise RuntimeError(f'{key} 未来函数：用到 {asof["max_used_date"]} ≥ 快照日 {ds}')
            results[key] = _series_entry(key, asof)

    # A4：chinaBond10Y 在旧快照里不存在（本批新增）。它可以从同一批数据的
    # 「美债10Y − 中美利差」反算：4.94 − 334bp = 1.60%，不是新数据源、不是造数。
    if not (results.get('chinaBond10Y') or {}).get('value'):
        cs = (results.get('creditSpread') or {}).get('value')
        u10 = (results.get('usBond10Y') or {}).get('value')
        if cs is not None and u10 is not None:
            results['chinaBond10Y'] = {
                'value': round(float(u10) - float(cs) / 100.0, 2),
                'unit': im.INDICATORS['chinaBond10Y']['unit'],
                'frequency': 'daily',
                'source': im.INDICATORS['chinaBond10Y']['source'],
                'caliberNoteSuffix': '（数值由美债10Y − 中美10Y利差反算，同源）',
                'dataDate': (results.get('creditSpread') or {}).get('dataDate'),
                'lastFetched': datetime.now().isoformat(),
                'realtime': False, 'used_fallback': False, 'fetchError': None,
            }

    prev_data = None
    if prev_doc:
        prev_data = {k: {'value': v.get('value'), 'dataDate': v.get('dataDate')}
                     for k, v in (prev_doc.get('data') or {}).items() if isinstance(v, dict)}

    indicators, meta = scoring.build_indicators_and_meta(results, prev_data, today=ds)
    # 幂等（trend 与 prev 无关；today 固定为快照日，隔天重跑也不变）
    indicators, meta = scoring.build_indicators_and_meta(results, prev_data, today=ds)

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
            'note': 'P1-8DIM 批次 A + A2 + P1：usdcnh / 4 个 A股港股代理 / 中债10Y 均取自回填日线序列'
                    f'（as-of，严格早于快照日），其余全部取自 {ds} 快照（不重抓、不造数）；'
                    '新鲜度 α 以**快照日**为“今天”计算（P1-5）。',
            'sourceSnapshot': ds,
            'generatedBy': 'scripts/replay_8dim_30d.py --rebuild-live',
            'usdcnh': {'value': entry.get('value'), 'dataDate': entry.get('dataDate'),
                       'ma_base': (indicators.get('usdcnh') or {}).get('ma_base'),
                       'ratio_value': (indicators.get('usdcnh') or {}).get('ratio_value'),
                       'score': (indicators.get('usdcnh') or {}).get('score')},
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
    u = (meta['dimensions'].get('fxExternal') or {}).get('score')
    ui = indicators.get('usdcnh') or {}
    print(f"   usdcnh={entry.get('value')} @{entry.get('dataDate')} "
          f"MA120={ui.get('ma_base')} ratio={ui.get('ratio_value')} "
          f"score={ui.get('score')} | fxExternal={u}")


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
        'usdcnh_no_lookahead': {
            'violations': res['lookahead_violations'],
            'passed': not res['lookahead_violations'],
            'rule': '每个快照日只允许使用 date < 快照日 的 usdcnh 观测（MA120 含当日=该日之前最近收盘）',
        },
        # A4：所有 series 指标统一 as-of（usdcnh + ashareTurnover/marginBalance/
        # southboundNet/hstechMomentum），否则 18/19 天 sentimentA=null。
        'series_no_lookahead': {
            'violations': res['lookahead_violations'],
            'passed': not res['lookahead_violations'],
            'keys': SERIES_KEYS,
            'rule': '每个快照日对每一条 series 只使用 date < 快照日 的观测',
        },
    }
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                              allow_nan=False), encoding='utf-8')
    print(f'\n已写: {args.json_out}')
    print(f"rules_hash old={payload['rules_hash_old']} → new={payload['rules_hash_new']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
