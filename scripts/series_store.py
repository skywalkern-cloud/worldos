#!/usr/bin/env python3
"""WorldOS 历史序列存储（V1b-1）

为什么单独一个模块：
  「读历史 / 追加今日 / 取样本窗口」这套动作，回填脚本（backfill_series.py）、
  日抓（fetch_worldos_data.py）、回算脚本（replay_sentiment_30d.py）三方都要用。
  任何一方自己实现一份，就会出现「回填写的是 79.80、线上写的是 79.81」这种鬼差异。
  单一真源：本模块。

存储约定（PM 2026-11-28 定）：
  data/history/series/<key>.json
  {"key","unit","transform","seriesValueKind":"raw","updatedAt","count",
   "series":[{"date":"YYYY-MM-DD","value":x}, ...]}
  - append-only：只增不减（本次没抓到某天，绝不删历史）；
  - 日期升序；同日重复取最后一条（幂等）；
  - series 里恒存 raw 值，transform 在打分时才算；
  - 原子写（tmp + replace），并只在真的变了时才写盘。
"""
import json
from datetime import datetime
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SERIES_DIR = WS / 'data' / 'history' / 'series'


def series_path(key: str) -> Path:
    return SERIES_DIR / f'{key}.json'


def load(key: str) -> dict:
    """返回 {date: value}（raw）。文件缺失/损坏 → 空 dict（不抛，打分侧走 warmup）。"""
    p = series_path(key)
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text())
        return {r['date']: r['value'] for r in doc.get('series', []) if r.get('date')}
    except Exception:
        return {}


def load_doc(key: str) -> dict:
    p = series_path(key)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def upsert(key: str, date: str, value, *, unit: str, transform: str,
           dry_run: bool = False) -> dict:
    """追加/更新一个数据点（幂等）。返回最新 doc。"""
    if not date or value is None:
        return load_doc(key)
    merged = load(key)
    before = dict(merged)
    merged[date] = value
    if merged == before:
        return load_doc(key)                      # 无变化，不碰文件（避免无意义覆盖）
    rows = [{'date': d, 'value': merged[d]} for d in sorted(merged)]
    doc = {
        'key': key,
        'unit': unit,
        'transform': transform,
        'seriesValueKind': 'raw',
        'updatedAt': datetime.now().isoformat(timespec='seconds'),
        'count': len(rows),
        'series': rows,
    }
    if dry_run:
        return doc
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    p = series_path(key)
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n')
    tmp.replace(p)
    return doc


def history_before(key: str, date: str, limit: int = 80) -> list:
    """取指定日期**之前**的原始观测（升序，最多 limit 条）。

    含 `date` 当天的一律剔除 —— pct_rank 的样本池不许含今日（PM 2026-11-28 确认口径）。
    """
    rows = load(key)
    keys = sorted(d for d in rows if d < date)
    if limit:
        keys = keys[-limit:]
    return [{'date': d, 'value': rows[d]} for d in keys]
