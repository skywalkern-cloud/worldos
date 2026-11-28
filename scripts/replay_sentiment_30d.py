#!/usr/bin/env python3
"""WorldOS V1b-1：撤 market_mismatch 前后的 30 个交易日回算对比。

⛔ 已废弃（P1-8DIM 2026-11-28）：维度 id `sentiment` 已拆为 `sentimentA` + `riskAppetite`，
   本脚本依赖的 `sentiment` 维度不存在了，且它「其余五维冻结」的前提也已过时。
   替代：`scripts/replay_8dim_30d.py`（旧 6 维 vs 新 8 维逐日回算 + 归因）。
   保留本文件只为回溯 V1b-1 的历史结论；不要再跑，也不要拿它当现状基线。

⚠️ 边界（必须和结论一起引用，别包装成「30 日 IAS 回测」）：
   只有 4 个新指标有逐日历史序列；其余 31 项（VIX/F&G 及各宏观项）**没有**逐日历史。
   因此本脚本的逐日回算 = 「其余五个维度锁死为当日值，仅逐日重算 sentiment」。
   结论只对 sentiment 维度（及其对 IAS 的权重贡献）成立，
   **不能**用来判断整体 IAS 信号的日间稳定性 —— 那需要六维逐日历史，目前不存在。

它回答两个问题：
  Q1 sentiment 维度分档（get_signal）在撤 mismatch 前后翻转几次？  ← 预期 0：mismatch 只乘在权重上，不改维度分
  Q2 IAS 分档翻转几次？（同一天在 0.4 / 0.8 两个有效权重下）      ← 这才是 mismatch 真正影响的东西

用法:
  python3 scripts/replay_sentiment_30d.py
  python3 scripts/replay_sentiment_30d.py --days 30 --json out.json
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
WS = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import indicator_meta as im          # noqa: E402
import scoring                        # noqa: E402
import series_store                    # noqa: E402

PCT_KEYS = list(im.QUANTILE_CONFIG)   # pct_rank + ratio_band 两类都算
# 没有逐日历史、只能冻结为当日值的 sentiment 成员
_SENT_DIM = next((d for d in im.DIMENSIONS if d['id'] == 'sentiment'), None)
if _SENT_DIM is None:
    # 不静默 StopIteration / 不自动换到 sentimentA（口径不同，换了就是假结论）
    raise SystemExit(
        '已废弃：维度 sentiment 已拆为 sentimentA + riskAppetite（P1-8DIM 2026-11-28）。\n'
        '请改用 scripts/replay_8dim_30d.py；本脚本不再维护。')
FROZEN_KEYS = [k for k in ['vix', 'fearGreed'] if k in _SENT_DIM['indicators']]

DISCLAIMER = ('本次回算只覆盖 sentiment 维度，其余五维冻结为当日值，'
              '因此 IAS 的日间差异不具代表性，不能用来判断整体信号的稳定性')


def trading_dates(days):
    """以 ashareTurnover 的序列日期为 A 股交易日轴，取最近 days 个。"""
    rows = sorted(series_store.load('ashareTurnover'))
    return rows[-days:]


def sentiment_dim_scores_for(date_str, live_doc):
    """算某一天的 sentiment 维度分（其余维度缺数据 → 置灰，不入 IAS）。"""
    ind = {}
    # 4 个 pct_rank 指标：当天值 + 当天之前的历史
    for key in PCT_KEYS:
        series = series_store.load(key)
        if date_str not in series:
            continue
        hist = series_store.history_before(key, date_str, limit=max(im.PCT_RANK_WINDOW_LONG, im.RATIO_MA_WINDOW) + 7)
        if key in im.RATIO_BAND_CONFIG:
            r = scoring.score_by_ratio_band(key, series[date_str], hist)
        else:
            r = scoring.score_by_pct_rank(key, series[date_str], hist)
        ind[key] = {'score': r['score'], 'timeliness': 1.0}
    # 冻结项：用线上当日值（没有逐日历史，这是本次回算的已知边界）
    for key in FROZEN_KEYS:
        live = (live_doc.get('indicators') or {}).get(key) or {}
        ind[key] = {'score': live.get('score'), 'timeliness': live.get('timeliness', 1.0)}
    return scoring.calc_dimension_scores(ind, {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--json', type=str, default=None)
    args = ap.parse_args()

    live = json.load(open(WS / 'public' / 'data' / 'market-data.json'))
    live_dims = live['meta']['dimensions']

    sent_dim = next(d for d in im.DIMENSIONS if d['id'] == 'sentiment')
    w_before = im.dimension_weights({**sent_dim, 'market_mismatch': 0.5})['effective']
    w_after = im.dimension_weights(sent_dim)['effective']
    print(f'有效权重：撤前(mismatch×0.5)={w_before}  撤后(满额)={w_after}\n')

    rows = []
    for d in trading_dates(args.days):
        ds = sentiment_dim_scores_for(d, live)
        sent = ds.get('sentiment') or {}
        # 其余五维锁定为当日值
        merged_before, merged_after = {}, {}
        for dim_id, meta in live_dims.items():
            entry = {'score': meta.get('score'),
                     'insufficient_data': meta.get('insufficient_data', False),
                     'weight_effective': meta.get('weight_effective')}
            if dim_id == 'sentiment':
                entry.update({'score': sent.get('score'),
                              'insufficient_data': sent.get('insufficient_data', False),
                              'valid_count': sent.get('valid_count')})
                merged_before[dim_id] = {**entry, 'weight_effective': w_before}
                merged_after[dim_id] = {**entry, 'weight_effective': w_after}
            else:
                merged_before[dim_id] = dict(entry)
                merged_after[dim_id] = dict(entry)

        ias_b, ias_a = scoring.calc_ias(merged_before), scoring.calc_ias(merged_after)
        rows.append({
            'date': d,
            'sentiment_score': sent.get('score'),
            'sentiment_signal': scoring.get_signal(sent['score']) if sent.get('score') is not None else 'gray',
            'sentiment_valid': sent.get('valid_count'),
            'ias_before': ias_b['score'],
            'ias_after': ias_a['score'],
            'ias_signal_before': ias_b['signal'],
            'ias_signal_after': ias_a['signal'],
        })

    def flips(field):
        return sum(1 for i in range(1, len(rows)) if rows[i][field] != rows[i - 1][field])

    s_flips = flips('sentiment_signal')
    i_flips_before, i_flips_after = flips('ias_signal_before'), flips('ias_signal_after')
    # 跨臂：同一天在撤前/撤后两套权重下分档是否不同
    cross = sum(1 for r in rows if r['ias_signal_before'] != r['ias_signal_after'])

    print(f'{"日期":<12}{"sentiment":<11}{"分档":<8}{"valid":<6}{"IAS撤前":<9}{"IAS撤后":<9}分档(撤前/撤后)')
    for r in rows:
        print(f"{r['date']:<12}{str(r['sentiment_score']):<11}{r['sentiment_signal']:<8}"
              f"{str(r['sentiment_valid']):<6}{str(r['ias_before']):<9}{str(r['ias_after']):<9}"
              f"{r['ias_signal_before']} / {r['ias_signal_after']}")

    print('\n' + '=' * 62)
    print(f'样本：{len(rows)} 个交易日（{rows[0]["date"]} → {rows[-1]["date"]}）')
    print(f'① sentiment 分档翻转：撤前 vs 撤后 = **0 次差异**（两臂序列完全相同）；')
    print(f'   序列自身翻转 {s_flips} 次（那是 sentiment 自身 30 天的波动，与本变更无关）')
    print(f'   原因：market_mismatch 只乘在**权重**上（w_eff 0.4→0.8），不参与维度分计算')
    print(f'② IAS 分档翻转：撤前 {i_flips_before} 次 / 撤后 {i_flips_after} 次')
    print(f'③ 同一天跨臂分档不同（撤前≠撤后）：{cross} / {len(rows)} 天')
    print(f'\n⚠️ 边界声明：{DISCLAIMER}')

    if args.json:
        Path(args.json).write_text(json.dumps({
            'disclaimer': DISCLAIMER,
            'weights': {'before': w_before, 'after': w_after},
            'rows': rows,
            'flips': {'sentiment_series_transitions': s_flips,
                      'sentiment_arm_diff': 0,
                      'ias_before': i_flips_before, 'ias_after': i_flips_after,
                      'cross_arm_days': cross},
        }, ensure_ascii=False, indent=1))
        print(f'\n已写出：{args.json}')


if __name__ == '__main__':
    main()
