from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parent
_src = ROOT_DIR / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

from polymarket_consensus.consensus_view import build_consensus_filter_off_lists, enrich_bets

load_dotenv(ROOT_DIR / ".env")

OUTPUT_PATH = Path("outputs/daily_report.json")

app = Flask(__name__)


def _event_day_tz_name() -> str:
    return os.getenv("EVENT_DAY_TIMEZONE", "America/New_York")


def _event_day_zoneinfo():
    try:
        return ZoneInfo(_event_day_tz_name())
    except Exception:
        return timezone.utc


def _today_history_path() -> Path:
    day = datetime.now(tz=_event_day_zoneinfo()).date().isoformat()
    return ROOT_DIR / "outputs" / f"consensus_history_{day}.jsonl"


def _load_today_consensus_history() -> list[dict]:
    path = _today_history_path()
    if not path.exists():
        return []
    snapshots: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    snapshots.reverse()
    display: list[dict] = []
    for snap in snapshots:
        traders = snap.get("traders") or []
        bets = snap.get("consensus_bets") or []
        display.append(
            {
                "generated_at_utc": snap.get("generated_at_utc"),
                "mode": snap.get("mode"),
                "top_traders_count": snap.get("top_traders_count"),
                "consensus_bets": enrich_bets(bets, traders),
            }
        )
    return display


def _load_report() -> dict:
    if not OUTPUT_PATH.exists():
        return {
            "generated_at_utc": None,
            "top_traders_count": 0,
            "positions_count": 0,
            "sports_positions_count": 0,
            "consensus_bets": [],
            "consensus_bets_relaxed": [],
            "relaxed_opposition_threshold_usd": 500.0,
            "sports_positions_today": [],
        }
    return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))


@app.get("/")
def dashboard():
    report = _load_report()
    relaxed_raw = report.get("consensus_bets_relaxed") or []
    top_20, bets_relaxed_extra = build_consensus_filter_off_lists(report)
    live_section_empty = not top_20 and not report.get("sports_positions_today") and not relaxed_raw
    material_usd = float(report.get("relaxed_opposition_threshold_usd") or 500.0)
    show_relaxed_consensus_ui = not live_section_empty
    relaxed_data_stale = "relaxed_opposition_threshold_usd" not in report and not live_section_empty
    history_today = _load_today_consensus_history()
    tz_name = _event_day_tz_name()
    history_date_local = datetime.now(tz=_event_day_zoneinfo()).date().isoformat()
    return render_template(
        "index.html",
        report=report,
        bets=top_20,
        bets_relaxed_extra=bets_relaxed_extra,
        show_relaxed_consensus_ui=show_relaxed_consensus_ui,
        relaxed_data_stale=relaxed_data_stale,
        live_section_empty=live_section_empty,
        material_opposition_min_usd=material_usd,
        consensus_history_today=history_today,
        history_date_local=history_date_local,
        event_day_timezone=tz_name,
    )


@app.get("/api/report")
def api_report():
    return jsonify(_load_report())


@app.post("/api/refresh")
def api_refresh():
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    src_path = str((ROOT_DIR / "src").resolve())
    env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}{os.pathsep}{existing_pythonpath}"
    result = subprocess.run(
        [sys.executable, "run_daily.py"],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Data refresh failed.",
                    "stderr": result.stderr[-2000:],
                    "stdout": result.stdout[-2000:],
                }
            ),
            500,
        )
    return jsonify({"ok": True, "message": "Data refreshed successfully."})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)

