"""
Phase 2: 交易信号设计与回测

信号规则:
  spread(t) = P_model(t) - P_market(t)
  net_edge(t) = |spread(t)| - taker_fee(P_market(t))
  当 net_edge > threshold 且连续维持 ≥10s → 触发信号

方向:
  spread > 0 → model 认为主场被低估 → 买 YES (主场获胜合约)
  spread < 0 → model 认为客场被低估 → 买 NO (= 客场获胜合约)

平仓规则 (两种对比):
  A: net_edge 回落至 threshold 以下 → 平仓（mark-to-market）
  B: 固定时间窗口（默认120s）强制平仓（mark-to-market）
  若比赛结束前未触发以上条件 → 以实际比赛结果结算（0 或 1），无平仓手续费

手续费:
  taker fee = $0.07 × C × (1−C) per contract（开仓和平仓各一次）
  比赛结算不收手续费

样本切分:
  按 game_id 在每个类别内排序，前 60% = in-sample，后 40% = out-of-sample
  阈值只在 in-sample 上调，out-of-sample 使用选定阈值验证

无 look-ahead bias 保证:
  P_model(t) 使用 PBP 中 wall_utc ≤ t 的最新快照（LOCF）
  pregame_market_prob 取 game_start 之前的数据，整场固定
  信号在持续 ≥10s 后才触发，不使用未来价格
"""

import json
import os
import pickle
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── 路径 ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent
PBP_CSV        = ROOT / "data/processed/nba_pbp_parsed.csv"
MODEL_REG_PKL  = ROOT / "data/processed/win_prob_model_regular_v2.pkl"
MODEL_PLAY_PKL = ROOT / "data/processed/win_prob_model_playoffs_v2.pkl"
TRADES_DIR     = ROOT / "data/raw/phase1_trades"
SELECTION_CSV  = ROOT / "data/processed/phase1_game_selection.csv"
PREGAME_CSV    = ROOT / "data/processed/pregame_market_probs.csv"
FIG_DIR        = ROOT / "outputs/figures"
REPORT_DIR     = ROOT / "outputs/reports"

# ── 超参数 ──────────────────────────────────────────────────────────────────
THRESHOLDS     = [0.03, 0.05, 0.07]   # 在 in-sample 上对比，5% 为主选
EXIT_WINDOWS   = [60, 120, 300]        # 秒, Exit B 固定窗口
MIN_PERSIST_S  = 10.0                  # ≥10s 持续才触发信号
ENDGAME_TR     = 300                   # 剩余 < 5 分钟 = 比赛末段
SPLIT_RATIO    = 0.60                  # 前 60% game_id 为 in-sample
SPLIT_SEED     = 42


# ── 手续费 ──────────────────────────────────────────────────────────────────

def taker_fee(C: np.ndarray | float) -> np.ndarray | float:
    """taker fee = $0.07 × C × (1−C)，单位同 C（0–1 美元/合约）。"""
    return 0.07 * C * (1.0 - C)


# ── 数据加载 ────────────────────────────────────────────────────────────────

def load_models():
    with open(MODEL_REG_PKL, "rb") as f:
        reg = pickle.load(f)
    with open(MODEL_PLAY_PKL, "rb") as f:
        play = pickle.load(f)
    return reg["model"], play["model"]


def load_pbp() -> pd.DataFrame:
    df = pd.read_csv(PBP_CSV, dtype={"game_id": str})
    df["wall_utc"]             = pd.to_numeric(df["wall_utc"], errors="coerce")
    df["score_diff"]           = pd.to_numeric(df["score_diff"], errors="coerce")
    df["time_remaining"]       = pd.to_numeric(df["time_remaining"], errors="coerce")
    df["period"]               = pd.to_numeric(df["period"], errors="coerce")
    df["is_overtime"]          = (df["period"] > 4).astype(int)
    df["time_remaining_feature"] = df.apply(
        lambda r: r["time_remaining"] + (r["period"] - 4) * 300
        if r["period"] > 4 else r["time_remaining"],
        axis=1,
    )
    return df.dropna(subset=["wall_utc", "score_diff"]).sort_values(["game_id", "wall_utc"])


def load_pregame_probs() -> dict[str, float]:
    df = pd.read_csv(PREGAME_CSV, dtype={"game_id": str})
    return df.set_index("game_id")["pregame_market_prob"].to_dict()


# ── Spread 时序构建 ──────────────────────────────────────────────────────────

def build_spread_df(
    game_json: dict,
    pbp_game: pd.DataFrame,
    model_reg,
    model_play,
    pregame_probs: dict[str, float],
) -> pd.DataFrame | None:
    """
    构建每场比赛的 spread 时序。
    返回 DataFrame: [t, p_market, p_model, spread, time_remaining_feature]
    只含比赛进行期间（game_start ~ game_end）的成交。

    无 look-ahead bias:
      - 每个时间点 t 只使用 wall_utc ≤ t 的 PBP 快照（LOCF）
      - pregame_market_prob 取 game_start 前数据，整场固定
    """
    gid      = game_json["nba_game_id"]
    game_cat = game_json["game_cat"]
    trades   = game_json.get("trades", [])

    if not trades or pbp_game.empty:
        return None

    # 解析成交记录
    rows = []
    for t in trades:
        try:
            ts    = pd.Timestamp(t["created_time"], tz="UTC").timestamp()
            price = float(t["yes_price_dollars"])
            rows.append({"t": ts, "price": price})
        except Exception:
            continue
    if not rows:
        return None

    tdf_all = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)

    game_start = pbp_game["wall_utc"].min()
    game_end   = pbp_game["wall_utc"].max()

    # 只保留比赛进行期间的成交
    tdf = tdf_all[(tdf_all["t"] >= game_start) & (tdf_all["t"] <= game_end)].copy().reset_index(drop=True)
    if len(tdf) < 10:
        return None

    # PBP 快照数组（升序）
    pbp_times = pbp_game["wall_utc"].values
    pbp_sd    = pbp_game["score_diff"].values
    pbp_tr    = pbp_game["time_remaining_feature"].values
    pbp_ot    = pbp_game["is_overtime"].values

    # LOCF 查找每个成交时间点对应的 PBP 快照
    t_arr = tdf["t"].values
    idx   = np.searchsorted(pbp_times, t_arr, side="right") - 1
    idx   = np.clip(idx, 0, len(pbp_times) - 1)

    sd = pbp_sd[idx]
    tr = pbp_tr[idx]
    ot = pbp_ot[idx]

    # pregame_market_prob: 固定值，整场不变
    pp_val = pregame_probs.get(gid, 0.5)
    if np.isnan(pp_val):
        pp_val = 0.5
    pp = np.full(len(t_arr), pp_val)

    # P_model (v2)
    if game_cat == "Regular":
        X = np.column_stack([sd, tr, ot, pp])
        p_model = model_reg.predict_proba(X)[:, 1]
    else:
        is_home = np.ones(len(t_arr))
        X = np.column_stack([sd, tr, ot, is_home, pp])
        p_model = model_play.predict_proba(X)[:, 1]

    tdf["p_model"]              = p_model
    tdf["p_market"]             = tdf["price"]
    tdf["spread"]               = p_model - tdf["price"].values
    tdf["time_remaining_feature"] = tr

    return tdf[["t", "p_market", "p_model", "spread", "time_remaining_feature"]].copy()


def get_game_result(pbp_game: pd.DataFrame) -> int:
    """
    从 PBP 最后一行 score_diff 判断主场胜负。
    score_diff = score_home - score_away
    返回 1 = 主场赢, 0 = 客场赢。NBA 无平局，score_diff ≠ 0。
    """
    final_sd = pbp_game.iloc[-1]["score_diff"]
    return 1 if final_sd > 0 else 0


# ── 信号检测 ────────────────────────────────────────────────────────────────

def detect_signals(
    tdf: pd.DataFrame,
    threshold: float,
    min_persist_s: float = MIN_PERSIST_S,
) -> list[dict]:
    """
    检测交易信号。
    规则: net_edge(t) = |spread(t)| - taker_fee(P_market(t)) > threshold
          且该状态连续维持 ≥ min_persist_s 秒 → 触发信号

    无 look-ahead bias: 只使用当前及之前的数据，不使用未来价格。
    信号触发时刻 = 已持续 ≥ min_persist_s 后的第一个时间点。

    返回信号列表，每个信号含:
      entry_idx, entry_ts, direction (+1=买YES, -1=买NO), entry_price,
      net_edge_at_entry, time_remaining_feature
    """
    C        = tdf["p_market"].values
    fee      = taker_fee(C)
    net_edge = np.abs(tdf["spread"].values) - fee
    dir_arr  = np.sign(tdf["spread"].values)
    t        = tdf["t"].values
    tr       = tdf["time_remaining_feature"].values
    n        = len(t)

    signals      = []
    persist_start = None  # 超过阈值开始的时间戳
    i = 0

    while i < n:
        if net_edge[i] > threshold:
            if persist_start is None:
                persist_start = t[i]
            elif t[i] - persist_start >= min_persist_s:
                # 信号触发
                signals.append({
                    "entry_idx":              i,
                    "entry_ts":               float(t[i]),
                    "direction":              int(dir_arr[i]),
                    "entry_price":            float(C[i]),
                    "net_edge_at_entry":      float(net_edge[i]),
                    "time_remaining_feature": float(tr[i]),
                    "is_endgame":             bool(tr[i] < ENDGAME_TR),
                })
                # 跳过当前连续超标区域，防止同一 gap 重复计数
                while i < n and net_edge[i] > threshold:
                    i += 1
                persist_start = None
                continue
        else:
            persist_start = None
        i += 1

    return signals


# ── 平仓逻辑 ────────────────────────────────────────────────────────────────

def _exit_convergence(
    signal: dict,
    tdf: pd.DataFrame,
    threshold: float,
) -> dict | None:
    """Exit A: net_edge 回落至 threshold 以下时 mark-to-market 平仓。"""
    C        = tdf["p_market"].values
    fee      = taker_fee(C)
    net_edge = np.abs(tdf["spread"].values) - fee
    t        = tdf["t"].values
    n        = len(t)

    for j in range(signal["entry_idx"] + 1, n):
        if net_edge[j] <= threshold:
            return {
                "exit_type": "convergence",
                "exit_ts":    float(t[j]),
                "exit_price": float(C[j]),
                "exit_fee":   float(taker_fee(C[j])),
            }
    return None


def _exit_fixed_window(
    signal: dict,
    tdf: pd.DataFrame,
    exit_window_s: float,
) -> dict | None:
    """Exit B: 固定时间窗口后 mark-to-market 平仓。"""
    target_ts = signal["entry_ts"] + exit_window_s
    C = tdf["p_market"].values
    t = tdf["t"].values
    n = len(t)

    for j in range(signal["entry_idx"] + 1, n):
        if t[j] >= target_ts:
            return {
                "exit_type": "fixed_window",
                "exit_ts":    float(t[j]),
                "exit_price": float(C[j]),
                "exit_fee":   float(taker_fee(C[j])),
            }
    return None


def _game_end_exit(game_result: int, tdf: pd.DataFrame) -> dict:
    """比赛结算: 以比赛结果定价，不收手续费（Kalshi 自动结算）。"""
    return {
        "exit_type":  "game_end",
        "exit_ts":    float(tdf["t"].iloc[-1]),
        "exit_price": float(game_result),  # 1=主场赢, 0=客场赢
        "exit_fee":   0.0,
    }


def compute_pnl(signal: dict, exit_info: dict) -> tuple[float, float]:
    """
    计算单笔交易的 P&L (毛利润, 净利润)，单位: 美元/合约。

    方向:
      +1 (买 YES): P&L_gross = exit_price - entry_price
      -1 (买 NO):  P&L_gross = entry_price - exit_price
         (因为 NO 合约买入价 = 1 - entry_price, 卖出价 = 1 - exit_price,
          P&L = (1-exit) - (1-entry) = entry - exit)
    """
    entry_price = signal["entry_price"]
    exit_price  = exit_info["exit_price"]
    direction   = signal["direction"]

    entry_fee = float(taker_fee(entry_price))
    exit_fee  = exit_info["exit_fee"]

    if direction == 1:
        pnl_gross = exit_price - entry_price
    else:
        pnl_gross = entry_price - exit_price

    pnl_net = pnl_gross - entry_fee - exit_fee
    return pnl_gross, pnl_net


# ── 单场回测 ─────────────────────────────────────────────────────────────────

def backtest_game(
    game_json: dict,
    pbp_game: pd.DataFrame,
    model_reg,
    model_play,
    pregame_probs: dict,
    threshold: float,
    exit_window_s: float,
) -> list[dict]:
    """
    单场比赛回测，返回该场所有交易记录列表（同时包含 Exit A 和 Exit B）。
    """
    gid      = game_json["nba_game_id"]
    game_cat = game_json["game_cat"]

    spread_df = build_spread_df(game_json, pbp_game, model_reg, model_play, pregame_probs)
    if spread_df is None or len(spread_df) < 10:
        return []

    game_result = get_game_result(pbp_game)
    signals = detect_signals(spread_df, threshold)
    game_end = _game_end_exit(game_result, spread_df)

    trades = []
    for sig in signals:
        # Exit A: 收敛平仓
        exit_a = _exit_convergence(sig, spread_df, threshold) or game_end
        # Exit B: 固定窗口平仓
        exit_b = _exit_fixed_window(sig, spread_df, exit_window_s) or game_end

        for exit_info in [exit_a, exit_b]:
            pnl_gross, pnl_net = compute_pnl(sig, exit_info)
            trades.append({
                "game_id":                gid,
                "game_cat":               game_cat,
                "exit_strategy":          exit_info["exit_type"],
                "threshold":              threshold,
                "exit_window_s":          exit_window_s,
                "entry_ts":               sig["entry_ts"],
                "exit_ts":                exit_info["exit_ts"],
                "direction":              sig["direction"],
                "entry_price":            sig["entry_price"],
                "exit_price":             exit_info["exit_price"],
                "net_edge_at_entry":      sig["net_edge_at_entry"],
                "time_remaining_feature": sig["time_remaining_feature"],
                "is_endgame":             sig["is_endgame"],
                "pnl_gross":              pnl_gross,
                "pnl_net":                pnl_net,
                "hold_time_s":            exit_info["exit_ts"] - sig["entry_ts"],
                "game_result":            game_result,
            })
    return trades


# ── 样本切分 ────────────────────────────────────────────────────────────────

def split_games(selection: pd.DataFrame) -> tuple[list[str], list[str]]:
    """
    按 game_id 分层（每个 game_cat 内）切分 in-sample / out-of-sample。
    各类别内按 game_id 排序，前 SPLIT_RATIO = in-sample，剩余 = out-of-sample。
    不随机：固定顺序保证可复现。
    """
    is_ids   = []
    oos_ids  = []
    for cat, grp in selection.groupby("game_cat"):
        sorted_ids = sorted(grp["nba_game_id"].tolist())
        cutoff = int(len(sorted_ids) * SPLIT_RATIO)
        is_ids.extend(sorted_ids[:cutoff])
        oos_ids.extend(sorted_ids[cutoff:])
    return is_ids, oos_ids


# ── 指标计算 ────────────────────────────────────────────────────────────────

def compute_metrics(trades: list[dict]) -> dict:
    """
    计算回测指标（pre-fee 和 post-fee）。

    指标:
      n_trades, win_rate (pnl > 0), avg_pnl, std_pnl,
      sharpe (mean/std, per-trade), max_drawdown (累计净值峰谷差),
      total_pnl
    """
    if not trades:
        return {
            "n_trades":    0,
            "win_rate_gross": np.nan, "win_rate_net": np.nan,
            "avg_pnl_gross":  np.nan, "avg_pnl_net":  np.nan,
            "std_pnl_gross":  np.nan, "std_pnl_net":  np.nan,
            "sharpe_gross":   np.nan, "sharpe_net":   np.nan,
            "max_dd_gross":   np.nan, "max_dd_net":   np.nan,
            "total_pnl_gross":np.nan, "total_pnl_net":np.nan,
        }

    pnl_g = np.array([t["pnl_gross"] for t in trades])
    pnl_n = np.array([t["pnl_net"]   for t in trades])

    def sharpe(arr):
        return float(arr.mean() / arr.std()) if arr.std() > 0 else np.nan

    def max_drawdown(arr):
        # 在首位插入 0，表示初始无仓位状态，确保回撤从 0 基线计算
        cumsum = np.concatenate([[0.0], np.cumsum(arr)])
        peak   = np.maximum.accumulate(cumsum)
        dd     = cumsum - peak
        return float(dd.min())

    return {
        "n_trades":        len(trades),
        "win_rate_gross":  float((pnl_g > 0).mean()),
        "win_rate_net":    float((pnl_n > 0).mean()),
        "avg_pnl_gross":   float(pnl_g.mean()),
        "avg_pnl_net":     float(pnl_n.mean()),
        "std_pnl_gross":   float(pnl_g.std()),
        "std_pnl_net":     float(pnl_n.std()),
        "sharpe_gross":    sharpe(pnl_g),
        "sharpe_net":      sharpe(pnl_n),
        "max_dd_gross":    max_drawdown(pnl_g),
        "max_dd_net":      max_drawdown(pnl_n),
        "total_pnl_gross": float(pnl_g.sum()),
        "total_pnl_net":   float(pnl_n.sum()),
    }


# ── 主函数 ──────────────────────────────────────────────────────────────────

def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    print("加载模型 ...")
    model_reg, model_play = load_models()

    print("加载 PBP ...")
    pbp_df = load_pbp()

    print("加载 pregame_market_probs ...")
    pregame_probs = load_pregame_probs()

    print("加载 Phase 1 游戏列表 ...")
    selection = pd.read_csv(SELECTION_CSV, dtype={"nba_game_id": str})

    is_ids, oos_ids = split_games(selection)
    print(f"In-sample: {len(is_ids)} 场 | Out-of-sample: {len(oos_ids)} 场")
    cat_counts = selection.groupby("game_cat")["nba_game_id"].count()
    print(f"类别分布: {cat_counts.to_dict()}")

    # ── 阶段 1: in-sample 阈值调参 ──────────────────────────────────────────
    print("\n=== In-sample 阈值调参 ===")
    is_summary_rows = []

    for threshold in THRESHOLDS:
        for exit_window in EXIT_WINDOWS:
            all_trades = []
            for gid in is_ids:
                g_json_path = TRADES_DIR / f"{gid}.json"
                if not g_json_path.exists():
                    continue
                with open(g_json_path) as f:
                    game_json = json.load(f)
                pbp_game = pbp_df[pbp_df["game_id"] == gid].copy()
                if pbp_game.empty:
                    continue
                trades = backtest_game(
                    game_json, pbp_game, model_reg, model_play,
                    pregame_probs, threshold, exit_window,
                )
                all_trades.extend(trades)

            # 按 exit_strategy 分开汇总
            for exit_strat in ["convergence", "fixed_window"]:
                subset = [t for t in all_trades if t["exit_strategy"] == exit_strat or
                          (exit_strat == "fixed_window" and t["exit_strategy"] in ["fixed_window", "game_end"]
                           and "exit_window_s" in t)]
                # 更精确: 过滤 exit_strategy == exit_strat 或 game_end 接管固定窗口的情况
                # 实际上两种策略分别在 backtest_game 中独立生成，exit_strategy 已正确标记
                pass

            # 分策略汇总
            conv_trades = [t for t in all_trades if t["exit_strategy"] in ("convergence", "game_end")
                          and t.get("exit_window_s") == exit_window]
            # 注: 两种策略在 backtest_game 中均记录，每个信号生成两条 trade 记录
            # 此处简化: 按 exit_strategy 字段直接过滤
            for strat in ["convergence", "game_end", "fixed_window"]:
                strat_trades = [t for t in all_trades if t["exit_strategy"] == strat]
                if strat_trades:
                    m = compute_metrics(strat_trades)
                    is_summary_rows.append({
                        "threshold":    threshold,
                        "exit_window":  exit_window,
                        "exit_type":    strat,
                        "split":        "in_sample",
                        **m,
                    })

    is_summary = pd.DataFrame(is_summary_rows)
    print("\nIn-sample 汇总:")
    print(is_summary[is_summary["n_trades"] > 0][[
        "threshold","exit_window","exit_type","n_trades",
        "win_rate_net","avg_pnl_net","sharpe_net","total_pnl_net"
    ]].to_string(index=False))

    # 选择最佳阈值（按 avg_pnl_net 在 convergence 策略上）
    conv_is = is_summary[is_summary["exit_type"].isin(["convergence","game_end"]) &
                         (is_summary["split"] == "in_sample") &
                         (is_summary["n_trades"] > 5)]
    if not conv_is.empty:
        best_row = conv_is.loc[conv_is["avg_pnl_net"].idxmax()]
        best_threshold  = best_row["threshold"]
        best_exit_window = best_row["exit_window"]
    else:
        best_threshold  = 0.05
        best_exit_window = 120
    print(f"\n选定阈值: {best_threshold:.0%}, Exit B 窗口: {best_exit_window}s")

    # ── 阶段 2: 完整回测（in-sample + out-of-sample，选定阈值）─────────────
    print("\n=== 完整回测（选定参数） ===")
    all_split_trades = []

    for split_label, split_ids in [("in_sample", is_ids), ("out_of_sample", oos_ids)]:
        for gid in split_ids:
            g_json_path = TRADES_DIR / f"{gid}.json"
            if not g_json_path.exists():
                continue
            with open(g_json_path) as f:
                game_json = json.load(f)
            pbp_game = pbp_df[pbp_df["game_id"] == gid].copy()
            if pbp_game.empty:
                continue
            trades = backtest_game(
                game_json, pbp_game, model_reg, model_play,
                pregame_probs, best_threshold, best_exit_window,
            )
            for t in trades:
                t["split"] = split_label
            all_split_trades.extend(trades)

    trades_df = pd.DataFrame(all_split_trades)
    if trades_df.empty:
        print("没有信号触发，请检查阈值参数。")
        return

    # 保存明细
    trades_out = REPORT_DIR / "phase2_trades.csv"
    trades_df.to_csv(trades_out, index=False)
    print(f"交易明细: {trades_out} ({len(trades_df)} 条)")

    # ── 阶段 3: 分组报告 ────────────────────────────────────────────────────
    print("\n=== 分组报告 ===")
    report_rows = []

    for split in ["in_sample", "out_of_sample"]:
        for cat in ["Regular", "Playoffs", "Finals"]:
            for exit_strat in ["convergence", "fixed_window", "game_end"]:
                subset = trades_df[
                    (trades_df["split"]         == split) &
                    (trades_df["game_cat"]       == cat)  &
                    (trades_df["exit_strategy"]  == exit_strat)
                ]
                if subset.empty:
                    continue
                m = compute_metrics(subset.to_dict("records"))
                row = {
                    "split":       split,
                    "game_cat":    cat,
                    "exit_strat":  exit_strat,
                    **m,
                }
                report_rows.append(row)

    report_df = pd.DataFrame(report_rows)

    # 打印核心结果
    key_cols = ["split","game_cat","exit_strat","n_trades",
                "win_rate_gross","win_rate_net",
                "avg_pnl_gross","avg_pnl_net",
                "sharpe_gross","sharpe_net",
                "max_dd_gross","max_dd_net",
                "total_pnl_gross","total_pnl_net"]
    print(report_df[key_cols].to_string(index=False))

    # ── 阶段 4: 末段敏感性分析 ───────────────────────────────────────────────
    print("\n=== 末段敏感性分析（is_endgame = True/False 对比）===")
    for split in ["in_sample", "out_of_sample"]:
        for endgame in [False, True]:
            subset = trades_df[
                (trades_df["split"]     == split) &
                (trades_df["is_endgame"] == endgame)
            ]
            tag = f"{split} | is_endgame={endgame}"
            m   = compute_metrics(subset.to_dict("records"))
            print(f"  {tag}: n={m['n_trades']}, "
                  f"avg_net={m['avg_pnl_net']:.4f}, "
                  f"sharpe_net={m['sharpe_net']:.3f}")

    # ── 可视化 ──────────────────────────────────────────────────────────────
    _plot_cumulative_pnl(trades_df, best_threshold, best_exit_window)
    _plot_pnl_distribution(trades_df, best_threshold)
    _plot_pnl_by_entry_price(trades_df)

    # ── 报告写入 ────────────────────────────────────────────────────────────
    _write_report(trades_df, report_df, best_threshold, best_exit_window, is_ids, oos_ids)

    print("\nPhase 2 完成。报告: outputs/reports/phase2_backtest_report.md")


# ── 可视化函数 ──────────────────────────────────────────────────────────────

def _plot_cumulative_pnl(trades_df: pd.DataFrame, threshold: float, exit_window: float):
    """累计 P&L 曲线（in-sample vs out-of-sample，两种退出策略）。"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.suptitle(f"Phase 2: 累计净 P&L (threshold={threshold:.0%}, exit_window={exit_window}s)", fontsize=12)

    for col, cat in enumerate(["Regular", "Playoffs/Finals"]):
        for row, split in enumerate(["in_sample", "out_of_sample"]):
            ax = axes[row][col]
            if cat == "Regular":
                mask = trades_df["game_cat"] == "Regular"
            else:
                mask = trades_df["game_cat"].isin(["Playoffs", "Finals"])

            sub = trades_df[mask & (trades_df["split"] == split)].sort_values("entry_ts")

            for strat, color, ls in [
                ("convergence", "steelblue", "-"),
                ("fixed_window", "darkorange", "--"),
                ("game_end",     "green",      ":"),
            ]:
                s = sub[sub["exit_strategy"] == strat]
                if not s.empty:
                    cum = np.cumsum(s["pnl_net"].values)
                    ax.plot(cum, label=strat, color=color, ls=ls, lw=1.2)

            ax.axhline(0, color="black", lw=0.5)
            ax.set_title(f"{cat} | {split.replace('_', '-')}", fontsize=9)
            ax.set_xlabel("trade #")
            ax.set_ylabel("cumulative net P&L ($)")
            ax.legend(fontsize=7)

    plt.tight_layout()
    path = FIG_DIR / "phase2_cumulative_pnl.png"
    plt.savefig(path, dpi=120)
    plt.close()
    print(f"图: {path}")


def _plot_pnl_distribution(trades_df: pd.DataFrame, threshold: float):
    """P&L 分布直方图（净利润，按退出策略）。"""
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    fig.suptitle(f"Phase 2: 净 P&L 分布 (threshold={threshold:.0%})", fontsize=12)

    for ax, strat in zip(axes, ["convergence", "fixed_window", "game_end"]):
        sub = trades_df[trades_df["exit_strategy"] == strat]["pnl_net"].dropna()
        if sub.empty:
            continue
        ax.hist(sub, bins=30, color="steelblue", alpha=0.7, edgecolor="white")
        ax.axvline(sub.mean(), color="red", ls="--", lw=1.2, label=f"mean={sub.mean():.4f}")
        ax.axvline(0, color="black", lw=0.8)
        ax.set_title(strat, fontsize=9)
        ax.set_xlabel("pnl_net ($)")
        ax.legend(fontsize=7)

    plt.tight_layout()
    path = FIG_DIR / "phase2_pnl_distribution.png"
    plt.savefig(path, dpi=120)
    plt.close()
    print(f"图: {path}")


def _plot_pnl_by_entry_price(trades_df: pd.DataFrame):
    """P&L vs 入场价格散点图（检查是否有手续费结构性亏损）。"""
    sub = trades_df[trades_df["exit_strategy"] == "convergence"]
    if sub.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    sc = ax.scatter(sub["entry_price"], sub["pnl_net"], c=sub["pnl_net"],
                    cmap="RdYlGn", alpha=0.5, s=15, vmin=-0.1, vmax=0.1)
    ax.axhline(0, color="black", lw=0.8)
    ax.axvline(0.5, color="gray", ls="--", lw=0.8)
    plt.colorbar(sc, ax=ax, label="pnl_net ($)")
    ax.set_xlabel("entry_price (yes_price)")
    ax.set_ylabel("pnl_net ($)")
    ax.set_title("Phase 2: 净 P&L vs 入场价格 (Exit A: 收敛平仓)")

    path = FIG_DIR / "phase2_pnl_vs_entry_price.png"
    plt.savefig(path, dpi=120)
    plt.close()
    print(f"图: {path}")


# ── 报告 ─────────────────────────────────────────────────────────────────────

def _write_report(
    trades_df: pd.DataFrame,
    report_df: pd.DataFrame,
    threshold: float,
    exit_window: float,
    is_ids: list,
    oos_ids: list,
):
    n_total   = len(trades_df)
    n_is      = len(trades_df[trades_df["split"] == "in_sample"])
    n_oos     = len(trades_df[trades_df["split"] == "out_of_sample"])
    n_endgame = len(trades_df[trades_df["is_endgame"]])

    def fmt_row(r) -> str:
        return (f"| {r.get('split',''):<16} | {r.get('game_cat',''):<9} | {r.get('exit_strat',''):<12} "
                f"| {int(r.get('n_trades',0)):>8} "
                f"| {r.get('win_rate_net',np.nan):>8.1%} "
                f"| {r.get('avg_pnl_gross',np.nan):>10.4f} "
                f"| {r.get('avg_pnl_net',np.nan):>10.4f} "
                f"| {r.get('sharpe_net',np.nan):>8.3f} "
                f"| {r.get('max_dd_net',np.nan):>10.4f} "
                f"| {r.get('total_pnl_net',np.nan):>10.4f} |")

    header = (
        "| split            | game_cat  | exit_strat   "
        "| n_trades | win_rate | avg_gross  | avg_net    "
        "| sharpe   | max_dd     | total_net  |\n"
        "|-----------------|-----------|--------------|"
        "----------|----------|------------|------------|"
        "----------|------------|------------|"
    )

    rows_str = "\n".join(fmt_row(r) for _, r in report_df.iterrows())

    report = f"""# Phase 2 回测报告

生成时间: 2026-06-21

## 参数设置

- 模型: v2 (Regular LR / Playoffs LR+mirror+is_home)
- 信号阈值: **{threshold:.0%}** (in-sample 调参选定)
- 最小持续时间: {MIN_PERSIST_S}s (固定)
- Exit A: 收敛平仓（net_edge 回落至阈值以下）
- Exit B: 固定 {exit_window}s 窗口平仓
- 手续费: taker fee = $0.07 × C × (1−C)，开平仓各一次；比赛结算无费用
- 末段标记: time_remaining_feature < {ENDGAME_TR}s = is_endgame

## 样本切分

- In-sample: {len(is_ids)} 场（各类别前 {SPLIT_RATIO:.0%} game_id 按字典序）
- Out-of-sample: {len(oos_ids)} 场

## 信号统计

| 指标 | 数值 |
|------|------|
| 总交易数（两种策略各一条） | {n_total} |
| In-sample 交易 | {n_is} |
| Out-of-sample 交易 | {n_oos} |
| 末段信号（is_endgame=True） | {n_endgame} ({n_endgame/n_total*100:.1f}%) |

## 分组回测结果

{header}
{rows_str}

> Playoffs/Finals 结果须保守解读（训练场次 74 场，小样本统计不稳定）。
> 末段信号（is_endgame=True）占 {n_endgame/n_total*100:.1f}%，可能包含战术犯规/暂停等不可重复因素。

## 图表

- `outputs/figures/phase2_cumulative_pnl.png` — 累计净 P&L 曲线
- `outputs/figures/phase2_pnl_distribution.png` — P&L 分布
- `outputs/figures/phase2_pnl_vs_entry_price.png` — P&L vs 入场价格

## 数据文件

- `outputs/reports/phase2_trades.csv` — 交易明细
"""
    path = REPORT_DIR / "phase2_backtest_report.md"
    with open(path, "w") as f:
        f.write(report)
    print(f"报告: {path}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
