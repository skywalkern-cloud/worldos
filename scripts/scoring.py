"""
WorldOS v4.1 连续评分模块
包含：单指标评分、时间衰减因子、维度评分、IAS综合评分

评分算法：
- 正向指标：三段线性映射 L→-1, T→0, H→+1
- 逆向指标：三段线性映射 L→+1, T→0, H→-1
- 双向指标：双三段，过低过高都降分
"""

from datetime import datetime, date
from typing import Optional

# ═══════════════════════════════════════════
# 评分参数
# ═══════════════════════════════════════════

# 正向指标：值越大越正面 (L=score:-1, T=score:0, H=score:+1)
POSITIVE_PARAMS = {
    'chinaGdp':          (3.0, 5.0, 7.0),
    'chinaPmi':          (48, 50, 53),
    'usGdp':             (-0.5, 2.5, 5.5),
    'usPmi':             (47, 50, 53),
    'euPmi':             (47, 50, 52),
    'servicePmi':        (47, 50, 53),
    'electricity':       (2.0, 5.0, 8.0),
    'ppi':               (-5.0, 0, 3.0),
    'm2':                (7.0, 9.0, 12.0),
    'northFlow':         (-100, 0, 100),
    'turnover':          (5000, 10000, 15000),
    'exportGrowth':      (-5.0, 5.0, 15.0),
    'aiGrowth':          (0, 10, 25),
    'robotInstall':      (-5.0, 10, 25),
    'evPenetration':     (20, 40, 60),
    'carbonPrice':       (30, 60, 90),
    'renewEnergyInvest': (800, 1200, 1600),
}

# 逆向指标：值越大越负面 (L=score:+1, T=score:0, H=score:-1)
NEGATIVE_PARAMS = {
    'lpr':               (2.0, 3.5, 5.0),
    'dr007':             (1.0, 1.8, 3.0),
    'creditSpread':      (100, 200, 400),
    'dollarIndex':       (92, 100, 112),
    'vix':               (12, 20, 35),
    'epu':               (80, 150, 300),
}

# 双向指标：过高过低都不好 (L_low, T_low, T_high, H_high)
BIDIRECTIONAL_PARAMS = {
    'cpi':               (0.0, 1.0, 3.0, 5.0),
    'usCpi':             (0.0, 1.5, 3.5, 5.0),
    'corePce':           (1.0, 1.5, 2.5, 3.5),
    'oilPrice':          (40, 60, 90, 120),
    'naturalGas':        (2.0, 2.5, 4.5, 7.0),
    'fedRate':           (1.0, 2.0, 4.0, 5.0),
}

# ═══════════════════════════════════════════
# 时间衰减参数
# ═══════════════════════════════════════════

TIMELINESS_RULES = {
    'daily':     {'yellow_days': 3, 'red_days': 5},
    'monthly':   {'yellow_days': 30, 'red_days': 45},
    'quarterly': {'yellow_days': 90, 'red_days': 120},
    'yearly':    {'yellow_days': 180, 'red_days': 365},
    'other':     {'yellow_days': 30, 'red_days': 45},
}

# ═══════════════════════════════════════════
# 维度映射
# ═══════════════════════════════════════════

DIMENSION_CONFIG = [
    {
        'id': 'economic',
        'name': '经济增长',
        'icon': '📈',
        'weight': 1.0,
        'indicators': ['chinaGdp', 'chinaPmi', 'usGdp', 'servicePmi', 'electricity'],
    },
    {
        'id': 'inflation',
        'name': '通胀与政策',
        'icon': '💰',
        'weight': 1.0,
        'indicators': ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate'],
    },
    {
        'id': 'liquidity',
        'name': '流动性',
        'icon': '💧',
        'weight': 0.8,
        'indicators': ['lpr', 'dr007', 'm2', 'creditSpread', 'dollarIndex'],
    },
    {
        'id': 'sentiment',
        'name': '市场情绪',
        'icon': '🧠',
        'weight': 0.8,
        'indicators': ['vix', 'epu'],
    },
    {
        'id': 'resource',
        'name': '资源与供应链',
        'icon': '🛢️',
        'weight': 0.6,
        'indicators': ['oilPrice', 'naturalGas', 'carbonPrice'],
    },
    {
        'id': 'techGreen',
        'name': '科技与绿色',
        'icon': '🌱',
        'weight': 0.4,
        'indicators': ['aiGrowth', 'robotInstall', 'evPenetration', 'renewEnergyInvest'],
    },
]

# ═══════════════════════════════════════════
# 国家映射
# ═══════════════════════════════════════════

INDICATOR_COUNTRY = {
    'chinaGdp': '🇨🇳',
    'chinaPmi': '🇨🇳',
    'usGdp': '🇺🇸',
    'usPmi': '🇺🇸',
    'euPmi': '🇪🇺',
    'servicePmi': '🇨🇳',
    'electricity': '🇨🇳',
    'cpi': '🇨🇳',
    'ppi': '🇨🇳',
    'usCpi': '🇺🇸',
    'corePce': '🇺🇸',
    'fedRate': '🇺🇸',
    'lpr': '🇨🇳',
    'dr007': '🇨🇳',
    'm2': '🇨🇳',
    'creditSpread': '🌐',
    'dollarIndex': '🌐',
    'vix': '🇺🇸',
    'northFlow': '🇨🇳',
    'turnover': '🇨🇳',
    'epu': '🌐',
    'oilPrice': '🌐',
    'naturalGas': '🌐',
    'exportGrowth': '🇨🇳',
    'bdi': '🌐',
    'aiGrowth': '🇨🇳',
    'robotInstall': '🇨🇳',
    'evPenetration': '🇨🇳',
    'carbonPrice': '🇨🇳',
    'renewEnergyInvest': '🇨🇳',
}

INDICATOR_NAMES = {
    'chinaGdp': 'GDP增速',
    'chinaPmi': '制造业PMI',
    'usGdp': 'GDP增速',
    'usPmi': 'ISM制造业PMI',
    'euPmi': '综合PMI',
    'servicePmi': '服务业PMI',
    'electricity': '用电量',
    'cpi': 'CPI',
    'ppi': 'PPI',
    'usCpi': 'CPI',
    'corePce': '核心PCE',
    'fedRate': '联邦基金利率',
    'lpr': 'LPR利率',
    'dr007': 'DR007',
    'm2': 'M2增速',
    'creditSpread': '信用利差',
    'dollarIndex': '美元指数',
    'vix': 'VIX恐慌指数',
    'northFlow': '北向资金',
    'turnover': 'A股成交额',
    'epu': '经济政策不确定性',
    'oilPrice': 'WTI原油',
    'naturalGas': '天然气',
    'exportGrowth': '出口增速',
    'bdi': 'BDI运价指数',
    'aiGrowth': 'AI产业增速',
    'robotInstall': '工业机器人',
    'evPenetration': '新能源渗透率',
    'carbonPrice': '碳价',
    'renewEnergyInvest': '新能源指数',
}


# ═══════════════════════════════════════════
# 评分函数
# ═══════════════════════════════════════════

def score_positive(value: float, L: float, T: float, H: float) -> float:
    """正向指标评分：值越大越正面"""
    if value < L:
        return -1.0
    elif value < T:
        return (value - L) / (T - L) - 1.0   # L→-1, T→0
    elif value < H:
        return (value - T) / (H - T)          # T→0, H→+1
    else:
        return 1.0


def score_negative(value: float, L: float, T: float, H: float) -> float:
    """逆向指标评分：值越大越负面"""
    if value < L:
        return 1.0
    elif value < T:
        return 1.0 - (value - L) / (T - L)   # L→+1, T→0
    elif value < H:
        return (T - value) / (H - T)          # T→0, H→-1
    else:
        return -1.0


def score_bidirectional(value: float, L_low: float, T_low: float, T_high: float, H_high: float) -> float:
    """双向指标评分：过高过低都不好"""
    if value < L_low:
        return -1.0
    elif value < T_low:
        return (value - L_low) / (T_low - L_low) - 1.0   # L_low→-1, T_low→0
    elif value <= T_high:
        return 0.0
    elif value <= H_high:
        return -(value - T_high) / (H_high - T_high)     # T_high→0, H_high→-1
    else:
        return -1.0


def calc_score(key: str, value) -> Optional[float]:
    """根据指标类型计算评分"""
    if value is None:
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None

    if key in POSITIVE_PARAMS:
        L, T, H = POSITIVE_PARAMS[key]
        return round(score_positive(v, L, T, H), 3)
    elif key in NEGATIVE_PARAMS:
        L, T, H = NEGATIVE_PARAMS[key]
        return round(score_negative(v, L, T, H), 3)
    elif key in BIDIRECTIONAL_PARAMS:
        L_low, T_low, T_high, H_high = BIDIRECTIONAL_PARAMS[key]
        return round(score_bidirectional(v, L_low, T_low, T_high, H_high), 3)

    return None


def calc_trend(value, prev_value) -> str:
    """计算趋势：'up' | 'down' | 'neutral'"""
    if value is None or prev_value is None:
        return 'neutral'
    try:
        diff = float(value) - float(prev_value)
        if diff > 0.01:
            return 'up'
        elif diff < -0.01:
            return 'down'
        return 'neutral'
    except (ValueError, TypeError):
        return 'neutral'


def get_signal(score: float) -> str:
    """根据评分值返回信号"""
    if score is None:
        return 'gray'
    if score <= -0.5:
        return 'red'
    elif score <= -0.1:
        return 'yellow'
    elif score >= 0.5:
        return 'green'
    elif score >= 0.1:
        return 'lightgreen'
    return 'gray'


def get_category(key: str) -> str:
    """根据指标名返回分类"""
    for dim in DIMENSION_CONFIG:
        if key in dim['indicators']:
            return dim['id']
    return 'other'


# ═══════════════════════════════════════════
# 时间衰减
# ═══════════════════════════════════════════

def calc_timeliness(data_date_str, frequency: str) -> float:
    """计算时间衰减因子α (0.0 ~ 1.0)"""
    if not data_date_str or data_date_str == '' or data_date_str == '-':
        return 1.0

    # Parse date
    try:
        if isinstance(data_date_str, str):
            # Try various formats: '2026-Q1', '2025-08', '2025年08月', '2026.4', '2026-05-22'
            ds = data_date_str.strip()
            # Handle '2026-Q1' format
            if 'Q' in ds.upper():
                parts = ds.split('-')
                year = int(parts[0])
                q = int(ds[ds.upper().index('Q') + 1])
                month = (q - 1) * 3 + 1  # Q1→1, Q2→4, Q3→7, Q4→10
                data_date = date(year, month, 1)
            elif '.' in ds:
                year, month = ds.split('.')
                data_date = date(int(year), int(month), 1)
            elif '年' in ds:
                import re
                m = re.match(r'(\d{4})年(\d{1,2})月', ds)
                if m:
                    data_date = date(int(m.group(1)), int(m.group(2)), 1)
                else:
                    return 1.0
            elif len(ds) == 7 and '-' in ds:
                year, month = ds.split('-')
                data_date = date(int(year), int(month), 1)
            elif len(ds) >= 10:
                data_date = datetime.strptime(ds[:10], '%Y-%m-%d').date()
            else:
                return 1.0
        else:
            return 1.0
    except (ValueError, TypeError):
        return 1.0

    days = (date.today() - data_date).days
    if days < 0:
        return 1.0  # Future data (shouldn't happen but be safe)

    rule = TIMELINESS_RULES.get(frequency, TIMELINESS_RULES['other'])
    if days > rule['red_days']:
        return 0.0
    elif days > rule['yellow_days']:
        return 0.5
    return 1.0


def get_freshness_label(alpha: float) -> str:
    """新鲜度标签"""
    if alpha >= 1.0:
        return '🟢'  # 正常
    elif alpha >= 0.5:
        return '🟡'  # 偏旧
    return '🔴'  # 过期


def get_freshness_level(alpha: float) -> str:
    if alpha >= 1.0:
        return 'fresh'
    elif alpha >= 0.5:
        return 'stale'
    return 'expired'


# ═══════════════════════════════════════════
# 维度 & IAS 评分
# ═══════════════════════════════════════════

def calc_dimension_scores(indicators: dict, raw_data: dict) -> dict:
    """
    计算6个维度评分
    indicators: { key: {score, timeliness, ...} }
    raw_data: { key: {value, ...} }

    Returns: { dim_id: {score, signal, avg_score}, ... }
    """
    dim_scores = {}
    for dim in DIMENSION_CONFIG:
        total_weighted = 0.0
        total_alpha = 0.0
        total_score = 0.0  # 用于简单平均的原始评分和
        valid_count = 0

        for key in dim['indicators']:
            ind = indicators.get(key)
            if ind and ind.get('score') is not None:
                alpha = ind.get('timeliness', 1.0)
                score_val = ind['score']
                total_weighted += score_val * alpha
                total_alpha += alpha
                total_score += score_val
                valid_count += 1

        if total_alpha > 0:
            avg_score = round(total_weighted / total_alpha, 3)
        elif valid_count > 0:
            # 所有指标都过期(α=0)时，用简单平均作为fallback
            avg_score = round(total_score / valid_count, 3)
        else:
            avg_score = 0.0

        dim_scores[dim['id']] = {
            'score': avg_score,
            'signal': get_signal(avg_score),
            'valid_count': valid_count,
        }

    return dim_scores


def calc_ias(dim_scores: dict) -> dict:
    """
    计算IAS综合评分
    IAS = Σ(i=1..6) F_i × W_i
    """
    total = 0.0
    max_possible = 0.0
    for dim in DIMENSION_CONFIG:
        ds = dim_scores.get(dim['id'], {})
        score = ds.get('score', 0.0)
        total += score * dim['weight']
        max_possible += 1.0 * dim['weight']

    ias_score = round(total, 2)

    # 信号映射
    if ias_score >= 2.5:
        signal = '强烈买入'
        position = '80-100%'
    elif ias_score >= 1.0:
        signal = '增持'
        position = '60-80%'
    elif ias_score >= -0.5:
        signal = '持有'
        position = '40-60%'
    elif ias_score >= -1.5:
        signal = '减仓'
        position = '20-40%'
    else:
        signal = '清仓/防御'
        position = '0-20%'

    return {
        'score': ias_score,
        'max_possible': round(max_possible, 1),
        'signal': signal,
        'position': position,
        'signal_icon': (
            '🚀' if ias_score >= 2.5 else
            '✅' if ias_score >= 1.0 else
            '➖' if ias_score >= -0.5 else
            '⚠️' if ias_score >= -1.5 else
            '🛑'
        ),
    }


# ═══════════════════════════════════════════
# 主入口：构建完整的 indicators & meta 输出
# ═══════════════════════════════════════════

def build_indicators_and_meta(raw_data: dict, prev_data: dict = None) -> tuple:
    """
    从原始数据构建 indicators 和 meta 对象

    raw_data: { key: {value, unit, frequency, source, dataDate} }
    prev_data: { key: {value, ...} } 用于趋势比较

    Returns: (indicators, meta)
    """
    indicators = {}
    data_values = {}  # flat { key: value } for dimension scoring

    for key, info in raw_data.items():
        if not isinstance(info, dict):
            continue

        value = info.get('value')
        if value is None:
            continue

        freq = info.get('frequency', 'monthly')
        data_date = info.get('dataDate')

        score = calc_score(key, value)
        timeliness = calc_timeliness(data_date, freq)

        # Trend from previous data
        prev_value = None
        if prev_data and key in prev_data:
            prev_info = prev_data[key]
            if isinstance(prev_info, dict):
                prev_value = prev_info.get('value')
        trend = calc_trend(value, prev_value)

        indicators[key] = {
            'value': value,
            'score': score,
            'trend': trend,
            'signal': get_signal(score) if score is not None else 'gray',
            'category': get_category(key),
            'country': INDICATOR_COUNTRY.get(key, '🌐'),
            'name': INDICATOR_NAMES.get(key, key),
            'frequency': freq,
            'dataDate': data_date,
            'source': info.get('source', ''),
            'unit': info.get('unit', ''),
            'timeliness': timeliness,
            'freshness': get_freshness_label(timeliness),
            'freshness_level': get_freshness_level(timeliness),
        }
        data_values[key] = value

    # 维度评分
    dim_scores = calc_dimension_scores(indicators, raw_data)

    # IAS
    ias = calc_ias(dim_scores)

    # Build dimension output
    dimensions = {}
    for dim in DIMENSION_CONFIG:
        ds = dim_scores.get(dim['id'], {})
        dimensions[dim['id']] = {
            'name': dim['name'],
            'icon': dim['icon'],
            'weight': dim['weight'],
            'score': ds.get('score', 0.0),
            'signal': ds.get('signal', 'gray'),
            'valid_count': ds.get('valid_count', 0),
        }

    meta = {
        'ias': ias,
        'dimensions': dimensions,
    }

    return indicators, meta
