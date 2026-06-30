# Kalshi NBA Prediction Market — Quant Research

Built a real-time NBA win-probability model using logistic regression, incorporating pre-game market-implied odds, and compared it against live Kalshi prediction-market prices to detect pricing inefficiencies. The goal was to test whether a sports prediction market could be systematically out-predicted using a quantitative model — validating data integrity, diagnosing model calibration failures, and strictly separating training from test data to rule out overfitting. The signal held a stable 59–67% win rate across both training and unseen test games.

---

## Project Structure

```
Kalshi/
├── src/
│   ├── data_collection/       # API scripts: Kalshi trades, NBA play-by-play, pregame probs
│   ├── modeling/              # Win probability model training (v1, split, v2)
│   ├── backtest/              # Phase 2 signal design and backtest engine
│   └── analysis/              # Spread analysis, no-fee scenario, flowchart generation
├── tests/                     # Unit tests for backtest logic
├── data/
│   ├── raw/                   # Raw API responses (excluded from git)
│   └── processed/             # Parsed CSVs; model .pkl files (excluded from git)
├── outputs/
│   ├── figures/               # Calibration curves, P&L plots, spread charts
│   └── reports/               # Markdown and CSV research reports
└── CLAUDE.md                  # Project decisions, workflow rules, research log
```

---

## How to Run

Reproduce results from scratch in this order:

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Fetch NBA play-by-play data and build game mapping**
```bash
python src/data_collection/fetch_nba_data.py
```

**3. Fetch Kalshi pre-game market probabilities (1 API call per game)**
```bash
python src/data_collection/fetch_pregame_probs.py
```

**4. Train win probability models (v2, Regular Season + Playoffs/Finals)**
```bash
python src/modeling/train_win_prob_v2.py
```

**5. Fetch live trade data for the 31 Phase 1 analysis games**
```bash
python src/data_collection/fetch_phase1_trades.py
```

**6. Run Phase 1 spread and convergence analysis**
```bash
python src/analysis/phase1_spread_analysis.py
```

**7. Run Phase 2 backtest (signal design + P&L with taker fees)**
```bash
python src/backtest/backtest_phase2.py
```

**8. Run no-fee theoretical analysis (signal quality assessment)**
```bash
python src/analysis/phase2_no_fee_analysis.py
```

**9. Run unit tests**
```bash
pytest tests/
```

---

## Key Findings

### Win Probability Model (v2)
- **Regular Season** (975 games, logistic regression): Brier score 0.1445, max calibration deviation 9.8% — within the 10% acceptance threshold.
- **Playoffs/Finals** (74 games, logistic regression + home-court + mirror augmentation): Brier score 0.1592, max deviation 7.3% — within threshold.
- Adding `pregame_market_prob` (last Kalshi trade price before tip-off, held fixed throughout the game) resolved a prior 14.3% calibration failure in Playoffs/Finals.

### Spread & Convergence (Phase 1, 31 games)
- Detected meaningful model-vs-market spreads throughout games, especially at tip-off where pre-game team strength was absent in v1.
- After ≥10-second persistence filtering (removing oscillation noise): Regular Season median convergence time 37s (p90: 185s); Playoffs 56s (p90: 529s); Finals 45s (p90: 288s).

### Backtest (Phase 2, 31 games, 18 in-sample / 13 out-of-sample)
- **Before taker fees**: signal win rate 59–67%, positive gross P&L across all categories — the model genuinely detects market mispricing.
- **After taker fees** (Kalshi taker fee = $0.07 × C × (1−C) per contract, charged on both entry and exit): all categories turn negative across all tested thresholds (3%/5%/7%).
  - Regular Season: IS total net −$1.82, OOS −$1.48
  - Playoffs: IS +$0.18 (near zero), OOS −$0.09
  - Finals: IS −$0.44, OOS −$0.82
- **Conclusion**: The Kalshi NBA market is approximately efficient after fees. The taker fee structure (~3.5% at mid-price) consumes the entire edge. IS and OOS results are directionally consistent, ruling out overfitting.

---

## Tech Stack

| Layer | Tools |
|---|---|
| Data — NBA | `nba_api` (PlayByPlayV3, LeagueGameLog) |
| Data — Market | Kalshi public REST API (`/historical/trades`, `/historical/market-candlesticks`) |
| Modeling | `scikit-learn` LogisticRegression, `numpy`, `pandas` |
| Backtesting | Custom Python engine (no look-ahead bias by construction) |
| Visualization | `matplotlib` |
| Testing | `pytest` (24 unit tests) |

---

> This is an independent demo project built to practice directing an AI agent (Claude Code) through a full quantitative research workflow.
