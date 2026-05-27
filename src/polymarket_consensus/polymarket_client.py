from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

from .config import Settings
from .models import Position, TopTradersResult, Trader

# Hard cap on leaderboard depth (candidate pool for active-trader backfill).
MAX_LEADERBOARD_FETCH = 60
EVENT_CACHE_TTL_SECONDS = 15 * 60
EVENT_CACHE_FILE = Path(__file__).resolve().parents[2] / "outputs" / ".event_meta_cache.json"
ACTIVITY_CACHE_TTL_SECONDS = 5 * 60
ACTIVITY_CACHE_FILE = Path(__file__).resolve().parents[2] / "outputs" / ".activity_cache.json"


class PolymarketClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        # Ignore system proxy env vars; direct API calls are more reliable for this script.
        self.session.trust_env = False
        self._event_sports_cache: dict[str, bool] = {}
        self._event_meta_cache: dict[str, dict[str, Any]] = {}
        self._event_meta_cache_ts: dict[str, float] = {}
        self._market_meta_cache: dict[str, dict[str, Any]] = {}
        self._activity_cache: dict[str, dict[str, Any]] = {}
        self._load_persistent_event_cache()
        self._load_persistent_activity_cache()

    def _load_persistent_event_cache(self) -> None:
        try:
            if not EVENT_CACHE_FILE.exists():
                return
            payload = json.loads(EVENT_CACHE_FILE.read_text(encoding="utf-8"))
            events = payload.get("events")
            if not isinstance(events, dict):
                return
            now = time.time()
            for event_id, row in events.items():
                if not isinstance(row, dict):
                    continue
                meta = row.get("payload")
                fetched_at = float(row.get("fetched_at", 0) or 0)
                if not isinstance(meta, dict) or fetched_at <= 0:
                    continue
                # Keep only reasonably fresh cache rows in memory.
                if (now - fetched_at) > EVENT_CACHE_TTL_SECONDS:
                    continue
                key = str(event_id).strip()
                if not key:
                    continue
                self._event_meta_cache[key] = meta
                self._event_meta_cache_ts[key] = fetched_at
        except Exception:
            # Cache is an optimization only; ignore corrupt files.
            return

    def _save_persistent_event_cache(self) -> None:
        try:
            EVENT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            events: dict[str, dict[str, Any]] = {}
            now = time.time()
            for event_id, meta in self._event_meta_cache.items():
                fetched_at = float(self._event_meta_cache_ts.get(event_id, 0) or 0)
                if not isinstance(meta, dict) or fetched_at <= 0:
                    continue
                if (now - fetched_at) > EVENT_CACHE_TTL_SECONDS:
                    continue
                events[event_id] = {"fetched_at": fetched_at, "payload": meta}
            EVENT_CACHE_FILE.write_text(
                json.dumps({"updated_at": now, "events": events}, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception:
            return

    def _load_persistent_activity_cache(self) -> None:
        try:
            if not ACTIVITY_CACHE_FILE.exists():
                return
            payload = json.loads(ACTIVITY_CACHE_FILE.read_text(encoding="utf-8"))
            rows = payload.get("traders")
            if not isinstance(rows, dict):
                return
            now = time.time()
            for address, row in rows.items():
                if not isinstance(row, dict):
                    continue
                checked_at = float(row.get("checked_at", 0) or 0)
                if checked_at <= 0:
                    continue
                if (now - checked_at) > ACTIVITY_CACHE_TTL_SECONDS:
                    continue
                key = str(address).strip().lower()
                if not key:
                    continue
                self._activity_cache[key] = {
                    "is_active": bool(row.get("is_active", False)),
                    "checked_at": checked_at,
                    "lookback_days": int(row.get("lookback_days", 0) or 0),
                }
        except Exception:
            return

    def _save_persistent_activity_cache(self) -> None:
        try:
            ACTIVITY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            rows: dict[str, dict[str, Any]] = {}
            for address, row in self._activity_cache.items():
                checked_at = float(row.get("checked_at", 0) or 0)
                if checked_at <= 0:
                    continue
                if (now - checked_at) > ACTIVITY_CACHE_TTL_SECONDS:
                    continue
                rows[address] = {
                    "is_active": bool(row.get("is_active", False)),
                    "checked_at": checked_at,
                    "lookback_days": int(row.get("lookback_days", 0) or 0),
                }
            ACTIVITY_CACHE_FILE.write_text(
                json.dumps({"updated_at": now, "traders": rows}, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception:
            return

    def _get_json(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            f"{base_url.rstrip('/')}/{path.lstrip('/')}",
            params=params or {},
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_top_traders(self) -> TopTradersResult:
        if not self.settings.require_active_leaderboard_traders:
            fetch_limit = self.settings.top_n_traders
        else:
            fetch_limit = max(
                self.settings.top_n_traders,
                min(self.settings.leaderboard_fetch_limit, MAX_LEADERBOARD_FETCH),
            )

        payload = self._get_json(
            self.settings.data_api_base,
            "/v1/leaderboard",
            params={
                "category": self.settings.leaderboard_category,
                "timePeriod": self.settings.leaderboard_time_period,
                "orderBy": self.settings.leaderboard_order_by,
                "limit": fetch_limit,
                "offset": 0,
            },
        )
        traders_data = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))

        ranked: list[Trader] = []
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
            ranked.append(
                Trader(
                    address=address,
                    name=str(row.get("userName") or row.get("name") or address[:8]),
                    pnl=_to_float(row.get("pnl") or row.get("profit")),
                    volume=_to_float(row.get("volume") or row.get("vol")),
                    win_rate=_to_float(row.get("winRate") or row.get("win_rate")),
                )
            )

        if not self.settings.require_active_leaderboard_traders:
            return TopTradersResult(traders=ranked[: self.settings.top_n_traders], inactive_skipped=[])

        selected: list[Trader] = []
        skipped: list[dict[str, Any]] = []
        since_ts = int(datetime.now(tz=timezone.utc).timestamp()) - (
            self.settings.leaderboard_active_lookback_days * 86400
        )

        lookback_days = int(self.settings.leaderboard_active_lookback_days)
        now = time.time()

        def _cache_get(address: str) -> bool | None:
            row = self._activity_cache.get(address.lower())
            if not row:
                return None
            checked_at = float(row.get("checked_at", 0) or 0)
            if checked_at <= 0 or (now - checked_at) > ACTIVITY_CACHE_TTL_SECONDS:
                return None
            if int(row.get("lookback_days", 0) or 0) != lookback_days:
                return None
            return bool(row.get("is_active", False))

        def _cache_put(address: str, is_active: bool) -> None:
            self._activity_cache[address.lower()] = {
                "is_active": bool(is_active),
                "checked_at": time.time(),
                "lookback_days": lookback_days,
            }

        def _check_active(address: str) -> bool:
            # Use a separate client/session per worker for safe concurrent HTTP calls.
            worker = PolymarketClient(self.settings)
            try:
                return worker._trader_has_trade_since(address, since_ts)
            except requests.RequestException:
                # Preserve prior behavior: transient errors count as active.
                return True

        active_by_address: dict[str, bool] = {}
        pending: list[str] = []
        for t in ranked:
            cached = _cache_get(t.address)
            if cached is None:
                pending.append(t.address)
            else:
                active_by_address[t.address] = cached

        if pending:
            max_workers = min(12, len(pending))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_check_active, address): address for address in pending}
                for future in as_completed(futures):
                    addr = futures[future]
                    try:
                        is_active = future.result()
                        active_by_address[addr] = is_active
                        _cache_put(addr, is_active)
                    except Exception:
                        # Preserve prior behavior: transient worker errors count as active.
                        active_by_address[addr] = True
                        _cache_put(addr, True)

        self._save_persistent_activity_cache()

        for idx, trader in enumerate(ranked, start=1):
            if len(selected) >= self.settings.top_n_traders:
                break
            active = active_by_address.get(trader.address, True)
            if active:
                selected.append(trader)
            else:
                skipped.append(
                    {
                        "leaderboard_rank": idx,
                        "address": trader.address,
                        "name": trader.name,
                        "pnl": trader.pnl,
                    }
                )

        return TopTradersResult(traders=selected, inactive_skipped=skipped)

    def _trader_has_trade_since(self, address: str, since_ts: int) -> bool:
        """True if any TRADE activity exists with timestamp >= since_ts (bounded scan of /activity)."""
        offset = 0
        limit = 100
        max_pages = 8

        for _ in range(max_pages):
            payload = self._get_json(
                self.settings.data_api_base,
                "/activity",
                params={"user": address, "limit": limit, "offset": offset},
            )
            rows = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
            if not rows:
                return False

            for row in rows:
                ts = _to_int(row.get("timestamp"))
                if str(row.get("type") or "").upper() != "TRADE":
                    continue
                if ts and ts >= since_ts:
                    return True

            if len(rows) < limit:
                return False
            offset += limit

        return False

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
        now = time.time()
        cached = self._event_meta_cache.get(key)
        cached_ts = float(self._event_meta_cache_ts.get(key, 0) or 0)
        if cached and cached_ts > 0 and (now - cached_ts) <= EVENT_CACHE_TTL_SECONDS:
            return cached
        try:
            payload = self._get_json(self.settings.gamma_api_base, f"/events/{key}")
            if isinstance(payload, dict):
                self._event_meta_cache[key] = payload
                self._event_meta_cache_ts[key] = now
                self._save_persistent_event_cache()
                return payload
        except requests.RequestException:
            # If refresh fails, fall back to stale cache rather than hard-failing.
            if isinstance(cached, dict) and cached:
                return cached
            raise
        self._event_meta_cache[key] = {}
        self._event_meta_cache_ts[key] = now
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

