#!/usr/bin/env python3
"""Build and merge a long-range editorial selection plan for CineCal."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "data" / "plan.json"
MODEL = os.environ.get("CINECAL_MODEL", "muse-spark-1.1")
ALLOWED_SIGNALS = {
    "holiday",
    "release_anniversary",
    "person_anniversary",
    "festival",
    "seasonal",
    "historic_event",
    "cultural_moment",
    "editorial_theme",
}


class PublicationError(RuntimeError):
    """Raised when a planning batch cannot be published safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def date_range(start: date, days: int) -> list[str]:
    if days < 1:
        raise PublicationError("days must be positive.")
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days)]


def build_matrix(start: date, days: int, batch_days: int) -> list[dict[str, Any]]:
    if batch_days < 1 or batch_days > 31:
        raise PublicationError("batch-days must be between 1 and 31.")
    batches = []
    consumed = 0
    while consumed < days:
        count = min(batch_days, days - consumed)
        batches.append(
            {
                "start": (start + timedelta(days=consumed)).isoformat(),
                "days": count,
            }
        )
        consumed += count
    return batches


def existing_titles(plan_path: Path, start: date, days: int) -> list[str]:
    if not plan_path.exists():
        return []
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    wanted = set(date_range(start - timedelta(days=45), days + 90))
    return [
        str(entry["title"])
        for entry in payload.get("entries", [])
        if entry.get("date") in wanted and entry.get("title")
    ]


def generate_batch(
    client: Any,
    start: date,
    days: int,
    excluded_titles: list[str],
) -> dict[str, Any]:
    from cinecal_agent import grounded_json, is_grounded_url

    dates = date_range(start, days)
    prompt = f"""
Create a date-specific editorial film/television plan for these calendar dates:
{json.dumps(dates, ensure_ascii=False)}

For every date, use live web search and choose exactly one culturally notable film or prestige
series. The date connection must be meaningful and sourceable. Consider, in order:
- public holidays, traditional festivals, memorial days, and seasonal rituals;
- original release anniversaries and historically important production events;
- birthdays or memorial anniversaries of a principal actor, director, writer, or composer;
- major film festivals, awards calendars, or a strong cultural theme for that time of year.

Balance eras, countries, languages, genres, and creators. Avoid repeating a title within this
batch or these nearby cached titles: {json.dumps(excluded_titles[-80:], ensure_ascii=False)}.
Do not fabricate an anniversary. If no exact anniversary is strong, use an honest seasonal or
editorial-theme signal. Prefer works with a real Douban subject page and usable landscape imagery.

Return JSON only:
{{
  "entries": [
    {{
      "date": "YYYY-MM-DD",
      "title": "official Chinese title",
      "originalTitle": "original or international title",
      "selectionScore": 0,
      "reason": "one concise Chinese editorial reason",
      "signals": [
        {{
          "type": "holiday | release_anniversary | person_anniversary | festival | seasonal | historic_event | cultural_moment | editorial_theme",
          "label": "specific Chinese explanation",
          "sourceURL": "https://..."
        }}
      ]
    }}
  ]
}}

Return exactly one entry for every requested date. Score 0–100 based on the strength of the date
connection, cultural value, visual potential, and audience interest.
""".strip()
    result, sources = grounded_json(client, prompt, search_context_size="medium")
    raw_entries = result.get("entries")
    if not isinstance(raw_entries, list):
        raise PublicationError("Planning response did not contain an entries array.")

    requested = set(dates)
    seen_dates: set[str] = set()
    seen_titles: set[str] = set()
    approved: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        entry_date = str(raw.get("date", ""))
        title = str(raw.get("title", "")).strip()
        if entry_date not in requested or not title or entry_date in seen_dates:
            continue
        if title.casefold() in seen_titles:
            raise PublicationError(f"Planning batch repeated title: {title}")

        grounded_signals = []
        for signal in raw.get("signals", []):
            if not isinstance(signal, dict):
                continue
            signal_type = str(signal.get("type", ""))
            source_url = str(signal.get("sourceURL", ""))
            if (
                signal_type in ALLOWED_SIGNALS
                and signal.get("label")
                and source_url.startswith("https://")
                and is_grounded_url(source_url, sources)
            ):
                grounded_signals.append(
                    {
                        "type": signal_type,
                        "label": str(signal["label"]),
                        "sourceURL": source_url,
                    }
                )
        if not grounded_signals:
            raise PublicationError(f"Plan entry {entry_date} had no grounded date-selection signal.")

        try:
            score = max(0, min(100, int(raw.get("selectionScore", 0))))
        except (TypeError, ValueError) as error:
            raise PublicationError(f"Plan entry {entry_date} had an invalid score.") from error
        approved.append(
            {
                "date": entry_date,
                "title": title,
                "originalTitle": str(raw.get("originalTitle", "")),
                "selectionScore": score,
                "reason": str(raw.get("reason", "")),
                "signals": grounded_signals,
                # Keep the long-range plan compact. The full web-search citation
                # set can contain dozens of incidental URLs per date; only the
                # grounded URLs that justify the editorial choice are needed by
                # the later card-materialization job.
                "researchSources": list(
                    dict.fromkeys(signal["sourceURL"] for signal in grounded_signals)
                ),
                "locked": False,
                "generatedAt": iso_now(),
            }
        )
        seen_dates.add(entry_date)
        seen_titles.add(title.casefold())

    missing = sorted(requested - seen_dates)
    if missing:
        raise PublicationError(f"Planning batch omitted dates: {', '.join(missing)}")
    approved.sort(key=lambda item: item["date"])
    return {"schemaVersion": 1, "generatedAt": iso_now(), "entries": approved}


def merge_batches(plan_path: Path, merge_dir: Path, horizon_days: int) -> None:
    existing: dict[str, Any]
    if plan_path.exists():
        existing = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        existing = {"schemaVersion": 1, "entries": []}
    if existing.get("schemaVersion") != 1:
        raise PublicationError("Existing plan has an unsupported schema version.")

    by_date = {
        str(entry["date"]): entry
        for entry in existing.get("entries", [])
        if isinstance(entry, dict) and entry.get("date")
    }
    batch_files = sorted(merge_dir.rglob("*.json"))
    if not batch_files:
        raise PublicationError("No planning batch artifacts were found.")
    for batch_path in batch_files:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        for entry in batch.get("entries", []):
            entry_date = str(entry.get("date", ""))
            if not entry_date:
                continue
            if by_date.get(entry_date, {}).get("locked") is True:
                continue
            by_date[entry_date] = entry

    try:
        existing_horizon = int(existing.get("horizonDays", 0))
    except (TypeError, ValueError):
        existing_horizon = 0
    merged = {
        "schemaVersion": 1,
        # A small refresh/pilot must not shrink a previously bootstrapped
        # 365/730-day planning horizon.
        "horizonDays": max(existing_horizon, horizon_days),
        "updatedAt": iso_now(),
        "entries": sorted(by_date.values(), key=lambda item: item.get("date", "")),
    }
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=date.today().isoformat())
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--batch-days", type=int, default=14)
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--merge-dir", type=Path)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--horizon-days", type=int, default=730)
    args = parser.parse_args()
    try:
        start = date.fromisoformat(args.start)
    except ValueError as error:
        raise SystemExit(f"Invalid --start: {error}") from error

    if args.matrix:
        print(json.dumps(build_matrix(start, args.days, args.batch_days), separators=(",", ":")))
        return 0
    if args.merge_dir:
        merge_batches(args.plan, args.merge_dir, args.horizon_days)
        print(f"Merged planning artifacts into {args.plan}.")
        return 0
    if not args.output:
        raise SystemExit("--output is required when generating a planning batch.")

    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("MODEL_API_KEY is required.")
    from openai import OpenAI

    client = OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=api_key,
        timeout=600.0,
        max_retries=1,
    )
    payload = generate_batch(client, start, args.days, existing_titles(args.plan, start, args.days))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Planned {args.days} days from {args.start}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicationError as error:
        print(f"Planning blocked: {error}", file=sys.stderr)
        raise SystemExit(1)
