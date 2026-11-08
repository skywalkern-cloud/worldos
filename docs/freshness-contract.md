# 新鲜度契约（T13，2026-11-09 冻结）

单一真源：`scripts/indicator_meta.py` → `FRESHNESS_STATES` / `resolve_freshness()`
输出字段：`indicators[key].freshness`（图标）、`.freshness_level`（枚举）、`.timeliness`（α）、
`.degraded_reasons`（枚举码数组）。

## 五态互斥表

| 状态 | 图标 | freshness_level | α | 前提 |
|---|---|---|---|---|
| 已核验新鲜 | 🟢 | `fresh` | 1.0 | 有可解析日期且未超黄线 |
| 实时报价 | 🔵 | `realtime` | 1.0 | `realtime=true` **且** 无日期 |
| 时效未知 | ⚪ | `unknown` | **0.5** | 无日期（或不可解析）且非 realtime |
| 偏旧 | 🟡 | `stale` | 0.5 | 有日期且超黄线未超红线 |
| 过期 | 🔴 | `expired` | 0.0 | 有日期且超红线 |

补充规则：
- `realtime=true` 但**有日期** → 按日期判定（realtime 标记不足为凭，落回 🟢/🟡/🔴）。
- `used_fallback=true` → α 封顶 0.5，状态最高只能 `stale`/`unknown`；realtime 待遇取消。
- 无日期 → **永不**判 `fresh`。这一条是 T13-1 的核心：α=1.0 的语义是「已验证新鲜」，
  没日期时什么都没验证过；旧实现 `return 1.0  # 不惩罚` 造出假绿灯。

## 时效阈值（按数据所属期**末日**算自然日）

```python
TIMELINESS_RULES = {
    'daily':     {'yellow_days': 5,   'red_days': 10},
    'monthly':   {'yellow_days': 60,  'red_days': 90},
    'quarterly': {'yellow_days': 120, 'red_days': 240},   # T13-3：200/400 → 120/240
    'yearly':    {'yellow_days': 180, 'red_days': 365},
    'other':     {'yellow_days': 60,  'red_days': 90},
}
```

季频口径：发布节奏 90 天/次 → 黄 = 错过 1 次（90+30 缓冲），红 = 错过 2 次（180+60）。
旧值 200/400 把「发布滞后正常」当成了「数据陈旧可接受」。

## validity_report.degraded（契约变更）

```json
"degraded": [
  {"key":"usGdp","displayName":"GDP增速","reason":"no_date",
   "reasonText":"无数据所属期且非实时报价，时效未知（按偏旧 α=0.5 计权）",
   "dataDate":null,"days_stale":null,"timeliness":0.5,"freshness":"⚪","freshness_level":"unknown"}
],
"degraded_count": 1
```

- `degraded`：**列表**（旧版是整型计数），一条 indicator 可因多个原因出现多次。
- reason 枚举：`no_date` | `used_fallback`。
- `degraded_count`：数值型兼容字段（老消费者用）。
- 区分：`failed` = 没拿到值；`degraded` = 有值但可信度被削。

## 前端消费

- 图标文案统一走 `src/lib/caliber.ts::describeFreshness()`：🔵=实时报价，⚪=时效未知。
  老快照（图标仍是旧语义的 ⚪）以 `freshness_level` 为准兜底。
- 描灰（`dimmed`）只看「有日期的超阈值」，`days_stale=null` 不描灰（未知 ≠ 0 天）。
