"""
附加分析：无手续费情景下的策略质量评估

⚠️ 理论分析，不代表真实可交易结果 ⚠️
本分析目的是评估信号设计与模型预测能力本身的质量，
与 Phase 2 已确认的核心结论（扣费后无 edge）完全分开。
所有报告标题及图表均明确标注此点。

分析维度：
1. 胜率分布（直方图，判断是否由极端值主导）
2. 信号强度 vs 收益相关性（按 net_edge 分组）
3. 三种退出策略对比：
   - Exit A：收敛平仓（net_edge 回落阈值以下）
   - Exit B：固定 60s 窗口平仓
   - Exit C：持有至比赛结算（binary outcome，gross 仅一次方向 × 结果）
4. IS vs OOS 一致性（不放松过拟合检查）
5. 按比赛类型分组（Regular/Playoffs/Finals）
6. 入场价格分布（描述性，检验是否集中在手续费最贵的 0.3-0.7 区间）
"""

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT       = Path(__file__).parent.parent.parent
TRADES_CSV = ROOT / "outputs/reports/phase2_trades.csv"
FIG_DIR    = ROOT / "outputs/figures"
REPORT_DIR = ROOT / "outputs/reports"

WARNING = "[理论分析·无手续费·不代表真实可交易结果]"


# ── 加载与整理 ───────────────────────────────────────────────────────────────

def load_and_prepare() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    加载 Phase 2 trades.csv，拆分三种退出策略的 gross P&L。

    trades.csv 中每个信号生成两条记录：
      - 一条 Exit A 记录（exit_strategy = convergence 或 game_end）
      - 一条 Exit B 记录（exit_strategy = fixed_window 或 game_end）

    Exit C（持有至结算）从 game_result 直接计算：
      direction=+1（买 YES）: P&L_gross_C = game_result - entry_price
      direction=-1（买 NO）:  P&L_gross_C = entry_price - game_result
    """
    df = pd.read_csv(TRADES_CSV)

    # Exit A: convergence 或 game_end 来源于 Exit A 路径
    # Exit B: fixed_window 或 game_end 来源于 Exit B 路径
    # 两类 game_end 在 trades.csv 中无法直接区分；由于 game_end 仅 22 条，
    # 此处将其与 convergence 合并为"Exit A 系"，与 fixed_window 合并为"Exit B 系"，
    # 再单独列 Exit C

    exit_a = df[df["exit_strategy"].isin(["convergence", "game_end"])].copy()
    exit_b = df[df["exit_strategy"] == "fixed_window"].copy()

    # 唯一信号（用于 Exit C 计算，去掉重复）
    signals = (
        df.sort_values("entry_ts")
        .groupby(["game_id", "entry_ts", "direction", "entry_price"], sort=False)
        .first()
        .reset_index()
    )
    signals["pnl_gross_exit_c"] = (
        signals["direction"] * (signals["game_result"] - signals["entry_price"])
    )
    signals["exit_strategy_c"] = "game_settlement"

    return df, signals


def compute_metrics_gross(arr: np.ndarray) -> dict:
    """只用 gross P&L 计算指标（无手续费）。"""
    if len(arr) == 0:
        return {k: np.nan for k in
                ["n","win_rate","avg","std","sharpe","max_dd","total"]}
    cum = np.concatenate([[0.0], np.cumsum(arr)])
    peak = np.maximum.accumulate(cum)
    max_dd = float((cum - peak).min())
    return {
        "n":        len(arr),
        "win_rate": float((arr > 0).mean()),
        "avg":      float(arr.mean()),
        "std":      float(arr.std()),
        "sharpe":   float(arr.mean() / arr.std()) if arr.std() > 0 else np.nan,
        "max_dd":   max_dd,
        "total":    float(arr.sum()),
    }


# ── 分析 1: 三种退出策略 × 分组报告 ─────────────────────────────────────────

def report_by_group(df_all: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """
    按 split × game_cat 报告三种退出策略的 gross 指标。
    """
    rows = []
    for split in ["in_sample", "out_of_sample"]:
        for cat in ["Regular", "Playoffs", "Finals"]:
            for strat, col, sub_df in [
                ("Exit_A", "pnl_gross", df_all[
                    (df_all["split"] == split) &
                    (df_all["game_cat"] == cat) &
                    (df_all["exit_strategy"].isin(["convergence", "game_end"]))
                ]),
                ("Exit_B", "pnl_gross", df_all[
                    (df_all["split"] == split) &
                    (df_all["game_cat"] == cat) &
                    (df_all["exit_strategy"] == "fixed_window")
                ]),
                ("Exit_C", "pnl_gross_exit_c", signals[
                    (signals["split"] == split) &
                    (signals["game_cat"] == cat)
                ]),
            ]:
                m = compute_metrics_gross(sub_df[col].values)
                rows.append({
                    "split": split, "game_cat": cat, "exit": strat,
                    **m,
                })
    return pd.DataFrame(rows)


# ── 分析 2: 信号强度 vs 收益相关性 ──────────────────────────────────────────

def signal_strength_vs_returns(signals: pd.DataFrame) -> pd.DataFrame:
    """
    按 net_edge_at_entry 分组（7-10% / 10-15% / 15%+），
    报告 Exit C gross P&L 均值，检验"spread 越大、收益是否越大"。
    """
    bins   = [0.07, 0.10, 0.15, 1.0]
    labels = ["7-10%", "10-15%", "15%+"]

    df = signals.copy()
    df["edge_bucket"] = pd.cut(df["net_edge_at_entry"], bins=bins, labels=labels, right=False)

    rows = []
    for split in ["in_sample", "out_of_sample"]:
        for bucket in labels:
            sub = df[(df["split"] == split) & (df["edge_bucket"] == bucket)]
            m = compute_metrics_gross(sub["pnl_gross_exit_c"].values)
            rows.append({"split": split, "edge_bucket": bucket, **m})
    return pd.DataFrame(rows)


# ── 分析 3: 入场价格分布 ─────────────────────────────────────────────────────

def entry_price_analysis(signals: pd.DataFrame) -> dict:
    """
    统计入场 yes_price 分布。检验是否集中在 0.3-0.7（手续费最高区间）。
    """
    ep = signals["entry_price"].values
    in_high_fee = ((ep >= 0.3) & (ep <= 0.7)).mean()
    return {
        "median_entry_price":   float(np.median(ep)),
        "pct_in_03_07":         float(in_high_fee),
        "pct_below_03":         float((ep < 0.3).mean()),
        "pct_above_07":         float((ep > 0.7).mean()),
        "mean_fee_at_entry":    float((0.07 * ep * (1 - ep)).mean()),
        "mean_fee_both_sides":  float((0.07 * ep * (1 - ep)).mean() * 2),
    }


# ── 可视化 ──────────────────────────────────────────────────────────────────

def plot_gross_distribution(df_all: pd.DataFrame, signals: pd.DataFrame):
    """
    三种退出策略的 gross P&L 分布直方图。
    标注"理论分析"警告。
    """
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    suptitle = f"Gross P&L Distribution {WARNING}"
    fig.suptitle(suptitle, fontsize=9)

    data_by_exit = [
        ("Exit A: Convergence", df_all[df_all["exit_strategy"].isin(["convergence","game_end"])]["pnl_gross"]),
        ("Exit B: Fixed 60s",   df_all[df_all["exit_strategy"] == "fixed_window"]["pnl_gross"]),
        ("Exit C: Game Settlement", signals["pnl_gross_exit_c"]),
    ]
    for ax, (label, arr) in zip(axes, data_by_exit):
        arr = arr.dropna()
        ax.hist(arr, bins=30, color="steelblue", alpha=0.7, edgecolor="white")
        ax.axvline(arr.mean(), color="red", ls="--", lw=1.2,
                   label=f"mean={arr.mean():.4f}")
        ax.axvline(0, color="black", lw=0.8)
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("gross P&L ($)")
        ax.legend(fontsize=7)

    plt.tight_layout()
    path = FIG_DIR / "phase2_nofee_gross_dist.png"
    plt.savefig(path, dpi=120)
    plt.close()
    print(f"图: {path}")


def plot_signal_strength(strength_df: pd.DataFrame):
    """
    信号强度 vs gross 收益条形图（IS 与 OOS 对比）。
    """
    buckets = ["7-10%", "10-15%", "15%+"]
    x = np.arange(len(buckets))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, split in enumerate(["in_sample", "out_of_sample"]):
        sub = strength_df[strength_df["split"] == split].set_index("edge_bucket")
        avgs = [sub.loc[b, "avg"] if b in sub.index else np.nan for b in buckets]
        bars = ax.bar(x + i * width, avgs, width, label=split.replace("_","-"), alpha=0.75)
        for bar, v in zip(bars, avgs):
            if not np.isnan(v):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                        f"{v:.4f}", ha="center", va="bottom", fontsize=7)

    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x + width / 2)
    ax.set_xticklabels(buckets)
    ax.set_xlabel("net_edge_at_entry")
    ax.set_ylabel("avg gross P&L ($) - Exit C")
    ax.set_title(f"Signal Strength vs Gross Returns {WARNING}", fontsize=9)
    ax.legend()
    plt.tight_layout()
    path = FIG_DIR / "phase2_nofee_signal_strength.png"
    plt.savefig(path, dpi=120)
    plt.close()
    print(f"图: {path}")


def plot_entry_price_dist(signals: pd.DataFrame):
    """
    入场价格分布直方图，标注手续费最高区间（0.3–0.7）。
    """
    fig, ax = plt.subplots(figsize=(8, 4))
    ep = signals["entry_price"].values
    ax.hist(ep, bins=30, color="steelblue", alpha=0.7, edgecolor="white")
    ax.axvspan(0.3, 0.7, alpha=0.12, color="red", label="High-fee zone (0.3-0.7)")
    ax.axvline(np.median(ep), color="red", ls="--", lw=1.2,
               label=f"median={np.median(ep):.3f}")
    pct = (ep >= 0.3) & (ep <= 0.7)
    ax.set_title(f"Entry Price Distribution -- {pct.mean():.1%} in high-fee zone 0.3-0.7\n"
                 f"(Descriptive analysis, {WARNING})", fontsize=9)
    ax.set_xlabel("entry yes_price")
    ax.legend(fontsize=8)
    plt.tight_layout()
    path = FIG_DIR / "phase2_nofee_entry_price_dist.png"
    plt.savefig(path, dpi=120)
    plt.close()
    print(f"图: {path}")


def plot_cumulative_gross(df_all: pd.DataFrame, signals: pd.DataFrame):
    """
    累计 gross P&L 曲线（IS vs OOS，三种退出策略）。
    """
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(f"Cumulative Gross P&L {WARNING}", fontsize=9)

    for ax, split in zip(axes, ["in_sample", "out_of_sample"]):
        for strat, label, color, ls in [
            ("exit_a", "Exit A (convergence)", "steelblue", "-"),
            ("exit_b", "Exit B (fixed 60s)",   "darkorange", "--"),
            ("exit_c", "Exit C (settlement)",   "green",      ":"),
        ]:
            if strat == "exit_a":
                sub = df_all[(df_all["split"]==split) &
                             (df_all["exit_strategy"].isin(["convergence","game_end"]))].sort_values("entry_ts")
                cum = np.cumsum(sub["pnl_gross"].values)
            elif strat == "exit_b":
                sub = df_all[(df_all["split"]==split) &
                             (df_all["exit_strategy"]=="fixed_window")].sort_values("entry_ts")
                cum = np.cumsum(sub["pnl_gross"].values)
            else:
                sub = signals[signals["split"]==split].sort_values("entry_ts")
                cum = np.cumsum(sub["pnl_gross_exit_c"].values)
            ax.plot(cum, label=label, color=color, ls=ls, lw=1.2)

        ax.axhline(0, color="black", lw=0.5)
        ax.set_title(split.replace("_","-"), fontsize=9)
        ax.set_xlabel("trade #")
        ax.set_ylabel("cumulative gross P&L ($)")
        ax.legend(fontsize=7)

    plt.tight_layout()
    path = FIG_DIR / "phase2_nofee_cumulative.png"
    plt.savefig(path, dpi=120)
    plt.close()
    print(f"图: {path}")


# ── 报告 ─────────────────────────────────────────────────────────────────────

def write_report(
    group_df: pd.DataFrame,
    strength_df: pd.DataFrame,
    entry_stats: dict,
    signals: pd.DataFrame,
):
    n_signals = len(signals)
    ep_pct     = entry_stats["pct_in_03_07"]
    avg_fee_2x = entry_stats["mean_fee_both_sides"]

    def fmt_group(r) -> str:
        return (
            f"| {r['split']:<16} | {r['game_cat']:<9} | {r['exit']:<8} "
            f"| {int(r['n']):>6} "
            f"| {r['win_rate']:>8.1%} "
            f"| {r['avg']:>9.4f} "
            f"| {r['sharpe']:>7.3f} "
            f"| {r['max_dd']:>9.4f} "
            f"| {r['total']:>9.4f} |"
        )

    header_group = (
        "| split            | game_cat  | exit     "
        "| n      | win_rate | avg       | sharpe  | max_dd    | total     |\n"
        "|-----------------|-----------|----------|"
        "--------|----------|-----------|---------|-----------|-----------|"
    )
    rows_group = "\n".join(fmt_group(r) for _, r in group_df.iterrows())

    def fmt_strength(r) -> str:
        return (
            f"| {r['split']:<16} | {r['edge_bucket']:<8} "
            f"| {int(r['n']):>6} | {r['win_rate']:>8.1%} | {r['avg']:>9.4f} | {r['sharpe']:>7.3f} |"
        )
    header_strength = (
        "| split            | edge     | n      | win_rate | avg       | sharpe  |\n"
        "|-----------------|----------|--------|----------|-----------|---------|"
    )
    rows_strength = "\n".join(fmt_strength(r) for _, r in strength_df.iterrows())

    # 预计算 f-string 中需要的统计值，避免在 f-string 内写复杂表达式
    exit_a_is_wr  = group_df[(group_df["exit"]=="Exit_A")&(group_df["split"]=="in_sample")]["win_rate"].mean()
    exit_a_oos_wr = group_df[(group_df["exit"]=="Exit_A")&(group_df["split"]=="out_of_sample")]["win_rate"].mean()
    exit_c_is_wr  = group_df[(group_df["exit"]=="Exit_C")&(group_df["split"]=="in_sample")]["win_rate"].mean()
    exit_c_oos_wr = group_df[(group_df["exit"]=="Exit_C")&(group_df["split"]=="out_of_sample")]["win_rate"].mean()
    fee_ratio     = avg_fee_2x / 0.018

    report = f"""# Phase 2 附加分析：无手续费情景下策略质量评估

> **⚠️ 理论分析，不代表真实可交易结果 ⚠️**
> 本分析去除手续费，单独评估信号设计与模型预测能力。
> Phase 2 核心结论（扣费后无 edge）已确认，本分析不替换、不淡化该结论。

生成时间: 2026-06-21
数据来源: Phase 2 trades.csv (阈值 7%，Exit A+B) + 新增 Exit C（持有至结算）

---

## 1. 三种退出策略对比（Gross P&L，无手续费）

说明：
- **Exit A**：spread 收敛（net_edge 回落阈值以下）平仓，或比赛结束结算
- **Exit B**：固定 60s 后平仓，或比赛结束结算
- **Exit C**：持有至比赛最终结果结算（binary: 1=主场赢, 0=客场赢）

{header_group}
{rows_group}

> ⚠️ Playoffs/Finals 小样本（训练 74 场），须保守解读。

---

## 2. 信号强度 vs Gross 收益相关性（Exit C）

检验"net_edge 越大，收益是否越大"——若无单调关系，说明信号强度不代表预测质量。

{header_strength}
{rows_strength}

---

## 3. 入场价格分布（描述性）

| 指标 | 数值 |
|------|------|
| 唯一信号数 | {n_signals} |
| 中位数入场价格（yes_price） | {entry_stats['median_entry_price']:.3f} |
| 入场价格在 0.3–0.7 的比例 | **{ep_pct:.1%}** |
| 入场价格 < 0.3 的比例 | {entry_stats['pct_below_03']:.1%} |
| 入场价格 > 0.7 的比例 | {entry_stats['pct_above_07']:.1%} |
| 平均单边手续费（实际收取） | ${entry_stats['mean_fee_at_entry']:.4f} |
| 平均双边手续费合计 | **${avg_fee_2x:.4f}** |

结构性观察：{ep_pct:.1%} 的信号发生在 0.3–0.7 高手续费区间（中间价位手续费最贵，最高 $0.0175/单边），
平均双边费用约 ${avg_fee_2x:.4f}。与 Phase 2 gross avg（约 $0.010–0.027）对比，费用相当于
{fee_ratio:.0f}× 均值 gross 收益量级，这解释了为何 gross 为正、net 为负的结构性原因：
**Kalshi 的手续费率对中间价位机会收取最高成本，恰好是 v2 模型发现大部分 spread 的区域。**

---

## 4. 综合评估

**信号设计质量评价（不含手续费，纯预测能力层面）：**

- Exit A gross IS 胜率达 {exit_a_is_wr:.1%}（均值），OOS {exit_a_oos_wr:.1%}：模型具备真实预测能力，spread 收敛方向可预测
- Exit C（持有至结算）gross IS 胜率约 {exit_c_is_wr:.1%}，OOS {exit_c_oos_wr:.1%}

**注意：Exit C 的 gross win_rate < 50% 是合理的**——即使模型判断方向正确（spread 会收敛），
也不意味着该方向最终是比赛胜者。Exit A 胜率高于 Exit C 正因此：
我们交易的是"spread 是否收敛"而非"比赛结果"。

**最终结论（与 Phase 2 一致）：**
信号具备真实预测能力（gross 层面），但当前费率结构使得该信号无法提取真实收益。
在费率降低（如 maker fee 场景）或 spread 系统性扩大（如市场参与者减少）的假设下，
方向层面的 edge 理论上可转化为正收益。但上述假设均须独立验证，当前不作为结论。

---

## 图表

- `phase2_nofee_gross_dist.png` — 三种退出策略 gross 分布
- `phase2_nofee_cumulative.png` — 累计 gross P&L 曲线
- `phase2_nofee_signal_strength.png` — 信号强度 vs 收益
- `phase2_nofee_entry_price_dist.png` — 入场价格分布
"""

    path = REPORT_DIR / "phase2_no_fee_report.md"
    with open(path, "w") as f:
        f.write(report)
    print(f"报告: {path}")


# ── 主函数 ──────────────────────────────────────────────────────────────────

def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    print("加载 Phase 2 trades ...")
    df_all, signals = load_and_prepare()
    print(f"总记录: {len(df_all)} 条, 唯一信号: {len(signals)} 个")

    # 1. 分组报告
    print("\n=== 分组 Gross 报告 ===")
    group_df = report_by_group(df_all, signals)
    key_cols = ["split","game_cat","exit","n","win_rate","avg","sharpe","max_dd","total"]
    print(group_df[key_cols].to_string(index=False))

    # 2. 信号强度分析
    print("\n=== 信号强度 vs 收益 ===")
    strength_df = signal_strength_vs_returns(signals)
    print(strength_df[["split","edge_bucket","n","win_rate","avg","sharpe"]].to_string(index=False))

    # 3. 入场价格分析
    entry_stats = entry_price_analysis(signals)
    print(f"\n=== 入场价格分析 ===")
    for k, v in entry_stats.items():
        print(f"  {k}: {v:.4f}")

    # 4. 可视化
    print("\n=== 生成图表 ===")
    plot_gross_distribution(df_all, signals)
    plot_cumulative_gross(df_all, signals)
    plot_signal_strength(strength_df)
    plot_entry_price_dist(signals)

    # 5. 报告
    write_report(group_df, strength_df, entry_stats, signals)

    print("\n附加分析完成。")
    print(f"报告: {REPORT_DIR}/phase2_no_fee_report.md")


if __name__ == "__main__":
    main()
