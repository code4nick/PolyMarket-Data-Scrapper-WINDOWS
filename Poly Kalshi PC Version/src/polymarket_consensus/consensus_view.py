"""Shared logic for the consensus table (matches UI: filter OFF, before Show all)."""

from __future__ import annotations


def address_to_name_map(traders: list[dict]) -> dict[str, str]:
    return {
        str(t.get("address", "")).lower(): str(t.get("name", "")).strip() or "Unknown trader"
        for t in traders
        if str(t.get("address", "")).strip()
    }


def consensus_row_key(bet: dict) -> tuple[str, str]:
    return (str(bet.get("market_slug", "")).lower(), str(bet.get("outcome", "")).lower())


def enrich_bets(bets: list[dict], traders: list[dict]) -> list[dict]:
    addr_to_name = address_to_name_map(traders)
    out: list[dict] = []
    for bet in bets:
        bd = dict(bet)
        addrs = [str(a).lower() for a in bd.get("unique_traders", [])]
        bd["trader_names"] = [addr_to_name.get(a, a) for a in addrs]
        out.append(bd)
    return out


def build_consensus_filter_off_lists(report: dict) -> tuple[list[dict], list[dict]]:
    """
    Same rows as the dashboard when Consensus filter is OFF and Show all is collapsed:
    primary block + relaxed-only extras (UI caps).
    """
    traders = report.get("traders", [])
    consensus = report.get("consensus_bets", [])
    strict_top: list[dict] = []
    for bet in consensus[:20]:
        bet_dict = dict(bet)
        trader_addresses = [str(addr).lower() for addr in bet_dict.get("unique_traders", [])]
        addr_map = address_to_name_map(traders)
        bet_dict["trader_names"] = [addr_map.get(addr, addr) for addr in trader_addresses]
        strict_top.append(bet_dict)
    relaxed_raw = report.get("consensus_bets_relaxed") or []
    relaxed_all = enrich_bets(relaxed_raw, traders)
    if strict_top:
        top_20 = strict_top
        base_keys = {consensus_row_key(b) for b in top_20}
        bets_relaxed_extra: list[dict] = []
        for b in relaxed_all:
            if consensus_row_key(b) not in base_keys:
                bets_relaxed_extra.append(b)
            if len(bets_relaxed_extra) >= 40:
                break
    else:
        top_20 = relaxed_all[:20]
        base_keys = {consensus_row_key(b) for b in top_20}
        bets_relaxed_extra = []
        for b in relaxed_all[20:]:
            if consensus_row_key(b) not in base_keys:
                bets_relaxed_extra.append(b)
            if len(bets_relaxed_extra) >= 40:
                break
    return top_20, bets_relaxed_extra


def status_label_for_row(bet: dict, relaxed_only_row: bool) -> str:
    if relaxed_only_row:
        return "RELAXED"
    if bet.get("is_unanimous"):
        return "UNANIMOUS"
    return "CONTESTED"
