from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_api_base: str = os.getenv("POLY_DATA_API_BASE", "https://data-api.polymarket.com")
    gamma_api_base: str = os.getenv("POLY_GAMMA_API_BASE", "https://gamma-api.polymarket.com")
    top_n_traders: int = int(os.getenv("TOP_N_TRADERS", "20"))
    leaderboard_category: str = os.getenv("LEADERBOARD_CATEGORY", "SPORTS")
    leaderboard_time_period: str = os.getenv("LEADERBOARD_TIME_PERIOD", "ALL")
    leaderboard_order_by: str = os.getenv("LEADERBOARD_ORDER_BY", "PNL")
    min_positions_per_market: int = int(os.getenv("MIN_POSITIONS_PER_MARKET", "2"))
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    sports_only_positions: bool = os.getenv("SPORTS_ONLY_POSITIONS", "true").lower() == "true"
    strict_unanimous_only: bool = os.getenv("STRICT_UNANIMOUS_ONLY", "true").lower() == "true"
    # Threshold (USD) for "material" other-side stake when building the relaxed consensus list.
    # If 0, run_daily uses a built-in default (500) for that second pass so the UI can always toggle.
    # Set > 0 to override that default (e.g. 250 or 1000).
    consensus_material_opposition_min_usd: float = float(
        (os.getenv("CONSENSUS_MATERIAL_OPPOSITION_MIN_USD", "0") or "0").strip() or "0"
    )
    # Same trader, same market: if non-target stake / dominant stake <= this ratio, treat as hedge.
    # Above this ratio, the secondary leg counts as meaningful dual exposure (breaks clean consensus).
    consensus_hedge_max_opposing_ratio: float = float(
        (os.getenv("CONSENSUS_HEDGE_MAX_OPPOSING_RATIO", "0.35") or "0.35").strip() or "0.35"
    )
    use_recent_activity_only: bool = os.getenv("USE_RECENT_ACTIVITY_ONLY", "false").lower() == "true"
    lookback_hours: int = int(os.getenv("LOOKBACK_HOURS", "24"))
    today_open_events_only: bool = os.getenv("TODAY_OPEN_EVENTS_ONLY", "true").lower() == "true"
    # IANA zone for which calendar day counts as "today" for open events (default US Eastern).
    event_day_timezone: str = os.getenv("EVENT_DAY_TIMEZONE", "America/New_York")


def get_settings() -> Settings:
    return Settings()

