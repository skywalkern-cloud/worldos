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
from datetime import date, datetime

# ═══════════════════════════════════════════
# 时间衰减规则
# ═══════════════════════════════════════════
# yellow_days / red_days 按「数据所属期的末日」到今天的自然日计算。
# quarterly 2026-11-09 由 270 → 400（龙五拍板）：季度数据本身有发布延迟，
# 270 天会把「滞后一季」误判为红；400 天仍能抓住「滞后一年」。
TIMELINESS_RULES = {
    'daily':     {'yellow_days': 5,   'red_days': 10},
    'monthly':   {'yellow_days': 60,  'red_days': 90},
    'quarterly': {'yellow_days': 200, 'red_days': 400},
    'yearly':    {'yellow_days': 180, 'red_days': 365},
    'other':     {'yellow_days': 60,  'red_days': 90},
}

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
        'name': 'WTI原油', 'short': 'WTI原油',
        'source': 'NYMEX期货', 'country': '🌐', 'unit': '$/桶', 'frequency': 'daily',
        'caliberNote': 'WTI 近月期货结算价',
    },
    'naturalGas': {
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
IAS_MIN_COVERAGE = 0.6   # 有效权重占比低于此值 → 不给仓位建议


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

    orphans = [k for k in INDICATORS if k not in seen]
    unscored_orphans = [k for k in orphans if not is_reference_only(k)]
    if unscored_orphans:
        problems.append(f'未归属任何维度却参与打分的指标: {unscored_orphans}')
    return problems


if __name__ == '__main__':
    issues = validate_metadata()
    if issues:
        print('❌ 元数据校验失败:')
        for i in issues:
            print('  -', i)
        raise SystemExit(1)
    print(f'✅ 元数据校验通过：{len(INDICATORS)} 个指标 / {len(DIMENSIONS)} 个维度')
    samples = ['2026-Q1-Q3', '2026-Q3', '2026-11-06', '2026-10', '2026.9', '2026年09', '2026-9月', '2026']
    for s in samples:
        p = parse_period(s)
        print(f'  {s:<12} → {p["end"] if p else "解析失败"}  ({p["kind"] if p else "-"}, {days_stale(s)}天前)')
