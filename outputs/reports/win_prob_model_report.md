# Phase 0: Win Probability Model Report

训练时间: 2026-06-20 20:14 UTC

## 数据概况

| 指标 | 值 |
|------|----|
| 总场次 | 1312 |
| 总行数 | 662,663 |
| OT 行数 | 3,823 (0.6%) |
| 主场胜率（场次级别） | 0.549 |
| 剔除场次（score_diff=0） | 11 |

## 切分

按 game_id 切分（禁止按行随机切分）：
- 训练集: 1049 场 / 529,528 行
- 验证集: 263 场 / 133,135 行

## 模型参数

| 特征 | 系数 |
|------|------|
| score_diff | 0.1471 |
| time_remaining_feature | 0.0000 |
| is_overtime | 0.0858 |
| (截距) | 0.1112 |

## 评估结果

| 集合 | Brier Score |
|------|-------------|
| In-sample（训练集） | **0.1685** |
| Out-of-sample（验证集） | **0.1594** |

（Brier Score 越低越好，完美预测 = 0，随机猜测 ≈ 0.25）

## 极端 case 验证

| 场景 | P(主场赢) |
|------|---------|
| 主场+30分 剩10s | 0.989 |
| 主场-30分 剩10s | 0.013 |
| 平局 剩60s | 0.528 |
| 主场+5分 OT剩60s | 0.718 |

## 图表

Calibration curve: `outputs/figures/win_prob_calibration.png`

## 待办

- Phase -1b 18处异常窗口：用 nba_api 真实终场时间回溯核查（见 CLAUDE.md 待办）