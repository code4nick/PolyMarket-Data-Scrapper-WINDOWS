"""Post large bet plays via Discord webhook."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

_WEBHOOK_TIMEOUT = 25
_CONTENT_CHUNK = 1900
_ROW_KEY_SEP = "\x1f"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _seen_keys_path() -> Path:
    out = _project_root() / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    return out / ".discord_consensus_seen_keys.json"


def _play_row_key(play: dict[str, Any]) -> str:
    slug = str(play.get("market_slug", "")).lower()
    outcome = str(play.get("outcome_key") or play.get("outcome", "")).lower()
    return f"{slug}{_ROW_KEY_SEP}{outcome}"


def _keys_from_plays(plays: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(_play_row_key(p) for p in plays)


def _load_seen_keys(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = data.get("row_keys")
        if isinstance(keys, list):
            return frozenset(str(k) for k in keys)
    except (json.JSONDecodeError, OSError):
        pass
    return frozenset()


def _save_seen_keys(path: Path, keys: frozenset[str]) -> None:
    obj = {"row_keys": sorted(keys)}
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def sync_report_to_discord_safe(report: dict[str, Any]) -> None:
    url = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
    if not url:
        return
    plays = report.get("large_bet_plays") or []
    path = _seen_keys_path()
    prev_keys = _load_seen_keys(path)
    current_keys = _keys_from_plays(plays)
    new_keys = current_keys - prev_keys
    if not new_keys:
        _save_seen_keys(path, current_keys)
        return
    try:
        _send_plays_webhook(url, report, plays, new_keys)
    except Exception as exc:
        print(f"Discord webhook failed: {exc}")
        return
    _save_seen_keys(path, current_keys)


def _new_plays_in_order(
    plays: list[dict[str, Any]],
    new_keys: frozenset[str],
) -> list[dict[str, Any]]:
    return [p for p in plays if _play_row_key(p) in new_keys]


def _send_plays_webhook(
    url: str,
    report: dict[str, Any],
    plays: list[dict[str, Any]],
    new_keys: frozenset[str],
) -> None:
    top_n = int(report.get("top_traders_count") or 0)
    settings = report.get("settings") or {}
    tz_name = str(settings.get("event_day_timezone") or "America/New_York")
    new_row_count = len(new_keys)
    entries = _new_plays_in_order(plays, new_keys)

    header = (
        "**Polymarket large bet plays** — *new rows only*\n"
        f"**{new_row_count} new** row(s) · "
        f"Generated (UTC): `{report.get('generated_at_utc') or '—'}` · `{tz_name}` · "
        f"mode `{report.get('mode') or '—'}` · board total **{len(plays)}** rows"
    )

    table_lines = _build_ascii_table_plays(entries, top_n)
    if not table_lines:
        _post(url, {"content": (header + "\n_No qualifying plays this run._")[:1999]})
        return

    chunks = _chunk_lines_for_codeblock(table_lines, _CONTENT_CHUNK)

    def fenced(body: str) -> str:
        return f"```{body}```"

    messages: list[str] = []
    first_try = f"{header}\n{fenced(chunks[0])}"
    if len(first_try) <= 2000:
        messages.append(first_try)
        messages.extend(fenced(c) for c in chunks[1:])
    else:
        messages.append(header[:1999])
        messages.extend(fenced(c) for c in chunks)

    total = len(messages)
    for i, msg in enumerate(messages):
        if i:
            time.sleep(0.4)
        if total > 1 and i and msg.startswith("```"):
            msg = f"_(continued {i + 1}/{total})_\n{msg}"
        if len(msg) > 2000:
            msg = msg[:1997] + "…"
        _post(url, {"content": msg})


def _post(url: str, payload: dict[str, Any]) -> None:
    r = requests.post(url, json=payload, timeout=_WEBHOOK_TIMEOUT)
    r.raise_for_status()


def _truncate(s: str, max_len: int) -> str:
    one_line = " ".join(str(s).split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 1] + "…"


def _play_row_cells(play: dict[str, Any], rank: int, top_n: int) -> tuple[str, ...]:
    slug = str(play.get("market_slug") or "")
    url = f"https://polymarket.com/event/{slug}"
    status = "CONSENSUS" if play.get("is_consensus") else "NON CONSENSUS"
    names = play.get("trader_names") or []
    names_txt = ", ".join(str(n) for n in names[:5])
    if len(names) > 5:
        names_txt += f", +{len(names) - 5}"
    traders_cell = f"{play.get('traders_count', 0)}/{top_n}" + (f" ({names_txt})" if names_txt else "")
    return (
        str(rank),
        _truncate(str(play.get("market_title") or ""), 48),
        _truncate(str(play.get("outcome") or ""), 22),
        _truncate(traders_cell, 36),
        str(play.get("opposed_traders_count") or 0),
        f"{float(play.get('showcased_value') or 0):,.2f}",
        f"{float(play.get('showcased_size') or 0):,.2f}",
        f"{float(play.get('weighted_avg_entry') or 0):.4f}",
        status[:14],
        url,
    )


def _build_ascii_table_plays(plays: list[dict[str, Any]], top_n: int) -> list[str]:
    rows: list[tuple[str, ...]] = []
    for i, play in enumerate(plays, start=1):
        rows.append(_play_row_cells(play, i, top_n))
    if not rows:
        return []

    headers = ("#", "Market", "Outcome", "Traders", "Op", "Value$", "Size", "Avg", "Status", "URL")
    widths = [max(len(headers[c]), max(len(r[c]) for r in rows)) for c in range(len(headers))]
    sep = " | "

    def fmt_row(cells: tuple[str, ...]) -> str:
        parts: list[str] = []
        for i, cell in enumerate(cells):
            w = widths[i]
            parts.append(cell.rjust(w) if i in (4, 5, 6, 7) else cell.ljust(w))
        return sep.join(parts)

    hparts = []
    for i, h in enumerate(headers):
        w = widths[i]
        hparts.append(h.rjust(w) if i in (4, 5, 6, 7) else h.ljust(w))
    header_line = sep.join(hparts)
    rule = sep.join("-" * widths[i] for i in range(len(headers)))
    out = [header_line, rule]
    out.extend(fmt_row(r) for r in rows)
    return out


def _chunk_lines_for_codeblock(lines: list[str], max_inner: int) -> list[str]:
    chunks: list[str] = []
    buf: list[str] = []
    n = 0
    for line in lines:
        add = len(line) + (1 if buf else 0)
        if n + add > max_inner and buf:
            chunks.append("\n".join(buf))
            buf = [line]
            n = len(line)
        else:
            if buf:
                n += 1
            buf.append(line)
            n += len(line)
    if buf:
        chunks.append("\n".join(buf))
    return chunks
