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
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

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

# ═══════════════════════════════════════════
# 响应速度标注（WorldOS V1a，2026-11-27）
# ═══════════════════════════════════════════
# 目的：回答「这条数据多快能反映市场变化」。frequency 只说明更新周期，
# **不等于可用延迟**——两融是日频，但 T+1 才披露（当日盘后只出到前一交易日）。
# 因此：
#   1) 默认按 frequency → 标签映射（日频=T+0，月频=月，季频=季）；
#   2) 指标可用 `responsiveness` 显式覆盖（仅在实测披露节奏与频率不符时才允许）。
# 维度卡片取该维度内「最慢」的那一项标注（最慢决定这一维最早何时能拐头），
# 明细则进 tooltip。判定顺序见 RESPONSIVENESS_ORDER。
RESPONSIVENESS_BY_FREQUENCY = {
    'daily': 'T+0',
    'monthly': '月',
    'quarterly': '季',
    'yearly': '年',
    'other': '—',
}
RESPONSIVENESS_ORDER = ('T+0', 'T+1', '月', '季', '年', '—')

# ═══════════════════════════════════════════
# pct_rank 打分（V1b-1，2026-11-28）
# ═══════════════════════════════════════════
# 为何用分位而不是三段线性：新指标没有历史标定过的 L/T/H 拐点，拍数字＝制造
# 看起来精确的假结论。分位只回答「今天这项在自家历史上处于什么位置」，
# 不声称知道绝对好坏 ---- 不知道就不装知道。
#
# 规则（龙六规格 / PM 2026-11-28 确认）：
#   pct_rank = (lt + 0.5*eq) / n，样本**恒不含今日**
#   score    = 2*pct_rank − 1（3 位小数，走 q()）
#   ≥60 有效观测 → S = 0.4*S20 + 0.6*S60；20~59 → 仅 S20（window_effective=20）
#   <20  → warmup=true, score=null（宁可不给分，不给瞎分）
#   pct ∈ {0,1} → saturated=true（极值），值仍要给，但要显式标\\"已到历史极值\\"
PCT_RANK_WINDOW_SHORT = 20
PCT_RANK_WINDOW_LONG = 60
PCT_RANK_MIN_SAMPLES = 20
PCT_RANK_W_SHORT = 0.4
PCT_RANK_W_LONG = 0.6

# 可用 transform（在打分时才应用；历史序列里恒存 raw）
PCT_TRANSFORMS = ('raw', 'delta5', 'sum5')

# polarity 枚举：决定「分位/相对量 → 方向」怎么映射。必须是配置字段，不许硬编码分支，
# 否则龙六改判时得改代码（PM 2026-11-28 明确要求）。
#   risk_appetite : 越高越好（线性分位）——marginBalance / southboundNet / hstechMomentum
#   growth_proxy  : 越高越好但**过热转负/钝化**——ashareTurnover 走该档（配 ratio_band）
POLARITIES = ('risk_appetite', 'growth_proxy')

# ── ratio_band（相对量分段打分，V1b-1b 龙六规格）──
# r = 今日值 / mean(前 N 个交易日)（不含今日）。分段线性 + 过热段线性衰减：
#   r ≤ 0.60        → -1.000（地量冰点）
#   0.60 < r ≤ 1.00 → -1.0 → +0.6（线性）
#   1.00 < r ≤ 1.60 → +0.6 → +0.8（线性）
#   r > 1.60        → +0.8 - 2.0×(r-1.60)，地板 0（过热只钝化，**不转负**）
# 龙六原话：“过热只钝化，不转负”——所以尾段斜率虽然为负，但有 0 底。
RATIO_MA_WINDOW = 120
RATIO_BAND_KNOTS = ((0.60, -1.0), (1.00, 0.6), (1.60, 0.8))
RATIO_BAND_LOW_VALUE = -1.0        # r ≤ 第一拐点
RATIO_BAND_POST_SLOPE = -2.0       # 过热段斜率
RATIO_BAND_POST_FLOOR = 0.0        # 过热段地板（不转负）

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
        'name': 'VIX恐慌指数', 'short': 'VIX',
        'source': 'CBOE波动率指数(官方日线)', 'country': '🇺🇸', 'unit': '', 'frequency': 'daily',
        'caliberNote': 'CBOE 官方 VIX 收盘价（VIX_History.csv），FRED VIXCLS 兜底；非沪深300 QVIX',
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
        # P1-8DIM：降级为 riskAppetite 的只展示参考项（避免与 fedRate、期限结构重复计入）
        'reference_only': True,
    },
    'usBond5Y': {
        'name': '美债5年收益率', 'short': '美债5Y',
        'source': 'akshare-中美债券', 'country': '🇺🇸', 'unit': '%', 'frequency': 'daily',
        'caliberNote': '美国5年期国债到期收益率',
        # P1-8DIM：降级为 riskAppetite 的只展示参考项
        'reference_only': True,
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
    # ── A股/港股情绪代理（WorldOS V1a，2026-11-27）────────────────────
    # 动因：sentiment 维度原本只有 CBOE VIX + CNN F&G 两个美股指标，
    # 11-27 A股上证 +3.73%/创业板 +11.61%/涨停 1487 家，却输出「减仓」——
    # 因为「市场情绪」里一个 A股/港股指标都没有。
    # V1a 阶段：只采集 + 只展示，**不打分**（reference_only=True），
    # 待龙六给出字段级打分规则（V1b）后再转正；转正时撤掉 market_mismatch 折半。
    'ashareTurnover': {
        'name': '两市成交额', 'short': '两市成交额',
        'source': '腾讯行情-沪深交易所', 'country': '🇨🇳', 'unit': '亿元', 'frequency': 'daily',
        'caliberNote': '上证(000001)+深证(399001)成交额之和；源字段单位为万元，此处已÷1e4 换算成亿元。盘中为当时点快照，收盘后为全日值。打分用相对量 r=今日/前120日均值（见 r_value/ma120_base）',
        # ── V1b-1 转正（2026-11-28）：pct_rank 打分 ──
        # V1b-1b（2026-11-28 龙六改裁）：成交额不分位，改**相对量** r
        #   r = 今日成交额 / mean(前 120 个交易日成交额)（不含今日）
        #   注：同一规则 MA60 给 +0.658 / MA120 给 +0.234 / MA250 给 +0.047
        #       —— 换窗口等于换规则，断点必须重标，不允许"随便换个均值"。
        'scoring_method': 'ratio_band',
        'transform': 'ratio_ma120',
        'polarity': 'growth_proxy',
        'reference_only': False,
    },
    'marginBalance': {
        'name': '两融余额', 'short': '两融余额',
        'source': '东方财富-沪深交易所', 'country': '🇨🇳', 'unit': '亿元', 'frequency': 'daily',
        # 日频但 T+1 披露（实测：11-27 晚间最新仅到 11-26），故显式覆盖默认映射。
        'responsiveness': 'T+1',
        'caliberNote': '**只打融资余额**（RPTA_RZRQ_LSHJ.RZYE，源为元、已÷1e8 换算亿元）。融资=杠杆做多意愿，融券=反向，两者性质不同、混在一起会互相稀释，故不合并；含融券的两融余额(marginTotal)仅放 extras 参考、不参与打分。T+1 披露',
        'scoring_method': 'pct_rank',
        'transform': 'delta5',            # 5 日变化率(%)，不是余额本身
        'polarity': 'risk_appetite',
        'reference_only': False,
    },
    'southboundNet': {
        'name': '南向净买入', 'short': '南向净买入',
        'source': '东方财富-港交所', 'country': '🇨🇳', 'unit': '亿元', 'frequency': 'daily',
        'caliberNote': '港股通(沪 MUTUAL_TYPE=004 + 深 MUTUAL_TYPE=006)两路净买入相加（源为百万元、已÷100 换算亿元）；正值=资金南下净买入。extras 分列 shNet/szNet/total',
        'scoring_method': 'pct_rank',
        'transform': 'sum5',              # 5 日累计净买入(亿元)
        'polarity': 'risk_appetite',
        'reference_only': False,
    },
    'hstechMomentum': {
        'name': '恒生科技动量', 'short': '恒科动量',
        'source': '东方财富-恒生指数公司', 'country': '🇨🇳', 'unit': '百分点', 'frequency': 'daily',
        'caliberNote': '恒生科技相对上证的 20 日相对强弱(百分点) = (HSTECH_t/HSTECH_t-20−1)×100 − (SH000001_t/SH000001_t-20−1)×100，两边均取东财日线同日期收盘；指数点位放 extras.indexLevel(点)，不参与打分。编制方为恒生指数公司（港交所仅交易场所）',
        'scoring_method': 'pct_rank',
        'transform': 'raw',
        'polarity': 'risk_appetite',
        'reference_only': False,
    },

    # ── 新增（P1-8DIM，2026-11-28）：USDCNH ─────────────────────────
    # A2（2026-11-28）重标：数据源改 akshare 东财**日线** forex_hist_em（带真实交易日），
    # 打分从「固定水位 7.05/7.20/7.35」改为「相对 120 个交易日移动均值的偏离」。
    # 旧水位是 7.2 时代遗物：现价 6.65 恒 <7.05 → 永久 +0.5 常数，等于给 fxExternal
    # 灌了一个永远看多人民币的偏置（与 11-27 认定要修的「越阈值后永久 +1」同病）。
    # 取数优先级：akshare 日线 → exchangerate-api 在岸 CNY（回退时 caliberNote 标注）→ None。
    'usdcnh': {
        'name': '美元兑离岸人民币', 'short': 'USDCNH',
        'source': 'akshare-东财离岸人民币日线（forex_hist_em USDCNH）',
        'country': '🌐', 'unit': '', 'frequency': 'daily',
        # 日线带真实交易日：不再标 realtime（前端按交易日 + 时效计算新鲜度）。
        'dateSource': 'daily',
        'caliberNote': ('离岸人民币日线收盘；ratio = USDCNH / MA120（120 个交易日收盘均值，含当日），'
                        '人民币越弱（ratio 越高）分越低；历史不足 120 日不出分'),
        'scoring_method': 'ratio_ma_steps',
        # 5 档对称阶跃（零值区 ±0.5%，满档 ±1.5%）；边界一律「≤ 上界归本档」：
        #   ratio ≤0.985 → +1.0；≤0.995 → +0.5；≤1.005 → 0；≤1.015 → −0.5；>1.015 → −1.0
        'ratio_ma_window': 120,
        'ratio_steps': (0.985, 0.995, 1.005, 1.015),
        'ratio_values': (1.0, 0.5, 0.0, -0.5, -1.0),
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
        'source': 'policyuncertainty.com-BakerBloomDavis', 'country': '🌐', 'unit': '', 'frequency': 'monthly',
        'caliberNote': '中国EPU指数（Baker-Bloom-Davis 官方站原始月度数），月度、滞后约 1 个月、参考项不参与 IAS 评分',
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
        # P1-8DIM：去共线 —— 与沪铜同向，降级为 resource 的只展示参考项
        'reference_only': True,
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
        'caliberNote': '6 项：中美 GDP + 中美 PMI + 用电量 + 非农（均按三段线性 breakpoint 打分）',
    },
    {
        'id': 'inflation', 'name': '通胀与政策', 'icon': '💰', 'weight': 1.0,
        'indicators': ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate'],
        'caliberNote': '5 项：中美 CPI + 核心PCE + PPI + 联邦基金利率',
    },
    {
        # P1-8DIM：**保留 id 不变**（避免历史序列 key 断裂），只改 name 与成员。
        # 移出 dollarIndex / creditSpread / usBond2Y / usBond5Y / usBond10Y。
        'id': 'liquidity', 'name': '流动性（国内）', 'icon': '💧', 'weight': 0.8,
        'indicators': ['lpr', 'dr007', 'm2'],
        'caliberNote': '仅国内 3 项（LPR / DR007 / M2）。T4：n≤3 要求全部有效，任一缺失整维置灰（0.8 权重归零）',
    },
    {
        # 新维度：汇率与外部（usdcnh 新增。4 项 → 最小有效数 max(2, ceil(4*0.5)) = 2，
        # usdcnh 取不到时维度仍可出分）。
        'id': 'fxExternal', 'name': '汇率与外部', 'icon': '💱', 'weight': 0.7,
        'indicators': ['usdcnh', 'dollarIndex', 'creditSpread', 'usBond10Y'],
        'caliberNote': 'USDCNH（离岸日线，按相对 120 日均值打分；缺失按 3/4 有效出分）+ 美元指数（三货币加权代理）+ 中美10Y利差 + 美债10Y；4 项需 ≥2 有效',
    },
    {
        # 原 sentiment 拆分：4 个 A股/港股代理独立成 sentimentA（0.9），
        # 老板 46% 仓位在港股 → 这是关键维度。旧 id 'sentiment' 已消失。
        'id': 'sentimentA', 'name': 'A股/港股情绪', 'icon': '🧠', 'weight': 0.9,
        'indicators': ['ashareTurnover', 'marginBalance', 'southboundNet', 'hstechMomentum'],
        'caliberNote': '4 项 A股/港股情绪代理：两市成交额(ratio_band) + 融资余额/南向净买入/恒科动量(pct_rank)',
    },
    {
        # 原 sentiment 的 VIX + F&G 缩编为本维度；美债 2Y/5Y 只展示不打分。
        'id': 'riskAppetite', 'name': '全球风险偏好', 'icon': '🌍', 'weight': 0.4,
        'indicators': ['vix', 'fearGreed'],
        'reference_indicators': ['usBond2Y', 'usBond5Y'],
        'caliberNote': 'VIX + CNN F&G 打分；美债2Y/5Y 仅展示（避免与 fedRate、期限结构重复计入）',
    },
    {
        # 去共线：lmeIndex 降 reference_only（与沪铜同向），carbonPrice 移入 techGreen 打分。
        'id': 'resource', 'name': '资源与供应链', 'icon': '🛢️', 'weight': 0.5,
        'indicators': ['oilPrice', 'naturalGas', 'shanghaiCopper'],
        'reference_indicators': ['lmeIndex'],
        'caliberNote': 'WTI 原油 + 天然气 + 沪铜打分；LME 铜仅展示（与沪铜共线）',
    },
    {
        # aiGrowth / robotInstall 保持 reference_only 现状（不顺手转正），移出计分分母。
        'id': 'techGreen', 'name': '科技与绿色', 'icon': '🌱', 'weight': 0.3,
        'indicators': ['evPenetration', 'renewEnergyInvest', 'carbonPrice'],
        'reference_indicators': ['aiGrowth', 'robotInstall'],
        'caliberNote': '新能源渗透率 + 新能源指数 + 碳价打分；AI/机器人代理仅展示',
    },
]

# IAS 信号阈值（P1-8DIM 2026-11-28：量纲统一为 **normalized**，比较一律用 ias.normalized）
#
# 旧 bug：内部拿 score（量纲 Σ权重=4.6）去比 -0.5，却对外发 normalized，
# 真实分界漂到 normalized −0.109。现在阈值在 normalized 空间恒定，缩放 IAS_SCALE 不再改信号含义：
#   旧 score 2.5 → /4.6 = 0.5435 → 0.543；1.0 → 0.2174 → 0.217；
#   −0.5 → −0.1087 → −0.109；−1.5 → −0.3261 → −0.326（half-up 3 位）。
IAS_THRESHOLD_SPACE = 'normalized'
IAS_THRESHOLDS = [
    (0.543,  '强烈买入', '80-100%', '🚀'),
    (0.217,  '增持',     '60-80%',  '✅'),
    (-0.109, '持有',     '40-60%',  '➖'),
    (-0.326, '减仓',     '20-40%',  '⚠️'),
]
IAS_POSITION_ERROR = ('清仓/防御', '0-20%', '🛑')
IAS_MIN_COVERAGE = 0.6      # data_coverage 低于此值 → 不给仓位建议
IAS_PARTIAL_COVERAGE = 0.8  # 0.6~0.8 → 出分但信号标注「部分维度缺失·参考」

# 综合分标尺：等于设计权重总和（今日 1.0+1.0+0.8+0.7+0.9+0.4+0.5+0.3 = 5.6）。
# 必须派生，不能硬编码 —— 硬编码的常数会变成僵尸常数，
# 阈值语义被悄悄改掉而没人知道（P1-8DIM 就是被这个坑咬过一次：4.6 写死、阈值按 score 比）。
# 现在**信号阈值在 normalized 空间**（见 IAS_THRESHOLDS），IAS_SCALE 只影响展示用 score 的量纲。
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
# pct_rank 打分配置（单一真源；scoring 只读这份，不许在 scoring 里再写一份）
PCT_RANK_CONFIG = {
    k: {
        'method': v.get('scoring_method', 'breakpoint'),
        'transform': v.get('transform', 'raw'),
        'polarity': v.get('polarity', 'risk_appetite'),
    }
    for k, v in INDICATORS.items()
    if v.get('scoring_method') == 'pct_rank'
}
# ratio_band 打分配置（目前只有 ashareTurnover）
RATIO_BAND_CONFIG = {
    k: {
        'method': 'ratio_band',
        'transform': v.get('transform', 'ratio_ma120'),
        'polarity': v.get('polarity', 'growth_proxy'),
        'window': RATIO_MA_WINDOW,
    }
    for k, v in INDICATORS.items()
    if v.get('scoring_method') == 'ratio_band'
}
# breakpoint_steps（四段阶跃）：A2 后 usdcnh 已改 ratio_ma_steps，本配置目前为空。
# 保留派生逻辑（而非删除）：将来若又有“固定水位阶梯”类指标可复用；
# 但 usdcnh **不得**再回到固定水位——旧水位 7.05/7.20/7.35 在 6.65 报价下恒为 +0.5。
# 语义：steps=(x1,x2,x3)，values=(v0,v1,v2,v3)，x < x1 → v0；…；x ≥ x3 → v3
BREAKPOINT_STEPS_CONFIG = {
    k: {
        'method': 'breakpoint_steps',
        'steps': tuple(v['breakpoint_steps']),
        'values': tuple(v['breakpoint_values']),
    }
    for k, v in INDICATORS.items()
    if v.get('scoring_method') == 'breakpoint_steps'
}

# ratio_ma_steps（相对 120 日均值的 5 档阶跃，A2 2026-11-28）：目前只有 usdcnh。
# ratio = 最新收盘 / MA(window)；MA 窗口取**含当日**的最近 window 个有效交易日收盘。
# 边界语义：ratio ≤ steps[0] → values[0]；…；ratio > steps[-1] → values[-1]。
# 方向：ratio 越高 = 人民币越弱 = 越差（values 递减）。
RATIO_MA_STEPS_CONFIG = {
    k: {
        'method': 'ratio_ma_steps',
        'window': int(v['ratio_ma_window']),
        'steps': tuple(v['ratio_steps']),
        'values': tuple(v['ratio_values']),
    }
    for k, v in INDICATORS.items()
    if v.get('scoring_method') == 'ratio_ma_steps'
}

# 所有「需要历史样本」的量化指标配置汇总（pct_rank + ratio_band + ratio_ma_steps）。
# fetch 用 QUANTILE_CONFIG 决定「哪些指标要写 series / 挂 history」。
QUANTILE_CONFIG = {**PCT_RANK_CONFIG, **RATIO_BAND_CONFIG, **RATIO_MA_STEPS_CONFIG}

# ── D7（龙五 2026-11-28）：口径降级 → 不给分 ─────────────────────────────
# 这些指标一旦 fetch 层报告 sourceDegraded（本次用了非主源/代理口径，如 usdcnh
# 回退 exchangerate-api 在岸 CNY），值只作展示，score 必须为 None：
#   在岸/离岸价差 0.1~0.3% 会让 ratio 长期慢漂，拿代理冒充真值 = 假结论。
# 消费方：scoring.build_indicators_and_meta。判据只认 fetch 已有的
# `sourceDegraded` / `caliberNoteSuffix`，不新增并行的降级标记。
NO_SCORE_WHEN_SOURCE_DEGRADED = {'usdcnh'}

INDICATOR_DIMENSION = {}
for _dim in DIMENSIONS:
    for _key in list(_dim['indicators']) + list(_dim.get('reference_indicators', [])):
        INDICATOR_DIMENSION[_key] = _dim['id']

# 兼容旧 import：scoring.DIMENSION_CONFIG
DIMENSION_CONFIG = [
    {
        'id': d['id'], 'name': d['name'], 'icon': d['icon'],
        'weight': d['weight'], 'indicators': list(d['indicators']),
        # 权重修正声明必须一起带过去，否则 scoring 拿不到 market_mismatch（曾漏过一次）
        'market_mismatch': d.get('market_mismatch', 1.0),
        # V1b-1：mismatch 已撤时这里是 None（不是空字符串）——「没有限制」与「限制为空」必须可区分
        'mismatch_reason': d.get('mismatch_reason'),
        # V1a：维度级口径说明（前端卡片副标题/tooltip），指标级在 INDICATORS[*].caliberNote
        'caliberNote': d.get('caliberNote', ''),
        # V1a：只展示不打分的参考项（不进分母、不参平均），前端渲染用这个列表
        'reference_indicators': list(d.get('reference_indicators', [])),
        'display_indicators': list(d['indicators']) + list(d.get('reference_indicators', [])),
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
      2. 市场错配折半（声明式）：维度可声明 market_mismatch 系数（默认 1.0）。
         P1-8DIM（2026-11-28）后已无维度使用该系数（原 sentiment 已拆分），
         但保留机制：下一轮若再出现「维度成员与目标市场不匹配」仍需声明式降权。

    2026-11-27 V1a 注记（**故意不改**本函数口径）：
      V1a 要往 sentiment 挂 4 个 reference_only 展示项。若把它们塞进 dim['indicators']，
      本函数会把它们算进分母 → shrink 1.0→0.333、有效权重 0.4→0.133，
      等于「只加展示项却偷改权重」。故 V1a 采用 reference_indicators（独立展示列），
      dim['indicators'] 一律保持「计分成员」语义不变，权重逐位零漂移。

    2026-11-28 P1-8DIM：上述「遗留不一致」（techGreen 的 aiGrowth/robotInstall 是
      reference_only 却仍在 indicators 里 → shrink=2/4）已修正：
      两项移到 reference_indicators，indicators 只留 3 个真计分项 → shrink=1.0。

    Returns: {design, effective, shrink, mismatch, reason, active_count, design_count,
              display_count}
    """
    design = dim['weight']
    display_count = len(dim['indicators']) + len(dim.get('reference_indicators', []))
    design_count = len(dim['indicators'])                                       # 仅计分成员（保持原口径）
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
        'display_count': display_count,
        'reason': '；'.join(reasons) if reasons else '满额',
    }


def responsiveness_of(key: str) -> str:
    """指标响应速度标签：显式覆盖 > frequency 映射。"""
    m = INDICATORS.get(key, {})
    override = m.get('responsiveness')
    if override:
        return override
    return RESPONSIVENESS_BY_FREQUENCY.get(m.get('frequency', 'other'), '—')


def dimension_responsiveness(dim: dict) -> dict:
    """维度响应速度：取该维最慢的一项（最慢决定这维最早何时能拐头）+ 明细。

    reference_only 的参考项**不参与**「最慢」判定（它不影响评分结论），
    但明细里仍然列出来并标 ref，方便前端在 tooltip 里说明。
    """
    detail = [
        {'key': k, 'label': responsiveness_of(k), 'reference_only': is_reference_only(k)}
        for k in list(dim['indicators']) + list(dim.get('reference_indicators', []))
    ]
    scoring_labels = [d['label'] for d in detail if not d['reference_only']] or [d['label'] for d in detail]
    known = [l for l in scoring_labels if l in RESPONSIVENESS_ORDER and l != '—']
    slowest = max(known, key=RESPONSIVENESS_ORDER.index) if known else '—'
    # 参考项里若有比计分项更慢的，单独提示（避免「标 T+0 却挂着月频参考项」被忽略）
    ref_known = [d['label'] for d in detail if d['reference_only'] and d['label'] != '—']
    slowest_ref = max(ref_known, key=RESPONSIVENESS_ORDER.index) if ref_known else None
    return {'slowest': slowest, 'slowest_reference': slowest_ref, 'detail': detail}


def q(x, n: int = 2):
    """定点舍入：half-up-away-from-zero（T15-1）。

    禁用裸 round()：Python 的 round 是 banker's rounding（.5 取决于奇偶），
    且 float 是二进制无法精确表示 0.07335 —— 在「恰好平局」时结果不可预期。
    实测案例：-0.2934 / 4.0 = -0.07335，裸 round(x,4) 给 -0.0733 或 -0.0734 取决于实现路径，
    测试与实现各得一个值，谁都没错 —— 因为规则不存在。

    全仓只此一份，scoring / 测试一律 import，禁止第二次自己 round。
    """
    if x is None:
        return None
    return float(Decimal(str(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def rules_snapshot() -> dict:
    """把「当天用什么规则算的」固化成可内嵌产物的快照（T14）。

    动机：阈值/权重一改，历史读数就不可比。data/history 从 2026-11-09 才开始记，
    不内嵌规则快照，三个月后手上只有一堆「分数在变但不知道按什么规则算的」文件。
    """
    return {
        'staleness_rules': {k: dict(v) for k, v in TIMELINESS_RULES.items()},
        'dimension_weights_design': {d['id']: d['weight'] for d in DIMENSIONS},
        'market_mismatch': {d['id']: d['market_mismatch']
                            for d in DIMENSIONS if d.get('market_mismatch', 1.0) != 1.0},
        'reference_only': sorted(REFERENCE_ONLY),
        'min_valid_rule': 'n>3 → max(2, ceil(n/2)); n<=3 → 全部有效; 参考项不计入分母',
        'ias_scale': IAS_SCALE,
        # P1-8DIM：阈值量纲声明（normalized）。缺了这行，第三方无法判断
        # 快照里的阈值该乘 IAS_SCALE 还是直接比 normalized。
        'ias_threshold_space': IAS_THRESHOLD_SPACE,
        'ias_thresholds': [[t, sig, pos] for t, sig, pos, _ in IAS_THRESHOLDS],
        'ias_min_coverage': IAS_MIN_COVERAGE,
        'ias_partial_coverage': IAS_PARTIAL_COVERAGE,
        'unknown_alpha': UNKNOWN_ALPHA,
    }


def canonical_rules_json(snapshot: dict) -> str:
    """rules_hash 的 canonical 形式（T15-2，公开规格）。

    任何第三方（泰斯特 / 将来的维护者 / P3 回测）必须能用这行复现同一个 hash。
    本函数是**唯一**的 canonical 定义，测试方要独立实现再比对，不许直接调本函数验自己。
    """
    return json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def compute_rules_hash(snapshot: dict = None) -> str:
    """sha256(canonical_rules_json)[:12]（T15-2）。

    两个产物 rules_hash 相同 ⇔ 规则快照逐字节相同 ⇒ 可直接横比分数。
    """
    snap = snapshot if snapshot is not None else rules_snapshot()
    return hashlib.sha256(canonical_rules_json(snap).encode('utf-8')).hexdigest()[:12]


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
        ds = days_stale(s)
        if ds is not None and ds < 0:
            ds = 0   # 未来日期（年度数据期末 12-31）按 0 处理，与 calc_timeliness 同口径
        print(f'  {s:<12} → {p["end"] if p else "解析失败"}  ({p["kind"] if p else "-"}, {ds}天前)')

# V1a：指标级响应速度查表（放文件末尾，因 responsiveness_of 定义在 helper 区）
INDICATOR_RESPONSIVENESS = {k: responsiveness_of(k) for k in INDICATORS}
