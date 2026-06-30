"""
批量拉取每场比赛 tip-off 前最后一笔 Kalshi 成交价（pregame_market_prob）。

策略:
  - 使用 /historical/trades?max_ts={game_start}&limit=1 只拉 tip-off 前最新的一笔
  - 只拉主场队市场（team2），P(away wins) = 1 - P(home wins) 对称计算
  - game_start 来源: PBP wall_utc 最小值（NBA 实际开赛时刻）
  - 无 Kalshi 覆盖的场次（2021-24 历史 Playoffs）标记为 NaN

输出: data/processed/pregame_market_probs.csv
  列: game_id, kalshi_event_ticker, home_team, home_ticker, game_start_utc,
      pregame_market_prob (home 视角 P(home wins))
"""

import csv
import os
import time
from datetime import datetime

import pandas as pd
import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
PBP_MAIN   = "data/processed/nba_pbp_parsed.csv"
PBP_EXTRA  = "data/processed/nba_pbp_extra_playoffs.csv"
MAPPING    = "data/raw/nba_game_mapping.csv"
OUT_CSV    = "data/processed/pregame_market_probs.csv"


def fetch_last_pregame_trade(ticker: str, game_start_ts: float) -> float | None:
    """
    拉取 tip-off 前最后一笔成交价。
    使用 max_ts 参数限制只返回赛前数据，limit=1 只要最近一笔。
    429 自动重试。
    """
    params = {"ticker": ticker, "limit": 1, "max_ts": int(game_start_ts)}
    for attempt in range(5):
        try:
            r = requests.get(BASE + "/historical/trades", params=params, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"    网络错误: {e}")
            time.sleep(2)
            continue

        if r.status_code == 429:
            time.sleep(2)
            continue

        if r.status_code != 200:
            return None  # 市场不存在或其他错误

        trades = r.json().get("trades", [])
        if not trades:
            return None
        return float(trades[0]["yes_price_dollars"])

    return None


def load_game_starts() -> dict[str, float]:
    """从 PBP 数据中提取每场比赛的 game_start（PBP wall_utc 最小值）。"""
    dfs = []
    for path in [PBP_MAIN, PBP_EXTRA]:
        if os.path.exists(path):
            df = pd.read_csv(path, dtype={"game_id": str},
                             usecols=["game_id", "wall_utc"])
            df["wall_utc"] = pd.to_numeric(df["wall_utc"], errors="coerce")
            dfs.append(df)
    combined = pd.concat(dfs, ignore_index=True).dropna(subset=["wall_utc"])
    return combined.groupby("game_id")["wall_utc"].min().to_dict()


def main():
    os.makedirs("data/processed", exist_ok=True)

    print("加载 PBP game_start 时间 ...")
    game_starts = load_game_starts()
    print(f"  共 {len(game_starts)} 场有 PBP 数据")

    mapping = pd.read_csv(MAPPING, dtype={"nba_game_id": str})
    mapping = mapping.dropna(subset=["nba_game_id"])
    mapping["home_ticker"] = mapping["kalshi_event_ticker"] + "-" + mapping["team2"]

    # 只处理有 PBP 数据的场次
    games = mapping[mapping["nba_game_id"].isin(game_starts)].copy()
    games["game_start_ts"] = games["nba_game_id"].map(game_starts)
    print(f"  有 Kalshi 映射的场次: {len(games)}")

    results = []
    n = len(games)

    for i, (_, row) in enumerate(games.iterrows(), 1):
        gid     = row["nba_game_id"]
        ticker  = row["home_ticker"]
        ts      = row["game_start_ts"]

        prob = fetch_last_pregame_trade(ticker, ts)

        results.append({
            "game_id":             gid,
            "kalshi_event_ticker": row["kalshi_event_ticker"],
            "home_team":           row["team2"],
            "home_ticker":         ticker,
            "game_start_utc":      ts,
            "pregame_market_prob": prob,
        })

        if i % 50 == 0 or i == n:
            found = sum(1 for r in results if r["pregame_market_prob"] is not None)
            print(f"  [{i}/{n}] 已处理 | 有赛前价格: {found}")

        time.sleep(0.12)  # 主动限速，避免 429

    df_out = pd.DataFrame(results)
    df_out.to_csv(OUT_CSV, index=False)

    found = df_out["pregame_market_prob"].notna().sum()
    missing = df_out["pregame_market_prob"].isna().sum()
    print(f"\n完成。总场次={len(df_out)}, 有赛前价格={found}, 无={missing}")
    print(f"保存: {OUT_CSV}")

    # 按前缀分组报告
    df_out["prefix"] = df_out["game_id"].str[:3]
    print(df_out.groupby("prefix")["pregame_market_prob"].agg(
        count="count", not_null=lambda x: x.notna().sum()
    ).to_string())


if __name__ == "__main__":
    main()
