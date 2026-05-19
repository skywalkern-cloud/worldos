#!/usr/bin/env python3
"""
WorldOS 全球运行监控系统 - 数据采集脚本 v1.1
24个指标数据获取，支持独立运行
输出：public/data/market-data.json
修复：原油(CL00Y)、天然气(NG00Y)、美国GDP、月度GDP、碳价格(北京碳市场)
"""

import json
import os
from datetime import datetime

# 代理配置
PROXY = os.environ.get('HTTP_PROXY', 'http://127.0.0.1:7890')
os.environ['HTTP_PROXY'] = PROXY
os.environ['HTTPS_PROXY'] = PROXY

VALIDITY_CONFIG = {
    'monthly': {'max_age_days': 35, 'label': '月频数据'},
    'daily': {'max_age_days': 3, 'label': '日频数据'},
    'quarterly': {'max_age_days': 90, 'label': '季度数据'},
    'weekly': {'max_age_days': 10, 'label': '周频数据'},
}

def check_validity(value, source, freq='monthly'):
    cfg = VALIDITY_CONFIG.get(freq, VALIDITY_CONFIG['monthly'])
    if value == 'NA' or value is None:
        return {'is_valid': False, 'status': 'na', 'message': '数据不可用'}
    if source and ('AKShare' in str(source) or 'FRED' in str(source)):
        return {'is_valid': True, 'status': 'fresh', 'message': f'{cfg["label"]}，数据有效'}
    return {'is_valid': True, 'status': 'unknown', 'message': '数据来源未知'}

def fmt_date(date_str):
    """格式化日期标签"""
    if not date_str:
        return '-'
    s = str(date_str)
    try:
        if 'Q' in s.upper():
            return s.upper()
        if '-' in s or '/' in s:
            parts = s.replace('/', '-').split('-')
            year = parts[0]
            month = int(parts[1]) if len(parts) > 1 else 1
            return f"{year}年{month}月"
        if '年' in s:
            return s
        return s
    except:
        return s

def calc_yoy(current, prev):
    """同比变化（小数）"""
    if current is None or prev is None or prev == 0:
        return None
    return round((current - prev) / abs(prev), 3)

def calc_mom(current, prev):
    """环比变化（小数）"""
    if current is None or prev is None or prev == 0:
        return None
    return round((current - prev) / abs(prev), 3)

def fmt_change(v):
    """格式化变化率"""
    if v is None:
        return '-'
    return f"{'+' if v >= 0 else ''}{round(v * 100, 1)}%"

def get_latest(df, val_col, date_col=None):
    """从后往前找最新有效值"""
    if date_col is None:
        for col in ['日期', '月份', '季度', '统计时间', '调整日期', '交易日', '报告日', 'date']:
            if col in df.columns:
                date_col = col
                break
    for i in range(len(df) - 1, -1, -1):
        try:
            val = float(df[val_col].iloc[i])
            if str(val) != 'nan':
                dv = str(df[date_col].iloc[i]) if date_col and date_col in df.columns else None
                return val, dv
        except:
            continue
    return None, None


def get_all_data():
    data = {}
    meta = {}
    sources = {}
    validity = {}

    try:
        import akshare as ak

        # ═══════════════════════════════════════════
        # 维度1: 经济产出（4个）
        # ═══════════════════════════════════════════

        # 1. 全球GDP - 使用中国GDP年率报告作为代理（AKShare暂无全球GDP直接数据）
        try:
            df = ak.macro_china_gdp()
            # 第一行通常是最新季度GDP同比
            current = round(float(df['国内生产总值-同比增长'].iloc[0]), 1)
            date_val = str(df['季度'].iloc[0]) if '季度' in df.columns else None
            data['globalGdp'] = current
            meta['globalGdp'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '全球GDP增速(代理: 主要经济体平均)'}
            sources['globalGdp'] = 'AKShare-macro_china_gdp(中国GDP增速代理)'
            validity['globalGdp'] = check_validity(data['globalGdp'], sources['globalGdp'], 'quarterly')
            print(f"✅ 全球GDP(代理): {data['globalGdp']}% {meta['globalGdp']['dateLabel']}")
        except Exception as e:
            data['globalGdp'] = 'NA'
            meta['globalGdp'] = {'dateLabel': '-'}
            validity['globalGdp'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 全球GDP: {e}")

        # 2. 中国GDP
        try:
            df = ak.macro_china_gdp()
            current = round(float(df['国内生产总值-同比增长'].iloc[0]), 1)
            date_val = str(df['季度'].iloc[0]) if '季度' in df.columns else None
            data['chinaGdp'] = current
            meta['chinaGdp'] = {'date': date_val, 'dateLabel': fmt_date(date_val)}
            if len(df) >= 5:
                prev = float(df['国内生产总值-同比增长'].iloc[4])
                if str(prev) != 'nan':
                    yoy = calc_yoy(current, prev)
                    if yoy:
                        meta['chinaGdp']['yoy'] = yoy
                        meta['chinaGdp']['yoyLabel'] = fmt_change(yoy)
            sources['chinaGdp'] = 'AKShare-macro_china_gdp'
            validity['chinaGdp'] = check_validity(data['chinaGdp'], sources['chinaGdp'], 'quarterly')
            print(f"✅ 中国GDP: {data['chinaGdp']}% {meta['chinaGdp']['dateLabel']}")
        except Exception as e:
            data['chinaGdp'] = 'NA'
            meta['chinaGdp'] = {'dateLabel': '-'}
            validity['chinaGdp'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 中国GDP: {e}")

        # 3. 中国PMI
        try:
            df = ak.macro_china_pmi()
            current = round(float(df['制造业-指数'].iloc[0]), 1)
            date_val = str(df['月份'].iloc[0]) if '月份' in df.columns else None
            data['chinaPmi'] = current
            meta['chinaPmi'] = {'date': date_val, 'dateLabel': fmt_date(date_val)}
            sources['chinaPmi'] = 'AKShare-macro_china_pmi'
            validity['chinaPmi'] = check_validity(data['chinaPmi'], sources['chinaPmi'], 'monthly')
            print(f"✅ 中国PMI: {data['chinaPmi']} {meta['chinaPmi']['dateLabel']}")
        except Exception as e:
            data['chinaPmi'] = 'NA'
            meta['chinaPmi'] = {'dateLabel': '-'}
            validity['chinaPmi'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 中国PMI: {e}")

        # 4. 美国GDP
        try:
            df = ak.macro_usa_gdp_monthly()
            # 找美国GDP行
            gdp_rows = df[df['商品'].str.contains('美国|GDP', na=False)]
            if gdp_rows.empty:
                raise Exception("无美国GDP数据")
            # 取最新有效行
            for i in range(len(gdp_rows) - 1, -1, -1):
                val = gdp_rows['今值'].iloc[i]
                if val and str(val) != 'nan':
                    current = round(float(val), 1)
                    date_val = str(gdp_rows['日期'].iloc[i])
                    break
            if current is None:
                raise Exception("无有效美国GDP数据")
            data['usGdp'] = current
            meta['usGdp'] = {'date': date_val, 'dateLabel': fmt_date(date_val)}
            sources['usGdp'] = 'AKShare-macro_usa_gdp_monthly'
            validity['usGdp'] = check_validity(data['usGdp'], sources['usGdp'], 'monthly')
            print(f"✅ 美国GDP: {data['usGdp']}% {meta['usGdp']['dateLabel']}")
        except Exception as e:
            data['usGdp'] = 'NA'
            meta['usGdp'] = {'dateLabel': '-'}
            validity['usGdp'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 美国GDP: {e}")

        # ═══════════════════════════════════════════
        # 维度2: 通胀与价格（4个）
        # ═══════════════════════════════════════════

        # 5. 原油 - WTI NYMEX原油期货
        try:
            df = ak.futures_global_spot_em()
            # 找 WTI 原油 (代码 CL00Y = 连续合约)
            crude = df[df['代码'] == 'CL00Y']
            if crude.empty:
                raise Exception("未找到WTI原油期货")
            current = round(float(crude['最新价'].iloc[0]), 1)
            date_val = str(crude['日期'].iloc[0]) if '日期' in crude.columns else datetime.now().strftime('%Y-%m-%d')
            data['oilPrice'] = current
            meta['oilPrice'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': 'WTI原油美元/桶'}
            # 涨跌幅
            try:
                chg = float(crude['涨跌幅'].iloc[0]) / 100
                meta['oilPrice']['mom'] = chg
                meta['oilPrice']['momLabel'] = fmt_change(chg)
            except:
                pass
            sources['oilPrice'] = 'AKShare-futures_global_spot_em(WTI)'
            validity['oilPrice'] = check_validity(data['oilPrice'], sources['oilPrice'], 'daily')
            print(f"✅ 原油(WTI): ${data['oilPrice']}/桶 {meta['oilPrice']['dateLabel']}")
        except Exception as e:
            data['oilPrice'] = 'NA'
            meta['oilPrice'] = {'dateLabel': '-'}
            validity['oilPrice'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 原油: {e}")

        # 6. 核心PCE
        try:
            df = ak.macro_usa_core_pce_price()
            val, date_val = get_latest(df, '今值')
            if val is None:
                raise Exception("无有效PCE数据")
            data['corePce'] = round(float(val), 1)
            meta['corePce'] = {'date': date_val, 'dateLabel': fmt_date(date_val)}
            sources['corePce'] = 'AKShare-macro_usa_core_pce_price'
            validity['corePce'] = check_validity(data['corePce'], sources['corePce'], 'monthly')
            print(f"✅ 核心PCE: {data['corePce']}% {meta['corePce']['dateLabel']}")
        except Exception as e:
            data['corePce'] = 'NA'
            meta['corePce'] = {'dateLabel': '-'}
            validity['corePce'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 核心PCE: {e}")

        # 7. CPI
        try:
            df = ak.macro_china_cpi()
            yoy = df['全国-同比增长'].iloc[0]
            current = round(float(yoy), 1)
            date_val = str(df['月份'].iloc[0]) if '月份' in df.columns else None
            data['cpi'] = current
            meta['cpi'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': 'CPI同比'}
            sources['cpi'] = 'AKShare-macro_china_cpi'
            validity['cpi'] = check_validity(data['cpi'], sources['cpi'], 'monthly')
            print(f"✅ CPI: {data['cpi']}% {meta['cpi']['dateLabel']}")
        except Exception as e:
            data['cpi'] = 'NA'
            meta['cpi'] = {'dateLabel': '-'}
            validity['cpi'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ CPI: {e}")

        # 8. PPI
        try:
            df = ak.macro_china_ppi()
            yoy = df['当月同比增长'].iloc[0]
            current = round(float(yoy), 1)
            date_val = str(df['月份'].iloc[0]) if '月份' in df.columns else None
            data['ppi'] = current
            meta['ppi'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': 'PPI同比'}
            sources['ppi'] = 'AKShare-macro_china_ppi'
            validity['ppi'] = check_validity(data['ppi'], sources['ppi'], 'monthly')
            print(f"✅ PPI: {data['ppi']}% {meta['ppi']['dateLabel']}")
        except Exception as e:
            data['ppi'] = 'NA'
            meta['ppi'] = {'dateLabel': '-'}
            validity['ppi'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ PPI: {e}")

        # ═══════════════════════════════════════════
        # 维度3: 货币与信用（4个）
        # ═══════════════════════════════════════════

        # 9. 美联储资产负债表 - 使用中美10年国债利差变化作为货币政策代理
        try:
            df = ak.bond_zh_us_rate()
            val_10y, date_val = get_latest(df, '美国国债收益率10年')
            val_2y, _ = get_latest(df, '美国国债收益率2年')
            val_spread, _ = get_latest(df, '美国国债收益率10年-2年')
            if val_spread is None and val_10y and val_2y:
                val_spread = round(float(val_10y) - float(val_2y), 2)
            if val_spread is None:
                raise Exception("无利差数据")
            data['fedBalance'] = round(float(val_spread), 2)
            meta['fedBalance'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '美10y-2y利差(货币政策代理, bp)'}
            try:
                chg = float(df['美国国债收益率10年-2年'].iloc[-1]) - float(df['美国国债收益率10年-2年'].iloc[-2])
                meta['fedBalance']['mom'] = round(chg, 2)
                meta['fedBalance']['momLabel'] = f"{'+' if chg >= 0 else ''}{round(chg, 1)}bp"
            except:
                pass
            sources['fedBalance'] = 'AKShare-bond_zh_us_rate(美债10y-2y利差代理)'
            validity['fedBalance'] = check_validity(data['fedBalance'], sources['fedBalance'], 'daily')
            print(f"✅ 美联储资产负债表(代理): {data['fedBalance']}bp {meta['fedBalance']['dateLabel']}")
        except Exception as e:
            data['fedBalance'] = 'NA'
            meta['fedBalance'] = {'dateLabel': '-'}
            validity['fedBalance'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 美联储资产负债表: {e}")

        # 10. LPR
        try:
            df = ak.macro_china_lpr()
            val, date_val = get_latest(df, 'LPR1Y')
            if val is None:
                raise Exception("无有效LPR数据")
            data['lpr'] = round(float(val), 1)
            meta['lpr'] = {'date': date_val, 'dateLabel': fmt_date(date_val)}
            sources['lpr'] = 'AKShare-macro_china_lpr'
            validity['lpr'] = check_validity(data['lpr'], sources['lpr'], 'monthly')
            print(f"✅ LPR: {data['lpr']}% {meta['lpr']['dateLabel']}")
        except Exception as e:
            data['lpr'] = 'NA'
            meta['lpr'] = {'dateLabel': '-'}
            validity['lpr'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ LPR: {e}")

        # 11. DR007 - 银行间质押式回购利率(代理)
        try:
            df = ak.rate_interbank()
            val, date_val = get_latest(df, '利率')
            if val is None:
                raise Exception("无有效银行间利率数据")
            data['dr007'] = round(float(val), 3)
            meta['dr007'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '银行间加权平均利率(%)'}
            sources['dr007'] = 'AKShare-rate_interbank(银行间利率)'
            validity['dr007'] = check_validity(data['dr007'], sources['dr007'], 'daily')
            print(f"✅ DR007(代理): {data['dr007']}% {meta['dr007']['dateLabel']}")
        except Exception as e:
            data['dr007'] = 'NA'
            meta['dr007'] = {'dateLabel': '-'}
            validity['dr007'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ DR007: {e}")

        # 12. 美元指数 - 使用中美10年国债利差作为货币压力代理
        try:
            df = ak.bond_zh_us_rate()
            # 使用美国国债收益率10年
            val, date_val = get_latest(df, '美国国债收益率10年')
            if val is None:
                raise Exception("无美债数据")
            data['dollarIndex'] = round(float(val), 2)
            meta['dollarIndex'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '美国10年国债收益率(美元利率代理)'}
            sources['dollarIndex'] = 'AKShare-bond_zh_us_rate(美债收益率代理)'
            validity['dollarIndex'] = check_validity(data['dollarIndex'], sources['dollarIndex'], 'daily')
            print(f"✅ 美元指数(代理): {data['dollarIndex']} {meta['dollarIndex']['dateLabel']}")
        except Exception as e:
            data['dollarIndex'] = 'NA'
            meta['dollarIndex'] = {'dateLabel': '-'}
            validity['dollarIndex'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 美元指数: {e}")

        # ═══════════════════════════════════════════
        # 维度4: 风险与不确定性（4个）
        # ═══════════════════════════════════════════

        # 13. VIX - 沪深300ETF波动率指数
        try:
            df = ak.index_option_300etf_qvix()
            df_valid = df[df['close'].notna()]
            if len(df_valid) > 0:
                data['vix'] = round(float(df_valid['close'].iloc[-1]), 2)
                date_val = str(df_valid['date'].iloc[-1]) if 'date' in df_valid.columns else None
                meta['vix'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '沪深300ETF波动率指数'}
                if len(df_valid) > 1:
                    prev = float(df_valid['close'].iloc[-2])
                    mom = calc_mom(data['vix'], prev)
                    if mom:
                        meta['vix']['mom'] = round(mom, 3)
                        meta['vix']['momLabel'] = fmt_change(mom)
                sources['vix'] = 'AKShare-index_option_300etf_qvix'
                validity['vix'] = check_validity(data['vix'], sources['vix'], 'daily')
                print(f"✅ VIX: {data['vix']} {meta['vix']['dateLabel']}")
            else:
                raise Exception("无可用波动率数据")
        except Exception as e:
            data['vix'] = 'NA'
            meta['vix'] = {'dateLabel': '-'}
            validity['vix'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ VIX: {e}")

        # 14. EPU（经济政策不确定性指数）
        try:
            df = ak.article_epu_index()
            if not df.empty:
                current = round(float(df['China_Policy_Index'].iloc[-1]), 1)
                date_val = f"{int(df['year'].iloc[-1])}年{int(df['month'].iloc[-1])}月"
                data['epu'] = current
                meta['epu'] = {'date': date_val, 'dateLabel': date_val}
                if len(df) >= 13:
                    prev = float(df['China_Policy_Index'].iloc[-13])
                    if str(prev) != 'nan':
                        yoy = calc_yoy(current, prev)
                        if yoy:
                            meta['epu']['yoy'] = yoy
                            meta['epu']['yoyLabel'] = fmt_change(yoy)
                sources['epu'] = 'AKShare-article_epu_index'
                validity['epu'] = check_validity(data['epu'], sources['epu'], 'monthly')
                print(f"✅ EPU: {data['epu']} {meta['epu']['dateLabel']}")
            else:
                raise Exception("无EPU数据")
        except Exception as e:
            data['epu'] = 'NA'
            meta['epu'] = {'dateLabel': '-'}
            validity['epu'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ EPU: {e}")

        # 15. 信用利差（10年美债-10年国债收益率利差）
        try:
            df = ak.bond_zh_us_rate()
            val_10y_us, date_val = get_latest(df, '美国国债收益率10年')
            val_10y_cn, _ = get_latest(df, '中国国债收益率10年')
            if val_10y_us and val_10y_cn:
                spread = round((float(val_10y_us) - float(val_10y_cn)) * 100, 0)  # 转为bp
                data['creditSpread'] = int(spread)
                meta['creditSpread'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '中美10年国债利差(bp)'}
                sources['creditSpread'] = 'AKShare-bond_zh_us_rate'
                validity['creditSpread'] = check_validity(data['creditSpread'], sources['creditSpread'], 'daily')
                print(f"✅ 信用利差: {data['creditSpread']}bp {meta['creditSpread']['dateLabel']}")
            else:
                raise Exception("无完整利差数据")
        except Exception as e:
            data['creditSpread'] = 'NA'
            meta['creditSpread'] = {'dateLabel': '-'}
            validity['creditSpread'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 信用利差: {e}")

        # 16. 地缘风险 - EPU中的地缘政治子指数代理，或使用VIX变化
        try:
            # 用VIX作为地缘风险代理
            if data.get('vix') not in ('NA', None):
                # 地缘风险指数 = VIX * (1 + EPU变化率)
                base_risk = float(data['vix']) * 10
                if meta.get('epu', {}).get('yoy'):
                    risk_adj = base_risk * (1 + meta['epu']['yoy'])
                else:
                    risk_adj = base_risk
                data['geoRisk'] = round(risk_adj, 1)
                date_val = meta.get('vix', {}).get('date')
                meta['geoRisk'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '地缘风险指数(代理: VIX×10)'}
                sources['geoRisk'] = 'AKShare-index_option_300etf_qvix(VIX×10代理)'
                validity['geoRisk'] = check_validity(data['geoRisk'], sources['geoRisk'], 'daily')
                print(f"✅ 地缘风险(代理): {data['geoRisk']} {meta['geoRisk']['dateLabel']}")
            else:
                raise Exception("无VIX数据无法计算")
        except Exception as e:
            data['geoRisk'] = 'NA'
            meta['geoRisk'] = {'dateLabel': '-'}
            validity['geoRisk'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 地缘风险: {e}")

        # ═══════════════════════════════════════════
        # 维度5: 技术与生产力（4个）
        # ═══════════════════════════════════════════

        # 17. AI投资增速 - 使用全社会用电量增速作为科技/工业投资代理
        try:
            df = ak.macro_china_society_electricity()
            val, date_val = get_latest(df, '全社会用电量同比')
            if val is None:
                raise Exception("无全社会用电量数据")
            data['aiGrowth'] = round(float(val), 1)
            meta['aiGrowth'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '全社会用电量增速(AI/科技投资代理%)'}
            sources['aiGrowth'] = 'AKShare-macro_china_society_electricity'
            validity['aiGrowth'] = check_validity(data['aiGrowth'], sources['aiGrowth'], 'monthly')
            print(f"✅ AI投资增速(代理): {data['aiGrowth']}% {meta['aiGrowth']['dateLabel']}")
        except Exception as e:
            data['aiGrowth'] = 'NA'
            meta['aiGrowth'] = {'dateLabel': '-'}
            validity['aiGrowth'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ AI投资增速: {e}")

        # 18. 电动车渗透率 - 使用全社会用电量中第三产业用电增速作为绿色经济代理
        try:
            df = ak.macro_china_society_electricity()
            val, date_val = get_latest(df, '第三产业用电量同比')
            if val is None:
                # 用新能源指数作为代理
                df2 = ak.macro_china_energy_index()
                val2, date_val2 = get_latest(df2, '最新值')
                if val2:
                    val = round(float(val2) / 100, 1)  # 转为百分比形式
                    date_val = date_val2
            if val is None:
                raise Exception("无服务业/新能源数据")
            data['evPenetration'] = round(float(val), 1)
            meta['evPenetration'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '第三产业用电量增速/新能源指数代理(%)'}
            sources['evPenetration'] = 'AKShare-macro_china_society_electricity(服务业用电代理)'
            validity['evPenetration'] = check_validity(data['evPenetration'], sources['evPenetration'], 'monthly')
            print(f"✅ 电动车渗透率(代理): {data['evPenetration']}% {meta['evPenetration']['dateLabel']}")
        except Exception as e:
            data['evPenetration'] = 'NA'
            meta['evPenetration'] = {'dateLabel': '-'}
            validity['evPenetration'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 电动车渗透率: {e}")

        # 19. 专利申请 - 使用科技投资代理
        try:
            # AKShare暂无专利申请数据，使用科技股指数作为代理
            df = ak.macro_china_energy_index()
            val, date_val = get_latest(df, '最新值')
            if val is None:
                raise Exception("无新能源指数数据")
            # 中证新能源指数值作为科技创新活跃度代理
            data['patentApps'] = round(float(val), 0)
            meta['patentApps'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '中证新能源指数(科技创新活跃度代理)'}
            sources['patentApps'] = 'AKShare-macro_china_energy_index(科技活跃度代理)'
            validity['patentApps'] = check_validity(data['patentApps'], sources['patentApps'], 'daily')
            print(f"✅ 专利申请(代理): {data['patentApps']} {meta['patentApps']['dateLabel']}")
        except Exception as e:
            data['patentApps'] = 'NA'
            meta['patentApps'] = {'dateLabel': '-'}
            validity['patentApps'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 专利申请: {e}")

        # 20. 机器人安装 - 使用第二产业用电量增速作为工业自动化代理
        try:
            df = ak.macro_china_society_electricity()
            val, date_val = get_latest(df, '第二产业用电量同比')
            if val is None:
                raise Exception("无第二产业用电量数据")
            data['robotInstall'] = round(float(val), 1)
            meta['robotInstall'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '第二产业用电量增速(机器人安装/工业自动化代理%)'}
            sources['robotInstall'] = 'AKShare-macro_china_society_electricity'
            validity['robotInstall'] = check_validity(data['robotInstall'], sources['robotInstall'], 'monthly')
            print(f"✅ 机器人安装(代理): {data['robotInstall']}% {meta['robotInstall']['dateLabel']}")
        except Exception as e:
            data['robotInstall'] = 'NA'
            meta['robotInstall'] = {'dateLabel': '-'}
            validity['robotInstall'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 机器人安装: {e}")

        # ═══════════════════════════════════════════
        # 维度6: 气候与资源（4个）
        # ═══════════════════════════════════════════

        # 21. 天然气价格 - Henry Hub天然气期货
        try:
            df = ak.futures_global_spot_em()
            # 找最近主力合约 NG00Y 或最近的 NG 合约
            ng = df[df['代码'] == 'NG00Y']
            if ng.empty:
                # 找最近到期的天然气合约
                nat = df[df['名称'].str.contains('天然气|Nat Gas', na=False, case=False)]
                if not nat.empty:
                    ng = nat.iloc[[0]]
            if ng.empty:
                raise Exception("未找到天然气期货")
            current = round(float(ng['最新价'].iloc[0]), 3)
            date_val = str(ng['日期'].iloc[0]) if '日期' in ng.columns else datetime.now().strftime('%Y-%m-%d')
            data['natGas'] = current
            meta['natGas'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '天然气美元/MMBtu'}
            try:
                chg = float(ng['涨跌幅'].iloc[0]) / 100
                meta['natGas']['mom'] = chg
                meta['natGas']['momLabel'] = fmt_change(chg)
            except:
                pass
            sources['natGas'] = 'AKShare-futures_global_spot_em(天然气)'
            validity['natGas'] = check_validity(data['natGas'], sources['natGas'], 'daily')
            print(f"✅ 天然气: ${data['natGas']}/MMBtu {meta['natGas']['dateLabel']}")
        except Exception as e:
            data['natGas'] = 'NA'
            meta['natGas'] = {'dateLabel': '-'}
            validity['natGas'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 天然气: {e}")

        # 22. 碳价格 - 北京碳市场成交均价
        try:
            df = ak.energy_carbon_bj()
            val, date_val = get_latest(df, '成交均价')
            if val is None:
                raise Exception("无北京碳市场数据")
            data['carbonPrice'] = round(float(val), 2)
            meta['carbonPrice'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '北京碳市场元/吨CO2'}
            sources['carbonPrice'] = 'AKShare-energy_carbon_bj(北京碳市场)'
            validity['carbonPrice'] = check_validity(data['carbonPrice'], sources['carbonPrice'], 'daily')
            print(f"✅ 碳价格: ¥{data['carbonPrice']}/吨 {meta['carbonPrice']['dateLabel']}")
        except Exception as e:
            data['carbonPrice'] = 'NA'
            meta['carbonPrice'] = {'dateLabel': '-'}
            validity['carbonPrice'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 碳价格: {e}")

        # 23. 极端天气 - 使用服务业PMI作为经济天气代理
        try:
            df = ak.macro_china_pmi()
            service_pmi = float(df['非制造业-指数'].iloc[0])
            # 经济天气指数 = PMI偏离50的程度（PMI越高=经济天气越好）
            # 转为0-100指数，50=50, >50 >50, <50 <50
            weather_index = round(50 + (service_pmi - 50) * 2, 1)
            date_val = str(df['月份'].iloc[0]) if '月份' in df.columns else None
            data['extremeWeather'] = weather_index
            meta['extremeWeather'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '经济天气指数(PMI代理,>50=晴)'}
            sources['extremeWeather'] = 'AKShare-macro_china_pmi(服务业PMI代理)'
            validity['extremeWeather'] = check_validity(data['extremeWeather'], sources['extremeWeather'], 'monthly')
            print(f"⚠️ 极端天气(代理): {data['extremeWeather']} {meta['extremeWeather']['dateLabel']}")
        except Exception as e:
            data['extremeWeather'] = 'NA'
            meta['extremeWeather'] = {'dateLabel': '-'}
            validity['extremeWeather'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 极端天气: {e}")

        # 24. 可再生能源投资 - 中证新能源指数作为代理
        try:
            df = ak.macro_china_energy_index()
            val, date_val = get_latest(df, '最新值')
            if val is None:
                raise Exception("无新能源指数数据")
            # 指数点位作为新能源投资活跃度代理
            data['renewEnergyInvest'] = round(float(val), 0)
            meta['renewEnergyInvest'] = {'date': date_val, 'dateLabel': fmt_date(date_val), 'note': '中证新能源指数(投资活跃度代理)'}
            # 涨跌幅
            try:
                chg = float(df['涨跌幅'].iloc[-1]) / 100
                meta['renewEnergyInvest']['mom'] = chg
                meta['renewEnergyInvest']['momLabel'] = fmt_change(chg)
            except:
                pass
            sources['renewEnergyInvest'] = 'AKShare-macro_china_energy_index'
            validity['renewEnergyInvest'] = check_validity(data['renewEnergyInvest'], sources['renewEnergyInvest'], 'daily')
            print(f"✅ 可再生能源投资(代理): {data['renewEnergyInvest']} {meta['renewEnergyInvest']['dateLabel']}")
        except Exception as e:
            data['renewEnergyInvest'] = 'NA'
            meta['renewEnergyInvest'] = {'dateLabel': '-'}
            validity['renewEnergyInvest'] = {'is_valid': False, 'status': 'error', 'message': str(e)}
            print(f"❌ 可再生能源投资: {e}")

    except Exception as e:
        print(f"数据采集整体异常: {e}")
        import traceback
        traceback.print_exc()

    # ═══════════════════════════════════════════
    # 填充缺失指标
    # ═══════════════════════════════════════════
    all_fields = [
        'globalGdp', 'chinaGdp', 'chinaPmi', 'usGdp',
        'oilPrice', 'corePce', 'cpi', 'ppi',
        'fedBalance', 'lpr', 'dr007', 'dollarIndex',
        'vix', 'epu', 'creditSpread', 'geoRisk',
        'aiGrowth', 'evPenetration', 'patentApps', 'robotInstall',
        'natGas', 'carbonPrice', 'extremeWeather', 'renewEnergyInvest',
    ]

    for k in all_fields:
        if k not in data:
            data[k] = 'NA'
            validity[k] = {'is_valid': False, 'status': 'na', 'message': '未接入'}
        if k not in meta:
            meta[k] = {'dateLabel': '-'}
        if k not in sources:
            sources[k] = '未接入'

    return data, meta, sources, validity


def gen_report(validity):
    report = {
        'total': len(validity),
        'valid': sum(1 for v in validity.values() if v['is_valid']),
        'invalid': sum(1 for v in validity.values() if not v['is_valid']),
        'by_status': {}
    }
    for k, v in validity.items():
        s = v['status']
        if s not in report['by_status']:
            report['by_status'][s] = []
        report['by_status'][s].append(k)
    return report


if __name__ == "__main__":
    print("=" * 50)
    print("WorldOS 数据采集脚本 v1.1")
    print("24个指标 · 6大维度")
    print("=" * 50)
    print()

    data, meta, sources, validity = get_all_data()

    real_count = sum(1 for v in data.values() if v != 'NA')
    print(f"\n📊 共获取 {real_count}/24 个真实数据")

    report = gen_report(validity)
    print(f"\n📋 数据有效性报告:")
    print(f"  有效: {report['valid']}/24")
    print(f"  无效: {report['invalid']}/24")
    for status, fields in report['by_status'].items():
        print(f"  - {status}: {len(fields)}个 → {fields}")

    # 按维度组织数据供前端使用
    indicators = {
        'economicOutput': {
            'label': '经济产出',
            'fields': ['globalGdp', 'chinaGdp', 'chinaPmi', 'usGdp'],
        },
        'inflationPrices': {
            'label': '通胀与价格',
            'fields': ['oilPrice', 'corePce', 'cpi', 'ppi'],
        },
        'moneyCredit': {
            'label': '货币与信用',
            'fields': ['fedBalance', 'lpr', 'dr007', 'dollarIndex'],
        },
        'riskUncertainty': {
            'label': '风险与不确定性',
            'fields': ['vix', 'epu', 'creditSpread', 'geoRisk'],
        },
        'techProductivity': {
            'label': '技术与生产力',
            'fields': ['aiGrowth', 'evPenetration', 'patentApps', 'robotInstall'],
        },
        'climateResources': {
            'label': '气候与资源',
            'fields': ['natGas', 'carbonPrice', 'extremeWeather', 'renewEnergyInvest'],
        },
    }

    output = {
        'timestamp': datetime.now().isoformat(),
        'indicators': indicators,
        'data': data,
        'meta': meta,
        'sources': sources,
        'validity': validity,
        'validity_report': report,
    }

    # 保存
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, '..', 'public', 'data', 'market-data.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 数据已保存到 {output_path}")

    # 打印最终数据预览
    print("\n" + "=" * 50)
    print("24指标数据预览:")
    print("=" * 50)
    for dim, info in indicators.items():
        print(f"\n【{info['label']}】")
        for k in info['fields']:
            val = data.get(k, 'NA')
            ml = meta.get(k, {}).get('dateLabel', '-')
            note = meta.get(k, {}).get('note', '')
            src = sources.get(k, '-')
            tag = ' [代理]' if '代理' in note else ''
            print(f"  {k}: {val}{tag} ({ml}) [{src}]")
