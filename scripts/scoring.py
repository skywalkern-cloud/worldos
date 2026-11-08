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

# ── 单一真源（P0/T1）：名称/来源/国家/口径/维度/频率 全部来自 indicator_meta ──
from indicator_meta import (  # noqa: F401  (DIMENSION_CONFIG / INDICATOR_NAMES 等为向后兼容再导出)
    DIMENSION_CONFIG,
    INDICATOR_NAMES,
    INDICATOR_COUNTRY,
    INDICATOR_CALIBER,
    INDICATOR_SHORT,
    REFERENCE_ONLY,
    TIMELINESS_RULES,
    IAS_THRESHOLDS,
    IAS_POSITION_ERROR,
    IAS_MIN_COVERAGE,
    required_valid_count,
    parse_period,
    days_stale,
    is_reference_only,
    caliber_of,
)

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
    'usNonFarm':         (5, 20, 40),
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
    'usBond2Y':          (1.5, 2.5, 4.5, 6.0),
    'usBond5Y':          (1.8, 2.8, 4.8, 6.3),
    'usBond10Y':         (2.0, 3.0, 5.0, 6.5),
    'fearGreed':         (20, 40, 60, 80),
    'oilPrice':          (40, 60, 90, 120),
    'naturalGas':        (2.0, 2.5, 4.5, 7.0),
    'fedRate':           (1.0, 2.0, 4.0, 5.0),
    'lmeIndex':          (3000, 6000, 12000, 15000),
    'shanghaiCopper':    (40000, 55000, 75000, 90000),
}

# ═══════════════════════════════════════════
# 时间衰减 / 维度 / 国家 / 名称 —— 全部来自 indicator_meta（单一真源）
# 本文件不再定义这些映射，避免出现第 2/3 份真源互相覆盖。
# ═══════════════════════════════════════════


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
    """计算时间衰减因子α (0.0 ~ 1.0)

    T2 修复（2026-11-09）：
      - 统一走 indicator_meta.parse_period，按「数据所属期末日」算天数。
        旧实现在 '2026-Q1-Q3' 上取 Q1 首日（2026-01-01），311 天 > 270 红线 → α=0，
        GDP 被隐形剔除但 valid_count 仍记数。现在取 2026-09-30。
      - 期日无法解析 → α=1.0（不惩罚），但会在 dataDateISO=null 处暴露。
      - 未来日期（当年年度数据）→ 按 0 天处理。
    """
    if not data_date_str or data_date_str == '' or data_date_str == '-':
        return 1.0

    days = days_stale(data_date_str)
    if days is None:
        return 1.0          # 解析不了：不猜，不惩罚
    if days < 0:
        days = 0            # 本年累计类数据，视为最新

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
    """计算6个维度评分（T4：最小有效数 + 置灰 + 参考项排除）

    indicators: { key: {score, timeliness, reference_only, ...} }

    规则（2026-11-09 龙五拍板）：
      1. reference_only=True 的指标不参与维度平均（只看不算）。
      2. 有效 = score 非 None 且 α>0（α=0 表示数据过期，不算有效，修旧版 valid_count 虚高）。
      3. 有效数 < required_valid_count(dim) → score=None, signal='gray', insufficient_data=True。
         分数给 None 而不是 0：0 会被下游当成「中性」计入 IAS，正是我们要消灭的假信号。

    Returns: { dim_id: {score, signal, valid_count, required_count, insufficient_data,
                        reference_only_count, avg_alpha} }
    """
    dim_scores = {}
    for dim in DIMENSION_CONFIG:
        total_weighted = 0.0
        total_alpha = 0.0
        valid_count = 0
        ref_count = 0
        active_total = 0

        for key in dim['indicators']:
            ind = indicators.get(key)
            if not ind or is_reference_only(key):
                if is_reference_only(key):
                    ref_count += 1
                continue
            active_total += 1
            score_val = ind.get('score')
            alpha = ind.get('timeliness', 1.0) or 0.0
            if score_val is not None and alpha > 0:
                total_weighted += score_val * alpha
                total_alpha += alpha
                valid_count += 1

        required = required_valid_count(dim)
        insufficient = valid_count < required

        if insufficient:
            avg_score = None
            signal = 'gray'
        else:
            avg_score = round(total_weighted / total_alpha, 3)
            signal = get_signal(avg_score)

        dim_scores[dim['id']] = {
            'score': avg_score,
            'signal': signal,
            'valid_count': valid_count,
            'required_count': required,
            'active_count': active_total,
            'reference_only_count': ref_count,
            'insufficient_data': insufficient,
            'avg_alpha': round(total_alpha / valid_count, 3) if valid_count else 0.0,
        }

    return dim_scores


def calc_ias(dim_scores: dict) -> dict:
    """计算 IAS 综合评分（T3：按有效权重归一化）

    T3 修复（2026-11-09）：
      旧式 IAS = Σ score_i×w_i，max_possible 固定 4.6。
      一旦某维度「数据不足」置灰、贡献 0，IAS 就系统性向 0 漂移，
      信号自动变「持有」而页面不提示 —— 这就是「置灰反而制造新假信号」。

      新式：
        normalized = Σ(score_i×w_i) / Σ(有效维度 w_i)      ∈ [-1, 1]
        score      = normalized × Σ(全部 w_i)  = normalized × 4.6
      score 保持旧量纲，前端阈值（±2.5/1.0/-0.5/-1.5）无需重标；
      normalized 供展示与跨日对比。

      覆盖率 = Σ有效w / Σ全部w；低于 IAS_MIN_COVERAGE 不给仓位建议。
    """
    total_weighted = 0.0
    valid_weight = 0.0
    total_weight = 0.0
    counted = []
    grayed = []

    for dim in DIMENSION_CONFIG:
        ds = dim_scores.get(dim['id'], {}) or {}
        total_weight += dim['weight']
        score = ds.get('score')
        if ds.get('insufficient_data') or score is None:
            grayed.append(dim['id'])
            continue
        total_weighted += score * dim['weight']
        valid_weight += dim['weight']
        counted.append(dim['id'])

    coverage = round(valid_weight / total_weight, 3) if total_weight else 0.0

    if valid_weight <= 0:
        return {
            'score': None,
            'normalized': None,
            'max_possible': round(total_weight, 1),
            'valid_weight': 0.0,
            'data_coverage': 0.0,
            'counted_dimensions': [],
            'grayed_dimensions': grayed,
            'signal': '数据不足',
            'position': '不适用',
            'signal_icon': '⚪',
            'is_actionable': False,
        }

    normalized = round(total_weighted / valid_weight, 4)
    ias_score = round(normalized * total_weight, 2)

    if coverage < IAS_MIN_COVERAGE:
        signal, position, icon = '数据不足', '不适用', '⚪'
        actionable = False
    else:
        actionable = True
        signal, position, icon = IAS_POSITION_ERROR
        for threshold, sig, pos, ico in IAS_THRESHOLDS:
            if ias_score >= threshold:
                signal, position, icon = sig, pos, ico
                break

    return {
        'score': ias_score,
        'normalized': normalized,
        'max_possible': round(total_weight, 1),
        'valid_weight': round(valid_weight, 2),
        'data_coverage': coverage,
        'counted_dimensions': counted,
        'grayed_dimensions': grayed,
        'signal': signal,
        'position': position,
        'signal_icon': icon,
        'is_actionable': actionable,
        'note': '未回测·非投资建议',
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
        stale_days = days_stale(data_date)

        # Trend from previous data
        prev_value = None
        if prev_data and key in prev_data:
            prev_info = prev_data[key]
            if isinstance(prev_info, dict):
                prev_value = prev_info.get('value')
        trend = calc_trend(value, prev_value)

        period = parse_period(data_date)
        name = INDICATOR_NAMES.get(key, key)
        ref_only = is_reference_only(key)

        indicators[key] = {
            'value': value,
            'score': score,
            'trend': trend,
            'signal': get_signal(score) if score is not None else 'gray',
            'category': get_category(key),
            'country': INDICATOR_COUNTRY.get(key, '🌐'),
            # name 保留（旧字段合约），displayName 为同一值的显式别名，前端新代码用后者
            'name': name,
            'displayName': name,
            'shortName': INDICATOR_SHORT.get(key, name),
            'caliberNote': caliber_of(key),
            'reference_only': ref_only,
            'frequency': freq,
            'dataDate': data_date,
            'dataDateISO': period['end'].isoformat() if period else None,
            'dataDateKind': period['kind'] if period else None,
            'days_stale': stale_days,
            'source': info.get('source', ''),
            'unit': info.get('unit', ''),
            'timeliness': timeliness,
            'freshness': get_freshness_label(timeliness),
            'freshness_level': get_freshness_level(timeliness),
        }
        # fetch 阶段带入的降级痕迹（fetch 失败、用上一轮值兜底）
        if info.get('used_fallback'):
            indicators[key]['used_fallback'] = True
            indicators[key]['fetchError'] = info.get('fetchError')
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
            'score': ds.get('score'),
            'signal': ds.get('signal', 'gray'),
            'valid_count': ds.get('valid_count', 0),
            'required_count': ds.get('required_count'),
            'active_count': ds.get('active_count'),
            'reference_only_count': ds.get('reference_only_count', 0),
            'insufficient_data': ds.get('insufficient_data', False),
            'avg_alpha': ds.get('avg_alpha', 0.0),
        }

    meta = {
        'ias': ias,
        'dimensions': dimensions,
        'model': {
            'version': 'v4.2',
            'reference_only': sorted(REFERENCE_ONLY),
            'ias_formula': 'normalized = Σ(score×w)/Σ(valid_w); score = normalized × Σ(w)',
            'min_coverage': IAS_MIN_COVERAGE,
        },
    }

    return indicators, meta
