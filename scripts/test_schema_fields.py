#!/usr/bin/env python3
"""
WorldOS P0 / T6 — 字段级 schema 校验 + 回归（只读）

用法:
  python3 scripts/test_schema_fields.py
  python3 scripts/test_schema_fields.py --json public/data/market-data.json
  python3 scripts/test_schema_fields.py --json /tmp/w.json --fixture tests/fixtures/market-data-edge-cases.json
  python3 scripts/test_schema_fields.py --json-out /tmp/schema-result.json

退出码: 0=全部 PASS / 1=有 FAIL / 2=输入不可读

设计约束（龙五 2026-11-09 硬要求）:
  - 时效阈值唯一真源 = indicator_meta.TIMELINESS_RULES，测试内**不硬编码天数**；
  - 评分规则唯一真源 = indicator_meta / scoring，测试只做独立复算与边界钉扎；
  - 参考日一律取 JSON timestamp 的日期（不是运行日），避免隔天 stale 漂移；
  - 输入文件只读，运行前后 sha256 必须一致；
  - 阈值契约（T6b-1）以 docs/freshness-contract.md 为外部 oracle：
    测试不回答「210 是否正确」，只回答「文档与代码是否一致」；正确性由龙五签字。
"""
import argparse
import ast
import hashlib
import json
import re
import sys
import traceback
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
WS = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import indicator_meta as im  # noqa: E402
import scoring  # noqa: E402  (仅 S4-U*/S5-U* 白盒夹具)

RESULTS = []
FAILED = []


def record(cid, ok, detail='', warn=False):
    RESULTS.append({'id': cid, 'status': 'WARN' if (warn and not ok) else ('PASS' if ok else 'FAIL'),
                    'detail': detail})
    if not ok and not warn:
        FAILED.append(f'{cid}: {detail}')


def check(cid, ok, detail=''):
    record(cid, ok, detail)


def warn_or_pass(cid, ok, detail=''):
    record(cid, ok, detail, warn=True)


def fail_if(cid, cond, detail=''):
    check(cid, not cond, detail)


# ═══════════════════════════════════════════
# 读取 / 严格解析
# ═══════════════════════════════════════════

def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f'重复 key: {k!r}')
        d[k] = v
    return d


def _no_const(tok):
    raise ValueError(f'非法 JSON 常量: {tok}')


def load_strict(path):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-8')
    if text.startswith('\ufeff'):
        raise ValueError('文件含 BOM')
    data = json.loads(text, object_pairs_hook=_no_dup, parse_constant=_no_const)
    return data, text, hashlib.sha256(raw).hexdigest()


def ref_date_of(doc):
    ts = doc.get('timestamp')
    if not isinstance(ts, str) or len(ts) < 10:
        raise ValueError(f'timestamp 不可解析: {ts!r}')
    return date.fromisoformat(ts[:10])


# ═══════════════════════════════════════════
# 独立 oracle（阈值来自 TIMELINESS_RULES，不写死天数）
# ═══════════════════════════════════════════

def days_stale_of(iso_str, ref):
    if iso_str is None:
        return None
    return (ref - date.fromisoformat(iso_str)).days


def expected_freshness(iso_str, freq, realtime, used_fallback, ref):
    """独立复算 (state, icon, alpha, days_stale, reasons)。"""
    ds = days_stale_of(iso_str, ref)
    reasons = []
    if ds is None:
        if realtime and not used_fallback:
            state = 'realtime'
        else:
            state = 'unknown'
            reasons.append('no_date')
    else:
        ds = max(0, ds)  # 未来/本年累计按 0 天
        rule = im.TIMELINESS_RULES.get(freq, im.TIMELINESS_RULES['other'])
        if ds > rule['red_days']:
            state = 'expired'
        elif ds > rule['yellow_days']:
            state = 'stale'
        else:
            state = 'fresh'
    if used_fallback:
        reasons.append('used_fallback')
        if state == 'fresh':
            state = 'stale'
    spec = im.FRESHNESS_STATES[state]
    alpha = spec['alpha']
    if used_fallback:
        alpha = min(alpha, 0.5)
    return state, spec['icon'], alpha, ds, reasons


def expected_required(active_n):
    if active_n <= 3:
        return active_n
    return max(2, (active_n + 1) // 2)


# ═══════════════════════════════════════════
# 冻结 source 表（557d31a/5c5d735 生产口径，逐字）
# ═══════════════════════════════════════════

EXPECTED_SOURCE = {
    'chinaGdp': ('国家统计局', '🇨🇳', 'quarterly'),
    'chinaPmi': ('东方财富-国家统计局', '🇨🇳', 'monthly'),
    'usGdp': ('东方财富-美国商务部', '🇺🇸', 'quarterly'),
    'servicePmi': ('东方财富-国家统计局', '🇨🇳', 'monthly'),
    'usCpi': ('美国劳工统计局', '🇺🇸', 'monthly'),
    'corePce': ('FRED API-美国商务部', '🇺🇸', 'monthly'),
    'vix': ('akshare-沪深300ETF期权波动率指数', '🇨🇳', 'daily'),
    'oilPrice': ('NYMEX期货', '🌐', 'daily'),
    'naturalGas': ('NYMEX期货', '🌐', 'daily'),
    'fedRate': ('FOMC会议记录', '🇺🇸', 'monthly'),
    'usBond2Y': ('akshare-中美债券', '🇺🇸', 'daily'),
    'usBond5Y': ('akshare-中美债券', '🇺🇸', 'daily'),
    'usBond10Y': ('akshare-中美债券', '🇺🇸', 'daily'),
    'usNonFarm': ('东方财富-美国劳工部', '🇺🇸', 'monthly'),
    'fearGreed': ('CNN Business-Fear&Greed', '🇺🇸', 'daily'),
    'dollarIndex': ('akshare-汇率加权计算', '🌐', 'daily'),
    'cpi': ('东方财富-国家统计局', '🇨🇳', 'monthly'),
    'ppi': ('东方财富-国家统计局', '🇨🇳', 'monthly'),
    'lpr': ('中国人民银行', '🇨🇳', 'monthly'),
    'dr007': ('全国银行间同业拆借中心', '🇨🇳', 'daily'),
    'm2': ('东方财富-中国人民银行', '🇨🇳', 'monthly'),
    'creditSpread': ('akshare-中美国债利差', '🌐', 'daily'),
    'epu': ('FRED API-EPU指数', '🌐', 'monthly'),
    'carbonPrice': ('北京碳市场', '🇨🇳', 'daily'),
    'electricity': ('国家能源局', '🇨🇳', 'monthly'),
    'renewEnergyInvest': ('中证新能源指数', '🇨🇳', 'daily'),
    'aiGrowth': ('国家能源局-第二产业', '🇨🇳', 'monthly'),
    'robotInstall': ('东方财富-规模以上工业增加值', '🇨🇳', 'monthly'),
    'evPenetration': ('乘联会-CPCA', '🇨🇳', 'monthly'),
    'lmeIndex': ('LME-综合铜03', '🌐', 'daily'),
    'shanghaiCopper': ('上期所-新浪财经', '🇨🇳', 'daily'),
}

SIGNALS = {'red', 'yellow', 'gray', 'lightgreen', 'green', 'reference'}
FRESHNESS_LEVELS = {'fresh', 'realtime', 'unknown', 'stale', 'expired'}
EXCLUSION_REASONS = {'reference_only', 'no_score', 'expired_alpha0'}
FETCH_REASONS = {'http_4xx', 'http_5xx', 'empty_response', 'parse_error',
                 'timeout', 'nan_value', 'not_found'}
DEGRADED_REASONS = {'no_date', 'used_fallback'}


# ═══════════════════════════════════════════
# S1 字段完整性 / 类型
# ═══════════════════════════════════════════

def test_s1(doc, label, ref, live):
    data, ind = doc['data'], doc['indicators']
    universe = {k for k, v in data.items() if v.get('value') is not None}
    check(f'S1-01[{label}]', set(ind) == universe,
          f'indicators={len(ind)} universe={len(universe)} diff={set(ind) ^ universe}')

    bad = []
    for k, v in ind.items():
        for f in ('value', 'unit', 'source', 'dataDate', 'frequency'):
            if f not in v:
                bad.append(f'{k}.{f} 缺失')
        if not isinstance(v.get('value'), (int, float)) or isinstance(v.get('value'), bool):
            bad.append(f'{k}.value 非数值')
        if not isinstance(v.get('unit'), str):
            bad.append(f'{k}.unit 非 str')
        if not isinstance(v.get('source'), str) or not v['source'].strip():
            bad.append(f'{k}.source 空')
        if v.get('dataDate') is not None and not isinstance(v.get('dataDate'), str):
            bad.append(f'{k}.dataDate 类型错')
        if v.get('frequency') not in im.ALLOWED_FREQUENCIES:
            bad.append(f'{k}.frequency={v.get("frequency")!r}')
    check(f'S1-02[{label}]', not bad, '; '.join(bad[:6]))

    derived = ('dataDateISO', 'dataDateKind', 'days_stale', 'overdue', 'overdue_level',
               'days_overdue', 'staleness_rule', 'realtime', 'reference_only',
               'excluded_from_scoring', 'exclusion_reason', 'degraded_reasons')
    bad = [f'{k}.{f}' for k, v in ind.items() for f in derived if f not in v]
    check(f'S1-03[{label}]', not bad, '缺失: ' + ', '.join(bad[:8]))

    shown = ('name', 'displayName', 'shortName', 'caliberNote', 'category', 'country',
             'signal', 'trend', 'score', 'timeliness', 'freshness', 'freshness_level')
    bad = [f'{k}.{f}' for k, v in ind.items() for f in shown if f not in v]
    check(f'S1-04[{label}]', not bad, '缺失: ' + ', '.join(bad[:8]))

    bad = []
    for k, v in ind.items():
        if v['country'] not in im.ALLOWED_COUNTRIES:
            bad.append(f'{k}.country={v["country"]!r}')
        if v['category'] not in ({d["id"] for d in im.DIMENSIONS} | {'other'}):
            bad.append(f'{k}.category={v["category"]!r}')
        if v['trend'] not in {'up', 'down', 'neutral'}:
            bad.append(f'{k}.trend={v["trend"]!r}')
        if v['signal'] not in SIGNALS:
            bad.append(f'{k}.signal={v["signal"]!r}')
        if v['freshness_level'] not in FRESHNESS_LEVELS:
            bad.append(f'{k}.freshness_level={v["freshness_level"]!r}')
        if v['freshness'] not in {s['icon'] for s in im.FRESHNESS_STATES.values()}:
            bad.append(f'{k}.freshness={v["freshness"]!r}')
        if not (0.0 <= float(v['timeliness']) <= 1.0):
            bad.append(f'{k}.timeliness={v["timeliness"]!r}')
        if v['score'] is not None and not (-1.0 <= float(v['score']) <= 1.0):
            bad.append(f'{k}.score={v["score"]!r}')
    check(f'S1-05[{label}]', not bad, '; '.join(bad[:6]))

    bad = []
    for k, v in ind.items():
        if v['name'] != v['displayName']:
            bad.append(f'{k}.name != displayName')
        if not v['shortName'] or not v['caliberNote']:
            bad.append(f'{k}.shortName/caliberNote 空')
        if v['score'] is None and v['signal'] != 'gray':
            bad.append(f'{k}.score=null signal={v["signal"]}')
    check(f'S1-06[{label}]', not bad, '; '.join(bad[:6]))

    bad = []
    for k, v in ind.items():
        d = data.get(k, {})
        for f in ('value', 'unit', 'source', 'frequency', 'dataDate'):
            if v.get(f) != d.get(f):
                bad.append(f'{k}.{f}: {v.get(f)!r} != {d.get(f)!r}')
    check(f'S1-07[{label}]', not bad, '; '.join(bad[:6]))

    bad = []
    for k, v in ind.items():
        p = im.parse_period(v.get('dataDate'))
        want_iso = p['end'].isoformat() if p else None
        want_kind = p['kind'] if p else None
        if v['dataDateISO'] != want_iso:
            bad.append(f'{k}.ISO {v["dataDateISO"]!r} != {want_iso!r}')
        if v['dataDateKind'] != want_kind:
            bad.append(f'{k}.kind {v["dataDateKind"]!r} != {want_kind!r}')
    check(f'S1-08[{label}]', not bad, '; '.join(bad[:6]))

    bad = []
    for k, v in ind.items():
        want = days_stale_of(v['dataDateISO'], ref)
        if want is not None:
            want = max(0, want)
        if v['days_stale'] != want:
            bad.append(f'{k}.days_stale {v["days_stale"]!r} != {want!r}')
    check(f'S1-09[{label}]', not bad, '; '.join(bad[:6]))

    bad = []
    for k, v in ind.items():
        want = (v['exclusion_reason'] == 'no_score')
        if (v['score'] is None) != want:
            bad.append(f'{k}.score={v["score"]!r} reason={v["exclusion_reason"]!r}')
    check(f'S1-10[{label}]', not bad, '; '.join(bad[:6]))

    bad = []
    for k, v in ind.items():
        r = v['exclusion_reason']
        if r is not None and r not in EXCLUSION_REASONS:
            bad.append(f'{k}.reason={r!r}')
        if bool(v['excluded_from_scoring']) != (r is not None):
            bad.append(f'{k}.excluded 与 reason 不一致')
        if not isinstance(v['overdue'], bool):
            bad.append(f'{k}.overdue 非 bool')
        if v['overdue_level'] not in {'none', 'yellow', 'red'}:
            bad.append(f'{k}.overdue_level={v["overdue_level"]!r}')
        if v['days_overdue'] is not None and not isinstance(v['days_overdue'], int):
            bad.append(f'{k}.days_overdue 非 int/null')
        if v['staleness_rule'] != im.TIMELINESS_RULES.get(
                v['frequency'], im.TIMELINESS_RULES['other']):
            bad.append(f'{k}.staleness_rule 与 TIMELINESS_RULES 不一致')
        if not set(v['degraded_reasons']) <= DEGRADED_REASONS:
            bad.append(f'{k}.degraded_reasons={v["degraded_reasons"]!r}')
    check(f'S1-11[{label}]', not bad, '; '.join(bad[:6]))


# ═══════════════════════════════════════════
# S2 source 白名单 / 口径
# ═══════════════════════════════════════════

def test_s2(doc, text, label, live):
    ind, data = doc['indicators'], doc['data']
    keys = [k for k in ind if not (not live and k == 'newIndicatorSample')]
    bad = []
    for k in keys:
        want = EXPECTED_SOURCE.get(k)
        if want is None:
            bad.append(f'{k} 不在冻结表')
            continue
        if ind[k]['source'] != want[0]:
            bad.append(f'{k}.source {ind[k]["source"]!r} != {want[0]!r}')
        if ind[k]['country'] != want[1]:
            bad.append(f'{k}.country {ind[k]["country"]!r} != {want[1]!r}')
        if ind[k]['frequency'] != want[2]:
            bad.append(f'{k}.frequency {ind[k]["frequency"]!r} != {want[2]!r}')
    check(f'S2-01[{label}]', not bad, '; '.join(bad[:6]))

    low = text.lower()
    hits = [s for s in ('alternative.me', 'policyuncertainty.com') if s in low]
    check(f'S2-02[{label}]', not hits, f'旧源残留: {hits}')

    if live:
        v = ind['vix']
        ok = ('QVIX' in v['displayName'] and '沪深300' in v['displayName']
              and '非CBOE VIX' in v['caliberNote'] and v['country'] == '🇨🇳')
        check(f'S2-03[{label}]', ok, json.dumps(
            {k: v[k] for k in ('source', 'displayName', 'caliberNote', 'country')},
            ensure_ascii=False))

        fg = ind['fearGreed']
        ok = ('CNN' in fg['displayName'] and 'CNN' in fg['source']
              and '非A股' in fg['caliberNote'] and fg['country'] == '🇺🇸')
        check(f'S2-04[{label}]', ok, json.dumps(
            {k: fg[k] for k in ('source', 'displayName', 'caliberNote', 'country')},
            ensure_ascii=False))

        cs = ind['creditSpread']
        ok = ('中美10年' in cs['displayName'] and '非信用利差' in cs['caliberNote']
              and cs['unit'] == 'bp' and cs['country'] == '🌐')
        check(f'S2-05[{label}]', ok, json.dumps(
            {k: cs[k] for k in ('source', 'displayName', 'caliberNote', 'unit', 'country')},
            ensure_ascii=False))

    bad = []
    for k in keys:
        s = ind[k]['source']
        if s != s.strip() or not s:
            bad.append(f'{k}.source 空白')
        if any(p in s for p in ('N/A', 'unknown', 'TODO', '测试')):
            bad.append(f'{k}.source 占位词: {s!r}')
    check(f'S2-06[{label}]', not bad, '; '.join(bad[:6]))

    if live:
        bad = []
        for k, meta in im.INDICATORS.items():
            want = EXPECTED_SOURCE.get(k)
            got = (meta['source'], meta['country'], meta['frequency'])
            if got != want:
                bad.append(f'{k}: {got} != {want}')
        check(f'S2-07[{label}]', not bad, '; '.join(bad[:6]))
        check(f'S2-08[{label}]', set(EXPECTED_SOURCE) == set(im.INDICATORS),
              f'冻结表 {len(EXPECTED_SOURCE)} vs 元数据 {len(im.INDICATORS)}')

    check(f'S2-09[{label}]', set(EXPECTED_SOURCE) >= {k for k in ind}, '存在未知指标 key')


# ═══════════════════════════════════════════
# S3 validity / failed / degraded
# ═══════════════════════════════════════════

def test_s3(doc, label):
    data, ind, v = doc['data'], doc['indicators'], doc['validity_report']
    total = len(data)
    valid = sum(1 for x in data.values() if x.get('value') is not None)
    check(f'S3-01[{label}]',
          v['total'] == total and v['valid'] == valid
          and v['invalid'] == total - valid and v['valid'] + v['invalid'] == total,
          f"total={v['total']}/{total} valid={v['valid']}/{valid} invalid={v['invalid']}")

    degraded = v.get('degraded')
    check(f'S3-02[{label}]', isinstance(degraded, list), f'degraded 非数组: {type(degraded).__name__}')
    if isinstance(degraded, list):
        pairs = [(k, r) for k, x in ind.items() for r in x['degraded_reasons']]
        got = [(x['key'], x['reason']) for x in degraded]
        check(f'S3-03[{label}]', sorted(got) == sorted(pairs),
              f'got={sorted(got)} want={sorted(pairs)}')
        check(f'S3-04[{label}]', v.get('degraded_count') == len(degraded),
              f"degraded_count={v.get('degraded_count')} len={len(degraded)}")
        bad = [x['key'] for x in degraded if x['reason'] not in DEGRADED_REASONS]
        check(f'S3-05[{label}]', not bad, f'非法 reason: {bad}')
        bad = []
        for x in degraded:
            for f in ('key', 'displayName', 'source', 'reason', 'reasonText',
                      'dataDate', 'dataDateISO', 'days_stale', 'timeliness',
                      'freshness', 'freshness_level'):
                if f not in x:
                    bad.append(f'{x.get("key")}.{f} 缺失')
            if not x.get('reasonText'):
                bad.append(f'{x.get("key")}.reasonText 空')
            src = ind.get(x['key'], {})
            for f in ('timeliness', 'freshness', 'freshness_level'):
                if src.get(f) != x.get(f):
                    bad.append(f'{x["key"]}.{f} 与 indicators 不一致')
        check(f'S3-06[{label}]', not bad, '; '.join(bad[:6]))

    fkeys = [x['key'] for x in v['failed']]
    check(f'S3-07[{label}]', len(fkeys) == len(set(fkeys)), 'failed key 重复')
    want_failed = {k for k, x in data.items()
                   if x.get('value') is None or x.get('fetchError') is not None}
    check(f'S3-08[{label}]', set(fkeys) == want_failed,
          f'got={sorted(set(fkeys))} want={sorted(want_failed)}')

    bad = []
    for x in v['failed']:
        if x.get('reason') not in FETCH_REASONS:
            bad.append(f'{x.get("key")}.reason={x.get("reason")!r}')
        if not x.get('reasonText'):
            bad.append(f'{x.get("key")}.reasonText 空')
        if not isinstance(x.get('used_fallback'), bool):
            bad.append(f'{x.get("key")}.used_fallback 非 bool')
        for f in ('key', 'displayName', 'source', 'dataDate', 'days_stale', 'lastAttempt'):
            if f not in x:
                bad.append(f'{x.get("key")}.{f} 缺失')
    check(f'S3-09[{label}]', not bad, '; '.join(bad[:6]))

    bad = []
    for x in v['failed']:
        k = x['key']
        if x['used_fallback']:
            if data[k].get('value') is None:
                bad.append(f'{k} 兜底但无值')
            if not ind.get(k, {}).get('used_fallback'):
                bad.append(f'{k} indicators 未标 used_fallback')
            if ind[k]['timeliness'] > 0.5 + 1e-9:
                bad.append(f'{k} 兜底 alpha={ind[k]["timeliness"]} > 0.5')
            if ind[k]['freshness_level'] not in {'stale', 'expired', 'unknown'}:
                bad.append(f'{k} 兜底 freshness={ind[k]["freshness_level"]}')
            if ind[k]['realtime']:
                bad.append(f'{k} 兜底却标 realtime')
        else:
            if data[k].get('value') is not None:
                bad.append(f'{k} 非兜底失败却有值')
    check(f'S3-10[{label}]', not bad, '; '.join(bad[:6]))

    fb_keys = {x['key'] for x in v['failed'] if x['used_fallback']}
    deg_fb = {x['key'] for x in (degraded or []) if x['reason'] == 'used_fallback'}
    check(f'S3-11[{label}]', fb_keys == deg_fb, f'{fb_keys} != {deg_fb}')


# ═══════════════════════════════════════════
# S4 IAS
# ═══════════════════════════════════════════

def test_s4(doc, label):
    ias, dims = doc['meta']['ias'], doc['meta']['dimensions']
    check(f'S4-01[{label}]',
          isinstance(ias.get('score'), (int, float))
          and isinstance(ias.get('normalized'), (int, float))
          and -1 <= ias['normalized'] <= 1
          and abs(ias['score'] - ias['normalized'] * ias['ias_scale']) <= 0.011,
          f'score={ias.get("score")} norm={ias.get("normalized")} scale={ias.get("ias_scale")}')

    design_sum = round(sum(d['weight'] for d in im.DIMENSIONS), 2)
    check(f'S4-02[{label}]',
          ias.get('ias_scale') == design_sum == ias.get('weight_design_sum')
          == ias.get('max_possible'),
          f"ias_scale={ias.get('ias_scale')} design={design_sum} "
          f"sum={ias.get('weight_design_sum')} max={ias.get('max_possible')}")

    weff_sum = round(sum(d['weight_effective'] for d in dims.values()), 4)
    check(f'S4-03[{label}]', abs(ias['weight_effective_sum'] - weff_sum) < 1e-9,
          f"{ias['weight_effective_sum']} != {weff_sum}")
    bad = [f"{k}={d['weight_effective']}" for k, d in dims.items()
           if not (0 < d['weight_effective'] <= d['weight_design'])]
    check(f'S4-04[{label}]', not bad, '; '.join(bad))

    check(f'S4-05[{label}]',
          ias['scale_coverage'] == round(weff_sum / design_sum, 3),
          f"{ias['scale_coverage']} != {round(weff_sum / design_sum, 3)}")

    counted = set(ias['counted_dimensions'])
    grayed = set(ias['grayed_dimensions'])
    want_counted = {k for k, d in dims.items()
                    if not d['insufficient_data'] and d['score'] is not None}
    check(f'S4-06[{label}]',
          counted == want_counted and grayed == set(dims) - counted
          and not counted & grayed and counted | grayed == set(dims),
          f'counted={sorted(counted)} grayed={sorted(grayed)}')

    valid_weight = round(sum(dims[k]['weight_effective'] for k in counted), 4)
    check(f'S4-07[{label}]', abs(ias['valid_weight'] - valid_weight) < 1e-9,
          f"{ias['valid_weight']} != {valid_weight}")
    want_cov = round(valid_weight / weff_sum, 3) if weff_sum else 0.0
    check(f'S4-08[{label}]', abs(ias['data_coverage'] - want_cov) < 1e-9,
          f"{ias['data_coverage']} != {want_cov}")

    if valid_weight > 0:
        # T15 新 spec：normalized 6 位、score 2 位、round half away from zero。
        # 测试独立用 Decimal 实现，不调 indicator_meta.q / scoring.q。
        def q_half_up(x, places):
            return float(Decimal(str(x)).quantize(Decimal('1.' + '0' * places),
                                                  rounding=ROUND_HALF_UP))

        want_norm_raw = sum(dims[k]['score'] * dims[k]['weight_effective']
                            for k in counted) / valid_weight
        want_norm = q_half_up(want_norm_raw, 6)
        want_score = q_half_up(want_norm * im.IAS_SCALE, 2)
        check(f'S4-09[{label}]',
              abs(ias['normalized'] - want_norm) <= 1e-12
              and abs(ias['score'] - want_score) <= 1e-12,
              f"norm {ias['normalized']} != {want_norm}; score {ias['score']} != {want_score}")
        check(f'S4-09b[{label}]',
              Decimal(str(ias['normalized'])).as_tuple().exponent >= -6
              and Decimal(str(ias['score'])).as_tuple().exponent >= -2,
              f"精度超限: norm={ias['normalized']!r} score={ias['score']!r}")
    else:
        check(f'S4-09[{label}]', ias['normalized'] is None and ias['score'] is None,
              '无有效权重时 normalized/score 应为 null')

    # 阈值表冻结 + 分档
    want_bands = [(2.5, '强烈买入', '80-100%', '🚀'), (1.0, '增持', '60-80%', '✅'),
                  (-0.5, '持有', '40-60%', '➖'), (-1.5, '减仓', '20-40%', '⚠️')]
    check(f'S4-10[{label}]', [tuple(x) for x in im.IAS_THRESHOLDS] == want_bands,
          f'{im.IAS_THRESHOLDS}')
    check(f'S4-11[{label}]', im.IAS_MIN_COVERAGE == 0.6 and im.IAS_PARTIAL_COVERAGE == 0.8,
          f'{im.IAS_MIN_COVERAGE}/{im.IAS_PARTIAL_COVERAGE}')

    base = ias['signal'].split('（')[0]
    if ias['data_coverage'] < im.IAS_MIN_COVERAGE:
        want = ('数据不足', '不适用', '⚪')
    else:
        want = im.IAS_POSITION_ERROR
        for t, s, p, i in want_bands:
            if ias['score'] >= t:
                want = (s, p, i)
                break
    check(f'S4-12[{label}]',
          (base, ias['position'], ias['signal_icon']) == want,
          f"got={(base, ias['position'], ias['signal_icon'])} want={want}")

    if ias['data_coverage'] < im.IAS_MIN_COVERAGE:
        check(f'S4-13[{label}]', ias['is_actionable'] is False, '低覆盖仍 actionable')
    elif ias['data_coverage'] < im.IAS_PARTIAL_COVERAGE:
        check(f'S4-14[{label}]',
              ias['signal'].endswith('（部分维度缺失·参考）') and ias['is_actionable'] is True,
              ias['signal'])
    else:
        check(f'S4-14[{label}]', '（部分' not in ias['signal'] and ias['is_actionable'] is True,
              ias['signal'])


# ═══════════════════════════════════════════
# S5 维度
# ═══════════════════════════════════════════

def test_s5(doc, label):
    dims = doc['meta']['dimensions']
    check(f'S5-01[{label}]', set(dims) == {d['id'] for d in im.DIMENSIONS},
          f'{set(dims)} != {{dim ids}}')
    bad = []
    for d in im.DIMENSIONS:
        x = dims[d['id']]
        if x['weight'] != d['weight'] or x['weight_design'] != d['weight']:
            bad.append(f'{d["id"]}.weight')
        if x['name'] != d['name'] or x['icon'] != d['icon']:
            bad.append(f'{d["id"]}.name/icon')
    check(f'S5-02[{label}]', not bad, '; '.join(bad))
    check(f'S5-03[{label}]',
          abs(sum(d['weight_design'] for d in dims.values()) - im.IAS_SCALE) < 1e-9,
          f'{sum(d["weight_design"] for d in dims.values())} != {im.IAS_SCALE}')

    bad = []
    for d in im.DIMENSIONS:
        x = dims[d['id']]
        active = [k for k in d['indicators'] if not im.is_reference_only(k)]
        refs = [k for k in d['indicators'] if im.is_reference_only(k)]
        if x['required_count'] != expected_required(len(active)):
            bad.append(f'{d["id"]}.required {x["required_count"]} != {expected_required(len(active))}')
        if x['active_count'] != len(active):
            bad.append(f'{d["id"]}.active {x["active_count"]} != {len(active)}')
        if x['reference_only_count'] != len(refs):
            bad.append(f'{d["id"]}.ref {x["reference_only_count"]} != {len(refs)}')
    check(f'S5-04[{label}]', not bad, '; '.join(bad))

    ind = doc['indicators']
    bad = []
    for d in im.DIMENSIONS:
        x = dims[d['id']]
        active = [k for k in d['indicators'] if not im.is_reference_only(k)]
        valid = [k for k in active
                 if ind.get(k) and ind[k]['score'] is not None and ind[k]['timeliness'] > 0]
        if x['valid_count'] != len(valid):
            bad.append(f'{d["id"]}.valid {x["valid_count"]} != {len(valid)}')
        if x['insufficient_data'] != (len(valid) < x['required_count']):
            bad.append(f'{d["id"]}.insufficient 与 valid/required 不符')
        if x['insufficient_data'] and x['score'] is not None:
            bad.append(f'{d["id"]} 置灰但 score={x["score"]}')
        if not x['insufficient_data'] and x['score'] is None:
            bad.append(f'{d["id"]} 未置灰但 score=null')
    check(f'S5-05[{label}]', not bad, '; '.join(bad))

    bad = []
    for d in im.DIMENSIONS:
        x = dims[d['id']]
        active = [k for k in d['indicators'] if not im.is_reference_only(k)]
        valid = [(ind[k]['score'], ind[k]['timeliness']) for k in active
                 if ind.get(k) and ind[k]['score'] is not None and ind[k]['timeliness'] > 0]
        if valid:
            sa = sum(a for _, a in valid)
            want = round(sum(s * a for s, a in valid) / sa, 3)
            if abs(x['score'] - want) > 1e-9:
                bad.append(f'{d["id"]}.score {x["score"]} != {want}')
            # T14: avg_alpha = Σα(score≠null) / active_count（含 α=0），不是 /valid_count
            alpha_sum = sum(ind[k]['timeliness'] for k in active
                            if ind.get(k) and ind[k]['score'] is not None)
            want_avg = round(alpha_sum / len(active), 3)
            if abs(x['avg_alpha'] - want_avg) > 1e-9:
                bad.append(f'{d["id"]}.avg_alpha {x["avg_alpha"]} != {want_avg}')
    check(f'S5-06[{label}]', not bad, '; '.join(bad))

    bad = []
    for d in im.DIMENSIONS:
        x = dims[d['id']]
        active = sum(1 for k in d['indicators'] if not im.is_reference_only(k))
        mismatch = float(d.get('market_mismatch', 1.0) or 1.0)
        want = round(d['weight'] * (active / len(d['indicators'])) * mismatch, 4)
        if abs(x['weight_effective'] - want) > 1e-9:
            bad.append(f'{d["id"]}.w_eff {x["weight_effective"]} != {want}')
    check(f'S5-07[{label}]', not bad, '; '.join(bad))

    bad = []
    for d in im.DIMENSIONS:
        x = dims[d['id']]
        want_sig = 'gray' if x['insufficient_data'] else scoring.get_signal(x['score'])
        if x['signal'] != want_sig:
            bad.append(f'{d["id"]}.signal {x["signal"]} != {want_sig}')
    check(f'S5-08[{label}]', not bad, '; '.join(bad))


# ═══════════════════════════════════════════
# S6 期日 / 时效 / 五态
# ═══════════════════════════════════════════

def test_s6(doc, label, ref):
    ind = doc['indicators']
    check(f'S6-01[{label}]', set(im.TIMELINESS_RULES) >= set(im.ALLOWED_FREQUENCIES),
          f'{sorted(im.TIMELINESS_RULES)}')

    bad = []
    for k, v in ind.items():
        st, icon, alpha, ds, reasons = expected_freshness(
            v['dataDateISO'], v['frequency'], v['realtime'],
            bool(v.get('used_fallback')), ref)
        if v['freshness_level'] != st:
            bad.append(f'{k}.state {v["freshness_level"]} != {st}')
        if v['freshness'] != icon:
            bad.append(f'{k}.icon {v["freshness"]} != {icon}')
        if abs(v['timeliness'] - alpha) > 1e-9:
            bad.append(f'{k}.alpha {v["timeliness"]} != {alpha}')
        if (v['days_stale'] is None) != (ds is None):
            bad.append(f'{k}.days_stale null 不一致')
        if v['degraded_reasons'] != reasons:
            bad.append(f'{k}.degraded_reasons {v["degraded_reasons"]} != {reasons}')
    check(f'S6-02[{label}]', not bad, '; '.join(bad[:8]))

    bad = []
    for k, v in ind.items():
        rule = im.TIMELINESS_RULES.get(v['frequency'], im.TIMELINESS_RULES['other'])
        ds = v['days_stale']
        if ds is None:
            want = (False, 'none', None)
        elif ds > rule['red_days']:
            want = (True, 'red', ds - rule['red_days'])
        elif ds > rule['yellow_days']:
            want = (True, 'yellow', ds - rule['yellow_days'])
        else:
            want = (False, 'none', 0)
        if (v['overdue'], v['overdue_level'], v['days_overdue']) != want:
            bad.append(f'{k} got={(v["overdue"], v["overdue_level"], v["days_overdue"])} want={want}')
    check(f'S6-03[{label}]', not bad, '; '.join(bad[:6]))

    # 季末 / 月末 / 年末
    bad = []
    for k, v in ind.items():
        p = im.parse_period(v['dataDate'])
        if not p:
            continue
        d = p['end']
        import calendar
        if p['kind'] in ('quarter', 'cumulative'):
            if d.day != calendar.monthrange(d.year, d.month)[1] or d.month not in (3, 6, 9, 12):
                bad.append(f'{k} 季末={d}')
        if p['kind'] == 'month':
            if d.day != calendar.monthrange(d.year, d.month)[1]:
                bad.append(f'{k} 月末={d}')
        if p['kind'] == 'year' and (d.month, d.day) != (12, 31):
            bad.append(f'{k} 年末={d}')
    check(f'S6-04[{label}]', not bad, '; '.join(bad[:6]))

    # 已知锚点（仅在真实生产 JSON 上跑）
    if label == 'live':
        g = ind['chinaGdp']
        want_g_days = (ref - date(2026, 9, 30)).days
        check('S6-05[live]',
              (g['dataDateISO'], g['days_stale'], g['timeliness'], g['dataDateKind'])
              == ('2026-09-30', want_g_days, 1.0, 'cumulative'),
              json.dumps({x: g[x] for x in ('dataDateISO', 'days_stale', 'timeliness', 'dataDateKind')}))
        u = ind['usGdp']
        rule = im.TIMELINESS_RULES['quarterly']
        want_alpha = 0.0 if u['days_stale'] > rule['red_days'] else (
            0.5 if u['days_stale'] > rule['yellow_days'] else 1.0)
        want_u_days = (ref - date(2026, 3, 31)).days
        check('S6-06[live]',
              (u['dataDateISO'], u['days_stale'], u['timeliness'], u['freshness_level'])
              == ('2026-03-31', want_u_days, want_alpha, 'expired' if want_alpha == 0 else 'stale'),
              json.dumps({x: u[x] for x in ('dataDateISO', 'days_stale', 'timeliness', 'freshness_level')}))

    # 五态互斥 / 一态一图标
    states = im.FRESHNESS_STATES
    want_state_alpha = {'fresh': 1.0, 'realtime': 1.0, 'unknown': im.UNKNOWN_ALPHA,
                        'stale': 0.5, 'expired': 0.0}
    # α 只有 3 个不同值（fresh/realtime 同为 1.0；unknown/stale 同为 0.5）；
    # 「互斥」指前置条件互斥，不是 α 唯一。
    matrix = [
        ((ref - timedelta(days=1)).isoformat(), 'daily', False, False, 'fresh'),
        ((ref - timedelta(days=7)).isoformat(), 'daily', False, False, 'stale'),
        ((ref - timedelta(days=20)).isoformat(), 'daily', False, False, 'expired'),
        (None, 'daily', True, False, 'realtime'),
        (None, 'daily', False, False, 'unknown'),
    ]
    bad = []
    for dd, freq, rt, fb, want in matrix:
        got = im.resolve_freshness(dd, freq, realtime=rt, used_fallback=fb, today=ref)['state']
        if got != want:
            bad.append(f'{dd!r}/{rt}/{fb}: {got} != {want}')
    check(f'S6-07[{label}]',
          set(states) == set(want_state_alpha)
          and len({s['icon'] for s in states.values()}) == 5
          and len({s['alpha'] for s in states.values()}) == 3
          and len({s['prerequisite'] for s in states.values()}) == 5
          and all(states[k]['alpha'] == v for k, v in want_state_alpha.items())
          and not bad,
          json.dumps({'states': {k: (v['icon'], v['alpha']) for k, v in states.items()},
                      'matrix': bad}, ensure_ascii=False))
    check(f'S6-08[{label}]',
          im.FRESHNESS_STATES['unknown']['alpha'] == im.UNKNOWN_ALPHA == 0.5,
          f"unknown alpha={im.FRESHNESS_STATES['unknown']['alpha']}")

    # 无日期：非 realtime 不得亮绿灯
    bad = []
    for k, v in ind.items():
        if v['dataDateISO'] is None and v['freshness_level'] == 'fresh':
            bad.append(k)
    check(f'S6-09[{label}]', not bad, f'无日期却 fresh: {bad}')


def test_s6_boundaries():
    """三档 α 的 12 个边界（阈值从 TIMELINESS_RULES 读，不写死）。"""
    ref = date(2026, 11, 9)
    from datetime import timedelta
    bad = []
    for freq in ('daily', 'monthly', 'quarterly'):
        rule = im.TIMELINESS_RULES[freq]
        for n, want in ((rule['yellow_days'], 1.0),
                        (rule['yellow_days'] + 1, 0.5),
                        (rule['red_days'], 0.5),
                        (rule['red_days'] + 1, 0.0)):
            ds = (ref - timedelta(days=n)).isoformat()
            got = im.resolve_freshness(ds, freq, today=ref)['alpha']
            if got != want:
                bad.append(f'{freq}@{n}d={got} want={want}')
    check('S6-10[unit]', not bad, '; '.join(bad))

    # S6-U1：未来期（年末未到）按 0 天算，days_stale 不保留负数
    fut = im.resolve_freshness('2026-12-31', 'yearly', today=ref)
    check('S6-U1[unit]', fut['days_stale'] == 0 and fut['alpha'] == 1.0,
          json.dumps(fut, ensure_ascii=False))


# ═══════════════════════════════════════════
# S7 结构 / 规则快照 / 严格 JSON
# ═══════════════════════════════════════════

def canonical_hash(obj):
    """独立实现 T15-2 公开规格：sort_keys + 紧凑 separators + sha256 前 12 位。"""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False,
                   separators=(',', ':')).encode('utf-8')
    ).hexdigest()[:12]


def test_s7(doc, text, label, live):
    ref = ref_date_of(doc)
    check(f'S7-01[{label}]', isinstance(doc.get('timestamp'), str),
          'timestamp 缺失')

    meta = doc['meta']
    model = meta.get('model', {})
    check(f'S7-02[{label}]',
          model.get('version') == 'v4.2'
          and model.get('reference_only') == sorted(im.REFERENCE_ONLY)
          and model.get('min_coverage') == im.IAS_MIN_COVERAGE
          and bool(model.get('ias_formula')),
          json.dumps(model, ensure_ascii=False)[:300])

    snap = meta.get('rules_snapshot')
    rhash = meta.get('rules_hash')
    check(f'S7-03[{label}]', isinstance(snap, dict) and bool(snap),
          'meta.rules_snapshot 缺失或为空（龙五 T13 要求）')
    check(f'S7-04[{label}]', isinstance(rhash, str) and bool(re.fullmatch(r'[0-9a-f]{12}', rhash)),
          f'meta.rules_hash={rhash!r}')
    if isinstance(snap, dict) and snap:
        check(f'S7-05[{label}]', canonical_hash(snap) == rhash,
              f'hash 不匹配: canonical={canonical_hash(snap)} rules_hash={rhash}')
        need = ('staleness_rules', 'dimension_weights_design', 'ias_scale', 'min_valid_rule')
        miss = [x for x in need if x not in snap]
        check(f'S7-06[{label}]', not miss, f'缺字段: {miss}')
        if 'staleness_rules' in snap:
            check(f'S7-07[{label}]', snap['staleness_rules'] == im.TIMELINESS_RULES,
                  'staleness_rules 与 TIMELINESS_RULES 不一致')
        if 'ias_scale' in snap:
            check(f'S7-08[{label}]', snap['ias_scale'] == im.IAS_SCALE,
                  f"{snap['ias_scale']} != {im.IAS_SCALE}")
        if 'dimension_weights_design' in snap:
            dw = snap['dimension_weights_design']
            bad = []
            for d in im.DIMENSIONS:
                if dw.get(d['id']) != d['weight']:
                    bad.append(f'{d["id"]}: {dw.get(d["id"])} != {d["weight"]}')
            mm = snap.get('market_mismatch', {})
            for d in im.DIMENSIONS:
                want = d.get('market_mismatch', 1.0)
                if want != 1.0 and mm.get(d['id']) != want:
                    bad.append(f'{d["id"]}.mismatch={mm.get(d["id"])} != {want}')
            check(f'S7-09[{label}]', not bad, f'维度权重快照不一致: {bad}')
        if 'min_valid_rule' in snap:
            check(f'S7-10[{label}]', bool(snap['min_valid_rule']), 'min_valid_rule 为空')

    check(f'S7-11[{label}]',
          'NaN' not in text and 'Infinity' not in text,
          '文本含 NaN/Infinity 字面量')

    bad = [k for k, v in doc['indicators'].items()
           if v['country'] not in im.ALLOWED_COUNTRIES]
    check(f'S7-12[{label}]', not bad, f'country 越界: {bad}')
    bad = [k for k, v in doc['indicators'].items()
           if v['frequency'] not in im.ALLOWED_FREQUENCIES]
    check(f'S7-13[{label}]', not bad, f'frequency 越界: {bad}')

    if live:
        check(f'S7-14[{label}]', set(doc['data']) == set(im.INDICATORS),
              f"data keys {len(doc['data'])} vs INDICATORS {len(im.INDICATORS)}")
        check(f'S7-15[{label}]',
              set(doc['indicators']) == {k for k, v in doc['data'].items()
                                         if v.get('value') is not None},
              'indicators 与 data 非空值集合不一致')
    else:
        extra = set(doc['data']) - set(im.INDICATORS)
        check(f'S7-16[{label}]', extra == {'newIndicatorSample'}, f'夹具额外 key={extra}')


# ═══════════════════════════════════════════
# S8 夹具分支矩阵
# ═══════════════════════════════════════════

def test_s8(fix):
    ind = fix['indicators']

    def branch(k, state, reason, excluded=True):
        x = ind.get(k)
        check(f'S8[{k}]',
              bool(x) and x['freshness_level'] == state
              and x['excluded_from_scoring'] is excluded
              and (x['exclusion_reason'] == reason if excluded else x['exclusion_reason'] is None),
              json.dumps({kk: x.get(kk) for kk in
                          ('freshness_level', 'exclusion_reason', 'excluded_from_scoring')},
                         ensure_ascii=False) if x else 'missing')

    branch('chinaGdp', 'expired', 'expired_alpha0')
    for k in ('usBond2Y', 'usBond5Y', 'usBond10Y', 'dollarIndex', 'lpr',
              'dr007', 'm2', 'creditSpread', 'renewEnergyInvest', 'evPenetration'):
        branch(k, 'expired', 'expired_alpha0')
    branch('aiGrowth', 'fresh', 'reference_only')
    branch('robotInstall', 'fresh', 'reference_only')
    branch('newIndicatorSample', 'fresh', 'no_score')
    check('S8[reference signal]',
          all(ind[k]['signal'] == 'reference' for k in ('aiGrowth', 'robotInstall')),
          f"{[(k, ind[k]['signal']) for k in ('aiGrowth', 'robotInstall')]}")
    check('S8[no_score]', ind['newIndicatorSample']['score'] is None
          and ind['newIndicatorSample']['signal'] == 'gray')

    liq, tech = fix['meta']['dimensions']['liquidity'], fix['meta']['dimensions']['techGreen']
    check('S8[liq gray]', liq['insufficient_data'] is True and liq['score'] is None
          and liq['valid_count'] < liq['required_count'],
          json.dumps(liq, ensure_ascii=False))
    check('S8[tech gray]', tech['insufficient_data'] is True and tech['score'] is None
          and tech['active_count'] == 2 and tech['reference_only_count'] == 2
          and tech['weight_effective'] == 0.2,
          json.dumps(tech, ensure_ascii=False))

    for k in ('naturalGas', 'lmeIndex'):
        x = ind[k]
        check(f'S8[realtime {k}]',
              x['realtime'] is True and x['dataDate'] is None and x['dataDateISO'] is None
              and x['days_stale'] is None and x['freshness'] == '🔵'
              and x['freshness_level'] == 'realtime' and x['timeliness'] == 1.0
              and bool(x['dateNote']),
              json.dumps(x, ensure_ascii=False)[:300])

    u = ind['usGdp']
    check('S8[unknown]', u['dataDate'] is None and u['days_stale'] is None
          and u['freshness'] == '⚪' and u['freshness_level'] == 'unknown'
          and u['timeliness'] == im.UNKNOWN_ALPHA,
          json.dumps(u, ensure_ascii=False)[:300])

    op = ind['oilPrice']
    check('S8[fallback]', op['used_fallback'] is True and op['timeliness'] <= 0.5
          and op['freshness_level'] in {'unknown', 'stale'}
          and op['fetchError']['reason'] == 'not_found',
          json.dumps(op, ensure_ascii=False)[:300])

    check('S8[epu failed]', 'epu' not in ind
          and any(f['key'] == 'epu' and f['used_fallback'] is False
                  for f in fix['validity_report']['failed']))
    check('S8[coverage]', fix['meta']['ias']['data_coverage'] == 0.75
          and '（部分维度缺失·参考）' in fix['meta']['ias']['signal'],
          json.dumps(fix['meta']['ias'], ensure_ascii=False))


# ═══════════════════════════════════════════
# 白盒单测（构造夹具，不改产品代码）
# ═══════════════════════════════════════════

def test_units():
    # S4-U1：只有一个有效维度 → 低覆盖，不得给「持有」
    ds = {d['id']: {'score': None, 'insufficient_data': True,
                    'weight_effective': im.dimension_weights(d)['effective']}
          for d in im.DIMENSIONS}
    ds['sentiment'].update({'score': -0.5, 'insufficient_data': False})
    out = scoring.calc_ias(ds)
    check('S4-U1', out['data_coverage'] < im.IAS_MIN_COVERAGE
          and out['signal'] == '数据不足' and out['is_actionable'] is False
          and out['position'] == '不适用',
          json.dumps(out, ensure_ascii=False))

    # S4-U2：分档边界（>= 语义）；all dims 同分时 normalized == 该分
    def dims_all(v):
        return {d['id']: {'score': v, 'insufficient_data': False,
                          'weight_effective': im.dimension_weights(d)['effective']}
                for d in im.DIMENSIONS}

    def want_band(score):
        want = im.IAS_POSITION_ERROR
        for t, s_, p_, i_ in im.IAS_THRESHOLDS:
            if score >= t:
                return (s_, p_, i_)
        return want

    bad = []
    for t, _sig, _pos, _ico in im.IAS_THRESHOLDS:
        for v, expect_ge in (((t + 0.02) / im.IAS_SCALE, True),
                             ((t - 0.03) / im.IAS_SCALE, False)):
            out = scoring.calc_ias(dims_all(v))
            got = (out['signal'], out['position'], out['signal_icon'])
            want = want_band(out['score'])
            if got != want:
                bad.append(f'{t} score={out["score"]} got={got} want={want}')
            if (out['score'] >= t) != expect_ge:
                bad.append(f'{t} 构造分 {out["score"]} 未落在预期侧')
    check('S4-U2', not bad, '; '.join(bad))

    # S5-U1：维度全 α=0 → insufficient、score=None（旧实现会 -1.0）
    econ = [d for d in im.DIMENSIONS if d['id'] == 'economic'][0]
    ind = {k: {'score': -1.0, 'timeliness': 0.0, 'reference_only': im.is_reference_only(k)}
           for k in econ['indicators']}
    out = scoring.calc_dimension_scores(ind, {})['economic']
    check('S5-U1', out['insufficient_data'] is True and out['score'] is None
          and out['valid_count'] == 0,
          json.dumps(out, ensure_ascii=False))

    # S5-U2：全参考项维度 → active 0
    tech = [d for d in im.DIMENSIONS if d['id'] == 'techGreen'][0]
    # 显式构造「维内 4 个全是参考项」的分支；calc_dimension_scores 走的是元数据
    # 的 is_reference_only，因此临时 monkeypatch，测完立即恢复。
    ind = {k: {'score': 1.0, 'timeliness': 1.0, 'reference_only': True}
           for k in tech['indicators']}
    orig = scoring.is_reference_only
    try:
        scoring.is_reference_only = lambda _k: True
        out = scoring.calc_dimension_scores(ind, {})['techGreen']
    finally:
        scoring.is_reference_only = orig
    check('S5-U2', out['insufficient_data'] is True and out['active_count'] == 0
          and out['reference_only_count'] == 4
          and out['valid_count'] == 0 and out['score'] is None,
          json.dumps(out, ensure_ascii=False))

    # S5-U3：valid 2 < required 3 → 不出分
    ind = {k: None for k in econ['indicators']}
    for k in ('chinaPmi', 'usNonFarm'):
        ind[k] = {'score': 0.9, 'timeliness': 1.0, 'reference_only': False}
    out = scoring.calc_dimension_scores(ind, {})['economic']
    check('S5-U3', out['valid_count'] == 2 and out['required_count'] == 3
          and out['insufficient_data'] is True and out['score'] is None,
          json.dumps(out, ensure_ascii=False))


# ═══════════════════════════════════════════
# T6b 契约守卫（龙五 2026-11-09 派单）
# ═══════════════════════════════════════════

CONTRACT_DOC = WS / 'docs' / 'freshness-contract.md'


def _rules_from_contract_doc():
    """从冻结契约文档的 python 代码块解析 TIMELINESS_RULES（外部 oracle）。

    刻意不 import、也不在测试里复制常量：测试不回答「210 是否正确」，
    只回答「文档与代码是否一致」；正确性由龙五签字。
    解析失败 / 块不存在 / 无该赋值 → 一律 FAIL，禁止静默 skip。
    """
    if not CONTRACT_DOC.exists():
        return None, f'契约文档不存在: {CONTRACT_DOC}'
    text = CONTRACT_DOC.read_text(encoding='utf-8')
    blocks = re.findall(r'```python\s*\n(.*?)```', text, re.S)
    if not blocks:
        return None, '文档中无 ```python 代码块'
    hits, errs = [], []
    for i, b in enumerate(blocks):
        try:
            tree = ast.parse(b)
        except SyntaxError as e:
            errs.append(f'block#{i} SyntaxError: {e}')
            continue
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'TIMELINESS_RULES'
                            for t in node.targets)):
                try:
                    hits.append(ast.literal_eval(node.value))
                except Exception as e:  # noqa: BLE001
                    errs.append(f'block#{i} literal_eval: {e}')
    if not hits:
        return None, '未找到 TIMELINESS_RULES 赋值' + (f'（{"; ".join(errs)}）' if errs else '')
    if len(hits) > 1:
        return None, f'找到 {len(hits)} 处 TIMELINESS_RULES 赋值（应唯一，避免多真源）'
    return hits[0], None


def test_t6b1():
    """T6b-1：冻结文档 vs 代码常量，逐键逐值比对（文档为 oracle）。"""
    doc_rules, err = _rules_from_contract_doc()
    ok_shape = isinstance(doc_rules, dict) and bool(doc_rules)
    check('T6b1-01[doc]', ok_shape,
          (f'已解析到 {len(doc_rules)} 个频率键' if ok_shape
           else (err or f'未能从文档解析出非空 dict（got {type(doc_rules).__name__}）')))
    if not ok_shape:
        for cid in ('T6b1-02[doc]', 'T6b1-03[doc]'):
            check(cid, False, '文档 oracle 不可用，无法比对（禁止静默 skip）')
        return

    want, got = im.TIMELINESS_RULES, doc_rules
    bad = []
    if set(got) != set(want):
        bad.append(f'键集合 文档={sorted(got)} 代码={sorted(want)}')
    for k in sorted(set(got) & set(want)):
        if not isinstance(got[k], dict) or 'yellow_days' not in got[k]:
            bad.append(f'{k}.yellow_days 缺失/非对象')
        elif got[k]['yellow_days'] != want[k]['yellow_days']:
            bad.append(f"{k}.yellow_days 文档={got[k]['yellow_days']} 代码={want[k]['yellow_days']}")
    check('T6b1-02[doc]', not bad, '; '.join(bad[:6]))

    bad = []
    for k in sorted(set(got) & set(want)):
        if not isinstance(got[k], dict) or 'red_days' not in got[k]:
            bad.append(f'{k}.red_days 缺失/非对象')
        elif got[k]['red_days'] != want[k]['red_days']:
            bad.append(f"{k}.red_days 文档={got[k]['red_days']} 代码={want[k]['red_days']}")
    check('T6b1-03[doc]', not bad, '; '.join(bad[:6]))


def test_t6b2(doc, label):
    """T6b-2：reference_only 与 exclusion_reason 的双向不变式（live + fixture 全量）。"""
    ind = doc['indicators']
    bad = [f"{k}: reference_only={v.get('reference_only')!r} "
           f"reason={v.get('exclusion_reason')!r}"
           for k, v in ind.items()
           if bool(v.get('reference_only')) != (v.get('exclusion_reason') == 'reference_only')]
    check(f'T6b2[{label}]', bool(ind) and not bad,
          f'{len(bad)} 处不一致: ' + '; '.join(bad[:6]))


def test_t6b3(doc, label, live):
    """T6b-3：账本闭合（定义数 / 产出数 / 失败项可追溯）。

    注意 invalid 与 len(failed) 不是一回事，禁止互相断言：
      invalid = data 里 value 为 null 的个数；failed = 本轮抓取失败个数；
      两者交叉但不重合（oilPrice 有值兜底却在 failed；epu 无值且在 failed/不在 indicators）。
    另：`total == valid + invalid` 与 S3-01 有意重叠，不计入新增覆盖，仅作本断言的自洽前提。
    """
    data, ind, v = doc['data'], doc['indicators'], doc['validity_report']
    bad = []
    if live:
        # live：定义集即生产口径，不该有多余键 —— 严格 total == len(im.INDICATORS)
        if v.get('total') != len(im.INDICATORS):
            bad.append(f"total={v.get('total')} 期望 {len(im.INDICATORS)}(len(IM.INDICATORS))")
    else:
        # fixture：数数会与 S3-01 同义重复，改验「定义集一个都不能少」
        # 夹具只允许一个合成样本 newIndicatorSample 作为额外键
        missing = set(im.INDICATORS) - set(data)
        extra = set(data) - set(im.INDICATORS)
        if missing:
            bad.append(f'data 缺定义键: {sorted(missing)}')
        if extra - {'newIndicatorSample'}:
            bad.append(f'data 多余键（仅允许 newIndicatorSample）: {sorted(extra)}')
    if v.get('valid') != len(ind):
        bad.append(f"valid={v.get('valid')} 期望 {len(ind)}(len(indicators))")
    if v.get('total') != v.get('valid', -1) + v.get('invalid', -1):
        bad.append(f"total={v.get('total')} != valid+invalid")
    check(f'T6b3-01[{label}]', not bad, '; '.join(bad))

    failed = v.get('failed')
    bad = []
    if not isinstance(failed, list):
        bad.append(f'failed 非数组: {type(failed).__name__}')
    else:
        for f in failed:
            k = f.get('key')
            x = data.get(k) if isinstance(k, str) else None
            fe = x.get('fetchError') if isinstance(x, dict) else None
            if not isinstance(fe, dict):
                bad.append(f'{k}: data[{k!r}] 无 fetchError 对象')
            elif fe.get('reason') != f.get('reason'):
                bad.append(f"{k}: fetchError.reason={fe.get('reason')!r} "
                           f"!= failed.reason={f.get('reason')!r}")
    check(f'T6b3-02[{label}]', not bad, '; '.join(bad[:6]))


# ═══════════════════════════════════════════
# main
# ═══════════════════════════════════════════

def run_one(json_path, fixture_path=None, do_units=True):
    doc, text, sha = load_strict(json_path)
    live = not bool(doc.get('fixture', {}).get('notRealData'))
    label = 'live' if live else 'fixture'
    ref = ref_date_of(doc)
    def safe(cid, fn, *a, **kw):
        try:
            fn(*a, **kw)
        except Exception as e:  # 旧 schema 缺字段时给 FAIL，不让整套崩
            check(f'{cid}[crash]', False, f'{type(e).__name__}: {e}')

    safe('S1', test_s1, doc, label, ref, live)
    safe('S2', test_s2, doc, text, label, live)
    safe('S3', test_s3, doc, label)
    safe('S4', test_s4, doc, label)
    safe('S5', test_s5, doc, label)
    safe('S6', test_s6, doc, label, ref)
    safe('S7', test_s7, doc, text, label, live)
    safe('S6B', test_s6_boundaries)
    safe('T6b1', test_t6b1)
    safe('T6b2', test_t6b2, doc, label)
    safe('T6b3', test_t6b3, doc, label, live)
    if do_units:
        safe('S4U', test_units)
    if live:
        try:
            a_ind, a_meta = scoring.build_indicators_and_meta(doc['data'], doc['data'])
            b_ind, b_meta = scoring.build_indicators_and_meta(doc['data'], doc['data'])
            # trend 是「相对上一份快照」派生的（涨/跌/平），不是 data 块的函数：
            # 用同一份 data 当 prev 重建，trend 必然全 neutral（2026-11-09 16:40
            # 数据落地后 cpi/fearGreed/ppi/shanghaiCopper/naturalGas/lmeIndex/dr007 七例真红）。
            # 故 replay 契约显式排除 prev 派生字段；白名单之外必须逐字节一致。
            # 注意：不得为了让断言变绿去改 neutral 判定，也不得降级为 warn。
            drop = {'trend'}
            a_s = {k: {f: x for f, x in v.items() if f not in drop}
                   for k, v in a_ind.items()}
            j_s = {k: {f: x for f, x in v.items() if f not in drop}
                   for k, v in doc['indicators'].items()}
            diff = sorted(k for k in set(a_s) | set(j_s) if a_s.get(k) != j_s.get(k))
            meta_same = (json.dumps(a_meta, sort_keys=True, ensure_ascii=False)
                         == json.dumps(doc['meta'], sort_keys=True, ensure_ascii=False))
            check('R-07[replay]', not diff and meta_same,
                  f'白名单 {sorted(drop)} 外不一致的指标={diff[:8]}；meta 一致={meta_same}')
            check('R-08[idempotent]',
                  json.dumps((a_ind, a_meta), sort_keys=True, ensure_ascii=False)
                  == json.dumps((b_ind, b_meta), sort_keys=True, ensure_ascii=False),
                  '两次构建不一致')
        except Exception as e:
            check('R-07[replay]', False, f'{type(e).__name__}: {e}')
    if live and fixture_path and Path(fixture_path).exists():
        fix, _, _ = load_strict(fixture_path)
        test_s8(fix)
        safe('T6b2', test_t6b2, fix, 'fixture')
        safe('T6b3', test_t6b3, fix, 'fixture', False)
    return sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=str(WS / 'public' / 'data' / 'market-data.json'))
    ap.add_argument('--fixture', default=str(WS / 'tests' / 'fixtures' / 'market-data-edge-cases.json'))
    ap.add_argument('--json-out')
    ap.add_argument('--no-units', action='store_true')
    args = ap.parse_args()

    try:
        before = hashlib.sha256(Path(args.json).read_bytes()).hexdigest()
        run_one(args.json, args.fixture, do_units=not args.no_units)
        after = hashlib.sha256(Path(args.json).read_bytes()).hexdigest()
        check('S0[readonly]', before == after, f'{before} -> {after}')
    except Exception as e:
        print(f'❌ 输入/执行错误: {e}')
        traceback.print_exc()
        return 2

    for r in RESULTS:
        mark = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}[r['status']]
        print(f"{mark} {r['id']}" + (f" {r['detail']}" if r['status'] != 'PASS' else ''))
    npass = sum(1 for r in RESULTS if r['status'] == 'PASS')
    nwarn = sum(1 for r in RESULTS if r['status'] == 'WARN')
    nfail = sum(1 for r in RESULTS if r['status'] == 'FAIL')
    print(f'\n{ npass } passed / { nwarn } warn / { nfail } failed / { len(RESULTS) } total')

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {'summary': {'passed': npass, 'warn': nwarn, 'failed': nfail, 'total': len(RESULTS)},
             'results': RESULTS}, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if nfail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
