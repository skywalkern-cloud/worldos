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
    'quarterly': {'yellow_days': 120, 'red_days': 210},   # T13-3：200/400 → 120/240 → 120/210（红按发布节奏重推，见下）
    'yearly':    {'yellow_days': 180, 'red_days': 365},
    'other':     {'yellow_days': 60,  'red_days': 90},
}
```

季频口径：发布节奏 90 天/次，季末到首次发布约 +25 天（中/美 GDP 都在 20-30 天窗口）
⇒「当期值」的 `days_stale` 上限 ≈ 115 天（下一季数据出来之前）。
黄 = 错过 1 次发布 ≈ 115–205 天 → 取 120（下限附近，宁紧勿松）；
红 = 错过 2 次发布 ≈ >205 天 → 取 210。
旧值 200/400 把「发布滞后正常」当成了「数据陈旧可接受」；240 则是没走推导拍的数，
以 210 取代：红线必须卡在「第二次发布已该到而没到」那一刻之后，早 30 天才是真陈旧。

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

---

## 附：定点小数与 `rules_hash` 复现规格（T15，2026-11-09）

### 1. 定点小数（T15-1）

所有对外数值一律走 `indicator_meta.q(x, n)`，**禁用裸 `round()`**：
`round()` 是 banker's rounding（.5 取偶），且 float 无法精确表示 `0.07335`，
平局时结果不可预期。实测案例：`-0.2934 / 4.0 = -0.07335`，实现与测试各得一个值，谁都没错 —— 因为规则不存在。

| 字段 | 位数 |
|---|---|
| `ias.normalized` | 6 |
| `ias.score`（= normalized × ias_scale） | 2 |
| 维度 `score` | 3 |

舍入方式：**half-up-away-from-zero**，用 `Decimal` + `ROUND_HALF_UP`。

### 2. `rules_hash` 复现（T15-2）

`meta.rules_snapshot` 是当天所用规则的全量快照，`meta.rules_hash` 是它的指纹。
**任何第三方都必须能用下面五行独立复现同一个 hash**（不要调用实现里的函数来"验自己"）：

```python
canonical = json.dumps(rules_snapshot, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':'))
rules_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]
```

判读规则：
- 两个日期 `rules_hash` 相同 → 规则逐字节相同 → 分数可直接横比
- `rules_hash` 不同 → 必须用各自 `rules_snapshot` 重算后再比，禁止直接比历史分数
- `rules_snapshot` 缺失（2026-11-09 之前的产物）→ 视为"规则未知"，不可参与回测

### 3. `rules_hash` 变更必须标注类型（2026-11-09 新增纪律）

任何导致 `rules_hash` 变化的提交，commit message / 变更说明里**必须二选一写清**：

| 标注 | 含义 | 处理方式 |
|---|---|---|
| **规则变** | `rules_snapshot` 内容变了（阈值/权重/公式/档位） | 历史分数**不可横比**，必须用各自快照重算 |
| **序列化变** | 快照内容一字未变，只是 canonical 形式变了（分隔符、排序、编码） | 历史分数**仍可横比**，`rules_hash` 需重算但数值含义不变 |

理由：三个月后有人看到 `88cb8f040f89 → xxxx`，若 message 只写「重新生成数据」，
他分不清是规则改了还是格式改了——而这两种情况的处理方式完全相反。
实例：T15-2 把 canonical 从 `json.dumps` 默认分隔符（`', '` / `': '`）改为
`separators=(',', ':')`，hash 由 `aeeb74397588` 变为 `88cb8f040f89`，属**序列化变**，
规则内容一字未动，历史分数仍可横比。
