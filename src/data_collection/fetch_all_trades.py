"""
拉取5场比赛全量 historical/trades，保存完整原始记录。
每次请求记录状态码，遇到429自动重试，不静默跳过。
"""

import requests
import json
import time
import os
from datetime import datetime

BASE = "https://api.elections.kalshi.com/trade-api/v2"

GAMES = [
    {
        "label": "2025-Finals-G7-OKC-IND",
        "tickers": ["KXNBAGAME-25JUN19OKCIND-OKC", "KXNBAGAME-25JUN19OKCIND-IND"],
    },
    {
        "label": "2025-Finals-G5-OKC-IND",
        "tickers": ["KXNBAGAME-25JUN13OKCIND-OKC", "KXNBAGAME-25JUN13OKCIND-IND"],
    },
    {
        "label": "2025-Christmas-MIN-DEN",
        "tickers": ["KXNBAGAME-25DEC25MINDEN-MIN", "KXNBAGAME-25DEC25MINDEN-DEN"],
    },
    {
        "label": "2026-Regular-DEN-OKC",
        "tickers": ["KXNBAGAME-26FEB27DENOKC-OKC", "KXNBAGAME-26FEB27DENOKC-DEN"],
    },
    {
        "label": "2026-Playoffs-GSW-LAC",
        "tickers": ["KXNBAGAME-26APR15GSWLAC-GSW", "KXNBAGAME-26APR15GSWLAC-LAC"],
    },
]


def fetch_ticker_trades(ticker: str) -> tuple[list[dict], list[dict]]:
    """
    拉取单个 market 的全部 trades，完整分页。
    返回 (trades列表, 请求审计日志)。
    429 时等待2秒后重试，不跳过。
    """
    all_trades = []
    request_log = []
    cursor = None
    page = 0

    while True:
        params = {"ticker": ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor

        while True:  # 429重试循环
            try:
                resp = requests.get(BASE + "/historical/trades", params=params, timeout=20)
            except requests.exceptions.RequestException as e:
                print(f"    网络错误，重试: {e}")
                time.sleep(2)
                continue

            request_log.append({
                "page": page,
                "ticker": ticker,
                "status_code": resp.status_code,
                "cursor_used": cursor,
                "ts": datetime.utcnow().isoformat(),
            })

            if resp.status_code == 429:
                print(f"    429 限速，等待2s后重试 (page={page})")
                time.sleep(2)
                continue

            resp.raise_for_status()
            break  # 成功，退出重试循环

        data = resp.json()
        trades = data.get("trades", [])
        all_trades.extend(trades)
        cursor = data.get("cursor")
        page += 1

        if page % 10 == 0:
            print(f"    page {page}, 累计 {len(all_trades)} 笔...")

        if not cursor or not trades:
            break

        time.sleep(0.05)  # 主动限速

    return all_trades, request_log


def main():
    os.makedirs("data/raw", exist_ok=True)
    output_path = "data/raw/phase1b_all_trades.json"

    result = {}

    for game in GAMES:
        label = game["label"]
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")

        game_trades = []
        game_logs = []

        for ticker in game["tickers"]:
            print(f"  拉取 {ticker} ...")
            trades, log = fetch_ticker_trades(ticker)
            print(f"    完成: {len(trades)} 笔, {len(log)} 次请求")
            game_trades.extend(trades)
            game_logs.extend(log)

        # 按时间排序
        game_trades.sort(key=lambda t: t["created_time"])

        result[label] = {
            "trades": game_trades,
            "request_log": game_logs,
            "total_trades": len(game_trades),
            "fetched_at": datetime.utcnow().isoformat(),
        }

        print(f"  [{label}] 合并后: {len(game_trades)} 笔")
        time.sleep(1)

    print(f"\n保存到 {output_path} ...")
    with open(output_path, "w") as f:
        json.dump(result, f)  # 不indent，节省空间

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    total = sum(v["total_trades"] for v in result.values())
    print(f"完成。总笔数: {total:,}，文件大小: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
