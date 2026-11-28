#!/usr/bin/env python3
"""WorldOS 产物健康检查（G：只加判据与日志，不新增 cron）

三类告警（龙六 2026-11-28 第 6 问）：
  ① usdcnh 降级（离岸源失败、回退在岸参考价，或已被口径降级挡在打分外）
  ② 任一维度因有效数不足被剔除（valid_count < required_count）
  ③ IAS boundary_margin < 0.02（刀锋：掉一维就翻档）

设计边界：
  - **不改打分、不写产物、不发通知、不加 cron**；只返回/打印人类可读告警。
  - 单一入口 check_document(doc)，fetch 保存后调用；也可手动跑：
        python3 scripts/health_check.py public/data/market-data.json
"""
import json
import sys
from pathlib import Path

THRESHOLD_MARGIN = 0.02


def check_document(doc: dict) -> list:
    """返回告警字符串列表（空 = 无告警）。不抛异常，坏字段跳过。"""
    warnings = []
    indicators = doc.get('indicators') or {}
    meta = doc.get('meta') or {}

    # ① usdcnh 降级：fetch 层 sourceDegraded，或 scoring 层 degraded_no_score
    cnh = indicators.get('usdcnh') or {}
    if cnh.get('sourceDegraded') or cnh.get('exclusion_reason') == 'degraded_no_score':
        sd = cnh.get('sourceDegraded') or {}
        reason = sd.get('reason') if isinstance(sd, dict) else None
        warnings.append(
            f'usdcnh 降级：{reason or cnh.get("exclusion_reason")}'
            f'（actualSource={cnh.get("actualSource") or sd.get("source") or "—"}）'
            '；在岸回退价只展示、不计分、不进历史序列')

    # ② 维度因有效数不足被剔除
    dims = meta.get('dimensions') or {}
    for dim_id, d in dims.items():
        if d.get('insufficient_data') is True:
            warnings.append(
                f'维度被剔除：{d.get("name", dim_id)}（{dim_id}）'
                f' valid={d.get("valid_count")} < required={d.get("required_count")}'
                f'，丢失有效权重 {d.get("weight_effective")}')

    # ③ 刀锋余量
    ias = meta.get('ias') or {}
    margin = ias.get('boundary_margin')
    if isinstance(margin, (int, float)) and abs(margin) < THRESHOLD_MARGIN:
        warnings.append(
            f'IAS 刀锋：boundary_margin={margin:+.4f}（<{THRESHOLD_MARGIN}）'
            f' 距阈值 {ias.get("boundary_threshold")} 仅一步；'
            f'脆弱维度={ias.get("fragile_inputs") or []}'
            f'；跨档后信号={ias.get("boundary_next_signal")}')

    return warnings


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ws = Path(__file__).resolve().parent.parent
    path = Path(argv[0]) if argv else ws / 'public' / 'data' / 'market-data.json'
    doc = json.loads(path.read_text())
    warnings = check_document(doc)
    if not warnings:
        print(f'✅ 健康检查通过：{path}')
        return 0
    print(f'🩺 {path}：{len(warnings)} 条告警')
    for w in warnings:
        print(f'  - {w}')
    return 0  # 告警不改变退出码（不加 cron，也不阻断抓取）


if __name__ == '__main__':
    raise SystemExit(main())
