"""
WorldOS 指标元数据·单一真源 (P0 / T1)
════════════════════════════════════════════════════════════════
设计原则（2026-11-09 龙五拍板）：
  1. 一个指标的名称/来源/国家/口径/维度归属/是否参考项，全仓只在这里定义一次。
  2. fetch_worldos_data.py、scoring.py、commentary_generator.py 一律 import 本模块，
     禁止再写第二份 INDICATOR_NAMES / INDICATOR_COUNTRY / DIMENSION_CONFIG。
  3. 指标 key 永不改名（下游 API 合约），只允许改 name/source/country/caliberNote。
  4. 新增字段 caliberNote（口径说明，前端做 tooltip）与 reference_only（只展示不打分）。

数据格式约定（T2）：
  - 输出 JSON 保留原始 dataDate（人读，如 "2026-Q1-Q3"、"2026.9"），
    同时新增 dataDateISO（该数据所属期的**末日**，机器读，恒为 YYYY-MM-DD）
    与 dataDateKind（day|month|quarter|cumulative|year）。
  - 时效性（α）一律按「期末日」计算，彻底修掉 2026-Q1-Q3 被解析成 Q1 首日的 bug。
"""

import calendar
import re
from datetime import date, datetime, timedelta

# ═══════════════════════════════════════════
# 时间衰减规则
# ═══════════════════════════════════════════
# yellow_days / red_days 按「数据所属期的末日」到今天的自然日计算。
#
# quarterly（T13-3/T13-5，2026-11-09 龙五两次修正，**已冻结**）：270 → 400 → 120/240 → 120/210。
#   历史：270（原）→ 400（第一次放宽，过松）→ 120/240（收回，240 仍是拍的）→ 120/210（按发布节奏重推）。
#   推导（不许再拍数字，要动必须重新走这个推导）：
#     季末 → 首次发布约 +25 天（中/美 GDP 都在 20-30 天窗口）
#     ⇒ 「当期值」的 days_stale 上限 ≈ 115 天（下一季数据出来之前）
#     黄 = 错过 1 次发布 ≈ 115–205 天 → 取 120（下限附近，宁紧勿松）
#     红 = 错过 2 次发布 ≈ >205 天    → 取 210
#   实例：usGdp 2026-Q1 在 2026-11-09 = 223 天 ⇒ Q2/Q3 都该有了 ⇒ 🔴（不是 🟡）。
TIMELINESS_RULES = {
    'daily':     {'yellow_days': 5,   'red_days': 10},
    'monthly':   {'yellow_days': 60,  'red_days': 90},
    'quarterly': {'yellow_days': 120, 'red_days': 210},
    'yearly':    {'yellow_days': 180, 'red_days': 365},
    'other':     {'yellow_days': 60,  'red_days': 90},
}

# ═══════════════════════════════════════════
# 新鲜度状态机（T13-2：五态互斥，一态一图标，⚪ 不再一码两用）
# ═══════════════════════════════════════════
# 旧实现把「realtime（实时报价·源无日期）」和「unknown（不知道多旧）」都画成 ⚪，
# 两个语义相反的状态共用一个图标 = 又一个「看着一样其实不一样」的坑。
# 现定死：
#   🟢 fresh    有日期且未超黄线          α=1.0
#   🔵 realtime realtime=true 且无日期    α=1.0（抓取当下即最新）
#   ⚪ unknown  无日期（或解析失败）且非 realtime  α=0.5（⚠️ 待议：未知按偏旧计权，保守）
#   🟡 stale    有日期且超黄线未超红线    α=0.5
#   🔴 expired  有日期且超红线            α=0.0
UNKNOWN_ALPHA = 0.5

FRESHNESS_STATES = {
    'fresh':    {'icon': '🟢', 'alpha': 1.0, 'label': '已核验新鲜',
                 'prerequisite': '有可解析日期且未超黄线'},
    'realtime': {'icon': '🔵', 'alpha': 1.0, 'label': '实时报价',
                 'prerequisite': 'realtime=true 且无日期'},
    'unknown':  {'icon': '⚪', 'alpha': UNKNOWN_ALPHA, 'label': '时效未知',
                 'prerequisite': '无日期（或不可解析）且非 realtime'},
    'stale':    {'icon': '🟡', 'alpha': 0.5, 'label': '偏旧',
                 'prerequisite': '有日期且超黄线未超红线'},
    'expired':  {'icon': '🔴', 'alpha': 0.0, 'label': '已过期',
                 'prerequisite': '有日期且超红线'},
}

# 进 validity_report.degraded 的状态 → reason 枚举码（其余状态不算降级）
FRESHNESS_DEGRADED_REASON = {'unknown': 'no_date'}

# 前端 COUNTRY_ORDER 只认这三个值，新增国家需先扩前端映射（已与扣钉约定）
ALLOWED_COUNTRIES = ('🇨🇳', '🇺🇸', '🌐')
ALLOWED_FREQUENCIES = ('daily', 'monthly', 'quarterly', 'yearly', 'other')

# ═══════════════════════════════════════════
# 指标元数据（31 个在抓指标 = 线上口径）
# ═══════════════════════════════════════════
# name        页面展示名（前端卡片标题，来自 indicators[key].name / displayName）
# short       文字/评论里的简称（不含括号注释）
# source      数据来源（展示用，必须与实际抓取函数一致）
# country     页面分组用 emoji，值域见 ALLOWED_COUNTRIES
# unit        单位
# frequency   数据频率，决定时效性阈值
# caliberNote 口径说明（前端 tooltip / 卡片副标题）
# reference_only True = 只展示不参与打分（T4）
INDICATORS = {
    'chinaGdp': {
        'name': 'GDP增速', 'short': 'GDP增速',
        'source': '国家统计局', 'country': '🇨🇳', 'unit': '%', 'frequency': 'quarterly',
        'caliberNote': '年内累计同比（Q1-Q3 为前三季度累计，非单季）',
    },
    'chinaPmi': {
        'name': '制造业PMI', 'short': '制造业PMI',
        'source': '东方财富-国家统计局', 'country': '🇨🇳', 'unit': '', 'frequency': 'monthly',
        'caliberNote': '官方制造业采购经理指数，50 为荣枯线',
    },
    'usGdp': {
        'name': 'GDP增速', 'short': '美国GDP增速',
        'source': '东方财富-美国商务部', 'country': '🇺🇸', 'unit': '%', 'frequency': 'quarterly',
        'caliberNote': '美国实际GDP环比折年率；季频数据有 1-2 季发布延迟',
    },
    'servicePmi': {
        'name': '服务业PMI', 'short': '服务业PMI',
        'source': '东方财富-国家统计局', 'country': '🇨🇳', 'unit': '', 'frequency': 'monthly',
        'caliberNote': '官方非制造业商务活动指数，50 为荣枯线',
    },
    'usCpi': {
        'name': 'CPI', 'short': '美国CPI',
        'source': '美国劳工统计局', 'country': '🇺🇸', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '美国CPI同比（未季调）',
    },
    'corePce': {
        'name': '核心PCE', 'short': '核心PCE',
        'source': 'FRED API-美国商务部', 'country': '🇺🇸', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '美联储通胀锚，核心PCE同比',
    },
    'vix': {
        'name': '沪深300期权波动率(QVIX)', 'short': '沪深300期权波动率',
        'source': 'akshare-沪深300ETF期权波动率指数', 'country': '🇨🇳', 'unit': '', 'frequency': 'daily',
        'caliberNote': '沪深300ETF期权波动率指数(QVIX)，非CBOE VIX；阈值已按QVIX量纲校准',
    },
    'oilPrice': {
        'dateSource': 'realtime',   # 现货/场外报价，数据源不提供交易日期（禁止伪造当天）
        'name': 'WTI原油', 'short': 'WTI原油',
        'source': 'NYMEX期货', 'country': '🌐', 'unit': '$/桶', 'frequency': 'daily',
        'caliberNote': 'WTI 近月期货结算价',
    },
    'naturalGas': {
        'dateSource': 'realtime',   # 现货/场外报价，数据源不提供交易日期（禁止伪造当天）
        'name': '天然气', 'short': '天然气',
        'source': 'NYMEX期货', 'country': '🌐', 'unit': '$/MMBtu', 'frequency': 'daily',
        'caliberNote': 'Henry Hub 天然气期货',
    },
    'fedRate': {
        'name': '联邦基金利率', 'short': '联邦基金利率',
        'source': 'FOMC会议记录', 'country': '🇺🇸', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '联邦基金目标利率上限；仅 FOMC 会议日变动',
    },
    'usBond2Y': {
        'name': '美债2年收益率', 'short': '美债2Y',
        'source': 'akshare-中美债券', 'country': '🇺🇸', 'unit': '%', 'frequency': 'daily',
        'caliberNote': '美国2年期国债到期收益率',
    },
    'usBond5Y': {
        'name': '美债5年收益率', 'short': '美债5Y',
        'source': 'akshare-中美债券', 'country': '🇺🇸', 'unit': '%', 'frequency': 'daily',
        'caliberNote': '美国5年期国债到期收益率',
    },
    'usBond10Y': {
        'name': '美债10年收益率', 'short': '美债10Y',
        'source': 'akshare-中美债券', 'country': '🇺🇸', 'unit': '%', 'frequency': 'daily',
        'caliberNote': '美国10年期国债到期收益率（全球资产定价锚）',
    },
    'usNonFarm': {
        'name': '非农就业', 'short': '非农就业',
        'source': '东方财富-美国劳工部', 'country': '🇺🇸', 'unit': '万人', 'frequency': 'monthly',
        'caliberNote': '美国非农新增就业人数（万人）',
    },
    'fearGreed': {
        'name': '美股恐惧贪婪(CNN)', 'short': '美股恐惧贪婪',
        'source': 'CNN Business-Fear&Greed', 'country': '🇺🇸', 'unit': '', 'frequency': 'daily',
        'caliberNote': '美股恐惧贪婪(CNN)，非A股情绪',
    },
    'dollarIndex': {
        'name': '美元指数', 'short': '美元指数',
        'source': 'akshare-汇率加权计算', 'country': '🌐', 'unit': '', 'frequency': 'daily',
        'caliberNote': '代理指标：由 USDCNY/EURUSD/USDJPY 加权计算，非 ICE DXY 官方值',
    },
    'cpi': {
        'name': 'CPI', 'short': 'CPI',
        'source': '东方财富-国家统计局', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '中国CPI当月同比',
    },
    'ppi': {
        'name': 'PPI', 'short': 'PPI',
        'source': '东方财富-国家统计局', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '中国PPI当月同比',
    },
    'lpr': {
        'name': 'LPR利率', 'short': 'LPR利率',
        'source': '中国人民银行', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '1年期贷款市场报价利率',
    },
    'dr007': {
        'name': 'DR007', 'short': 'DR007',
        'source': '全国银行间同业拆借中心', 'country': '🇨🇳', 'unit': '%', 'frequency': 'daily',
        'caliberNote': '银行间7天质押式回购加权利率',
    },
    'm2': {
        'name': 'M2增速', 'short': 'M2增速',
        'source': '东方财富-中国人民银行', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': 'M2余额同比',
    },
    'creditSpread': {
        'name': '中美10年利差', 'short': '中美10Y利差',
        'source': 'akshare-中美国债利差', 'country': '🌐', 'unit': 'bp', 'frequency': 'daily',
        'caliberNote': '中美10年期国债收益率之差(bp)；非信用利差',
    },
    'epu': {
        'name': '经济政策不确定性', 'short': 'EPU',
        'source': 'FRED API-EPU指数', 'country': '🌐', 'unit': '', 'frequency': 'monthly',
        'caliberNote': '中国EPU指数（Baker-Bloom-Davis），非高频指标，仅作背景参考',
        # 孤儿指标：不在任何维度里（历史上就没进过打分），显式标为参考项，
        # 避免「抓了 31 个但只有 30 个在算」却看不出来。
        'reference_only': True,
    },
    'carbonPrice': {
        'name': '碳价', 'short': '碳价',
        'source': '北京碳市场', 'country': '🇨🇳', 'unit': '¥/吨', 'frequency': 'daily',
        'caliberNote': '北京碳市场配额成交价',
    },
    'electricity': {
        'name': '用电量', 'short': '用电量',
        'source': '国家能源局', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '全社会用电量当月同比',
    },
    'renewEnergyInvest': {
        'name': '新能源指数', 'short': '新能源指数',
        'source': '中证新能源指数', 'country': '🇨🇳', 'unit': '点', 'frequency': 'daily',
        'caliberNote': '中证新能源指数点位（非投资额）',
    },
    'aiGrowth': {
        'name': '第二产业用电增速(代理)', 'short': '第二产业用电增速',
        'source': '国家能源局-第二产业', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '第二产业用电量同比，制造业活动代理，参考项',
        'reference_only': True,
    },
    'robotInstall': {
        'name': '规上工业增加值(代理)', 'short': '规上工业增加值',
        'source': '东方财富-规模以上工业增加值', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '规上工业增加值同比，机器人安装代理，参考项',
        'reference_only': True,
    },
    'evPenetration': {
        'name': '新能源渗透率', 'short': '新能源渗透率',
        'source': '乘联会-CPCA', 'country': '🇨🇳', 'unit': '%', 'frequency': 'monthly',
        'caliberNote': '新能源乘用车零售渗透率',
    },
    'lmeIndex': {
        'dateSource': 'realtime',   # 现货/场外报价，数据源不提供交易日期（禁止伪造当天）
        'name': 'LME金属指数', 'short': 'LME铜',
        'source': 'LME-综合铜03', 'country': '🌐', 'unit': '$/吨', 'frequency': 'daily',
        'caliberNote': '代理指标：LME 3个月铜价，非 LME 综合金属指数',
    },
    'shanghaiCopper': {
        'name': '沪铜', 'short': '沪铜',
        'source': '上期所-新浪财经', 'country': '🇨🇳', 'unit': '¥/吨', 'frequency': 'daily',
        'caliberNote': '沪铜主力连续合约价',
    },
}


# ═══════════════════════════════════════════
# 维度定义（唯一定义处；含权重与最小有效数门槛）
# ═══════════════════════════════════════════
# 最小有效数（T4）：指标数 ≥4 时要求 max(2, ceil(n*0.5))，
# 指标数 ≤3 时要求「全部有效」。参考项（reference_only）不计入分母、不参与平均。
DIMENSIONS = [
    {
        'id': 'economic', 'name': '经济增长', 'icon': '📈', 'weight': 1.0,
        'indicators': ['chinaGdp', 'chinaPmi', 'usGdp', 'servicePmi', 'electricity', 'usNonFarm'],
    },
    {
        'id': 'inflation', 'name': '通胀与政策', 'icon': '💰', 'weight': 1.0,
        'indicators': ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate'],
    },
    {
        'id': 'liquidity', 'name': '流动性', 'icon': '💧', 'weight': 0.8,
        'indicators': ['lpr', 'dr007', 'm2', 'creditSpread', 'dollarIndex',
                       'usBond2Y', 'usBond5Y', 'usBond10Y'],
    },
    {
        'id': 'sentiment', 'name': '市场情绪', 'icon': '🧠', 'weight': 0.8,
        'indicators': ['vix', 'fearGreed'],
        # D(2026-11-09 龙五拍板)：该维度 2 项里只有 1 项是 A 股市场指标
        # （沪深300 QVIX），美股 CNN F&G 占 50%。0.8 是按「A股情绪齐备」设计的，
        # 与现构成不符 → 声明式折半到 0.4，P1 补 A 股情绪代理后移除本标记恢复。
        'market_mismatch': 0.5,
        'mismatch_reason': '2 项中仅 1 项为 A 股指标（美股 F&G 占 50%）',
    },
    {
        'id': 'resource', 'name': '资源与供应链', 'icon': '🛢️', 'weight': 0.6,
        'indicators': ['oilPrice', 'naturalGas', 'carbonPrice', 'lmeIndex', 'shanghaiCopper'],
    },
    {
        'id': 'techGreen', 'name': '科技与绿色', 'icon': '🌱', 'weight': 0.4,
        'indicators': ['aiGrowth', 'robotInstall', 'evPenetration', 'renewEnergyInvest'],
    },
]

# IAS 信号阈值（对外统一使用 ias.score，量纲 = Σ权重 = 4.6，
# 因此阈值沿用旧标定值；ias.normalized = score / 4.6 仅供展示）
IAS_THRESHOLDS = [
    (2.5,  '强烈买入', '80-100%', '🚀'),
    (1.0,  '增持',     '60-80%',  '✅'),
    (-0.5, '持有',     '40-60%',  '➖'),
    (-1.5, '减仓',     '20-40%',  '⚠️'),
]
IAS_POSITION_ERROR = ('清仓/防御', '0-20%', '🛑')
IAS_MIN_COVERAGE = 0.6      # data_coverage 低于此值 → 不给仓位建议
IAS_PARTIAL_COVERAGE = 0.8  # 0.6~0.8 → 出分但信号标注「部分维度缺失·参考」

# 综合分标尺：等于设计权重总和（今日 4.6）。
# 必须派生，不能硬编码——P1 一旦调整 design 权重（sentiment 恢复 0.8 / 新增汇率维度），
# 硬编码的 4.6 会变成僵尸常数，阈值语义被悄悄改掉而没人知道。
IAS_SCALE = round(sum(d['weight'] for d in DIMENSIONS), 2)


# ═══════════════════════════════════════════
# 派生映射（供旧代码 import，保持向后兼容）
# ═══════════════════════════════════════════
INDICATOR_NAMES = {k: v['name'] for k, v in INDICATORS.items()}
INDICATOR_SHORT = {k: v['short'] for k, v in INDICATORS.items()}
INDICATOR_COUNTRY = {k: v['country'] for k, v in INDICATORS.items()}
INDICATOR_SOURCE = {k: v['source'] for k, v in INDICATORS.items()}
INDICATOR_FREQUENCY = {k: v['frequency'] for k, v in INDICATORS.items()}
INDICATOR_UNIT = {k: v['unit'] for k, v in INDICATORS.items()}
INDICATOR_CALIBER = {k: v.get('caliberNote', '') for k, v in INDICATORS.items()}
REFERENCE_ONLY = {k for k, v in INDICATORS.items() if v.get('reference_only')}

INDICATOR_DIMENSION = {}
for _dim in DIMENSIONS:
    for _key in _dim['indicators']:
        INDICATOR_DIMENSION[_key] = _dim['id']

# 兼容旧 import：scoring.DIMENSION_CONFIG
DIMENSION_CONFIG = [
    {
        'id': d['id'], 'name': d['name'], 'icon': d['icon'],
        'weight': d['weight'], 'indicators': list(d['indicators']),
        # 权重修正声明必须一起带过去，否则 scoring 拿不到 market_mismatch（曾漏过一次）
        'market_mismatch': d.get('market_mismatch', 1.0),
        'mismatch_reason': d.get('mismatch_reason', ''),
    }
    for d in DIMENSIONS
]


# ═══════════════════════════════════════════
# 查询helper
# ═══════════════════════════════════════════

def meta(key: str) -> dict:
    return INDICATORS.get(key, {})


def display_name(key: str) -> str:
    return INDICATORS.get(key, {}).get('name', key)


def short_name(key: str) -> str:
    return INDICATORS.get(key, {}).get('short', display_name(key))


def source_of(key: str) -> str:
    return INDICATORS.get(key, {}).get('source', '')


def country_of(key: str) -> str:
    return INDICATORS.get(key, {}).get('country', '🌐')


def caliber_of(key: str) -> str:
    return INDICATORS.get(key, {}).get('caliberNote', '')


def is_reference_only(key: str) -> bool:
    return bool(INDICATORS.get(key, {}).get('reference_only', False))


def dimension_of(key: str) -> str:
    return INDICATOR_DIMENSION.get(key, 'other')


def dimension_weights(dim: dict) -> dict:
    """维度权重：设计权重 → 有效权重（可审计，不拍脑袋）

    规则（2026-11-09 龙五拍板 D 案）：
      1. 有效性收缩（自动）：w_eff = w_design × (active_count / 设计指标数)
         代理/参考项不算 active，所以剔掉它们会自动收缩权重，
         不需要为「只剩 2 个指标」单独拍一个魔法数字。
      2. 市场错配折半（声明式）：维度可声明 market_mismatch 系数（默认 1.0），
         仅 sentiment 有值 0.5，原因写进 mismatch_reason。

    Returns: {design, effective, shrink, mismatch, reason, active_count, design_count}
    """
    design = dim['weight']
    design_count = len(dim['indicators'])
    active_count = sum(1 for k in dim['indicators'] if not is_reference_only(k))
    shrink = (active_count / design_count) if design_count else 1.0
    mismatch = float(dim.get('market_mismatch', 1.0) or 1.0)
    effective = round(design * shrink * mismatch, 4)

    reasons = []
    if shrink < 1:
        reasons.append(f'有效性收缩 {active_count}/{design_count}')
    if mismatch != 1.0:
        reasons.append(f'市场错配 ×{mismatch}（{dim.get("mismatch_reason", "")}）')

    return {
        'design': design,
        'effective': effective,
        'shrink': round(shrink, 4),
        'mismatch': mismatch,
        'active_count': active_count,
        'design_count': design_count,
        'reason': '；'.join(reasons) if reasons else '满额',
    }


def required_valid_count(dim: dict) -> int:
    """维度最小有效指标数（排除参考项后的分母）。"""
    active = [k for k in dim['indicators'] if not is_reference_only(k)]
    n = len(active)
    if n <= 3:
        return n
    return max(2, (n + 1) // 2)


# ═══════════════════════════════════════════
# 期日解析（T2：修 2026-Q1-Q3 被当 Q1 首日的 bug）
# ═══════════════════════════════════════════
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_period(value):
    """把 dataDate 字符串解析成所属期区间。

    Returns: {'start': date, 'end': date, 'kind': str} 或 None
    kind ∈ day | month | quarter | cumulative | year
    解析失败返回 None（调用方应视为「未知期」，不算新鲜也不算过期）。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        d = value.date()
        return {'start': d, 'end': d, 'kind': 'day'}
    if isinstance(value, date):
        return {'start': value, 'end': value, 'kind': 'day'}
    if not isinstance(value, str):
        return None

    ds = value.strip()
    if not ds or ds in ('-', 'N/A', 'None'):
        return None
    ds = ds.replace('／', '/').replace('　', ' ')

    # 2026-11-06 / 2026/11/06 / 2026.11.06
    m = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$', ds)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return {'start': d, 'end': d, 'kind': 'day'}
        except ValueError:
            return None

    # 2026-Q1-Q3（年内累计）→ 取最后一季的季末
    m = re.match(r'^(\d{4})\s*[-–]?\s*Q([1-4])\s*[-–]\s*Q([1-4])$', ds, re.I)
    if m:
        y, q1, q2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if q1 > q2:
            q1, q2 = q2, q1
        em, ed = _QUARTER_END[q2]
        return {'start': date(y, (q1 - 1) * 3 + 1, 1), 'end': date(y, em, ed), 'kind': 'cumulative'}

    # 2026-Q3
    m = re.match(r'^(\d{4})\s*[-–]?\s*Q([1-4])$', ds, re.I)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        em, ed = _QUARTER_END[q]
        return {'start': date(y, (q - 1) * 3 + 1, 1), 'end': date(y, em, ed), 'kind': 'quarter'}

    # 2026年9月 / 2026年09
    m = re.match(r'^(\d{4})\s*年\s*(\d{1,2})\s*月?$', ds)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return {'start': date(y, mo, 1), 'end': _month_end(y, mo), 'kind': 'month'}
        return None

    # 2026-9月 / 2026.9月
    m = re.match(r'^(\d{4})\s*[-/.]\s*(\d{1,2})\s*月$', ds)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return {'start': date(y, mo, 1), 'end': _month_end(y, mo), 'kind': 'month'}
        return None

    # 2026-10 / 2026.9（月度，无日）
    m = re.match(r'^(\d{4})\s*[-/.]\s*(\d{1,2})$', ds)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return {'start': date(y, mo, 1), 'end': _month_end(y, mo), 'kind': 'month'}
        return None

    # 2026年 / 2026
    m = re.match(r'^(\d{4})\s*年?$', ds)
    if m:
        y = int(m.group(1))
        return {'start': date(y, 1, 1), 'end': date(y, 12, 31), 'kind': 'year'}

    return None


def data_date_iso(value):
    """所属期末日 ISO 字符串（YYYY-MM-DD）；解析失败返回 None。"""
    p = parse_period(value)
    return p['end'].isoformat() if p else None


def days_stale(value, today=None):
    """距期末日的自然日数；解析失败返回 None（不是 0！）。

    返回 None 的语义是「不知道有多旧」，前端必须与 0（今天刚更新）区分开。
    """
    p = parse_period(value)
    if not p:
        return None
    today = today or date.today()
    return (today - p['end']).days


def resolve_freshness(data_date_str, frequency, realtime=False,
                      used_fallback=False, today=None) -> dict:
    """时效状态的唯一判定入口（T13：五态互斥，α / 图标 / 降级原因全部从这里出）。

    旧代码分成两处判：calc_timeliness() 按日期算 α，build_indicators_and_meta() 再
    单独判断 realtime 图标 —— 两次判定 = 两个可能不一致的真源，且无日期时直接
    `return 1.0`（语义上等于「已验证新鲜」），造出无日期却 🟢 + α=1.0 的假绿灯。

    Args:
        data_date_str: 原始 dataDate（可为 None / '-' / 不可解析串）
        frequency:     daily|monthly|quarterly|yearly|other
        realtime:      数据源声明「实时报价、不提供日期」
        used_fallback: 本轮抓取失败、用的是上一轮值（必然更旧）

    Returns: {
        'state': fresh|realtime|unknown|stale|expired,
        'icon': 🟢|🔵|⚪|🟡|🔴, 'alpha': float, 'days_stale': int|None,
        'reasons': [...],    # 进 validity_report.degraded 的枚举码（no_date / used_fallback）
        'date_note': str|None,
    }
    """
    reasons = []
    ds = days_stale(data_date_str, today=today)

    if ds is None:
        if realtime and not used_fallback:
            state = 'realtime'
            date_note = '实时报价，数据源未提供日期'
        else:
            # 无日期（或不可解析）+ 非 realtime → 不知道有多旧，按「偏旧」计权
            state = 'unknown'
            date_note = '无数据所属期，时效未知'
            reasons.append(FRESHNESS_DEGRADED_REASON['unknown'])
    else:
        if ds < 0:
            ds = 0          # 本年累计类数据，视为最新
        rule = TIMELINESS_RULES.get(frequency, TIMELINESS_RULES['other'])
        if ds > rule['red_days']:
            state = 'expired'
        elif ds > rule['yellow_days']:
            state = 'stale'
        else:
            state = 'fresh'
        date_note = None

    if used_fallback:
        reasons.append('used_fallback')
        # 兜底值来自上一轮，必然更旧：α 封顶 0.5，最鲜也只能到「偏旧」
        if state == 'fresh':
            state = 'stale'

    spec = FRESHNESS_STATES[state]
    alpha = spec['alpha']
    if used_fallback:
        alpha = min(alpha, 0.5)

    return {
        'state': state,
        'icon': spec['icon'],
        'alpha': alpha,
        'days_stale': ds,
        'reasons': reasons,
        'date_note': date_note,
    }


def validate_freshness_contract(today=None) -> list:
    """T13-2 断言：五态互斥、一态一图标、α 与状态一致、无日期不得亮绿灯。

    返回问题列表（空 = 通过）。日期用「相对今天」构造，避免用例随时间腐坏。
    """
    problems = []
    icons = [s['icon'] for s in FRESHNESS_STATES.values()]
    if len(set(icons)) != len(icons):
        problems.append(f'新鲜度图标重复（一码两用）: {icons}')

    today = today or date.today()
    d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731

    # (dataDate, freq, realtime, used_fallback, 期望 state, 期望 alpha, 期望 reason)
    cases = [
        (d(1), 'daily', False, False, 'fresh', 1.0, None),
        (d(70), 'monthly', False, False, 'stale', 0.5, None),
        (d(100), 'monthly', False, False, 'expired', 0.0, None),
        (None, 'daily', True, False, 'realtime', 1.0, None),
        (None, 'daily', False, False, 'unknown', UNKNOWN_ALPHA, 'no_date'),
        ('-', 'monthly', False, False, 'unknown', UNKNOWN_ALPHA, 'no_date'),
        ('未来某天', 'monthly', False, False, 'unknown', UNKNOWN_ALPHA, 'no_date'),
        (d(1), 'daily', True, False, 'fresh', 1.0, None),        # 有日期 → realtime 标记不足为凭
        (None, 'daily', True, True, 'unknown', UNKNOWN_ALPHA, 'no_date'),  # 兜底时连 realtime 也不算
        (d(1), 'daily', False, True, 'stale', 0.5, 'used_fallback'),       # 兜底不许自证新鲜
        (d(400), 'monthly', False, True, 'expired', 0.0, 'used_fallback'),
    ]
    for dd, freq, rt, fb, want_state, want_alpha, want_reason in cases:
        got = resolve_freshness(dd, freq, realtime=rt, used_fallback=fb, today=today)
        tag = f'freshness[{dd!r},{freq},rt={rt},fb={fb}]'
        if got['state'] != want_state:
            problems.append(f'{tag}: state={got["state"]} 期望 {want_state}')
        if abs(got['alpha'] - want_alpha) > 1e-9:
            problems.append(f'{tag}: alpha={got["alpha"]} 期望 {want_alpha}')
        if want_reason and want_reason not in got['reasons']:
            problems.append(f'{tag}: reasons={got["reasons"]} 缺 {want_reason}')
        if not want_reason and got['reasons']:
            problems.append(f'{tag}: 不该带降级原因，实得 {got["reasons"]}')
        if got['icon'] != FRESHNESS_STATES[want_state]['icon']:
            problems.append(f'{tag}: icon={got["icon"]} 与状态不符')
        # 互斥：同一时刻只能命中一个状态
        hit = [k for k in FRESHNESS_STATES if k == got['state']]
        if len(hit) != 1:
            problems.append(f'{tag}: 命中状态数={len(hit)}（必须互斥）')
        # 无日期且非 realtime 绝不允许亮绿灯
        if got['days_stale'] is None and not (rt and not fb) and got['state'] in ('fresh',):
            problems.append(f'{tag}: 无日期却判 fresh（假绿灯）')
    return problems


# ═══════════════════════════════════════════
# 自检（T6 预置，泰斯特的正式用例会覆盖）
# ═══════════════════════════════════════════

def validate_metadata() -> list:
    """校验元数据自洽，返回问题列表（空 = 通过）。"""
    problems = []
    for key, info in INDICATORS.items():
        for field in ('name', 'short', 'source', 'country', 'unit', 'frequency'):
            if field not in info:
                problems.append(f'{key}: 缺字段 {field}')
        if info.get('country') not in ALLOWED_COUNTRIES:
            problems.append(f'{key}: country={info.get("country")!r} 不在 {ALLOWED_COUNTRIES}')
        if info.get('frequency') not in ALLOWED_FREQUENCIES:
            problems.append(f'{key}: frequency={info.get("frequency")!r} 不在 {ALLOWED_FREQUENCIES}')
        if not info.get('caliberNote'):
            problems.append(f'{key}: 缺 caliberNote')

    seen = {}
    for dim in DIMENSIONS:
        for key in dim['indicators']:
            if key not in INDICATORS:
                problems.append(f'维度 {dim["id"]} 引用了未定义指标 {key}')
            if key in seen:
                problems.append(f'{key} 同时出现在 {seen[key]} 和 {dim["id"]}')
            seen[key] = dim['id']
        if required_valid_count(dim) < 1:
            problems.append(f'维度 {dim["id"]} 最小有效数为 0')
        if not (0 < float(dim.get('market_mismatch', 1.0)) <= 1.0):
            problems.append(f'维度 {dim["id"]} market_mismatch 必须在 (0,1]')
        w = dimension_weights(dim)
        if not (0 < w['effective'] <= w['design']):
            problems.append(f'维度 {dim["id"]} 有效权重异常: {w}')

    # IAS_SCALE 必须等于设计权重总和
    if abs(IAS_SCALE - sum(d['weight'] for d in DIMENSIONS)) > 1e-9:
        problems.append(f'IAS_SCALE({IAS_SCALE}) != Σ设计权重({sum(d["weight"] for d in DIMENSIONS)})')
    if abs(IAS_SCALE - sum(d['weight'] for d in DIMENSION_CONFIG)) > 1e-9:
        problems.append('DIMENSION_CONFIG 与 DIMENSIONS 的权重不一致')

    orphans = [k for k in INDICATORS if k not in seen]
    unscored_orphans = [k for k in orphans if not is_reference_only(k)]
    if unscored_orphans:
        problems.append(f'未归属任何维度却参与打分的指标: {unscored_orphans}')

    # T13-2：三态（fresh / realtime / unknown）互斥、一态一图标、无日期不得亮绿灯
    problems.extend(validate_freshness_contract())
    return problems


if __name__ == '__main__':
    issues = validate_metadata()
    if issues:
        print('❌ 元数据校验失败:')
        for i in issues:
            print('  -', i)
        raise SystemExit(1)
    print(f'✅ 元数据校验通过：{len(INDICATORS)} 个指标 / {len(DIMENSIONS)} 个维度')
    print('\n维度权重（设计 → 有效）:')
    total_d = total_e = 0.0
    for d in DIMENSIONS:
        w = dimension_weights(d)
        total_d += w['design']
        total_e += w['effective']
        print(f"  {d['name']:<8} {w['design']:.2f} → {w['effective']:.2f}  "
              f"({w['active_count']}/{w['design_count']})  {w['reason']}")
    print(f"  合计     {total_d:.2f} → {total_e:.2f}")
    samples = ['2026-Q1-Q3', '2026-Q3', '2026-11-06', '2026-10', '2026.9', '2026年09', '2026-9月', '2026']
    for s in samples:
        p = parse_period(s)
        print(f'  {s:<12} → {p["end"] if p else "解析失败"}  ({p["kind"] if p else "-"}, {days_stale(s)}天前)')
