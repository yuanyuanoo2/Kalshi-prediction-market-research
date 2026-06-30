"""
Phase 0: Win probability logistic regression.
Features : score_diff, time_remaining_feature, is_overtime
Label    : home_team_wins (from final score_diff of each game)
Split    : by game_id (80/20), fixed seed — no row-level random split
Output   : outputs/figures/win_prob_calibration.png
           outputs/reports/win_prob_model_report.md
           data/processed/win_prob_model.pkl
"""

import os, pickle
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.linear_model import LogisticRegression
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss

# ── 路径常量 ──────────────────────────────────────────────────────────
PBP_CSV   = "data/processed/nba_pbp_parsed.csv"
FIG_PATH  = "outputs/figures/win_prob_calibration.png"
REPORT_MD = "outputs/reports/win_prob_model_report.md"
MODEL_PKL = "data/processed/win_prob_model.pkl"
SEED      = 42
TRAIN_FRAC = 0.80


def load_and_prepare(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={"game_id": str, "period": int})

    # ── 计算每场最终 score_diff（标签来源）──
    # 用 action_number 最大行，已含前向填充比分，无 look-ahead bias：
    # 标签是"比赛最终结果"，在训练时整场比赛数据均已结束，不存在未来信息泄漏。
    final = (
        df.sort_values(["game_id", "action_number"])
        .groupby("game_id")["score_diff"]
        .last()
        .reset_index()
        .rename(columns={"score_diff": "final_score_diff"})
    )

    # 剔除最终 score_diff = 0 的场次（PBP 数据截断，NBA 无平局）
    valid_games = final[final["final_score_diff"] != 0].copy()
    valid_games["home_wins"] = (valid_games["final_score_diff"] > 0).astype(int)

    df = df.merge(valid_games[["game_id", "home_wins"]], on="game_id", how="inner")

    # ── 特征工程 ──
    # is_overtime: period > 4
    df["is_overtime"] = (df["period"] > 4).astype(int)

    # time_remaining_feature:
    #   - 常规赛节(period≤4): 直接用 time_remaining (2880→0)
    #   - 加时赛(period>4)  : 按 OT 本身剩余时间计算 (300→0)
    #     推导: total_time_remaining(p,c) = c - (p-4)*300 (for p>4)
    #           所以 clock_s = time_remaining + (period-4)*300
    df["time_remaining_feature"] = df.apply(
        lambda r: r["time_remaining"] + (r["period"] - 4) * 300
        if r["period"] > 4 else r["time_remaining"],
        axis=1,
    )

    # 只保留 wall_utc 非空的行（已确认全部非空，防御性过滤）
    df = df.dropna(subset=["wall_utc"])

    return df


def split_by_game(df: pd.DataFrame, train_frac: float, seed: int):
    """按 game_id 切分，禁止按行随机切分。"""
    games = df["game_id"].unique()
    rng   = np.random.default_rng(seed)
    rng.shuffle(games)
    n_train = int(len(games) * train_frac)
    train_games = set(games[:n_train])
    val_games   = set(games[n_train:])
    return df[df["game_id"].isin(train_games)], df[df["game_id"].isin(val_games)]


def main():
    os.makedirs("outputs/figures", exist_ok=True)
    os.makedirs("outputs/reports", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)

    # ── 加载 ──
    print("加载数据 ...")
    df = load_and_prepare(PBP_CSV)

    n_games     = df["game_id"].nunique()
    n_rows      = len(df)
    ot_rows     = df["is_overtime"].sum()
    home_win_rate = df.drop_duplicates("game_id")["home_wins"].mean()

    print(f"  场次数:     {n_games}")
    print(f"  总行数:     {n_rows:,}")
    print(f"  OT 行数:   {ot_rows:,}  ({ot_rows/n_rows*100:.1f}%)")
    print(f"  主场胜率:  {home_win_rate:.3f}")

    # ── 切分 ──
    train_df, val_df = split_by_game(df, TRAIN_FRAC, SEED)
    print(f"\n训练集: {train_df['game_id'].nunique()} 场 / {len(train_df):,} 行")
    print(f"验证集: {val_df['game_id'].nunique()} 场 / {len(val_df):,} 行")

    FEATURES = ["score_diff", "time_remaining_feature", "is_overtime"]
    X_train = train_df[FEATURES].values
    y_train = train_df["home_wins"].values
    X_val   = val_df[FEATURES].values
    y_val   = val_df["home_wins"].values

    # ── 训练 ──
    print("\n训练 logistic regression ...")
    model = LogisticRegression(max_iter=1000, random_state=SEED)
    model.fit(X_train, y_train)

    coef = dict(zip(FEATURES, model.coef_[0]))
    print(f"  系数: {coef}")
    print(f"  截距: {model.intercept_[0]:.4f}")

    # ── 评估 ──
    prob_train = model.predict_proba(X_train)[:, 1]
    prob_val   = model.predict_proba(X_val)[:, 1]

    brier_train = brier_score_loss(y_train, prob_train)
    brier_val   = brier_score_loss(y_val,   prob_val)

    print(f"\nBrier Score — in-sample:  {brier_train:.4f}")
    print(f"Brier Score — out-of-sample: {brier_val:.4f}")

    # ── Calibration curve ──
    frac_pos_tr, mean_pred_tr = calibration_curve(y_train, prob_train, n_bins=20, strategy="uniform")
    frac_pos_val, mean_pred_val = calibration_curve(y_val,   prob_val,   n_bins=20, strategy="uniform")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Win Probability Model — Calibration Curve (Logistic Regression)", fontsize=12)

    for ax, frac_pos, mean_pred, label, brier, color in [
        (axes[0], frac_pos_tr,  mean_pred_tr,  f"In-sample (train)\nBrier={brier_train:.4f}",  brier_train, "steelblue"),
        (axes[1], frac_pos_val, mean_pred_val, f"Out-of-sample (val)\nBrier={brier_val:.4f}", brier_val,   "coral"),
    ]:
        ax.plot([0, 1], [0, 1], "k--", linewidth=0.8, label="Perfect calibration")
        ax.plot(mean_pred, frac_pos, "o-", color=color, linewidth=1.5, markersize=4, label=label)
        ax.set_xlabel("Mean predicted probability")
        ax.set_ylabel("Fraction of positives (home team wins)")
        ax.set_title(label.split("\n")[0])
        ax.legend(fontsize=9)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(FIG_PATH, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nCalibration curve 保存: {FIG_PATH}")

    # ── 极端 case 验证（look-ahead bias 检查）──
    # 人工构造：主场领先 30 分，剩余 10 秒（不含 OT）→ 应接近 1.0
    # 主场落后 30 分，剩余 10 秒 → 应接近 0.0
    test_cases = [
        ( 30, 10, 0, "主场+30分 剩10s"),
        (-30, 10, 0, "主场-30分 剩10s"),
        (  0, 60, 0, "平局 剩60s"),
        (  5, 60, 1, "主场+5分 OT剩60s"),
    ]
    print("\n极端 case 验证:")
    for sd, tr, ot, desc in test_cases:
        p = model.predict_proba([[sd, tr, ot]])[0][1]
        print(f"  {desc}: P(home wins) = {p:.3f}")

    # ── 保存模型 ──
    with open(MODEL_PKL, "wb") as f:
        pickle.dump({"model": model, "features": FEATURES}, f)
    print(f"\n模型保存: {MODEL_PKL}")

    # ── 写报告 ──
    lines = [
        "# Phase 0: Win Probability Model Report",
        "",
        f"训练时间: {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 数据概况",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 总场次 | {n_games} |",
        f"| 总行数 | {n_rows:,} |",
        f"| OT 行数 | {ot_rows:,} ({ot_rows/n_rows*100:.1f}%) |",
        f"| 主场胜率（场次级别） | {home_win_rate:.3f} |",
        f"| 剔除场次（score_diff=0） | 11 |",
        "",
        "## 切分",
        "",
        f"按 game_id 切分（禁止按行随机切分）：",
        f"- 训练集: {train_df['game_id'].nunique()} 场 / {len(train_df):,} 行",
        f"- 验证集: {val_df['game_id'].nunique()} 场 / {len(val_df):,} 行",
        "",
        "## 模型参数",
        "",
        "| 特征 | 系数 |",
        "|------|------|",
    ]
    for feat, c in coef.items():
        lines.append(f"| {feat} | {c:.4f} |")
    lines += [
        f"| (截距) | {model.intercept_[0]:.4f} |",
        "",
        "## 评估结果",
        "",
        "| 集合 | Brier Score |",
        "|------|-------------|",
        f"| In-sample（训练集） | **{brier_train:.4f}** |",
        f"| Out-of-sample（验证集） | **{brier_val:.4f}** |",
        "",
        "（Brier Score 越低越好，完美预测 = 0，随机猜测 ≈ 0.25）",
        "",
        "## 极端 case 验证",
        "",
        "| 场景 | P(主场赢) |",
        "|------|---------|",
    ]
    for sd, tr, ot, desc in test_cases:
        p = model.predict_proba([[sd, tr, ot]])[0][1]
        lines.append(f"| {desc} | {p:.3f} |")
    lines += [
        "",
        "## 图表",
        "",
        f"Calibration curve: `{FIG_PATH}`",
        "",
        "## 待办",
        "",
        "- Phase -1b 18处异常窗口：用 nba_api 真实终场时间回溯核查（见 CLAUDE.md 待办）",
    ]

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))
    print(f"报告保存: {REPORT_MD}")


if __name__ == "__main__":
    main()
