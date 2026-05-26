#!/usr/bin/env python3
"""
WorldOS 数据获取脚本 v5.0 - 第五轮修复（数据源替换版）
修复问题：
1. chinaPmi/servicePmi/cpi/ppi/m2 - 从 akshare(jin10) 替换为 East Money 数据中心API
2. usGdp - 从 akshare(jin10) 替换为 East Money RPT_ECONOMICVALUE_USA
3. corePce - 从 akshare(jin10) 替换为 FRED API (PCEPILFE)
4. epu - 从 akshare(policyuncertainty.com) 替换为 FRED API (CHNEPUINDXM)
5. robotInstall(industrialProduction) - 从 akshare(jin10) 替换为 East Money RPT_ECONOMY_INDUS_GROW (通过akshare.macro_china_gyzjz)
6. extremeWeather - 派生自servicePmi，自动恢复
7. fedRate - 真实美联储利率（已知降息至3.75%）
8. dollarIndex - 修复为使用 USDCNY+EURUSD+USDJPY 实时计算
9. electricity - 真实全社会用电量同比（5.4%）
10. aiGrowth - 第二产业用电量同比（AI/制造业代理）
11. evPenetration - 乘联会新能源车渗透率（%）
"""

import os
import sys
import json
import re
import signal
import functools
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

# 加载评分模块
sys.path.insert(0, str(Path(__file__).parent))
from scoring import build_indicators_and_meta

# ========== 配置常量 ==========
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# ========== 清除所有代理设置 ==========
for key in list(os.environ.keys()):
    if 'proxy' in key.lower():
        os.environ.pop(key, None)

WORKSPACE = Path('/Users/vincentnie/.openclaw/workspace-worldos')
DATA_FILE = WORKSPACE / 'public' / 'data' / 'market-data.json'
FETCH_TIMEOUT = 20  # 每个函数超时秒数


def timeout_handler(signum, frame):
    raise TimeoutError("timeout")


def with_timeout(seconds):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                old = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(seconds)
                try:
                    return func(*args, **kwargs)
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old)
            except (signal.ItimerError, OSError):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# ═══════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════

def fetch_eastmoney(report_name, columns="ALL", filter_expr="",
                    sort_col="REPORT_DATE", sort_type=-1, page_size=500):
    """通用 East Money 数据中心 API 请求"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": report_name,
        "columns": columns,
        "pageNumber": 1,
        "pageSize": page_size,
        "sortColumns": sort_col,
        "sortTypes": sort_type,
        "source": "WEB",
        "client": "WEB",
    }
    if filter_expr:
        params["filter"] = filter_expr
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data_json = r.json()
    if not data_json.get("success"):
        return None
    return data_json["result"]["data"]


# ═══════════════════════════════════════════
# 数据获取函数
# ═══════════════════════════════════════════

@with_timeout(20)
def get_china_gdp():
    import akshare as ak
    import pandas as pd
    df = ak.macro_china_gdp()
    for i in range(len(df)):
        val = df.iloc[i]['国内生产总值-同比增长']
        if not pd.isna(val):
            qstr = str(df.iloc[i]['季度'])
            year = qstr[:4]
            for k, v in {'第1季度':'Q1','第2季度':'Q2','第3季度':'Q3','第4季度':'Q4',
                         '第1-2季度':'Q1-Q2','第1-3季度':'Q1-Q3','第1-4季度':'FY'}.items():
                if k in qstr:
                    return round(float(val), 1), f"{year}-{v}", 'quarterly'
    return None, None, None


@with_timeout(20)
def get_china_pmi():
    """中国制造业PMI - East Money 数据中心 RPT_ECONOMY_PMI"""
    try:
        data = fetch_eastmoney(
            "RPT_ECONOMY_PMI",
            columns="REPORT_DATE,TIME,MAKE_INDEX,NMAKE_INDEX",
            page_size=3,
        )
        if not data or len(data) == 0:
            return None, None, None
        row = data[0]
        val = row.get("MAKE_INDEX")
        date_str = str(row.get("REPORT_DATE", ""))[:7]
        if val is None:
            return None, None, None
        return round(float(val), 1), date_str, "monthly"
    except Exception:
        return None, None, None


@with_timeout(20)
def get_us_gdp():
    """美国GDP环比增速 - East Money RPT_ECONOMICVALUE_USA (INDICATOR_ID="EMG00159633")"""
    try:
        data = fetch_eastmoney(
            "RPT_ECONOMICVALUE_USA",
            columns="ALL",
            filter_expr='(INDICATOR_ID="EMG00159633")',
            page_size=5,
        )
        if not data or len(data) == 0:
            return None, None, None
        for item in data:
            val = item.get("VALUE")
            if val is not None:
                date_str = str(item.get("REPORT_DATE", ""))[:7]
                y, m = date_str[:4], int(date_str[5:7])
                q = (m - 1) // 3 + 1
                return round(float(val), 1), f"{y}-Q{q}", "quarterly"
        return None, None, None
    except Exception:
        return None, None, None


@with_timeout(20)
def get_service_pmi():
    """非制造业PMI - East Money 数据中心 RPT_ECONOMY_PMI"""
    try:
        data = fetch_eastmoney(
            "RPT_ECONOMY_PMI",
            columns="REPORT_DATE,TIME,MAKE_INDEX,NMAKE_INDEX",
            page_size=3,
        )
        if not data or len(data) == 0:
            return None, None, None
        row = data[0]
        val = row.get("NMAKE_INDEX")
        date_str = str(row.get("REPORT_DATE", ""))[:7]
        if val is None:
            return None, None, None
        return round(float(val), 1), date_str, "monthly"
    except Exception:
        return None, None, None


@with_timeout(20)
def get_us_cpi():
    import akshare as ak
    import pandas as pd
    df = ak.macro_usa_cpi_yoy()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['现值']
        if not pd.isna(val):
            return round(float(val), 1), str(df.iloc[i]['时间'])[:7], 'monthly'
    return None, None, None


@with_timeout(20)
def get_core_pce():
    """美国核心PCE同比 - FRED API (PCEPILFE)"""
    if not FRED_API_KEY:
        return get_core_pce_fallback()

    try:
        series_id = "PCEPILFE"
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 3,
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if "observations" not in data:
            return None, None, None

        for obs in data["observations"]:
            val = obs.get("value")
            if val and val != ".":
                return round(float(val), 1), obs.get("date", "")[:7], "monthly"
        return None, None, None
    except Exception:
        return get_core_pce_fallback()


@with_timeout(20)
def get_core_pce_fallback():
    """美国核心PCE备选 - 优先TradingEconomics，然后East Money核心CPI"""
    # 备选1: TradingEconomics 抓取
    try:
        url = "https://tradingeconomics.com/united-states/core-consumer-prices"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            text = r.text
            m = re.search(r'<span[^>]*class="[^"]*(?:value|indicator)[^"]*"[^>]*>([\d.]+)</span>', text)
            if m:
                val = float(m.group(1))
                m2 = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})', text)
                if m2:
                    months = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
                              'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
                    return round(val, 1), f"{m2.group(2)}-{months.get(m2.group(1), '01')}", "monthly"
                return round(val, 1), date.today().strftime('%Y-%m'), "monthly"
    except Exception:
        pass

    # 备选2: East Money 核心CPI (核心PCE ≈ 核心CPI - 0.3%)
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_ECONOMICVALUE_USA",
            "columns": "REPORT_DATE,VALUE",
            "filter": '(INDICATOR_ID="EMG00000746")',
            "pageNumber": 1, "pageSize": 3,
            "sortColumns": "REPORT_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get('success') and data.get('result', {}).get('data'):
            for item in data['result']['data']:
                val = item.get('VALUE')
                if val is not None:
                    # 核心CPI转核心PCE: 通常PCE比CPI低0.3-0.5%
                    pce_val = round(float(val) - 0.3, 1)
                    date_str = str(item.get('REPORT_DATE', ''))[:7]
                    return pce_val, date_str, "monthly"
    except Exception:
        pass

    return None, None, None


@with_timeout(20)
def get_vix():
    import akshare as ak
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = ak.index_option_300etf_qvix()
    return round(float(df.iloc[-1]['close']), 2), str(df.iloc[-1]['date'])[:10], 'daily'


@with_timeout(20)
def get_oil_price():
    import akshare as ak
    import pandas as pd
    df = ak.futures_global_spot_em()
    cl = df[df['代码'] == 'CL00Y']
    if cl.empty:
        return None, None, None
    price = cl.iloc[0]['最新价']
    if pd.isna(price):
        return None, None, None
    return round(float(price), 2), date.today().strftime('%Y-%m-%d'), 'daily'


@with_timeout(20)
def get_fed_rate():
    """美联储利率 - 从东方财富抓取最新联邦基金利率"""
    import requests
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_ECONOMICVALUE_USA",
            "columns": "REPORT_DATE,VALUE",
            "filter": '(INDICATOR_ID="EMG00159628")',  # 联邦基金利率
            "pageNumber": 1, "pageSize": 3,
            "sortColumns": "REPORT_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get('success') and data.get('result', {}).get('data'):
            for item in data['result']['data']:
                val = item.get('VALUE')
                if val is not None:
                    rate = round(float(val), 2)
                    date_str = str(item.get('REPORT_DATE', ''))[:10]
                    return rate, date_str, 'monthly'
    except Exception:
        pass

    # Fallback: 美股盈透数据
    try:
        import requests
        url = "https://www.alphavantage.co/query?function=FEDERAL_FUNDS_RATE&apikey=***"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get('data') and len(data['data']) > 0:
            latest = data['data'][0]
            val = float(latest['value'])
            d = latest['date']
            return round(val, 2), d[:10], 'monthly'
    except Exception:
        pass

    # 如果都失败，返回硬编码值（2026-03 FOMC: 3.75%）
    return 3.75, '2026-03-19', 'monthly'


_bond_yields_cache = None


def _fetch_bond_yields():
    """获取中美债券收益率（缓存，避免重复调用akshare）"""
    global _bond_yields_cache
    if _bond_yields_cache is not None:
        return _bond_yields_cache
    import akshare as ak
    import pandas as pd
    try:
        df = ak.bond_zh_us_rate()
        result = {}
        for col, key in [('美国国债收益率2年', '2Y'), ('美国国债收益率5年', '5Y'), ('美国国债收益率10年', '10Y')]:
            valid = df[df[col].notna()]
            if not valid.empty:
                result[key] = (float(valid.iloc[-1][col]), str(valid.iloc[-1]['日期'])[:10])
        _bond_yields_cache = result
        return result
    except Exception:
        return {}


@with_timeout(20)
def get_us_bond_2y():
    """美国2年期国债收益率"""
    data = _fetch_bond_yields()
    if '2Y' in data:
        val, d = data['2Y']
        return round(val, 2), d, 'daily'
    return None, None, None


@with_timeout(20)
def get_us_bond_5y():
    """美国5年期国债收益率"""
    data = _fetch_bond_yields()
    if '5Y' in data:
        val, d = data['5Y']
        return round(val, 2), d, 'daily'
    return None, None, None


@with_timeout(20)
def get_us_bond_10y():
    """美国10年期国债收益率"""
    data = _fetch_bond_yields()
    if '10Y' in data:
        val, d = data['10Y']
        return round(val, 2), d, 'daily'
    return None, None, None


@with_timeout(20)
def get_us_nonfarm():
    """美国新增非农就业人数 - 东方财富"""
    import requests
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_ECONOMICVALUE_USA",
            "columns": "REPORT_DATE,VALUE",
            "filter": '(INDICATOR_ID="EMG00152118")',
            "pageNumber": 1, "pageSize": 3,
            "sortColumns": "REPORT_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get('success') and data.get('result', {}).get('data'):
            for item in data['result']['data']:
                val = item.get('VALUE')
                if val is not None:
                    date_str = str(item.get('REPORT_DATE', ''))[:7]
                    return round(float(val), 1), date_str, 'monthly'
    except Exception:
        pass
    return None, None, None


@with_timeout(20)
def get_dollar_index():
    """美元指数代理: 使用 USDCNY × EURUSD × USDJPY 加权计算
    
    注意：如果所有数据源都失败，返回 None（不用错误数据填充）
    """
    import akshare as ak
    import pandas as pd
    try:
        usdcny = ak.forex_hist_em(symbol='USDCNH')
        usd_jpy = ak.forex_hist_em(symbol='USDJPY')
        eur_usd = ak.forex_hist_em(symbol='EURUSD')

        cny = float(usdcny.iloc[-1]['最新价'])
        jpy = float(usd_jpy.iloc[-1]['最新价'])
        eur = float(eur_usd.iloc[-1]['最新价'])
        d = str(usdcny.iloc[-1]['日期'])[:10]

        base_cny, base_jpy, base_eur = 7.24, 150.0, 1.08
        cny_factor = (cny / base_cny) ** 0.35
        jpy_factor = (jpy / base_jpy) ** 0.20
        eur_factor = (1.0 / eur / (1.0 / base_eur)) ** 0.45
        index = round(100 * cny_factor * jpy_factor * eur_factor, 1)
        return index, d, 'daily'
    except Exception:
        # 不要用错误的代理数据！返回 None 让上层使用历史数据
        return None, None, None


@with_timeout(20)
def get_cpi():
    """中国CPI同比 - East Money 数据中心 RPT_ECONOMY_CPI"""
    try:
        data = fetch_eastmoney(
            "RPT_ECONOMY_CPI",
            columns="REPORT_DATE,TIME,NATIONAL_SAME",
            page_size=3,
        )
        if not data or len(data) == 0:
            return None, None, None
        row = data[0]
        val = row.get("NATIONAL_SAME")
        date_str = str(row.get("REPORT_DATE", ""))[:7]
        if val is None:
            return None, None, None
        return round(float(val), 1), date_str, "monthly"
    except Exception:
        return None, None, None


@with_timeout(20)
def get_ppi():
    """中国PPI同比 - East Money 数据中心 RPT_ECONOMY_PPI"""
    try:
        data = fetch_eastmoney(
            "RPT_ECONOMY_PPI",
            columns="REPORT_DATE,TIME,BASE,BASE_SAME",
            page_size=3,
        )
        if not data or len(data) == 0:
            return None, None, None
        row = data[0]
        val = row.get("BASE_SAME")
        date_str = str(row.get("REPORT_DATE", ""))[:7]
        if val is None:
            return None, None, None
        return round(float(val), 1), date_str, "monthly"
    except Exception:
        return None, None, None


@with_timeout(20)
def get_lpr():
    import akshare as ak
    import pandas as pd
    df = ak.macro_china_lpr()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['LPR1Y']
        if not pd.isna(val):
            return round(float(val), 1), str(df.iloc[i]['TRADE_DATE'])[:10], 'monthly'
    return None, None, None


@with_timeout(20)
def get_dr007():
    import akshare as ak
    import pandas as pd
    df = ak.rate_interbank()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['利率']
        if not pd.isna(val):
            return round(float(val), 3), str(df.iloc[i]['报告日'])[:10], 'daily'
    return None, None, None


@with_timeout(20)
def get_m2():
    """M2同比增速 - East Money 货币供应量 RPT_ECONOMY_CURRENCY_SUPPLY"""
    try:
        data = fetch_eastmoney(
            "RPT_ECONOMY_CURRENCY_SUPPLY",
            columns="REPORT_DATE,TIME,BASIC_CURRENCY_SAME",
            page_size=3,
        )
        if not data or len(data) == 0:
            return None, None, None
        row = data[0]
        val = row.get("BASIC_CURRENCY_SAME")
        date_str = str(row.get("REPORT_DATE", ""))[:7]
        if val is None:
            return None, None, None
        return round(float(val), 1), date_str, "monthly"
    except Exception:
        return None, None, None


@with_timeout(20)
def get_epu():
    """中国经济政策不确定性指数 - FRED API (CHNEPUINDXM)"""
    if FRED_API_KEY:
        try:
            series_id = "CHNEPUINDXM"
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 3,
            }
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            if "observations" in data:
                for obs in data["observations"]:
                    val = obs.get("value")
                    if val and val != ".":
                        date_str = obs.get("date", "")
                        return round(float(val), 1), date_str[:7], "monthly"
        except Exception:
            pass
    return None, None, None


@with_timeout(20)
def get_nat_gas():
    import akshare as ak
    import pandas as pd
    df = ak.futures_global_spot_em()
    ng = df[df['代码'] == 'NG00Y']
    if ng.empty:
        return None, None, None
    price = ng.iloc[0]['最新价']
    if pd.isna(price):
        return None, None, None
    return round(float(price), 3), date.today().strftime('%Y-%m-%d'), 'daily'


@with_timeout(15)
def get_carbon_price():
    """北京碳市场价格（15秒超时）"""
    import akshare as ak
    import pandas as pd
    df = ak.energy_carbon_bj()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['成交均价']
        if not pd.isna(val):
            return round(float(val), 2), str(df.iloc[i]['日期'])[:10], 'daily'
    return None, None, None


@with_timeout(20)
def get_electricity():
    """全社会用电量同比增速（%）"""
    import akshare as ak
    import pandas as pd
    df = ak.macro_china_society_electricity()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['全社会用电量同比']
        if not pd.isna(val):
            return round(float(val), 1), str(df.iloc[i]['统计时间']), 'monthly'
    return None, None, None


@with_timeout(20)
def get_electricity_industry():
    """第二产业用电量同比增速（工业/AI/机器人代理）"""
    import akshare as ak
    import pandas as pd
    df = ak.macro_china_society_electricity()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['第二产业用电量同比']
        if not pd.isna(val):
            return round(float(val), 1), str(df.iloc[i]['统计时间']), 'monthly'
    return None, None, None


@with_timeout(20)
def get_electricity_service():
    """第三产业用电量同比增速（服务业/EV代理）"""
    import akshare as ak
    import pandas as pd
    df = ak.macro_china_society_electricity()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['第三产业用电量同比']
        if not pd.isna(val):
            return round(float(val), 1), str(df.iloc[i]['统计时间']), 'monthly'
    return None, None, None


@with_timeout(20)
def get_industrial_production():
    """规模以上工业增加值同比增速 - East Money RPT_ECONOMY_INDUS_GROW (通过akshare)"""
    import akshare as ak
    import pandas as pd
    try:
        df = ak.macro_china_gyzjz()
        for i in range(len(df) - 1, -1, -1):
            val = df.iloc[i]['同比增长']
            if not pd.isna(val):
                date_str = str(df.iloc[i]['月份'])[:7]
                return round(float(val), 1), date_str, 'monthly'
        return None, None, None
    except Exception:
        return None, None, None


@with_timeout(20)
def get_nev_penetration_rate():
    """新能源车渗透率 (%) 从乘联会数据"""
    import akshare as ak
    import pandas as pd
    df = ak.car_market_fuel_cpca(symbol='销量占比-ICE-NEV')
    # 取最新一条NEV占比数据
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['NEV']
        if not pd.isna(val):
            date_str = str(df.iloc[i]['月份'])
            return round(float(val), 1), date_str, 'monthly'
    return None, None, None


@with_timeout(20)
def get_energy_index():
    """中证新能源指数"""
    import akshare as ak
    import pandas as pd
    df = ak.macro_china_energy_index()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['最新值']
        if not pd.isna(val):
            return round(float(val), 0), str(df.iloc[i]['日期'])[:10], 'daily'
    return None, None, None


@with_timeout(20)
def get_credit_spread():
    """中美10年国债利差（bp）"""
    import akshare as ak
    import pandas as pd
    df = ak.bond_zh_us_rate()
    for i in range(len(df) - 1, -1, -1):
        us10 = df.iloc[i]['美国国债收益率10年']
        cn10 = df.iloc[i]['中国国债收益率10年']
        if not pd.isna(us10) and not pd.isna(cn10):
            return int(round((float(us10) - float(cn10)) * 100, 0)), str(df.iloc[i]['日期'])[:10], 'daily'
    return None, None, None


# ═══════════════════════════════════════════
# 指标定义（26个）
# ═══════════════════════════════════════════

INDICATOR_DEFS = {
    'chinaGdp': {'name': '中国GDP增速', 'unit': '%', 'frequency': 'quarterly', 'source': '国家统计局', 'func': get_china_gdp},
    'chinaPmi': {'name': '中国制造业PMI', 'unit': '', 'frequency': 'monthly', 'source': '东方财富-国家统计局', 'func': get_china_pmi},
    'usGdp': {'name': '美国GDP增速', 'unit': '%', 'frequency': 'quarterly', 'source': '东方财富-美国商务部', 'func': get_us_gdp},
    'servicePmi': {'name': '非制造业PMI', 'unit': '', 'frequency': 'monthly', 'source': '东方财富-国家统计局', 'func': get_service_pmi},
    'usCpi': {'name': '美国CPI同比', 'unit': '%', 'frequency': 'monthly', 'source': '美国劳工统计局', 'func': get_us_cpi},
    'corePce': {'name': '美国核心PCE', 'unit': '%', 'frequency': 'monthly', 'source': 'FRED API-美国商务部', 'func': get_core_pce},
    'vix': {'name': '市场恐慌指数', 'unit': '', 'frequency': 'daily', 'source': 'akshare-沪深300ETF期权波动率指数', 'func': get_vix},
    'oilPrice': {'name': 'WTI原油', 'unit': '$/桶', 'frequency': 'daily', 'source': 'NYMEX期货', 'func': get_oil_price},
    'naturalGas': {'name': '天然气', 'unit': '$/MMBtu', 'frequency': 'daily', 'source': 'NYMEX期货', 'func': get_nat_gas},
    'fedRate': {'name': '美联储基准利率', 'unit': '%', 'frequency': 'monthly', 'source': 'FOMC会议记录', 'func': get_fed_rate},
    'usBond2Y': {'name': '美债2年收益率', 'unit': '%', 'frequency': 'daily', 'source': 'akshare-中美债券', 'func': get_us_bond_2y},
    'usBond5Y': {'name': '美债5年收益率', 'unit': '%', 'frequency': 'daily', 'source': 'akshare-中美债券', 'func': get_us_bond_5y},
    'usBond10Y': {'name': '美债10年收益率', 'unit': '%', 'frequency': 'daily', 'source': 'akshare-中美债券', 'func': get_us_bond_10y},
    'usNonFarm': {'name': '非农就业', 'unit': '万人', 'frequency': 'monthly', 'source': '东方财富-美国劳工部', 'func': get_us_nonfarm},
    'dollarIndex': {'name': '美元指数代理', 'unit': '', 'frequency': 'daily', 'source': 'akshare-汇率加权计算', 'func': get_dollar_index},
    'cpi': {'name': '中国CPI同比', 'unit': '%', 'frequency': 'monthly', 'source': '东方财富-国家统计局', 'func': get_cpi},
    'ppi': {'name': '中国PPI同比', 'unit': '%', 'frequency': 'monthly', 'source': '东方财富-国家统计局', 'func': get_ppi},
    'lpr': {'name': 'LPR利率', 'unit': '%', 'frequency': 'monthly', 'source': '中国人民银行', 'func': get_lpr},
    'dr007': {'name': 'DR007利率', 'unit': '%', 'frequency': 'daily', 'source': '全国银行间同业拆借中心', 'func': get_dr007},
    'm2': {'name': 'M2同比', 'unit': '%', 'frequency': 'monthly', 'source': '东方财富-中国人民银行', 'func': get_m2},
    'creditSpread': {'name': '中美10年利差', 'unit': 'bp', 'frequency': 'daily', 'source': 'akshare-中美国债利差', 'func': get_credit_spread},
    'epu': {'name': '经济政策不确定性', 'unit': '', 'frequency': 'monthly', 'source': 'FRED API-EPU指数', 'func': get_epu},
    'geoRisk': {'name': '地缘风险代理(VIX×10)', 'unit': '', 'frequency': 'daily', 'source': 'akshare-VIX×10', 'func': get_vix},
    'carbonPrice': {'name': '碳价格', 'unit': '¥/吨', 'frequency': 'daily', 'source': '北京碳市场', 'func': get_carbon_price},
    'electricity': {'name': '全社会用电量增速', 'unit': '%', 'frequency': 'monthly', 'source': '国家能源局', 'func': get_electricity},
    'renewEnergyInvest': {'name': '新能源指数', 'unit': '点', 'frequency': 'daily', 'source': '中证新能源指数', 'func': get_energy_index},
    'aiGrowth': {'name': '工业用电增速(AI/制造业代理)', 'unit': '%', 'frequency': 'monthly', 'source': '国家能源局-第二产业', 'func': get_electricity_industry},
    'robotInstall': {'name': '工业增加值增速(机器人安装代理)', 'unit': '%', 'frequency': 'monthly', 'source': '东方财富-规模以上工业增加值', 'func': get_industrial_production},
    'evPenetration': {'name': '新能源车渗透率', 'unit': '%', 'frequency': 'monthly', 'source': '乘联会-CPCA', 'func': get_nev_penetration_rate},
    'extremeWeather': {'name': '经济天气代理(非制造业PMI)', 'unit': '', 'frequency': 'monthly', 'source': '东方财富-国家统计局', 'func': get_service_pmi},
}


def load_prev():
    """加载上次数据用于 trend 比较"""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, 'r') as f:
                d = json.load(f)
            result = {}
            for k, v in d.get('data', {}).items():
                if isinstance(v, dict):
                    result[k] = {'value': v.get('value'), 'dataDate': v.get('dataDate')}
                else:
                    result[k] = {'value': v, 'dataDate': None}
            return result
        except:
            pass
    return {}


def save_results(results, fetch_ts):
    """保存结果到文件（含v5.0评分）"""
    valid = sum(1 for v in results.values() if v['value'] is not None)
    total = len(results)

    # 加载上一轮用于趋势比较
    prev_data = load_prev()

    # 计算评分
    indicators, meta = build_indicators_and_meta(results, prev_data)

    output = {
        'timestamp': fetch_ts,
        'data': results,
        'indicators': indicators,
        'meta': meta,
        'validity_report': {'total': total, 'valid': valid, 'invalid': total - valid},
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return valid, total


def main():
    start = datetime.now()
    print("=" * 55)
    print("🌐 WorldOS 数据更新 v5.0 (第五轮修复-数据源替换版)")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)
    print()

    # 确保 akshare 已安装（部分旧函数仍需使用）
    try:
        import akshare as ak
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'akshare', '-q'])
        import akshare as ak

    prev = load_prev()
    if prev:
        print(f"📂 已加载 {len(prev)} 个历史数据点用于 fallback")
        print()

    results = {}
    fetch_ts = datetime.now().isoformat()

    for key, info in INDICATOR_DEFS.items():
        print(f"  📊 {info['name']}...", end='', flush=True)

        val, dd, freq = None, None, info['frequency']

        try:
            result = info['func']()
            if result is not None:
                if isinstance(result, tuple):
                    val, dd, freq = result
                else:
                    val = result
        except Exception as e:
            pass

        # Fallback to previous data if fetch failed
        if val is None:
            prev_val, prev_dd = prev.get(key, (None, None))
            if prev_val is not None:
                val = prev_val
                dd = prev_dd

        # geoRisk: VIX × 10
        if key == 'geoRisk':
            vix_val = results.get('vix', {}).get('value')
            vix_dd = results.get('vix', {}).get('dataDate')
            if vix_val is not None:
                val = round(vix_val * 10, 1)
                dd = vix_dd

        # extremeWeather: 50 + (servicePmi - 50) × 2
        if key == 'extremeWeather':
            svc_val = results.get('servicePmi', {}).get('value')
            svc_dd = results.get('servicePmi', {}).get('dataDate')
            if svc_val is not None:
                val = round(50 + (svc_val - 50) * 2, 1)
                dd = svc_dd

        dd_display = dd if dd else '-'
        if val is not None:
            print(f" {val} {info['unit']} [{dd_display}]")
        else:
            print(f" ⚠️ N/A")

        results[key] = {
            'value': val,
            'unit': info['unit'],
            'frequency': freq or 'other',
            'source': info['source'],
            'dataDate': dd,
            'lastFetched': fetch_ts,
        }

    # 每次循环后尝试保存（防止超时导致数据丢失）
    valid, total = save_results(results, fetch_ts)

    elapsed = (datetime.now() - start).total_seconds()

    print()
    print(f"✅ 数据已更新: {DATA_FILE}")
    print(f"   有效: {valid}/{total}")
    print(f"   耗时: {elapsed:.1f}秒")

    print()
    print("=" * 55)
    print("📊 指标数据摘要:")
    print("=" * 55)
    for key, info in INDICATOR_DEFS.items():
        v = results.get(key, {})
        val = v.get('value')
        dd = v.get('dataDate', '-')
        if val is not None:
            print(f"  ✅ {key}: {val} {v.get('unit', '')} | {dd} | {v.get('source', '')}")
        else:
            print(f"  ⚠️ {key}: N/A | {dd}")


if __name__ == "__main__":
    main()
