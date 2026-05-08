# Polymarket Sports Consensus Tracker

This project pulls the top all-time profitable sports traders on Polymarket, fetches their active positions, and outputs the bets with the strongest cross-trader consensus.

## What it does

- Pulls top traders from Polymarket leaderboard (`SPORTS`, `ALL`, ordered by `PNL` by default).
- Fetches each trader's current positions.
- Keeps only positions whose event has the `sports` tag (on by default).
- Groups positions by market + outcome.
- Ranks consensus bets by overlap (number of unique top traders) and dollar value.
- Writes daily outputs to `outputs/`.

## Setup (Windows / PowerShell)

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

## Run (Windows / PowerShell)

```powershell
$env:PYTHONPATH = "src"
python run_daily.py
```

## One-command launch (Windows)

```powershell
.\start.ps1
```

This command installs deps (if needed), refreshes data, and starts the UI at `http://127.0.0.1:8000`.

If you are in Git Bash, use:

```bash
./start.sh
```

You can also double-click `start.bat` from File Explorer.

## UI Dashboard

1. Start/update data:

   ```powershell
   $env:PYTHONPATH = "src"
   python run_daily.py
   ```

2. Launch UI:

   ```powershell
   python ui.py
   ```

3. Open:
   - `http://127.0.0.1:8000`
   - JSON API: `http://127.0.0.1:8000/api/report`

## Outputs

- `outputs/daily_report.json` full run output (settings, traders, all consensus rows)
- `outputs/top_consensus_today.json` top 20 consensus bets
- `outputs/top_consensus_today.md` readable daily report

## Important settings

- `TOP_N_TRADERS`: how many top sports traders to track (10-20 recommended).
- `LEADERBOARD_TIME_PERIOD=ALL`: all-time profitability leaderboard.
- `LEADERBOARD_ORDER_BY=PNL`: rank by all-time PnL.
- `SPORTS_ONLY_POSITIONS=true`: keep only sports-tagged positions.
- `STRICT_UNANIMOUS_ONLY=true`: exclude any market side with opposite-side top-trader participation.
- `TODAY_OPEN_EVENTS_ONLY=true`: include only currently open markets with event date today in `EVENT_DAY_TIMEZONE`.
- `USE_RECENT_ACTIVITY_ONLY=false`: optional alternative mode using recent trade activity.
- `LOOKBACK_HOURS=24`: only include BUY trades placed in the last 24 hours.

## Automate daily (Windows Task Scheduler)

Create a basic task that runs daily and points to:

- Program/script: `powershell.exe`
- Add arguments:

```powershell
-ExecutionPolicy Bypass -File "C:\Users\Nick\Desktop\Poly Kalshi PC Version\start.ps1"
```

