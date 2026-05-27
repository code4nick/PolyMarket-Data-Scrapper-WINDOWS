from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parent
_src = ROOT_DIR / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from polymarket_consensus.large_bet_plays import enrich_large_bet_plays

load_dotenv(ROOT_DIR / ".env")

OUTPUT_PATH = Path("outputs/daily_report.json")

app = Flask(__name__)

# Cold-start refresh should run once per server process, not on every page reload.
_cold_start_pending = str(os.getenv("UI_COLD_START", "false") or "false").lower() == "true"

UI_LARGE_BET_CONFIG_PATH = ROOT_DIR / "outputs" / ".ui_large_bet_config.json"
_UI_LARGE_BET_CONFIG_DEFAULTS = {
    "min_usd": float(os.getenv("LARGE_BET_MIN_USD", "15000") or "15000"),
    "max_opposing_ratio": float(os.getenv("LARGE_BET_MAX_OPPOSING_RATIO", "2.5") or "2.5"),
    "ratio_basis": str(os.getenv("LARGE_BET_RATIO_BASIS", "usd") or "usd").strip().lower(),  # "usd" or "shares"
}


def _normalize_ratio_basis(val: Any) -> str:
    basis = str(val or "").strip().lower()
    return basis if basis in ("usd", "shares") else "usd"


def _load_ui_large_bet_config() -> dict[str, Any]:
    try:
        if not UI_LARGE_BET_CONFIG_PATH.exists():
            return dict(_UI_LARGE_BET_CONFIG_DEFAULTS)
        payload = json.loads(UI_LARGE_BET_CONFIG_PATH.read_text(encoding="utf-8"))
        return {
            "min_usd": float(payload.get("min_usd", _UI_LARGE_BET_CONFIG_DEFAULTS["min_usd"])),
            "max_opposing_ratio": float(
                payload.get(
                    "max_opposing_ratio",
                    _UI_LARGE_BET_CONFIG_DEFAULTS["max_opposing_ratio"],
                )
            ),
            "ratio_basis": _normalize_ratio_basis(payload.get("ratio_basis", "usd")),
        }
    except Exception:
        return dict(_UI_LARGE_BET_CONFIG_DEFAULTS)


def _save_ui_large_bet_config(cfg: dict[str, Any]) -> None:
    UI_LARGE_BET_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    UI_LARGE_BET_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


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


def _load_today_plays_history() -> list[dict]:
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
        plays = snap.get("large_bet_plays") or snap.get("consensus_bets") or []
        display.append(
            {
                "generated_at_utc": snap.get("generated_at_utc"),
                "mode": snap.get("mode"),
                "top_traders_count": snap.get("top_traders_count"),
                "large_bet_plays": enrich_large_bet_plays(plays, traders),
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
            "large_bet_plays": [],
            "sports_positions_today": [],
            "settings": {},
        }
    return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))


@app.get("/")
def dashboard():
    global _cold_start_pending
    cold_start = _cold_start_pending
    if cold_start:
        _cold_start_pending = False

    report = _load_report()
    if cold_start:
        report = {
            "generated_at_utc": None,
            "top_traders_count": 0,
            "positions_count": 0,
            "sports_positions_count": 0,
            "large_bet_plays": [],
            "sports_positions_today": [],
            "settings": {},
        }

    settings = report.get("settings") or {}
    plays = report.get("large_bet_plays") or []
    live_section_empty = not plays
    history_today = _load_today_plays_history()
    tz_name = _event_day_tz_name()
    history_date_local = datetime.now(tz=_event_day_zoneinfo()).date().isoformat()
    ui_cfg = _load_ui_large_bet_config()
    min_usd = float(ui_cfg.get("min_usd") or 15000)
    max_ratio = float(ui_cfg.get("max_opposing_ratio") or 2.5)
    ratio_basis = ui_cfg.get("ratio_basis") or "usd"
    return render_template(
        "index.html",
        report=report,
        plays=plays,
        live_section_empty=live_section_empty,
        large_bet_min_usd=min_usd,
        large_bet_max_ratio=max_ratio,
        large_bet_ratio_basis=ratio_basis,
        plays_history_today=history_today,
        history_date_local=history_date_local,
        event_day_timezone=tz_name,
        cold_start=cold_start,
    )


@app.get("/api/report")
def api_report():
    return jsonify(_load_report())


@app.get("/api/ui_config")
def api_ui_config_get():
    return jsonify(_load_ui_large_bet_config())


@app.post("/api/ui_config")
def api_ui_config_post():
    payload = request.get_json(silent=True) or {}
    try:
        min_usd = float(payload.get("min_usd", _UI_LARGE_BET_CONFIG_DEFAULTS["min_usd"]))
        max_ratio = float(payload.get("max_opposing_ratio", _UI_LARGE_BET_CONFIG_DEFAULTS["max_opposing_ratio"]))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Invalid numeric inputs."}), 400
    ratio_basis = _normalize_ratio_basis(payload.get("ratio_basis", "usd"))

    # Basic sanity bounds
    if min_usd < 0 or max_ratio <= 0:
        return jsonify({"ok": False, "message": "min_usd must be >= 0 and max_opposing_ratio must be > 0."}), 400

    cfg = {"min_usd": min_usd, "max_opposing_ratio": max_ratio, "ratio_basis": ratio_basis}
    _save_ui_large_bet_config(cfg)
    return jsonify({"ok": True, "message": "Saved."})


@app.post("/api/refresh")
def api_refresh():
    refresh_started = perf_counter()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    src_path = str((ROOT_DIR / "src").resolve())
    env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}{os.pathsep}{existing_pythonpath}"

    # Apply UI-saved large-bet filters to the next refresh run.
    ui_cfg = _load_ui_large_bet_config()
    env["LARGE_BET_MIN_USD"] = str(ui_cfg.get("min_usd", 15000.0))
    env["LARGE_BET_MAX_OPPOSING_RATIO"] = str(ui_cfg.get("max_opposing_ratio", 2.5))
    env["LARGE_BET_RATIO_BASIS"] = str(ui_cfg.get("ratio_basis", "usd"))

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
    elapsed = perf_counter() - refresh_started
    print(f"api_refresh elapsed_s={elapsed:.2f}")
    return jsonify({"ok": True, "message": "Data refreshed successfully."})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
