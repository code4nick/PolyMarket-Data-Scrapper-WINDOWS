from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .config import get_settings
from .discord_sync import sync_report_to_discord_safe
from .large_bet_plays import build_large_bet_plays, enrich_large_bet_plays
from .models import Position, Trader, utc_now_iso
from .polymarket_client import PolymarketClient


def run() -> None:
    run_started = perf_counter()
    load_dotenv()
    settings = get_settings()
    client = PolymarketClient(settings)

    t0 = perf_counter()
    top_traders = client.get_top_traders()
    t_top_traders = perf_counter() - t0
    traders = top_traders.traders
    all_positions: list[Position] = []

    t0 = perf_counter()
    failed_traders: list[str] = []

    def _fetch_positions_for_trader(trader: Trader) -> tuple[str, list[Position], bool]:
        # Separate client/session per worker to safely parallelize network I/O.
        worker = PolymarketClient(settings)
        try:
            if settings.use_recent_activity_only:
                rows = worker.get_user_recent_trades(trader.address, settings.lookback_hours)
            else:
                rows = worker.get_user_positions(trader.address)
            return trader.address, rows, False
        except Exception:
            return trader.address, [], True

    if traders:
        max_workers = min(12, len(traders))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_fetch_positions_for_trader, trader) for trader in traders]
            for future in as_completed(futures):
                address, rows, failed = future.result()
                if failed:
                    failed_traders.append(address)
                else:
                    all_positions.extend(rows)
    t_positions_fetch = perf_counter() - t0

    sports_positions: list[Position] = []
    skipped_non_sports = 0
    t0 = perf_counter()
    if settings.sports_only_positions:
        for pos in all_positions:
            try:
                if settings.today_open_events_only:
                    if client.is_sports_open_today_event(pos.event_id):
                        sports_positions.append(pos)
                    else:
                        skipped_non_sports += 1
                elif settings.use_recent_activity_only:
                    if client.is_sports_and_open_by_slug(pos.market_slug):
                        sports_positions.append(pos)
                    else:
                        skipped_non_sports += 1
                elif client.is_sports_event(pos.event_id):
                    sports_positions.append(pos)
                else:
                    skipped_non_sports += 1
            except Exception:
                skipped_non_sports += 1
    else:
        sports_positions = all_positions
    t_sports_filter = perf_counter() - t0

    t0 = perf_counter()
    large_bet_plays = build_large_bet_plays(
        sports_positions,
        min_usd=settings.large_bet_min_usd,
        max_opposing_ratio=settings.large_bet_max_opposing_ratio,
        ratio_basis=settings.large_bet_ratio_basis,
    )
    large_bet_plays_enriched = enrich_large_bet_plays(
        large_bet_plays,
        [asdict(t) for t in traders],
    )
    t_build_plays = perf_counter() - t0

    t0 = perf_counter()
    sports_positions_today = _serialize_sports_positions_for_ui(traders, sports_positions)

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    payload = {
        "generated_at_utc": utc_now_iso(),
        "settings": asdict(settings),
        "top_traders_count": len(traders),
        "leaderboard_inactive_skipped": top_traders.inactive_skipped,
        "failed_traders_count": len(failed_traders),
        "failed_traders": failed_traders,
        "positions_count": len(all_positions),
        "sports_positions_count": len(sports_positions),
        "skipped_non_sports_positions": skipped_non_sports,
        "mode": (
            "today_open_events"
            if settings.today_open_events_only
            else ("recent_activity" if settings.use_recent_activity_only else "positions_snapshot")
        ),
        "traders": [asdict(t) for t in traders],
        "large_bet_plays": large_bet_plays_enriched,
        "sports_positions_today": sports_positions_today,
    }
    (output_dir / "daily_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _append_consensus_history_snapshot(output_dir, payload)
    (output_dir / "top_consensus_today.json").write_text(
        json.dumps(large_bet_plays_enriched[:20], indent=2),
        encoding="utf-8",
    )
    (output_dir / "top_consensus_today.md").write_text(
        _build_markdown_report(traders, large_bet_plays_enriched, settings),
        encoding="utf-8",
    )
    t_write_outputs = perf_counter() - t0

    print(f"Saved: {output_dir / 'daily_report.json'}")
    print(f"Saved: {output_dir / 'top_consensus_today.json'}")
    print(f"Saved: {output_dir / 'top_consensus_today.md'}")
    print(
        "Processed "
        f"traders={len(traders)} failed={len(failed_traders)} "
        f"positions={len(all_positions)} sports={len(sports_positions)} "
        f"large_bet_plays={len(large_bet_plays_enriched)}"
    )

    t0 = perf_counter()
    sync_report_to_discord_safe(payload)
    t_discord = perf_counter() - t0
    t_total = perf_counter() - run_started
    print(
        "Timing(s): "
        f"top_traders={t_top_traders:.2f} "
        f"positions_fetch={t_positions_fetch:.2f} "
        f"sports_filter={t_sports_filter:.2f} "
        f"build_plays={t_build_plays:.2f} "
        f"write_outputs={t_write_outputs:.2f} "
        f"discord={t_discord:.2f} "
        f"total={t_total:.2f}"
    )


def _serialize_sports_positions_for_ui(traders: list[Trader], positions: list[Position]) -> list[dict[str, Any]]:
    names = {t.address.lower(): t.name for t in traders}
    rows: list[dict[str, Any]] = []
    for p in positions:
        addr = p.trader_address.lower()
        rows.append(
            {
                "trader_name": names.get(addr, addr),
                "trader_address": addr,
                "market_title": p.market_title,
                "market_slug": p.market_slug,
                "outcome": p.outcome,
                "size": p.size,
                "current_value": p.current_value,
                "average_price": p.average_price,
            }
        )
    rows.sort(key=lambda r: (str(r["market_title"]).lower(), str(r["trader_name"]).lower()))
    return rows


def _build_markdown_report(traders: list[Trader], plays: list[dict], settings: Any) -> str:
    lines: list[str] = []
    lines.append("# Polymarket Large Bet Plays")
    lines.append("")
    lines.append(f"Generated at: {utc_now_iso()}")
    lines.append(f"Top traders scanned: {len(traders)}")
    lines.append(
        f"Rules: position ≥ ${settings.large_bet_min_usd:,.0f}, "
        f"stake ≤ {settings.large_bet_max_opposing_ratio}× other side's largest top-trader bet"
    )
    lines.append("")
    lines.append("## Top plays (today)")
    lines.append("")

    if not plays:
        lines.append("No qualifying large bets found with current filters.")
        lines.append("")
        return "\n".join(lines)

    for idx, play in enumerate(plays[:20], start=1):
        status = "CONSENSUS" if play.get("is_consensus") else "NON CONSENSUS"
        lines.append(f"{idx}. **{play['market_title']}** ({status})")
        lines.append(f"   - Outcome: `{play['outcome']}`")
        lines.append(f"   - Traders: {play['traders_count']}")
        lines.append(f"   - Showcased value: ${play['showcased_value']:,.2f}")
        lines.append(f"   - Showcased size: {play['showcased_size']:,.2f}")
        lines.append(f"   - Avg Entry: {play['weighted_avg_entry']:.4f}")
        if play.get("opposing_positions"):
            lines.append("   - Opposing qualifying:")
            for opp in play["opposing_positions"]:
                name = opp.get("trader_name") or opp.get("trader_address", "")
                lines.append(
                    f"     - {name}: `{opp['outcome']}` ${opp['current_value']:,.2f}"
                )
        lines.append("")

    return "\n".join(lines)


def _append_consensus_history_snapshot(output_dir: Path, payload: dict) -> None:
    """Append one line per run for intraday history; file day matches EVENT_DAY_TIMEZONE (default Eastern)."""
    settings = payload.get("settings") or {}
    tz_name = str(settings.get("event_day_timezone") or "America/New_York")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    raw_ts = str(payload.get("generated_at_utc") or "").strip()
    try:
        dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        day = dt.astimezone(tz).date()
    except ValueError:
        day = datetime.now(tz=tz).date()
    path = output_dir / f"consensus_history_{day.isoformat()}.jsonl"
    traders_min = [
        {"address": str(t.get("address", "")).lower(), "name": str(t.get("name", "")).strip()}
        for t in payload.get("traders", [])
        if str(t.get("address", "")).strip()
    ]
    line_obj = {
        "generated_at_utc": payload.get("generated_at_utc"),
        "mode": payload.get("mode"),
        "top_traders_count": payload.get("top_traders_count"),
        "traders": traders_min,
        "large_bet_plays": payload.get("large_bet_plays", []),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line_obj, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    run()

