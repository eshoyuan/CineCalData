#!/usr/bin/env python3
"""Resolve exact TMDB entities for catalog entries that lack a landscape image."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_provider import MediaProviderError, TMDBProvider, normalized_title


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def title_set(*values: str) -> set[str]:
    return {normalized_title(value) for value in values if value and normalized_title(value)}


def validate_match(item: dict[str, Any], result: dict[str, Any]) -> str | None:
    wanted_type = "tv" if item.get("mediaType") in {"tv", "series"} else "movie"
    if result.get("mediaType") != wanted_type:
        return "TMDB media type did not match"
    year = item.get("year")
    if year and result.get("releaseYear") and int(result["releaseYear"]) != int(year):
        return "TMDB release year did not match"
    wanted_titles = title_set(
        str(item.get("title", "")),
        str(item.get("originalTitle", "")),
        *[str(value) for value in item.get("alternateTitles", [])[:6]],
    )
    returned_titles = title_set(str(result.get("title", "")), str(result.get("originalTitle", "")))
    if not wanted_titles.intersection(returned_titles):
        return "TMDB title did not match exactly"
    if not result.get("imageCandidates"):
        return "TMDB entity had no landscape image"
    return None


def apply_result(item: dict[str, Any], result: dict[str, Any]) -> None:
    item["tmdbID"] = int(result["tmdbID"])
    ratings = item.setdefault("ratings", {})
    ratings["tmdb"] = {
        "score": round(float(result.get("tmdbScore", 0)), 1),
        "count": int(result.get("tmdbVoteCount", 0)),
        "url": str(result["tmdbURL"]),
    }
    item.setdefault("popularity", {})["tmdb"] = round(float(result.get("tmdbPopularity", 0)), 4)
    images = item.setdefault("images", {})
    images["backdrop"] = str(result["imageCandidates"][0]["imageURL"])
    images["poster"] = str(result.get("posterURL", ""))
    item["tmdbResolvedAt"] = utc_now()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.json")
    parser.add_argument("--report", default="data/offline-tmdb-backdrop-report.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--checkpoint-every", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    provider = TMDBProvider()
    catalog_path = Path(args.catalog)
    catalog = json.loads(catalog_path.read_text())
    pending = [item for item in catalog["items"] if not item.get("images", {}).get("backdrop")]
    if args.limit > 0:
        pending = pending[: args.limit]
    item_index = {str(item["key"]): item for item in pending}
    resolved = 0
    failures: dict[str, str] = {}

    def resolve(item: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str | None]:
        key = str(item["key"])
        try:
            result = provider.resolve(
                str(item.get("title", "")),
                original_title=str(item.get("originalTitle", "")),
                release_year=item.get("year"),
                media_type=str(item.get("mediaType", "")),
            )
            reason = validate_match(item, result)
            return key, result if reason is None else None, reason
        except Exception as error:
            return key, None, str(error)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(resolve, item): str(item["key"]) for item in pending}
        for completed, future in enumerate(as_completed(futures), start=1):
            key, result, error = future.result()
            if result is not None:
                apply_result(item_index[key], result)
                resolved += 1
            else:
                failures[key] = error or "unresolved"
            if completed % max(1, args.checkpoint_every) == 0:
                write_json_atomic(catalog_path, catalog)
                print(f"processed {completed}/{len(pending)}; resolved={resolved}", flush=True)

    summary = {
        "updatedAt": utc_now(),
        "requested": len(pending),
        "resolved": resolved,
        "failed": len(failures),
        "failures": failures,
    }
    catalog["offlineBackdropResolution"] = {
        key: value for key, value in summary.items() if key != "failures"
    }
    write_json_atomic(catalog_path, catalog)
    write_json_atomic(Path(args.report), summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
