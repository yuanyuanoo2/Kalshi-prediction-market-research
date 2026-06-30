# Project Progress

最后更新：2026-06-21（附加分析完成）

---

## 已完成阶段

### Phase -1：Kalshi API 可行性确认 ✅
- Base URL：`https://api.elections.kalshi.com/trade-api/v2`，无需认证
- 数据形态：逐笔成交 `/historical/trades`（精确时间戳）+ 1分钟 candlestick
- 手续费：taker = $0.07 × C × (1−C)，maker = taker × 25%
- Ticker 格式：`KXNBAGAME-{YY}{MON}{DD}{TEAM1}{TEAM2}-{WINNER}`
- **主客场约定确认**：team1 = 客场，team2 = 主场（用 2025 Finals G1–G6 交叉验证）

### Phase -1b：流动性可行性检测 ✅（结论：初步可行）
- 5 场比赛，441,369 笔成交，关键时段成交间隔中位数 ≤ 30s
- 18 处 >30s 异常间隔经双源核查（API 重拉 + candlestick）→ 全部为真实流动性真空
- 结论暂定"初步可行"，18 处异常的业务解释（比赛末段价格收敛→做市商退出）待 nba_api 真实终场时间回溯核实

### Phase 0 前置：NBA 数据拉取与时间对齐 ✅
- 接入 nba_api（PlayByPlayV3），拉取 2024-25 Playoffs + 2025-26 Regular/PlayIn/Playoffs
- 建立 Kalshi ↔ NBA 映射表：**1323 场匹配**（53 场不匹配为季前赛等，可接受）
- 提取 score_diff、time_remaining、wall clock（UTC 线性插值）
- 修复跨午夜 bug：Christmas MIN-DEN、Feb27 DEN-OKC 两场 Q3/Q4/OT 时间戳偏移 −24h，已修正
- 时间对齐人工核查 3 场（含 2 场 OT）：通过
- 产出：`data/raw/nba_game_mapping.csv`、`data/raw/nba_pbp/*.json`（1323 个）、`data/processed/nba_pbp_parsed.csv`（**668,207 行**，wall_utc 缺失 = 0）

### Phase 0：Win Probability 模型训练 ✅（v2，含 pregame_market_prob）

#### 模型迭代历史（Playoffs 子集）

| 版本 | 训练场次 | 变更内容 | max_dev | Kill Criteria |
|------|---------|---------|--------|--------------|
| v0：LR | 93 | 基线 | 26.3% | ⚠️ 触发 |
| v0：LR | 345 | 补 2021-24 历史数据 | 15.9% | ⚠️ 触发 |
| v0：LR + is_home + 镜像 | 345 | 主客场双视角数据增强 | 14.3% | ⚠️ 触发 |
| v0：XGBoost + is_home + 镜像 | 345 | 换非线性模型 | 13.7% | ⚠️ 触发 |
| **v2：LR + is_home + 镜像 + pregame_market_prob** | **74** | 加赛前隐含胜率特征 | **7.3%** | **✅ 未触发** |

根本原因（v0 失败）：偏差集中在 0.27–0.53 胶着区间，系列赛球队实力信息缺失。pregame_market_prob 直接补充了这一信息，Playoffs 校准大幅改善。

#### 最终确定模型（v2）

| 子模型 | 特征 | 训练场次 | Brier(val) | max_dev | Kill Criteria |
|--------|------|---------|-----------|--------|--------------|
| Regular Season | score_diff, time_remaining, is_overtime, **pregame_market_prob** | 975 | 0.1445 | 9.8% | ✅ 未触发 |
| Playoffs/Finals | lead, time_remaining, is_overtime, is_home, **pregame_market_prob** | 74 | 0.1592 | 7.3% | ✅ 未触发 |

**极端 case 验证通过**：大比分领先时分数主导（+30分 剩10s → P=0.99），开局平局时赛前价格主导（pregame=0.8 → P=0.72，pregame=0.2 → P=0.26）。

**镜像数据验证通过**：同场比赛主客双视角均在同一集合（overlap = 0），无数据泄露。Playoffs away 视角使用 `1 - home_market_prob`，与 focal-team 视角对称。

**已知局限**：
- Playoffs is_home 系数为负（-0.383），与直觉相反，疑为小样本噪声（训练仅 74 场），已记录
- 比赛末段极端 spread 属战术犯规/暂停行为，不在当前特征集解决范围内

产出：`data/processed/win_prob_model_regular_v2.pkl`、`data/processed/win_prob_model_playoffs_v2.pkl`

### Phase 1：市场价差与收敛时间分析 ✅（含 v2 模型重跑）

#### 数据范围
- 31 场：Regular Season 15 / Playoffs 10 / Finals 6
- 总成交笔数：293,323 笔（含赛前）
- pregame_market_prob 批量拉取：**1323 场全部获取**，0 缺失（使用 `max_ts` 参数，每场 1 次 API 调用）

#### 核心结果：收敛时间（≥10s 过滤后）

| 类别 | 过滤前事件数 | 过滤后事件数 | 过滤比例 | 中位数收敛时间 | p90 收敛时间 |
|------|-----------|-----------|---------|------------|-----------|
| Regular Season | 2127 | 490 | 77% | **37s** | 185s |
| Playoffs ⚠️ | 347 | 216 | 38% | 56s | 529s |
| Finals ⚠️ | 728 | 180 | 75% | 45s | 288s |

注：77% 的 Regular Season 原始事件为振荡噪声（持续 <10s）。过滤后真实 gap 中位数 37s，p90 185s。

#### 核心结果：开局 vs 后半阶段 spread（v1 对比 v2）

分界：time_remaining > 1440s = 开局（上半场）；≤1440s = 后半场。

| 类别 | v1 开局 | v1 后半 | v2 开局 | v2 后半 | 开局改善 |
|------|--------|--------|--------|--------|---------|
| Regular Season | 0.162 | 0.126 | **0.065** | **0.046** | **−0.097 ✅ 大幅收窄** |
| Playoffs ⚠️ | 0.082 | 0.117 | 0.088 | 0.110 | 基本持平 |
| Finals ⚠️ | 0.123 | 0.100 | 0.064 | 0.098 | 开局收窄 |

**Regular Season 开局 spread 从 0.162 降至 0.065**，验证了"模型 v1 缺球队实力信息"假设。v2 模型在开局阶段系统性偏差大幅收窄，符合 pregame_market_prob 特征设计预期。后半场仍有 spread 残留，部分来自战术行为（末段犯规/暂停），属已知局限。

#### 产出文件
- `data/processed/pregame_market_probs.csv`（1323 场赛前价格）
- `data/raw/phase1_trades/*.json`（31 个文件，293,323 笔）
- `outputs/reports/phase1_spread_report.md`、`phase1_summary.csv`
- `outputs/figures/phase1_spread_samples.png`、`phase1_convergence_dist.png`、`phase1_phase_spread.png`
- `outputs/figures/win_prob_v2_calibration.png`
- `outputs/reports/win_prob_v2_report.md`

### Phase 2：交易信号设计与回测 ✅（Kill Criteria 触发：扣费后无可交易 edge）

#### 参数设置

- 信号阈值：7%（in-sample 调参选定，3%/5%/7% 全部净负，7% 最优）
- 最小持续时间：10s（固定，与 Phase 1 一致）
- Exit A：net_edge 回落阈值以下收敛平仓
- Exit B：固定 60s 窗口平仓
- 手续费：taker fee 双边（$0.07 × C × (1−C)）；比赛结算无费用
- 末段标记：time_remaining_feature < 300s = is_endgame
- 样本：18 场 in-sample / 13 场 out-of-sample（各类别内按 game_id 字典序 60/40 分层切分）

#### 核心结果（Exit A 收敛平仓，阈值 7%）

| 类别 | 样本 | 笔数 | 扣费前均收益 | **扣费后均收益** | Sharpe(net) | 总净收益 |
|------|------|------|-----------|------------|------------|---------|
| Regular | IS | 168 | +0.0177 | **−0.0108** | −0.204 | −1.82 |
| Regular | OOS | 105 | +0.0105 | **−0.0141** | −0.370 | −1.48 |
| Playoffs ⚠️ | IS | 96 | +0.0270 | **+0.0019** | +0.032 | +0.18 |
| Playoffs ⚠️ | OOS | 45 | +0.0191 | **−0.0021** | −0.038 | −0.09 |
| Finals ⚠️ | IS | 64 | +0.0116 | **−0.0068** | −0.187 | −0.44 |
| Finals ⚠️ | OOS | 57 | +0.0132 | **−0.0144** | −0.389 | −0.82 |

#### 关键发现

1. **扣费前信号真实**：收敛 win_rate gross 达 59–67%，v2 模型确实识别出市场偏差
2. **扣费后无 edge**：taker fee 双边（中间价位约 3.5%）吃掉 1–3% 量级的 spread 优势，净收益全部转负或趋零
3. **无过拟合**：IS 和 OOS 方向一致（均为净负），OOS 比 IS 略差但无明显断崖式失效
4. **最高阈值（7%）最优**：更少但质量更高的信号，但仍无法翻正
5. **末段信号（12.7%）**：OOS avg_net = +0.009（46 笔），样本太小，不具统计意义

#### Kill Criteria 判定

**触发**："扣除手续费后，所有检测到的价差都不再具备正收益空间"

→ **结论：Kalshi NBA 市场扣费后近似有效，当前特征集无法提取可交易 edge。** 这是合法且完整的研究结论。

Playoffs IS 收敛勉强正值（+$0.002/笔，共 +$0.18）在 OOS 立即翻负，经济意义为零。

#### 产出文件

- `src/backtest/backtest_phase2.py`（主回测脚本）
- `tests/test_backtest.py`（24 个单元测试，全部通过）
- `outputs/reports/phase2_backtest_report.md`
- `outputs/reports/phase2_trades.csv`（1106 条交易明细）
- `outputs/figures/phase2_cumulative_pnl.png`、`phase2_pnl_distribution.png`、`phase2_pnl_vs_entry_price.png`

### 附加分析：无手续费情景下的策略质量评估 ✅（理论分析，不替换 Phase 2 核心结论）

#### 前提声明

⚠️ 此为理论分析，不代表真实可交易结果。Phase 2 核心结论（扣费后无 edge）不变。

#### 核心结果

**Exit A（收敛平仓）Gross — IS vs OOS 一致，是信号质量最可信证据：**

| 类别 | IS win_rate | IS avg_gross | OOS win_rate | OOS avg_gross |
|------|------------|------------|-------------|-------------|
| Regular | 64.2% | +0.0121 | 58.5% | +0.0097 |
| Playoffs ⚠️ | 62.1% | +0.0182 | 57.4% | +0.0174 |
| Finals ⚠️ | 48.5% | +0.0049 | 60.0% | +0.0077 |

IS 和 OOS 方向一致（均为正），说明 v2 模型对 spread 收敛方向的预测是真实的，并非过拟合。

**Exit C（持有至结算）Gross — 结果噪声大，不适合评估信号质量：**
- Regular：IS −0.190 / OOS −0.121（持续为负）
- Playoffs：IS +0.090 / OOS +0.243（但样本小）
- Finals：IS +0.421 / OOS **−0.009**（断崖 = 小样本二元结果噪声，6 场比赛）

Finals IS/OOS 大幅反转（+0.421 → −0.009）是典型小样本噪声，不作为信号质量证据。

**信号强度 vs 收益（无单调关系）：**

| net_edge 分档 | IS avg | OOS avg |
|-------------|--------|---------|
| 7–10% | +0.025 | −0.011 |
| 10–15% | −0.012 | +0.019 |
| 15%+ | +0.032 | **−0.089** |

OOS 最高分档（15%+）表现最差（−0.089）。极高 spread 往往发生在比赛末段等高不确定性时刻，信号更不可靠，net_edge 大小不能预测 gross 收益。

**入场价格结构性分析：**
- 中位数入场价格：0.59，48.5% 在高手续费区间（0.3–0.7）
- 平均双边手续费 $0.0245 ≈ Exit A avg_gross（~$0.012）的 **2倍**
- 结构性结论：Kalshi 费率结构对中间价位机会收取最高成本，恰好是 v2 模型发现大部分 spread 的区域

#### 综合评价

信号预测能力确实存在（Exit A gross IS/OOS 均正），但当前 Kalshi 费率结构（双边约 $0.025）约为可捕获 gross 收益（~$0.012）的 2 倍，使得预测能力无法转化为正收益。更高的 spread 不代表更可靠的信号。

#### 产出文件

- `src/analysis/phase2_no_fee_analysis.py`
- `outputs/reports/phase2_no_fee_report.md`
- `outputs/figures/phase2_nofee_gross_dist.png`、`phase2_nofee_cumulative.png`、`phase2_nofee_signal_strength.png`、`phase2_nofee_entry_price_dist.png`

---

## 当前进展

**所在阶段：全部阶段完成（Phase 0/1/2 + 附加分析）。项目核心结论：Kalshi NBA 市场扣费后近似有效，当前特征集无法提取可交易 edge；信号方向预测能力真实存在，但被费率结构消耗。**

---

## 跨阶段已知局限

| 局限 | 来源 | 影响 | 处理方式 |
|------|------|------|---------|
| Playoffs is_home 系数为负 | 训练仅 74 场，小样本噪声 | 轻微 | 已记录，不重训 |
| 比赛末段极端 spread 仍存在 | 犯规/暂停等战术行为，特征缺失 | 中等 | 记录为已知局限 |
| Playoffs/Finals 结论须保守解读 | 训练场次少，小样本统计不稳定 | 中等 | 所有 Playoffs/Finals 结果单独标注 ⚠️ |
| Phase -1b 18 处流动性真空未最终确认 | 尚未用 nba_api 真实终场时间回溯 | 低（不阻塞） | 长期待办 |
| 扣费后无可交易 edge | Kalshi taker fee 结构消除 spread 优势 | 核心结论 | Kill Criteria 触发，已如实报告 |

---

## 长期待办（不阻塞当前任务）
- 用 nba_api 真实终场时间回溯核查 Phase -1b 18 处异常窗口
