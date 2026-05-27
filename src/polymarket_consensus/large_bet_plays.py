"""Large qualifying bets from top traders (replaces legacy consensus table)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .models import Position


def _normalize_market_key(slug: str, title: str) -> str:
    slug_clean = (slug or "").strip().lower()
    if slug_clean:
        return slug_clean
    return " ".join((title or "").strip().lower().split())


def _normalize_outcome(outcome: str) -> str:
    return " ".join((outcome or "").strip().lower().split())


def _collapse_hedges_to_dominant_side(market_positions: list[Position]) -> list[Position]:
    """
    For each trader in a market, keep only their dominant side by current_value.

    This treats smaller opposite-side exposure as hedge and removes it from
    play qualification logic.
    """
    # First aggregate by (trader, outcome) so split fills on the same side are combined.
    by_trader_outcome: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "trader_address": "",
            "event_id": "",
            "market_slug": "",
            "market_title": "",
            "outcome": "",
            "current_value": 0.0,
            "size": 0.0,
            "avg_price_weighted_sum": 0.0,
            "avg_price_weight_total": 0.0,
        }
    )
    for p in market_positions:
        trader = p.trader_address.lower()
        outcome_key = _normalize_outcome(p.outcome)
        k = (trader, outcome_key)
        row = by_trader_outcome[k]
        row["trader_address"] = trader
        row["event_id"] = p.event_id
        row["market_slug"] = p.market_slug
        row["market_title"] = p.market_title
        row["outcome"] = p.outcome
        row["current_value"] += float(p.current_value or 0.0)
        row["size"] += float(p.size or 0.0)
        weight = float(p.size if p.size > 0 else p.current_value or 0.0)
        if weight > 0:
            row["avg_price_weighted_sum"] += float(p.average_price or 0.0) * weight
            row["avg_price_weight_total"] += weight

    # Then pick one dominant outcome per trader.
    by_trader: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (trader, _outcome_key), agg in by_trader_outcome.items():
        by_trader[trader].append(agg)

    collapsed: list[Position] = []
    for trader, rows in by_trader.items():
        dominant = max(
            rows,
            key=lambda r: (float(r["current_value"]), float(r["size"]), _normalize_outcome(str(r["outcome"]))),
        )
        wt = float(dominant["avg_price_weight_total"] or 0.0)
        avg_price = (float(dominant["avg_price_weighted_sum"]) / wt) if wt > 0 else 0.0
        collapsed.append(
            Position(
                trader_address=trader,
                event_id=str(dominant["event_id"]),
                market_slug=str(dominant["market_slug"]),
                market_title=str(dominant["market_title"]),
                outcome=str(dominant["outcome"]),
                size=float(dominant["size"]),
                current_value=float(dominant["current_value"]),
                average_price=float(avg_price),
                outcome_index=None,
                trade_timestamp=None,
            )
        )
    return collapsed


@dataclass(frozen=True)
class QualifyingPosition:
    trader_address: str
    market_slug: str
    market_title: str
    outcome: str
    outcome_key: str
    current_value: float
    size: float
    average_price: float


def _other_side_max_usd(
    by_outcome: dict[str, list[Position]],
    outcome_key: str,
) -> float:
    best = 0.0
    for ok, positions in by_outcome.items():
        if ok == outcome_key:
            continue
        for p in positions:
            if p.current_value > best:
                best = p.current_value
    return best


def _metric_amount(pos: Position, ratio_basis: str) -> float:
    """Metric used for the 2.5x comparison (USD vs share units)."""
    if ratio_basis == "shares":
        return float(pos.size or 0.0)
    return float(pos.current_value or 0.0)


def _other_side_max_metric(
    by_outcome: dict[str, list[Position]],
    outcome_key: str,
    ratio_basis: str,
) -> float:
    best = 0.0
    for ok, positions in by_outcome.items():
        if ok == outcome_key:
            continue
        for p in positions:
            m = _metric_amount(p, ratio_basis)
            if m > best:
                best = m
    return best


def _position_qualifies(
    pos: Position,
    other_side_max: float,
    min_usd: float,
    max_opposing_ratio: float,
    ratio_basis: str,
) -> bool:
    if pos.current_value < min_usd:
        return False
    # If the opposing side has no stake, the ratio check passes by definition.
    if other_side_max <= 0:
        return True
    this_metric = _metric_amount(pos, ratio_basis)
    # "Within 2.5x" means bounded both ways, not only an upper cap.
    # Example with ratio=2.5:
    # - passes: 20k vs 50k (50/20 = 2.5)
    # - fails: 41k vs 345k (345/41 > 2.5)
    lower_bound = other_side_max / max_opposing_ratio
    upper_bound = other_side_max * max_opposing_ratio
    return lower_bound <= this_metric <= upper_bound


def build_large_bet_plays(
    positions: list[Position],
    min_usd: float = 15_000.0,
    max_opposing_ratio: float = 2.5,
    ratio_basis: str = "usd",
) -> list[dict[str, Any]]:
    """
    One row per market with at least one qualifying top-trader position.

    Showcase side priority:
    1) More qualifying top bettors on that side.
    2) If tied, larger single qualifying bet on that side.
    3) If still tied, higher total qualifying stake.
    Consensus = no qualifying stake on any opposing outcome in the same market.
    """
    by_market: dict[str, list[Position]] = defaultdict(list)
    for pos in positions:
        by_market[_normalize_market_key(pos.market_slug, pos.market_title)].append(pos)

    plays: list[dict[str, Any]] = []

    for _market_key, market_positions in by_market.items():
        by_outcome: dict[str, list[Position]] = defaultdict(list)
        outcome_labels: dict[str, str] = {}
        dominant_positions = _collapse_hedges_to_dominant_side(market_positions)
        for p in dominant_positions:
            ok = _normalize_outcome(p.outcome)
            by_outcome[ok].append(p)
            if ok not in outcome_labels:
                outcome_labels[ok] = p.outcome

        qualifying_by_outcome: dict[str, list[QualifyingPosition]] = defaultdict(list)

        ratio_basis_norm = (ratio_basis or "usd").strip().lower()
        if ratio_basis_norm not in ("usd", "shares"):
            ratio_basis_norm = "usd"

        for outcome_key, outcome_positions in by_outcome.items():
            other_max = _other_side_max_metric(by_outcome, outcome_key, ratio_basis_norm)
            for p in outcome_positions:
                if not _position_qualifies(p, other_max, min_usd, max_opposing_ratio, ratio_basis_norm):
                    continue
                qualifying_by_outcome[outcome_key].append(
                    QualifyingPosition(
                        trader_address=p.trader_address.lower(),
                        market_slug=p.market_slug,
                        market_title=p.market_title,
                        outcome=p.outcome,
                        outcome_key=outcome_key,
                        current_value=p.current_value,
                        size=p.size,
                        average_price=p.average_price,
                    )
                )

        if not qualifying_by_outcome:
            continue

        def side_total(ok: str) -> float:
            qlist = qualifying_by_outcome.get(ok, [])
            if ratio_basis_norm == "shares":
                return sum(q.size for q in qlist)
            return sum(q.current_value for q in qlist)

        def side_count(ok: str) -> int:
            return len(qualifying_by_outcome.get(ok, []))

        def side_largest_bet(ok: str) -> float:
            qlist = qualifying_by_outcome.get(ok, [])
            if not qlist:
                return 0.0
            if ratio_basis_norm == "shares":
                return max(q.size for q in qlist)
            return max(q.current_value for q in qlist)

        showcased_key = max(
            qualifying_by_outcome.keys(),
            key=lambda ok: (side_count(ok), side_largest_bet(ok), side_total(ok), ok),
        )
        showcased_positions = qualifying_by_outcome[showcased_key]

        opposing: list[dict[str, Any]] = []
        for ok, qlist in qualifying_by_outcome.items():
            if ok == showcased_key:
                continue
            for q in qlist:
                opposing.append(
                    {
                        "trader_address": q.trader_address,
                        "outcome": q.outcome,
                        "current_value": round(q.current_value, 2),
                        "size": round(q.size, 4),
                        "average_price": round(q.average_price, 4),
                    }
                )

        small_opposing_interest: list[dict[str, Any]] = []
        # "Small opposing interest" = opposing-side top-trader positions that FAIL the same
        # qualification requirements (min-$ threshold AND the 2.5x ratio rule).
        # These do not count as qualifying opposed bets (so they do not make NON CONSENSUS).
        for ok, positions in by_outcome.items():
            if ok == showcased_key:
                continue
            other_max_for_side = _other_side_max_metric(by_outcome, ok, ratio_basis_norm)
            for p in positions:
                qualifies = _position_qualifies(
                    p,
                    other_max_for_side,
                    min_usd,
                    max_opposing_ratio,
                    ratio_basis_norm,
                )
                if qualifies:
                    continue
                if float(p.current_value or 0.0) <= 0:
                    continue
                small_opposing_interest.append(
                    {
                        "trader_address": p.trader_address.lower(),
                        "outcome": p.outcome,
                        "current_value": round(float(p.current_value or 0.0), 2),
                        "size": round(float(p.size or 0.0), 4),
                        "average_price": round(float(p.average_price or 0.0), 4),
                    }
                )

        small_opposing_interest.sort(key=lambda r: (-r["current_value"], r["trader_address"]))
        small_opposing_interest = small_opposing_interest[:10]

        supporting = [
            {
                "trader_address": q.trader_address,
                "outcome": q.outcome,
                "current_value": round(q.current_value, 2),
                "size": round(q.size, 4),
                "average_price": round(q.average_price, 4),
            }
            for q in showcased_positions
        ]
        supporting.sort(key=lambda r: (-r["current_value"], r["trader_address"]))

        showcased_value = sum(r["current_value"] for r in supporting)
        showcased_size = sum(r["size"] for r in supporting)
        weighted_entry = 0.0
        weight_total = 0.0
        for q in showcased_positions:
            w = q.size if q.size > 0 else q.current_value
            if w <= 0:
                continue
            weighted_entry += q.average_price * w
            weight_total += w
        if weight_total > 0:
            weighted_entry /= weight_total

        exemplar = market_positions[0]
        plays.append(
            {
                "market_slug": exemplar.market_slug,
                "market_title": exemplar.market_title,
                "outcome": outcome_labels.get(showcased_key, showcased_key),
                "outcome_key": showcased_key,
                "showcased_value": round(showcased_value, 2),
                "showcased_size": round(showcased_size, 4),
                "weighted_avg_entry": round(weighted_entry, 4),
                "traders_count": len(supporting),
                "unique_traders": sorted({r["trader_address"] for r in supporting}),
                "supporting_positions": supporting,
                "opposing_positions": opposing,
                "opposed_traders_count": len({r["trader_address"] for r in opposing}),
                "small_opposing_interest_positions": small_opposing_interest,
                "is_consensus": len(opposing) == 0,
            }
        )

    plays.sort(
        key=lambda row: (row["showcased_value"], row["traders_count"]),
        reverse=True,
    )
    return plays


def enrich_large_bet_plays(plays: list[dict], traders: list[dict]) -> list[dict]:
    addr_to_name = {
        str(t.get("address", "")).lower(): str(t.get("name", "")).strip() or "Unknown trader"
        for t in traders
        if str(t.get("address", "")).strip()
    }
    out: list[dict] = []
    for play in plays:
        row = dict(play)
        addrs = [str(a).lower() for a in row.get("unique_traders", [])]
        row["trader_names"] = [addr_to_name.get(a, a) for a in addrs]
        for key in ("supporting_positions", "opposing_positions", "small_opposing_interest_positions"):
            enriched: list[dict] = []
            for pos in row.get(key) or []:
                pd = dict(pos)
                addr = str(pd.get("trader_address", "")).lower()
                pd["trader_name"] = addr_to_name.get(addr, addr)
                enriched.append(pd)
            row[key] = enriched
        out.append(row)
    return out
