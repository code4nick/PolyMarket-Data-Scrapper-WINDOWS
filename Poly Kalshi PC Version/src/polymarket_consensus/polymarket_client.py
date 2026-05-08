from __future__ import annotations

import re
from typing import Any
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

import requests

from .config import Settings
from .models import Position, Trader


class PolymarketClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        # Ignore system proxy env vars; direct API calls are more reliable for this script.
        self.session.trust_env = False
        self._event_sports_cache: dict[str, bool] = {}
        self._event_meta_cache: dict[str, dict[str, Any]] = {}
        self._market_meta_cache: dict[str, dict[str, Any]] = {}

    def _get_json(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            f"{base_url.rstrip('/')}/{path.lstrip('/')}",
            params=params or {},
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_top_traders(self) -> list[Trader]:
        payload = self._get_json(
            self.settings.data_api_base,
            "/v1/leaderboard",
            params={
                "category": self.settings.leaderboard_category,
                "timePeriod": self.settings.leaderboard_time_period,
                "orderBy": self.settings.leaderboard_order_by,
                "limit": self.settings.top_n_traders,
                "offset": 0,
            },
        )
        traders_data = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))

        traders: list[Trader] = []
        for row in traders_data:
            address = str(
                row.get("proxyWallet")
                or row.get("user")
                or row.get("address")
                or row.get("walletAddress")
                or ""
            ).lower()
            if not address:
                continue
            traders.append(
                Trader(
                    address=address,
                    name=str(row.get("userName") or row.get("name") or address[:8]),
                    pnl=_to_float(row.get("pnl") or row.get("profit")),
                    volume=_to_float(row.get("volume") or row.get("vol")),
                    win_rate=_to_float(row.get("winRate") or row.get("win_rate")),
                )
            )
        return traders

    def get_user_positions(self, address: str) -> list[Position]:
        payload = self._get_json(
            self.settings.data_api_base,
            "/positions",
            params={"user": address, "sizeThreshold": 1},
        )
        positions_data = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
        positions: list[Position] = []

        for row in positions_data:
            title = str(row.get("title") or row.get("marketTitle") or row.get("question") or "")
            slug = str(row.get("slug") or row.get("marketSlug") or row.get("conditionId") or title)
            outcome = str(row.get("outcome") or row.get("tokenName") or row.get("side") or "").strip()
            size = _to_float(row.get("size") or row.get("amount") or row.get("shares"))
            value = _to_float(row.get("currentValue") or row.get("value") or row.get("usdValue"))
            avg_price = _to_float(row.get("avgPrice") or row.get("averagePrice") or row.get("entryPrice"))
            outcome_index = row.get("outcomeIndex")
            if outcome_index is not None:
                try:
                    outcome_index = int(outcome_index)
                except (TypeError, ValueError):
                    outcome_index = None

            if not title or not outcome:
                continue
            if size <= 0 and value <= 0:
                continue

            positions.append(
                Position(
                    trader_address=address.lower(),
                    event_id=str(row.get("eventId") or ""),
                    market_slug=slug,
                    market_title=title,
                    outcome=outcome,
                    size=size,
                    current_value=value,
                    average_price=avg_price,
                    outcome_index=outcome_index,
                    trade_timestamp=None,
                )
            )
        return positions

    def get_user_recent_trades(self, address: str, lookback_hours: int) -> list[Position]:
        cutoff_ts = int(datetime.now(tz=timezone.utc).timestamp()) - (lookback_hours * 3600)
        results: list[Position] = []
        offset = 0
        limit = 500

        while True:
            try:
                payload = self._get_json(
                    self.settings.data_api_base,
                    "/activity",
                    params={"user": address, "limit": limit, "offset": offset},
                )
            except requests.RequestException:
                # Keep partial data for this trader if one page fails.
                break
            rows = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
            if not rows:
                break

            should_continue = False
            for row in rows:
                ts = _to_int(row.get("timestamp"))
                if ts and ts < cutoff_ts:
                    continue
                if str(row.get("type") or "").upper() != "TRADE":
                    continue
                if str(row.get("side") or "").upper() != "BUY":
                    continue

                should_continue = True
                title = str(row.get("title") or "")
                slug = str(row.get("slug") or row.get("eventSlug") or row.get("conditionId") or title)
                outcome = str(row.get("outcome") or "").strip()
                size = _to_float(row.get("size"))
                usdc_size = _to_float(row.get("usdcSize"))
                price = _to_float(row.get("price"))

                if not title or not outcome:
                    continue
                if size <= 0 and usdc_size <= 0:
                    continue

                results.append(
                    Position(
                        trader_address=address.lower(),
                        event_id="",
                        market_slug=slug,
                        market_title=title,
                        outcome=outcome,
                        size=size,
                        current_value=usdc_size,
                        average_price=price,
                        outcome_index=_to_optional_int(row.get("outcomeIndex")),
                        trade_timestamp=ts if ts > 0 else None,
                    )
                )

            if len(rows) < limit:
                break
            if not should_continue:
                break
            offset += limit

        return results

    def is_sports_event(self, event_id: str) -> bool:
        event_id = (event_id or "").strip()
        if not event_id:
            return False
        if event_id in self._event_sports_cache:
            return self._event_sports_cache[event_id]

        payload = self._get_json(self.settings.gamma_api_base, f"/events/{event_id}")
        tags = payload.get("tags") if isinstance(payload, dict) else []
        is_sports = False
        if isinstance(tags, list):
            for tag in tags:
                slug = str((tag or {}).get("slug") or "").strip().lower()
                label = str((tag or {}).get("label") or "").strip().lower()
                if slug == "sports" or label == "sports":
                    is_sports = True
                    break
        self._event_sports_cache[event_id] = is_sports
        return is_sports

    def is_sports_open_today_event(self, event_id: str) -> bool:
        event = self.get_event_by_id(event_id)
        if not event:
            return False
        if not bool(event.get("active")) or bool(event.get("closed")):
            return False
        if not self.is_sports_event(event_id):
            return False
        event_day = _event_calendar_date_in_tz(event, self.settings.event_day_timezone)
        if event_day is None:
            return False
        try:
            tz = ZoneInfo(self.settings.event_day_timezone)
        except Exception:
            tz = timezone.utc
        today_local = datetime.now(tz=tz).date()
        return event_day == today_local

    def get_event_by_id(self, event_id: str) -> dict[str, Any] | None:
        key = (event_id or "").strip()
        if not key:
            return None
        if key in self._event_meta_cache:
            cached = self._event_meta_cache[key]
            return cached or None
        payload = self._get_json(self.settings.gamma_api_base, f"/events/{key}")
        if isinstance(payload, dict):
            self._event_meta_cache[key] = payload
            return payload
        self._event_meta_cache[key] = {}
        return None

    def get_event_by_slug(self, slug: str) -> dict[str, Any] | None:
        key = (slug or "").strip().lower()
        if not key:
            return None
        if key in self._event_meta_cache:
            return self._event_meta_cache[key]
        payload = self._get_json(self.settings.gamma_api_base, "/events", params={"slug": key, "limit": 1})
        if isinstance(payload, list) and payload:
            self._event_meta_cache[key] = payload[0]
            return payload[0]
        self._event_meta_cache[key] = {}
        return None

    def is_sports_and_open_by_slug(self, slug: str) -> bool:
        market = self.get_market_by_slug(slug)
        if not market:
            return False
        is_active = bool(market.get("active"))
        is_closed = bool(market.get("closed"))
        if not is_active or is_closed:
            return False
        events = market.get("events")
        event_id = ""
        if isinstance(events, list) and events:
            event_id = str((events[0] or {}).get("id") or "")
        if not event_id:
            return False
        return self.is_sports_event(event_id)

    def get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        key = (slug or "").strip().lower()
        if not key:
            return None
        if key in self._market_meta_cache:
            cached = self._market_meta_cache[key]
            return cached or None
        payload = self._get_json(self.settings.gamma_api_base, "/markets", params={"slug": key, "limit": 1})
        if isinstance(payload, list) and payload:
            self._market_meta_cache[key] = payload[0]
            return payload[0]
        self._market_meta_cache[key] = {}
        return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_optional_int(value: Any) -> int | None:
    i = _to_int(value)
    return i if i != 0 else None


# Gamma often returns calendar game day as date-only "YYYY-MM-DD". That must not be parsed as
# UTC midnight (which shifts the Eastern calendar day and lets "tomorrow" games match "today").
_DATE_ONLY_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _event_calendar_date_in_tz(event: dict[str, Any], tz_name: str) -> date | None:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    for field in ("eventDate", "startDate", "endDate"):
        raw = str(event.get(field) or "").strip()
        if not raw:
            continue
        if _DATE_ONLY_ISO.fullmatch(raw):
            try:
                return date.fromisoformat(raw)
            except ValueError:
                continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(tz).date()
        except ValueError:
            continue
    return None

