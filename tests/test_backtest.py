"""
Phase 2 回测核心逻辑单元测试。

覆盖:
  - taker_fee 计算
  - detect_signals 信号检测（含持续时间过滤）
  - compute_pnl P&L 计算（买YES/买NO，mark-to-market/结算两种情形）
  - compute_metrics 指标统计
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

from src.backtest.backtest_phase2 import (
    taker_fee,
    detect_signals,
    compute_pnl,
    compute_metrics,
    split_games,
    ENDGAME_TR,
)


# ── taker_fee ────────────────────────────────────────────────────────────────

def test_taker_fee_midpoint():
    """C = 0.5 时手续费最大: 0.07 × 0.5 × 0.5 = 0.0175。"""
    assert abs(taker_fee(0.5) - 0.0175) < 1e-9


def test_taker_fee_extremes():
    """C = 0 或 1 时手续费为 0（已无风险，不收费）。"""
    assert taker_fee(0.0) == 0.0
    assert taker_fee(1.0) == 0.0


def test_taker_fee_array():
    """向量化计算正确。"""
    C = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    fees = taker_fee(C)
    expected = 0.07 * C * (1 - C)
    np.testing.assert_allclose(fees, expected)


def test_taker_fee_symmetry():
    """手续费关于 0.5 对称: fee(C) = fee(1-C)。"""
    for c in [0.1, 0.3, 0.4]:
        assert abs(taker_fee(c) - taker_fee(1 - c)) < 1e-12


# ── detect_signals ───────────────────────────────────────────────────────────

def _make_spread_df(ts, spreads, p_market=None):
    """构造测试用 spread_df。"""
    if p_market is None:
        p_market = np.full(len(ts), 0.5)  # 固定 0.5，手续费最大
    tr = np.full(len(ts), 1000.0)  # time_remaining_feature, 不是末段
    return pd.DataFrame({
        "t":                      ts,
        "p_market":               p_market,
        "spread":                 spreads,
        "time_remaining_feature": tr,
    })


def test_detect_signals_no_signal_below_threshold():
    """净边距不超过阈值时，不应产生信号。"""
    ts      = np.arange(0.0, 60.0, 1.0)
    # spread = 0.06 - fee(0.5)=0.0175 → net = 0.0425 < threshold 0.05
    spreads = np.full(len(ts), 0.06)
    tdf     = _make_spread_df(ts, spreads)
    signals = detect_signals(tdf, threshold=0.05)
    assert len(signals) == 0, "净边距不足，不应触发信号"


def test_detect_signals_fires_after_persistence():
    """
    净边距超过阈值，持续 ≥10s 后应触发一个信号。
    spread = 0.08, fee(0.5) = 0.0175, net = 0.0625 > 0.05 → 超标
    持续 20s → 第 10s 处应触发。
    """
    ts      = np.arange(0.0, 30.0, 1.0)  # 0..29s, 步长 1s
    spreads = np.full(len(ts), 0.08)
    tdf     = _make_spread_df(ts, spreads)
    signals = detect_signals(tdf, threshold=0.05, min_persist_s=10.0)
    assert len(signals) == 1, "应触发且仅触发一次信号"
    assert signals[0]["entry_ts"] >= 10.0, "信号应在持续 ≥10s 后触发"
    assert signals[0]["direction"] == 1, "spread > 0 → 方向应为 +1 (买YES)"


def test_detect_signals_no_fire_short_duration():
    """持续时间 < 10s → 不触发。"""
    ts      = np.arange(0.0, 8.0, 1.0)  # 只有 8s
    spreads = np.full(len(ts), 0.08)
    tdf     = _make_spread_df(ts, spreads)
    signals = detect_signals(tdf, threshold=0.05, min_persist_s=10.0)
    assert len(signals) == 0, "持续不足 10s，不应触发"


def test_detect_signals_direction_negative():
    """spread < 0 → direction = -1 (买NO)。"""
    ts      = np.arange(0.0, 30.0, 1.0)
    spreads = np.full(len(ts), -0.08)
    tdf     = _make_spread_df(ts, spreads)
    signals = detect_signals(tdf, threshold=0.05, min_persist_s=10.0)
    assert len(signals) == 1
    assert signals[0]["direction"] == -1


def test_detect_signals_two_gaps():
    """两个独立的 gap 各自触发一个信号。"""
    ts = np.arange(0.0, 80.0, 1.0)
    spreads = np.zeros(len(ts))
    spreads[0:25]  = 0.08   # gap 1: 0–24s (持续 25s > 10s → 触发)
    # gap 间隔: 25–44s 为 0
    spreads[45:75] = 0.08   # gap 2: 45–74s (持续 30s > 10s → 触发)
    tdf     = _make_spread_df(ts, spreads)
    signals = detect_signals(tdf, threshold=0.05, min_persist_s=10.0)
    assert len(signals) == 2, f"应触发 2 个信号，实际: {len(signals)}"


def test_detect_signals_endgame_flag():
    """time_remaining_feature < ENDGAME_TR → is_endgame = True。"""
    ts      = np.arange(0.0, 30.0, 1.0)
    spreads = np.full(len(ts), 0.08)
    tr      = np.full(len(ts), ENDGAME_TR - 10.0)  # 末段
    tdf = pd.DataFrame({
        "t": ts, "p_market": np.full(len(ts), 0.5),
        "spread": spreads, "time_remaining_feature": tr,
    })
    signals = detect_signals(tdf, threshold=0.05, min_persist_s=10.0)
    assert len(signals) == 1
    assert signals[0]["is_endgame"] is True


# ── compute_pnl ──────────────────────────────────────────────────────────────

def _make_signal(direction, entry_price):
    return {
        "direction":   direction,
        "entry_price": entry_price,
    }


def _make_exit(exit_price, exit_fee, exit_type="convergence"):
    return {
        "exit_price": exit_price,
        "exit_fee":   exit_fee,
        "exit_type":  exit_type,
    }


def test_pnl_buy_yes_profit():
    """买YES，价格上涨 → 盈利。"""
    sig  = _make_signal(+1, 0.4)
    exit = _make_exit(0.6, taker_fee(0.6))
    pnl_g, pnl_n = compute_pnl(sig, exit)
    assert pnl_g == pytest.approx(0.2, abs=1e-9), "毛利润应为 0.2"
    assert pnl_n < pnl_g, "净利润 < 毛利润（手续费>0）"
    assert pnl_n > 0, "手续费后仍应盈利"


def test_pnl_buy_yes_loss():
    """买YES，价格下跌 → 亏损。"""
    sig  = _make_signal(+1, 0.6)
    exit = _make_exit(0.4, taker_fee(0.4))
    pnl_g, pnl_n = compute_pnl(sig, exit)
    assert pnl_g == pytest.approx(-0.2, abs=1e-9)
    assert pnl_n < pnl_g  # 亏损加手续费更少


def test_pnl_buy_no_profit():
    """买NO（spread < 0），价格下跌 → 盈利。"""
    sig  = _make_signal(-1, 0.6)   # 入场时 yes_price = 0.6（NO = 0.4）
    exit = _make_exit(0.4, taker_fee(0.4))  # yes_price 降至 0.4（NO = 0.6，涨了）
    pnl_g, pnl_n = compute_pnl(sig, exit)
    # P&L = entry_price - exit_price = 0.6 - 0.4 = 0.2
    assert pnl_g == pytest.approx(0.2, abs=1e-9)
    assert pnl_n > 0


def test_pnl_game_end_settlement_no_exit_fee():
    """
    比赛结算（exit_fee = 0）正确计算。
    买YES at 0.3，主场最终赢 → exit_price = 1.0，exit_fee = 0。
    """
    sig  = _make_signal(+1, 0.3)
    exit = _make_exit(1.0, 0.0, exit_type="game_end")
    pnl_g, pnl_n = compute_pnl(sig, exit)
    assert pnl_g == pytest.approx(0.7, abs=1e-9)
    entry_fee = taker_fee(0.3)
    assert pnl_n == pytest.approx(0.7 - entry_fee, abs=1e-9)


def test_pnl_fee_symmetry():
    """
    同等条件下买 YES (C=0.3) 和买 NO (C=0.7) 的净 P&L 对称。
    假设市场从 C 收敛到 P_model=0.5（spread 为 0.2）。
    """
    # 买 YES: 入 0.3，出 0.5
    sig_yes  = _make_signal(+1, 0.3)
    exit_yes = _make_exit(0.5, taker_fee(0.5))
    _, pnl_yes = compute_pnl(sig_yes, exit_yes)

    # 买 NO（即 spread < 0, P_model=0.5 < P_market=0.7）: 入 0.7，出 0.5
    sig_no  = _make_signal(-1, 0.7)
    exit_no = _make_exit(0.5, taker_fee(0.5))
    _, pnl_no = compute_pnl(sig_no, exit_no)

    # 两者毛利润应对称（都是 0.2），但手续费不同（taker_fee(0.3)≠taker_fee(0.7）实际相等）
    assert abs(pnl_yes - pnl_no) < 1e-9, "对称 trade 的净 P&L 应相等"


# ── compute_metrics ──────────────────────────────────────────────────────────

def _make_trade(pnl_gross, pnl_net):
    return {"pnl_gross": pnl_gross, "pnl_net": pnl_net}


def test_metrics_empty():
    """空交易列表返回 n_trades=0，其余 NaN。"""
    m = compute_metrics([])
    assert m["n_trades"] == 0
    assert np.isnan(m["avg_pnl_net"])


def test_metrics_win_rate():
    """3 赢 1 负 → 胜率 0.75。"""
    trades = [_make_trade(0.05, 0.04)] * 3 + [_make_trade(-0.05, -0.06)]
    m = compute_metrics(trades)
    assert m["n_trades"] == 4
    assert m["win_rate_net"] == pytest.approx(0.75)


def test_metrics_all_losses():
    """全部亏损 → 胜率 0，最大回撤等于累计亏损。"""
    trades = [_make_trade(-0.02, -0.04)] * 5
    m = compute_metrics(trades)
    assert m["win_rate_net"] == 0.0
    assert m["max_dd_net"] == pytest.approx(-0.04 * 5, abs=1e-9)


def test_metrics_sharpe():
    """常数 P&L → Sharpe 为 NaN（std = 0）。"""
    trades = [_make_trade(0.1, 0.08)] * 5
    m = compute_metrics(trades)
    assert np.isnan(m["sharpe_net"])


def test_metrics_max_drawdown():
    """
    累计净 P&L: [0.1, 0.2, 0.1, 0.05, 0.15]
    峰值: [0.1, 0.2, 0.2, 0.2, 0.2]
    回撤: [0, 0, -0.1, -0.15, -0.05]
    最大回撤: -0.15
    """
    pnls = [0.1, 0.1, -0.1, -0.05, 0.1]
    trades = [_make_trade(p + 0.02, p) for p in pnls]
    m = compute_metrics(trades)
    assert m["max_dd_net"] == pytest.approx(-0.15, abs=1e-9)


def test_metrics_total_pnl():
    """总净 P&L 等于各笔求和。"""
    pnls = [0.04, -0.02, 0.03]
    trades = [_make_trade(p + 0.01, p) for p in pnls]
    m = compute_metrics(trades)
    assert m["total_pnl_net"] == pytest.approx(sum(pnls), abs=1e-9)


# ── split_games ──────────────────────────────────────────────────────────────

def test_split_no_overlap():
    """In-sample 和 out-of-sample 无重叠。"""
    data = {
        "nba_game_id": [f"game_{i:04d}" for i in range(30)],
        "game_cat":    ["Regular"] * 15 + ["Playoffs"] * 10 + ["Finals"] * 5,
    }
    sel = pd.DataFrame(data)
    is_ids, oos_ids = split_games(sel)
    assert len(set(is_ids) & set(oos_ids)) == 0, "In/Out-of-sample 不得重叠"


def test_split_ratio():
    """In-sample 比例约等于 SPLIT_RATIO。"""
    from src.backtest.backtest_phase2 import SPLIT_RATIO
    data = {
        "nba_game_id": [f"game_{i:04d}" for i in range(30)],
        "game_cat":    ["Regular"] * 15 + ["Playoffs"] * 10 + ["Finals"] * 5,
    }
    sel = pd.DataFrame(data)
    is_ids, oos_ids = split_games(sel)
    total = len(is_ids) + len(oos_ids)
    assert abs(len(is_ids) / total - SPLIT_RATIO) < 0.05


def test_split_all_games_covered():
    """所有游戏都被分配到 in-sample 或 out-of-sample。"""
    data = {
        "nba_game_id": [f"game_{i:04d}" for i in range(31)],
        "game_cat":    ["Regular"] * 15 + ["Playoffs"] * 10 + ["Finals"] * 6,
    }
    sel = pd.DataFrame(data)
    is_ids, oos_ids = split_games(sel)
    assert sorted(is_ids + oos_ids) == sorted(data["nba_game_id"])


if __name__ == "__main__":
    import pytest as pt
    pt.main([__file__, "-v"])
