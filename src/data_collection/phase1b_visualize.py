"""
Phase -1b: 生成流动性检测可视化图表。
"""

import json
import os
import requests
import time
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

BASE = "https://api.elections.kalshi.com/trade-api/v2"

GAMES = [
    {
        "label": "2025-Finals-G7\nOKC vs IND",
        "event_ticker": "KXNBAGAME-25JUN19OKCIND",
        "tickers": ["KXNBAGAME-25JUN19OKCIND-OKC", "KXNBAGAME-25JUN19OKCIND-IND"],
    },
    {
        "label": "2025-Finals-G5\nOKC vs IND",
        "event_ticker": "KXNBAGAME-25JUN13OKCIND",
        "tickers": ["KXNBAGAME-25JUN13OKCIND-OKC", "KXNBAGAME-25JUN13OKCIND-IND"],
    },
    {
        "label": "2025-Christmas\nMIN vs DEN",
        "event_ticker": "KXNBAGAME-25DEC25MINDEN",
        "tickers": ["KXNBAGAME-25DEC25MINDEN-MIN", "KXNBAGAME-25DEC25MINDEN-DEN"],
    },
    {
        "label": "2026-Regular\nDEN vs OKC",
        "event_ticker": "KXNBAGAME-26FEB27DENOKC",
        "tickers": ["KXNBAGAME-26FEB27DENOKC-OKC", "KXNBAGAME-26FEB27DENOKC-DEN"],
    },
    {
        "label": "2026-Playoffs\nGSW vs LAC",
        "event_ticker": "KXNBAGAME-26APR15GSWLAC",
        "tickers": ["KXNBAGAME-26APR15GSWLAC-GSW", "KXNBAGAME-26APR15GSWLAC-LAC"],
    },
]


def fetch_all_trades(ticker: str) -> list[dict]:
    all_trades = []
    cursor = None
    while True:
        params = {"ticker": ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(BASE + "/historical/trades", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        trades = data.get("trades", [])
        all_trades.extend(trades)
        cursor = data.get("cursor")
        if not cursor or not trades:
            break
    return all_trades


def parse_ts(s: str) -> float:
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def percentile(data, p):
    if not data:
        return float("nan")
    data_sorted = sorted(data)
    idx = (len(data_sorted) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(data_sorted) - 1)
    return data_sorted[lo] + (data_sorted[hi] - data_sorted[lo]) * (idx - lo)


def main():
    os.makedirs("outputs/figures", exist_ok=True)

    # 拉取所有游戏数据
    all_game_data = []
    for game in GAMES:
        print(f"拉取 {game['label'].replace(chr(10), ' ')} ...")
        all_trades = []
        for ticker in game["tickers"]:
            trades = fetch_all_trades(ticker)
            all_trades.extend(trades)
        all_trades.sort(key=lambda t: t["created_time"])
        timestamps = [parse_ts(t["created_time"]) for t in all_trades]
        prices = [float(t["yes_price_dollars"]) for t in all_trades]
        all_game_data.append({
            "label": game["label"],
            "timestamps": timestamps,
            "prices": prices,
            "trades": all_trades,
        })
        time.sleep(0.5)

    # === 图1: 各游戏成交间隔 CDF（全场 + 最后20分钟） ===
    fig, axes = plt.subplots(2, 5, figsize=(20, 8))
    fig.suptitle("Kalshi NBA 历史成交间隔分布 (Phase -1b 流动性检测)", fontsize=14, fontweight="bold")

    for col, gdata in enumerate(all_game_data):
        ts = gdata["timestamps"]
        prices = gdata["prices"]
        game_end = ts[-1]

        # 全场间隔
        ivs_all = [ts[i+1] - ts[i] for i in range(len(ts)-1)]
        # 最后20分钟
        cutoff = game_end - 20 * 60
        ts_last20 = [t for t in ts if t >= cutoff]
        ivs_last20 = [ts_last20[i+1] - ts_last20[i] for i in range(len(ts_last20)-1)]

        for row, (ivs, title) in enumerate([
            (ivs_all, "全场"),
            (ivs_last20, "最后20分钟"),
        ]):
            ax = axes[row][col]
            if not ivs:
                ax.text(0.5, 0.5, "无数据", ha="center", va="center")
                continue
            # CDF，截断到60秒
            clipped = [min(v, 60) for v in ivs]
            x = sorted(clipped)
            y = np.arange(1, len(x)+1) / len(x)
            ax.plot(x, y, linewidth=1.5)
            ax.axvline(x=30, color="red", linestyle="--", alpha=0.6, label="30s")
            ax.set_xlim(0, 60)
            ax.set_ylim(0, 1)
            median = percentile(ivs, 50)
            p90 = percentile(ivs, 90)
            ax.set_title(f"{gdata['label']}\n{title}\n中位={median:.1f}s  p90={p90:.1f}s",
                         fontsize=8)
            ax.set_xlabel("间隔 (秒)", fontsize=7)
            if col == 0:
                ax.set_ylabel("CDF", fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("outputs/figures/phase1b_interval_cdf.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("保存: outputs/figures/phase1b_interval_cdf.png")

    # === 图2: 每场比赛价格走势 + 成交频率（2小时窗口，即比赛期间） ===
    fig, axes = plt.subplots(5, 2, figsize=(14, 20))
    fig.suptitle("Kalshi NBA 比赛期间价格走势与成交频率", fontsize=13, fontweight="bold")

    for row, gdata in enumerate(all_game_data):
        ts = np.array(gdata["timestamps"])
        prices_arr = np.array(gdata["prices"])
        game_end = ts[-1]
        # 取比赛最后3小时（游戏实际进行窗口）
        window_start = game_end - 3 * 3600
        mask = ts >= window_start
        ts_w = ts[mask]
        pr_w = prices_arr[mask]

        # 相对分钟
        rel_min = (ts_w - window_start) / 60

        # 价格走势
        ax_price = axes[row][0]
        ax_price.scatter(rel_min, pr_w, s=0.5, alpha=0.3, color="steelblue")
        ax_price.axhline(0.35, color="gray", linestyle=":", alpha=0.5)
        ax_price.axhline(0.65, color="gray", linestyle=":", alpha=0.5)
        ax_price.set_ylabel("YES price ($)", fontsize=8)
        ax_price.set_title(f"{gdata['label'].replace(chr(10), ' ')} - 价格走势(最后3h)", fontsize=9)
        ax_price.set_ylim(-0.02, 1.02)
        ax_price.tick_params(labelsize=7)
        ax_price.grid(True, alpha=0.3)

        # 每分钟成交笔数
        ax_vol = axes[row][1]
        bins = np.arange(0, 181, 1)  # 0-180分钟，每1分钟一个桶
        counts, _ = np.histogram(rel_min, bins=bins)
        ax_vol.bar(bins[:-1], counts, width=1, color="coral", alpha=0.7)
        ax_vol.set_ylabel("成交笔数/分钟", fontsize=8)
        ax_vol.set_title(f"{gdata['label'].replace(chr(10), ' ')} - 成交频率(最后3h)", fontsize=9)
        ax_vol.tick_params(labelsize=7)
        ax_vol.grid(True, alpha=0.3, axis="y")
        ax_vol.set_xlabel("距比赛结束前 (分钟)", fontsize=7)

    # x轴翻转（让右边是比赛结束）
    for row in range(5):
        for col in range(2):
            axes[row][col].invert_xaxis()
            axes[row][col].set_xlabel("距比赛结束前 (分钟)", fontsize=7)

    plt.tight_layout()
    plt.savefig("outputs/figures/phase1b_price_and_volume.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("保存: outputs/figures/phase1b_price_and_volume.png")

    print("\n图表生成完毕。")


if __name__ == "__main__":
    main()
