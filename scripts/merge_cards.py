#!/usr/bin/env python3
"""Merge independently materialized card artifacts into the public feed."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def merge_cards(calendar_path: Path, artifact_root: Path) -> int:
    feed: dict[str, Any] = json.loads(calendar_path.read_text(encoding="utf-8"))
    entries = {
        str(entry["date"]): entry
        for entry in feed.get("entries", [])
        if isinstance(entry, dict) and entry.get("date")
    }
    merged_count = 0
    for artifact in sorted(artifact_root.glob("card-*")):
        target_date = artifact.name.removeprefix("card-")
        artifact_calendar = artifact / "data" / "calendar.json"
        if not artifact_calendar.exists():
            continue
        batch = json.loads(artifact_calendar.read_text(encoding="utf-8"))
        card = next((entry for entry in batch.get("entries", []) if entry.get("date") == target_date), None)
        if not card:
            continue
        entries[target_date] = card
        merged_count += 1
        for folder in ("images", "reports"):
            source_dir = artifact / "data" / folder
            destination_dir = calendar_path.parent / folder
            if not source_dir.exists():
                continue
            destination_dir.mkdir(parents=True, exist_ok=True)
            for source in source_dir.iterdir():
                if source.is_file() and source.name.startswith(target_date):
                    shutil.copy2(source, destination_dir / source.name)

    if merged_count == 0:
        raise ValueError("No successful card artifacts were available to merge.")
    feed["entries"] = sorted(entries.values(), key=lambda item: item.get("date", ""))
    feed["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    calendar_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return merged_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, default=Path("data/calendar.json"))
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    count = merge_cards(args.calendar, args.artifacts)
    print(f"Merged {count} precomputed cards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
