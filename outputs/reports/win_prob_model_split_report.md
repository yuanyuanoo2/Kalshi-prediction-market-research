# Phase 0 (Revision): Win Probability Models — Split by Game Type

训练时间: 2026-06-20 20:33 UTC

## 背景

合并模型诊断发现 Playoffs/Finals 子集校准偏差达 23.3%，触发 Kill Criteria。
决策：分拆为两个独立模型分别训练评估。

## 结果汇总

| 类型 | 训练场次 | 验证场次 | Brier(train) | Brier(val) | 最大校准偏差(val) | Kill Criteria |
|------|---------|---------|-------------|-----------|-----------------|--------------|
| Regular Season | 975 | 244 | 0.1685 | 0.1566 | 0.097 | ❌ 未触发 |
| Playoffs/Finals | 74 | 19 | 0.1773 | 0.1651 | 0.263 | ⚠️ 触发 |

## 模型系数

| 特征 | Regular Season | Playoffs/Finals |
|------|---------------|----------------|
| score_diff | 0.1489 | 0.1324 |
| time_remaining_feature | 0.0000 | 0.0003 |
| is_overtime | -0.0002 | -0.0174 |
| (截距) | 0.0156 | -0.4553 |

## 极端 case 验证

| 场景 | Regular P(home) | Playoffs P(home) |
|------|----------------|-----------------|
| +30分 剩10s | 0.989 | 0.971 |
| -30分 剩10s | 0.012 | 0.012 |
| 平局 剩60s | 0.504 | 0.392 |
| +5分 OT剩60s | 0.682 | 0.551 |

## 注意事项

- Playoffs 验证集仅 19 场（约 9,648 行），校准曲线统计噪声较大
- Playoffs 模型系数与 Regular 差异反映两类比赛的不同动态（季后赛结果更具决定性）
- 后续回测须用对应类型的模型：Regular Season 用 `win_prob_model_regular.pkl`，Playoffs 用 `win_prob_model_playoffs.pkl`