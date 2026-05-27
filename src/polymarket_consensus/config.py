from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_api_base: str = os.getenv("POLY_DATA_API_BASE", "https://data-api.polymarket.com")
    gamma_api_base: str = os.getenv("POLY_GAMMA_API_BASE", "https://gamma-api.polymarket.com")
    top_n_traders: int = int(os.getenv("TOP_N_TRADERS", "20"))
    # When true: walk the all-time leaderboard in order and skip inactive wallets until
    # `top_n_traders` active ones are collected (requires fetching a deeper leaderboard slice).
    require_active_leaderboard_traders: bool = (
        os.getenv("REQUIRE_ACTIVE_LEADERBOARD_TRADERS", "true").lower() == "true"
    )
    # A wallet counts as active if it has at least one on-chain TRADE activity row within this window.
    leaderboard_active_lookback_days: int = int(os.getenv("LEADERBOARD_ACTIVE_LOOKBACK_DAYS", "30"))
    # Ranked leaderboard rows to pull before active filter (capped at 60 in the client; must be >= top_n).
    leaderboard_fetch_limit: int = int(os.getenv("LEADERBOARD_FETCH_LIMIT", "60"))
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
    # Large-bet plays table: min position value (USD) and max ratio vs other side's largest stake.
    large_bet_min_usd: float = float((os.getenv("LARGE_BET_MIN_USD", "15000") or "15000").strip() or "15000")
    large_bet_max_opposing_ratio: float = float(
        (os.getenv("LARGE_BET_MAX_OPPOSING_RATIO", "2.5") or "2.5").strip() or "2.5"
    )
    # How to apply the 2.5x ratio rule: compare opposing-side by USD value or by share units.
    # This impacts only the ratio comparison, not the min-$ threshold.
    large_bet_ratio_basis: str = (os.getenv("LARGE_BET_RATIO_BASIS", "usd") or "usd").strip().lower()


def get_settings() -> Settings:
    return Settings()

