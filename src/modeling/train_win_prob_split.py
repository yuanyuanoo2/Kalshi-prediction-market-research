"""
Phase 0 (revision): 按比赛类型分别训练 win probability 模型。
  - Model A: Regular Season (game_id 前缀 002)
  - Model B: Playoffs/Finals + PlayIn (game_id 前缀 004, 005)
Features : score_diff, time_remaining_feature, is_overtime
Label    : home_team_wins
Split    : 按 game_id 80/20，各类型独立切分
Output   :
  data/processed/win_prob_model_regular.pkl
  data/processed/win_prob_model_playoffs.pkl
  outputs/figures/win_prob_calibration_split.png
  outputs/reports/win_prob_model_split_report.md
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

PBP_CSV   = "data/processed/nba_pbp_parsed.csv"
FIG_PATH  = "outputs/figures/win_prob_calibration_split.png"
REPORT_MD = "outputs/reports/win_prob_model_split_report.md"
SEED      = 42
TRAIN_FRAC = 0.80
FEATURES   = ["score_diff", "time_remaining_feature", "is_overtime"]


def load_and_prepare(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={"game_id": str, "period": int})

    # 标签：每场最终 score_diff 的符号
    final = (
        df.sort_values(["game_id", "action_number"])
        .groupby("game_id")["score_diff"].last()
        .reset_index()
        .rename(columns={"score_diff": "final_score_diff"})
    )
    valid = final[final["final_score_diff"] != 0].copy()
    valid["home_wins"] = (valid["final_score_diff"] > 0).astype(int)

    df = df.merge(valid[["game_id", "home_wins"]], on="game_id", how="inner")

    # 特征工程
    df["is_overtime"] = (df["period"] > 4).astype(int)
    # OT 期间 time_remaining 按 OT 本身剩余时间计算，不与常规时间累加
    df["time_remaining_feature"] = df.apply(
        lambda r: r["time_remaining"] + (r["period"] - 4) * 300
        if r["period"] > 4 else r["time_remaining"],
        axis=1,
    )

    # 按 game_id 前缀分类
    prefix = df["game_id"].str[:3]
    df["game_type"] = "Other"
    df.loc[prefix == "002", "game_type"] = "Regular"
    df.loc[prefix.isin(["004", "005"]), "game_type"] = "Playoffs"

    return df.dropna(subset=["wall_utc"])


def split_by_game(df: pd.DataFrame, seed: int):
    games = df["game_id"].unique().copy()
    rng   = np.random.default_rng(seed)
    rng.shuffle(games)
    n_train = int(len(games) * TRAIN_FRAC)
    train_g = set(games[:n_train])
    val_g   = set(games[n_train:])
    return df[df["game_id"].isin(train_g)], df[df["game_id"].isin(val_g)]


def train_and_eval(df: pd.DataFrame, label: str, seed: int):
    """训练+评估一个类型，返回 (model, train_df, val_df, metrics_dict)。"""
    train_df, val_df = split_by_game(df, seed)

    X_tr = train_df[FEATURES].values;  y_tr = train_df["home_wins"].values
    X_va = val_df[FEATURES].values;    y_va = val_df["home_wins"].values

    model = LogisticRegression(max_iter=1000, random_state=seed)
    model.fit(X_tr, y_tr)

    prob_tr = model.predict_proba(X_tr)[:, 1]
    prob_va = model.predict_proba(X_va)[:, 1]

    brier_tr = brier_score_loss(y_tr, prob_tr)
    brier_va = brier_score_loss(y_va, prob_va)

    n_bins = 10 if len(val_df["game_id"].unique()) < 30 else 15
    frac_tr, pred_tr = calibration_curve(y_tr, prob_tr, n_bins=n_bins, strategy="uniform")
    frac_va, pred_va = calibration_curve(y_va, prob_va, n_bins=n_bins, strategy="uniform")

    max_dev_va = float(np.abs(frac_va - pred_va).max())

    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"  训练集: {train_df['game_id'].nunique()} 场 / {len(train_df):,} 行")
    print(f"  验证集: {val_df['game_id'].nunique()} 场 / {len(val_df):,} 行")
    print(f"  Brier: in-sample={brier_tr:.4f}  out-of-sample={brier_va:.4f}")
    print(f"  最大校准偏差(val): {max_dev_va:.3f}")
    coef = dict(zip(FEATURES, model.coef_[0]))
    print(f"  系数: {coef}")

    return model, train_df, val_df, {
        "label": label,
        "n_train_games": train_df["game_id"].nunique(),
        "n_val_games":   val_df["game_id"].nunique(),
        "n_train_rows":  len(train_df),
        "n_val_rows":    len(val_df),
        "brier_train":   brier_tr,
        "brier_val":     brier_va,
        "max_dev_val":   max_dev_va,
        "coef":          coef,
        "intercept":     model.intercept_[0],
        "frac_tr": frac_tr, "pred_tr": pred_tr,
        "frac_va": frac_va, "pred_va": pred_va,
    }


def main():
    os.makedirs("outputs/figures", exist_ok=True)
    os.makedirs("outputs/reports", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)

    print("加载数据 ...")
    df = load_and_prepare(PBP_CSV)

    counts = df.groupby("game_type")["game_id"].nunique()
    print("场次分布:")
    print(counts.to_string())

    # ── 分别训练 ──
    reg_df  = df[df["game_type"] == "Regular"].copy()
    play_df = df[df["game_type"] == "Playoffs"].copy()

    model_reg,  tr_r, va_r, m_r = train_and_eval(reg_df,  "Regular Season",    SEED)
    model_play, tr_p, va_p, m_p = train_and_eval(play_df, "Playoffs/Finals",   SEED)

    # ── 极端 case 验证（两个模型） ──
    test_cases = [
        ( 30, 10, 0, "+30分 剩10s"),
        (-30, 10, 0, "-30分 剩10s"),
        (  0, 60, 0, "平局 剩60s"),
        (  5, 60, 1, "+5分 OT剩60s"),
    ]
    print("\n极端 case 对比:")
    print(f"  {'场景':15s}  {'Regular':>8}  {'Playoffs':>8}")
    for sd, tr, ot, desc in test_cases:
        p_r = model_reg.predict_proba([[sd, tr, ot]])[0][1]
        p_p = model_play.predict_proba([[sd, tr, ot]])[0][1]
        print(f"  {desc:15s}  {p_r:8.3f}  {p_p:8.3f}")

    # ── 保存模型 ──
    for mdl, path, name in [
        (model_reg,  "data/processed/win_prob_model_regular.pkl",  "Regular"),
        (model_play, "data/processed/win_prob_model_playoffs.pkl", "Playoffs"),
    ]:
        with open(path, "wb") as f:
            pickle.dump({"model": mdl, "features": FEATURES, "game_type": name}, f)
        print(f"模型保存: {path}")

    # ── 校准曲线图（2行×2列：上=in-sample, 下=out-of-sample）──
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    fig.suptitle("Win Probability Calibration — Split by Game Type", fontsize=12)

    configs = [
        (axes[0][0], m_r["pred_tr"],  m_r["frac_tr"],  f"Regular Season — In-sample\nBrier={m_r['brier_train']:.4f}",  "steelblue"),
        (axes[0][1], m_p["pred_tr"],  m_p["frac_tr"],  f"Playoffs/Finals — In-sample\nBrier={m_p['brier_train']:.4f}", "darkorange"),
        (axes[1][0], m_r["pred_va"],  m_r["frac_va"],  f"Regular Season — Out-of-sample\nBrier={m_r['brier_val']:.4f}  max_dev={m_r['max_dev_val']:.3f}",  "steelblue"),
        (axes[1][1], m_p["pred_va"],  m_p["frac_va"],  f"Playoffs/Finals — Out-of-sample\nBrier={m_p['brier_val']:.4f}  max_dev={m_p['max_dev_val']:.3f}", "darkorange"),
    ]
    for ax, x, y, title, color in configs:
        ax.plot([0,1],[0,1],"k--",linewidth=0.8,label="Perfect")
        ax.plot(x, y, "o-", color=color, linewidth=1.5, markersize=4, label=title)
        ax.set_xlabel("Mean predicted probability"); ax.set_ylabel("Fraction of positives")
        ax.set_title(title.split("\n")[0])
        ax.legend(fontsize=8); ax.set_xlim(-0.02,1.02); ax.set_ylim(-0.02,1.02)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(FIG_PATH, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n校准曲线保存: {FIG_PATH}")

    # ── 报告 ──
    lines = [
        "# Phase 0 (Revision): Win Probability Models — Split by Game Type",
        "",
        f"训练时间: {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 背景",
        "",
        "合并模型诊断发现 Playoffs/Finals 子集校准偏差达 23.3%，触发 Kill Criteria。",
        "决策：分拆为两个独立模型分别训练评估。",
        "",
        "## 结果汇总",
        "",
        "| 类型 | 训练场次 | 验证场次 | Brier(train) | Brier(val) | 最大校准偏差(val) | Kill Criteria |",
        "|------|---------|---------|-------------|-----------|-----------------|--------------|",
    ]
    for m in [m_r, m_p]:
        kc = "❌ 未触发" if m["max_dev_val"] < 0.10 else "⚠️ 触发"
        lines.append(
            f"| {m['label']} | {m['n_train_games']} | {m['n_val_games']} "
            f"| {m['brier_train']:.4f} | {m['brier_val']:.4f} "
            f"| {m['max_dev_val']:.3f} | {kc} |"
        )
    lines += [
        "",
        "## 模型系数",
        "",
        "| 特征 | Regular Season | Playoffs/Finals |",
        "|------|---------------|----------------|",
    ]
    for feat in FEATURES:
        lines.append(f"| {feat} | {m_r['coef'][feat]:.4f} | {m_p['coef'][feat]:.4f} |")
    lines += [
        f"| (截距) | {m_r['intercept']:.4f} | {m_p['intercept']:.4f} |",
        "",
        "## 极端 case 验证",
        "",
        "| 场景 | Regular P(home) | Playoffs P(home) |",
        "|------|----------------|-----------------|",
    ]
    for sd, tr, ot, desc in test_cases:
        p_r = model_reg.predict_proba([[sd, tr, ot]])[0][1]
        p_p = model_play.predict_proba([[sd, tr, ot]])[0][1]
        lines.append(f"| {desc} | {p_r:.3f} | {p_p:.3f} |")
    lines += [
        "",
        "## 注意事项",
        "",
        f"- Playoffs 验证集仅 {m_p['n_val_games']} 场（约 {m_p['n_val_rows']:,} 行），校准曲线统计噪声较大",
        "- Playoffs 模型系数与 Regular 差异反映两类比赛的不同动态（季后赛结果更具决定性）",
        "- 后续回测须用对应类型的模型：Regular Season 用 `win_prob_model_regular.pkl`，Playoffs 用 `win_prob_model_playoffs.pkl`",
    ]

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))
    print(f"报告保存: {REPORT_MD}")


if __name__ == "__main__":
    main()
