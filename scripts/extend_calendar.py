#!/usr/bin/env python3
"""Maintain a complete date-keyed calendar for every client timezone."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DOUBAN_SUBJECT_PATTERN = re.compile(r"/subject/(\d+)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def subject_id(value: dict[str, Any]) -> str:
    explicit = str(value.get("doubanSubjectID") or "").strip()
    if explicit:
        return explicit
    match = DOUBAN_SUBJECT_PATTERN.search(str(value.get("doubanURL") or ""))
    return match.group(1) if match else ""


def normalized_title(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def is_complete(entry: dict[str, Any]) -> bool:
    return all(
        str(entry.get(field) or "").strip()
        for field in ("date", "title", "rating", "quote", "doubanURL", "imageURLSmall", "imageURLMedium")
    ) and bool(subject_id(entry))


def catalog_entry(item: dict[str, Any], day: str, plan: dict[str, Any] | None) -> dict[str, Any]:
    rating = float(item["rating"])
    result: dict[str, Any] = {
        "date": day,
        "id": str(item["key"]),
        "title": str(item["title"]),
        "rating": f"{rating:.1f}",
        "quote": str(item["quote"]),
        "quoteType": "editorial",
        "quoteAttribution": "CineCal 原创编辑文案",
        "imageURL": str(item.get("imageURLMedium") or item.get("imageURLSmall")),
        "imageURLSmall": str(item.get("imageURLSmall") or item.get("imageURLMedium")),
        "imageURLMedium": str(item.get("imageURLMedium") or item.get("imageURLSmall")),
        "doubanURL": str(item["doubanURL"]),
        "doubanSubjectID": subject_id(item),
        "source": "widget-catalog",
    }
    if plan:
        result["selectionReason"] = str(plan.get("reason") or "")
        result["selectionSignals"] = plan.get("signals") or []
    return result


def choose_item(
    *,
    day: str,
    catalog: list[dict[str, Any]],
    by_title: dict[str, list[dict[str, Any]]],
    plan: dict[str, Any] | None,
    used_subjects: set[str],
) -> dict[str, Any]:
    if plan:
        planned_titles = [str(plan.get("title") or ""), str(plan.get("originalTitle") or "")]
        for title in planned_titles:
            for candidate in by_title.get(normalized_title(title), []):
                if subject_id(candidate) not in used_subjects:
                    return candidate

    start = int.from_bytes(hashlib.sha256(f"cinecal-calendar-v1:{day}".encode()).digest()[:8], "big") % len(catalog)
    for offset in range(len(catalog)):
        candidate = catalog[(start + offset) % len(catalog)]
        if subject_id(candidate) not in used_subjects:
            return candidate
    raise ValueError("The widget catalog has too few unique Douban subjects for this horizon")


def extend_calendar(
    calendar_payload: dict[str, Any],
    catalog_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    *,
    start: date,
    days: int,
    generated_at: str,
) -> dict[str, Any]:
    if days < 1:
        raise ValueError("days must be positive")

    catalog: list[dict[str, Any]] = []
    seen_catalog_subjects: set[str] = set()
    for item in catalog_payload.get("items", []):
        sid = subject_id(item)
        if not sid or sid in seen_catalog_subjects:
            continue
        if not all(str(item.get(field) or "").strip() for field in ("key", "title", "quote", "doubanURL")):
            continue
        if not (item.get("imageURLSmall") or item.get("imageURLMedium")):
            continue
        if not isinstance(item.get("rating"), (int, float)) or float(item["rating"]) < 6:
            continue
        seen_catalog_subjects.add(sid)
        catalog.append(item)
    if len(catalog) < days:
        raise ValueError(f"Need {days} unique complete catalog items, found {len(catalog)}")

    by_title: dict[str, list[dict[str, Any]]] = {}
    for item in catalog:
        by_title.setdefault(normalized_title(str(item["title"])), []).append(item)

    plans = {str(item.get("date")): item for item in plan_payload.get("entries", []) if item.get("date")}
    old_entries = {
        str(item.get("date")): item
        for item in calendar_payload.get("entries", [])
        if item.get("date")
    }
    target_days = [(start + timedelta(days=offset)).isoformat() for offset in range(days)]
    used_subjects: set[str] = set()
    target_entries: dict[str, dict[str, Any]] = {}

    # Preserve complete editorial choices first, but remove duplicate works inside
    # the active horizon so each user receives a genuinely different daily card.
    for day in target_days:
        existing = old_entries.get(day)
        sid = subject_id(existing or {})
        if existing and is_complete(existing) and sid not in used_subjects:
            normalized = dict(existing)
            normalized.setdefault("doubanSubjectID", sid)
            target_entries[day] = normalized
            used_subjects.add(sid)

    for day in target_days:
        if day in target_entries:
            continue
        plan = plans.get(day)
        item = choose_item(
            day=day,
            catalog=catalog,
            by_title=by_title,
            plan=plan,
            used_subjects=used_subjects,
        )
        target_entries[day] = catalog_entry(item, day, plan)
        used_subjects.add(subject_id(item))

    outside_horizon = [
        item for item in calendar_payload.get("entries", []) if str(item.get("date") or "") not in target_entries
    ]
    entries = outside_horizon + [target_entries[day] for day in target_days]
    entries.sort(key=lambda item: str(item.get("date") or ""))
    return {
        "schemaVersion": 1,
        "updatedAt": generated_at,
        "horizon": {"start": target_days[0], "end": target_days[-1], "days": days},
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar", type=Path, default=Path("data/calendar.json"))
    parser.add_argument("--catalog", type=Path, default=Path("data/widget-catalog.json"))
    parser.add_argument("--plan", type=Path, default=Path("data/plan.json"))
    parser.add_argument("--start", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    parser.add_argument("--days", type=int, default=732)
    args = parser.parse_args()

    calendar_payload = json.loads(args.calendar.read_text(encoding="utf-8"))
    catalog_payload = json.loads(args.catalog.read_text(encoding="utf-8"))
    plan_payload = json.loads(args.plan.read_text(encoding="utf-8")) if args.plan.exists() else {"entries": []}
    payload = extend_calendar(
        calendar_payload,
        catalog_payload,
        plan_payload,
        start=args.start,
        days=args.days,
        generated_at=utc_now(),
    )
    args.calendar.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["horizon"], ensure_ascii=False))


if __name__ == "__main__":
    main()
