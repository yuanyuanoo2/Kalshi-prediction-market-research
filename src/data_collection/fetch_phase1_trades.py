"""
Phase 1: 拉取 31 场比赛的 Kalshi home-team market historical/trades。
只拉主场方 ticker（team2），用于与模型的 P(home wins) 对齐。
每场保存到 data/raw/phase1_trades/{nba_game_id}.json。
"""

import csv
import json
import os
import time
from datetime import datetime

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SELECTION_CSV = "data/processed/phase1_game_selection.csv"
OUT_DIR = "data/raw/phase1_trades"


def fetch_ticker_trades(ticker: str) -> tuple[list[dict], list[dict]]:
    """
    完整分页拉取单个 market 的全部 trades。
    返回 (trades列表, 请求审计日志)。
    429 自动重试，不跳过。
    """
    all_trades: list[dict] = []
    request_log: list[dict] = []
    cursor = None
    page = 0

    while True:
        params: dict = {"ticker": ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor

        while True:  # 429 重试循环
            try:
                resp = requests.get(
                    BASE + "/historical/trades", params=params, timeout=20
                )
            except requests.exceptions.RequestException as e:
                print(f"    网络错误，重试: {e}")
                time.sleep(2)
                continue

            request_log.append(
                {
                    "page": page,
                    "ticker": ticker,
                    "status_code": resp.status_code,
                    "cursor_used": cursor,
                    "ts": datetime.utcnow().isoformat(),
                }
            )

            if resp.status_code == 429:
                print(f"    429 限速，等待 2s 后重试 (page={page})")
                time.sleep(2)
                continue

            resp.raise_for_status()
            break

        data = resp.json()
        trades = data.get("trades", [])
        all_trades.extend(trades)
        cursor = data.get("cursor")
        page += 1

        if page % 5 == 0:
            print(f"    page {page}, 累计 {len(all_trades)} 笔 ...")

        if not cursor or not trades:
            break

        time.sleep(0.1)

    return all_trades, request_log


def load_selection() -> list[dict]:
    games = []
    with open(SELECTION_CSV, newline="") as f:
        for row in csv.DictReader(f):
            games.append(row)
    return games


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    games = load_selection()

    print(f"共 {len(games)} 场待拉取，保存至 {OUT_DIR}/")

    for i, g in enumerate(games, 1):
        gid = g["nba_game_id"]
        out_path = os.path.join(OUT_DIR, f"{gid}.json")

        # 已拉取则跳过（断点续传）
        if os.path.exists(out_path):
            print(f"[{i:02d}/{len(games)}] {gid} 已存在，跳过")
            continue

        ticker = g["home_ticker"]
        print(f"\n[{i:02d}/{len(games)}] {gid} | {g['game_cat']:8s} | {ticker}")

        trades, log = fetch_ticker_trades(ticker)

        payload = {
            "nba_game_id": gid,
            "game_cat": g["game_cat"],
            "kalshi_event_ticker": g["kalshi_event_ticker"],
            "home_team": g["team2"],
            "away_team": g["team1"],
            "home_ticker": ticker,
            "date": g["date"],
            "trades": trades,
            "request_log": log,
            "fetched_at": datetime.utcnow().isoformat(),
            "n_trades": len(trades),
        }

        with open(out_path, "w") as f:
            json.dump(payload, f)

        print(f"    完成: {len(trades)} 笔 → {out_path}")
        time.sleep(0.5)

    # 汇总
    total = 0
    by_cat: dict[str, int] = {}
    for g in games:
        p = os.path.join(OUT_DIR, f"{g['nba_game_id']}.json")
        if os.path.exists(p):
            with open(p) as f:
                d = json.load(f)
            n = d.get("n_trades", 0)
            total += n
            cat = g["game_cat"]
            by_cat[cat] = by_cat.get(cat, 0) + n

    print(f"\n=== 拉取完成 ===")
    print(f"总成交笔数: {total:,}")
    for cat, n in by_cat.items():
        print(f"  {cat}: {n:,} 笔")


if __name__ == "__main__":
    main()
