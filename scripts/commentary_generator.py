#!/usr/bin/env python3
"""
WorldOS 数据解读评论生成器 v1.0 (模板引擎)

⚠️  此文件已被 v2.0 (generate_commentary_llm.py) 替代。
    保留作为 LLM 调用失败时的 fallback 使用。
    主入口：generate_commentary_llm.py

根据评分后的 indicators 和 meta 数据，自动生成6个维度 + IAS整体解读的评论。
完全基于模板引擎，无需 LLM 或外部依赖。

输出: commentary.json (public/data/commentary.json)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── 维度排序（按权重降序，与 scoring.py DIMENSION_CONFIG 一致）───
DIMENSION_ORDER = ['economic', 'inflation', 'liquidity', 'sentiment', 'resource', 'techGreen']

DIMENSION_META = {
    'economic':  {'name': '经济增长',   'icon': '📈', 'weight': 1.0},
    'inflation': {'name': '通胀与政策', 'icon': '💰', 'weight': 1.0},
    'liquidity': {'name': '流动性',     'icon': '💧', 'weight': 0.8},
    'sentiment': {'name': '市场情绪',   'icon': '🧠', 'weight': 0.8},
    'resource':  {'name': '资源与供应链', 'icon': '🛢️', 'weight': 0.6},
    'techGreen': {'name': '科技与绿色', 'icon': '🌱', 'weight': 0.4},
}

# 每个维度包含的指标 key（与 scoring.py DIMENSION_CONFIG 保持一致）
DIMENSION_INDICATORS = {
    'economic':  ['chinaGdp', 'chinaPmi', 'usGdp', 'servicePmi', 'electricity', 'usNonFarm'],
    'inflation': ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate'],
    'liquidity': ['lpr', 'dr007', 'm2', 'creditSpread', 'dollarIndex', 'usBond2Y', 'usBond5Y', 'usBond10Y'],
    'sentiment': ['vix', 'fearGreed'],
    'resource':  ['oilPrice', 'naturalGas', 'carbonPrice', 'lmeIndex', 'shanghaiCopper'],
    'techGreen': ['aiGrowth', 'robotInstall', 'evPenetration', 'renewEnergyInvest'],
}

# 指标短名（用于评论中）
INDICATOR_SHORT = {
    'chinaGdp':       'GDP增速',
    'chinaPmi':       '制造业PMI',
    'usGdp':          'GDP增速',
    'servicePmi':     '服务业PMI',
    'electricity':    '用电量',
    'usNonFarm':      '非农就业',
    'cpi':            'CPI',
    'ppi':            'PPI',
    'usCpi':          'CPI',
    'corePce':        '核心PCE',
    'fedRate':        '联邦基金利率',
    'lpr':            'LPR利率',
    'dr007':          'DR007',
    'm2':             'M2增速',
    'creditSpread':   '信用利差',
    'dollarIndex':    '美元指数',
    'usBond2Y':       '美债2Y',
    'usBond5Y':       '美债5Y',
    'usBond10Y':      '美债10Y',
    'vix':            'VIX',
    'fearGreed':     '恐惧贪婪指数',
    'oilPrice':       'WTI原油',
    'naturalGas':     '天然气',
    'carbonPrice':    '碳价',
    'lmeIndex':       'LME铜期货',
    'shanghaiCopper': '沪铜期货',
    'aiGrowth':       'AI产业增速',
    'robotInstall':   '工业机器人增速',
    'evPenetration':  '新能源渗透率',
    'renewEnergyInvest': '新能源指数',
}

INDICATOR_COUNTRY = {
    'chinaGdp': '🇨🇳', 'chinaPmi': '🇨🇳', 'usGdp': '🇺🇸', 'servicePmi': '🇨🇳',
    'electricity': '🇨🇳', 'usNonFarm': '🇺🇸', 'cpi': '🇨🇳', 'ppi': '🇨🇳',
    'usCpi': '🇺🇸', 'corePce': '🇺🇸', 'fedRate': '🇺🇸', 'lpr': '🇨🇳',
    'dr007': '🇨🇳', 'm2': '🇨🇳', 'creditSpread': '🌐', 'dollarIndex': '🌐',
    'usBond2Y': '🇺🇸', 'usBond5Y': '🇺🇸', 'usBond10Y': '🇺🇸',
    'vix': '🇺🇸', 'fearGreed': '🌐', 'oilPrice': '🌐', 'naturalGas': '🌐',
    'carbonPrice': '🇨🇳', 'lmeIndex': '🌐', 'shanghaiCopper': '🇨🇳', 'aiGrowth': '🇨🇳', 'robotInstall': '🇨🇳',
    'evPenetration': '🇨🇳', 'renewEnergyInvest': '🇨🇳',
}


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
    """💧 流动性板块解读"""
    dim_score = dim_meta.get('score', 0)
    cls = classify_score(dim_score)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    lpr = get_indicator(indicators, 'lpr')
    dr007 = get_indicator(indicators, 'dr007')
    m2 = get_indicator(indicators, 'm2')
    credit = get_indicator(indicators, 'creditSpread')
    dollar = get_indicator(indicators, 'dollarIndex')
    b2y = get_indicator(indicators, 'usBond2Y')
    b10y = get_indicator(indicators, 'usBond10Y')

    lines = []
    cls_label = '中性偏松但结构分化明显' if abs(dim_score) < 0.2 else ('偏宽松' if dim_score > 0 else '偏紧')
    lines.append(f"流动性板块评分**{dim_score:+.2f}**（{signal_label}），{cls_label}。")

    # 国内流动性
    cn_parts = []
    lpr_v = lpr.get('value')
    dr_v = dr007.get('value')
    m2_v = m2.get('value')
    if lpr_v is not None:
        cn_parts.append(f"LPR{value_str(lpr)}{' 低于3.5% target，政策偏松' if lpr_v < 3.5 else ' 符合预期'}")
    if dr_v is not None:
        cn_parts.append(f"DR007实际成交{value_str(dr007, 2)}{' 远低于1.8%中性线' if dr_v < 1.6 else ' 在1.8%附近'}")
    if m2_v is not None:
        cn_parts.append(f"M2增速{value_str(m2)}{' 接近9% target' if abs(m2_v - 9.0) < 1.5 else ''}")
    if cn_parts:
        lines.append("国内宽松信号清晰：" + "，".join(cn_parts) + "。")

    # 利差和美元
    cross_parts = []
    cr_v = credit.get('value')
    if cr_v is not None:
        cross_parts.append(f"信用利差{value_str(credit)}{' 高于200bp中性线，中美利差倒挂压力大' if cr_v > 250 else ' 在200bp附近'}")
    d_v = dollar.get('value')
    if d_v is not None:
        cross_parts.append(f"美元指数{value_str(dollar)}{' 高位震荡' if d_v > 100 else ' 偏弱'}")
    if cross_parts:
        lines.append("跨境维度，" + "，".join(cross_parts) + "。")

    # 美债收益率曲线
    b2y_v = b2y.get('value')
    b10y_v = b10y.get('value')
    if b2y_v is not None and b10y_v is not None:
        if b10y_v > b2y_v:
            lines.append(f"美债收益率曲线正常化（10Y **{b10y_v:.2f}%** > 2Y **{b2y_v:.2f}%**），但整体高利率环境仍压制全球风险偏好。")
        else:
            lines.append(f"美债收益率曲线持续倒挂（10Y **{b10y_v:.2f}%** < 2Y **{b2y_v:.2f}%**），衰退预期未消。")
    else:
        lines.append("整体利率环境偏高，压制全球风险偏好。")

    return ''.join(lines)


def _dim_commentary_sentiment(indicators: dict, dim_meta: dict) -> str:
    """🧠 市场情绪板块解读"""
    dim_score = dim_meta.get('score', 0)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    vix = get_indicator(indicators, 'vix')
    epu = get_indicator(indicators, 'epu')

    lines = []
    lines.append(f"市场情绪板块评分**{dim_score:+.2f}**（{signal_label}），信号中性但数据源单一需谨慎解读。")

    vix_v = vix.get('value')
    if vix_v is not None:
        if vix_v < 15:
            lines.append(f"VIX指数{value_str(vix)}低于15，市场情绪非常平静。")
        elif vix_v < 20:
            lines.append(f"VIX指数{value_str(vix)}处于15-20的常规区间，市场情绪正常。")
        elif vix_v < 25:
            lines.append(f"VIX指数{value_str(vix)}略高于20的中性线，市场存在一定紧张情绪，资产定价中不可忽视隐含的风险溢价。")
        elif vix_v < 30:
            lines.append(f"VIX指数{value_str(vix)}超过25，市场恐慌情绪明显升温，需警惕地缘事件或流动性冲击的传导风险。")
        else:
            lines.append(f"VIX指数{value_str(vix)}突破30，市场处于极端恐慌状态，系统性风险显著上升。")
    else:
        lines.append("VIX指数暂无有效数据，情绪指标缺失。")

    epu_v = epu.get('value')
    if epu_v is not None:
        lines.append(f"EPU指数{value_str(epu)}，政策不确定性{'高企' if epu_v > 150 else '中等' if epu_v > 100 else '较低'}。")
    else:
        lines.append("EPU指数暂缺有效数据，情绪维度数据面偏薄，需警惕VIX未充分反映的实际风险。")

    return ''.join(lines)


def _dim_commentary_resource(indicators: dict, dim_meta: dict) -> str:
    """🛢️ 资源与供应链板块解读"""
    dim_score = dim_meta.get('score', 0)
    cls = classify_score(dim_score)
    signal_label = get_signal_label(dim_meta.get('signal', 'gray'))

    oil = get_indicator(indicators, 'oilPrice')
    nat_gas = get_indicator(indicators, 'naturalGas')
    carbon = get_indicator(indicators, 'carbonPrice')

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

    cb_v = carbon.get('value')
    if cb_v is not None:
        if cb_v > 90:
            lines.append(f"碳价{value_str(carbon)}持续高于90¥/吨H值，碳市场定价机制运转良好，绿色转型信号积极。")
        else:
            lines.append(f"碳价{value_str(carbon)}在合理区间。")

    # ── LME铜期货 ──
    lme = get_indicator(indicators, 'lmeIndex')
    lme_v = lme.get('value')
    if lme_v is not None:
        # bidirectional: L=3000, T_low=6000, T_high=12000, H=15000
        if lme_v < 3000:
            lines.append(f"LME铜{value_str(lme)}处于3000$/吨以下极低位，需求萎缩风险突出。")
        elif lme_v <= 6000:
            lines.append(f"LME铜{value_str(lme)}处于3000-6000$/吨偏低区间，关注低位修复机会。")
        elif lme_v <= 12000:
            lines.append(f"LME铜{value_str(lme)}处于6000-12000$/吨理想区间内，供需格局健康。")
        elif lme_v <= 15000:
            lines.append(f"LME铜{value_str(lme)}处于12000-15000$/吨偏高区间，铜价上行压力显现，关注下游成本传导。")
        else:
            lines.append(f"LME铜{value_str(lme)}突破15000$/吨高位，铜价过热风险上升，警惕需求抑制。")

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

    # 科技
    tech_parts = []
    ai_v = ai.get('value')
    if ai_v is not None:
        tech_parts.append(f"AI产业增速{value_str(ai)}{'低于' if ai_v < 10 else '达到'}10% target")
    robot_v = robot.get('value')
    if robot_v is not None:
        tech_parts.append(f"工业机器人增速{value_str(robot)}{'低于' if robot_v < 10 else '达到'}10% target")
    if tech_parts:
        lines.append("、".join(tech_parts) + "，科技升级实际落地速度弱于政策目标。")

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
    lines.append(f"本期IAS综合评分**{ias_score:+.2f}**（{signal_icon}{signal}，建议仓位{position}），整体信号{_ias_signal_desc(ias_score)}。\n")

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
    strategy = _strategy_advice(ias_score, indicators, meta)
    if strategy:
        lines.append(f"{strategy}")

    return ''.join(lines)


def _ias_signal_desc(score: float) -> str:
    if score >= 2.5:
        return "全面向好"
    if score >= 1.0:
        return "偏积极"
    if score >= -0.5:
        return "中性偏弱，各板块分化明显"
    if score >= -1.5:
        return "偏防御"
    return "高度警惕"


def _strategy_advice(ias_score: float, indicators: dict, meta: dict) -> str:
    """投资策略建议"""
    dims = meta.get('dimensions', {})
    if ias_score >= 0.5:
        return f"投资策略上，IAS信号积极，可适度增加风险敞口。结构性机会明确，可关注新能源和碳市场相关资产。"
    elif ias_score >= -0.5:
        # 中性策略：点出亮点和风险
        ev = get_indicator(indicators, 'evPenetration').get('value')
        carbon = get_indicator(indicators, 'carbonPrice').get('value')
        highlights = []
        if ev is not None and ev >= 40:
            highlights.append("新能源产业链（渗透率超预期）")
        if carbon is not None and carbon >= 90:
            highlights.append("碳市场相关资产（碳价创新高）")
        if highlights:
            hl_text = "结构性亮点在于中国" + "和".join(highlights)
        else:
            hl_text = "国内宽松政策提供支撑"
        return (f"投资策略上，IAS信号指向'持有'区间，维持40-60%仓位。"
                f"{hl_text}。"
                f"而美国方向需警惕利率环境持续偏紧对估值的压制。建议均衡配置，不过度暴露单一市场风险。")
    else:
        return (f"投资策略上，IAS信号偏防御，建议适度降低风险敞口。"
                f"关注防御性资产和高股息板块，等待数据改善信号。")


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
        risks.append(f"VIX指数{vix_risk['value']:.1f}超过25，市场风险溢价攀升")

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
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(commentary, f, ensure_ascii=False, indent=2)

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
