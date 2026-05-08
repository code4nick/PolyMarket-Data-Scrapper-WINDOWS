from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Trader:
    address: str
    name: str
    pnl: float
    volume: float
    win_rate: float


@dataclass(frozen=True)
class Position:
    trader_address: str
    event_id: str
    market_slug: str
    market_title: str
    outcome: str
    size: float
    current_value: float
    average_price: float
    outcome_index: int | None
    trade_timestamp: int | None = None


@dataclass(frozen=True)
class ConsensusBet:
    market_slug: str
    market_title: str
    outcome: str
    traders_count: int
    opposed_traders_count: int
    unique_traders: list[str]
    total_size: float
    total_value: float
    weighted_avg_entry: float
    score: float
    is_unanimous: bool


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

