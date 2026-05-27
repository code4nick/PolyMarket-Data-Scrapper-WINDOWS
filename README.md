# Polymarket Sports Consensus Tracker

This project pulls the top all-time profitable sports traders on Polymarket, fetches their active positions, and outputs the bets with the strongest cross-trader consensus.

## What it does

- Pulls top traders from Polymarket leaderboard (`SPORTS`, `ALL`, ordered by `PNL` by default).
- Optionally requires “active” wallets (recent on-chain trades) and backfills from deeper leaderboard ranks when enabled.
- Fetches each trader's current positions.
- Keeps only positions whose event has the `sports` tag (on by default).
- Groups positions by market + outcome.
- Ranks consensus bets by overlap (number of unique top traders) and dollar value.
- Writes daily outputs to `outputs/`.

## Setup

### macOS / Linux

1. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

2. Copy env file and tune settings:

   ```bash
   cp .env.example .env
   ```

### Windows (PowerShell)

1. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Copy env file and tune settings:

   ```powershell
   Copy-Item .env.example .env
   ```

## Run

### macOS / Linux

```bash
PYTHONPATH=src python3 run_daily.py
```

### Windows (PowerShell)

```powershell
$env:PYTHONPATH = "src"
python run_daily.py
```

## One-command launch

### Windows

```powershell
.\start.ps1
```

From Git Bash on Windows:

```bash
./start.sh
```

You can also double-click `start.bat` from File Explorer.

### macOS / Linux

```bash
./start.sh
```

This installs deps (if needed), refreshes data, opens `http://127.0.0.1:8000`, and starts the UI.

## UI Dashboard

1. Start/update data (see **Run** above).

2. Launch UI:

   - macOS / Linux: `PYTHONPATH=src python3 ui.py`
   - Windows: `$env:PYTHONPATH = "src"; python ui.py`

3. Open:
   - `http://127.0.0.1:8000`
   - JSON API: `http://127.0.0.1:8000/api/report`

## Outputs

- `outputs/daily_report.json` full run output (settings, traders, all consensus rows)
- `outputs/top_consensus_today.json` top 20 consensus bets
- `outputs/top_consensus_today.md` readable daily report

## Important settings

- `TOP_N_TRADERS`: how many top sports traders to track (10–20 recommended).
- `REQUIRE_ACTIVE_LEADERBOARD_TRADERS=true`: walk the all-time leaderboard in order and skip inactive wallets until `TOP_N_TRADERS` active ones are collected.
- `LEADERBOARD_ACTIVE_LOOKBACK_DAYS=30`: a wallet counts as active if it has at least one on-chain TRADE within this window.
- `LEADERBOARD_FETCH_LIMIT=60`: how many ranked leaderboard rows to pull before the active filter (capped at 60 in code).
- `LEADERBOARD_TIME_PERIOD=ALL`: all-time profitability leaderboard.
- `LEADERBOARD_ORDER_BY=PNL`: rank by all-time PnL.
- `SPORTS_ONLY_POSITIONS=true`: keep only sports-tagged positions.
- `STRICT_UNANIMOUS_ONLY=true`: exclude any market side with opposite-side top-trader participation.
- `TODAY_OPEN_EVENTS_ONLY=true`: include only currently open markets with event date today in `EVENT_DAY_TIMEZONE`.
- `USE_RECENT_ACTIVITY_ONLY=false`: optional alternative mode using recent trade activity.
- `LOOKBACK_HOURS=24`: only include BUY trades placed in the last 24 hours (when recent-activity mode is on).

## Automate daily

### macOS (cron)

```bash
crontab -e
```

Example (run daily at 9:00 AM local):

```cron
0 9 * * * cd "/path/to/Poly Kalshi PC Version" && /usr/bin/env bash -lc 'source .venv/bin/activate && PYTHONPATH=src python3 run_daily.py >> outputs/cron.log 2>&1'
```

### Windows (Task Scheduler)

- Program/script: `powershell.exe`
- Add arguments:

```powershell
-ExecutionPolicy Bypass -File "C:\Users\Nick\Desktop\Poly Kalshi PC Version\start.ps1"
```

(Adjust the path to match where you keep the project.)
