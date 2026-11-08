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
    IAS_PARTIAL_COVERAGE,
    IAS_SCALE,
    UNKNOWN_ALPHA,
    required_valid_count,
    dimension_weights,
    parse_period,
    days_stale,
    is_reference_only,
    caliber_of,
    resolve_freshness,
    FRESHNESS_STATES,
    UNKNOWN_ALPHA,
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

def calc_timeliness(data_date_str, frequency: str, realtime: bool = False,
                    used_fallback: bool = False) -> float:
    """计算时间衰减因子α (0.0 ~ 1.0)

    T13 起：本函数只是 resolve_freshness() 的薄封装，α 的唯一真源在
    indicator_meta.resolve_freshness —— 不要再在这里加第二套判定。

    历史修正：
    - T2（2026-11-09）：统一按「数据所属期末日」算天数，不再把 2026-Q1-Q3 当 Q1 首日。
    - T13-1（2026-11-09）：无日期不再 `return 1.0`。α=1.0 的语义是「已验证新鲜」，
      而没日期时我们什么都没验证过。改为 α=0.5 + state=unknown + ⚪，
      并进 validity_report.degraded(reason='no_date')。
      ⚠️ 待议：0.5 是个主动选的保守值（未知按偏旧计权），不是公理，需外部复核。
    """
    return resolve_freshness(data_date_str, frequency,
                             realtime=realtime, used_fallback=used_fallback)['alpha']


def get_freshness_label(alpha: float) -> str:
    """新鲜度图标（仅按 α 回退的兼容入口）。

    ⚠️ legacy：α=0.5 既可能是 stale(🟡) 也可能是 unknown(⚪)，光看 α 分不开。
    新代码请直接用 resolve_freshness()['icon'] / indicators[key]['freshness']。
    """
    if alpha >= 1.0:
        return FRESHNESS_STATES['fresh']['icon']
    elif alpha >= 0.5:
        return FRESHNESS_STATES['stale']['icon']
    return FRESHNESS_STATES['expired']['icon']


def get_freshness_level(alpha: float) -> str:
    """新鲜度状态（仅按 α 回退的兼容入口，无法区分 unknown / realtime）。"""
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
        alpha_sum_active = 0.0   # 含 α=0 的指标，用于「这个维度数据整体多新」
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
            if score_val is not None:
                alpha_sum_active += alpha
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

        w = dimension_weights(dim)
        dim_scores[dim['id']] = {
            'score': avg_score,
            'signal': signal,
            'valid_count': valid_count,
            'required_count': required,
            'active_count': active_total,
            'reference_only_count': ref_count,
            'insufficient_data': insufficient,
            # T14：分母用 active_count（含 α=0），否则恒等于 1.0 失去信息量。
            # 例：economic = (1.0×5 + 0.0×1)/6 ≈ 0.833 → 才回答得了「整体多新」
            'avg_alpha': round(alpha_sum_active / active_total, 3) if active_total else 0.0,
            # D 案：权重可审计（设计 → 有效 + 原因）
            'weight_design': w['design'],
            'weight_effective': w['effective'],
            'weight_reason': w['reason'],
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
    total_weight = 0.0        # Σ 有效权重
    design_weight = 0.0       # Σ 设计权重（保持 4.6，用于把 normalized 还原成旧量纲）
    counted = []
    grayed = []

    for dim in DIMENSION_CONFIG:
        ds = dim_scores.get(dim['id'], {}) or {}
        w_eff = ds.get('weight_effective')
        if w_eff is None:
            w_eff = dimension_weights(dim)['effective']
        design_weight += dim['weight']
        total_weight += w_eff
        score = ds.get('score')
        if ds.get('insufficient_data') or score is None:
            grayed.append(dim['id'])
            continue
        total_weighted += score * w_eff
        valid_weight += w_eff
        counted.append(dim['id'])

    coverage = round(valid_weight / total_weight, 3) if total_weight else 0.0

    if valid_weight <= 0:
        return {
            'score': None,
            'normalized': None,
            'max_possible': round(design_weight, 1),
            'weight_design_sum': round(design_weight, 2),
            'weight_effective_sum': round(total_weight, 2),
            'scale_coverage': 0.0,
            'ias_scale': IAS_SCALE,
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
    # score 恒按「设计权重总和(4.6)」还原，保证与历史阈值/前端分档可比的量纲；
    # 有效权重之和是 4.0（D 案收缩后），所以 normalized 才是横比用的那个数。
    if abs(design_weight - IAS_SCALE) > 1e-9:
        # 防御：设计权重总和变了却没人重标阈值
        print(f'⚠️ 设计权重总和 {design_weight} != IAS_SCALE {IAS_SCALE}，阈值可能已失真')
    ias_score = round(normalized * IAS_SCALE, 2)

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
        if coverage < IAS_PARTIAL_COVERAGE:
            # 中间档：仍然出分（部分维度缺失不等于没结论），但必须标出来
            signal = f'{signal}（部分维度缺失·参考）'

    return {
        'score': ias_score,
        'normalized': normalized,
        'max_possible': round(design_weight, 1),
        'weight_design_sum': round(design_weight, 2),
        'weight_effective_sum': round(total_weight, 2),
        # 披露用，不触发降级：有效权重是设计决定（含主动收缩），
        # 拿它降级等于重复惩罚（既收缩权重又降可信度）。
        'scale_coverage': round(total_weight / design_weight, 3) if design_weight else 0.0,
        'ias_scale': IAS_SCALE,
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

def build_degraded_items(indicators: dict) -> list:
    """从 indicators 提取降级项（T13）：单一实现，fetch 与夹具共用。

    降级 = 有值、但可信度被削了一档，包括：
      - no_date：无数据所属期且非 realtime → α=0.5、⚪（未核验不得亮绿灯）
      - used_fallback：本轮抓取失败、用上一轮值兜底 → α 封顶 0.5

    注意：它是「降级」不是「失败」。失败（无值）走 validity_report.failed。
    """
    items = []
    for key, info in indicators.items():
        reasons = info.get('degraded_reasons') or []
        if not reasons:
            continue
        for reason in reasons:
            items.append({
                'key': key,
                'displayName': info.get('displayName'),
                'source': info.get('source'),
                'reason': reason,
                'reasonText': {
                    'no_date': '无数据所属期且非实时报价，时效未知（按偏旧 α=0.5 计权）',
                    'used_fallback': '本轮抓取失败，使用上一轮值兜底（α 封顶 0.5）',
                }.get(reason, reason),
                'dataDate': info.get('dataDate'),
                'dataDateISO': info.get('dataDateISO'),
                'days_stale': info.get('days_stale'),
                'timeliness': info.get('timeliness'),
                'freshness': info.get('freshness'),
                'freshness_level': info.get('freshness_level'),
            })
    return items


def rules_snapshot() -> dict:
    """T14：把「当天用什么规则算的」内嵌进产物。

    动机：阈值/权重一改，历史读数就不可比。data/history 从 2026-11-09 才开始记，
    今天不内嵌规则快照，三个月后手上只有一堆「分数在变但不知道按什么规则算」的文件，
    P3 回测直接做不成。成本一个 dict + 一个 hash，价值是把「可复现」从人的记性
    变成数据自带。
    """
    snap = {
        'staleness_rules': {k: dict(v) for k, v in TIMELINESS_RULES.items()},
        'dimension_weights_design': {d['id']: d['weight'] for d in DIMENSION_CONFIG},
        'market_mismatch': {d['id']: d.get('market_mismatch', 1.0)
                            for d in DIMENSION_CONFIG if d.get('market_mismatch', 1.0) != 1.0},
        'reference_only': sorted(REFERENCE_ONLY),
        'min_valid_rule': 'n>3 → max(2, ceil(n/2)); n<=3 → 全部有效; 参考项不计入分母',
        'ias_scale': IAS_SCALE,
        'ias_thresholds': [[t, s_, p_] for t, s_, p_, _ in IAS_THRESHOLDS],
        'ias_min_coverage': IAS_MIN_COVERAGE,
        'ias_partial_coverage': IAS_PARTIAL_COVERAGE,
        'unknown_alpha': UNKNOWN_ALPHA,
    }
    return snap


def rules_hash() -> str:
    """规则快照的 sha256 前 12 位：两个日期的 hash 相同 = 规则未变，可直接横比。"""
    import hashlib
    import json as _json
    payload = _json.dumps(rules_snapshot(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]


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

        # 实时报价类（源不提供日期）：不伪造 dataDate，改为显式标注 dateNote。
        # T13：兜底值不享受 realtime 待遇（上一轮值必然比今天旧）。
        used_fallback = bool(info.get('used_fallback'))
        realtime = bool(info.get('realtime')) and not used_fallback

        # T13：α / 图标 / 状态 / 降级原因全部一次性从唯一真源拿，
        # 不再「先算 α 再单独判图标」（两套判定 = 两个可能不一致的口径）。
        fresh = resolve_freshness(data_date, freq, realtime=realtime,
                                  used_fallback=used_fallback)
        timeliness = fresh['alpha']
        stale_days = fresh['days_stale']

        # Trend from previous data
        prev_value = None
        if prev_data and key in prev_data:
            prev_info = prev_data[key]
            if isinstance(prev_info, dict):
                prev_value = prev_info.get('value')
        trend = calc_trend(value, prev_value)

        # 超期判定（单一份口径，前端不再抄阈值表；扣钉只需读 overdue/overdue_level）
        rule = TIMELINESS_RULES.get(freq, TIMELINESS_RULES['other'])
        if stale_days is None:
            overdue, overdue_level, days_overdue = False, 'none', None
        elif stale_days > rule['red_days']:
            overdue, overdue_level, days_overdue = True, 'red', stale_days - rule['red_days']
        elif stale_days > rule['yellow_days']:
            overdue, overdue_level, days_overdue = True, 'yellow', stale_days - rule['yellow_days']
        else:
            overdue, overdue_level, days_overdue = False, 'none', 0

        period = parse_period(data_date)
        name = INDICATOR_NAMES.get(key, key)
        ref_only = is_reference_only(key)

        # 是否进评分：参考项 / 无评分 / 过期(α=0) 三种都不进
        if ref_only:
            excluded, exclusion_reason = True, 'reference_only'
        elif score is None:
            excluded, exclusion_reason = True, 'no_score'
        elif timeliness <= 0:
            excluded, exclusion_reason = True, 'expired_alpha0'
        else:
            excluded, exclusion_reason = False, None

        # T12：参考项固定灰信号，不能显示红/黄——它根本没进结论，
        # 却给读者一个红灯，正是我们要消灭的展示层误导。
        if ref_only:
            signal = 'reference'
        elif score is not None:
            signal = get_signal(score)
        else:
            signal = 'gray'

        indicators[key] = {
            'value': value,
            'score': score,
            'trend': trend,
            'signal': signal,
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
            'overdue': overdue,
            'overdue_level': overdue_level,     # none | yellow | red
            'days_overdue': days_overdue,       # 超出对应阈值的天数；未超为 0，无日期为 null
            'staleness_rule': {'yellow_days': rule['yellow_days'], 'red_days': rule['red_days']},
            'realtime': realtime,
            'dateNote': fresh['date_note'] or info.get('dateNote') or None,
            'source': info.get('source', ''),
            'unit': info.get('unit', ''),
            'timeliness': timeliness,
            # T13：五态互斥，一态一图标 —— 🟢已核验新鲜 / 🔵实时报价 /
            # ⚪时效未知(α=0.5) / 🟡偏旧 / 🔴过期。无日期不再亮绿灯。
            'freshness': fresh['icon'],
            'freshness_level': fresh['state'],
            # 进 validity_report.degraded 的枚举码（no_date / used_fallback）
            'degraded_reasons': fresh['reasons'],
            # 是否被排除在评分之外（给前端区分「数据旧了」和「这项没进评分」）
            'excluded_from_scoring': excluded,
            'exclusion_reason': exclusion_reason,
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
            'weight': dim['weight'],                     # 兼容旧字段 = 设计权重
            'weight_design': ds.get('weight_design', dim['weight']),
            'weight_effective': ds.get('weight_effective', dim['weight']),
            'weight_reason': ds.get('weight_reason', '满额'),
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
        'rules_snapshot': rules_snapshot(),
        'rules_hash': rules_hash(),
        'model': {
            'version': 'v4.2',
            'reference_only': sorted(REFERENCE_ONLY),
            'ias_formula': 'normalized = Σ(score×w)/Σ(valid_w); score = normalized × Σ(w)',
            'min_coverage': IAS_MIN_COVERAGE,
        },
    }

    return indicators, meta
