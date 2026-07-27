#!/usr/bin/env python3
"""
WorldOS 数据解读评论生成器 v2.0 (LLM 版)

调用 DeepSeek V4 Flash API 生成每日评论，解决模板引擎文案重复问题。
如果 LLM 调用失败，自动 fallback 到模板引擎 (commentary_generator.py)。

输入:  public/data/market-data.json
       public/data/commentary.json (昨日评论，用于趋势对比)
输出:  public/data/commentary.json

环境变量:
  NO_PROXY=api.deepseek.com        API 调用不走代理
  DEEPSEEK_API_KEY                 可选，不设则从 auth-profiles.json 读取
"""

import json
import os
import random
import sys
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── 路径 ───
SCRIPT_DIR = Path(__file__).parent
WORKSPACE = SCRIPT_DIR.parent
MARKET_DATA_FILE = WORKSPACE / 'public' / 'data' / 'market-data.json'
COMMENTARY_FILE = WORKSPACE / 'public' / 'data' / 'commentary.json'

# ─── 维度配置（与 commentary_generator.py 一致）───
DIMENSION_ORDER = ['economic', 'inflation', 'liquidity', 'sentiment', 'resource', 'techGreen']
DIMENSION_META = {
    'economic':  {'name': '经济增长',   'icon': '📈', 'weight': 1.0},
    'inflation': {'name': '通胀与政策', 'icon': '💰', 'weight': 1.0},
    'liquidity': {'name': '流动性',     'icon': '💧', 'weight': 0.8},
    'sentiment': {'name': '市场情绪',   'icon': '🧠', 'weight': 0.8},
    'resource':  {'name': '资源与供应链', 'icon': '🛢️', 'weight': 0.6},
    'techGreen': {'name': '科技与绿色', 'icon': '🌱', 'weight': 0.4},
}
DIMENSION_INDICATORS = {
    'economic':  ['chinaGdp', 'chinaPmi', 'usGdp', 'servicePmi', 'electricity', 'usNonFarm'],
    'inflation': ['cpi', 'ppi', 'usCpi', 'corePce', 'fedRate'],
    'liquidity': ['lpr', 'dr007', 'm2', 'creditSpread', 'dollarIndex', 'usBond2Y', 'usBond5Y', 'usBond10Y'],
    'sentiment': ['vix', 'fearGreed'],
    'resource':  ['oilPrice', 'naturalGas', 'carbonPrice', 'lmeIndex', 'shanghaiCopper'],
    'techGreen': ['aiGrowth', 'robotInstall', 'evPenetration', 'renewEnergyInvest'],
}
INDICATOR_SHORT = {
    'chinaGdp':       'GDP增速',
    'chinaPmi':       '制造业PMI',
    'usGdp':          'GDP增速',
    'servicePmi':     '服务业PMI',
    'electricity':    '用电量',
    'usNonFarm':      '非农就业',
    'cpi':            'CPI',
    'ppi':            'PPI',
    'usCpi':          'CPI',
    'corePce':        '核心PCE',
    'fedRate':        '联邦基金利率',
    'lpr':            'LPR利率',
    'dr007':          'DR007',
    'm2':             'M2增速',
    'creditSpread':   '信用利差',
    'dollarIndex':    '美元指数',
    'usBond2Y':       '美债2Y',
    'usBond5Y':       '美债5Y',
    'usBond10Y':      '美债10Y',
    'vix':            'VIX',
    'fearGreed':      '恐惧贪婪指数',
    'oilPrice':       'WTI原油',
    'naturalGas':     '天然气',
    'carbonPrice':    '碳价',
    'lmeIndex':       'LME铜期货',
    'shanghaiCopper': '沪铜期货',
    'aiGrowth':       'AI产业增速',
    'robotInstall':   '工业机器人增速',
    'evPenetration':  '新能源渗透率',
    'renewEnergyInvest': '新能源指数',
}
INDICATOR_COUNTRY = {
    'chinaGdp': '🇨🇳', 'chinaPmi': '🇨🇳', 'usGdp': '🇺🇸', 'servicePmi': '🇨🇳',
    'electricity': '🇨🇳', 'usNonFarm': '🇺🇸', 'cpi': '🇨🇳', 'ppi': '🇨🇳',
    'usCpi': '🇺🇸', 'corePce': '🇺🇸', 'fedRate': '🇺🇸', 'lpr': '🇨🇳',
    'dr007': '🇨🇳', 'm2': '🇨🇳', 'creditSpread': '🌐', 'dollarIndex': '🌐',
    'usBond2Y': '🇺🇸', 'usBond5Y': '🇺🇸', 'usBond10Y': '🇺🇸',
    'vix': '🇺🇸', 'fearGreed': '🌐', 'oilPrice': '🌐', 'naturalGas': '🌐',
    'carbonPrice': '🇨🇳', 'lmeIndex': '🌐', 'shanghaiCopper': '🇨🇳', 'aiGrowth': '🇨🇳', 'robotInstall': '🇨🇳',
    'evPenetration': '🇨🇳', 'renewEnergyInvest': '🇨🇳',
}


# ═══════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════

def _is_numeric(val) -> bool:
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return True
    try:
        float(str(val))
        return True
    except (ValueError, TypeError):
        return False


def get_indicator(indicators: dict, key: str) -> dict:
    """安全获取指标数据"""
    default = {'value': None, 'score': None, 'signal': 'gray', 'unit': '', 'name': key}
    ind = indicators.get(key)
    if not ind:
        return default
    result = {**default, **ind}
    if not _is_numeric(result['value']):
        result['value'] = None
        result['score'] = None
    return result


def _extract_highlights(dim_id: str, indicators: dict) -> list:
    """提取板块关键指标快照（前端高亮展示用）"""
    indicator_keys = DIMENSION_INDICATORS.get(dim_id, [])
    highlights = []
    for key in indicator_keys:
        ind = get_indicator(indicators, key)
        if ind.get('value') is not None:
            unit = ind.get('unit', '')
            name = INDICATOR_SHORT.get(key, key)
            country = INDICATOR_COUNTRY.get(key, '')
            highlights.append({
                'indicator': key,
                'value': ind['value'],
                'unit': unit,
                'key': f"{country}{name}",
            })
    return highlights


def load_prev_commentary(filepath: Optional[Path] = None) -> Optional[dict]:
    """加载上一轮评论数据（用于 LLM prompt 中的趋势对比）"""
    if filepath is None:
        filepath = COMMENTARY_FILE
    if filepath and filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"  ⚠️  读取昨日评论失败: {e}")
    return None


def read_api_key() -> str:
    """从 auth-profiles.json 读取 DeepSeek API Key"""
    # 优先从环境变量读取（方便测试）
    env_key = os.environ.get('DEEPSEEK_API_KEY')
    if env_key:
        return env_key

    auth_file = Path.home() / '.openclaw' / 'agents' / 'main' / 'auth-profiles.json'
    try:
        with open(auth_file, 'r', encoding='utf-8') as f:
            auth = json.load(f)
        return auth['profiles']['deepseek:default']['key']
    except Exception as e:
        print(f"  ❌ 读取 API Key 失败: {e}")
        raise


# ═══════════════════════════════════════════
# LLM Prompt 构造
# ═══════════════════════════════════════════

def build_prompt(indicators: dict, meta: dict, prev_commentary: Optional[dict] = None) -> str:
    """构造发送给 LLM 的 prompt"""
    ias = meta.get('ias', {})
    dims = meta.get('dimensions', {})

    # ── 每日随机切入角度 ──
    ANGLES = [
        "数据中的最大反差",
        "本周趋势转折信号",
        "被低估/被高估的指标",
        "跨维度共振分析（如通胀+流动性联动）",
        "中美政策博弈视角",
        "产业链上下游传导",
        "风险预警视角",
        "机会挖掘视角",
        "历史对比（与过去N周对比）",
        "外部冲击压力测试",
    ]
    chosen_angle = random.choice(ANGLES)

    # ── 数据摘要 ──
    data_section = []
    data_section.append("## 当前市场数据")

    for dim_id in DIMENSION_ORDER:
        dim_info = DIMENSION_META.get(dim_id, {})
        dim_data = dims.get(dim_id, {})
        data_section.append(f"\n### {dim_info.get('icon', '')} {dim_info.get('name', dim_id)}")
        data_section.append(f"维度评分: {dim_data.get('score', 0):+.3f}, 信号: {dim_data.get('signal', 'gray')}")
        data_section.append("| 指标名 | 值 | 评分 | 信号 | 趋势 | 国家 |")
        data_section.append("|--------|----|------|------|------|------|")

        for key in DIMENSION_INDICATORS.get(dim_id, []):
            ind = get_indicator(indicators, key)
            val = ind.get('value')
            val_str = f"{val:.2f}" if isinstance(val, (int, float)) else str(val)
            score = ind.get('score')
            score_str = f"{score:+.3f}" if isinstance(score, (int, float)) else str(score)
            trend = ind.get('trend', 'neutral')
            unit = ind.get('unit', '')
            country = INDICATOR_COUNTRY.get(key, '')
            data_section.append(f"| {key} ({INDICATOR_SHORT.get(key, key)}) | {val_str} {unit} | {score_str} | {ind.get('signal', 'gray')} | {trend} | {country} |")

    data_section.append(f"\n### IAS 综合")
    data_section.append(f"IAS 评分: {ias.get('score', 0):+.3f}")
    data_section.append(f"IAS 信号: {ias.get('signal', '持有')}")
    data_section.append(f"建议仓位: {ias.get('position', '40-60%')}")

    # ── 昨日评论参考 ──
    prev_section = ""
    if prev_commentary:
        prev_section = """
## 昨日评论参考（用于对比今日变化，不要直接复制）
""" + json.dumps({
            'ias_summary': prev_commentary.get('ias', {}).get('summary', '')[:500],
            'dimension_summaries': {
                dim: prev_commentary.get('dimensions', {}).get(dim, {}).get('commentary', '')[:300]
                for dim in DIMENSION_ORDER
            },
            'keyDivergences': prev_commentary.get('ias', {}).get('keyDivergences', []),
            'keyRisks': prev_commentary.get('ias', {}).get('keyRisks', []),
        }, ensure_ascii=False, indent=2)

    # ── Agent 身份和指令 ──
    prompt = f"""你是一位专业投资分析师，正在为 WorldOS 投资监控系统撰写每日市场评论。

## 今日切入角度：{chosen_angle}
请以「{chosen_angle}」为主要切入角度来构思今日评论。从数据中挖掘与此角度相关的内容，避免泛泛而谈。

## 核心要求

1. **基于实际数据**：所有数值和趋势判断必须来自下方"当前市场数据"表格，不得编造。
2. **信息密度要高**：不是流水账念指标，而是做交叉分析、归因分析。
3. **中文输出**：使用简体中文，Markdown 格式。
4. **加粗关键数值**：所有重要数字用 **加粗** 强调。

## ⚠️ 必须做到的差异化
1. **首句**必须对比今天和昨天 IAS 评分变化（例如"📍 本期评分 **-0.33**，较昨日的 **-0.28** 继续走弱"）
2. **每个维度解读**中，至少有一句指出与昨日相比的变化（数值增减、信号转变、趋势加强/减弱）
3. 如果今日数据与昨日完全相同，写"今日数据未更新"并用历史趋势分析代替

## 输出要求

严格按照以下 JSON 结构输出（只输出 JSON，不要加注释或代码块标记）：

```json
{{
  "ias": {{
    "summary": "<IAS 整体解读，约300-400字，包含：总览、核心矛盾、尾部风险、策略建议>",
    "keyDivergences": ["<矛盾1，不超过50字>", "<矛盾2>", "<矛盾3>"],
    "keyRisks": ["<风险1，不超过50字>", "<风险2>"]
  }},
  "dimensions": {{
    "economic": {{
      "commentary": "<经济增长维度解读，约100-200字，以关键结论开头，进行中美交叉分析>"
    }},
    "inflation": {{
      "commentary": "<通胀与政策维度解读，约100-200字，突出中美通胀分化及货币政策方向>"
    }},
    "liquidity": {{
      "commentary": "<流动性维度解读，约100-200字，国内宽松vs美债压制>"
    }},
    "sentiment": {{
      "commentary": "<市场情绪维度解读，约100-200字，VIX和市场情绪>"
    }},
    "resource": {{
      "commentary": "<资源与供应链维度解读，约100-200字，能源、碳价、铜价等>"
    }},
    "techGreen": {{
      "commentary": "<科技与绿色维度解读，约100-200字，新能源渗透率与科技升级>"
    }}
  }}
}}
```

## 要有观点
不要写安全无趣的中性话。对于每个有数据支撑的判断，给一个明确的观点：
- "我们认为XX指标被市场低估/高估"
- "中美XX分化正在加剧/收敛"
- "值得警惕的是…"
- "被忽视的信号是…"

## IAS 整体解读(ias.summary) 要点
- 首句总览：IAS评分 **{ias.get('score', 0):+.2f}**（信号），整体信号方向
- 核心矛盾提炼：找 2-3 个数据中最突出的矛盾
- 尾部风险提示：找 2 个尾部风险
- 策略建议：投资方向
- 段落之间用换行分隔

## 各维度解读要点
- 首句给出维度评分和方向判断
- 分国家/地区分析主要指标的变动含义
- 做交叉分析（如PPI-CPI剪刀差、中美利差、产业热vs资本冷）
- 给出结论或判断
- 不要罗列所有指标，挑最重要的 2-4 个

## 已有昨日评论
参考以下昨日评论，重点说出**今日的变化和差异**：
{prev_section}

## 当前市场数据
{data_section}
"""

    return prompt


# ═══════════════════════════════════════════
# LLM API 调用
# ═══════════════════════════════════════════

def call_llm(prompt: str) -> Optional[dict]:
    """调用 DeepSeek V4 Flash API 解析评论"""
    api_key = read_api_key()

    # 确保 NO_PROXY 环境变量已设
    os.environ.setdefault('NO_PROXY', 'api.deepseek.com')
    os.environ.setdefault('HTTP_PROXY', '')
    os.environ.setdefault('HTTPS_PROXY', '')

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )

        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "你是一位专业投资分析师。你只输出有效的 JSON，不含任何注释、代码块标记或额外说明。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        print(f"  ✅ LLM 响应成功, tokens: {response.usage.total_tokens}")
        return json.loads(content)

    except Exception as e:
        print(f"  ❌ LLM 调用失败: {e}")
        return None


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

def generate_commentary_llm(indicators: dict, meta: dict, prev_commentary: Optional[dict] = None) -> Optional[dict]:
    """
    使用 LLM 生成评论

    Returns:
        dict if successful, None if LLM failed
    """
    dims = meta.get('dimensions', {})
    ias = meta.get('ias', {'score': 0, 'signal': '持有', 'position': '40-60%', 'signal_icon': '➖'})

    # ── 构造 prompt 并调用 LLM ──
    prompt = build_prompt(indicators, meta, prev_commentary)
    print(f"  📝 Prompt 长度: {len(prompt)} chars")

    result = call_llm(prompt)
    if not result:
        return None

    # ── 校验 LLM 输出结构 ──
    required_keys = ['ias', 'dimensions']
    for k in required_keys:
        if k not in result:
            print(f"  ❌ LLM 输出缺少字段: {k}")
            return None

    required_dim_keys = ['economic', 'inflation', 'liquidity', 'sentiment', 'resource', 'techGreen']
    for k in required_dim_keys:
        if k not in result.get('dimensions', {}):
            print(f"  ❌ LLM 输出缺少维度字段: {k}")
            return None

    # ── 构建最终输出 ──
    now = datetime.now().isoformat()

    # 从 LLM 解析的 ias 中提取
    llm_ias = result.get('ias', {})
    llm_dims = result.get('dimensions', {})

    # 构建最终 commentary
    commentary = {
        'version': '1.0',
        'generatedAt': now,
        'dataTimestamp': now,
        'ias': {
            'score': ias.get('score', 0),
            'signal': ias.get('signal', '持有'),
            'summary': llm_ias.get('summary', ''),
            'keyDivergences': llm_ias.get('keyDivergences', []),
            'keyRisks': llm_ias.get('keyRisks', []),
        },
        'dimensions': {},
    }

    for dim_id in DIMENSION_ORDER:
        dim = dims.get(dim_id, {})
        llm_dim = llm_dims.get(dim_id, {})
        highlights = _extract_highlights(dim_id, indicators)
        commentary['dimensions'][dim_id] = {
            'score': dim.get('score', 0),
            'signal': dim.get('signal', 'gray'),
            'commentary': llm_dim.get('commentary', ''),
            'highlights': highlights,
        }

    # ── 相似度检测：与昨日评论对比 ──
    if prev_commentary:
        today_summary = commentary['ias']['summary']
        yesterday_summary = prev_commentary.get('ias', {}).get('summary', '')
        if yesterday_summary:
            similarity = SequenceMatcher(None, today_summary, yesterday_summary).ratio()
            print(f"  🔍 与昨日评论相似度: {similarity:.3f}")
            if similarity > 0.7:
                print(f"  ⚠️  相似度 {similarity:.3f} > 0.7，过于相似，重新生成…")
                # 重新调用 LLM，prompt 追加差异指令
                retry_prompt_extra = f"""

## ⚠️ 上次生成的评论与昨日过于相似（相似度{similarity:.2f}），请务必写出明显不同的内容。
- 换个切入角度
- 不要复制昨日的句式结构和结论
- 找到数据中昨日未提及的细节或角度
- 使用完全不同的表达方式
"""
                new_prompt = prompt + retry_prompt_extra
                print(f"  🔄 重试 Prompt 长度: {len(new_prompt)} chars")
                retry_result = call_llm(new_prompt)
                if retry_result:
                    # 校验重试结果
                    if 'ias' in retry_result and 'dimensions' in retry_result:
                        for k in required_dim_keys:
                            if k not in retry_result.get('dimensions', {}):
                                print(f"  ❌ 重试输出仍缺少维度字段: {k}")
                                break
                        else:
                            # 重试结果可用，更新 commentary
                            retry_ias = retry_result.get('ias', {})
                            commentary['ias']['summary'] = retry_ias.get('summary', commentary['ias']['summary'])
                            commentary['ias']['keyDivergences'] = retry_ias.get('keyDivergences', commentary['ias']['keyDivergences'])
                            commentary['ias']['keyRisks'] = retry_ias.get('keyRisks', commentary['ias']['keyRisks'])
                            for dim_id in DIMENSION_ORDER:
                                retry_dim = retry_result.get('dimensions', {}).get(dim_id, {})
                                if retry_dim.get('commentary'):
                                    commentary['dimensions'][dim_id]['commentary'] = retry_dim['commentary']
                            print(f"  ✅ 重试生成成功，已替换评论内容")

    return commentary


def fallback_template(indicators: dict, meta: dict, prev_commentary: Optional[dict] = None) -> dict:
    """Fallback 到旧模板引擎"""
    print("  ⚠️  Fallback 到模板引擎...")
    from commentary_generator import generate_commentary
    return generate_commentary(indicators, meta, prev_commentary)


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

def main():
    """主函数：读取数据 → LLM 生成 → 保存 → 打印摘要"""
    print(f"{'='*60}")
    print(f"  WorldOS 评论生成器 v2.0 (LLM)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 1. 读取市场数据
    if not MARKET_DATA_FILE.exists():
        print(f"  ❌ 未找到 market-data.json: {MARKET_DATA_FILE}")
        sys.exit(1)

    with open(MARKET_DATA_FILE, 'r', encoding='utf-8') as f:
        market_data = json.load(f)

    indicators = market_data.get('indicators', {})
    meta = market_data.get('meta', {})

    if not indicators or not meta:
        print("  ❌ market-data.json 数据不完整")
        sys.exit(1)

    print(f"  📊 指标数量: {len(indicators)}")
    print(f"  📊 维度数量: {len(meta.get('dimensions', {}))}")

    # 2. 加载昨日评论
    prev = load_prev_commentary()
    if prev:
        print(f"  📖 已加载昨日评论")

    # 3. LLM 生成
    commentary = generate_commentary_llm(indicators, meta, prev)

    # 4. Fallback
    if commentary is None:
        print("  ⚠️  LLM 生成失败，触发 fallback")
        commentary = fallback_template(indicators, meta, prev)

    # 5. 保存
    out_path = WORKSPACE / 'public' / 'data' / 'commentary.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(commentary, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 评论已保存: {out_path}")
    print(f"  📋 版本: {commentary['version']}")
    print(f"  🕐 生成时间: {commentary['generatedAt']}")

    # 6. 打印摘要
    print(f"\n{'='*60}")
    print("IAS 整体解读:")
    print(f"{'='*60}")
    print(commentary['ias']['summary'][:500])
    if len(commentary['ias']['summary']) > 500:
        print("...（已截断）")

    for dim_id in DIMENSION_ORDER:
        dc = commentary['dimensions'].get(dim_id, {})
        dm = DIMENSION_META.get(dim_id, {})
        print(f"\n{dm.get('icon', '')} {dm.get('name', dim_id)} ({dc.get('score', 0):+.2f})")
        print("-" * 40)
        print(dc.get('commentary', '')[:200])

    print(f"\n{'='*60}")
    print("  完成！")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
