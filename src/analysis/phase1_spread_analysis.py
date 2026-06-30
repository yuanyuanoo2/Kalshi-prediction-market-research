"""
Phase 1: 市场价差与收敛时间分析（含 pregame_market_prob、收敛过滤、阶段拆分）

新增 / 修改:
  pregame_market_prob — tip-off 前最后一笔成交价，整场固定不变，捕捉赛前隐含胜率
  收敛过滤 ≥10s     — |spread|>5% 须连续维持 ≥10s 才算有效事件，剔除振荡噪声
  比赛阶段拆分       — "开局" (time_remaining > 1440s, 上半场) vs "后半" (≤1440s)
                      定义依据：以 24 分钟（2880s 的一半）为界，客观、不依赖比分

无 look-ahead bias 保证:
  在每个成交时间点 t，只使用 PBP 中 wall_utc ≤ t 的最近一行计算 P_model(t)。
  pregame_market_prob 取 game_start 之前的数据，不含比赛内信息。
"""

import json
import os
import pickle
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── 路径 ────────────────────────────────────────────────────────────────────
PBP_CSV        = "data/processed/nba_pbp_parsed.csv"
MODEL_REG_PKL  = "data/processed/win_prob_model_regular_v2.pkl"
MODEL_PLAY_PKL = "data/processed/win_prob_model_playoffs_v2.pkl"
TRADES_DIR     = "data/raw/phase1_trades"
FIG_DIR        = "outputs/figures"
REPORT_MD      = "outputs/reports/phase1_spread_report.md"

GAP_THRESHOLD   = 0.05   # 5% spread threshold
MIN_PERSIST_S   = 10.0   # 连续维持 ≥10s 才计入有效事件
# 上半场 / 下半场 分界（秒）：常规赛共 2880s，1440s = 正好一半
HALFTIME_TR     = 1440


# ── 数据加载 ────────────────────────────────────────────────────────────────

def load_models():
    with open(MODEL_REG_PKL, "rb") as f:
        reg = pickle.load(f)
    with open(MODEL_PLAY_PKL, "rb") as f:
        play = pickle.load(f)
    return reg["model"], play["model"]


def load_pbp() -> pd.DataFrame:
    df = pd.read_csv(PBP_CSV, dtype={"game_id": str, "period": int})
    df["wall_utc"]            = pd.to_numeric(df["wall_utc"], errors="coerce")
    df["score_diff"]          = pd.to_numeric(df["score_diff"], errors="coerce")
    df["time_remaining"]      = pd.to_numeric(df["time_remaining"], errors="coerce")
    df["is_overtime"]         = (df["period"] > 4).astype(int)
    df["time_remaining_feature"] = df.apply(
        lambda r: r["time_remaining"] + (r["period"] - 4) * 300
        if r["period"] > 4 else r["time_remaining"],
        axis=1,
    )
    return df.dropna(subset=["wall_utc", "score_diff"]).sort_values(["game_id", "wall_utc"])


# ── pregame_market_prob ──────────────────────────────────────────────────────

def extract_pregame_prob(trades: list[dict], game_start: float) -> float | None:
    """
    取 tip-off（game_start）前最后一笔成交的 yes_price_dollars。
    整场比赛中固定不变，不随时间更新。
    若无赛前成交记录则返回 None。
    """
    pre = []
    for t in trades:
        try:
            ts    = pd.Timestamp(t["created_time"], tz="UTC").timestamp()
            price = float(t["yes_price_dollars"])
            if ts < game_start:
                pre.append((ts, price))
        except Exception:
            continue
    if not pre:
        return None
    pre.sort(key=lambda x: x[0])
    return pre[-1][1]  # 最后一笔赛前成交价


# ── 收敛时间（过滤前 / 过滤后）────────────────────────────────────────────────

def _raw_gap_events(t: np.ndarray, sp: np.ndarray, threshold: float) -> list[tuple[float, float]]:
    """
    返回所有 gap 事件 (start_ts, conv_time_s) 列表（未经持续时间过滤）。
    gap 从第一个 sp[i] > threshold 开始，到第一个 sp[j] ≤ threshold 结束。
    """
    n = len(sp)
    events = []
    i = 0
    while i < n:
        if sp[i] > threshold:
            j = i + 1
            while j < n and sp[j] > threshold:
                j += 1
            if j < n:
                events.append((t[i], float(t[j] - t[i])))
            i = j
        else:
            i += 1
    return events


def gap_convergence_times(
    tdf: pd.DataFrame,
    threshold: float,
    min_persist_s: float,
) -> tuple[list[float], list[float]]:
    """
    返回 (raw_times, filtered_times):
      raw_times     — 过滤前全部收敛时间列表
      filtered_times — 仅保留持续时间 ≥ min_persist_s 的事件
    """
    t  = tdf["t"].values
    sp = np.abs(tdf["spread"].values)

    raw_events = _raw_gap_events(t, sp, threshold)
    raw_times      = [e[1] for e in raw_events]
    filtered_times = [e[1] for e in raw_events if e[1] >= min_persist_s]
    return raw_times, filtered_times


# ── 比赛阶段拆分 spread ──────────────────────────────────────────────────────

def phase_spread(tdf: pd.DataFrame, pbp_tr: np.ndarray, pbp_times: np.ndarray) -> dict:
    """
    按 time_remaining_feature 拆分 "开局" vs "后半"。
    开局：time_remaining_feature > HALFTIME_TR（上半场，>24min）
    后半：time_remaining_feature ≤ HALFTIME_TR（下半场 + OT）

    依据：2880s 常规赛时间的自然中点，客观且不依赖比分动态。
    """
    t_arr = tdf["t"].values
    idx = np.searchsorted(pbp_times, t_arr, side="right") - 1
    idx = np.clip(idx, 0, len(pbp_times) - 1)
    tr_at_trade = pbp_tr[idx]

    sp = np.abs(tdf["spread"].values)
    opening = sp[tr_at_trade > HALFTIME_TR]
    closing = sp[tr_at_trade <= HALFTIME_TR]

    return {
        "opening_mean":  float(opening.mean()) if len(opening) else np.nan,
        "opening_n":     int(len(opening)),
        "closing_mean":  float(closing.mean()) if len(closing) else np.nan,
        "closing_n":     int(len(closing)),
    }


# ── 单场分析 ─────────────────────────────────────────────────────────────────

def analyze_game(
    game_json: dict,
    pbp_game: pd.DataFrame,
    model_reg,
    model_play,
) -> dict | None:
    """
    分析单场比赛。
    P_model(t) 只使用 wall_utc ≤ t 的 PBP 数据（无 look-ahead bias）。
    pregame_market_prob 取 game_start 前最后一笔，整场固定。
    """
    gid      = game_json["nba_game_id"]
    game_cat = game_json["game_cat"]
    trades   = game_json.get("trades", [])

    if not trades or pbp_game.empty:
        return None

    # 全部 trade 解析（时序）
    trade_rows = []
    for t in trades:
        try:
            ts    = pd.Timestamp(t["created_time"], tz="UTC").timestamp()
            price = float(t["yes_price_dollars"])
            trade_rows.append({"t": ts, "price": price})
        except Exception:
            continue

    if not trade_rows:
        return None

    tdf_all = pd.DataFrame(trade_rows).sort_values("t").reset_index(drop=True)

    game_start = pbp_game["wall_utc"].min()
    game_end   = pbp_game["wall_utc"].max()

    # pregame_market_prob：tip-off 前最后一笔，整场固定
    pregame_prob = extract_pregame_prob(trades, game_start)

    # 只保留比赛进行期间的成交
    tdf = tdf_all[(tdf_all["t"] >= game_start) & (tdf_all["t"] <= game_end)].copy().reset_index(drop=True)
    if len(tdf) < 10:
        return None

    # PBP 快照数组（已按 wall_utc 升序排列）
    pbp_times = pbp_game["wall_utc"].values
    pbp_sd    = pbp_game["score_diff"].values
    pbp_tr    = pbp_game["time_remaining_feature"].values
    pbp_ot    = pbp_game["is_overtime"].values

    # 在每个成交时间点查最近 PBP 快照（LOCF，无 look-ahead bias）
    t_arr = tdf["t"].values
    idx = np.searchsorted(pbp_times, t_arr, side="right") - 1
    idx = np.clip(idx, 0, len(pbp_times) - 1)

    sd = pbp_sd[idx]
    tr = pbp_tr[idx]
    ot = pbp_ot[idx]

    # P_model（v2: 需要 pregame_market_prob，整场固定，在 game_start 前确定，无 look-ahead bias）
    pp_val = pregame_prob if pregame_prob is not None else 0.5
    pp = np.full(len(t_arr), pp_val)

    if game_cat == "Regular":
        # v2 features: [score_diff, time_remaining_feature, is_overtime, pregame_market_prob]
        X = np.column_stack([sd, tr, ot, pp])
        p_model = model_reg.predict_proba(X)[:, 1]
    else:
        # v2 features: [lead, time_remaining_feature, is_overtime, is_home, pregame_market_prob]
        is_home = np.ones(len(t_arr))
        X = np.column_stack([sd, tr, ot, is_home, pp])
        p_model = model_play.predict_proba(X)[:, 1]

    p_market = tdf["price"].values
    spread   = p_model - p_market

    tdf["p_model"]  = p_model
    tdf["p_market"] = p_market
    tdf["spread"]   = spread

    # 收敛时间（过滤前 / 过滤后）
    raw_times, filtered_times = gap_convergence_times(tdf, GAP_THRESHOLD, MIN_PERSIST_S)

    # 比赛阶段 spread
    phases = phase_spread(tdf, pbp_tr, pbp_times)

    return {
        "game_id":          gid,
        "game_cat":         game_cat,
        "n_trades":         len(tdf),
        "spread_df":        tdf,
        "pregame_prob":     pregame_prob,
        "raw_times":        raw_times,
        "filtered_times":   filtered_times,
        "n_gap_raw":        len(raw_times),
        "n_gap_filtered":   len(filtered_times),
        "mean_abs_spread":  float(np.abs(spread).mean()),
        "p90_abs_spread":   float(np.percentile(np.abs(spread), 90)),
        **phases,
    }


# ── 汇总 ────────────────────────────────────────────────────────────────────

def summarize(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        ft = r["filtered_times"]
        rt = r["raw_times"]
        rows.append({
            "game_id":          r["game_id"],
            "game_cat":         r["game_cat"],
            "n_trades":         r["n_trades"],
            "pregame_prob":     r.get("pregame_prob"),
            "mean_abs_spread":  r["mean_abs_spread"],
            "p90_abs_spread":   r["p90_abs_spread"],
            "n_gap_raw":        len(rt),
            "n_gap_filtered":   len(ft),
            "filter_rate":      1 - len(ft) / len(rt) if rt else np.nan,
            "conv_median_raw":  float(np.median(rt)) if rt else np.nan,
            "conv_p90_raw":     float(np.percentile(rt, 90)) if rt else np.nan,
            "conv_median_filt": float(np.median(ft)) if ft else np.nan,
            "conv_p90_filt":    float(np.percentile(ft, 90)) if ft else np.nan,
            "opening_mean":     r.get("opening_mean", np.nan),
            "closing_mean":     r.get("closing_mean", np.nan),
            "opening_n":        r.get("opening_n", 0),
            "closing_n":        r.get("closing_n", 0),
        })
    return pd.DataFrame(rows)


# ── 可视化 ──────────────────────────────────────────────────────────────────

def plot_spread_samples(results: list[dict], out_path: str):
    by_cat: dict[str, list] = {"Regular": [], "Playoffs": [], "Finals": []}
    for r in results:
        by_cat[r["game_cat"]].append(r)

    fig, axes = plt.subplots(3, 1, figsize=(14, 11))
    fig.suptitle("Phase 1: spread(t) = P_model - P_market", fontsize=12)
    colors = {"Regular": "steelblue", "Playoffs": "darkorange", "Finals": "crimson"}

    for ax, cat in zip(axes, ["Regular", "Playoffs", "Finals"]):
        group = by_cat.get(cat, [])
        if not group:
            ax.set_title(f"{cat} - no data")
            continue
        sample = max(group, key=lambda r: r["n_gap_raw"])
        df = sample["spread_df"]
        t0 = df["t"].min()
        t_rel = (df["t"] - t0) / 60
        ax.plot(t_rel, df["spread"], lw=0.6, alpha=0.7, color=colors[cat])
        ax.axhline(GAP_THRESHOLD,  color="gray", ls="--", lw=0.8)
        ax.axhline(-GAP_THRESHOLD, color="gray", ls="--", lw=0.8)
        ax.axhline(0, color="black", lw=0.5)
        pp = sample.get("pregame_prob")
        pp_str = f"  pregame_prob={pp:.3f}" if pp is not None else ""
        title = f"{cat} - {sample['game_id']} ({sample['n_trades']} trades){pp_str}"
        if cat in ("Playoffs", "Finals"):
            title += " [low model confidence]"
        ax.set_title(title, fontsize=9)
        ax.set_ylabel("spread")
        ax.set_xlabel("minutes from first trade")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"spread samples: {out_path}")


def plot_convergence_dist(results: list[dict], out_path: str):
    by_raw:  dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    by_filt: dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    for r in results:
        by_raw[r["game_cat"]].extend(r["raw_times"])
        by_filt[r["game_cat"]].extend(r["filtered_times"])

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    fig.suptitle(f"|spread|>{GAP_THRESHOLD*100:.0f}% convergence time (top=raw, bottom=filtered >=10s)", fontsize=11)
    colors = {"Regular": "steelblue", "Playoffs": "darkorange", "Finals": "crimson"}

    for col, cat in enumerate(["Regular", "Playoffs", "Finals"]):
        for row, (data, label) in enumerate([(by_raw[cat], "raw"), (by_filt[cat], ">=10s")]):
            ax = axes[row][col]
            if not data:
                ax.set_title(f"{cat} {label} - no events")
                continue
            arr = np.array(data)
            ax.hist(arr, bins=40, color=colors[cat], alpha=0.7, edgecolor="white")
            med = np.median(arr)
            p90 = np.percentile(arr, 90)
            ax.axvline(med, color="black", ls="--", lw=1.1, label=f"med={med:.0f}s")
            ax.axvline(p90, color="red",   ls=":",  lw=1.1, label=f"p90={p90:.0f}s")
            note = " [low conf]" if cat in ("Playoffs", "Finals") else ""
            ax.set_title(f"{cat} {label} (n={len(arr)}){note}", fontsize=9)
            ax.set_xlabel("convergence time (s)")
            ax.set_ylabel("count")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"convergence dist: {out_path}")


def plot_phase_spread(results: list[dict], out_path: str):
    """开局 vs 后半阶段 mean|spread| 对比（按类型分组）。"""
    by_cat: dict[str, list] = {"Regular": [], "Playoffs": [], "Finals": []}
    for r in results:
        by_cat[r["game_cat"]].append(r)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Mean |spread| by game phase: opening (>24min) vs closing (<=24min)", fontsize=11)
    colors = {"Regular": "steelblue", "Playoffs": "darkorange", "Finals": "crimson"}

    for ax, cat in zip(axes, ["Regular", "Playoffs", "Finals"]):
        group = by_cat.get(cat, [])
        if not group:
            ax.set_title(f"{cat} - no data")
            continue

        opening = [r["opening_mean"] for r in group if not np.isnan(r.get("opening_mean", np.nan))]
        closing = [r["closing_mean"] for r in group if not np.isnan(r.get("closing_mean", np.nan))]

        positions = [1, 2]
        bp = ax.boxplot(
            [opening, closing],
            positions=positions,
            patch_artist=True,
            widths=0.5,
        )
        for patch, c in zip(bp["boxes"], [colors[cat], colors[cat]]):
            patch.set_facecolor(c)
            patch.set_alpha(0.6 if patch == bp["boxes"][0] else 0.9)

        ax.set_xticks(positions)
        ax.set_xticklabels(["Opening\n(>24min)", "Closing\n(<=24min)"])
        note = " [low conf]" if cat in ("Playoffs", "Finals") else ""
        ax.set_title(f"{cat}{note}\nopening med={np.median(opening):.3f} closing med={np.median(closing):.3f}", fontsize=9)
        ax.set_ylabel("mean |spread| per game")
        ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"phase spread: {out_path}")


# ── 报告 ────────────────────────────────────────────────────────────────────

def write_report(summary_df: pd.DataFrame, results: list[dict]):
    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)

    by_raw:  dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    by_filt: dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    by_open: dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    by_clos: dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}

    for r in results:
        cat = r["game_cat"]
        by_raw[cat].extend(r["raw_times"])
        by_filt[cat].extend(r["filtered_times"])
        if not np.isnan(r.get("opening_mean", np.nan)):
            by_open[cat].append(r["opening_mean"])
        if not np.isnan(r.get("closing_mean", np.nan)):
            by_clos[cat].append(r["closing_mean"])

    lines = [
        "# Phase 1: 市场价差与收敛时间分析（修订版）",
        "",
        f"生成时间: {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 分析设置",
        "",
        f"- Gap threshold: {GAP_THRESHOLD*100:.0f}%",
        f"- 收敛过滤: gap 须连续维持 ≥{MIN_PERSIST_S:.0f}s 才计入有效事件",
        f"- 比赛阶段分界: time_remaining_feature > {HALFTIME_TR}s 为开局（上半场），≤{HALFTIME_TR}s 为后半场",
        "- pregame_market_prob: tip-off 前最后一笔成交价，整场固定",
        "- Playoffs/Finals 模型置信度较低（14.3% 已知偏差），结果须保守解读",
        "",
        "## 1. 收敛时间：过滤前 vs 过滤后（≥10s）",
        "",
        "| 类别 | 过滤前事件数 | 过滤后事件数 | 过滤比例 | 过滤后中位数 | 过滤后p90 |",
        "|------|------------|------------|---------|------------|---------|",
    ]

    for cat in ["Regular", "Playoffs", "Finals"]:
        rt = by_raw[cat]
        ft = by_filt[cat]
        note = "" if cat == "Regular" else " ⚠️"
        if not rt:
            lines.append(f"| {cat} | 0 | 0 | — | — | — |{note}")
            continue
        filt_rate = (1 - len(ft) / len(rt)) * 100
        med_f = f"{np.median(ft):.0f}s" if ft else "—"
        p90_f = f"{np.percentile(ft, 90):.0f}s" if ft else "—"
        lines.append(
            f"| {cat}{note} | {len(rt)} | {len(ft)} | {filt_rate:.0f}% | {med_f} | {p90_f} |"
        )

    lines += [
        "",
        "## 2. 比赛阶段 spread 对比（验证模型缺球队实力信息假设）",
        "",
        f"定义: 开局 = time_remaining > {HALFTIME_TR}s（上半场 > 24 min）；"
        f"后半 = time_remaining ≤ {HALFTIME_TR}s",
        "",
        "| 类别 | 开局 mean|spread| | 后半 mean|spread| | 差值 | 结论 |",
        "|------|-----------------|-----------------|------|------|",
    ]
    for cat in ["Regular", "Playoffs", "Finals"]:
        op = by_open[cat]
        cl = by_clos[cat]
        note = "" if cat == "Regular" else " ⚠️"
        if not op or not cl:
            lines.append(f"| {cat}{note} | — | — | — | 数据不足 |")
            continue
        med_op = np.median(op)
        med_cl = np.median(cl)
        diff   = med_op - med_cl
        if diff > 0.02:
            conclusion = "开局>后半，支持'缺球队实力信息'假设"
        elif diff < -0.02:
            conclusion = "后半>开局，反向，需排查其他原因"
        else:
            conclusion = "两阶段接近，假设不成立，需重新排查"
        lines.append(
            f"| {cat}{note} | {med_op:.3f} | {med_cl:.3f} | {diff:+.3f} | {conclusion} |"
        )

    lines += [
        "",
        "## 3. pregame_market_prob 统计",
        "",
        "| 类别 | 均值 | 中位数 | min | max | 备注 |",
        "|------|------|------|-----|-----|------|",
    ]
    for cat in ["Regular", "Playoffs", "Finals"]:
        pp_vals = [r["pregame_prob"] for r in results if r["game_cat"] == cat and r.get("pregame_prob") is not None]
        note = "" if cat == "Regular" else " ⚠️"
        if not pp_vals:
            lines.append(f"| {cat}{note} | — | — | — | — | 无赛前成交 |")
            continue
        arr = np.array(pp_vals)
        lines.append(
            f"| {cat}{note} | {arr.mean():.3f} | {np.median(arr):.3f} "
            f"| {arr.min():.3f} | {arr.max():.3f} | |"
        )

    lines += [
        "",
        "## 4. 各场明细",
        "",
        "| game_id | 类型 | trades | pregame_prob | mean|spread| | gap_raw | gap_filt | filt% | opening_mean | closing_mean |",
        "|---------|------|--------|-------------|-------------|---------|---------|-------|-------------|-------------|",
    ]
    for _, row in summary_df.sort_values(["game_cat", "game_id"]).iterrows():
        pp = f"{row['pregame_prob']:.3f}" if pd.notna(row["pregame_prob"]) else "—"
        op = f"{row['opening_mean']:.3f}" if pd.notna(row["opening_mean"]) else "—"
        cl = f"{row['closing_mean']:.3f}" if pd.notna(row["closing_mean"]) else "—"
        fr = f"{row['filter_rate']*100:.0f}%" if pd.notna(row["filter_rate"]) else "—"
        lines.append(
            f"| {row['game_id']} | {row['game_cat']} | {row['n_trades']:,} "
            f"| {pp} | {row['mean_abs_spread']:.3f} "
            f"| {int(row['n_gap_raw'])} | {int(row['n_gap_filtered'])} | {fr} "
            f"| {op} | {cl} |"
        )

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))
    print(f"报告: {REPORT_MD}")


# ── 主函数 ───────────────────────────────────────────────────────────────────

def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs("outputs/reports", exist_ok=True)

    print("加载模型和 PBP ...")
    model_reg, model_play = load_models()
    pbp_all = load_pbp()
    print(f"  PBP: {len(pbp_all):,} 行, {pbp_all['game_id'].nunique()} 场")

    trade_files = sorted(Path(TRADES_DIR).glob("*.json"))
    print(f"  trades 文件: {len(trade_files)} 个")

    results = []
    for fp in trade_files:
        with open(fp) as f:
            gj = json.load(f)
        gid = gj["nba_game_id"]
        pbp_game = pbp_all[pbp_all["game_id"] == gid].copy()

        r = analyze_game(gj, pbp_game, model_reg, model_play)
        if r is None:
            print(f"  [{gid}] 跳过")
            continue
        results.append(r)
        pp = f"{r['pregame_prob']:.3f}" if r.get("pregame_prob") is not None else "N/A"
        print(
            f"  [{gid}] {gj['game_cat']:8s} | {r['n_trades']:5d} trades "
            f"| pregame={pp} | mean|sp|={r['mean_abs_spread']:.3f} "
            f"| gap {r['n_gap_raw']}->{r['n_gap_filtered']} "
            f"| open={r.get('opening_mean', float('nan')):.3f} clos={r.get('closing_mean', float('nan')):.3f}"
        )

    print(f"\n有效场次: {len(results)}")

    summary_df = summarize(results)
    summary_df.to_csv("outputs/reports/phase1_summary.csv", index=False)
    print("汇总 CSV: outputs/reports/phase1_summary.csv")

    plot_spread_samples(results, os.path.join(FIG_DIR, "phase1_spread_samples.png"))
    plot_convergence_dist(results, os.path.join(FIG_DIR, "phase1_convergence_dist.png"))
    plot_phase_spread(results, os.path.join(FIG_DIR, "phase1_phase_spread.png"))
    write_report(summary_df, results)

    # 核心数字打印
    by_raw:  dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    by_filt: dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    by_open: dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    by_clos: dict[str, list[float]] = {"Regular": [], "Playoffs": [], "Finals": []}
    for r in results:
        cat = r["game_cat"]
        by_raw[cat].extend(r["raw_times"])
        by_filt[cat].extend(r["filtered_times"])
        if not np.isnan(r.get("opening_mean", np.nan)):
            by_open[cat].append(r["opening_mean"])
        if not np.isnan(r.get("closing_mean", np.nan)):
            by_clos[cat].append(r["closing_mean"])

    print("\n=== 收敛时间：过滤前 → 过滤后（≥10s）===")
    for cat in ["Regular", "Playoffs", "Finals"]:
        rt = by_raw[cat]; ft = by_filt[cat]
        note = "" if cat == "Regular" else " [⚠️ 模型置信度低]"
        if not rt:
            print(f"  {cat}: 无事件{note}")
            continue
        fr = (1 - len(ft)/len(rt))*100
        med_f = f"{np.median(ft):.0f}s" if ft else "—"
        p90_f = f"{np.percentile(ft,90):.0f}s" if ft else "—"
        print(f"  {cat}{note}: {len(rt)} → {len(ft)} ({fr:.0f}% 过滤), 中位数={med_f}, p90={p90_f}")

    print("\n=== 比赛阶段 mean|spread|（中位数跨场次）===")
    for cat in ["Regular", "Playoffs", "Finals"]:
        op = by_open[cat]; cl = by_clos[cat]
        note = "" if cat == "Regular" else " [⚠️]"
        if not op or not cl:
            continue
        print(
            f"  {cat}{note}: 开局={np.median(op):.3f}  后半={np.median(cl):.3f}"
            f"  差值={np.median(op)-np.median(cl):+.3f}"
        )


if __name__ == "__main__":
    main()
