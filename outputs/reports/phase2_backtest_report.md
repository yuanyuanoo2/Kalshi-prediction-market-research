# Phase 2 回测报告

生成时间: 2026-06-21

## 参数设置

- 模型: v2 (Regular LR / Playoffs LR+mirror+is_home)
- 信号阈值: **7%** (in-sample 调参选定)
- 最小持续时间: 10.0s (固定)
- Exit A: 收敛平仓（net_edge 回落至阈值以下）
- Exit B: 固定 60s 窗口平仓
- 手续费: taker fee = $0.07 × C × (1−C)，开平仓各一次；比赛结算无费用
- 末段标记: time_remaining_feature < 300s = is_endgame

## 样本切分

- In-sample: 18 场（各类别前 60% game_id 按字典序）
- Out-of-sample: 13 场

## 信号统计

| 指标 | 数值 |
|------|------|
| 总交易数（两种策略各一条） | 1106 |
| In-sample 交易 | 682 |
| Out-of-sample 交易 | 424 |
| 末段信号（is_endgame=True） | 140 (12.7%) |

## 分组回测结果

| split            | game_cat  | exit_strat   | n_trades | win_rate | avg_gross  | avg_net    | sharpe   | max_dd     | total_net  |
|-----------------|-----------|--------------|----------|----------|------------|------------|----------|------------|------------|
| in_sample        | Regular   | convergence  |      168 |    24.4% |     0.0177 |    -0.0108 |   -0.204 |    -1.8272 |    -1.8202 |
| in_sample        | Regular   | fixed_window |      171 |    17.5% |    -0.0027 |    -0.0306 |   -0.495 |    -5.3236 |    -5.2277 |
| in_sample        | Regular   | game_end     |        5 |     0.0% |    -0.1740 |    -0.1823 |   -1.099 |    -0.9114 |    -0.9114 |
| in_sample        | Playoffs  | convergence  |       96 |    34.4% |     0.0270 |     0.0019 |    0.032 |    -0.6732 |     0.1845 |
| in_sample        | Playoffs  | fixed_window |      101 |    24.8% |     0.0084 |    -0.0156 |   -0.328 |    -1.5853 |    -1.5717 |
| in_sample        | Playoffs  | game_end     |        7 |     0.0% |    -0.1029 |    -0.1082 |   -0.822 |    -0.7574 |    -0.7574 |
| in_sample        | Finals    | convergence  |       64 |    31.2% |     0.0116 |    -0.0068 |   -0.187 |    -0.5871 |    -0.4356 |
| in_sample        | Finals    | fixed_window |       66 |    25.8% |     0.0050 |    -0.0130 |   -0.400 |    -0.8590 |    -0.8590 |
| in_sample        | Finals    | game_end     |        4 |     0.0% |    -0.1025 |    -0.1073 |   -0.666 |    -0.4291 |    -0.4291 |
| out_of_sample    | Regular   | convergence  |      105 |    20.0% |     0.0105 |    -0.0141 |   -0.370 |    -1.8138 |    -1.4836 |
| out_of_sample    | Regular   | fixed_window |      106 |    19.8% |     0.0045 |    -0.0197 |   -0.484 |    -2.1115 |    -2.0861 |
| out_of_sample    | Regular   | game_end     |        1 |     0.0% |    -0.0700 |    -0.0746 |      nan |    -0.0746 |    -0.0746 |
| out_of_sample    | Playoffs  | convergence  |       45 |    44.4% |     0.0191 |    -0.0021 |   -0.038 |    -0.3434 |    -0.0941 |
| out_of_sample    | Playoffs  | fixed_window |       45 |    24.4% |     0.0102 |    -0.0110 |   -0.279 |    -0.5036 |    -0.4962 |
| out_of_sample    | Playoffs  | game_end     |        2 |     0.0% |    -0.0200 |    -0.0214 |      nan |    -0.0427 |    -0.0427 |
| out_of_sample    | Finals    | convergence  |       57 |    26.3% |     0.0132 |    -0.0144 |   -0.389 |    -0.9033 |    -0.8220 |
| out_of_sample    | Finals    | fixed_window |       60 |    23.3% |     0.0028 |    -0.0237 |   -0.653 |    -1.4242 |    -1.4242 |
| out_of_sample    | Finals    | game_end     |        3 |     0.0% |    -0.0967 |    -0.1018 |   -0.839 |    -0.3055 |    -0.3055 |

> Playoffs/Finals 结果须保守解读（训练场次 74 场，小样本统计不稳定）。
> 末段信号（is_endgame=True）占 12.7%，可能包含战术犯规/暂停等不可重复因素。

## 图表

- `outputs/figures/phase2_cumulative_pnl.png` — 累计净 P&L 曲线
- `outputs/figures/phase2_pnl_distribution.png` — P&L 分布
- `outputs/figures/phase2_pnl_vs_entry_price.png` — P&L vs 入场价格

## 数据文件

- `outputs/reports/phase2_trades.csv` — 交易明细
