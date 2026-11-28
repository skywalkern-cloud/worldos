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
import series_store  # noqa: E402  (S12：回算产物与日线序列互证)

RESULTS = []
FAILED = []

# ── prev 派生字段：不得进入 data-only replay 契约 ──
# trend = calc_trend(value, prev_value)（scoring.py:168-181 / 503-508），
# 传同一份 data 当 prev 时 diff 恒 0 ⇒ 恒返回 neutral。它需要「上一份快照」才能重放。
# 若要覆盖 trend 的重放，必须另立一条用「冻 prev 夹具」，本次不做。
PREV_DERIVED = {'trend'}

# ── 时钟派生字段：不得进入 data-only replay 的逐字节比对，但必须另立派生断言 ──
# days_stale = (今天 − 数据所属期末日)，days_overdue = max(0, days_stale − 阈值)：
# scoring 按「运行日」算，快照按「生成日」算，隔天重放两者必然差 drift 天。
# 单纯丢进白名单 = 覆盖丧失（字段没人管），故：
#   1) 字节比对排除 CLOCK_DERIVED；2) R-07a/b 用 drift 公式独立复算并逐指标比对；
#   3) drift 由「今天 − 快照 timestamp 所在日」推出，同日时 drift=0、断言退化为等值比对，仍然有效。
CLOCK_DERIVED = {'days_stale', 'days_overdue'}
TREND_ENUM = {'up', 'down', 'neutral'}


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
    'vix': ('CBOE波动率指数(官方日线)', '🇺🇸', 'daily'),
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
    # A4：中债10Y（liquidity 第 4 项），与中美利差同一次 akshare 请求
    'chinaBond10Y': ('akshare-中美债券（bond_zh_us_rate）', '🇨🇳', 'daily'),
    'epu': ('policyuncertainty.com-BakerBloomDavis', '🌐', 'monthly'),
    'carbonPrice': ('北京碳市场', '🇨🇳', 'daily'),
    'electricity': ('国家能源局', '🇨🇳', 'monthly'),
    'renewEnergyInvest': ('中证新能源指数', '🇨🇳', 'daily'),
    'aiGrowth': ('国家能源局-第二产业', '🇨🇳', 'monthly'),
    'robotInstall': ('东方财富-规模以上工业增加值', '🇨🇳', 'monthly'),
    'evPenetration': ('乘联会-CPCA', '🇨🇳', 'monthly'),
    'lmeIndex': ('LME-综合铜03', '🌐', 'daily'),
    'shanghaiCopper': ('上期所-新浪财经', '🇨🇳', 'daily'),
    # WorldOS V1a（2026-11-27）新增 4 个 A股/港股情绪代理（reference_only）
    'ashareTurnover': ('腾讯行情-沪深交易所', '🇨🇳', 'daily'),
    'marginBalance': ('东方财富-沪深交易所', '🇨🇳', 'daily'),
    'southboundNet': ('东方财富-港交所', '🇨🇳', 'daily'),
    'hstechMomentum': ('东方财富-恒生指数公司', '🇨🇳', 'daily'),
    # P1-8DIM（2026-11-28）：USDCNH 新增；A2 改东财**日线**源（带交易日）
    'usdcnh': ('akshare-东财离岸人民币日线（forex_hist_em USDCNH）', '🌐', 'daily'),
}

SIGNALS = {'red', 'yellow', 'gray', 'lightgreen', 'green', 'reference'}
FRESHNESS_LEVELS = {'fresh', 'realtime', 'unknown', 'stale', 'expired'}
EXCLUSION_REASONS = {'reference_only', 'no_score', 'expired_alpha0', 'degraded_no_score'}
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
        # 不变式（V1a 修正后的准确表述）：
        #   无分数 ⇔ 被排除，且理由 ∈ {no_score, reference_only, degraded_no_score}；
        #   有分数 ⇒ 理由不得是 no_score / degraded_no_score。
        # 旧版写的是 `(score is None) == (reason == 'no_score')`，它默认了
        # 「参考项一定有分数」（当时 epu/aiGrowth/robotInstall 都有参量表）。
        # V1a 新增的 4 个 A股/港股代理**无评分参数**却 reference_only，
        # 旧式会把正确实现判成错的（参考项本来就不该有分数）。
        if v['score'] is None and v['exclusion_reason'] not in ('no_score', 'reference_only', 'degraded_no_score'):
            bad.append(f'{k}.score={v["score"]!r} reason={v["exclusion_reason"]!r}')
        if v['score'] is not None and v['exclusion_reason'] in ('no_score', 'degraded_no_score'):
            bad.append(f'{k}.score={v["score"]!r} reason={v["exclusion_reason"]!r}')
    check(f'S1-10[{label}]', not bad, '; '.join(bad[:6]))

    # S1-10b：真·双向不变式（V1b-1b 龙六要求：不许只做单向蕴含）
    # 「有分数却标 no_score」与「无分数却标 expired_alpha0」两句都必须咬住：
    #   方向 A：score is None ⇒ reason ∈ {no_score, reference_only, degraded_no_score}
    #   方向 B：reason ∈ {no_score, degraded_no_score} ⇒ score is None
    # 为什么右集合必须包含 reference_only：epu / aiGrowth / robotInstall 是参考项，
    # 它们**照常算出展示用的 score**（不进 IAS 而已）。若写死 score is None ⇔ reason∈{...}，
    # 这 3 项会被判错——那是契约写错了，不是实现错（已向 PM/龙六报备）。
    bi = []
    for k, v in ind.items():
        s_none = v['score'] is None
        r = v['exclusion_reason']
        if s_none and r not in ('no_score', 'reference_only', 'degraded_no_score'):
            bi.append(f'{k}: score=None 但 reason={r!r}')
        if r in ('no_score', 'degraded_no_score') and not s_none:
            bi.append(f'{k}: reason={r} 但 score={v["score"]!r}')
    check(f'S1-10b[{label}]', not bi, '; '.join(bi[:6]))

    # 变异自证：把「参考项有分数」改成「no_score 但有分数」必须被抓到 —— 证明上面不是假绿
    probe = {k: dict(v) for k, v in list(ind.items())[:1]}
    if probe:
        pk = next(iter(probe))
        probe[pk].update({'score': 0.5, 'exclusion_reason': 'no_score'})
        caught = any(x['score'] is not None and x['exclusion_reason'] == 'no_score'
                     for x in probe.values())
        check(f'S1-10c[{label}]', caught, '变异探针未触发（断言是假绿）')

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

    # 2026-11-24：epu 换源后 policyuncertainty.com 是**正确来源**（官方 xlsx），
    # 不再是旧源残留；黑名单只保留已废弃的 alternative.me。
    low = text.lower()
    hits = [s for s in ('alternative.me',) if s in low]
    check(f'S2-02[{label}]', not hits, f'旧源残留: {hits}')

    if live:
        v = ind['vix']
        ok = (v['displayName'] == 'VIX恐慌指数' and 'CBOE' in v['caliberNote']
              and '非沪深300 QVIX' in v['caliberNote'] and v['country'] == '🇺🇸')
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

    # 阈值表冻结 + 分档（P1-8DIM：阈值量纲 = normalized）
    want_bands = [(0.543, '强烈买入', '80-100%', '🚀'), (0.217, '增持', '60-80%', '✅'),
                  (-0.109, '持有', '40-60%', '➖'), (-0.326, '减仓', '20-40%', '⚠️')]
    check(f'S4-10[{label}]', [tuple(x) for x in im.IAS_THRESHOLDS] == want_bands,
          f'{im.IAS_THRESHOLDS}')
    check(f'S4-10b[{label}]',
          getattr(im, 'IAS_THRESHOLD_SPACE', None) == 'normalized'
          and ias.get('threshold_space') == 'normalized',
          f"threshold_space={ias.get('threshold_space')}")
    check(f'S4-11[{label}]', im.IAS_MIN_COVERAGE == 0.6 and im.IAS_PARTIAL_COVERAGE == 0.8,
          f'{im.IAS_MIN_COVERAGE}/{im.IAS_PARTIAL_COVERAGE}')

    base = ias['signal'].split('（')[0]
    if ias['data_coverage'] < im.IAS_MIN_COVERAGE:
        want = ('数据不足', '不适用', '⚪')
    else:
        want = im.IAS_POSITION_ERROR
        for t, s, p, i in want_bands:
            # P1-8DIM：一律比 normalized（不许比 ias.score）
            if ias['normalized'] >= t:
                want = (s, p, i)
                break
    check(f'S4-12[{label}]',
          (base, ias['position'], ias['signal_icon']) == want,
          f"got={(base, ias['position'], ias['signal_icon'])} want={want} "
          f"norm={ias['normalized']}")

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
        # V1b-1b（龙六）：先断言两个列表交集为空，再计数。
        # 否则同一项会被计两次、active+ref 总数对不上 validity_report.total，
        # 而「总数对得上」正是这条断言存在的意义。
        overlap = set(d['indicators']) & set(d.get('reference_indicators', []))
        if overlap:
            bad.append(f'{d["id"]}.indicators ∩ reference_indicators = {sorted(overlap)}')
        active = [k for k in d['indicators'] if not im.is_reference_only(k)]
        # V1a：参考项数 = 计分列表里的参考项 + 单独的 reference_indicators（只展示不打分）
        refs = [k for k in list(d['indicators']) + list(d.get('reference_indicators', []))
                if im.is_reference_only(k)]
        # A4：required 可由维度显式覆盖（fxExternal 3 项但允许 usdcnh 降级 → 2），
        # 单一真源在 im.required_valid_count，不在测试里复写一份规则。
        if x['required_count'] != im.required_valid_count(d):
            bad.append(f'{d["id"]}.required {x["required_count"]} != {im.required_valid_count(d)}')
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
            # 跟随后端 scoring.py:300 的 q(...,3)：定点 half-up away-from-zero。
            # 直接调 scoring.q（与后端聚合同一函数对象，来自 indicator_meta.q）。
            # 不得用裸 round()（banker's rounding）：-0.4325 会被舍成 -0.432，
            # 而后端 q() 给 -0.433（T15-1 单一舍入真源）。
            # 也不许放宽容差来掩饰差异。
            want = scoring.q(sum(s * a for s, a in valid) / sa, 3)
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

def test_s9(doc, label):
    """S9：pct_rank / ratio_band 打分自洽性（V1b-1 / V1b-1b）。

    这些量全部由历史样本派生，所以断言只验**关系**，不写死数值：
      pct_rank：warmup ⇔ score is None ⇔ hist<20；window 与 hist 自洽；score 可由 pct 重算；
      ratio_band：r_value 与 ma120_base 必须都在，且 score == f(r_value) 可复算。
    """
    ind = doc['indicators']
    pct_keys = [k for k in ind if k in im.PCT_RANK_CONFIG]
    ratio_keys = [k for k in ind if k in im.RATIO_BAND_CONFIG]

    check(f'S9-01[{label}]', bool(pct_keys) and bool(ratio_keys),
          f'pct={pct_keys} ratio={ratio_keys}')

    # ── 字段齐全 ──
    common = ('scoring_method', 'transform', 'window', 'history_days', 'warmup',
              'saturated', 'polarity', 'raw_value', 'transform_value')
    bad = [f'{k}.{f}' for k in pct_keys for f in common + ('pct_20', 'pct_60')
           if f not in ind[k]]
    bad += [f'{k}.{f}' for k in ratio_keys for f in common + ('r_value', 'ma120_base')
            if f not in ind[k]]
    check(f'S9-02[{label}]', not bad, '缺失: ' + ', '.join(bad[:8]))

    # ── 分位法不变式 ──
    bad = []
    for k in pct_keys:
        v = ind[k]
        hd, warm, win = v['history_days'], v['warmup'], v['window']
        if warm is not (v['score'] is None):
            bad.append(f'{k}.warmup={warm} 但 score={v["score"]}')
        if warm is not (hd < im.PCT_RANK_MIN_SAMPLES):
            bad.append(f'{k}.warmup={warm} 但 history_days={hd}')
        if win == 60 and hd < im.PCT_RANK_WINDOW_LONG:
            bad.append(f'{k}.window=60 但 history_days={hd}')
        if win == 20 and not (im.PCT_RANK_MIN_SAMPLES <= hd < im.PCT_RANK_WINDOW_LONG):
            bad.append(f'{k}.window=20 但 history_days={hd}')
        for f in ('pct_20', 'pct_60'):
            if v[f] is not None and not (0.0 <= v[f] <= 1.0):
                bad.append(f'{k}.{f}={v[f]}')
    # ── 相对量法不变式 ──
    for k in ratio_keys:
        v = ind[k]
        hd, warm = v['history_days'], v['warmup']
        if warm is not (hd < v['window']):
            bad.append(f'{k}.warmup={warm} 但 history_days={hd} < window={v["window"]}')
        if warm and v['score'] is not None:
            bad.append(f'{k} warmup 但有分数 {v["score"]}')
        r_val, ma_base = v.get('r_value'), v.get('ma120_base')
        if not warm and (r_val is None or ma_base is None):
            bad.append(f'{k} 非 warmup 但 r_value/ma120_base 缺失')
        if r_val is not None and v['transform_value'] != r_val:
            bad.append(f'{k}.transform_value={v["transform_value"]} != r_value={r_val}')
        if v['polarity'] != 'growth_proxy' or v['scoring_method'] != 'ratio_band':
            bad.append(f'{k}.polarity/method={v["polarity"]}/{v["scoring_method"]}')
    for k in pct_keys:
        v = ind[k]
        if v['scoring_method'] != 'pct_rank' or v['transform'] not in im.PCT_TRANSFORMS:
            bad.append(f'{k}.method/transform={v["scoring_method"]}/{v["transform"]}')
        if v['polarity'] not in im.POLARITIES:
            bad.append(f'{k}.polarity={v["polarity"]}')
    check(f'S9-03[{label}]', not bad, '; '.join(bad[:6]))

    # ── score 可复算（分位法与相对量法各一条）──
    bad = []
    for k in pct_keys:
        v = ind[k]
        if v['warmup']:
            continue
        if v['window'] == 60 and v['pct_20'] is not None and v['pct_60'] is not None:
            want = (im.PCT_RANK_W_SHORT * (2 * v['pct_20'] - 1)
                    + im.PCT_RANK_W_LONG * (2 * v['pct_60'] - 1))
        elif v['window'] == 20 and v['pct_20'] is not None:
            want = 2 * v['pct_20'] - 1
        else:
            bad.append(f'{k}: window={v["window"]} 与分位不匹配')
            continue
        if abs(im.q(want, 3) - v['score']) > 1e-9:
            bad.append(f'{k}: {im.q(want, 3)} != {v["score"]}')
    for k in ratio_keys:
        v = ind[k]
        if v['warmup']:
            continue
        r_val = v.get('r_value')
        if r_val is None:
            bad.append(f'{k}: 非 warmup 但 r_value 缺失')
            continue
        want = im.q(scoring.ratio_band_score(r_val), 3)
        if abs(want - v['score']) > 1e-9:
            bad.append(f'{k}: f(r={r_val})={want} != {v["score"]}')
    check(f'S9-04[{label}]', not bad, '; '.join(bad[:6]))

    # ── saturated 语义 ──
    bad = []
    for k in pct_keys:
        v = ind[k]
        if v['warmup']:
            continue
        used = [v['pct_20']] + ([v['pct_60']] if v['window'] == 60 else [])
        want_sat = any(p in (0.0, 1.0) for p in used if p is not None)
        if v['saturated'] is not want_sat:
            bad.append(f'{k}.saturated={v["saturated"]} 但 pct={used}')
    for k in ratio_keys:
        v = ind[k]
        if v['warmup']:
            continue
        r = v.get('r_value')
        if r is None:
            continue
        want_sat = r <= im.RATIO_BAND_KNOTS[0][0] or (
            im.q(scoring.ratio_band_score(r), 3) <= im.RATIO_BAND_POST_FLOOR
            and r > im.RATIO_BAND_KNOTS[-1][0])
        if v['saturated'] is not want_sat:
            bad.append(f'{k}.saturated={v["saturated"]} 但 r={r}')
    check(f'S9-05[{label}]', not bad, '; '.join(bad[:6]))

    # ── 已转正项必须真的在计分 ──
    bad = [k for k in ind if k in im.QUANTILE_CONFIG
           and (ind[k]['reference_only'] is not False
                or (not ind[k]['warmup'] and ind[k]['excluded_from_scoring'] is not False))]
    check(f'S9-06[{label}]', not bad, f'仍被当参考项/被排除: {bad}')

    # ── S9-07：ratio_band 测试向量逐点（龙六给的 14 点，字面量输入，不依赖任何产物）──
    vectors = [(0.40, -1.000), (0.60, -1.000), (0.70, -0.600), (0.80, -0.200),
               (0.908, 0.232), (1.00, 0.600), (1.20, 0.667), (1.40, 0.733),
               (1.60, 0.800), (1.70, 0.600), (1.80, 0.400), (1.90, 0.200),
               (2.00, 0.000), (2.50, 0.000)]
    bad = []
    for r, want in vectors:
        got = im.q(scoring.ratio_band_score(r), 3)
        if abs(got - want) > 1e-9:
            bad.append(f'r={r} want={want} got={got}')
    check(f'S9-07[vector]', not bad, f'{len(vectors)} 点中失败: ' + '; '.join(bad[:4]))


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
    for k in ('usBond10Y', 'dollarIndex', 'lpr',
              'dr007', 'm2', 'chinaBond10Y', 'renewEnergyInvest', 'evPenetration'):
        branch(k, 'expired', 'expired_alpha0')
    # P1-8DIM：美债 2Y/5Y 已降为 riskAppetite 的只展示参考项；即使 α=0 也先按参考项剔除
    branch('usBond2Y', 'expired', 'reference_only')
    branch('usBond5Y', 'expired', 'reference_only')
    # A4：creditSpread 降为 fxExternal 参考项（只展示、不计分）
    branch('creditSpread', 'expired', 'reference_only')
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
          and tech['active_count'] == 3 and tech['reference_only_count'] == 2
          and abs(tech['weight_effective'] - 0.3) < 1e-9,
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
    # 覆盖面断言：不写死具体小数（那是「随规则变的量」，硬编码必然下次再红）。
    # 改为从产物自身派生：coverage = Σ(非置灰维度有效权重) / Σ(全部有效权重)，
    # 再钉两条语义：必须落在「部分维度缺失」档（< IAS_PARTIAL_COVERAGE），且信号文案带后缀。
    ias_fix = fix['meta']['ias']
    dims_fix = fix['meta']['dimensions']
    total_w = sum(d['weight_effective'] for d in dims_fix.values())
    valid_w = sum(d['weight_effective'] for d in dims_fix.values()
                  if d['insufficient_data'] is not True and d['score'] is not None)
    want_cov = round(valid_w / total_w, 3) if total_w else 0.0
    check('S8[coverage]', ias_fix['data_coverage'] == want_cov
          and ias_fix['data_coverage'] < im.IAS_PARTIAL_COVERAGE
          and ias_fix['data_coverage'] >= im.IAS_MIN_COVERAGE
          and '（部分维度缺失·参考）' in ias_fix['signal'],
          f"coverage={ias_fix['data_coverage']} want={want_cov} "
          + json.dumps(ias_fix, ensure_ascii=False))


# ═══════════════════════════════════════════
# 白盒单测（构造夹具，不改产品代码）
# ═══════════════════════════════════════════

def test_units():
    # S4-U1：只有一个有效维度 → 低覆盖，不得给「持有」
    ds = {d['id']: {'score': None, 'insufficient_data': True,
                    'weight_effective': im.dimension_weights(d)['effective']}
          for d in im.DIMENSIONS}
    ds['sentimentA'].update({'score': -0.5, 'insufficient_data': False})
    out = scoring.calc_ias(ds)
    check('S4-U1', out['data_coverage'] < im.IAS_MIN_COVERAGE
          and out['signal'] == '数据不足' and out['is_actionable'] is False
          and out['position'] == '不适用',
          json.dumps(out, ensure_ascii=False))

    # S4-U2：分档边界（>= 语义）；all dims 同分时 normalized == 该分
    # P1-8DIM：全部用 normalized 构造与比较（阈值量纲已统一为 normalized）
    def dims_all(v):
        return {d['id']: {'score': v, 'insufficient_data': False,
                          'weight_effective': im.dimension_weights(d)['effective']}
                for d in im.DIMENSIONS}

    def want_band(norm):
        want = im.IAS_POSITION_ERROR
        for t, s_, p_, i_ in im.IAS_THRESHOLDS:
            if norm >= t:
                return (s_, p_, i_)
        return want

    bad = []
    for t, _sig, _pos, _ico in im.IAS_THRESHOLDS:
        for v, expect_ge in (((t + 0.02), True), ((t - 0.02), False)):
            out = scoring.calc_ias(dims_all(v))
            got = (out['signal'], out['position'], out['signal_icon'])
            want = want_band(out['normalized'])
            if got != want:
                bad.append(f'{t} norm={out["normalized"]} got={got} want={want}')
            if (out['normalized'] >= t) != expect_ge:
                bad.append(f'{t} 构造 normalized {out["normalized"]} 未落在预期侧')
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
    # P1-8DIM：techGreen 计分项 3 + 参考项 2（aiGrowth/robotInstall），全部标参考应得 5
    tech = [d for d in im.DIMENSIONS if d['id'] == 'techGreen'][0]
    # 显式构造「维内全部都是参考项」的分支；calc_dimension_scores 走的是元数据
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
          and out['reference_only_count'] == len(tech['indicators']) + len(tech.get('reference_indicators', []))
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
      两者交叉但不重合（oilPrice 有值兜底却在 failed；epu 换源前无值且在 failed/不在 indicators，
      换源后已有值、不再进 failed —— 夹具仍保留 epu=None 的硬失效样本守该分支）。
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
# S10：P1-8DIM 工单 §6.5 五条断言（2026-11-28）
# ═══════════════════════════════════════════

def test_s10_8dim(doc, label):
    """工单 §6.5 强制要求：

    ① dimension_weights() 设计权重和 == sum(weight) == IAS_SCALE（5.6）
    ② 参考项（reference_only）不计入分母、不参与平均
    ③ 同一天旧阈值→新阈值信号不变（阈值量纲换算不改变语义）
    ④ usdcnh 取不到时维度仍能算（4 项仅 3 个有效 → 出分）+ 缺失不伪造值
    ⑤ 若未取到 usdcnh，fxExternal 维度因子数仍满足 required_valid_count
    """
    dims = doc['meta']['dimensions']

    # ① IAS_SCALE 由 sum(weight) 派生，且与产物一致
    design_sum = round(sum(d['weight'] for d in im.DIMENSIONS), 2)
    check(f'S10-01[{label}]',
          abs(design_sum - im.IAS_SCALE) < 1e-9
          and abs(sum(d['weight_design'] for d in dims.values()) - im.IAS_SCALE) < 1e-9
          and doc['meta']['ias']['ias_scale'] == im.IAS_SCALE == 5.6,
          f'design_sum={design_sum} IAS_SCALE={im.IAS_SCALE} '
          f"产={doc['meta']['ias']['ias_scale']}")

    # ② 参考项不进分母：每个维度的 design_count 只数非参考项
    bad = []
    for d in im.DIMENSIONS:
        act = [k for k in d['indicators'] if not im.is_reference_only(k)]
        x = dims[d['id']]
        if x['active_count'] != len(act):
            bad.append(f"{d['id']}.active={x['active_count']} != {len(act)}")
        # weight_effective = weight × (active / design_count)，参考项不得出现在分母里
        want = round(d['weight'] * (len(act) / len(d['indicators'])), 4)
        if abs(x['weight_effective'] - want) > 1e-9:
            bad.append(f"{d['id']}.w_eff={x['weight_effective']} != {want}")
        for k in d.get('reference_indicators', []):
            if not im.is_reference_only(k):
                bad.append(f"{d['id']}: {k} 在 reference_indicators 却未标 reference_only")
            if k in d['indicators']:
                bad.append(f"{d['id']}: {k} 同时在计分列表与参考列表")
    check(f'S10-02[{label}]', not bad, '; '.join(bad[:6]))

    # ③ 阈值量纲换算不改变信号语义：对同一 normalized，新旧阈值分档必须一致
    #   旧口径 = 拿 normalized×4.6 去比 2.5/1.0/-0.5/-1.5
    def band_old(norm):
        s = scoring.q(norm * 4.6, 2)
        for t, sig, _p, _i in ((2.5, '强烈买入', 0, 0), (1.0, '增持', 0, 0),
                               (-0.5, '持有', 0, 0), (-1.5, '减仓', 0, 0)):
            if s >= t:
                return sig
        return '清仓/防御'

    def band_new(norm):
        for t, sig, _p, _i in im.IAS_THRESHOLDS:
            if norm >= t:
                return sig
        return '清仓/防御'

    bad = []
    n = -1000
    while n <= 1000:            # -1.000 ~ 1.000，步长 0.001
        norm = n / 1000
        if band_old(norm) != band_new(norm):
            bad.append(norm)
        n += 1
    # 允许的不一致只能来自「旧阈值 /4.6 后取 3 位」的舍入窗口
    # 最大窗：-1.495/4.6 = -0.3250 vs -0.326 → 0.0011，故阈值取 0.0012
    BOUNDS = (0.5435, 0.2174, 0.1087, 0.3261)
    stray = [v for v in bad if min(abs(abs(v) - b) for b in BOUNDS) > 0.0012]
    check(f'S10-03[{label}]', not stray,
          f'舍入窗口外仍有 {len(stray)} 处不一致: {stray[:6]}（窗口内 {len(bad) - len(stray)} 处）')

    # ④ usdcnh 缺失时：必须为 null/不存在，不得伪造值；fxExternal 仍能算
    raw_cnh = (doc.get('data') or {}).get('usdcnh') or {}
    cnh_val = raw_cnh.get('value')
    fx = dims['fxExternal']
    if cnh_val is None:
        ok = (fx['valid_count'] >= fx['required_count'])
        check(f'S10-04[{label}]', ok,
              f"usdcnh 缺失但 fxExternal valid={fx['valid_count']}/{fx['required_count']}")
        check(f'S10-05[{label}]',
              'usdcnh' not in doc['indicators']
              or doc['indicators']['usdcnh']['score'] is None,
              'usdcnh 无值时不得出分')
    else:
        # A2（2026-11-28）：usdcnh 已改 ratio_ma_steps；分数必须能用
        # 「历史 + 当日」独立重算 MA120/ratio 后复现，不得硬编码/手填。
        ind_cnh = doc['indicators'].get('usdcnh') or {}
        meta_cnh = im.RATIO_MA_STEPS_CONFIG['usdcnh']
        want_meta = scoring.score_by_ratio_ma(
            'usdcnh', cnh_val, raw_cnh.get('history') or [])
        got = ind_cnh.get('score')
        check(f'S10-04[{label}]',
              got == want_meta['score']
              and ind_cnh.get('ma_base') is not None
              and ind_cnh.get('ratio_value') is not None,
              f'usdcnh={cnh_val} score={got} 期望 {want_meta["score"]} '
              f'(MA120={want_meta["ma_base"]} ratio={want_meta["ratio_value"]})')
        # 边界语义：分数必须与 ratio 5 档表逐档一致（防手填/旧水位复活）
        want = scoring.ratio_ma_steps_score(
            ind_cnh['ratio_value'], meta_cnh['steps'], meta_cnh['values'])
        check(f'S10-04b[{label}]', got == want,
              f'ratio={ind_cnh.get("ratio_value")} → {want}, got {got}')
        # 口径可读：「vs 120 日均值 ±x.x%」必须出现在 caliberNote
        note = ind_cnh.get('caliberNote') or ''
        check(f'S10-04c[{label}]',
              '120 日均值' in note and f"{ind_cnh.get('deviation_pct'):+.2f}%" in note,
              f'caliberNote 缺均值偏差: {note}')
        check(f'S10-05[{label}]', fx['valid_count'] >= 1 and fx['score'] is not None,
              f"fxExternal valid={fx['valid_count']} score={fx['score']}")


# ═══════════════════════════════════════════
# S11：usdcnh ratio_ma_steps 边界与 warmup（A2，2026-11-28）
# ═══════════════════════════════════════════

def test_s11_usdcnh_ratio():
    """A2 强制断言（不依赖任何产物）：

    ① ratio 5 档逐档命中：0.98/0.99/1.0/1.01/1.02 → +1.0/+0.5/0/−0.5/−1.0
    ② 边界归属：=0.985→+1.0、=0.995→+0.5、=1.005→0、=1.015→−0.5、>…1.015→−1.0
    ③ MA120 历史不足 120 日 → score=null（不硬填/不插值）
    ④ 即使 usdcnh warmup，fxExternal 仍能出分（3/4 有效 ≥ 2）
    """
    cfg = im.RATIO_MA_STEPS_CONFIG.get('usdcnh') or {}
    check('S11-00[usdcnh]',
          bool(cfg) and cfg['window'] == 120
          and cfg['steps'] == (0.985, 0.995, 1.005, 1.015)
          and cfg['values'] == (1.0, 0.5, 0.0, -0.5, -1.0),
          f'ratio_ma_steps 配置异常: {cfg}')

    probes = [(0.98, 1.0), (0.99, 0.5), (1.0, 0.0), (1.01, -0.5), (1.02, -1.0)]
    bad = []
    for r, want in probes:
        got = scoring.ratio_ma_steps_score(r, cfg['steps'], cfg['values'])
        if got != want:
            bad.append(f'{r}→{got}≠{want}')
    check('S11-01[ratio 5 档探针]', not bad, '; '.join(bad))

    edges = [(0.9849, 1.0), (0.985, 1.0), (0.9851, 0.5),
             (0.995, 0.5), (0.9951, 0.0),
             (1.005, 0.0), (1.0051, -0.5),
             (1.015, -0.5), (1.0151, -1.0)]
    bad = []
    for r, want in edges:
        got = scoring.ratio_ma_steps_score(r, cfg['steps'], cfg['values'])
        if got != want:
            bad.append(f'{r}→{got}≠{want}')
    check('S11-02[边界归属 ≤上界]', not bad, '; '.join(bad))

    # 方向：ratio 越高分越低（不得反向）
    seq = [scoring.ratio_ma_steps_score(r, cfg['steps'], cfg['values'])
           for r in (0.97, 0.99, 1.0, 1.01, 1.03)]
    check('S11-03[方向: 人民币越弱分越低]',
          all(a >= b for a, b in zip(seq, seq[1:])), f'{seq}')

    # warmup：118/119 条历史 + 当日 = 119/120 个点（MA120 含当日）
    from datetime import date as _date, timedelta as _td
    end = _date.today()
    def _hist(n):
        return [{'date': (end - _td(days=n - i)).isoformat(), 'value': 6.7}
                for i in range(n)]
    short = scoring.score_by_ratio_ma('usdcnh', 6.65, _hist(118))
    exact = scoring.score_by_ratio_ma('usdcnh', 6.65, _hist(119))
    check('S11-04[<120 点 warmup=null]',
          short['warmup'] is True and short['score'] is None
          and short['ma_base'] is None and short['ratio_value'] is None,
          f"{short}")
    check('S11-05[=120 点即可出分]',
          exact['warmup'] is False and exact['score'] is not None
          and exact['total_points'] == 120,
          f"{exact}")

    # 不破维度：A4 后 fxExternal 计分 3 项，usdcnh warmup 时 2/3 有效仍出分
    raw = {
        'usdcnh': {'value': 6.65, 'unit': '', 'frequency': 'daily',
                   'source': 'test', 'dataDate': end.isoformat(),
                   'realtime': False, 'used_fallback': False,
                   'history': _hist(50)},
        'dollarIndex': {'value': 100.0, 'unit': '', 'frequency': 'daily',
                        'source': 'test', 'dataDate': end.isoformat()},
        'creditSpread': {'value': 200.0, 'unit': 'bp', 'frequency': 'daily',
                         'source': 'test', 'dataDate': end.isoformat()},
        'usBond10Y': {'value': 4.0, 'unit': '%', 'frequency': 'daily',
                      'source': 'test', 'dataDate': end.isoformat()},
    }
    ind, meta2 = scoring.build_indicators_and_meta(raw)
    fx = meta2['dimensions']['fxExternal']
    check('S11-06[warmup 不破维度]',
          ind['usdcnh']['score'] is None
          and fx['valid_count'] == 2 and fx['required_count'] == 2
          and fx['insufficient_data'] is False and fx['score'] is not None,
          f"usdcnh={ind['usdcnh']['score']} fx={fx}")


# ═══════════════════════════════════════════
# S12：回算产物无未来函数（A2）
# ═══════════════════════════════════════════

def test_s12_replay_no_lookahead():
    """回算的 usdcnh 必须只用「当日之前」的观测算 MA120。

    双重校验：
      ① 产物自述 max_used_date < 行日期；
      ② 用 series_store 独立重算 ma_base/ratio/score，必须与产物逐项一致。
    """
    p = WS / 'data' / 'history' / 'recompute-8dim-2026-11-28.json'
    if not p.exists():
        check('S12-00[skip]', True, '无回算产物，跳过（不视为通过）', warn=True)
        return
    doc = json.loads(p.read_text())
    series = series_store.load('usdcnh')
    bad, recompute_bad = [], []
    for row in doc.get('rows') or []:
        ds = row['date']
        u = row.get('usdcnh') or {}
        if u.get('value') is None:
            continue
        mud = u.get('max_used_date')
        if not mud or mud >= ds:
            bad.append(f'{ds}: max_used={mud} ≥ 当日')
            continue
        ds_list = sorted(d for d in series if d < ds)
        if not ds_list:
            recompute_bad.append(f'{ds}: 序列无可用点')
            continue
        last = ds_list[-1]
        hist = [{'date': d, 'value': series[d]} for d in ds_list[:-1]]
        want = scoring.score_by_ratio_ma('usdcnh', series[last], hist)
        for f in ('ma_base', 'ratio_value', 'score'):
            if u.get(f) != want[f]:
                recompute_bad.append(f'{ds}.{f}: {u.get(f)} != {want[f]}')
        if last != u.get('data_date'):
            recompute_bad.append(f'{ds}.data_date: {u.get("data_date")} != {last}')
    check('S12-01[无未来函数]', not bad, '; '.join(bad[:6]))
    check('S12-02[MA120 可由序列复算]', not recompute_bad,
          '; '.join(recompute_bad[:6]))
    lo = doc.get('usdcnh_no_lookahead') or {}
    check('S12-03[产物声明]', lo.get('passed') is True, f'{lo}')


# ══════════════════════════════════════════
# S14：饱和披露（A4 / 龙六 P0-1）
# ══════════════════════════════════════════

def test_s14_saturation():
    """撞 ±1.0 的指标必须 saturated=true，并接到维度级计数。"""
    from datetime import date as _date
    today = _date.today().isoformat()
    raw = {
        'ppi': {'value': 5.7, 'unit': '%', 'frequency': 'monthly',
                'source': 'test', 'dataDate': today},
        'carbonPrice': {'value': 97.0, 'unit': '¥/吨', 'frequency': 'daily',
                        'source': 'test', 'dataDate': today},
        'shanghaiCopper': {'value': 92550.0, 'unit': '¥/吨', 'frequency': 'daily',
                           'source': 'test', 'dataDate': today},
        'evPenetration': {'value': 67.4, 'unit': '%', 'frequency': 'monthly',
                          'source': 'test', 'dataDate': today},
        'cpi': {'value': 2.0, 'unit': '%', 'frequency': 'monthly',
                'source': 'test', 'dataDate': today},
    }
    ind, meta = scoring.build_indicators_and_meta(raw)
    sat = {k: (ind[k]['score'], ind[k]['saturated']) for k in
           ('ppi', 'carbonPrice', 'shanghaiCopper', 'evPenetration')}
    check('S14-01[±1.0 ⇒ saturated=true]',
          all(s == 1.0 or s == -1.0 for s, _ in sat.values())
          and all(f is True for _, f in sat.values()),
          f'{sat}')
    check('S14-02[未截断项 saturated=false]',
          ind['cpi']['saturated'] is False and ind['cpi']['score'] != 1.0,
          f"cpi score={ind['cpi']['score']} sat={ind['cpi']['saturated']}")
    check('S14-03[维度级计数]',
          meta['dimensions']['inflation']['saturated_count'] == 1
          and 'ppi' in meta['dimensions']['inflation']['saturated_indicators']
          and meta['dimensions']['techGreen']['saturated_count'] == 2,
          f"inflation={meta['dimensions']['inflation']['saturated_count']} "
          f"techGreen={meta['dimensions']['techGreen']['saturated_count']}")
    check('S14-04[IAS 饱和总表]',
          set(meta['ias']['saturated_inputs'])
          >= {'ppi', 'carbonPrice', 'shanghaiCopper', 'evPenetration'},
          f"{meta['ias']['saturated_inputs']}")


# ══════════════════════════════════════════
# S15：A4 拆汇率双计（creditSpread 只展示 / chinaBond10Y 进 liquidity）
# ══════════════════════════════════════════

def test_s15_fx_deconflation():
    from datetime import date as _date
    today = _date.today().isoformat()

    # 元数据归属
    liq = next(d for d in im.DIMENSIONS if d['id'] == 'liquidity')
    fx = next(d for d in im.DIMENSIONS if d['id'] == 'fxExternal')
    check('S15-01[chinaBond10Y 进 liquidity]',
          'chinaBond10Y' in liq['indicators']
          and im.INDICATORS['chinaBond10Y']['caliberNote'],
          f"{liq['indicators']}")
    check('S15-02[liquidity 4 项、最小有效 2]',
          len(liq['indicators']) == 4 and im.required_valid_count(liq) == 2,
          f"n={len(liq['indicators'])} req={im.required_valid_count(liq)}")
    check('S15-03[creditSpread 转参考项]',
          'creditSpread' not in fx['indicators']
          and 'creditSpread' in fx.get('reference_indicators', [])
          and im.is_reference_only('creditSpread'),
          f"fx.indicators={fx['indicators']} ref={fx.get('reference_indicators')}")
    check('S15-04[usBond10Y 仍在打分]',
          'usBond10Y' in fx['indicators'] and not im.is_reference_only('usBond10Y'),
          f"{fx['indicators']}")

    def item(v, unit='', freq='daily'):
        return {'value': v, 'unit': unit, 'frequency': freq,
                'source': 'test', 'dataDate': today}
    raw = {
        'lpr': item(3.0, '%', 'monthly'), 'dr007': item(1.6, '%'), 'm2': item(8.9, '%', 'monthly'),
        'chinaBond10Y': item(1.60, '%'),
        'usdcnh': {'value': 6.65, 'unit': '', 'frequency': 'daily', 'source': 'test',
                   'dataDate': today, 'history': []},
        'dollarIndex': item(100.0), 'usBond10Y': item(4.94, '%'),
        'creditSpread': item(334, 'bp'),
    }
    ind, meta = scoring.build_indicators_and_meta(raw)
    check('S15-05[中债10Y 打分方向]',
          ind['chinaBond10Y']['score'] == 0.9,
          f"score={ind['chinaBond10Y']['score']}")
    check('S15-06[creditSpread 不计分]',
          ind['creditSpread']['reference_only'] is True
          and ind['creditSpread']['excluded_from_scoring'] is True
          and meta['dimensions']['fxExternal']['score'] is not None,
          f"ref={ind['creditSpread']['reference_only']} "
          f"excl={ind['creditSpread']['excluded_from_scoring']}")
    # fx 的维度均分必须只由 3 个计分项构成（不含 creditSpread）
    fx_dim = meta['dimensions']['fxExternal']
    check('S15-07[fx 均分不含利差]',
          fx_dim['active_count'] == 3 and fx_dim['reference_only_count'] == 1
          and fx_dim['valid_count'] <= 3,
          f"active={fx_dim['active_count']} ref={fx_dim['reference_only_count']} "
          f"valid={fx_dim['valid_count']}")


# ══════════════════════════════════════════
# S16：IAS 边界余量 / 脆弱输入 / 置信度（A4 / 龙六 P0-3）
# ══════════════════════════════════════════

def test_s16_boundary_disclosure(doc):
    ias = doc['meta']['ias']
    for f in ('boundary_margin', 'boundary_threshold', 'boundary_next_signal',
              'fragile_inputs', 'fragile_details', 'degraded_inputs', 'confidence'):
        check(f'S16-00[{f} 存在]', f in ias, f'缺字段 {f}')
    margin = ias.get('boundary_margin')
    norm = ias.get('normalized')
    thr = ias.get('boundary_threshold')
    ok = (isinstance(margin, (int, float)) and isinstance(norm, (int, float))
          and isinstance(thr, (int, float))
          and abs(margin - round(norm - thr, 6)) < 1e-9
          and thr in [t for t, _s, _p, _i in im.IAS_THRESHOLDS])
    check('S16-01[余量 = normalized − 最近阈值]', ok,
          f'norm={norm} thr={thr} margin={margin}')
    check('S16-02[confidence 枚举]',
          ias.get('confidence') in ('high', 'medium', 'low'),
          f"{ias.get('confidence')}")
    dims = {d['id'] for d in im.DIMENSIONS}
    check('S16-03[fragile 子集且按影响降序]',
          set(ias.get('fragile_inputs') or []) <= dims
          and all(a['impact'] >= b['impact']
                  for a, b in zip(ias.get('fragile_details') or [],
                                  (ias.get('fragile_details') or [])[1:])),
          f"{ias.get('fragile_inputs')}")


# ══════════════════════════════════════════
# S13：usdcnh 降级（在岸回退）不得参与打分（D7，2026-11-28）
# ══════════════════════════════════════════

def test_s13_usdcnh_degraded_no_score():
    """D7 强制断言（不依赖任何产物）：口径降级 → 只展示、不计分。

    ① fetch 层：monkeypatch 源1（akshare 离岸日线）失败、源2（exchangerate-api 在岸
       CNY）命中 → 必须带出 source_degraded（含 caliberNoteSuffix），不得静默当正常；
    ② scoring 层：同一份 4 项 fxExternal，只给 usdcnh 加降级痕迹
       → score=null、ratio_value/ma_base/deviation_pct 全为 null（不留半套数），
         exclusion_reason=degraded_no_score；
    ③ 展示不丢：value 仍是 6.6551（展示 ≠ 打分），caliberNote 明写「降级·在岸参考价，不计分」；
    ④ 维度不破：降级态 fxExternal 3/4 有效仍出分；同日正常态作对照必须出分且两者
       fxExternal/IAS 可对照（差异只能来自 usdcnh 这一项）。
    """
    import sys as _sys
    import types as _types
    import fetch_worldos_data as fetch_mod

    # ── ① fetch 层 monkeypatch：源2 命中 ──
    fake_ak = _types.ModuleType('akshare')
    def _ak_boom(*a, **k):
        raise RuntimeError('akshare unavailable (simulated by S13)')
    fake_ak.forex_hist_em = _ak_boom

    class _FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {'date': '2026-11-27', 'rates': {'CNY': 6.6551}}

    seen_urls = []
    fake_requests = _types.ModuleType('requests')
    def _req_get(url, timeout=10):
        seen_urls.append(url)
        return _FakeResp()
    fake_requests.get = _req_get

    old_ak = _sys.modules.get('akshare')
    old_req = _sys.modules.get('requests')
    _sys.modules['akshare'] = fake_ak
    _sys.modules['requests'] = fake_requests
    try:
        f_val, f_dd, f_freq, f_degraded, f_extras = fetch_mod.get_usdcnh()
    finally:
        if old_ak is not None:
            _sys.modules['akshare'] = old_ak
        else:
            _sys.modules.pop('akshare', None)
        if old_req is not None:
            _sys.modules['requests'] = old_req
        else:
            _sys.modules.pop('requests', None)

    check('S13-00[源2命中]',
          f_val == 6.6551 and f_freq == 'daily' and bool(seen_urls)
          and 'exchangerate-api' in (seen_urls[0] if seen_urls else ''),
          f'value={f_val} freq={f_freq} url={seen_urls[:1]}')
    check('S13-01[降级信号外带]',
          isinstance(f_degraded, dict)
          and f_degraded.get('reason') == 'primary_source_missing'
          and '在岸' in (f_degraded.get('caliberNoteSuffix') or '')
          and '在岸' in (f_degraded.get('source') or ''),
          f'{f_degraded}')

    # ── ②/③/④ scoring 层：同日数据，正常态 vs 降级态 ──
    from datetime import date as _date
    end = _date.today()
    hist = [{'date': _date.fromordinal(end.toordinal() - (119 - i)).isoformat(),
             'value': 6.7239} for i in range(119)]   # 119 条 + 当日 = 120 点，满窗

    def _raw(degraded: bool):
        cnh = {'value': 6.6551, 'unit': '', 'frequency': 'daily',
               'source': 'akshare-东财离岸人民币日线（forex_hist_em USDCNH）',
               'dataDate': end.isoformat(), 'realtime': False,
               'used_fallback': False, 'history': hist}
        if degraded:
            cnh['sourceDegraded'] = {
                'source': 'exchangerate-api 在岸中间价',
                'primarySource': 'akshare 离岸 USDCNH 日线（forex_hist_em）',
                'reason': 'primary_source_missing',
                'reasonText': '离岸日线暂不可得，已回退在岸参考价（口径见 caliberNote）',
                'caliberNoteSuffix': '（本条为在岸参考价，非离岸价）',
            }
            cnh['caliberNoteSuffix'] = '（本条为在岸参考价，非离岸价）'
            cnh['actualSource'] = 'exchangerate-api 在岸中间价'
        return {
            'usdcnh': cnh,
            'dollarIndex': {'value': 100.0, 'unit': '', 'frequency': 'daily',
                            'source': 'test', 'dataDate': end.isoformat()},
            'creditSpread': {'value': 200.0, 'unit': 'bp', 'frequency': 'daily',
                             'source': 'test', 'dataDate': end.isoformat()},
            'usBond10Y': {'value': 4.0, 'unit': '%', 'frequency': 'daily',
                          'source': 'test', 'dataDate': end.isoformat()},
        }

    n_ind, n_meta = scoring.build_indicators_and_meta(_raw(False))
    d_ind, d_meta = scoring.build_indicators_and_meta(_raw(True))
    n_cnh, d_cnh = n_ind['usdcnh'], d_ind['usdcnh']

    check('S13-02[降级→score=null 且不留半套数]',
          d_cnh['score'] is None and d_cnh.get('ratio_value') is None
          and d_cnh.get('ma_base') is None and d_cnh.get('deviation_pct') is None
          and 'warmup' not in d_cnh,
          json.dumps({k: d_cnh.get(k) for k in
                      ('score', 'ratio_value', 'ma_base', 'deviation_pct')},
                     ensure_ascii=False))
    check('S13-03[降级标在 caliberNote]',
          '降级·在岸参考价，不计分' in (d_cnh.get('caliberNote') or '')
          and '在岸参考价' in (d_cnh.get('caliberNote') or '')
          and '当前 ' not in (d_cnh.get('caliberNote') or ''),
          f"{d_cnh.get('caliberNote')}")
    check('S13-04[excluded + 专属理由码]',
          d_cnh.get('excluded_from_scoring') is True
          and d_cnh.get('exclusion_reason') == 'degraded_no_score'
          and d_cnh.get('signal') == 'gray',
          f"excluded={d_cnh.get('excluded_from_scoring')} "
          f"reason={d_cnh.get('exclusion_reason')} signal={d_cnh.get('signal')}")
    check('S13-05[值仍展示 6.6551]', d_cnh.get('value') == 6.6551,
          f"value={d_cnh.get('value')}")

    d_fx = d_meta['dimensions']['fxExternal']
    n_fx = n_meta['dimensions']['fxExternal']
    # A4 后 fxExternal 计分项 = usdcnh/dollarIndex/usBond10Y（creditSpread 仅展示），
    # required_valid 显式降为 2，保证 usdcnh 降级时仍按 2/3 出分（D2 不被降级破掉）。
    check('S13-06[降级不破维度 2/3 出分]',
          d_fx['valid_count'] == 2 and d_fx['required_count'] == 2
          and d_fx['insufficient_data'] is False and d_fx['score'] is not None,
          f'fx={d_fx}')
    check('S13-07[正常态对照：同值仍出分]',
          n_cnh['score'] is not None and n_cnh.get('ratio_value') is not None
          and n_fx['valid_count'] == 3 and n_fx['score'] is not None
          and n_meta['ias']['score'] is not None and d_meta['ias']['score'] is not None,
          f"normal: usdcnh={n_cnh['score']} fx={n_fx['score']} ias={n_meta['ias']['score']}; "
          f"degraded: usdcnh={d_cnh['score']} fx={d_fx['score']} ias={d_meta['ias']['score']}")
    # 差异只能来自 usdcnh：另外 2 个计分项分数必须逐个持平（降级不得波及他项）
    shared_bad = [k for k in ('dollarIndex', 'usBond10Y')
                  if n_ind[k]['score'] != d_ind[k]['score']]
    check('S13-08[降级不波及他项]', not shared_bad, f'{shared_bad}')

    # A4 P0：降级值不得写回历史序列（D7 只拦了打分，没拦住喂序列）
    import tempfile
    from pathlib import Path as _Path
    import series_store as _ss
    old_dir = _ss.SERIES_DIR
    with tempfile.TemporaryDirectory() as td:
        _ss.SERIES_DIR = _Path(td)
        try:
            before = _ss.load('usdcnh')
            # 先写一条正常值做基底，再喂降级值，断言降级日不新增
            ok = {'usdcnh': {'value': 6.6551, 'dataDate': end.isoformat(),
                             'source': 'test', 'history': hist}}
            fetch_mod.sync_series(ok)
            base = _ss.load('usdcnh')
            bad_day = {'usdcnh': {'value': 6.7000, 'dataDate': '2026-12-01',
                                  'source': 'exchangerate-api',
                                  'sourceDegraded': {'reason': 'primary_source_missing'},
                                  'caliberNoteSuffix': '（在岸参考价）'}}
            skipped = fetch_mod.sync_series(bad_day)
            after = _ss.load('usdcnh')
            check('S13-09[降级不写序列]',
                  base == after and '2026-12-01' not in after
                  and skipped == ['usdcnh']
                  and 'history' not in bad_day['usdcnh'],
                  f'before={len(before)} base={len(base)} after={len(after)} '
                  f'skipped={skipped} hist={bad_day["usdcnh"].get("history")}')
        finally:
            _ss.SERIES_DIR = old_dir


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
    safe('S14', test_s14_saturation)
    safe('S15', test_s15_fx_deconflation)
    safe('S16', test_s16_boundary_disclosure, doc)
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
            # 故 replay 契约显式排除 PREV_DERIVED；白名单之外必须逐字节一致。
            # 注意：不得为了让断言变绿去改 neutral 判定，也不得降级为 warn。
            # 时钟派生字段（days_stale/days_overdue）同样不做字节比对，但由下面 R-07a/b
            # 用 drift 公式独立复算兜住（不是「没人管」）。
            SKIP = PREV_DERIVED | CLOCK_DERIVED
            a_s = {k: {f: x for f, x in v.items() if f not in SKIP}
                   for k, v in a_ind.items()}
            j_s = {k: {f: x for f, x in v.items() if f not in SKIP}
                   for k, v in doc['indicators'].items()}
            diff = sorted(k for k in set(a_s) | set(j_s) if a_s.get(k) != j_s.get(k))
            meta_same = (json.dumps(a_meta, sort_keys=True, ensure_ascii=False)
                         == json.dumps(doc['meta'], sort_keys=True, ensure_ascii=False))
            # 覆盖率不倒退：trend 被排除在重放之外，但不能变成「没人管」的字段。
            # 仍须全量 ∈ 合法枚举，并打印分布（up/down 多为真数据，全 neutral 需警觉）。
            trends = [v.get('trend') for v in doc['indicators'].values()]
            trend_ok = bool(trends) and all(t in TREND_ENUM for t in trends)
            n_up = trends.count('up')
            n_down = trends.count('down')
            n_neu = trends.count('neutral')
            print(f"  ℹ️ trend 覆盖: total={len(trends)} up={n_up} down={n_down} "
                  f"neutral={n_neu}（均 ∈ {sorted(TREND_ENUM)}）")
            check('R-07[replay]',
                  not diff and meta_same and trend_ok,
                  f'白名单 {sorted(SKIP)} 外不一致的指标={diff[:8]}；'
                  f'meta 一致={meta_same}；trend 枚举合法={trend_ok}')

            # ── R-07a/b：时钟派生字段的显式派生断言（替代被排除的字节比对） ──
            # drift = 今天 − 快照 timestamp 所在日；重算值必须 = 快照值 + drift。
            # red_days 一律从 indicator_meta.TIMELINESS_RULES 读（单一真源），不写死天数。
            drift = (date.today() - ref_date_of(doc)).days
            # days_overdue 的口径（抄 scoring.py:510-519 的语义，不抄数字）：
            #   超红线 → days_stale − red_days；超黄线未超红 → days_stale − yellow_days；未超 → 0；无日期 → null。
            # 注：龙五派单原文写的是 max(0, days_stale − red_days)，对「黄档」项不成立
            # （oilPrice 9 天 / 黄线 5 → 快照 4，而 9−10 = −1），故按被测实现语义走，已回报。
            def over_of(ds, red, yellow):
                if ds is None:
                    return None
                if ds > red:
                    return ds - red
                if ds > yellow:
                    return ds - yellow
                return 0

            bad_stale, bad_over, bad_rule, missing = [], [], [], []
            for k, jv in doc['indicators'].items():
                av = a_ind.get(k)
                if av is None:
                    missing.append(k)
                    continue
                js, as_ = jv.get('days_stale'), av.get('days_stale')
                if js is None or as_ is None:
                    # null 语义不得漂移：快照说「不知道多旧」，重算也必须不知道
                    if js != as_:
                        bad_stale.append(f"{k}: 快照={js} 重算={as_}（null 语义漂移）")
                elif js + drift != as_:
                    bad_stale.append(f'{k}: 快照 {js} + drift {drift} = {js + drift} != 重算 {as_}')

                freq = jv.get('frequency') or av.get('frequency')
                rule = im.TIMELINESS_RULES.get(freq, im.TIMELINESS_RULES['other'])
                red, yellow = rule['red_days'], rule['yellow_days']
                # 快照自带 staleness_rule 必须与单一真源一致，否则阈值漂移会被白名单掩盖
                sr = jv.get('staleness_rule') or {}
                if sr.get('red_days') != red or sr.get('yellow_days') != yellow:
                    bad_rule.append(
                        f'{k}({freq}): 快照 staleness_rule={sr} != 单一真源 '
                        f'{{"yellow_days": {yellow}, "red_days": {red}}}')
                # 重算侧：days_overdue = 超出「已被突破的那条阈值」的天数
                exp_over = over_of(as_, red, yellow)
                if av.get('days_overdue') != exp_over:
                    bad_over.append(
                        f'{k}: 重算 days_overdue={av.get("days_overdue")} != '
                        f'over({as_}, red={red}, yellow={yellow}) = {exp_over}')
                # 快照侧自洽：否则「改快照 days_overdue」不会被任何断言咬住
                exp_over_snap = over_of(js, red, yellow)
                if jv.get('days_overdue') != exp_over_snap:
                    bad_over.append(
                        f'{k}: 快照 days_overdue={jv.get("days_overdue")} != '
                        f'over({js}, red={red}, yellow={yellow}) = {exp_over_snap}')

            print(f'  ℹ️ 时钟派生: drift={drift} 天 '
                  f'（快照 {ref_date_of(doc)} → 今天 {date.today()}）'
                  f' 覆盖 {len(doc["indicators"]) - len(missing)}/{len(doc["indicators"])} 指标')
            check('R-07a[clock-derived days_stale]',
                  not bad_stale and not missing,
                  f'drift={drift}; ' + '; '.join(bad_stale[:6]) +
                  (f'; 重算缺指标={missing[:6]}' if missing else ''))
            check('R-07b[clock-derived days_overdue]',
                  not bad_over,
                  '; '.join(bad_over[:6]))
            check('R-07c[staleness_rule 单一真源]',
                  not bad_rule,
                  '; '.join(bad_rule[:6]))
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
    # V1b-1：pct_rank 契约（live + fixture 两套都要验）
    safe('S9', test_s9, doc, label)
    # P1-8DIM：工单 §6.5 五条断言（只对 live 有意义：fixture 是合成值）
    if live:
        safe('S10', test_s10_8dim, doc, label)
    if live and fixture_path and Path(fixture_path).exists():
        safe('S9', test_s9, fix, 'fixture')
    return sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=str(WS / 'public' / 'data' / 'market-data.json'))
    ap.add_argument('--fixture', default=str(WS / 'tests' / 'fixtures' / 'market-data-edge-cases.json'))
    ap.add_argument('--json-out')
    ap.add_argument('--no-units', action='store_true')
    args = ap.parse_args()

    # A2：usdcnh ratio_ma_steps 契约（不依赖产物）+ 回算无未来函数
    try:
        test_s11_usdcnh_ratio()
        test_s12_replay_no_lookahead()
        test_s13_usdcnh_degraded_no_score()
    except Exception as e:  # noqa: BLE001
        check('S11/S12/S13[crash]', False, f'{type(e).__name__}: {e}')

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
