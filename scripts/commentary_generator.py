#!/usr/bin/env python3
"""
WorldOS 数据解读评论生成器 v1.0 (模板引擎)

⚠️  此文件已被 v2.0 (generate_commentary_llm.py) 替代。
    保留作为 LLM 调用失败时的 fallback 使用。
    主入口：generate_commentary_llm.py

根据评分后的 indicators 和 meta 数据，自动生成 8 个维度 + IAS整体解读的评论。
完全基于模板引擎，无需 LLM 或外部依赖。

输出: commentary.json (public/data/commentary.json)
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def _sanitize(obj):
    """递归把 NaN/±Infinity 转成 None，保证 allow_nan=False 可序列化。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return _sanitize(obj.item())
    except ImportError:
        pass
    return obj


def write_json_strict(path, obj):
    """原子写入合法 JSON：清洗 NaN/Inf → allow_nan=False → 严格回读自检。"""
    path = Path(path)
    clean = _sanitize(obj)
    payload = json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False)

    def _reject_constant(token):
        raise ValueError(f"非法 JSON 常量: {token}")

    json.loads(payload, parse_constant=_reject_constant)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + '.tmp')
    tmp_path.write_text(payload, encoding='utf-8')
    os.replace(tmp_path, path)
    return clean

# ─── 维度与指标名：全部来自 indicator_meta（单一真源，P0/T1）───
# 此前本文件自带 DIMENSION_META / DIMENSION_INDICATORS / INDICATOR_SHORT /
# INDICATOR_COUNTRY 四份映射，与 scoring.py 互相覆盖并污染了评论正文里的口径。
from indicator_meta import (  # noqa: E402
    DIMENSIONS as _DIMENSIONS,
    INDICATOR_SHORT,
    INDICATOR_COUNTRY,
    display_name,
    short_name,
)

DIMENSION_ORDER = [d['id'] for d in _DIMENSIONS]
DIMENSION_META = {
    d['id']: {'name': d['name'], 'icon': d['icon'], 'weight': d['weight']}
    for d in _DIMENSIONS
}
DIMENSION_INDICATORS = {d['id']: list(d['indicators']) for d in _DIMENSIONS}


# ═══════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════

def classify_score(score: Optional[float]) -> str:
    """评分分类"""
    if score is None:
        return 'no_data'
    if score >= 0.5:
        return 'very_positive'
    if score >= 0.1:
        return 'positive'
    if score >= -0.1:
        return 'neutral'
    if score >= -0.5:
        return 'negative'
    return 'very_negative'


def get_signal_label(signal: str) -> str:
    """信号颜色映射为文字"""
    return {'green': '🟢', 'lightgreen': '🟢', 'gray': '🟡', 'yellow': '🟡', 'red': '🔴'}.get(signal, '🟡')


def _is_numeric(val) -> bool:
    """检查值是否为有效的数值类型"""
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return True
    # str that can be coerced to number
    try:
        float(str(val))
        return True
    except (ValueError, TypeError):
        return False


def get_indicator(indicators: dict, key: str) -> dict:
    """安全获取指标数据，返回带默认值的 dict"""
    default = {'value': None, 'score': None, 'signal': 'gray', 'unit': '', 'name': key}
    ind = indicators.get(key)
    if not ind:
        return default
    result = {**default, **ind}
    # Sanitize: if value is not numeric, treat it as None
    if not _is_numeric(result['value']):
        result['value'] = None
        result['score'] = None
    return result


def value_str(indicator: dict, decimals: int = 1) -> str:
    """格式化数值：有值返回带单位的加粗字符串，无值返回'暂无数据'"""
    raw_val = indicator.get('value')
    if raw_val is None:
        return '暂无数据'
    if not isinstance(raw_val, (int, float)):
        try:
            raw_val = float(str(raw_val))
        except (ValueError, TypeError):
            return '暂无数据'
    fmt = f".{decimals}f"
    val = format(raw_val, fmt)
    unit = indicator.get('unit', '')
    # 如果 unit 不是 % 则非空白时加在值后
    if unit and unit != '%':
        return f"**{val}**{unit}"
    elif unit == '%':
        return f"**{val}%**"
    return f"**{val}**"


def score_indicator(score: Optional[float]) -> str:
    """评分方向描述"""
    if score is None:
        return '—'
    if score > 0:
        return '偏正面'
    if score < 0:
        return '偏负面'
    return '中性'


# ═══════════════════════════════════════════
# 维度解读函数
# ═══════════════════════════════════════════

def _dim_commentary_economic(indicators: dict, dim_meta: dict) -> str:
    """📈 经济增长板块解读"""
    dim_score = dim_meta.get('score', 0)
    cls = classify_score(dim_score)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    # 提取关键指标
    china_gdp = get_indicator(indicators, 'chinaGdp')
    china_pmi = get_indicator(indicators, 'chinaPmi')
    service_pmi = get_indicator(indicators, 'servicePmi')
    us_gdp = get_indicator(indicators, 'usGdp')
    us_nonfarm = get_indicator(indicators, 'usNonFarm')
    electricity = get_indicator(indicators, 'electricity')

    lines = []

    # 结论句
    lines.append(f"经济增长板块评分**{dim_score:+.2f}**（{signal_label}），信号偏"
                 f"{'正面' if dim_score > 0.1 else '谨慎' if dim_score > -0.1 else '负面'}"
                 f"。")

    # 中国部分
    cn_parts = []
    gdp_v = china_gdp.get('value')
    pmi_v = china_pmi.get('value')
    svc_v = service_pmi.get('value')
    elec_v = electricity.get('value')
    if gdp_v is not None:
        target_text = f"持平年度目标" if abs(gdp_v - 5.0) < 0.3 else ("高于" if gdp_v > 5.0 else "低于")
        cn_parts.append(f"中国GDP同比{value_str(china_gdp)}{' ' + target_text + ' 5.0%' if abs(gdp_v - 5.0) < 0.3 else ''}")
    if pmi_v is not None:
        below_50 = "跌破" if pmi_v < 50 else "处于"
        cn_parts.append(f"制造业PMI **{pmi_v:.1f}**{' 跌破荣枯线' if pmi_v < 50 else ' 在荣枯线附近' if pmi_v < 50.5 else ' 在扩张区间'}")
    if svc_v is not None:
        cn_parts.append(f"服务业PMI **{svc_v:.1f}**{'跌破' if svc_v < 50 else '高于'}50荣枯线")

    if cn_parts:
        lines.append("中国方面，" + "，".join(cn_parts[:3]) + "。")

    # 美国部分
    us_parts = []
    usg_v = us_gdp.get('value')
    nf_v = us_nonfarm.get('value')
    if usg_v is not None:
        us_parts.append(f"美国GDP同比{value_str(us_gdp)}{' 低于2.5% target' if usg_v < 2.3 else ' 符合预期'}")
    if nf_v is not None:
        nf_target = 200
        us_parts.append(f"非农就业{value_str(us_nonfarm)}{' 显著低于' if nf_v < nf_target else ' 大超' if nf_v > nf_target + 50 else ' 接近'}{nf_target}万target")
    if us_parts:
        lines.append("美国方面，" + "，".join(us_parts[:2]) + "。")

    # 交叉分析
    cross_parts = []
    if elec_v is not None:
        cross_parts.append(f"用电量同比{value_str(electricity)}保持扩张")
    # 判断双方信号
    us_signal = cls
    if usg_v is not None and usg_v < 2.0:
        us_signal = 'negative'
    cross_parts.append(f"中美双方面临增长动能{'偏弱' if 'negative' in [cls, us_signal] else '分化'}的问题")

    lines.append("、".join(cross_parts) + "，短期难见强劲反弹。" if '偏弱' in cross_parts[-1] else "，短期仍待观察。")

    return ''.join(lines)


def _dim_commentary_inflation(indicators: dict, dim_meta: dict) -> str:
    """💰 通胀与政策板块解读"""
    dim_score = dim_meta.get('score', 0)
    cls = classify_score(dim_score)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    cpi = get_indicator(indicators, 'cpi')
    ppi = get_indicator(indicators, 'ppi')
    us_cpi = get_indicator(indicators, 'usCpi')
    core_pce = get_indicator(indicators, 'corePce')
    fed_rate = get_indicator(indicators, 'fedRate')

    lines = []
    cls_label = '中性偏谨慎' if cls in ('neutral', 'positive') else '偏正面' if dim_score > 0.1 else '偏负面'
    lines.append(f"通胀与政策板块评分**{dim_score:+.2f}**（{signal_label}），{cls_label}。")

    # 中国通胀
    cn_parts = []
    cpi_v = cpi.get('value')
    ppi_v = ppi.get('value')
    if cpi_v is not None:
        ideal = cpi_v >= 1.0 and cpi_v <= 3.0
        cn_parts.append(f"中国CPI{value_str(cpi)}{' 处于1-3%温和区间' if ideal else ' 处于偏低水平' if cpi_v < 1.0 else ' 偏高'}")
    if ppi_v is not None:
        cn_parts.append(f"PPI{value_str(ppi)}{' 高于0% target，PPI-CPI剪刀差挤压中下游企业利润' if ppi_v > 0.5 else ' 接近0% target，价格传导压力可控'}")
    if cn_parts:
        lines.append("国内方面，" + "，".join(cn_parts) + "。")

    # 美国通胀
    us_parts = []
    usc_v = us_cpi.get('value')
    pce_v = core_pce.get('value')
    if usc_v is not None:
        us_parts.append(f"美国CPI{value_str(us_cpi)}{' 高于2%目标' if usc_v > 2.5 else ' 接近2%目标'}")
    if pce_v is not None:
        us_parts.append(f"核心PCE{value_str(core_pce)}{' 超Fed 2%目标' if pce_v > 2.5 else ' 接近Fed 2%目标'}")
    fr_v = fed_rate.get('value')
    if fr_v is not None:
        us_parts.append(f"联邦基金利率{value_str(fed_rate)}{' 处于中性略偏紧位置' if fr_v >= 3.0 else ' 宽松水平'}，短期降息空间有限" if fr_v >= 3.0 else '')
    if us_parts:
        lines.append("美国方面，" + "，".join(us_parts) + "。")

    # 综合
    if cpi_v is not None and usc_v is not None and cpi_v < 2.0 and usc_v > 3.0:
        lines.append(f"中国有宽松空间但需求端传导不畅，美国继续面临'higher for longer'的利率环境。")
    else:
        lines.append(f"中美货币政策空间不对称，需关注通胀走势分化对跨境资本流动的影响。")

    return ''.join(lines)


def _dim_commentary_liquidity(indicators: dict, dim_meta: dict) -> str:
    """💧 流动性（国内）板块解读

    P1-8DIM（2026-11-28）：本维度为国内 4 项（LPR / DR007 / M2 / 中债10Y）。
    中美利差 / 美元指数 / 美债收益率已迁到 fxExternal，本段不再重复讲，
    否则同一件事在两张卡上说两遍（口径重复 = 读者无法归因）。
    """
    dim_score = dim_meta.get('score', 0)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    lpr = get_indicator(indicators, 'lpr')
    dr007 = get_indicator(indicators, 'dr007')
    m2 = get_indicator(indicators, 'm2')
    cny10 = get_indicator(indicators, 'chinaBond10Y')

    lines = []
    cls_label = ('国内流动性中性偏松但结构分化' if abs(dim_score) < 0.2
                 else ('国内流动性偏宽松' if dim_score > 0 else '国内流动性偏紧'))
    lines.append(f"流动性（国内）板块评分**{dim_score:+.2f}**（{signal_label}），{cls_label}。")

    parts = []
    lpr_v = lpr.get('value')
    dr_v = dr007.get('value')
    m2_v = m2.get('value')
    if lpr_v is not None:
        parts.append(f"LPR{value_str(lpr)}{' 低于3.5%政策中枢，价格型工具偏松' if lpr_v < 3.5 else ' 符合政策中枢'}")
    if dr_v is not None:
        parts.append(f"DR007实际成交{value_str(dr007, 2)}{' 低于1.8%中性线，银行间不缺钱' if dr_v < 1.6 else ' 在1.8%附近，资金面中性'}")
    if m2_v is not None:
        parts.append(f"M2增速{value_str(m2)}{' 接近9%目标' if abs(m2_v - 9.0) < 1.5 else ''}")
    cny10_v = cny10.get('value')
    if cny10_v is not None:
        parts.append(f"中债10Y {value_str(cny10, 2)}{' 处于低位，长端利率宽松' if cny10_v < 2.0 else ''}")
    if parts:
        lines.append("国内货币环境：" + "，".join(parts) + "。")

    missing = [k for k, v in (('LPR', lpr), ('DR007', dr007), ('M2', m2),
                               ('中债10Y', cny10)) if v.get('value') is None]
    if missing:
        lines.append(f"注意：{'/'.join(missing)} 本轮缺失。本维度 4 项，"
                     "最小有效数 2；有效项不足 2 时整维置灰（0.8 权重不计入 IAS）。")
    else:
        lines.append("四项均有效，按权重全额计入 IAS。")

    lines.append("跨境资金与美债收益率已单独成「汇率与外部」维度，不在本段重复。")
    return ''.join(lines)


def _dim_commentary_sentimentA(indicators: dict, dim_meta: dict) -> str:
    """🧠 A股/港股情绪板块解读（P1-8DIM：原 sentiment 拆分而来）

    成员：两市成交额（相对量）、融资余额（5日变化率）、南向净买入（5日累计）、恒科动量。
    权重 0.9——老板 46% 仓位在港股，这一维的解释力比美股情绪更高。
    """
    dim_score = dim_meta.get('score', 0)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    turnover = get_indicator(indicators, 'ashareTurnover')
    margin = get_indicator(indicators, 'marginBalance')
    south = get_indicator(indicators, 'southboundNet')
    hstech = get_indicator(indicators, 'hstechMomentum')

    lines = []
    lines.append(f"A股/港股情绪板块评分**{dim_score:+.2f}**（{signal_label}）。")

    parts = []
    t_v = turnover.get('value')
    if t_v is not None:
        r = turnover.get('r_value')
        base = turnover.get('ma120_base')
        extra = (f"（相对前120日均值 {r:.2f} 倍，基准 {base:.0f} 亿）"
                 if isinstance(r, (int, float)) and isinstance(base, (int, float)) else '')
        parts.append(f"两市成交额{value_str(turnover, 0)}{extra}")
    m_v = margin.get('value')
    if m_v is not None:
        parts.append(f"融资余额{value_str(margin, 0)}（打分取5日变化率）")
    s_v = south.get('value')
    if s_v is not None:
        parts.append(f"南向净买入{value_str(south)}（5日累计口径）")
    h_v = hstech.get('value')
    if h_v is not None:
        parts.append(f"恒科相对上证20日强弱{value_str(hstech)}")
    if parts:
        lines.append("、".join(parts) + "。")

    # 打分方法透明化：4 项都是相对量/分位，不说清楚会被误读成绝对水平判断
    lines.append("本维四项均用**相对自身历史**的分位/相对量打分（非绝对高低）："
                 "成交额看相对量、融资看5日变化率、南向看5日累计、恒科看20日相对强弱。")

    if dim_meta.get('insufficient_data'):
        lines.append(f"⚠️ 有效项不足（{dim_meta.get('valid_count')}/{dim_meta.get('required_count')}），"
                     "本维置灰，不计入 IAS。")
    return ''.join(lines)


def _dim_commentary_fxExternal(indicators: dict, dim_meta: dict) -> str:
    """💱 汇率与外部板块解读（P1-8DIM 新增）"""
    dim_score = dim_meta.get('score', 0)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    cnh = get_indicator(indicators, 'usdcnh')
    dollar = get_indicator(indicators, 'dollarIndex')
    credit = get_indicator(indicators, 'creditSpread')
    b10y = get_indicator(indicators, 'usBond10Y')

    lines = []
    lines.append(f"汇率与外部板块评分**{dim_score:+.2f}**（{signal_label}）。")

    cnh_v = cnh.get('value')
    if cnh_v is not None:
        zone = ('人民币偏强（<7.05）' if cnh_v < 7.05 else
                '人民币中性（7.05~7.20）' if cnh_v < 7.20 else
                '人民币偏弱（7.20~7.35）' if cnh_v < 7.35 else
                '人民币明显承压（≥7.35）')
        lines.append(f"美元兑离岸人民币{value_str(cnh, 4)}，{zone}。")
    else:
        lines.append("美元兑离岸人民币本轮未取到（不回退造数），本项不计分。")

    d_v = dollar.get('value')
    if d_v is not None:
        lines.append(f"美元指数{value_str(dollar)}（三货币加权代理，非 ICE DXY）{' 高位' if d_v > 100 else ' 偏弱'}。")
    cr_v = credit.get('value')
    if cr_v is not None:
        lines.append(f"中美10年利差{value_str(credit, 0)}（仅展示、不计分；美债10Y 已单列，避免同一因子计两次）"
                     f"{'，倒挂压力大。' if cr_v > 250 else '。'}")
    b10_v = b10y.get('value')
    if b10_v is not None:
        lines.append(f"美债10Y {value_str(b10y, 2)}，仍是全球资产定价锚。")

    if dim_meta.get('insufficient_data'):
        lines.append(f"⚠️ 有效项不足（{dim_meta.get('valid_count')}/{dim_meta.get('required_count')}），"
                     "本维置灰。")
    return ''.join(lines)


def _dim_commentary_riskAppetite(indicators: dict, dim_meta: dict) -> str:
    """🌍 全球风险偏好板块解读（P1-8DIM：原 sentiment 的 VIX/F&G 部分）"""
    dim_score = dim_meta.get('score', 0)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    vix = get_indicator(indicators, 'vix')
    fg = get_indicator(indicators, 'fearGreed')
    b2y = get_indicator(indicators, 'usBond2Y')
    b5y = get_indicator(indicators, 'usBond5Y')

    lines = []
    lines.append(f"全球风险偏好板块评分**{dim_score:+.2f}**（{signal_label}）。")

    vix_v = vix.get('value')
    if vix_v is not None:
        if vix_v < 15:
            lines.append(f"{short_name('vix')}{value_str(vix)}低于15，市场情绪非常平静。")
        elif vix_v < 20:
            lines.append(f"{short_name('vix')}{value_str(vix)}处于15-20常规区间，情绪正常。")
        elif vix_v < 25:
            lines.append(f"{short_name('vix')}{value_str(vix)}略高于20中性线，存在一定紧张情绪。")
        elif vix_v < 30:
            lines.append(f"{short_name('vix')}{value_str(vix)}超过25，恐慌情绪明显升温。")
        else:
            lines.append(f"{short_name('vix')}{value_str(vix)}突破30，极端恐慌。")
    else:
        lines.append(f"{short_name('vix')}暂无有效数据。")

    fg_v = fg.get('value')
    if fg_v is not None:
        lines.append(f"CNN 恐惧贪婪指数{value_str(fg)}{'（极度恐惧）' if fg_v < 25 else '（恐惧）' if fg_v < 45 else '（中性）' if fg_v < 60 else '（贪婪）'}。")

    ref = []
    if b2y.get('value') is not None:
        ref.append(f"2Y {b2y['value']:.2f}%")
    if b5y.get('value') is not None:
        ref.append(f"5Y {b5y['value']:.2f}%")
    if ref:
        lines.append(f"参考（不计分）：美债 {' / '.join(ref)}。")

    if dim_meta.get('insufficient_data'):
        lines.append(f"⚠️ 有效项不足（{dim_meta.get('valid_count')}/{dim_meta.get('required_count')}），本维置灰。")
    return ''.join(lines)


def _dim_commentary_resource(indicators: dict, dim_meta: dict) -> str:
    """🛢️ 资源与供应链板块解读"""
    dim_score = dim_meta.get('score', 0)
    cls = classify_score(dim_score)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    oil = get_indicator(indicators, 'oilPrice')
    nat_gas = get_indicator(indicators, 'naturalGas')

    lines = []
    lines.append(f"资源与供应链板块评分**{dim_score:+.2f}**（{signal_label}），是表现{'最好的板块' if dim_score > 0.2 else '偏稳的板块'}。")

    oil_v = oil.get('value')
    if oil_v is not None:
        if oil_v < 60:
            lines.append(f"WTI原油{value_str(oil)}低于60$/桶理想区间下沿，能源成本低位运行。")
        elif oil_v <= 90:
            lines.append(f"WTI原油{value_str(oil)}处于60-90$/桶理想区间内，能源成本可控。")
        elif oil_v <= 120:
            lines.append(f"WTI原油{value_str(oil)}微幅超出60-90$/桶理想区间上沿，但远未触及120$/桶危机线，预计短期震荡偏稳。")
        else:
            lines.append(f"WTI原油{value_str(oil)}突破120$/桶危机线，能源冲击风险上升。")

    ng_v = nat_gas.get('value')
    if ng_v is not None:
        if 2.5 <= ng_v <= 4.5:
            lines.append(f"天然气{value_str(nat_gas, 2)}处于2.5-4.5$/MMBtu的理想区间内，供应端无压力。")
        elif ng_v < 2.5:
            lines.append(f"天然气{value_str(nat_gas, 2)}偏低，供应充裕。")
        else:
            lines.append(f"天然气{value_str(nat_gas, 2)}偏高，关注能源成本传导。")

    # ── LME铜（P1-8DIM：降为只展示参考项，与沪铜共线，不重复计分）──
    lme = get_indicator(indicators, 'lmeIndex')
    lme_v = lme.get('value')
    if lme_v is not None:
        # bidirectional: L=3000, T_low=6000, T_high=12000, H=15000（仅展示）
        if lme_v < 6000:
            lines.append(f"参考（不计分）LME铜{value_str(lme)}处于6000$/吨以下偏低区间。")
        elif lme_v <= 12000:
            lines.append(f"参考（不计分）LME铜{value_str(lme)}处于6000-12000$/吨合理区间。")
        else:
            lines.append(f"参考（不计分）LME铜{value_str(lme)}高于12000$/吨，铜价偏热。")

    # ── 沪铜期货 ──
    sh_copper = get_indicator(indicators, 'shanghaiCopper')
    sh_v = sh_copper.get('value')
    if sh_v is not None:
        # bidirectional: L=40000, T_low=55000, T_high=75000, H=90000
        if sh_v < 40000:
            lines.append(f"沪铜{value_str(sh_copper)}处于40000¥/吨以下极低位，需求疲软。")
        elif sh_v <= 55000:
            lines.append(f"沪铜{value_str(sh_copper)}处于40000-55000¥/吨偏低区间，等待需求回暖。")
        elif sh_v <= 75000:
            lines.append(f"沪铜{value_str(sh_copper)}处于55000-75000¥/吨理想区间内，国内市场供需均衡。")
        elif sh_v <= 90000:
            lines.append(f"沪铜{value_str(sh_copper)}处于75000-90000¥/吨偏高区间，铜价上行压力显现。")
        else:
            lines.append(f"沪铜{value_str(sh_copper)}突破90000¥/吨高位，国内铜价过热，需关注下游企业成本压力及政策调控动向。")

    lines.append("LME 铜仅作参考展示（与沪铜共线，避免重复计分）；碳价已归入「科技与绿色」维度。")

    lines.append("整体资源端未构成系统性风险，但对油价上行通道需保持关注。" if oil_v is None or oil_v <= 90 else "整体资源端构成一定压力，需持续监控。")

    return ''.join(lines)


def _dim_commentary_techGreen(indicators: dict, dim_meta: dict) -> str:
    """🌱 科技与绿色板块解读"""
    dim_score = dim_meta.get('score', 0)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    ai = get_indicator(indicators, 'aiGrowth')
    robot = get_indicator(indicators, 'robotInstall')
    ev = get_indicator(indicators, 'evPenetration')
    energy_idx = get_indicator(indicators, 'renewEnergyInvest')

    lines = []
    lines.append(f"科技与绿色板块评分**{dim_score:+.2f}**（{signal_label}），结构分化明显。")

    # 新能源 - 大概率是亮点
    ev_v = ev.get('value')
    if ev_v is not None:
        if ev_v >= 40:
            lines.append(f"新能源渗透率{value_str(ev)}已{'远超' if ev_v >= 50 else '超过'}40% target，处于{'全球领先水平，是最大亮点' if ev_v >= 50 else '领先水平'}。")
        else:
            lines.append(f"新能源渗透率{value_str(ev)}低于40% target，仍有提升空间。")
    else:
        lines.append("新能源渗透率数据暂缺。")

    idx_v = energy_idx.get('value')
    if idx_v is not None:
        if idx_v < 1200:
            lines.append(f"但新能源指数仅{value_str(energy_idx, 0)}低于1200点target，资本市场定价与产业现实存在脱节。")
        else:
            lines.append(f"新能源指数{value_str(energy_idx, 0)}达到1200点target，市场定价合理。")

    # 碳价（P1-8DIM：从 resource 迁入，作为本维第三个计分项）
    carbon = get_indicator(indicators, 'carbonPrice')
    cb_v = carbon.get('value')
    if cb_v is not None:
        lines.append(f"碳价{value_str(carbon)}，"
                     f"{'高于90的H值，碳市场定价机制运转良好' if cb_v > 90 else '在合理区间'}。")
    else:
        lines.append("碳价数据暂缺（本维仅 3 个计分项，需全部有效，缺失将导致整维置灰）。")

    # 科技（P1-8DIM：两项降为只展示参考项，不计入本维平均）
    tech_parts = []
    ai_v = ai.get('value')
    if ai_v is not None:
        tech_parts.append(f"{short_name('aiGrowth')}{value_str(ai)}")
    robot_v = robot.get('value')
    if robot_v is not None:
        tech_parts.append(f"{short_name('robotInstall')}{value_str(robot)}")
    if tech_parts:
        lines.append("参考（不计分）：" + "、".join(tech_parts) +
                     "，科技升级落地速度与政策目标的差距仍需观察。")

    lines.append("板块存在'产业热、资本冷'的结构性矛盾，值得持续关注。")

    return ''.join(lines)


# ═══════════════════════════════════════════
# IAS 整体解读
# ═══════════════════════════════════════════

def _generate_ias_summary(meta: dict, indicators: dict) -> str:
    """生成 IAS 整体解读正文"""
    ias = meta.get('ias', {})
    ias_score = ias.get('score', 0)
    signal = ias.get('signal', '持有')
    position = ias.get('position', '40-60%')
    signal_icon = ias.get('signal_icon', '➖')

    lines = []

    # 1. 总览
    lines.append(f"本期IAS综合评分**{ias_score:+.2f}**（{signal_icon}{signal}，建议仓位{position}），"
                 f"整体信号{_ias_signal_desc(signal)}。\n")

    # 2. 板块贡献分解
    dims = meta.get('dimensions', {})
    pos_dims = []
    neg_dims = []
    for dim_id in DIMENSION_ORDER:
        dim = dims.get(dim_id, {})
        s = dim.get('score', 0)
        dname = DIMENSION_META.get(dim_id, {}).get('name', dim_id)
        dicon = DIMENSION_META.get(dim_id, {}).get('icon', '')
        if s >= 0.05:
            pos_dims.append(f"{dicon}{dname}（**{s:+.2f}**）")
        elif s <= -0.05:
            neg_dims.append(f"{dicon}{dname}（**{s:+.2f}**）")

    if pos_dims:
        lines.append("、".join(pos_dims) + "是主要加分来源。")
    if neg_dims:
        lines.append("但" + "、".join(neg_dims) + "构成拖累。")
    # 找核心矛盾
    core_items = [d for d in [neg_dims[-1] if neg_dims else None, pos_dims[0] if pos_dims else None] if d]
    if core_items:
        lines.append(f"核心矛盾在于数据分化明显，多空因素并存。\n")

    # 3. 关键矛盾（提取自 indicators）
    divergences = _extract_key_divergences(indicators, meta)
    if divergences:
        lines.append(f"⚠️**关键矛盾**：{'；'.join(divergences[:2])}。\n")

    # 4. 尾部风险
    risks = _extract_key_risks(indicators, meta)
    if risks:
        lines.append(f"⚠️**尾部风险**：{'；'.join(risks[:2])}。\n")

    # 5. 策略建议
    strategy = _strategy_advice(ias, indicators, meta)
    if strategy:
        lines.append(f"{strategy}")

    return ''.join(lines)


def _ias_signal_desc(signal: str) -> str:
    """信号档位 → 一句话描述。

    P1-8DIM（2026-11-28）：旧版拿 score（量纲 Σ权重）比 2.5/1.0/-0.5/-1.5，
    与后端阈值同一个量纲 bug。现在**只认后端给的 signal 文案**（单一真源），
    本文件不再存第二张阈值表 —— 否则 threshold 一改又得改两处。
    """
    base = (signal or '').split('（')[0]
    return {
        '强烈买入': '全面向好',
        '增持': '偏积极',
        '持有': '中性偏弱，各板块分化明显',
        '减仓': '偏防御',
        '清仓/防御': '高度警惕',
        '数据不足': '数据不足，不给仓位建议',
    }.get(base, '中性偏弱，各板块分化明显')


def _strategy_advice(ias: dict, indicators: dict, meta: dict) -> str:
    """投资策略建议（P1-8DIM：改按后端 signal 分档，不再自己比 score 阈值）"""
    base = (ias.get('signal') or '持有').split('（')[0]
    position = ias.get('position') or '40-60%'
    if base in ('强烈买入', '增持'):
        return "投资策略上，IAS 信号积极，可适度增加风险敞口；结构性机会聚焦新能源与碳市场相关资产。"
    if base == '持有':
        ev = get_indicator(indicators, 'evPenetration').get('value')
        carbon = get_indicator(indicators, 'carbonPrice').get('value')
        highlights = []
        if ev is not None and ev >= 40:
            highlights.append("新能源产业链（渗透率超预期）")
        if carbon is not None and carbon >= 90:
            highlights.append("碳市场相关资产（碳价高位）")
        hl_text = ("结构性亮点在于中国" + "和".join(highlights)) if highlights else "国内宽松政策提供支撑"
        return (f"投资策略上，IAS 信号指向'持有'区间，维持{position}仓位。"
                f"{hl_text}。而美国方向需警惕利率环境偏紧对估值的压制。"
                "建议均衡配置，不过度暴露单一市场风险。")
    return "投资策略上，IAS 信号偏防御，建议适度降低风险敞口；关注防御性资产和高股息板块，等待数据改善信号。"


def _extract_key_divergences(indicators: dict, meta: dict) -> list:
    """提取关键矛盾/分化"""
    divergences = []
    cpi = get_indicator(indicators, 'cpi')
    us_cpi = get_indicator(indicators, 'usCpi')
    if cpi.get('value') is not None and us_cpi.get('value') is not None:
        cpi_v = cpi['value']
        usc_v = us_cpi['value']
        if cpi_v < 2.0 and usc_v > 3.0:
            divergences.append(f"中美通胀剪刀差：中国CPI {cpi_v}% vs 美国CPI {usc_v}%")

    ev = get_indicator(indicators, 'evPenetration')
    idx = get_indicator(indicators, 'renewEnergyInvest')
    if ev.get('value') is not None and ev['value'] >= 40 and idx.get('value') is not None and idx['value'] < 1200:
        divergences.append(f"新能源产业热但资本冷：渗透率{ev['value']}% vs 指数{idx['value']:.0f}点")

    us_gdp = get_indicator(indicators, 'usGdp')
    china_gdp = get_indicator(indicators, 'chinaGdp')
    if china_gdp.get('value') is not None and us_gdp.get('value') is not None:
        divergences.append(f"中美增长分化：中国GDP {china_gdp['value']}% vs 美国GDP {us_gdp['value']}%")

    return divergences[:3]


def _extract_key_risks(indicators: dict, meta: dict) -> list:
    """提取关键风险"""
    risks = []
    credit = get_indicator(indicators, 'creditSpread')
    if credit.get('value') is not None and credit['value'] > 250:
        risks.append(f"中美利差{credit['value']}bp持续扩大，人民币承压")

    vix_risk = get_indicator(indicators, 'vix')
    if vix_risk.get('value') is not None and vix_risk['value'] > 25:
        risks.append(f"{short_name('vix')}{vix_risk['value']:.1f}超过25，市场风险溢价攀升")

    # Fed rate risk
    fed = get_indicator(indicators, 'fedRate')
    us_cpi = get_indicator(indicators, 'usCpi')
    if fed.get('value') is not None and fed['value'] >= 3.5 and us_cpi.get('value') is not None and us_cpi['value'] > 3.5:
        risks.append(f"美国高利率高通胀组合压制风险资产估值")

    # Oil risk
    oil = get_indicator(indicators, 'oilPrice')
    if oil.get('value') is not None and oil['value'] > 110:
        risks.append(f"油价突破110$/桶，输入性通胀风险上升")

    return risks[:3]


def _extract_highlights(dim_id: str, indicators: dict) -> list:
    """提取板块关键指标快照（前端高亮展示用）"""
    indicator_keys = DIMENSION_INDICATORS.get(dim_id, [])
    highlights = []
    for key in indicator_keys:
        ind = get_indicator(indicators, key)
        if ind.get('value') is not None:
            # 生成一段简短 key 说明
            unit = ind.get('unit', '')
            name = INDICATOR_SHORT.get(key, key)
            country = INDICATOR_COUNTRY.get(key, '')
            highlights.append({
                'indicator': key,
                'value': ind['value'],
                'unit': unit,
                'key': f"{country}{name}",
            })
    return highlights


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

def generate_commentary(
    indicators: dict,        # 来自 scoring.build_indicators_and_meta 的 indicators
    meta: dict,              # 来自 scoring.build_indicators_and_meta 的 meta
    prev_commentary: Optional[dict] = None  # 上一轮评论（可选，暂未使用）
) -> dict:
    """
    生成完整的数据解读评论

    Args:
        indicators: 指标数据 { key: {value, score, signal, unit, ...} }
        meta: 维度评分 + IAS { ias: {...}, dimensions: {...} }
        prev_commentary: 上一轮 commentary 数据（可选），预留用于对比

    Returns:
        commentary dict（符合第7节定义的数据结构）
    """
    dims = meta.get('dimensions', {})
    ias = meta.get('ias', {'score': 0, 'signal': '持有', 'position': '40-60%', 'signal_icon': '➖'})

    # 维度解读
    dimension_commentary = {}
    for dim_id in DIMENSION_ORDER:
        dim = dims.get(dim_id, {})
        # 根据 dim_id 调用对应的解读函数
        func_name = f'_dim_commentary_{dim_id}'
        func = globals().get(func_name)
        if func:
            commentary_text = func(indicators, dim)
        else:
            commentary_text = f"该板块暂无详细解读。"

        highlights = _extract_highlights(dim_id, indicators)
        dimension_commentary[dim_id] = {
            'score': dim.get('score', 0),
            'signal': dim.get('signal', 'gray'),
            'commentary': commentary_text,
            'highlights': highlights,
        }

    # IAS 整体解读
    ias_summary = _generate_ias_summary(meta, indicators)
    divergences = _extract_key_divergences(indicators, meta)
    risks = _extract_key_risks(indicators, meta)

    # 构建输出
    now = datetime.now().isoformat()
    result = {
        'version': '1.0',
        'generatedAt': now,
        'dataTimestamp': now,
        'ias': {
            'score': ias.get('score', 0),
            'signal': ias.get('signal', '持有'),
            'summary': ias_summary,
            'keyDivergences': divergences,
            'keyRisks': risks,
        },
        'dimensions': dimension_commentary,
    }

    return result


def load_prev_commentary(filepath: Optional[Path] = None, workspace: Optional[Path] = None) -> Optional[dict]:
    """加载上一轮评论数据（用于对比）"""
    if filepath is None and workspace is not None:
        filepath = workspace / 'public' / 'data' / 'commentary.json'
    if filepath and filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════
# 自测试
# ═══════════════════════════════════════════

if __name__ == '__main__':
    # 简单测试：尝试加载近期的 market-data.json 并生成长评论
    script_dir = Path(__file__).parent
    workspace = script_dir.parent
    data_file = workspace / 'public' / 'data' / 'market-data.json'

    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            market_data = json.load(f)

        indicators = market_data.get('indicators', {})
        meta = market_data.get('meta', {})

        prev = load_prev_commentary(workspace=workspace)
        commentary = generate_commentary(indicators, meta, prev)

        out_path = workspace / 'public' / 'data' / 'commentary.json'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # strict 写入：NaN/Inf → null，绝不产出非法 JSON
        write_json_strict(out_path, commentary)

        print(f"✅ 评论已生成: {out_path}")
        print(f"   版本: {commentary['version']}")
        print(f"   时间: {commentary['generatedAt']}")
        print(f"\n{'='*60}")
        print("IAS 整体解读:")
        print(f"{'='*60}")
        print(commentary['ias']['summary'])
        print()
        for dim_id in DIMENSION_ORDER:
            dc = commentary['dimensions'].get(dim_id, {})
            dm = DIMENSION_META.get(dim_id, {})
            print(f"\n{dm.get('icon', '')} {dm.get('name', dim_id)} ({dc.get('score', 0):+.2f})")
            print("-" * 40)
            print(dc.get('commentary', ''))
    else:
        print(f"⚠️ 未找到 market-data.json: {data_file}")
        print("请先运行 fetch_worldos_data.py 生成数据后，再运行此测试。")
