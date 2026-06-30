# Win Probability Model v2 (+ pregame_market_prob)

训练时间: 2026-06-21 18:09 UTC

## 模型变更

新增特征 `pregame_market_prob`: tip-off 前最后一笔 Kalshi 成交价，整场固定不变。
Playoffs 镜像数据集中，away 视角使用 `1 - home_market_prob`，保持 focal-team 视角对称。
Playoffs 训练集仅保留有 Kalshi 数据场次（约 88 场，不含 2021-24 历史数据）。

## 评估结果

| 子模型 | 训练场次 | 验证场次 | Brier(train) | Brier(val) | max_dev | Kill Criteria |
|--------|---------|---------|-------------|-----------|--------|--------------|
| Regular Season | 975 | 244 | 0.1530 | 0.1445 | 0.098 | ❌ 未触发 |
| Playoffs/Finals | 74 | 19 | 0.1761 | 0.1592 | 0.073 | ❌ 未触发 |

## 模型系数

### Regular Season

| 特征 | 系数 |
|------|------|
| score_diff | 0.1348 |
| time_remaining_feature | 0.0000 |
| is_overtime | -0.0560 |
| pregame_market_prob | 3.2959 |
| (截距) | -1.7820 |

### Playoffs/Finals

| 特征 | 系数 |
|------|------|
| lead | 0.1218 |
| time_remaining_feature | -0.0000 |
| is_overtime | -0.0239 |
| is_home | -0.3833 |
| pregame_market_prob | 1.5938 |
| (截距) | -0.6042 |

## 极端 case 验证

### Regular Season

| 场景 | P(home wins) |
|------|-------------|
| +30分 剩10s 赛前主场强队(0.7) | 0.990 |
| -30分 剩10s 赛前主场强队(0.7) | 0.029 |
| 平局 剩60s 赛前主场强队(0.7) | 0.629 |
| 平局 剩60s 赛前主场弱队(0.3) | 0.312 |
| 开局平局 赛前主场超强(0.8) | 0.718 |
| 开局平局 赛前主场超弱(0.2) | 0.260 |

### Playoffs/Finals

| 场景 | P(focal wins) |
|------|--------------|
| +30分 剩10s 主场视角 赛前强(0.7) | 0.978 |
| -30分 剩10s 客场视角 赛前强(0.3→away=0.7) | 0.022 |
| 平局 剩60s 主场视角 超强(0.8) | 0.571 |
| 平局 剩60s 客场视角 超弱(0.2→away=0.8) | 0.429 |

## 已知局限

- Playoffs 训练场次从 276 降至约 88，校准统计噪声更大
- 比赛末段极端 spread（如 -0.4）预期仍然存在，来源是战术犯规/暂停等
  特征缺失问题，不是 pregame_market_prob 要解决的问题，记录为已知局限