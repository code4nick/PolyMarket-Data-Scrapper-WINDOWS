from __future__ import annotations

from collections import defaultdict

from .models import ConsensusBet, Position


def _group_positions_for_consensus(
    positions: list[Position],
) -> tuple[dict[tuple[str, str], list[Position]], dict[str, dict[str, set[str]]]]:
    grouped: dict[tuple[str, str], list[Position]] = defaultdict(list)
    market_outcome_to_traders: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for pos in positions:
        market_key = _normalize_market_key(pos.market_slug, pos.market_title)
        outcome_key = _normalize_outcome(pos.outcome)
        key = (market_key, outcome_key)
        grouped[key].append(pos)
        market_outcome_to_traders[market_key][outcome_key].add(pos.trader_address)
    return grouped, market_outcome_to_traders


def _consensus_bet_from_group(
    market_key: str,
    outcome_key: str,
    group: list[Position],
    opposed_count: int,
) -> ConsensusBet:
    unique_traders = sorted({p.trader_address for p in group})
    supporting_count = len(unique_traders)
    is_unanimous = opposed_count == 0
    total_size = sum(p.size for p in group)
    total_value = sum(p.current_value for p in group)
    weighted_avg_entry = _weighted_avg_entry(group)
    score = supporting_count * max(total_value, 1.0)
    exemplar = group[0]
    return ConsensusBet(
        market_slug=market_key,
        market_title=exemplar.market_title,
        outcome=outcome_key,
        traders_count=supporting_count,
        opposed_traders_count=opposed_count,
        unique_traders=unique_traders,
        total_size=round(total_size, 4),
        total_value=round(total_value, 4),
        weighted_avg_entry=round(weighted_avg_entry, 4),
        score=round(score, 4),
        is_unanimous=is_unanimous,
    )


def _market_trader_outcome_notional_usd(
    positions: list[Position],
    market_key: str,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for pos in positions:
        mk = _normalize_market_key(pos.market_slug, pos.market_title)
        if mk != market_key:
            continue
        trader = pos.trader_address.lower()
        outcome = _normalize_outcome(pos.outcome)
        out[trader][outcome] += pos.current_value
    return out


def _trader_opposes_candidate_row(
    oc_vals: dict[str, float],
    target_outcome: str,
    hedge_max_opposing_ratio: float,
) -> bool:
    """
    Whether this trader counts as opposing consensus on ``target_outcome``.

    - If their dominant outcome is not ``target_outcome``, they oppose (directionally elsewhere).
    - If dominant == ``target_outcome``, they oppose only when non-target stake / dominant stake
      exceeds ``hedge_max_opposing_ratio`` (above that, the other leg is not treated as a hedge).
    """
    if not oc_vals:
        return False
    dominant_outcome, dominant_usd = max(oc_vals.items(), key=lambda kv: (kv[1], kv[0]))
    usd_others_vs_target = sum(v for k, v in oc_vals.items() if k != target_outcome)

    if dominant_outcome != target_outcome:
        return True

    if usd_others_vs_target <= 0 or dominant_usd <= 0:
        return False
    if hedge_max_opposing_ratio < 0:
        return True
    return (usd_others_vs_target / dominant_usd) > hedge_max_opposing_ratio


def _count_opposed_traders_hybrid(
    positions: list[Position],
    market_key: str,
    target_outcome: str,
    hedge_max_opposing_ratio: float,
    min_other_side_usd: float | None,
) -> int:
    """
    Count traders who oppose ``target_outcome``.

    ``min_other_side_usd`` when set (relaxed mode): require USD on outcomes other than
    ``target_outcome`` to reach this floor. Strict mode passes ``None``.
    """
    market_trader_outcomes = _market_trader_outcome_notional_usd(positions, market_key)
    opposed_count = 0
    for oc_vals in market_trader_outcomes.values():
        if not _trader_opposes_candidate_row(oc_vals, target_outcome, hedge_max_opposing_ratio):
            continue
        if min_other_side_usd is not None and min_other_side_usd > 0:
            other_usd = sum(v for k, v in oc_vals.items() if k != target_outcome)
            if other_usd < min_other_side_usd:
                continue
        opposed_count += 1
    return opposed_count


def build_consensus(
    positions: list[Position],
    min_positions_per_market: int,
    strict_unanimous_only: bool,
    material_opposition_min_usd: float = 0.0,
    hedge_max_opposing_ratio: float = 0.35,
) -> list[ConsensusBet]:
    grouped, _market_outcome_to_traders_raw = _group_positions_for_consensus(positions)

    consensus_bets: list[ConsensusBet] = []
    for (market_key, outcome_key), group in grouped.items():
        unique_traders = sorted({p.trader_address for p in group})
        supporting_count = len(unique_traders)
        if supporting_count < min_positions_per_market:
            continue
        min_other_side_usd = (
            material_opposition_min_usd if material_opposition_min_usd > 0 else None
        )
        opposed_count = _count_opposed_traders_hybrid(
            positions,
            market_key,
            outcome_key,
            hedge_max_opposing_ratio,
            min_other_side_usd,
        )
        is_unanimous = opposed_count == 0
        if strict_unanimous_only and not is_unanimous:
            continue

        consensus_bets.append(
            _consensus_bet_from_group(market_key, outcome_key, group, opposed_count)
        )

    return sorted(
        consensus_bets,
        key=lambda x: (x.traders_count, x.total_value, x.total_size, x.score),
        reverse=True,
    )


def _normalize_market_key(slug: str, title: str) -> str:
    slug_clean = (slug or "").strip().lower()
    if slug_clean:
        return slug_clean
    return " ".join((title or "").strip().lower().split())


def _normalize_outcome(outcome: str) -> str:
    return " ".join((outcome or "").strip().lower().split())


def _weighted_avg_entry(group: list[Position]) -> float:
    weighted_sum = 0.0
    weight_total = 0.0
    for p in group:
        weight = p.size if p.size > 0 else p.current_value
        if weight <= 0:
            continue
        weighted_sum += p.average_price * weight
        weight_total += weight
    if weight_total == 0:
        return 0.0
    return weighted_sum / weight_total

