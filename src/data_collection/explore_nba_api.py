"""
Exploratory: 完整打印 nba_api 各端点的原始 response，不预设 schema。
目标：
  1. 确认 play-by-play 数据的字段（score、game clock）
  2. 确认 game log 的比赛起止时间字段
  3. 确认数据覆盖范围（最早到哪个赛季）
"""

import json
import time
from nba_api.stats.endpoints import (
    leaguegamelog,
    playbyplayv2,
    boxscoresummaryv2,
)
from nba_api.stats.static import teams

# ── Step 1: 已知有 Kalshi 数据的赛季是 2024-25 和 2025-26
#            先找一场 2025 NBA Finals 比赛的 game_id
print("=" * 60)
print("STEP 1: LeagueGameLog — 2024-25 赛季 Playoffs，找总决赛")
print("=" * 60)
log = leaguegamelog.LeagueGameLog(
    season="2024-25",
    season_type_all_star="Playoffs",
    player_or_team_abbreviation="T",  # team level
)
raw = log.get_dict()
print("Headers:", raw["resultSets"][0]["headers"])
print("Row count:", len(raw["resultSets"][0]["rowSet"]))
print("First 3 rows:")
for row in raw["resultSets"][0]["rowSet"][:3]:
    print(" ", row)
print()
time.sleep(1)

# ── Step 2: 找 OKC vs IND 总决赛的 game_id（2025-06-13 和 2025-06-19）
print("=" * 60)
print("STEP 2: 过滤 OKC-IND 总决赛比赛，找 game_id")
print("=" * 60)
headers = raw["resultSets"][0]["headers"]
rows = raw["resultSets"][0]["rowSet"]
# 找包含 OKC 或 IND 的比赛，6月份
finals_rows = [
    row for row in rows
    if (row[headers.index("TEAM_ABBREVIATION")] in ("OKC", "IND"))
    and row[headers.index("GAME_DATE")].startswith("2025-06")
]
for r in finals_rows[:10]:
    print({h: v for h, v in zip(headers, r) if h in
           ("GAME_ID", "GAME_DATE", "TEAM_ABBREVIATION", "MATCHUP", "WL")})
print()
time.sleep(1)

# ── Step 3: 选一个 game_id，看 BoxScoreSummaryV2（含精确起止时间）
if finals_rows:
    game_id = finals_rows[0][headers.index("GAME_ID")]
    print("=" * 60)
    print(f"STEP 3: BoxScoreSummaryV2 for game_id={game_id}")
    print("=" * 60)
    summary = boxscoresummaryv2.BoxScoreSummaryV2(game_id=game_id)
    summary_dict = summary.get_dict()
    for rs in summary_dict["resultSets"]:
        print(f"  ResultSet: {rs['name']}")
        print(f"  Headers:   {rs['headers']}")
        if rs["rowSet"]:
            print(f"  Row[0]:    {rs['rowSet'][0]}")
        print()
    time.sleep(1)

    # ── Step 4: PlayByPlayV2 — 原始字段
    print("=" * 60)
    print(f"STEP 4: PlayByPlayV2 for game_id={game_id}（前10行）")
    print("=" * 60)
    pbp = playbyplayv2.PlayByPlayV2(game_id=game_id)
    pbp_dict = pbp.get_dict()
    for rs in pbp_dict["resultSets"]:
        print(f"  ResultSet: {rs['name']}")
        print(f"  Headers:   {rs['headers']}")
        print(f"  Row count: {len(rs['rowSet'])}")
        if rs["rowSet"]:
            print("  First 5 rows:")
            for row in rs["rowSet"][:5]:
                print("   ", row)
        print()
else:
    print("未找到总决赛比赛，请检查赛季/日期过滤条件")
