# Phase -1b 流动性可行性检测报告

生成时间：2026-06-20

---

## 1. 检测目标

验证 Kalshi NBA 市场的实际成交频率，判断 latency arbitrage 策略方向是否现实可行。

判定标准（来自 CLAUDE.md）：
- 关键时段成交间隔中位数 ≤ 30s → **可行**，继续原计划
- 30s–2min → 降低信号灵敏度预期，继续但需明确限制
- 普遍 > 2min → Kill Criteria，转向 mispricing 方向

---

## 2. 数据来源

- API：`https://api.elections.kalshi.com/trade-api/v2/historical/trades`
- 端点类型：public GET，无需认证
- 数据字段：`created_time`（精确到微秒）、`yes_price_dollars`、`count_fp`

---

## 3. 抽样比赛

| # | 标签 | Event Ticker | 类型 | 日期 |
|---|------|-------------|------|------|
| 1 | 2025-Finals-G7-OKC-IND | KXNBAGAME-25JUN19OKCIND | 2025 总决赛 G7 | 2025-06-19 |
| 2 | 2025-Finals-G5-OKC-IND | KXNBAGAME-25JUN13OKCIND | 2025 总决赛 G5 | 2025-06-13 |
| 3 | 2025-Christmas-MIN-DEN | KXNBAGAME-25DEC25MINDEN | 圣诞节常规赛 | 2025-12-25 |
| 4 | 2026-Regular-DEN-OKC | KXNBAGAME-26FEB27DENOKC | 常规赛 | 2026-02-27 |
| 5 | 2026-Playoffs-GSW-LAC | KXNBAGAME-26APR15GSWLAC | 2026 季后赛 | 2026-04-15 |

每场比赛合并两个 market（YES side + NO side）的全部 trades。

---

## 4. 关键统计结果

### 4.1 全场统计

| 比赛 | 总成交笔数 | 全场中位间隔 | 全场 p90 | 全场 p99 |
|------|-----------|------------|---------|---------|
| 2025-Finals-G7-OKC-IND | 56,304 | 0.4s | 10.7s | 40.4s |
| 2025-Finals-G5-OKC-IND | 57,119 | 0.3s | 5.2s | 40.7s |
| 2025-Christmas-MIN-DEN | 102,465 | 0.1s | 0.7s | 43.8s |
| 2026-Regular-DEN-OKC | 106,535 | 0.1s | 0.6s | 38.5s |
| 2026-Playoffs-GSW-LAC | 118,946 | 0.1s | 1.4s | 41.4s |

### 4.2 关键时段：最后 20 分钟 wall clock（代理 NBA 最后约 5 分钟比赛时间）

| 比赛 | 成交笔数 | 中位间隔 | p90 | p99 |
|------|---------|---------|-----|-----|
| 2025-Finals-G7-OKC-IND | 222 | **3.7s** | 11.8s | 40.3s |
| 2025-Finals-G5-OKC-IND | 69 | **11.0s** | 42.2s | 91.6s |
| 2025-Christmas-MIN-DEN | 13,933 | **<0.1s** | 0.2s | 1.0s |
| 2026-Regular-DEN-OKC | 13,457 | **<0.1s** | 0.2s | 0.9s |
| 2026-Playoffs-GSW-LAC | 31,727 | **<0.1s** | 0.1s | 0.3s |

### 4.3 关键时段：胶着时段（yes_price 在 0.35–0.65 之间，代理比分差 < 5 分）

| 比赛 | 成交笔数 | 中位间隔 | p90 | p99 |
|------|---------|---------|-----|-----|
| 2025-Finals-G7-OKC-IND | 15,038 | **0.2s** | 4.0s | 59.0s |
| 2025-Finals-G5-OKC-IND | 24,549 | **0.2s** | 0.9s | 2.8s |
| 2025-Christmas-MIN-DEN | 46,682 | **0.1s** | 3.8s | 94.9s |
| 2026-Regular-DEN-OKC | 65,045 | **0.1s** | 0.3s | 1.3s |
| 2026-Playoffs-GSW-LAC | 18,261 | **<0.1s** | 2.4s | 178.2s |

---

## 5. 图表

- `outputs/figures/phase1b_interval_cdf.png`：各比赛全场及最后20分钟成交间隔 CDF（x轴截断60s，红线=30s阈值）
- `outputs/figures/phase1b_price_and_volume.png`：各比赛最后3小时价格走势 + 每分钟成交笔数

---

## 6. 结论

**结论：Latency arbitrage 方向可行，且流动性远超预期。**

所有5场比赛在两个关键时段（最后20分钟 + 胶着时段）的成交间隔中位数全部远低于30秒判定阈值，具体：
- 最坏情况（2025总决赛G5最后20分钟）：中位间隔 11.0s，仍在30s以内
- 典型情况（常规赛、2026季后赛）：中位间隔 < 0.1s，每秒多笔成交
- 胶着时段流动性极佳：5场比赛中位间隔均 ≤ 0.2s

**附加观察：**

1. **总决赛 vs 常规赛差异明显**：总决赛最后20分钟成交笔数（69–222笔）远少于常规赛/季后赛（13,000–31,000笔）。可能原因：总决赛比赛结果往往在最后几分钟已经明朗，价格快速收敛到接近0或1，此时流动性自然萎缩。胶着时段的流动性两者都非常充裕。

2. **p99 间隔偏高**：部分比赛 p99 超过 40s（甚至 178s），说明偶发性的流动性真空存在。这在建模时需要考虑：极端情况下信号触发后可能短暂无法成交。

3. **数据覆盖范围**：历史数据从 2025-04-16 到 2026-04-20，共 1376 场独立 NBA 比赛事件，覆盖 2024-25 赛季后半段 + 2025-26 完整赛季，数据量充足支持后续建模。

---

## 7. 下一步（待确认后进入 Phase 0）

Phase -1b 完成，等待确认可进入 Phase 0：Win probability 模型建模。

**进入 Phase 0 前，主动提出 Adversarial Check：**

- 当前流动性检测的"胶着时段"用 yes_price ∈ [0.35, 0.65] 做代理，实际比分差数据并不在 Kalshi 里。后续建模需要外部 NBA 比赛比分数据（比如 NBA Stats API 或第三方数据源）来计算真实的 score_diff 特征。**这个外部数据源的确认需要在 Phase 0 开始前解决。**
- 最后20分钟 wall clock 是对"NBA最后5分钟比赛时间"的粗略代理，NBA 最后2分钟经常延长到20-40分钟 wall clock。实际的 game clock 对齐将是 Phase 0 时间对齐逻辑的核心挑战。

---

*数据文件：`data/raw/phase1b_liquidity_raw.json`*
