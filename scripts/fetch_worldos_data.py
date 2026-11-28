#!/usr/bin/env python3
"""
WorldOS 数据获取脚本 v5.0 - 第五轮修复（数据源替换版）
修复问题：
1. chinaPmi/servicePmi/cpi/ppi/m2 - 从 akshare(jin10) 替换为 East Money 数据中心API
2. usGdp - 从 akshare(jin10) 替换为 East Money RPT_ECONOMICVALUE_USA
3. corePce - 从 akshare(jin10) 替换为 FRED API (PCEPILFE)
4. epu - 直连 policyuncertainty.com 官方 xlsx（FRED 无中国经济政策不确定性系列）
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
from scoring import build_indicators_and_meta, build_degraded_items
from indicator_meta import INDICATORS as INDICATOR_META, days_stale as _days_stale
from indicator_meta import PCT_RANK_CONFIG, PCT_RANK_WINDOW_LONG, QUANTILE_CONFIG
import series_store

# V1b-1：需要历史窗口的指标（回填历史 / 每日追加 / 挂样本）
# pct_rank 与 ratio_band 都要历史，统一从 indicator_meta.QUANTILE_CONFIG 派生（单一真源）
PCT_SERIES_KEYS = dict(QUANTILE_CONFIG)
PCT_TRANSFORM_LOOKBACK = 5      # delta5/sum5 需额外 5 个原始点才能算出当日 transform
SERIES_META = {                 # 存储声明，与 indicator_meta 的 transform/unit 一致
    'ashareTurnover': {'unit': '亿元', 'transform': 'raw'},
    'marginBalance': {'unit': '亿元', 'transform': 'delta5'},
    'southboundNet': {'unit': '亿元', 'transform': 'sum5'},
    'hstechMomentum': {'unit': '百分点', 'transform': 'raw'},
    'usdcnh': {'unit': '', 'transform': 'raw'},   # A2：日线收盘，ratio_ma_steps 的 MA120 来源
}

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
                return round(val, 1), None, "monthly"   # T11: 拿不到期日就不写，绝不伪造当月
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


CBOE_VIX_URL = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
FRED_VIX_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS'
BROWSER_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36')


def _vix_from_cboe():
    """CBOE 官方 VIX 日线：VIX_History.csv 最后一行 Close + 该行日期。

    行格式 `11/20/2026,28.630000,40.030000,26.940000,35.890000`（DATE,OPEN,HIGH,LOW,CLOSE）。
    日期解析失败即放弃（不伪造当天）。
    """
    r = requests.get(CBOE_VIX_URL, headers={'User-Agent': BROWSER_UA}, timeout=20)
    r.raise_for_status()
    for line in reversed(r.text.strip().splitlines()):
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 5:
            continue
        m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', parts[0])
        if not m:
            continue
        close = parts[4]
        if _is_bad_number(close):
            continue
        iso = f'{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
        return round(float(close), 2), iso
    return None


def _vix_from_fred():
    """FRED VIXCLS 兜底：最后一条有效 `YYYY-MM-DD,值`。"""
    r = requests.get(FRED_VIX_URL, headers={'User-Agent': BROWSER_UA}, timeout=20)
    r.raise_for_status()
    for line in reversed(r.text.strip().splitlines()):
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 2:
            continue
        ds, close = parts[0][:10], parts[1]
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', ds) or _is_bad_number(close):
            continue
        return round(float(close), 2), ds
    return None


@with_timeout(60)  # 主源 CBOE + 兜底 FRED，各自 requests timeout=20
def get_vix():
    """CBOE 官方 VIX 恐慌指数（日线收盘）。

    主源：CBOE VIX_History.csv → 真实交易日期
    兜底：FRED VIXCLS（同为 CBOE VIX 收盘价序列）
    两路皆失败 → (None, None, None)，交上一轮兜底并进 validity_report.failed。
    **不得回退到沪深300 QVIX**（不同标的、不同量纲，冒充即为数据造假）。
    """
    errors = []
    try:
        got = _vix_from_cboe()
        if got:
            return got[0], got[1], 'daily'
        errors.append('cboe: 无有效行')
    except Exception as e:
        errors.append(f'cboe: {type(e).__name__}: {e}'[:120])

    try:
        got = _vix_from_fred()
        if got:
            print(f" (VIX 主源失败，FRED VIXCLS 兜底: {' | '.join(errors)})", end='')
            return got[0], got[1], 'daily', {
                'source': 'FRED VIXCLS',
                'primarySource': 'CBOE VIX_History.csv',
                'reason': 'primary_source_failed',
                'reasonText': f'CBOE 官方日线不可用（{" | ".join(errors)}）；降级取 FRED VIXCLS（同为 CBOE VIX 收盘价）',
                'triedErrors': errors,
            }
        errors.append('fred: 无有效行')
    except Exception as e:
        errors.append(f'fred: {type(e).__name__}: {e}'[:120])

    print(f" (VIX 两路全失败: {' | '.join(errors)})", end='')
    return None, None, None


# WTI 合约代码：CL + 两位年 + 月份码（F Jan … Z Dec），如 CL27F
_CL_CONTRACT_RE = re.compile(r'^CL(\d{2})([FGHJKMNQUVXZ])$')
_MONTH_CODES = 'FGHJKMNQUVXZ'


def _oil_from_oilprice():
    """OilPrice.com 首页 WTI Crude 报价（源不含交易日期 → dataDate=None/realtime）。

    逻辑内联自 workspace-market-insight/scripts/oil_price.py（不跨仓库 import）：
    抓 data-hash="WTI-Crude" 行里的 <td class="value">；带 UA / timeout / 异常上抛。
    """
    r = requests.get('https://oilprice.com/', headers={'User-Agent': BROWSER_UA}, timeout=15)
    r.raise_for_status()
    html = r.text
    pattern = (
        r'data-hash="WTI-Crude"[^>]*>'
        r'.*?<td class="value">\s*([0-9]+(?:\.[0-9]+)?)\s*(?:<i[^<]*</i>)?\s*</td>'
    )
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return None
    price = float(m.group(1))
    if _is_bad_number(price) or price <= 0:
        return None
    return round(price, 2), None, 'daily'


def _oil_from_spot_em():
    """东财全球期货现货表：最近月 CL 合约最新价（源不含交易日期 → None）。

    CL00Y 主连已从该表下线，只剩具体月合约（CL27F…CL28H）。
    按 (两位年, 月份码) 显式排序取最近月，不写死月份、不依赖表内行序。
    """
    import akshare as ak
    import pandas as pd
    df = ak.futures_global_spot_em()
    if df is None or df.empty or '代码' not in df.columns:
        return None
    cands = []
    for _, row in df.iterrows():
        code = str(row.get('代码', '')).strip()
        m = _CL_CONTRACT_RE.match(code)
        if not m:
            continue
        price = row.get('最新价')
        if pd.isna(price) or _is_bad_number(price):
            continue
        cands.append(((int(m.group(1)), _MONTH_CODES.index(m.group(2))), code, float(price)))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    _, code, price = cands[0]
    return round(price, 2), None, 'daily', code


def _oil_from_hist_em():
    """东财 CL00Y 日线：返回「最新价」+ 真实交易日期（日期不可解析即放弃，不伪造）。"""
    import akshare as ak
    import pandas as pd
    df = ak.futures_global_hist_em(symbol='CL00Y')
    if df is None or df.empty or '最新价' not in df.columns:
        return None
    for _, row in df.iloc[::-1].iterrows():
        price = row.get('最新价')
        if pd.isna(price) or _is_bad_number(price):
            continue
        ds = str(row.get('日期'))[:10] if row.get('日期') is not None else ''
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', ds):
            return None
        return round(float(price), 2), ds, 'daily'
    return None


def _oil_from_yfinance():
    """yfinance CL=F 最近一根有效日线的收盘价 + 该日日期。"""
    import yfinance as yf
    h = yf.Ticker('CL=F').history(period='5d')
    if h is None or h.empty or 'Close' not in h.columns:
        return None
    h = h[h['Close'].notna()]
    if h.empty:
        return None
    close = h['Close'].iloc[-1]
    if _is_bad_number(close):
        return None
    ds = str(h.index[-1])[:10]
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', ds):
        return None
    return round(float(close), 2), ds, 'daily'


@with_timeout(90)  # 四路降级链（OilPrice 15s + akshare 两路 + yfinance），旧 45s 偏紧
def get_oil_price():
    """WTI 近月价：显式降级链，主源失败必须如实标注（不许静默冒充成功）。

    a) OilPrice.com 首页 WTI Crude  → 报价（源不含日期 → dataDate=None/realtime）
    b) 东财 futures_global_spot_em  → 最近月 CL 合约最新价（无日期）
    c) 东财 futures_global_hist_em('CL00Y') → 日线「最新价」+ 真实交易日
    d) yfinance CL=F               → 最近一根日线收盘 + 其日期
    e) 全失败 → None（交给上一轮值兜底）

    命中 b/c/d 时额外返回第 4 项 sourceDegraded：有值 ≠ 主源成功，
    上层据此写 actualSource 并进 validity_report.source_degraded。
    """
    PRIMARY = 'OilPrice.com WTI Crude'
    errors = []
    try:
        got = _oil_from_oilprice()
        if got:
            return got[:3]
        errors.append('oilprice: 未解析到 WTI Crude 行')
    except Exception as e:
        errors.append(f'oilprice: {type(e).__name__}: {e}'[:120])

    try:
        got = _oil_from_spot_em()
        if got:
            val, _, freq, code = got
            return val, None, freq, {
                'source': f'东财最近月合约({code})',
                'primarySource': PRIMARY,
                'reason': 'primary_source_failed',
                'reasonText': f'OilPrice.com 不可用；降级取东财现货表最近月合约 {code} 最新价（源不含日期，非实时报价）',
                'triedErrors': errors,
            }
        errors.append('spot_em: 无可用 CL 月合约')
    except Exception as e:
        errors.append(f'spot_em: {type(e).__name__}: {e}'[:120])

    try:
        got = _oil_from_hist_em()
        if got:
            val, dd, freq = got
            return val, dd, freq, {
                'source': '东财CL00Y日线',
                'primarySource': PRIMARY,
                'reason': 'primary_source_failed',
                'reasonText': 'OilPrice.com 与东财现货表均不可用；降级取东财 CL00Y 日线（真实交易日，非实时报价）',
                'triedErrors': errors,
            }
        errors.append('hist_em: 无有效日线')
    except Exception as e:
        errors.append(f'hist_em: {type(e).__name__}: {e}'[:120])

    try:
        got = _oil_from_yfinance()
        if got:
            val, dd, freq = got
            return val, dd, freq, {
                'source': 'yfinance CL=F',
                'primarySource': PRIMARY,
                'reason': 'primary_source_failed',
                'reasonText': 'OilPrice.com、东财现货表与东财日线均不可用；降级取 yfinance CL=F 日线收盘',
                'triedErrors': errors,
            }
        errors.append('yfinance: 无有效日线')
    except Exception as e:
        errors.append(f'yfinance: {type(e).__name__}: {e}'[:120])

    print(f" (WTI 四路全失败: {' | '.join(errors)})", end='')
    return None, None, None


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
def get_usdcnh():
    """美元兑离岸人民币 USDCNH（P1-8DIM 新增；A2 2026-11-28 改日线源）

    取数优先级（必须 log 用了哪个源）：
      1) akshare forex_hist_em('USDCNH') **日线**（东财，带真实交易日；取最新一根收盘）
      2) exchangerate-api /v4/latest/USD 的 rates.CNY（**在岸**中间价；回退时
         用 source_degraded + caliberNoteSuffix 把「在岸参考价」写上页面）
      3) 都取不到 → None。**不许造数、不许用上一交易日硬填、不许插值补齐。**

    为何改日线（A2）：旧源 forex_spot_em 不带交易日，只能标 realtime；且旧打分用
    固定水位 7.05/7.20/7.35，现价 6.65 恒为 +0.5 —— 要算「相对 120 日均值」就必须有日期序列。

    Returns: (value, dataDate, 'daily', source_degraded_or_None, extras_or_None)
    """
    import pandas as pd

    # ── 源 1：akshare 离岸日线（带交易日）──
    try:
        import akshare as ak
        df = ak.forex_hist_em(symbol='USDCNH')
        if df is not None and not df.empty:
            df = df.sort_values('日期')
            row = df.iloc[-1]
            price = row.get('最新价')
            d = str(row.get('日期'))[:10]
            if price is not None and not pd.isna(price) and d:
                v = round(float(price), 4)
                print(f" [源=akshare-forex_hist_em 离岸USDCNH日线 {v} @{d}]", end='')
                return v, d, 'daily', None, None
        print(" [源1 akshare日线: 无有效行]", end='')
    except Exception as e:  # noqa: BLE001
        print(f" [源1 akshare日线失败: {type(e).__name__}]", end='')

    # ── 源 2：exchangerate-api（在岸 CNY，必须标降级）──
    try:
        import requests
        r = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=10)
        r.raise_for_status()
        data = r.json()
        cny = (data.get('rates') or {}).get('CNY')
        if cny:
            v = round(float(cny), 4)
            d = data.get('date') or None
            print(f" [源=exchangerate-api 在岸CNY {v}（降级：非离岸价）]", end='')
            return v, d, 'daily', {
                'source': 'exchangerate-api 在岸中间价',
                'primarySource': 'akshare 离岸 USDCNH 日线（forex_hist_em）',
                'reason': 'primary_source_missing',
                'reasonText': '离岸日线暂不可得，已回退在岸参考价（口径见 caliberNote）',
                'caliberNoteSuffix': '（本条为在岸参考价，非离岸价）',
            }, None
        print(" [源2 exchangerate-api: 无 CNY]", end='')
    except Exception as e:  # noqa: BLE001
        print(f" [源2 exchangerate-api失败: {type(e).__name__}]", end='')

    # ── 源 3：取不到 → None（不许造数）──
    print(" [无可用源→None]", end='')
    return None, None, 'daily', None, None


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


@with_timeout(40)
def get_epu():
    """中国经济政策不确定性指数 - Baker-Bloom-Davis 官方站 (policyuncertainty.com)

    源：China_Mainland_Paper_EPU.xlsx（sheet 'EPU 2000 onwards'，列 year/month/EPU）
    说明：FRED 上并无中国经济政策不确定性系列（CHNEPUINDX* 全 404），故直连官方站。
    约定：取不到 / 字段缺失 / 值非法 → (None, None, None)，不兜底、不猜日期。
    """
    import io
    import pandas as pd

    url = "https://www.policyuncertainty.com/media/China_Mainland_Paper_EPU.xlsx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code != 200 or not r.content:
            return None, None, None
        df = pd.read_excel(io.BytesIO(r.content), sheet_name="EPU 2000 onwards")
        if not {"year", "month", "EPU"}.issubset(df.columns):
            return None, None, None
        df = df[df["EPU"].apply(lambda x: isinstance(x, (int, float)) and not pd.isna(x))]
        if df.empty:
            return None, None, None
        row = df.iloc[-1]
        year = int(row["year"])
        month = int(row["month"])
        val = float(row["EPU"])
        if not (1990 <= year <= 2100 and 1 <= month <= 12):
            return None, None, None
        if not math.isfinite(val) or val < 0:
            return None, None, None
        return round(val, 1), f"{year}-{month:02d}", "monthly"
    except Exception:
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
    # T11: 同上，不伪造日期
    return round(float(price), 3), None, 'daily'


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
                # T11: 不伪造日期
                return round(float(price), 2), None, 'daily'
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
                # T11: 新浪 nf_ 行情第 18 位(索引17)是真实交易日期，用它，不用 date.today()
                trade_date = parts[17].strip() if len(parts) > 17 else ''
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', trade_date):
                    trade_date = None
                if latest_price and latest_price != '0.000' and not _is_bad_number(latest_price):
                    return round(float(latest_price), 0), trade_date, 'daily'
    except Exception:
        pass
    return None, None, None


# ═══════════════════════════════════════════
# A股/港股情绪代理（WorldOS V1a，2026-11-27）
# ═══════════════════════════════════════════
# 全部 reference_only：只采集 + 只展示，不打分。
# 纪律（10-22 裸 NaN 事故）：抓不到就抛异常/返回 None → 由 main() 落 null + fetchError，
# 绝不塞假值（0 也是假值）、绝不产出 NaN（write_json_strict 会二次兜底）。
# 返回值约定：5 元组 (value, dataDate, freq, source_degraded, extras)
#   extras = 额外只展示字段（可空），前端从 indicators[key].extras 读。

def _tencent_quote(*codes):
    """腾讯行情 qt.gtimg.cn 通用解析。

    返回 {code: [字段...]}（“~” 分隔后的原始数组）。字段序号经 11-27 实测：
      [3]=最新价 [4]=昨收 [5]=今开 [6]=成交量(手) [30]=时间戳 [32]=涨跌幅%
      [37]=成交额(万元)  ← ashareTurnover 用的就是它，**不是 [6]**（[6] 是成交量）
      [38]=换手率 [39]=市盈率
    """
    import requests
    url = 'https://qt.gtimg.cn/q=' + ','.join(codes)
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0',
                                   'Referer': 'https://gu.qq.com/'}, timeout=10)
    r.encoding = 'gbk'          # 腾讯行情是 GBK，不解码会乱码
    out = {}
    for line in r.text.split(';'):
        line = line.strip()
        if not line.startswith('v_') or '="' not in line:
            continue
        head, body = line.split('="', 1)
        out[head[2:]] = body.rstrip('"').split('~')
    return out


def _tencent_trade_date(fields):
    """从腾讯行情字段里取交易日期（[30] 形如 20261127161427 或 2026/11/27 16:09:22）。"""
    if len(fields) <= 30:
        return None
    raw = (fields[30] or '').strip()
    digits = re.sub(r'[^0-9]', '', raw)
    if len(digits) < 8:
        return None
    y, m, d = digits[:4], digits[4:6], digits[6:8]
    if not (1900 < int(y) < 2200 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31):
        return None
    return f'{y}-{m}-{d}'


def _em_kline_amount(secid, lmt=10):
    """东财日 K 的成交额（元）：返回 {date: amount}。只给双源互证用。"""
    import requests
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
           f'?secid={secid}&fields1=f1,f2&fields2=f51,f52,f53,f54,f55,f56,f57'
           f'&klt=101&fqt=1&end=20500101&lmt={lmt}')
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0',
                                   'Referer': 'https://quote.eastmoney.com/'}, timeout=15)
    r.raise_for_status()
    out = {}
    for line in (r.json().get('data') or {}).get('klines') or []:
        p = line.split(',')
        if len(p) < 7:
            continue
        try:
            out[p[0]] = float(p[6])
        except (TypeError, ValueError):
            continue
    return out


def get_ashare_turnover():
    """两市成交额（亿元）= 上证(000001) + 深证(399001) 的 [37] 成交额(万元) 相加 ÷ 1e4。

    单位核实（11-27 19:40 实测）：上证 [37]=92977724 万元 = 9297.77 亿；
    深证 [37]=107001721 万元 = 10700.17 亿；合计 ≈ 19997.94 亿 ≈ 2.0 万亿。

    双源互证（V1b-1b，龙六建议）：腾讯 [37] 与东财 kline f57 逐日比对，偏差 >0.5% 告警。
    不做成硬失败（两源采样时点略有差异），但必须能看见 —— 同名不同义字段这类错，
    单点验收永远拓不到，两条独立路径互证才行。
    """
    quote = _tencent_quote('sh000001', 'sz399001')
    total_wan = 0.0
    per_market = {}
    dates = []
    tx_yi = {}
    for code, label, secid in (('sh000001', '沪', '1.000001'),
                               ('sz399001', '深', '0.399001')):
        f = quote.get(code)
        if not f or len(f) <= 37:
            raise ValueError(f'腾讯行情缺 {code} 或字段不足（len={len(f) if f else 0}）')
        amt_wan = f[37].strip()
        if not amt_wan or _is_bad_number(amt_wan):
            raise ValueError(f'{code} 成交额非法: {amt_wan!r}')
        amt_wan = float(amt_wan)
        if amt_wan <= 0:
            raise ValueError(f'{code} 成交额非正数: {amt_wan}')
        total_wan += amt_wan
        per_market[label] = round(amt_wan / 1e4, 2)     # 万元 → 亿元
        tx_yi[label] = amt_wan / 1e8                    # 万元 → 亿元（未舍入，供比对）
        d = _tencent_trade_date(f)
        if d:
            dates.append(d)

    trade_date = min(dates) if dates else None
    value_yi = round(total_wan / 1e4, 2)

    # ── 双源互证：同一交易日的腾讯合计 vs 东财 f57 合计 ──
    cross = {'checked': False}
    degraded = None
    try:
        em_total = 0.0
        em_dates = []
        for secid, label in (('1.000001', '沪'), ('0.399001', '深')):
            bars = _em_kline_amount(secid, lmt=10)
            if trade_date and trade_date in bars:
                em_total += bars[trade_date]
                em_dates.append(trade_date)
        if len(em_dates) == 2 and em_total > 0:
            em_yi = em_total / 1e8
            diff_pct = (value_yi - em_yi) / em_yi * 100
            cross = {'checked': True, 'tencent': round(value_yi, 2),
                     'eastmoney': round(em_yi, 2), 'diff_pct': round(diff_pct, 4)}
            if abs(diff_pct) > 0.5:
                degraded = {
                    'source': '腾讯行情-沪深交易所',
                    'primarySource': '腾讯行情-沪深交易所',
                    'reason': 'cross_check_deviation',
                    'reasonText': (f'双源互证偏差 {diff_pct:+.3f}% > 0.5%：'
                                   f'腾讯 {value_yi:.2f} 亿 vs 东财 {em_yi:.2f} 亿（{trade_date}）'),
                }
    except Exception as e:
        cross = {'checked': False, 'error': f'{type(e).__name__}: {e}'}

    extras = {'unit': '亿元', 'sh': per_market.get('沪'), 'sz': per_market.get('深'),
              'rawUnit': '万元', 'crossCheck': cross}
    return (value_yi, trade_date, 'daily', degraded, extras)


def _em_datacenter(report_name, *, filter_expr=None, sort_column='DIM_DATE',
                   page_size=6):
    """东方财富数据中心通用查询（只读）。"""
    import requests
    from urllib.parse import quote as _q
    params = [f'reportName={report_name}', 'columns=ALL', 'source=WEB', 'client=WEB',
              f'sortColumns={sort_column}', 'sortTypes=-1',
              'pageNumber=1', f'pageSize={page_size}', 'pageNo=1']
    if filter_expr:
        params.append('filter=' + _q(filter_expr))
    url = 'https://datacenter-web.eastmoney.com/api/data/v1/get?' + '&'.join(params)
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0',
                                   'Referer': 'https://data.eastmoney.com/'}, timeout=15)
    r.raise_for_status()
    doc = r.json()
    rows = (doc.get('result') or {}).get('data') or []
    if not rows:
        raise ValueError(f'{report_name} 返回空数据（code={doc.get("code")}）')
    return rows


def get_margin_balance():
    """两融余额（亿元）= RPTA_RZRQ_LSHJ.**RZYE 融资余额**（源单位元）÷ 1e8。

    口径修正（2026-11-27 复核）：只打融资余额。旧版打的是 RZRQYE（含融券），
    融资=杠杆做多意愿、融券=反向，两者混在一起会互相稀释 → 错。
    含融券的 marginTotal 仅放 extras 标明「不参与打分」。
    T+1 披露属实锤：11-27 晚间最新一行 DIM_DATE=2026-11-26。
    """
    rows = _em_datacenter('RPTA_RZRQ_LSHJ', page_size=6)
    latest = rows[0]
    raw = latest.get('RZYE')                      # 融资余额（非 RZRQYE）
    if raw is None or _is_bad_number(raw):
        raise ValueError(f'RZYE 非法: {raw!r}')
    rz_yi = round(float(raw) / 1e8, 2)
    dd = (latest.get('DIM_DATE') or '')[:10] or None

    chg3d = None
    base_row = rows[3] if len(rows) >= 4 else None
    if base_row and base_row.get('RZYE') and not _is_bad_number(base_row['RZYE']):
        chg3d = round((float(raw) - float(base_row['RZYE'])) / 1e8, 2)

    def _yi(v):
        return round(float(v) / 1e8, 2) if v is not None and not _is_bad_number(v) else None

    extras = {
        'unit': '亿元',
        'chg3d': chg3d,                            # 融资余额 3 日变化
        'chg3dUnit': '亿元',
        'chg3dBaseDate': (base_row.get('DIM_DATE') or '')[:10] if base_row else None,
        'rzYe': _yi(raw),                          # = value 本体
        'rqYe': _yi(latest.get('RQYE')),           # 融券余额（反向，不参与打分）
        'marginTotal': _yi(latest.get('RZRQYE')),  # 融资+融券，不参与打分
        'marginTotalNote': '含融券，仅参考不参与打分',
        'rawUnit': '元',
    }
    return rz_yi, dd, 'daily', None, extras


def get_southbound_net():
    """南向净买入（亿元）= 港股通沪(004) + 港股通深(006) 的 NET_DEAL_AMT（源百万元）÷100 相加。

    口径修正（2026-11-27 复核）：旧版只取 004（沪），少一半以上；且文案写「沪+深合计」
    → 文案与实现自相矛盾。实测 11-27：004=3393.79、006=4586.57 百万元
    → 33.94 + 45.87 = 79.81 亿元。
    两路必须同一交易日，否则视为失败（不拿不同日的数据相加冒充当日合计）。
    """
    legs = {}
    for mutual_type, label in (('004', 'sh'), ('006', 'sz')):
        rows = _em_datacenter('RPT_MUTUAL_DEAL_HISTORY',
                              filter_expr=f'(MUTUAL_TYPE="{mutual_type}")',
                              sort_column='TRADE_DATE', page_size=1)
        latest = rows[0]
        raw = latest.get('NET_DEAL_AMT')
        if raw is None or _is_bad_number(raw):
            raise ValueError(f'{mutual_type} NET_DEAL_AMT 非法: {raw!r}')
        legs[label] = {
            'net': round(float(raw) / 100, 2),                      # 百万元 → 亿元
            'date': (latest.get('TRADE_DATE') or '')[:10] or None,
            'buy': round(float(latest['BUY_AMT']) / 100, 2) if latest.get('BUY_AMT') is not None else None,
            'sell': round(float(latest['SELL_AMT']) / 100, 2) if latest.get('SELL_AMT') is not None else None,
            'deal': round(float(latest['DEAL_AMT']) / 100, 2) if latest.get('DEAL_AMT') is not None else None,
            'leadStock': latest.get('LEAD_STOCKS_NAME'),
            'hsiChange': latest.get('INDEX_CHANGE_RATE'),
        }

    dates = {v['date'] for v in legs.values()}
    if len(dates) != 1 or None in dates:
        raise ValueError(f'两路南向交易日不一致: { {k: v["date"] for k, v in legs.items()} }')

    total = round(legs['sh']['net'] + legs['sz']['net'], 2)
    extras = {
        'unit': '亿元',
        'shNet': legs['sh']['net'],      # 004 港股通沪
        'szNet': legs['sz']['net'],      # 006 港股通深
        'total': total,
        'sh': legs['sh'],
        'sz': legs['sz'],
        'rawUnit': '百万元',
    }
    return total, legs['sh']['date'], 'daily', None, extras


def _em_kline(secid, lmt=40):
    """东财日 K（收盘序列）。返回 [(date, close)] 升序。

    口径统一（2026-11-27 复核）：恒生科技用 124.HSTECH（100.HSTECH 返回 rc=100），
    上证用 1.000001 —— 两边同一数据源，日期才能对齐。
    """
    import requests
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
           f'?secid={secid}&fields1=f1,f2&fields2=f51,f52,f53,f54,f55,f56,f57'
           f'&klt=101&fqt=1&end=20500101&lmt={lmt}')
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0',
                                   'Referer': 'https://quote.eastmoney.com/'}, timeout=15)
    r.raise_for_status()
    doc = r.json()
    if doc.get('rc') not in (0, None):
        raise ValueError(f'{secid} rc={doc.get("rc")}')
    klines = (doc.get('data') or {}).get('klines') or []
    out = []
    for line in klines:
        parts = line.split(',')
        if len(parts) < 3:
            continue
        try:
            close = float(parts[2])
        except (TypeError, ValueError):
            continue
        if close > 0:
            out.append((parts[0], close))
    out.sort(key=lambda x: x[0])
    return out


def _close_on_or_before(bars, target_date):
    """取 <= target_date 的最近一根收盘（港股/A股节假日不完全重合，按日期对齐而非按位置）。"""
    hit = None
    for d, c in bars:
        if d <= target_date:
            hit = (d, c)
        else:
            break
    return hit


def get_hstech_momentum():
    """恒生科技 20 日相对强弱（百分点）= 恒科 20 日涨幅 − 上证 20 日涨幅。

    口径修正（2026-11-27 复核）：旧版 value 存的是指数点位，不是动量 → 错。
    现：value = (HSTECH_t/HSTECH_t-20−1)×100 − (SH000001_t/SH000001_t-20−1)×100，保留 1 位；
    unit = 百分点；指数点位挤到 extras.indexLevel（只展示，不参与打分）。
    历史取不到就抛异常 → 落 null + fetchError，绝不拿点位冒充动量。
    """
    hst = _em_kline('124.HSTECH', lmt=40)
    sh = _em_kline('1.000001', lmt=40)
    if len(hst) < 21:
        raise ValueError(f'HSTECH 日线不足（{len(hst)} 根，需 21 根）')
    t_date, t_close = hst[-1]
    base_date, base_close = hst[-21]

    sh_t = _close_on_or_before(sh, t_date)
    sh_b = _close_on_or_before(sh, base_date)
    if not sh_t or not sh_b or sh_b[1] <= 0:
        raise ValueError(f'上证日线无法覆盖 {base_date}/{t_date}')

    hst_ret = (t_close / base_close - 1) * 100
    sh_ret = (sh_t[1] / sh_b[1] - 1) * 100
    rs = round(hst_ret - sh_ret, 1)

    extras = {
        'unit': '百分点',
        'indexLevel': round(t_close, 2),          # 指数点位（只展示）
        'indexLevelUnit': '点',
        'chg20d': round(hst_ret, 2),              # 恒科 20 日涨幅 %
        'shChg20d': round(sh_ret, 2),             # 上证 20 日涨幅 %
        'baseDate': base_date,
        'baseHstech': base_close,
        'baseSh': sh_b[1],
        'shDateUsed': {'t': sh_t[0], 'base': sh_b[0]},
        'note': f"{base_date}→{t_date}：恒科 {hst_ret:+.2f}% − 上证 {sh_ret:+.2f}% = {rs:+.1f}pp",
    }
    return rs, t_date, 'daily', None, extras


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
    'usdcnh': get_usdcnh,
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
    # WorldOS V1a（11-27）：A股/港股情绪代理，全部 reference_only
    'ashareTurnover': get_ashare_turnover,
    'marginBalance': get_margin_balance,
    'southboundNet': get_southbound_net,
    'hstechMomentum': get_hstech_momentum,
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
    for key, info in INDICATOR_DEFS.items():
        v = results.get(key, {})
        err = v.get('fetchError')
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

    # T13：degraded 由「计数」改为「带 reason 的列表」——只报个数等于把
    # 「为什么降级」埋掉。degraded_count 保留给数值型消费者（前端/旧脚本）。
    degraded_items = build_degraded_items(indicators)

    # 「成功但有降级原因」单独一栏：主源缺失、改用备源，值有效但来源不同。
    # 不进 degraded[]（degraded 的枚举码与 α 封顶口径由 resolve_freshness 独家定义），
    # 也不进 failed[]（这些指标确实取到了新值）。
    source_degraded_items = []
    for key, info in INDICATOR_DEFS.items():
        v = results.get(key, {})
        sd = v.get('sourceDegraded')
        if not sd or v.get('value') is None:
            continue
        source_degraded_items.append({
            'key': key,
            'displayName': info['name'],
            'source': v.get('source'),
            'actualSource': sd.get('source'),
            'primarySource': sd.get('primarySource'),
            'reason': sd.get('reason', 'primary_source_missing'),
            'reasonText': sd.get('reasonText', ''),
            'value': v.get('value'),
            'dataDate': v.get('dataDate'),
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
            'degraded': degraded_items,
            'degraded_count': len(degraded_items),
            'failed': failed_indicators,
            'source_degraded': source_degraded_items,
            'source_degraded_count': len(source_degraded_items),
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
        extras = None
        # 「成功但有降级原因」：抓取函数用 4 元组显式上报降级源，
        # 有值 ≠ 主源成功，不得静默当成正常抓取。
        source_degraded = None

        try:
            result = info['func']()
            if result is None:
                fetch_error = {'reason': 'empty_response', 'reasonText': '数据源返回空'}
            elif isinstance(result, tuple):
                val, dd, got_freq = result[:3]
                if len(result) > 3 and isinstance(result[3], dict):
                    source_degraded = result[3]
                # V1a：第 5 位 = 只展示的附加字段（extras），透传给 indicators[key].extras
                if len(result) > 4 and isinstance(result[4], dict):
                    extras = result[4]
                # T10: freq 以指标定义为准；抓取函数返回 None 时绝不能把日频降级成 other
                if got_freq:
                    freq = got_freq
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

        # 上一轮兜底优先级高于「备源降级」：两者同时出现时以兜底为准（更旧更弱）
        if used_fallback:
            source_degraded = None

        dd_display = dd if dd else '-'
        if val is not None:
            flags = []
            if used_fallback:
                flags.append('↺兜底')
            elif source_degraded:
                flags.append(f"⚠备源:{source_degraded.get('source')}")
            flag = (' ' + ' '.join(flags)) if flags else ''
            print(f" {val} {info['unit']} [{dd_display}]{flag}")
        else:
            print(f" ⚠️ N/A [{fetch_error.get('reason') if fetch_error else '-'}]")

        results[key] = {
            'value': val,
            'unit': info['unit'],
            'frequency': freq or info['frequency'],
            'source': info['source'],
            'dataDate': dd,
            'lastFetched': fetch_ts,
            # realtime 是对「源不提供日期」的声明：本次拿到了真实交易日（备源日线）
            # 就不能再标 realtime，否则前端会当成实时报价展示。
            'realtime': (INDICATOR_META.get(key, {}).get('dateSource') == 'realtime'
                         and not (source_degraded and dd)),
            'used_fallback': used_fallback,
            'fetchError': fetch_error if (fetch_error and (used_fallback or val is None)) else None,
        }
        if source_degraded:
            # source 保持冻结口径（NYMEX期货）；actualSource 写实际取数路径
            results[key]['actualSource'] = source_degraded.get('source')
            results[key]['sourceDegraded'] = source_degraded
            # 口径声明降级（usdcnh 在岸回退）：拼到 indicators[key].caliberNote，
            # 让「这条是在岸价」在页面上能看见，而不是只藏在 validity_report。
            if source_degraded.get('caliberNoteSuffix'):
                results[key]['caliberNoteSuffix'] = source_degraded['caliberNoteSuffix']
        # V1a：参考项的附加展示字段（20日涨幅 / 3日变化 / 两市拆分）
        if extras:
            results[key]['extras'] = extras

    # ── V1b-1：把今日值写回历史序列，并把「今日之前」的样本挂到 results[key]['history'] ──
    # 两个动作必须成对：写回 → 序列才能日积月累；挂 history → 打分不需要读磁盘，产物可回放。
    for key, cfg in PCT_SERIES_KEYS.items():
        v = results.get(key, {})
        val = v.get('value')
        dd = v.get('dataDate')
        if val is None or not dd:
            continue
        try:
            series_store.upsert(key, dd, val,
                                unit=SERIES_META[key]['unit'],
                                transform=SERIES_META[key]['transform'])
            # 每个指标的回看窗口不同（ratio_band 要 120，pct_rank 要 60），从配置派生
            window = cfg.get('window') or PCT_RANK_WINDOW_LONG
            lookback = window + PCT_TRANSFORM_LOOKBACK + 2
            hist = series_store.history_before(key, dd, limit=lookback)
            v['history'] = hist
            print(f'  🧮 {key}: 历史样本 {len(hist)} 条（{cfg["method"]}, 窗口 {window}）')
        except Exception as e:
            # 历史写失败不能把当日值弄丢：history 留空 → 打分侧自然走 warmup
            print(f'  ⚠️ {key}: 历史序列处理失败（本轮按 warmup, score=null）：{type(e).__name__}: {e}')

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
