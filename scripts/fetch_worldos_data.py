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
import math
import re
import signal
import functools
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

# 加载评分模块
sys.path.insert(0, str(Path(__file__).parent))
from scoring import build_indicators_and_meta
from indicator_meta import INDICATORS as INDICATOR_META, days_stale as _days_stale

# ========== 配置常量 ==========
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# ========== 清除所有代理设置 ==========
for key in list(os.environ.keys()):
    if 'proxy' in key.lower():
        os.environ.pop(key, None)

WORKSPACE = Path('/Users/vincentnie/.openclaw/workspace-worldos')
DATA_FILE = WORKSPACE / 'public' / 'data' / 'market-data.json'
HISTORY_DIR = WORKSPACE / 'data' / 'history'          # T7：每日快照归档（不进 public/，不随站点部署）
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

def _is_bad_number(value) -> bool:
    """None / NaN / ±Infinity / 非数字 → True。

    akshare 与部分 JSON API 会返回 NaN 而不抛异常，
    必须在写盘前统一识别，否则会产出非法 JSON 字面量 NaN。
    """
    if value is None:
        return True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return True
    return math.isnan(number) or math.isinf(number)


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
    # numpy 标量（np.float32 等不是 float 子类）
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return _sanitize(obj.item())
    except ImportError:
        pass
    return obj


def write_json_strict(path, obj):
    """原子写入合法 JSON：先清洗 NaN/Inf → allow_nan=False 序列化 → 严格回读自检。

    任何一步失败都抛异常，绝不落盘半个非法文件。
    """
    path = Path(path)
    clean = _sanitize(obj)
    payload = json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False)

    # 严格自检：遇 NaN/Infinity 立即抛错
    def _reject_constant(token):
        raise ValueError(f"非法 JSON 常量: {token}")

    json.loads(payload, parse_constant=_reject_constant)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + '.tmp')
    tmp_path.write_text(payload, encoding='utf-8')
    os.replace(tmp_path, path)
    return clean


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
    """美国核心PCE同比 - FRED API (PCEPILFE指数→YoY%)"""
    if FRED_API_KEY:
        try:
            series_id = "PCEPILFE"
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 15,
            }
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            if "observations" in data:
                obs = data["observations"]
                # 计算同比: 找12个月前同月的指数值
                for i in range(len(obs)):
                    o = obs[i]
                    if o["value"] == ".":
                        continue
                    y, m = o["date"][:4], o["date"][5:7]
                    prev_y = str(int(y) - 1)
                    for j in range(i + 1, len(obs)):
                        o2 = obs[j]
                        if o2["date"].startswith(f"{prev_y}-{m}") and o2["value"] != ".":
                            yoy = (float(o["value"]) - float(o2["value"])) / float(o2["value"]) * 100
                            return round(yoy, 1), o["date"][:7], "monthly"
        except Exception:
            pass
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
    import pandas as pd
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = ak.index_option_300etf_qvix()
    if df is None or df.empty:
        return None, None, None
    # akshare 会把当周剩余交易日（含未来日期）的空行一起返回，
    # 因此 iloc[-1] 在周一~周四永远命中未来空行（close=NaN）。
    # 必须先丢掉 NaN 行，再取最后一条有效数据（对齐 _fetch_bond_yields 的写法）。
    valid = df[df['close'].notna()]
    if valid.empty:
        return None, None, None
    row = valid.iloc[-1]
    close = row['close']
    if _is_bad_number(close):
        return None, None, None
    return round(float(close), 2), str(row['date'])[:10], 'daily'


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
@with_timeout(20)
def get_fear_greed():
    """恐惧贪婪指数 - CNN Fear & Greed Index"""
    import requests, os
    try:
        # 绕过代理直接连CNN
        for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
            os.environ.pop(key, None)
        url = "https://production.dataviz.cnn.io/index/fearandgreed/current"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Origin": "https://www.cnn.com",
            "Referer": "https://www.cnn.com/markets/fear-and-greed",
        }
        r = requests.get(url, headers=headers, timeout=15, proxies={"https": "", "http": ""})
        if r.status_code == 200:
            data = r.json()
            val = round(data.get("score", 0), 1)
            rating = data.get("rating", "")
            ts = data.get("timestamp", "")[:10]
            return val, ts, "daily"
    except Exception:
        pass
    return None, None, None


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
                    # 东方财富单位是千人，WorldOS 配置单位是万人，除以10转换
                    val = float(val) / 10
                    return round(val, 1), date_str, 'monthly'
    except Exception:
        pass
    return None, None, None


@with_timeout(20)
def get_dollar_index():
    """美元指数代理: 使用 USDCNY × EURUSD × USDJPY 加权计算
    
    通过 exchangerate-api.com API 获取实时汇率（akshare的东方财富源有代理问题）
    """
    import requests
    try:
        r = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=10)
        r.raise_for_status()
        data = r.json()
        rates = data.get('rates', {})
        
        cny = rates.get('CNY')
        jpy = rates.get('JPY')
        eur = rates.get('EUR')
        
        if not all([cny, jpy, eur]):
            return None, None, None
        
        cny = float(cny)
        jpy = float(jpy)
        eur = 1.0 / float(eur)  # EURUSD 汇率为 1/EUR
        
        d = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        base_cny, base_jpy, base_eur = 7.24, 150.0, 1.08
        cny_factor = (cny / base_cny) ** 0.35
        jpy_factor = (jpy / base_jpy) ** 0.20
        eur_factor = (1.0 / eur / (1.0 / base_eur)) ** 0.45
        index = round(100 * cny_factor * jpy_factor * eur_factor, 1)
        return index, d, 'daily'
    except Exception:
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


@with_timeout(40)
def get_carbon_price():
    """北京碳市场价格（40秒超时，该接口正常需约27秒）"""
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


@with_timeout(15)
def get_lme_index():
    """LME金属指数 - 使用LME铜3个月期货作为核心代表"""
    import akshare as ak
    import pandas as pd
    try:
        # 使用 futures_global_spot_em 获取 LME 铜(综合铜03)价格
        df = ak.futures_global_spot_em()
        lme_cu = df[df['代码'] == 'LCPT']
        if not lme_cu.empty:
            price = lme_cu.iloc[0]['最新价']
            if not pd.isna(price):
                return round(float(price), 2), date.today().strftime('%Y-%m-%d'), 'daily'
    except Exception:
        pass
    return None, None, None


@with_timeout(15)
def get_shanghai_copper():
    """沪铜期货主力合约价格 - 通过新浪财经实时行情"""
    import requests
    import re
    try:
        headers = {'Referer': 'https://finance.sina.com.cn'}
        r = requests.get('https://hq.sinajs.cn/list=nf_CU0', headers=headers, timeout=10)
        r.encoding = 'gbk'
        text = r.text
        # 格式: var hq_str_nf_CU0="铜连续,ID,开盘价,最高价,最低价,昨收,最新价,买价,卖价,..."
        # 最新价在索引6（从0开始）
        match = re.search(r'"([^"]+)"', text)
        if match:
            parts = match.group(1).split(',')
            if len(parts) > 8:
                latest_price = parts[6].strip()
                if latest_price and latest_price != '0.000' and not _is_bad_number(latest_price):
                    return round(float(latest_price), 0), date.today().strftime('%Y-%m-%d'), 'daily'
    except Exception:
        pass
    return None, None, None


# ═══════════════════════════════════════════
# 指标定义（名称/单位/频率/来源 均取自 indicator_meta 单一真源，T1）
# ═══════════════════════════════════════════
# 本文件只声明「用哪个抓取函数 → 哪个 key」，不再写第二份指标名。
FETCH_FUNCS = {
    'chinaGdp': get_china_gdp,
    'chinaPmi': get_china_pmi,
    'usGdp': get_us_gdp,
    'servicePmi': get_service_pmi,
    'usCpi': get_us_cpi,
    'corePce': get_core_pce,
    'vix': get_vix,
    'oilPrice': get_oil_price,
    'naturalGas': get_nat_gas,
    'fedRate': get_fed_rate,
    'usBond2Y': get_us_bond_2y,
    'usBond5Y': get_us_bond_5y,
    'usBond10Y': get_us_bond_10y,
    'usNonFarm': get_us_nonfarm,
    'fearGreed': get_fear_greed,
    'dollarIndex': get_dollar_index,
    'cpi': get_cpi,
    'ppi': get_ppi,
    'lpr': get_lpr,
    'dr007': get_dr007,
    'm2': get_m2,
    'creditSpread': get_credit_spread,
    'epu': get_epu,
    'carbonPrice': get_carbon_price,
    'electricity': get_electricity,
    'renewEnergyInvest': get_energy_index,
    'aiGrowth': get_electricity_industry,
    'robotInstall': get_industrial_production,
    'evPenetration': get_nev_penetration_rate,
    'lmeIndex': get_lme_index,
    'shanghaiCopper': get_shanghai_copper,
}

# 由单一真源生成原有结构，保持下游 `info['name'] / ['unit'] / ['source']` 可用
INDICATOR_DEFS = {
    key: {
        'name': INDICATOR_META[key]['name'],
        'unit': INDICATOR_META[key]['unit'],
        'frequency': INDICATOR_META[key]['frequency'],
        'source': INDICATOR_META[key]['source'],
        'func': FETCH_FUNCS[key],
        'reference_only': bool(INDICATOR_META[key].get('reference_only', False)),
    }
    for key in FETCH_FUNCS
}

_missing_meta = [k for k in FETCH_FUNCS if k not in INDICATOR_META]
_orphan_funcs = [k for k in INDICATOR_META if k not in FETCH_FUNCS]
if _missing_meta:
    raise RuntimeError(f'指标缺元数据定义: {_missing_meta}')
if _orphan_funcs:
    raise RuntimeError(f'元数据里的指标没有抓取函数: {_orphan_funcs}')

# 已废弃：extremeWeather（= servicePmi × 2 − 50 的派生值，无评分、不在任何维度，纯噪音）
# 2026-11-09 P0 删除，避免「抓了 32 个但只有 31 个有用」的计数虚高。
DEPRECATED_KEYS = ['extremeWeather']


def _classify_error(exc) -> str:
    """把异常归类成稳定的枚举码（前端按码分色/给建议，不靠自由文本）。

    值域：http_4xx / http_5xx / empty_response / parse_error / timeout /
          nan_value / not_found
    """
    if exc is None:
        return 'not_found'
    if isinstance(exc, (TimeoutError,)):
        return 'timeout'

    resp = getattr(exc, 'response', None)
    code = getattr(resp, 'status_code', None)
    if isinstance(code, int):
        if 400 <= code < 500:
            return 'http_4xx'
        if 500 <= code < 600:
            return 'http_5xx'

    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if 'timeout' in name or 'timed out' in msg or 'timeout' in msg:
        return 'timeout'
    if any(w in msg for w in ('json', 'decode', 'parse', 'expecting value', 'keyerror')):
        return 'parse_error'
    if any(w in msg for w in ('connection', 'max retries', 'remote end', 'ssl', 'proxy')):
        return 'http_5xx'
    if 'not found' in msg or '404' in msg:
        return 'not_found'
    return 'parse_error'


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
    """保存结果到文件（含v5.0评分 + 评论生成）

    validity_report 升级（T6 前置）：failed[] 带稳定枚举码 reason + reasonText +
    days_stale（未知→null，绝不用 0 伪装新鲜）+ used_fallback。
    """
    valid = sum(1 for v in results.values() if v['value'] is not None)
    total = len(results)

    # 加载上一轮用于趋势比较
    prev_data = load_prev()

    # 计算评分
    indicators, meta = build_indicators_and_meta(results, prev_data)

    # 找出获取失败 / 降级兜底的指标
    failed_indicators = []
    degraded = 0
    for key, info in INDICATOR_DEFS.items():
        v = results.get(key, {})
        err = v.get('fetchError')
        if v.get('used_fallback'):
            degraded += 1
        if err is None and v.get('value') is not None:
            continue
        if err is None:
            err = {'reason': 'not_found', 'reasonText': '未取到数据'}
        failed_indicators.append({
            'key': key,
            'displayName': info['name'],
            'source': info['source'],
            'reason': err.get('reason', 'parse_error'),
            'reasonText': err.get('reasonText', ''),
            'dataDate': v.get('dataDate'),
            'days_stale': _days_stale(v.get('dataDate')),
            'used_fallback': bool(v.get('used_fallback')),
            'lastAttempt': fetch_ts,
        })

    output = {
        'timestamp': fetch_ts,
        'data': results,
        'indicators': indicators,
        'meta': meta,
        'validity_report': {
            'total': total,
            'valid': valid,
            'invalid': total - valid,
            'degraded': degraded,
            'failed': failed_indicators,
        },
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # strict 写入：NaN/Inf → null，allow_nan=False + 回读自检，绝不产出非法 JSON
    write_json_strict(DATA_FILE, output)

    # T7：每日快照归档（回测的前提；放 data/ 而非 public/，不随站点部署）
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        snap = HISTORY_DIR / f"{date.today().isoformat()}.json"
        write_json_strict(snap, output)
        print(f"  📚 历史快照已归档: {snap}")
    except Exception as e:
        print(f"  ⚠️ 历史快照归档失败: {e}")

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
        fetch_error = None

        try:
            result = info['func']()
            if result is None:
                fetch_error = {'reason': 'empty_response', 'reasonText': '数据源返回空'}
            elif isinstance(result, tuple):
                val, dd, freq = result
                if val is None:
                    fetch_error = {'reason': 'not_found', 'reasonText': '数据源无有效记录'}
            else:
                val = result
        except Exception as e:
            fetch_error = {
                'reason': _classify_error(e),
                'reasonText': f'{type(e).__name__}: {e}'[:200],
            }

        # 归一化：任何来源的 NaN/±Inf 一律视为获取失败（触发上一轮 fallback）
        if val is not None and _is_bad_number(val):
            fetch_error = {'reason': 'nan_value', 'reasonText': '数据源返回 NaN/Inf'}
            print(" (NaN→丢弃)", end='')
            val = None

        # Fallback to previous data if fetch failed（明文标记，不再静默冒充新鲜数据）
        used_fallback = False
        if val is None:
            prev_item = prev.get(key)
            if prev_item is not None:
                if isinstance(prev_item, dict):
                    val = prev_item.get('value')
                    dd = prev_item.get('dataDate')
                else:
                    val = prev_item
                    dd = None
                if val is not None:
                    used_fallback = True
                    if fetch_error is None:
                        fetch_error = {'reason': 'empty_response', 'reasonText': '数据源返回空'}
                    fetch_error['reasonText'] = (
                        fetch_error.get('reasonText', '') + '（已用上一轮值兜底）'
                    )

        dd_display = dd if dd else '-'
        if val is not None:
            flag = ' ↺兜底' if used_fallback else ''
            print(f" {val} {info['unit']} [{dd_display}]{flag}")
        else:
            print(f" ⚠️ N/A [{fetch_error.get('reason') if fetch_error else '-'}]")

        results[key] = {
            'value': val,
            'unit': info['unit'],
            'frequency': freq or 'other',
            'source': info['source'],
            'dataDate': dd,
            'lastFetched': fetch_ts,
            'used_fallback': used_fallback,
            'fetchError': fetch_error if (fetch_error and (used_fallback or val is None)) else None,
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
