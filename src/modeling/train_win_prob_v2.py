"""
Phase 0 v2: 加入 pregame_market_prob 特征重训两个子模型。

新增特征: pregame_market_prob = tip-off 前最后一笔 Kalshi 成交价（整场固定）
  Regular Season: P(home wins) from Kalshi home-team market
  Playoffs/Finals (镜像数据集):
    home 视角 (is_home=1): pregame_market_prob = home_market_prob
    away 视角 (is_home=0): pregame_market_prob = 1 - home_market_prob

Playoffs 训练集: 只保留有 Kalshi 数据的场次（2024-25/2025-26 Playoffs/Finals，共 ~88 场）
  原有 2021-24 历史数据无 Kalshi 覆盖，本版本不再使用。

训练/验证集按 game_id 切分（禁止按行切分）。
"""

import os
import pickle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

PBP_MAIN     = "data/processed/nba_pbp_parsed.csv"
PREGAME_CSV  = "data/processed/pregame_market_probs.csv"
FIG_DIR      = "outputs/figures"
REPORT_MD    = "outputs/reports/win_prob_v2_report.md"
SEED         = 42
TRAIN_FRAC   = 0.80

FEATURES_REG  = ["score_diff", "time_remaining_feature", "is_overtime", "pregame_market_prob"]
FEATURES_PLAY = ["lead", "time_remaining_feature", "is_overtime", "is_home", "pregame_market_prob"]


# ── 数据准备 ─────────────────────────────────────────────────────────────────

def load_pbp_with_pregame() -> pd.DataFrame:
    df = pd.read_csv(PBP_MAIN, dtype={"game_id": str, "period": int})

    # 最终比分标签
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
    df["time_remaining_feature"] = df.apply(
        lambda r: r["time_remaining"] + (r["period"] - 4) * 300
        if r["period"] > 4 else r["time_remaining"],
        axis=1,
    )

    # 合并赛前价格
    pregame = pd.read_csv(PREGAME_CSV, dtype={"game_id": str})
    pregame = pregame[["game_id", "pregame_market_prob"]].dropna()
    df = df.merge(pregame, on="game_id", how="inner")

    # 按 game_id 前缀分类
    prefix = df["game_id"].str[:3]
    df["game_type"] = "Other"
    df.loc[prefix == "002", "game_type"] = "Regular"
    df.loc[prefix.isin(["004", "005"]), "game_type"] = "Playoffs"

    return df.dropna(subset=["wall_utc"])


def split_by_game(df: pd.DataFrame, seed: int):
    games = df["game_id"].unique().copy()
    rng = np.random.default_rng(seed)
    rng.shuffle(games)
    n_train = int(len(games) * TRAIN_FRAC)
    train_g = set(games[:n_train])
    val_g   = set(games[n_train:])
    return df[df["game_id"].isin(train_g)], df[df["game_id"].isin(val_g)]


def mirror_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    主客场双视角数据增强（Playoffs 专用）。
    away 视角的 pregame_market_prob = 1 - home_market_prob，
    表示 P(away wins)，与 focal team 视角对称。
    split 在 mirror 之前按 game_id 完成，两条镜像数据始终在同一集合。
    """
    home = df.assign(
        is_home=1,
        lead=df["score_diff"],
        focal_wins=df["home_wins"],
        pregame_market_prob=df["pregame_market_prob"],
    )
    away = df.assign(
        is_home=0,
        lead=-df["score_diff"],
        focal_wins=1 - df["home_wins"],
        pregame_market_prob=1 - df["pregame_market_prob"],
    )
    return pd.concat([home, away], ignore_index=True)


# ── 训练与评估 ───────────────────────────────────────────────────────────────

def train_and_eval(df: pd.DataFrame, features: list[str], label_col: str,
                   label: str, seed: int, use_mirror: bool = False):
    """
    按 game_id 切分 → (可选)镜像 → 训练 LR → 校准评估。
    返回 (model, metrics_dict)。
    """
    train_df, val_df = split_by_game(df, seed)

    if use_mirror:
        train_m = mirror_dataset(train_df)
        val_m   = mirror_dataset(val_df)
    else:
        train_m, val_m = train_df, val_df

    X_tr = train_m[features].values;  y_tr = train_m[label_col].values
    X_va = val_m[features].values;    y_va = val_m[label_col].values

    model = LogisticRegression(max_iter=2000, random_state=seed)
    model.fit(X_tr, y_tr)

    prob_tr = model.predict_proba(X_tr)[:, 1]
    prob_va = model.predict_proba(X_va)[:, 1]

    brier_tr = brier_score_loss(y_tr, prob_tr)
    brier_va = brier_score_loss(y_va, prob_va)

    n_bins = 10 if val_df["game_id"].nunique() < 30 else 15
    frac_tr, pred_tr = calibration_curve(y_tr, prob_tr, n_bins=n_bins, strategy="uniform")
    frac_va, pred_va = calibration_curve(y_va, prob_va, n_bins=n_bins, strategy="uniform")
    max_dev_va = float(np.abs(frac_va - pred_va).max())

    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"  训练场次: {train_df['game_id'].nunique()} / 行: {len(train_m):,}")
    print(f"  验证场次: {val_df['game_id'].nunique()} / 行: {len(val_m):,}")
    print(f"  Brier: in={brier_tr:.4f}  out={brier_va:.4f}")
    print(f"  最大校准偏差(val): {max_dev_va:.3f}")
    coef = dict(zip(features, model.coef_[0]))
    print(f"  系数: {coef}")

    kill = max_dev_va >= 0.10
    if kill:
        print(f"  ⚠️  Kill Criteria 触发 (max_dev={max_dev_va:.3f} ≥ 0.10)")
    else:
        print(f"  ✅ Kill Criteria 未触发")

    return model, {
        "label":          label,
        "n_train_games":  train_df["game_id"].nunique(),
        "n_val_games":    val_df["game_id"].nunique(),
        "n_train_rows":   len(train_m),
        "n_val_rows":     len(val_m),
        "brier_train":    brier_tr,
        "brier_val":      brier_va,
        "max_dev_val":    max_dev_va,
        "coef":           coef,
        "intercept":      model.intercept_[0],
        "frac_tr": frac_tr, "pred_tr": pred_tr,
        "frac_va": frac_va, "pred_va": pred_va,
        "kill":           kill,
    }


# ── 极端 case 验证 ────────────────────────────────────────────────────────────

def extreme_cases(model_reg, model_play):
    print("\n极端 case 验证:")
    # Regular: [score_diff, time_remaining_feature, is_overtime, pregame_market_prob]
    reg_cases = [
        (30,  10, 0, 0.7, "+30分 剩10s 赛前主场强队(0.7)"),
        (-30, 10, 0, 0.7, "-30分 剩10s 赛前主场强队(0.7)"),
        (0,   60, 0, 0.7, "平局 剩60s 赛前主场强队(0.7)"),
        (0,   60, 0, 0.3, "平局 剩60s 赛前主场弱队(0.3)"),
        (0, 2880, 0, 0.8, "开局平局 赛前主场超强(0.8)"),
        (0, 2880, 0, 0.2, "开局平局 赛前主场超弱(0.2)"),
    ]
    print("  Regular Season:")
    for sd, tr, ot, pp, desc in reg_cases:
        p = model_reg.predict_proba([[sd, tr, ot, pp]])[0][1]
        print(f"    {desc}: P(home)={p:.3f}")

    # Playoffs: [lead, time_remaining_feature, is_overtime, is_home, pregame_market_prob]
    play_cases = [
        (30,  10, 0, 1, 0.7, "+30分 剩10s 主场视角 赛前强(0.7)"),
        (-30, 10, 0, 0, 0.3, "-30分 剩10s 客场视角 赛前强(0.3→away=0.7)"),
        (0,   60, 0, 1, 0.8, "平局 剩60s 主场视角 超强(0.8)"),
        (0,   60, 0, 0, 0.2, "平局 剩60s 客场视角 超弱(0.2→away=0.8)"),
    ]
    print("  Playoffs/Finals:")
    for ld, tr, ot, ih, pp, desc in play_cases:
        p = model_play.predict_proba([[ld, tr, ot, ih, pp]])[0][1]
        print(f"    {desc}: P(focal)={p:.3f}")

    return reg_cases, play_cases


# ── 校准曲线图 ────────────────────────────────────────────────────────────────

def plot_calibration(m_r: dict, m_p: dict, out_path: str):
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    fig.suptitle("Win Prob v2 (+ pregame_market_prob) — Calibration", fontsize=12)

    configs = [
        (axes[0][0], m_r["pred_tr"], m_r["frac_tr"],
         f"Regular In-sample  Brier={m_r['brier_train']:.4f}", "steelblue"),
        (axes[0][1], m_p["pred_tr"], m_p["frac_tr"],
         f"Playoffs In-sample  Brier={m_p['brier_train']:.4f}", "darkorange"),
        (axes[1][0], m_r["pred_va"], m_r["frac_va"],
         f"Regular Out-of-sample  Brier={m_r['brier_val']:.4f}  max_dev={m_r['max_dev_val']:.3f}",
         "steelblue"),
        (axes[1][1], m_p["pred_va"], m_p["frac_va"],
         f"Playoffs Out-of-sample  Brier={m_p['brier_val']:.4f}  max_dev={m_p['max_dev_val']:.3f}",
         "darkorange"),
    ]
    for ax, x, y, title, color in configs:
        ax.plot([0, 1], [0, 1], "k--", lw=0.8, label="Perfect")
        ax.plot(x, y, "o-", color=color, lw=1.5, markersize=4, label=title)
        ax.set_xlabel("Mean predicted probability")
        ax.set_ylabel("Fraction of positives")
        ax.set_title(title.split("  ")[0], fontsize=9)
        ax.legend(fontsize=7); ax.set_xlim(-0.02, 1.02); ax.set_ylim(-0.02, 1.02)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"校准曲线: {out_path}")


# ── 报告 ────────────────────────────────────────────────────────────────────

def write_report(m_r: dict, m_p: dict, reg_cases, play_cases, model_reg, model_play):
    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)
    lines = [
        "# Win Probability Model v2 (+ pregame_market_prob)",
        "",
        f"训练时间: {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 模型变更",
        "",
        "新增特征 `pregame_market_prob`: tip-off 前最后一笔 Kalshi 成交价，整场固定不变。",
        "Playoffs 镜像数据集中，away 视角使用 `1 - home_market_prob`，保持 focal-team 视角对称。",
        "Playoffs 训练集仅保留有 Kalshi 数据场次（约 88 场，不含 2021-24 历史数据）。",
        "",
        "## 评估结果",
        "",
        "| 子模型 | 训练场次 | 验证场次 | Brier(train) | Brier(val) | max_dev | Kill Criteria |",
        "|--------|---------|---------|-------------|-----------|--------|--------------|",
    ]
    for m in [m_r, m_p]:
        kc = "❌ 未触发" if not m["kill"] else "⚠️ 触发"
        lines.append(
            f"| {m['label']} | {m['n_train_games']} | {m['n_val_games']} "
            f"| {m['brier_train']:.4f} | {m['brier_val']:.4f} "
            f"| {m['max_dev_val']:.3f} | {kc} |"
        )

    lines += [
        "",
        "## 模型系数",
        "",
        "### Regular Season",
        "",
        "| 特征 | 系数 |",
        "|------|------|",
    ]
    for feat, c in m_r["coef"].items():
        lines.append(f"| {feat} | {c:.4f} |")
    lines.append(f"| (截距) | {m_r['intercept']:.4f} |")

    lines += [
        "",
        "### Playoffs/Finals",
        "",
        "| 特征 | 系数 |",
        "|------|------|",
    ]
    for feat, c in m_p["coef"].items():
        lines.append(f"| {feat} | {c:.4f} |")
    lines.append(f"| (截距) | {m_p['intercept']:.4f} |")

    lines += ["", "## 极端 case 验证", "", "### Regular Season", "",
              "| 场景 | P(home wins) |", "|------|-------------|"]
    for sd, tr, ot, pp, desc in reg_cases:
        p = model_reg.predict_proba([[sd, tr, ot, pp]])[0][1]
        lines.append(f"| {desc} | {p:.3f} |")

    lines += ["", "### Playoffs/Finals", "",
              "| 场景 | P(focal wins) |", "|------|--------------|"]
    for ld, tr, ot, ih, pp, desc in play_cases:
        p = model_play.predict_proba([[ld, tr, ot, ih, pp]])[0][1]
        lines.append(f"| {desc} | {p:.3f} |")

    lines += [
        "",
        "## 已知局限",
        "",
        "- Playoffs 训练场次从 276 降至约 88，校准统计噪声更大",
        "- 比赛末段极端 spread（如 -0.4）预期仍然存在，来源是战术犯规/暂停等",
        "  特征缺失问题，不是 pregame_market_prob 要解决的问题，记录为已知局限",
    ]

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))
    print(f"报告: {REPORT_MD}")


# ── 主函数 ────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs("outputs/reports", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)

    print("加载数据 ...")
    df = load_pbp_with_pregame()
    counts = df.groupby("game_type")["game_id"].nunique()
    print("场次分布:")
    print(counts.to_string())

    reg_df  = df[df["game_type"] == "Regular"].copy()
    play_df = df[df["game_type"] == "Playoffs"].copy()

    print(f"\nRegular Season pregame_prob 统计: "
          f"mean={reg_df.groupby('game_id')['pregame_market_prob'].first().mean():.3f} "
          f"std={reg_df.groupby('game_id')['pregame_market_prob'].first().std():.3f}")

    # ── Regular Season ─────────────────────────────────────────────────────
    model_reg, m_r = train_and_eval(
        reg_df, FEATURES_REG, "home_wins", "Regular Season", SEED, use_mirror=False
    )

    # ── Playoffs/Finals ────────────────────────────────────────────────────
    model_play, m_p = train_and_eval(
        play_df, FEATURES_PLAY, "focal_wins", "Playoffs/Finals", SEED, use_mirror=True
    )

    # ── Kill Criteria 汇总 ─────────────────────────────────────────────────
    print("\n=== Kill Criteria 汇总 ===")
    for m in [m_r, m_p]:
        status = "⚠️ 触发" if m["kill"] else "✅ 未触发"
        print(f"  {m['label']}: max_dev={m['max_dev_val']:.3f} → {status}")

    # ── 极端 case ──────────────────────────────────────────────────────────
    reg_cases, play_cases = extreme_cases(model_reg, model_play)

    # ── 保存模型 ──────────────────────────────────────────────────────────
    for mdl, path, name, feats, meta in [
        (model_reg,  "data/processed/win_prob_model_regular_v2.pkl",  "Regular",
         FEATURES_REG,  {"note": "v2: added pregame_market_prob"}),
        (model_play, "data/processed/win_prob_model_playoffs_v2.pkl", "Playoffs",
         FEATURES_PLAY, {"note": "v2: added pregame_market_prob; away uses 1-home_market_prob; trained on Kalshi-mapped games only"}),
    ]:
        payload = {
            "model":      mdl,
            "features":   feats,
            "game_type":  name,
            "model_type": "LogisticRegression",
        }
        payload.update(meta)
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        print(f"模型保存: {path}")

    # ── 可视化 ────────────────────────────────────────────────────────────
    plot_calibration(m_r, m_p, os.path.join(FIG_DIR, "win_prob_v2_calibration.png"))

    # ── 报告 ──────────────────────────────────────────────────────────────
    write_report(m_r, m_p, reg_cases, play_cases, model_reg, model_play)


if __name__ == "__main__":
    main()
