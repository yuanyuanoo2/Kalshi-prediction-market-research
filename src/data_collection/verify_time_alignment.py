"""
CLAUDE.md VERIFICATION: 抽查3场比赛，肉眼检查 game clock vs wall clock 对齐。
- 场次1: 2025 Finals G7 (OKC-IND) — 总决赛
- 场次2: 2025-12-25 MIN-DEN       — 圣诞节常规赛
- 场次3: 2026-02-27 DEN-OKC       — 常规赛
每场图：上方 Kalshi yes_price，下方 PBP score_diff；x轴对齐到 UTC wall clock。
"""

import json, csv
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import os

PBP_CSV    = "data/processed/nba_pbp_parsed.csv"
TRADES_RAW = "data/raw/phase1b_all_trades.json"
FIG_DIR    = "outputs/figures"

CHECK_GAMES = [
    {
        "label":        "2025-Finals-G7 (OKC vs IND)",
        "game_id":      "0042400406",
        "kalshi_tickers": ["KXNBAGAME-25JUN19OKCIND-OKC", "KXNBAGAME-25JUN19OKCIND-IND"],
        "home_team":    "OKC",   # home team in NBA stats
    },
    {
        "label":        "2025-Christmas MIN vs DEN",
        "game_id":      "0022500013",
        "kalshi_tickers": ["KXNBAGAME-25DEC25MINDEN-MIN", "KXNBAGAME-25DEC25MINDEN-DEN"],
        "home_team":    "MIN",
    },
    {
        "label":        "2026-Feb27 DEN vs OKC",
        "game_id":      "0022500862",
        "kalshi_tickers": ["KXNBAGAME-26FEB27DENOKC-OKC", "KXNBAGAME-26FEB27DENOKC-DEN"],
        "home_team":    "DEN",
    },
]


def load_pbp(game_id: str) -> pd.DataFrame:
    df = pd.read_csv(PBP_CSV, dtype=str)
    df = df[df["game_id"] == game_id].copy()
    df["wall_utc"]      = pd.to_numeric(df["wall_utc"],      errors="coerce")
    df["time_remaining"] = pd.to_numeric(df["time_remaining"], errors="coerce")
    df["score_diff"]    = pd.to_numeric(df["score_diff"],    errors="coerce")
    df = df.dropna(subset=["wall_utc"]).sort_values("wall_utc")
    df["wall_dt"] = pd.to_datetime(df["wall_utc"], unit="s", utc=True)
    return df


def load_trades(tickers: list[str], trades_raw: dict) -> pd.DataFrame:
    rows = []
    for label, gdata in trades_raw.items():
        for t in gdata["trades"]:
            if t["ticker"] in tickers:
                rows.append({
                    "created_time": t["created_time"],
                    "yes_price":    float(t["yes_price_dollars"]),
                    "ticker":       t["ticker"],
                })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["wall_dt"] = pd.to_datetime(df["created_time"], utc=True)
    return df.sort_values("wall_dt")


def print_alignment_stats(pbp: pd.DataFrame, trades: pd.DataFrame, label: str):
    """打印关键时间锚点，供人工肉眼核查。"""
    print(f"\n{'─'*55}")
    print(f"  {label}")
    print(f"{'─'*55}")

    # PBP: 各节起止时间
    for period in [1, 2, 3, 4]:
        p_data = pbp[pbp["period"].astype(str) == str(period)]
        if p_data.empty:
            continue
        t_start = p_data["wall_dt"].min()
        t_end   = p_data["wall_dt"].max()
        tr_start = p_data.loc[p_data["wall_dt"].idxmin(), "time_remaining"]
        tr_end   = p_data.loc[p_data["wall_dt"].idxmax(), "time_remaining"]
        print(f"  Q{period}: {t_start.strftime('%H:%M:%S UTC')} (TR={tr_start:.0f}s)"
              f" → {t_end.strftime('%H:%M:%S UTC')} (TR={tr_end:.0f}s)")

    if not trades.empty:
        t_first = trades["wall_dt"].min()
        t_last  = trades["wall_dt"].max()
        print(f"  Kalshi trades: {t_first.strftime('%H:%M:%S UTC')} → {t_last.strftime('%H:%M:%S UTC')}")

        # 对比：Kalshi 交易最活跃的15分钟窗口 vs PBP Q4 时间
        q4 = pbp[pbp["period"].astype(str) == "4"]
        if not q4.empty:
            q4_start = q4["wall_dt"].min()
            q4_end   = q4["wall_dt"].max()
            trades_in_q4 = trades[
                (trades["wall_dt"] >= q4_start) & (trades["wall_dt"] <= q4_end)
            ]
            print(f"  Q4 PBP 窗口内 Kalshi 成交笔数: {len(trades_in_q4)}"
                  f"  (Q4={q4_start.strftime('%H:%M')}-{q4_end.strftime('%H:%M')} UTC)")


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    print("加载数据 ...")
    with open(TRADES_RAW) as f:
        trades_raw = json.load(f)

    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle("时间对齐核查：PBP score_diff vs Kalshi yes_price（UTC wall clock）",
                 fontsize=13, fontweight="bold")

    for row_i, game in enumerate(CHECK_GAMES):
        pbp    = load_pbp(game["game_id"])
        trades = load_trades(game["kalshi_tickers"], trades_raw)

        if pbp.empty:
            print(f"  WARNING: {game['game_id']} PBP 数据为空")
            continue

        print_alignment_stats(pbp, trades, game["label"])

        # 取比赛当天 ±1小时窗口
        if not trades.empty:
            # 以 Kalshi 最后成交时间为基准，取前3小时
            t_end   = trades["wall_dt"].max()
            t_start = t_end - pd.Timedelta(hours=3)
        else:
            t_end   = pbp["wall_dt"].max() + pd.Timedelta(minutes=10)
            t_start = t_end - pd.Timedelta(hours=3)

        pbp_w    = pbp[(pbp["wall_dt"] >= t_start) & (pbp["wall_dt"] <= t_end)]
        trades_w = trades[(trades["wall_dt"] >= t_start) & (trades["wall_dt"] <= t_end)] \
                   if not trades.empty else pd.DataFrame()

        # ── 上图：Kalshi yes_price ──
        ax_top = axes[row_i][0]
        if not trades_w.empty:
            # 只取 OKC/home 方的 yes_price
            home_ticker = [t for t in game["kalshi_tickers"]
                           if game["home_team"] in t]
            if home_ticker:
                tr_h = trades_w[trades_w["ticker"] == home_ticker[0]]
            else:
                tr_h = trades_w
            ax_top.scatter(tr_h["wall_dt"], tr_h["yes_price"],
                           s=1, alpha=0.4, color="steelblue")
        ax_top.set_ylabel("yes_price ($)", fontsize=9)
        ax_top.set_title(f"{game['label']}\nKalshi yes_price ({game['home_team']} wins)",
                         fontsize=9)
        ax_top.set_ylim(-0.05, 1.05)
        ax_top.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax_top.tick_params(labelsize=8)
        ax_top.grid(True, alpha=0.3)

        # ── 下图：PBP score_diff + 节边界 ──
        ax_bot = axes[row_i][1]
        if not pbp_w.empty:
            ax_bot.step(pbp_w["wall_dt"], pbp_w["score_diff"],
                        where="post", linewidth=1.2, color="coral")
            # 标记各节边界
            for period in [1, 2, 3, 4]:
                p = pbp_w[pbp_w["period"].astype(str) == str(period)]
                if not p.empty:
                    ax_bot.axvline(p["wall_dt"].min(), color="gray",
                                   linestyle="--", alpha=0.5, linewidth=0.8)
                    ax_bot.text(p["wall_dt"].min(), ax_bot.get_ylim()[1] if ax_bot.get_ylim()[1] != 0 else 10,
                                f"Q{period}", fontsize=7, color="gray", va="top")
        ax_bot.axhline(0, color="black", linewidth=0.5, linestyle=":")
        ax_bot.set_ylabel("score_diff (home−away)", fontsize=9)
        ax_bot.set_title(f"{game['label']}\nNBA PBP score_diff", fontsize=9)
        ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax_bot.tick_params(labelsize=8)
        ax_bot.grid(True, alpha=0.3)

        # 统一 x 轴范围
        for ax in [ax_top, ax_bot]:
            ax.set_xlim(t_start, t_end)
            ax.set_xlabel("UTC wall clock", fontsize=8)

    plt.tight_layout()
    out_path = os.path.join(FIG_DIR, "time_alignment_check.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n图表保存: {out_path}")
    print("\n核查要点（肉眼检查）:")
    print("  1. 左图 yes_price 从 ~0.5 开始，比赛结果确定后收敛至 0 或 1")
    print("  2. 右图 score_diff 阶梯变化，Q 边界垂直线应在左图价格波动段内")
    print("  3. 左右图 x 轴同步，price 变动与 score_diff 变动应时序吻合")


if __name__ == "__main__":
    main()
