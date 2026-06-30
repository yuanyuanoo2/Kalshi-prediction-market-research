"""
Phase -1b: 流动性可行性检测
对 5 场历史 NBA 比赛拉取全量 /historical/trades，统计成交间隔分布。
只调用 public GET 端点，无需认证。
"""

import requests
import json
import time
from datetime import datetime, timezone
import statistics

BASE = "https://api.elections.kalshi.com/trade-api/v2"

# 5 场选手：2025 总决赛 × 2 + 圣诞常规赛 + 常规赛高流量 + 2026 季后赛
GAMES = [
    {
        "label": "2025-Finals-G7-OKC-IND",
        "event_ticker": "KXNBAGAME-25JUN19OKCIND",
        "tickers": ["KXNBAGAME-25JUN19OKCIND-OKC", "KXNBAGAME-25JUN19OKCIND-IND"],
    },
    {
        "label": "2025-Finals-G5-OKC-IND",
        "event_ticker": "KXNBAGAME-25JUN13OKCIND",
        "tickers": ["KXNBAGAME-25JUN13OKCIND-OKC", "KXNBAGAME-25JUN13OKCIND-IND"],
    },
    {
        "label": "2025-Christmas-MIN-DEN",
        "event_ticker": "KXNBAGAME-25DEC25MINDEN",
        "tickers": ["KXNBAGAME-25DEC25MINDEN-MIN", "KXNBAGAME-25DEC25MINDEN-DEN"],
    },
    {
        "label": "2026-Regular-DEN-OKC",
        "event_ticker": "KXNBAGAME-26FEB27DENOKC",
        "tickers": ["KXNBAGAME-26FEB27DENOKC-OKC", "KXNBAGAME-26FEB27DENOKC-DEN"],
    },
    {
        "label": "2026-Playoffs-GSW-LAC",
        "event_ticker": "KXNBAGAME-26APR15GSWLAC",
        "tickers": ["KXNBAGAME-26APR15GSWLAC-GSW", "KXNBAGAME-26APR15GSWLAC-LAC"],
    },
]


def fetch_all_trades(ticker: str) -> list[dict]:
    """拉取单个 market 的全部历史 trades（游标翻页）。"""
    all_trades = []
    cursor = None
    page = 0
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
        page += 1
        if not cursor or not trades:
            break
    return all_trades


def parse_ts(s: str) -> float:
    """ISO8601 字符串 → Unix 秒（float）。"""
    # Python 3.11+ 支持 fromisoformat with Z，低版本需替换
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def compute_intervals(timestamps: list[float]) -> list[float]:
    """给定有序时间戳列表，返回相邻间隔（秒）。"""
    if len(timestamps) < 2:
        return []
    return [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]


def percentile(data: list[float], p: float) -> float:
    if not data:
        return float("nan")
    data_sorted = sorted(data)
    idx = (len(data_sorted) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(data_sorted) - 1)
    return data_sorted[lo] + (data_sorted[hi] - data_sorted[lo]) * (idx - lo)


def analyze_game(game: dict) -> dict:
    label = game["label"]
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    # 拉取两个市场（YEA/NO 两侧）的 trades 并合并
    all_trades = []
    for ticker in game["tickers"]:
        trades = fetch_all_trades(ticker)
        print(f"  {ticker}: {len(trades)} trades")
        all_trades.extend(trades)

    if not all_trades:
        print("  !! 无 trades 数据")
        return {}

    # 按时间排序（API 返回倒序，此处正序）
    all_trades.sort(key=lambda t: t["created_time"])

    # 时间戳列表
    timestamps = [parse_ts(t["created_time"]) for t in all_trades]
    prices = [float(t["yes_price_dollars"]) for t in all_trades]

    game_start = timestamps[0]
    game_end = timestamps[-1]
    duration_min = (game_end - game_start) / 60

    print(f"  时间范围: {all_trades[0]['created_time']} → {all_trades[-1]['created_time']}")
    print(f"  总时长: {duration_min:.1f} 分钟（wall clock）")
    print(f"  总成交笔数: {len(all_trades)}")

    # 全场间隔
    intervals_all = compute_intervals(timestamps)

    # 关键时段 1: 最后 20 分钟 wall clock（代理 NBA 最后约 5 分钟比赛时间）
    cutoff_last20 = game_end - 20 * 60
    ts_last20 = [ts for ts in timestamps if ts >= cutoff_last20]
    intervals_last20 = compute_intervals(ts_last20)

    # 关键时段 2: 胶着时段（yes_price 在 0.35–0.65 之间，代理比分差小）
    ts_close = [
        ts for ts, p in zip(timestamps, prices) if 0.35 <= p <= 0.65
    ]
    intervals_close = compute_intervals(ts_close)

    def stats(ivs: list[float], label: str) -> dict:
        if not ivs:
            return {"label": label, "n": 0}
        return {
            "label": label,
            "n": len(ivs) + 1,
            "median_s": round(percentile(ivs, 50), 1),
            "p90_s": round(percentile(ivs, 90), 1),
            "p99_s": round(percentile(ivs, 99), 1),
            "mean_s": round(statistics.mean(ivs), 1),
        }

    result = {
        "game": label,
        "total_trades": len(all_trades),
        "duration_min": round(duration_min, 1),
        "start": all_trades[0]["created_time"],
        "end": all_trades[-1]["created_time"],
        "all": stats(intervals_all, "全场"),
        "last20min": stats(intervals_last20, "最后20分钟"),
        "close_game": stats(intervals_close, "胶着时段(35-65¢)"),
    }

    for key in ["all", "last20min", "close_game"]:
        s = result[key]
        if s.get("n", 0) > 1:
            print(f"  [{s['label']}] n={s['n']}笔  中位间隔={s['median_s']}s  p90={s['p90_s']}s  p99={s['p99_s']}s")
        else:
            print(f"  [{key}] 数据不足")

    return result


def main():
    results = []
    for game in GAMES:
        result = analyze_game(game)
        if result:
            results.append(result)
        time.sleep(1)  # 避免触发限速

    # 保存原始结果
    import os
    os.makedirs("data/raw", exist_ok=True)
    with open("data/raw/phase1b_liquidity_raw.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n\n" + "=" * 60)
    print("汇总结论")
    print("=" * 60)
    for r in results:
        last20 = r.get("last20min", {})
        close = r.get("close_game", {})
        median_last20 = last20.get("median_s", float("nan"))
        median_close = close.get("median_s", float("nan"))
        print(f"\n{r['game']}")
        print(f"  全场成交: {r['total_trades']} 笔 / {r['duration_min']} 分钟")
        print(f"  关键时段(最后20分钟) 中位间隔: {median_last20}s")
        print(f"  关键时段(胶着35-65¢) 中位间隔: {median_close}s")

    print("\n原始数据已保存: data/raw/phase1b_liquidity_raw.json")


if __name__ == "__main__":
    main()
