#!/usr/bin/env python3
"""WorldOS V1b-1 历史回填：给 4 个 A股/港股情绪指标攒够 pct_rank 窗口。

为什么要有这一步（先补历史，再谈转正）：
  pct_rank 需要 ≥60 个有效历史观测才敢出分（<20 只能 warmup）。线上 daily 抓取
  一天只留一条，攒到 60 天要等两个月 —— 转正不能靠等，必须回填。

存储约定（PM 2026-11-28 定，龙六复核）：
  data/history/series/<key>.json
  {"key":..., "unit":..., "transform":..., "updatedAt":..., "series":[{"date":"YYYY-MM-DD","value":x}, ...]}
  - append-only：只增不减，绝不因为「本次没抓到某天」就把历史删掉；
  - 按日期升序；同日重复取最后一条（幂等，可反复重跑）；
  - series 里恒存**原始值（raw）**，transform（delta5/sum5）在打分时才算，
    这样回填/取数互不耦合，改 transform 不用重写历史。

用法:
  python3 scripts/backfill_series.py            # 回填全部 4 项
  python3 scripts/backfill_series.py --key marginBalance
  python3 scripts/backfill_series.py --dry-run  # 只打印，不落盘
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

WS = Path(__file__).resolve().parent.parent
SERIES_DIR = WS / 'data' / 'history' / 'series'

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
EM_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}

# 每项的元信息（unit / transform 与 indicator_meta 保持一致，此处只做存储声明）
SERIES_META = {
    'ashareTurnover': {'unit': '亿元', 'transform': 'raw'},
    'marginBalance': {'unit': '亿元', 'transform': 'delta5'},
    'southboundNet': {'unit': '亿元', 'transform': 'sum5'},
    'hstechMomentum': {'unit': '百分点', 'transform': 'raw'},
    'usdcnh': {'unit': '', 'transform': 'raw'},      # A2：离岸人民币日线（MA120 分母序列）
}


# ═══════════════════════════════════════════
# 取数
# ═══════════════════════════════════════════

def em_kline(secid, lmt=400):
    """东财日 K：返回 [(date, close, amount)] 升序。f57 = 成交额(元)。"""
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
           f'?secid={secid}&fields1=f1,f2&fields2=f51,f52,f53,f54,f55,f56,f57'
           f'&klt=101&fqt=1&end=20500101&lmt={lmt}')
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    doc = r.json()
    if doc.get('rc') not in (0, None):
        raise ValueError(f'{secid} rc={doc.get("rc")}')
    out = []
    for line in (doc.get('data') or {}).get('klines') or []:
        p = line.split(',')
        if len(p) < 7:
            continue
        try:
            out.append((p[0], float(p[2]), float(p[6])))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def em_datacenter(report_name, *, filter_expr=None, sort_column='DIM_DATE', page_size=400):
    params = [f'reportName={report_name}', 'columns=ALL', 'source=WEB', 'client=WEB',
              f'sortColumns={sort_column}', 'sortTypes=-1',
              'pageNumber=1', f'pageSize={page_size}', 'pageNo=1']
    if filter_expr:
        from urllib.parse import quote as _q
        params.append('filter=' + _q(filter_expr))
    url = 'https://datacenter-web.eastmoney.com/api/data/v1/get?' + '&'.join(params)
    r = requests.get(url, headers=EM_HEADERS, timeout=25)
    r.raise_for_status()
    rows = (r.json().get('result') or {}).get('data') or []
    if not rows:
        raise ValueError(f'{report_name} 返回空数据')
    return rows


# ═══════════════════════════════════════════
# 各指标的历史序列构建（全部返回 {date: value}，值为 raw）
# ═══════════════════════════════════════════

def build_ashare_turnover():
    """两市成交额（亿元）：同日对齐后相加，任一路缺该日 → 丢弃该日。"""
    sh = {d: amt for d, _c, amt in em_kline('1.000001') if amt > 0}
    sz = {d: amt for d, _c, amt in em_kline('0.399001') if amt > 0}
    common = sorted(set(sh) & set(sz))
    return {d: round((sh[d] + sz[d]) / 1e8, 2) for d in common}   # 元 → 亿元


def build_margin_balance():
    """融资余额（亿元）= RZYE/1e8。排序列必须是 DIM_DATE（写 DATE 会报排序列不存在）。"""
    rows = em_datacenter('RPTA_RZRQ_LSHJ', sort_column='DIM_DATE', page_size=400)
    out = {}
    for r in rows:
        d = (r.get('DIM_DATE') or '')[:10]
        v = r.get('RZYE')
        if not d or v is None:
            continue
        out[d] = round(float(v) / 1e8, 2)
    return out


def build_southbound_net():
    """南向净买入（亿元）：004 + 006 同日对齐相加，任一路缺该日 → 丢弃该日。

    舍入顺序故意与 fetch_worldos_data.get_southbound_net 一致（先各路保留 2 位再相加），
    否则同一交易日会出现 79.81(线上) vs 79.80(回填) 的鬼差异 —— 序列末日必须与线上当日值逐位相等，
    否则 pct_rank 的今日样本和窗口样本不在一套刻度上。
    """
    legs = {}
    for mt in ('004', '006'):
        rows = em_datacenter('RPT_MUTUAL_DEAL_HISTORY',
                            filter_expr=f'(MUTUAL_TYPE="{mt}")',
                            sort_column='TRADE_DATE', page_size=400)
        leg = {}
        for r in rows:
            d = (r.get('TRADE_DATE') or '')[:10]
            v = r.get('NET_DEAL_AMT')
            if d and v is not None:
                leg[d] = round(float(v) / 100, 2)     # 百万元 → 亿元（先舍入，与线上同口径）
        legs[mt] = leg
    common = sorted(set(legs['004']) & set(legs['006']))
    return {d: round(legs['004'][d] + legs['006'][d], 2) for d in common}


def _close_on_or_before(bars, target):
    """as-of join：取 <= target 的最近一根（A股/港股节假日不重合，按日期对齐而非按位置）。"""
    hit = None
    for d, c, _a in bars:
        if d <= target:
            hit = (d, c)
        else:
            break
    return hit


def build_hstech_momentum():
    """恒生科技 20 日相对强弱（百分点），以 A 股交易日为时间轴，HSTECH 用 as-of join。"""
    hst = em_kline('124.HSTECH', lmt=400)
    sh = em_kline('1.000001', lmt=400)
    if len(hst) < 21:
        raise ValueError(f'HSTECH 日线不足（{len(hst)} 根）')
    out = {}
    for i in range(20, len(hst)):
        d, c = hst[i][0], hst[i][1]
        base_d, base_c = hst[i - 20][0], hst[i - 20][1]
        sh_t = _close_on_or_before(sh, d)
        sh_b = _close_on_or_before(sh, base_d)
        if not sh_t or not sh_b or not base_c or not sh_b[1]:
            continue
        hst_ret = (c / base_c - 1) * 100
        sh_ret = (sh_t[1] / sh_b[1] - 1) * 100
        out[d] = round(hst_ret - sh_ret, 1)
    return out


def build_usdcnh():
    """美元兑离岸人民币日线收盘（A2，2026-11-28）。

    源：akshare.forex_hist_em('USDCNH')——实测 4232 行、带交易日、最新 2026-11-27=6.6551。
    只回填**最近 250 个交易日**（足够 MA120 + 19 日回算窗口，又不至于把十年数据塞进仓库）。
    序列存 raw 收盘，MA120 在打分时按窗口均值现算，**不落任何均值常数**。
    """
    import akshare as ak
    df = ak.forex_hist_em(symbol='USDCNH')
    if df is None or df.empty:
        raise ValueError('forex_hist_em(USDCNH) 返回空')
    df = df.sort_values('日期')
    out = {}
    for _, row in df.tail(250).iterrows():
        d = str(row.get('日期'))[:10]
        v = row.get('最新价')
        if d and v is not None and v == v:      # v==v 排 NaN（不依赖 numpy）
            out[d] = round(float(v), 4)
    if not out:
        raise ValueError('forex_hist_em(USDCNH) 无有效收盘')
    return out


BUILDERS = {
    'ashareTurnover': build_ashare_turnover,
    'marginBalance': build_margin_balance,
    'southboundNet': build_southbound_net,
    'hstechMomentum': build_hstech_momentum,
    'usdcnh': build_usdcnh,
}


# ═══════════════════════════════════════════
# 合并 + 落盘（幂等、append-only）
# ═══════════════════════════════════════════

def series_path(key):
    return SERIES_DIR / f'{key}.json'


def load_existing(key):
    p = series_path(key)
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text())
        return {r['date']: r['value'] for r in doc.get('series', [])}
    except Exception as e:
        print(f'  ⚠️ 既有序列读取失败（将重建，历史请从 git 恢复）：{e}')
        return {}


def merge_and_write(key, new_points, dry_run=False):
    """读旧 + 合并 + 原子写。只在「真的有变化」时才写文件，避免无意义覆盖。"""
    meta = SERIES_META[key]
    existing = load_existing(key)
    merged = dict(existing)
    added = 0
    for d, v in new_points.items():
        if d not in merged:
            added += 1
        merged[d] = v                          # 同日取最后一条（幂等）
    dropped = len(existing) - len(set(existing) & set(merged))
    rows = [{'date': d, 'value': merged[d]} for d in sorted(merged)]
    doc = {
        'key': key,
        'unit': meta['unit'],
        'transform': meta['transform'],
        'seriesValueKind': 'raw',
        'updatedAt': datetime.now().isoformat(timespec='seconds'),
        'count': len(rows),
        'series': rows,
    }
    changed = (added > 0) or (rows != [{'date': d, 'value': existing[d]} for d in sorted(existing)])
    if dry_run:
        print(f'  [dry-run] {key}: 将写 {len(rows)} 条（新增 {added}）')
        return doc
    if not changed:
        print(f'  {key}: 无变化（{len(rows)} 条），跳过写盘')
        return doc
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = series_path(key).with_suffix('.json.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n')
    tmp.replace(series_path(key))              # 原子替换，避免半截文件
    drop_note = '丢弃 0' if not dropped else f'丢失 {dropped}'
    print(f'  {key}: 写入 {len(rows)} 条（新增 {added}，{drop_note}），'
          f'{rows[0]["date"]} → {rows[-1]["date"]}')
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', action='append', choices=list(BUILDERS), help='只回填指定 key')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    keys = args.key or list(BUILDERS)
    print(f'🔄 历史回填 {len(keys)} 项 → {SERIES_DIR}')
    fail = []
    for key in keys:
        print(f'📚 {key}...', end=' ', flush=True)
        try:
            points = BUILDERS[key]()
            print(f'源数据 {len(points)} 天', end=' | ')
            merge_and_write(key, points, dry_run=args.dry_run)
        except Exception as e:
            print(f'❌ 失败: {type(e).__name__}: {e}')
            fail.append((key, str(e)))
    if fail:
        print('\n❌ 失败项：')
        for k, e in fail:
            print(f'  - {k}: {e}')
        return 1
    print('\n✅ 全部完成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
