Please help me organize this project into a clean GitHub repository. Do the following in order:

1. Create a README.md at the root level with:
   - Project title: "Kalshi NBA Prediction Market — Quant Research"
   - One-paragraph summary (use this: "Built a real-time NBA win-probability model using logistic regression, incorporating pre-game market-implied odds, and compared it against live Kalshi prediction-market prices to detect pricing inefficiencies. The goal was to test whether a sports prediction market could be systematically out-predicted using a quantitative model — validating data integrity, diagnosing model calibration failures, and strictly separating training from test data to rule out overfitting. The signal held a stable 59–67% win rate across both training and unseen test games.")
   - A "Project Structure" section that maps out the folder layout
   - A "How to Run" section with step-by-step instructions to reproduce the results from scratch (data collection → model training → spread analysis → backtest)
   - A "Key Findings" section summarizing the main results
   - A "Tech Stack" section listing the main libraries and data sources used
   - A note at the bottom: "This is an independent demo project built to practice directing an AI agent (Claude Code) through a full quantitative research workflow."

2. Create a .gitignore that excludes:
   - data/raw/ (raw API data, too large)
   - data/processed/*.pkl (model files)
   - __pycache__/ and .pyc files
   - .env files
   - .DS_Store

3. Create a requirements.txt by scanning all Python files in src/ and listing the packages actually imported.

4. Check every Python file in src/ and add a one-line docstring at the top of any file that is missing one, describing what that script does.

5. Make sure the folder structure is clean:
   - src/data_collection/
   - src/modeling/
   - src/backtest/
   - src/analysis/
   - outputs/figures/
   - outputs/reports/
   - tests/
   If any of these folders are missing, create them with a .gitkeep file inside.

6. After all files are in place, run:
   git init
   git add .
   git commit -m "Initial commit: Kalshi NBA prediction market quant research project"

Then tell me:
- What files were created or modified
- What the final folder structure looks like
- Any files you skipped and why
- The exact commands I need to run next to push this to a new GitHub remote (just print the commands, don't run them)