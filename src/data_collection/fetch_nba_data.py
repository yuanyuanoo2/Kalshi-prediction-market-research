"""
Phase 0 前置: NBA 数据拉取与处理
Step 1 - 建 Kalshi event ticker → NBA game_id 映射表
Step 2 - 拉取所有匹配场次的 PlayByPlayV3
Step 3 - 解析 period 时间戳 + 线性插值 wall clock + 前向填充比分
产出:
  data/raw/nba_game_mapping.csv
  data/raw/nba_pbp/<game_id>.json   (原始)
  data/processed/nba_pbp_parsed.csv (处理后)
"""

import os, re, json, time, csv
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests
from nba_api.stats.endpoints import leaguegamelog, playbyplayv3

# ── 常量 ──────────────────────────────────────────────────────────────
EASTERN = ZoneInfo("America/New_York")   # 自动处理 EST/EDT
MONTH_MAP = {
    "JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06",
    "JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12",
}
QUARTER_SECS  = 12 * 60   # 720s
OT_SECS       = 5  * 60   # 300s
PBP_DIR       = "data/raw/nba_pbp"
MAPPING_CSV   = "data/raw/nba_game_mapping.csv"
PARSED_CSV    = "data/processed/nba_pbp_parsed.csv"
NBA_DELAY     = 0.6        # nba_api 请求间隔，避免触发限速


# ── Step 1: 建 Kalshi → NBA game_id 映射 ─────────────────────────────

def fetch_game_log(season: str, season_type: str) -> list[dict]:
    """拉取 NBA 赛季 game log，返回每场唯一行（去掉两队重复）。"""
    log = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star=season_type,
        player_or_team_abbreviation="T",
    )
    d = log.get_dict()
    h = d["resultSets"][0]["headers"]
    rows = d["resultSets"][0]["rowSet"]
    seen, result = set(), []
    for r in rows:
        gid = r[h.index("GAME_ID")]
        if gid not in seen:
            seen.add(gid)
            matchup = r[h.index("MATCHUP")]
            team    = r[h.index("TEAM_ABBREVIATION")]
            # 从 matchup 里提取对手
            other = matchup.replace(team, "").replace(" @ ", "").replace(" vs. ", "").strip()
            result.append({
                "game_id":   gid,
                "game_date": r[h.index("GAME_DATE")],
                "team1":     team,
                "team2":     other,
            })
    return result


def build_nba_lookup() -> dict:
    """返回 {(date, frozenset{t1,t2}): game_id}"""
    lookup = {}
    configs = [
        ("2024-25", "Playoffs"),
        ("2025-26", "Regular Season"),
        ("2025-26", "PlayIn"),
        ("2025-26", "Playoffs"),
    ]
    for season, stype in configs:
        print(f"  拉取 {season} {stype} ...", end=" ", flush=True)
        try:
            rows = fetch_game_log(season, stype)
            for g in rows:
                key = (g["game_date"], frozenset([g["team1"], g["team2"]]))
                lookup[key] = g["game_id"]
            print(f"{len(rows)} 场")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(NBA_DELAY)
    return lookup


def parse_kalshi_ticker(ticker: str):
    """
    KXNBAGAME-25JUN13OKCIND → (date='2025-06-13', t1='OKC', t2='IND')
    返回 None 如果格式不匹配。
    """
    m = re.match(r"KXNBAGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]{3})([A-Z]{3})$", ticker)
    if not m:
        return None
    yy, mon, dd, t1, t2 = m.groups()
    if mon not in MONTH_MAP:
        return None
    date = f"20{yy}-{MONTH_MAP[mon]}-{dd}"
    return date, t1, t2


def load_kalshi_event_tickers() -> list[str]:
    """从已保存的 Kalshi historical markets 数据里提取 KXNBAGAME 事件 ticker。
    如果没有保存的数据，直接走 API 拉一次。"""
    import requests as req
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    tickers = set()
    cursor = None
    while True:
        params = {"limit": 1000, "series_ticker": "KXNBAGAME"}
        if cursor:
            params["cursor"] = cursor
        r = req.get(BASE + "/historical/markets", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        for m in data.get("markets", []):
            et = m.get("event_ticker", "")
            if et.startswith("KXNBAGAME-"):
                tickers.add(et)
        cursor = data.get("cursor")
        if not cursor or not data.get("markets"):
            break
    return list(tickers)


def build_mapping(kalshi_tickers: list[str], nba_lookup: dict) -> list[dict]:
    rows = []
    unmatched = []
    for ticker in kalshi_tickers:
        parsed = parse_kalshi_ticker(ticker)
        if not parsed:
            continue
        date, t1, t2 = parsed
        key = (date, frozenset([t1, t2]))
        game_id = nba_lookup.get(key)
        rows.append({"kalshi_event_ticker": ticker, "date": date,
                     "team1": t1, "team2": t2, "nba_game_id": game_id or ""})
        if not game_id:
            unmatched.append(ticker)
    return rows, unmatched


# ── Step 2: PlayByPlayV3 拉取 ─────────────────────────────────────────

def fetch_pbp(game_id: str) -> list[dict]:
    """拉取并返回 actions 列表。"""
    pbp = playbyplayv3.PlayByPlayV3(game_id=game_id)
    raw = json.loads(pbp.get_response())
    return raw["game"]["actions"]


# ── Step 3: 解析 + 线性插值 wall clock ───────────────────────────────

def parse_period_time(description: str) -> datetime | None:
    """
    从 'Start/End of Xth Period (8:38 PM EST)' 里解析时间。
    返回 UTC aware datetime，或 None。
    注意：NBA API 标注 'EST' 但实际随 DST 变化，用 America/New_York 处理。
    """
    m = re.search(r"\((\d+:\d+\s*[AP]M)\s+E[SD]T\)", description, re.IGNORECASE)
    if not m:
        return None
    time_str = m.group(1).strip()
    # 需要日期才能正确处理 DST；从外部传入 game_date
    return time_str   # 先返回字符串，在调用方结合日期解析


def time_str_to_utc(time_str: str, game_date: str) -> datetime | None:
    """
    '8:38 PM' + '2025-06-05' → UTC datetime
    """
    try:
        naive = datetime.strptime(f"{game_date} {time_str}", "%Y-%m-%d %I:%M %p")
        local = naive.replace(tzinfo=EASTERN)
        return local.astimezone(timezone.utc)
    except Exception:
        return None


def clock_to_seconds(clock_str: str) -> float:
    """'PT11M15.00S' → 675.0 (seconds remaining in period)"""
    m = re.match(r"PT(\d+)M([\d.]+)S", clock_str)
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + float(m.group(2))


def period_total_seconds(period: int) -> float:
    """返回该节的总时长（秒）。1-4节=720s，加时=300s。"""
    return QUARTER_SECS if period <= 4 else OT_SECS


def total_time_remaining(period: int, clock_s: float) -> float:
    """
    返回全场剩余时间（秒）。
    规定时间：4×720=2880s 为满值。
    加时赛：每节额外 300s，返回负值（-OT_SECS 到 0 之间）。
    """
    if period <= 4:
        return (4 - period) * QUARTER_SECS + clock_s
    else:
        ot_num = period - 4
        return -(ot_num - 1) * OT_SECS - (OT_SECS - clock_s)


def parse_actions(actions: list[dict], game_date: str) -> list[dict]:
    """
    解析 PlayByPlayV3 actions：
    - 提取 period 边界 UTC 时间戳（处理跨午夜比赛）
    - 线性插值每个 event 的 wall clock（UTC）
    - 前向填充 scoreHome / scoreAway
    返回逐行记录列表。
    """
    # ── 收集 period 边界时间（按节顺序，检测跨午夜自动 +1天）──
    # period_bounds[period] = {"start": utc_dt, "end": utc_dt}
    raw_events = []
    for a in actions:
        if a.get("actionType") != "period":
            continue
        period = a["period"]
        sub    = a.get("subType", "")
        desc   = a.get("description", "")
        t_str  = parse_period_time(desc)
        if t_str:
            raw_events.append((period, sub, t_str))

    # 按 (period, start=0/end=1) 排序，保证时间单调递增
    raw_events.sort(key=lambda x: (x[0], 0 if x[1] == "start" else 1))

    cur_date   = game_date
    last_utc   = None
    period_bounds = {}

    for period, sub, t_str in raw_events:
        utc_dt = time_str_to_utc(t_str, cur_date)
        if utc_dt is None:
            continue
        # 跨午夜检测：如果解析结果早于上一个时间戳，则日期 +1 天重新解析
        if last_utc is not None and utc_dt < last_utc:
            next_date = (datetime.strptime(cur_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            utc_dt = time_str_to_utc(t_str, next_date)
            if utc_dt is None:
                continue
            cur_date = next_date
        last_utc = utc_dt
        if period not in period_bounds:
            period_bounds[period] = {}
        period_bounds[period][sub] = utc_dt

    # ── 逐 action 插值 ──
    records = []
    last_score_home = 0
    last_score_away = 0

    for a in actions:
        period   = a["period"]
        clock_s  = clock_to_seconds(a.get("clock", "PT00M00.00S"))
        tr       = total_time_remaining(period, clock_s)

        # 前向填充比分
        sh = a.get("scoreHome", "")
        sa = a.get("scoreAway", "")
        if sh != "":
            try:
                last_score_home = int(sh)
                last_score_away = int(sa)
            except (ValueError, TypeError):
                pass

        # 线性插值 wall clock
        wall_utc = None
        bounds = period_bounds.get(period, {})
        p_start = bounds.get("start")
        p_end   = bounds.get("end")
        p_dur   = period_total_seconds(period)

        if p_start and p_end:
            elapsed_s  = p_dur - clock_s
            total_span = (p_end - p_start).total_seconds()
            if total_span > 0:
                ratio    = min(max(elapsed_s / p_dur, 0.0), 1.0)
                wall_utc = p_start.timestamp() + ratio * total_span
            else:
                # p_end 解析异常（不应出现），退化为 start + elapsed
                wall_utc = p_start.timestamp() + elapsed_s
        elif p_start:
            # 只有 start（比赛中途取消等），用 start + elapsed
            elapsed_s = p_dur - clock_s
            wall_utc  = p_start.timestamp() + elapsed_s

        records.append({
            "action_number":   a.get("actionNumber"),
            "action_id":       a.get("actionId"),
            "period":          period,
            "clock":           a.get("clock"),
            "clock_seconds":   clock_s,
            "time_remaining":  round(tr, 2),
            "score_home":      last_score_home,
            "score_away":      last_score_away,
            "score_diff":      last_score_home - last_score_away,
            "action_type":     a.get("actionType"),
            "sub_type":        a.get("subType"),
            "team":            a.get("teamTricode"),
            "wall_utc":        round(wall_utc, 3) if wall_utc is not None else None,
            "description":     a.get("description", "")[:80],
        })

    return records


# ── 主流程 ────────────────────────────────────────────────────────────

def main():
    os.makedirs(PBP_DIR, exist_ok=True)
    os.makedirs("data/raw", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)

    # ── Step 1: 建映射 ──
    print("\n[Step 1] 拉取 NBA game log，建映射表")
    nba_lookup = build_nba_lookup()

    print("[Step 1] 拉取 Kalshi event tickers ...")
    kalshi_tickers = load_kalshi_event_tickers()
    print(f"  共 {len(kalshi_tickers)} 个 KXNBAGAME event tickers")

    mapping, unmatched = build_mapping(kalshi_tickers, nba_lookup)
    matched = [r for r in mapping if r["nba_game_id"]]
    print(f"  匹配成功: {len(matched)}, 未匹配: {len(unmatched)}")
    if unmatched[:5]:
        print(f"  未匹配样本: {unmatched[:5]}")

    with open(MAPPING_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kalshi_event_ticker","date","team1","team2","nba_game_id"])
        w.writeheader()
        w.writerows(mapping)
    print(f"  保存: {MAPPING_CSV}")

    # ── Step 2+3: 拉取 PBP + 解析 ──
    print(f"\n[Step 2+3] 拉取 {len(matched)} 场比赛的 PlayByPlayV3 并解析 ...")

    parsed_rows = []
    failed = []

    for i, row in enumerate(matched):
        game_id = row["nba_game_id"]
        date    = row["date"]
        ticker  = row["kalshi_event_ticker"]
        pbp_path = os.path.join(PBP_DIR, f"{game_id}.json")

        # 如果本地已有缓存则跳过 API 调用
        if os.path.exists(pbp_path):
            with open(pbp_path) as f:
                actions = json.load(f)
        else:
            try:
                actions = fetch_pbp(game_id)
                with open(pbp_path, "w") as f:
                    json.dump(actions, f)
                time.sleep(NBA_DELAY)
            except Exception as e:
                print(f"  [{i+1}/{len(matched)}] {game_id} FAILED: {e}")
                failed.append({"game_id": game_id, "ticker": ticker, "error": str(e)})
                time.sleep(1)
                continue

        records = parse_actions(actions, date)
        for rec in records:
            rec["game_id"] = game_id
            rec["kalshi_event_ticker"] = ticker
            rec["game_date"] = date
        parsed_rows.extend(records)

        if (i + 1) % 50 == 0 or i + 1 == len(matched):
            print(f"  [{i+1}/{len(matched)}] 累计 {len(parsed_rows):,} 行 | 失败: {len(failed)}")

    # 写 CSV
    if parsed_rows:
        fieldnames = list(parsed_rows[0].keys())
        with open(PARSED_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(parsed_rows)
        print(f"\n保存: {PARSED_CSV}  ({len(parsed_rows):,} 行)")

    if failed:
        fail_path = "data/raw/nba_pbp_failed.json"
        with open(fail_path, "w") as f:
            json.dump(failed, f, indent=2)
        print(f"失败场次: {len(failed)}，详见 {fail_path}")

    print("\n[完成] Phase 0 数据拉取结束。")
    print(f"  PBP 原始 JSON: {PBP_DIR}/ ({len(matched)} 个文件)")
    print(f"  处理后 CSV:    {PARSED_CSV}")
    print(f"  映射表:        {MAPPING_CSV}")


if __name__ == "__main__":
    main()
