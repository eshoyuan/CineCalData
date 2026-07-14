#!/usr/bin/env python3
"""Publish a tiny, model-free pointer to an already cached CineCal card."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def choose_entry(entries: list[dict[str, Any]], target_date: str) -> tuple[dict[str, Any], bool]:
    exact = next((entry for entry in entries if entry.get("date") == target_date), None)
    if exact:
        return exact, False
    earlier = sorted(
        (entry for entry in entries if str(entry.get("date", "")) <= target_date),
        key=lambda entry: str(entry.get("date", "")),
        reverse=True,
    )
    if not earlier:
        raise ValueError(f"No cached card is available on or before {target_date}.")
    return earlier[0], True


def publish(calendar_path: Path, output_path: Path, target_date: str) -> dict[str, Any]:
    feed = json.loads(calendar_path.read_text(encoding="utf-8"))
    if feed.get("schemaVersion") != 1 or not isinstance(feed.get("entries"), list):
        raise ValueError("Unsupported calendar feed.")
    entry, used_fallback = choose_entry(feed["entries"], target_date)
    required = ["title", "rating", "quote", "doubanURL", "imageURLSmall", "imageURLMedium"]
    missing = [field for field in required if not entry.get(field)]
    payload = {
        "schemaVersion": 1,
        "date": target_date,
        "publishedAt": iso_now(),
        "complete": not missing,
        "usedFallback": used_fallback,
        "missingFields": missing,
        "entry": entry,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--calendar", type=Path, default=ROOT / "data" / "calendar.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "today.json")
    args = parser.parse_args()
    target_date = date.fromisoformat(args.date).isoformat()
    payload = publish(args.calendar, args.output, target_date)
    state = "complete" if payload["complete"] else "incomplete"
    print(f"Published {target_date} pointer ({state}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
