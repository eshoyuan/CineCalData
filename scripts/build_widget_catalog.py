#!/usr/bin/env python3
"""Build the compact catalog consumed by the iOS app and widget."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def douban_subject_id(source: dict) -> str:
    explicit = str(source.get("doubanSubjectID") or "").strip()
    if explicit:
        return explicit
    url = str(source.get("ratings", {}).get("douban", {}).get("url") or "")
    match = re.search(r"/subject/(\d+)", url)
    return match.group(1) if match else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.json"))
    parser.add_argument("--output", type=Path, default=Path("data/widget-catalog.json"))
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    items: list[dict[str, object]] = []
    seen_subjects: set[str] = set()

    for source in catalog.get("items", []):
        douban = source.get("ratings", {}).get("douban", {})
        images = source.get("images", {})
        score = douban.get("score")
        url = douban.get("url")
        quote = source.get("quote")
        small = images.get("small")
        medium = images.get("medium")
        subject_id = douban_subject_id(source)

        if (
            source.get("recommendationEligible") is False
            or not isinstance(score, (int, float))
            or score < 6
            or not isinstance(url, str)
            or not url.startswith("https://")
            or not isinstance(quote, str)
            or not quote.strip()
            or not (small or medium)
            or not subject_id
            or subject_id in seen_subjects
        ):
            continue

        seen_subjects.add(subject_id)
        items.append(
            {
                "key": source["key"],
                "doubanSubjectID": subject_id,
                "title": source["title"],
                "rating": round(float(score), 1),
                "quote": quote,
                "imageURLSmall": small,
                "imageURLMedium": medium,
                "doubanURL": url,
            }
        )

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(items),
        "items": items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(items)} items to {args.output}")


if __name__ == "__main__":
    main()
