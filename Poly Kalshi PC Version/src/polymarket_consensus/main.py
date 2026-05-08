from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .config import get_settings
from .consensus import build_consensus
from .discord_sync import sync_report_to_discord_safe
from .models import Position, Trader, utc_now_iso
from .polymarket_client import PolymarketClient

# Used for the second "relaxed" consensus pass when CONSENSUS_MATERIAL_OPPOSITION_MIN_USD is 0.
RELAXED_OPPOSITION_DEFAULT_USD = 500.0


def run() -> None:
    load_dotenv()
    settings = get_settings()
    client = PolymarketClient(settings)

    traders = client.get_top_traders()
    all_positions: list[Position] = []

    failed_traders: list[str] = []
    for trader in traders:
        try:
            if settings.use_recent_activity_only:
                all_positions.extend(client.get_user_recent_trades(trader.address, settings.lookback_hours))
            else:
                all_positions.extend(client.get_user_positions(trader.address))
        except Exception:
            failed_traders.append(trader.address)

    sports_positions: list[Position] = []
    skipped_non_sports = 0
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

    consensus = build_consensus(
        sports_positions,
        settings.min_positions_per_market,
        settings.strict_unanimous_only,
        material_opposition_min_usd=0.0,
        hedge_max_opposing_ratio=settings.consensus_hedge_max_opposing_ratio,
    )
    relaxed_threshold_usd = (
        settings.consensus_material_opposition_min_usd
        if settings.consensus_material_opposition_min_usd > 0
        else RELAXED_OPPOSITION_DEFAULT_USD
    )
    consensus_relaxed = build_consensus(
        sports_positions,
        settings.min_positions_per_market,
        settings.strict_unanimous_only,
        material_opposition_min_usd=relaxed_threshold_usd,
        hedge_max_opposing_ratio=settings.consensus_hedge_max_opposing_ratio,
    )

    sports_positions_today = _serialize_sports_positions_for_ui(traders, sports_positions)

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    payload = {
        "generated_at_utc": utc_now_iso(),
        "settings": asdict(settings),
        "top_traders_count": len(traders),
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
        "consensus_bets": [asdict(c) for c in consensus],
        "consensus_bets_relaxed": [asdict(c) for c in consensus_relaxed],
        "relaxed_opposition_threshold_usd": relaxed_threshold_usd,
        "sports_positions_today": sports_positions_today,
    }
    (output_dir / "daily_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _append_consensus_history_snapshot(output_dir, payload)
    (output_dir / "top_consensus_today.json").write_text(
        json.dumps([asdict(c) for c in consensus[:20]], indent=2),
        encoding="utf-8",
    )
    (output_dir / "top_consensus_today.md").write_text(
        _build_markdown_report(traders, consensus),
        encoding="utf-8",
    )

    print(f"Saved: {output_dir / 'daily_report.json'}")
    print(f"Saved: {output_dir / 'top_consensus_today.json'}")
    print(f"Saved: {output_dir / 'top_consensus_today.md'}")
    print(
        "Processed "
        f"traders={len(traders)} failed={len(failed_traders)} "
        f"positions={len(all_positions)} sports={len(sports_positions)} "
        f"consensus={len(consensus)}"
    )

    sync_report_to_discord_safe(payload)


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


def _build_markdown_report(traders: list[Trader], consensus: list) -> str:
    lines: list[str] = []
    lines.append("# Polymarket Sports Consensus Bets")
    lines.append("")
    lines.append(f"Generated at: {utc_now_iso()}")
    lines.append(f"Top traders scanned: {len(traders)}")
    lines.append("")
    lines.append("## Top Consensus (today)")
    lines.append("")

    if not consensus:
        lines.append("No overlapping positions found with current filters.")
        lines.append("")
        return "\n".join(lines)

    for idx, bet in enumerate(consensus[:20], start=1):
        lines.append(f"{idx}. **{bet.market_title}**")
        lines.append(f"   - Outcome: `{bet.outcome}`")
        lines.append(f"   - Traders: {bet.traders_count}")
        lines.append(f"   - Total Value: ${bet.total_value:,.2f}")
        lines.append(f"   - Total Size: {bet.total_size:,.2f}")
        lines.append(f"   - Avg Entry: {bet.weighted_avg_entry:.4f}")
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
        "consensus_bets": payload.get("consensus_bets", []),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line_obj, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    run()

