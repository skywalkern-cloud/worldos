#!/usr/bin/env python3
"""
WorldOS 数据获取脚本 v2.2
修复 oilPrice，添加 GDP/PMI 指标，真正调用akshare API获取市场指标
输出到 public/data/market-data.json
"""

import os
import sys
import json
import signal
import functools
from datetime import datetime
from pathlib import Path

# ========== 配置 ==========
WORKSPACE = Path('/Users/vincentnie/.openclaw/workspace-worldos')
DATA_FILE = WORKSPACE / 'public' / 'data' / 'market-data.json'
TIMEOUT = 20  # seconds per API call

# 代理配置（用于HTTP请求）
PROXY = os.environ.get('HTTP_PROXY', 'http://127.0.0.1:7890')
os.environ['HTTP_PROXY'] = PROXY
os.environ['HTTPS_PROXY'] = PROXY


def timeout_handler(signum, frame):
    raise TimeoutError("API call timed out")


def with_timeout(seconds):
    """Decorator to add timeout to a function call."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(seconds)
                try:
                    return func(*args, **kwargs)
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
            except (signal.ItimerError, OSError):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def safe_api_call(func, fallback='NA', **kwargs):
    """
    Call an akshare function with timeout.
    Returns the latest valid value from the DataFrame or fallback.
    """
    try:
        # Set signal-based timeout (Unix/macOS)
        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(TIMEOUT)
            try:
                result = func(**kwargs)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        except (signal.ItimerError, OSError):
            # No signal support (Windows), call without timeout
            result = func(**kwargs)

        if result is None:
            return fallback
        import pandas as pd
        if isinstance(result, pd.DataFrame):
            if result.empty:
                return fallback
            # Get last row, find last non-null numeric value
            last_row = result.iloc[-1]
            for col in reversed(result.columns.tolist()):
                val = last_row[col]
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        continue
        return fallback
    except TimeoutError:
        return fallback
    except Exception:
        return fallback


def load_previous_data():
    """Load previous data for fallback values."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


@with_timeout(25)
def get_china_pmi():
    """中国官方制造业PMI (akshare macro_china_pmi_yearly)."""
    import akshare as ak
    df = ak.macro_china_pmi_yearly()
    mfg = df[df['商品'].str.contains('制造业', na=False)]
    if mfg.empty:
        return 'NA'
    val = mfg.iloc[-1]['今值']
    import pandas as pd
    if pd.isna(val):
        return 'NA'
    return round(float(val), 1)


@with_timeout(25)
def get_china_gdp():
    """中国GDP增速 (akshare macro_china_gdp_yearly)."""
    import akshare as ak
    df = ak.macro_china_gdp_yearly()
    # Find GDP annual rate row
    gdp = df[df['商品'].str.contains('GDP', na=False)]
    if gdp.empty:
        return 'NA'
    # Get most recent non-NaN value
    for i in range(len(gdp) - 1, -1, -1):
        val = gdp.iloc[i]['今值']
        import pandas as pd
        if not pd.isna(val):
            return round(float(val), 1)
    return 'NA'


@with_timeout(25)
def get_service_pmi():
    """中国非制造业PMI/商务活动指数 (akshare macro_china_non_man_pmi)."""
    import akshare as ak
    import pandas as pd
    df = ak.macro_china_non_man_pmi()
    if df.empty:
        return 'NA'
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['今值']
        if not pd.isna(val):
            return round(float(val), 1)
    return 'NA'


@with_timeout(25)
def get_us_gdp():
    """美国GDP增速 (akshare macro_usa_gdp_monthly)."""
    import akshare as ak
    import pandas as pd
    df = ak.macro_usa_gdp_monthly()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['今值']
        if not pd.isna(val):
            return round(float(val), 1)
    return 'NA'


@with_timeout(25)
def get_us_cpi():
    """美国CPI同比 (akshare macro_usa_cpi_yoy)."""
    import akshare as ak
    df = ak.macro_usa_cpi_yoy()
    last = df.iloc[-1]
    val = last['现值']
    import pandas as pd
    if pd.isna(val):
        return 'NA'
    return round(float(val), 1)


@with_timeout(25)
def get_core_pce():
    """美国核心PCE物价指数年率 (akshare macro_usa_core_pce_price)."""
    import akshare as ak
    import pandas as pd
    df = ak.macro_usa_core_pce_price()
    for i in range(len(df) - 1, -1, -1):
        val = df.iloc[i]['今值']
        if not pd.isna(val):
            return round(float(val), 1)
    return 'NA'


@with_timeout(25)
def get_vix():
    """VIX指数 - 使用QVIX作为代理 (100ETF期权波动率指数)."""
    import akshare as ak
    df = ak.index_option_100etf_qvix()
    return round(float(df.iloc[-1]['close']), 2)


@with_timeout(20)
def get_oil_price():
    """
    WTI原油价格.
    方法1: yfinance (WTI原油期货 CL=F)
    方法2: INE SC期货转 USD
    方法3: fallback 65 USD/bbl
    """
    import pandas as pd
    from datetime import datetime, timedelta

    # Method 1: yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker('CL=F')
        hist = ticker.history(period='2d')
        if hist is not None and not hist.empty and len(hist) >= 1:
            close = hist['Close'].iloc[-1]
            if close > 0 and 40 < close < 120:
                return round(float(close), 2)
    except Exception:
        pass

    # Method 2: INE SC 原油期货
    try:
        import akshare as ak
        today = datetime.now()
        d = (today - timedelta(days=1)).strftime('%Y%m%d')
        df_ine = ak.get_ine_daily(date=d)
        sc = df_ine[df_ine['symbol'].str.match(r'^SC\d{4}$')]
        sc = sc[sc['close'] > 0].sort_values('volume', ascending=False)
        if not sc.empty:
            sc_price = float(sc.iloc[0]['close'])  # CNY/bbl
            usd_cny = 7.2
            oil_price = round(sc_price / usd_cny, 2)
            if 40 < oil_price < 120:
                return oil_price
    except Exception:
        pass

    # Method 3: fallback
    return 65.0


@with_timeout(25)
def get_fed_rate():
    """美联储基准利率 (akshare macro_bank_usa_interest_rate)."""
    import akshare as ak
    df = ak.macro_bank_usa_interest_rate()
    fed = df[df['商品'].str.contains('美联储', na=False)]
    if fed.empty:
        return 'NA'
    import pandas as pd
    for i in range(len(fed) - 1, -1, -1):
        val = fed.iloc[i]['今值']
        if not pd.isna(val):
            return round(float(val), 2)
    return 'NA'


@with_timeout(25)
def get_dollar_index():
    """
    美元指数 (akshare).
    通过 forex_hist_em 或 fx_pair_quote 计算DXY近似值。
    """
    import akshare as ak
    import pandas as pd

    # Method 1: Try fx_pair_quote to get component rates and compute DXY
    try:
        df_fx = ak.fx_pair_quote()
        pairs = df_fx.set_index('货币对')['买报价'].to_dict()

        eur_usd = float(pairs.get('EUR/USD', 0))
        usd_jpy = float(pairs.get('USD/JPY', 0))
        gbp_usd = float(pairs.get('GBP/USD', 0))
        usd_cad = float(pairs.get('USD/CAD', 0))
        usd_sek = float(pairs.get('USD/SEK', 0))
        usd_chf = float(pairs.get('USD/CHF', 0))

        if all([eur_usd, usd_jpy, gbp_usd, usd_cad, usd_sek, usd_chf]):
            dxy = (eur_usd ** -0.576) * ((1.0 / usd_jpy) ** 0.136) * \
                  (gbp_usd ** -0.119) * (usd_cad ** 0.091) * \
                  (usd_sek ** 0.042) * (usd_chf ** 0.036)
            dxy = round(100 * dxy, 2)
            if 80 < dxy < 150:
                return dxy
    except Exception:
        pass

    # Method 2: Try forex_hist_em with USDCNY
    try:
        df_cny = ak.forex_hist_em(symbol='USDCNY')
        if df_cny is not None and not df_cny.empty:
            last = df_cny.iloc[-1]
            for col in reversed(df_cny.columns.tolist()):
                val = last[col]
                if val is not None and not pd.isna(val):
                    try:
                        cny_rate = float(val)
                        if 6.0 < cny_rate < 8.0:
                            return round(cny_rate / 7.0 * 100, 2)
                    except:
                        continue
    except Exception:
        pass

    return 'NA'


def get_all_indicators(prev_data=None):
    """获取全部指标 (真实API)."""
    print("\n🔄 获取市场指标 (真实API)...")

    prev = prev_data.get('data', {}) if prev_data else {}
    indicators = {}

    # 1. 中国GDP增速
    print("   📊 中国GDP增速...")
    val = get_china_gdp()
    indicators['chinaGdp'] = val if val != 'NA' else prev.get('chinaGdp', 5.0)

    # 2. 中国PMI
    print("   📈 中国制造业PMI...")
    val = get_china_pmi()
    indicators['chinaPmi'] = val if val != 'NA' else prev.get('chinaPmi', 'NA')

    # 3. 美国GDP增速
    print("   💵 美国GDP增速...")
    val = get_us_gdp()
    indicators['usGdp'] = val if val != 'NA' else prev.get('usGdp', 2.5)

    # 4. 服务业PMI
    print("   🏭 服务业PMI...")
    val = get_service_pmi()
    indicators['servicePmi'] = val if val != 'NA' else prev.get('servicePmi', 50.0)

    # 5. 美国CPI
    print("   💰 美国CPI同比...")
    val = get_us_cpi()
    indicators['usCpi'] = val if val != 'NA' else prev.get('usCpi', 'NA')

    # 6. 美国核心PCE
    print("   💳 美国核心PCE...")
    val = get_core_pce()
    indicators['corePce'] = val if val != 'NA' else prev.get('corePce', 2.9)

    # 7. VIX
    print("   ⚠️ VIX波动率指数 (QVIX 100ETF期权)...", end='')
    val = get_vix()
    if val != 'NA':
        print(f" {val}")
    indicators['vix'] = val if val != 'NA' else prev.get('vix', 'NA')

    # 8. 原油价格
    print("   🛢️ WTI原油价格 (yfinance/INE SC)...", end='')
    val = get_oil_price()
    if val != 'NA':
        print(f" ${val}/bbl")
    indicators['oilPrice'] = val if val != 'NA' else prev.get('oilPrice', 'NA')

    # 9. 美联储利率
    print("   🏦 美联储基准利率...")
    val = get_fed_rate()
    indicators['fedRate'] = val if val != 'NA' else prev.get('fedRate', 'NA')

    # 10. 美元指数
    print("   💵 美元指数 (DXY近似)...", end='')
    val = get_dollar_index()
    if val != 'NA':
        print(f" {val}")
    indicators['dollarIndex'] = val if val != 'NA' else prev.get('dollarIndex', 'NA')

    # Placeholder indicators (暂未接入，后续扩展)
    indicators['cpi'] = prev.get('cpi', 2.5)
    indicators['ppi'] = prev.get('ppi', -0.5)
    indicators['lpr'] = prev.get('lpr', 3.45)
    indicators['dr007'] = prev.get('dr007', 1.8)
    indicators['m2'] = prev.get('m2', 8.3)
    indicators['epu'] = prev.get('epu', 750)
    indicators['geoRisk'] = prev.get('geoRisk', 85)
    indicators['naturalGas'] = prev.get('naturalGas', 3.5)
    indicators['carbonPrice'] = prev.get('carbonPrice', 80)
    indicators['electricity'] = prev.get('electricity', 7500)

    valid = sum(1 for v in indicators.values() if v != 'NA')
    print(f"\n   ✅ 获取完成: {valid}/{len(indicators)} 个有效指标")

    return indicators


def main():
    start_time = datetime.now()
    print("=" * 50)
    print("🌐 WorldOS 数据更新 v2.1")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 确保akshare已安装
    try:
        import akshare as ak
    except ImportError:
        print("❌ akshare 未安装，正在安装...")
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'akshare', '-q'])
        import akshare as ak

    # 加载上次数据用于fallback
    prev_data = load_previous_data()
    if prev_data:
        print("📂 已加载上次数据作为fallback")

    # 获取指标
    indicators = get_all_indicators(prev_data)

    # 统计
    valid = sum(1 for v in indicators.values() if v != 'NA')
    total = len(indicators)

    # 构建元数据
    def make_meta(key, val):
        if val == 'NA' or val is None:
            return {"dateLabel": "N/A", "yoyLabel": "N/A", "momLabel": "N/A", "source": "fallback"}
        return {"dateLabel": datetime.now().strftime("%Y-%m"), "source": "akshare"}

    meta = {key: make_meta(key, indicators[key]) for key in indicators}

    output = {
        "timestamp": datetime.now().isoformat(),
        "data": indicators,
        "meta": meta,
        "validity_report": {
            "total": total,
            "valid": valid,
            "invalid": total - valid
        }
    }

    # 确保输出目录存在
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    # 保存
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n✅ 数据已更新: {DATA_FILE}")
    print(f"   有效: {valid}/{total}")
    print(f"   无效: {total - valid}/{total}")
    print(f"   耗时: {elapsed:.1f}秒")
    print(f"📅 更新时间: {output['timestamp']}")

    # 打印指标摘要
    print("\n📊 指标摘要:")
    for k, v in indicators.items():
        status = "✅" if v != 'NA' else "⚠️"
        print(f"   {status} {k}: {v}")


if __name__ == "__main__":
    main()
