"""
Phase A: 定位每场比赛"最后20分钟"和"胶着时段"中所有 >30s 的成交间隔。
只看关键时段，因为全场 p99 包含比赛前几天的市场休眠期，不是分析重点。
"""

import json
import pandas as pd
import os

RAW_PATH = "data/raw/phase1b_all_trades.json"
OUT_CSV = "outputs/reports/phase1b_anomaly_list.csv"
OUT_MD = "outputs/reports/phase1b_anomaly_list.md"

GAMES = [
    "2025-Finals-G7-OKC-IND",
    "2025-Finals-G5-OKC-IND",
    "2025-Christmas-MIN-DEN",
    "2026-Regular-DEN-OKC",
    "2026-Playoffs-GSW-LAC",
]

THRESHOLD_S = 30.0


def load_game_df(data: dict, label: str) -> pd.DataFrame:
    trades = data[label]["trades"]
    df = pd.DataFrame(trades)
    df["created_time"] = pd.to_datetime(df["created_time"], utc=True)
    df = df.sort_values("created_time").reset_index(drop=True)
    return df


def find_gaps(df: pd.DataFrame, label: str, window_label: str, threshold: float) -> list[dict]:
    df = df.copy().reset_index(drop=True)
    df["gap_s"] = df["created_time"].diff().dt.total_seconds()
    anomaly_rows = df[df["gap_s"] > threshold]

    results = []
    for idx in anomaly_rows.index:
        prev = df.loc[idx - 1]
        curr = df.loc[idx]
        results.append({
            "game": label,
            "window": window_label,
            "gap_s": round(curr["gap_s"], 1),
            "prev_time": str(prev["created_time"]),
            "prev_price": prev.get("yes_price_dollars", ""),
            "prev_ticker": prev.get("ticker", ""),
            "curr_time": str(curr["created_time"]),
            "curr_price": curr.get("yes_price_dollars", ""),
            "curr_ticker": curr.get("ticker", ""),
        })
    return results


def main():
    print("加载原始数据...")
    with open(RAW_PATH) as f:
        data = json.load(f)

    os.makedirs("outputs/reports", exist_ok=True)
    all_anomalies = []

    for label in GAMES:
        df = load_game_df(data, label)
        game_end = df["created_time"].max()

        # 关键时段1：最后20分钟
        cutoff_last20 = game_end - pd.Timedelta(minutes=20)
        df_last20 = df[df["created_time"] >= cutoff_last20].reset_index(drop=True)

        # 关键时段2：胶着时段（yes_price 0.35–0.65）
        df_close = df[
            df["yes_price_dollars"].astype(float).between(0.35, 0.65)
        ].reset_index(drop=True)

        gaps_last20 = find_gaps(df_last20, label, "last20min", THRESHOLD_S)
        gaps_close = find_gaps(df_close, label, "close_game(35-65c)", THRESHOLD_S)

        all_anomalies.extend(gaps_last20)
        all_anomalies.extend(gaps_close)

        print(f"\n{label}")
        print(f"  最后20分钟: {len(df_last20)} 笔 → {len(gaps_last20)} 处 >30s 异常")
        print(f"  胶着时段:   {len(df_close)} 笔 → {len(gaps_close)} 处 >30s 异常")

        for g in sorted(gaps_last20, key=lambda x: -x["gap_s"])[:5]:
            print(f"    [{g['window']}] {g['gap_s']}s | {g['prev_time']} ({g['prev_price']}) → {g['curr_time']} ({g['curr_price']})")
        for g in sorted(gaps_close, key=lambda x: -x["gap_s"])[:5]:
            print(f"    [{g['window']}] {g['gap_s']}s | {g['prev_time']} ({g['prev_price']}) → {g['curr_time']} ({g['curr_price']})")

    result_df = pd.DataFrame(all_anomalies).sort_values("gap_s", ascending=False).reset_index(drop=True)
    result_df.to_csv(OUT_CSV, index=False)

    # Markdown 摘要
    summary_lines = [
        "# Phase A: 异常间隔清单 (>30s)\n",
        f"总计: {len(result_df)} 处异常（关键时段合并，含跨时段重复）\n",
        "",
        "## 按比赛 × 时段统计\n",
        "| 比赛 | 时段 | 异常数 | 最大间隔 |",
        "|------|------|--------|---------|",
    ]
    for label in GAMES:
        for window in ["last20min", "close_game(35-65c)"]:
            sub = result_df[(result_df["game"] == label) & (result_df["window"] == window)]
            if len(sub) > 0:
                summary_lines.append(f"| {label} | {window} | {len(sub)} | {sub['gap_s'].max()}s |")

    summary_lines += [
        "",
        "## 最大间隔 Top 20\n",
        "| # | 比赛 | 时段 | 间隔(s) | 前一笔时间 | 前价 | 后一笔时间 | 后价 |",
        "|---|------|------|---------|-----------|------|-----------|------|",
    ]
    for i, row in result_df.head(20).iterrows():
        summary_lines.append(
            f"| {i+1} | {row['game']} | {row['window']} | {row['gap_s']} "
            f"| {row['prev_time'][:19]} | {row['prev_price']} "
            f"| {row['curr_time'][:19]} | {row['curr_price']} |"
        )

    with open(OUT_MD, "w") as f:
        f.write("\n".join(summary_lines))

    print(f"\n\n{'='*60}")
    print(f"Phase A 完成")
    print(f"总异常: {len(result_df)} 处")
    print(f"CSV: {OUT_CSV}")
    print(f"MD:  {OUT_MD}")


if __name__ == "__main__":
    main()
