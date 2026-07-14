#!/usr/bin/env python3
"""Mechanically resolve direct Douban subjects before using the search Agent."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_provider import MediaProviderError, douban_lookup


DOUBAN_SUBJECT = re.compile(r"^https://movie\.douban\.com/subject/(\d+)/$")
MIN_DOUBAN_SCORE = 6.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def needs_douban(item: dict[str, Any]) -> bool:
    rating = item.get("ratings", {}).get("douban", {})
    return not (
        DOUBAN_SUBJECT.fullmatch(str(rating.get("url", "")))
        and isinstance(rating.get("score"), (int, float))
    )


class RequestGate:
    def __init__(self, interval: float):
        self.interval = max(0.0, interval)
        self.lock = threading.Lock()
        self.last_started = 0.0

    def wait(self) -> None:
        with self.lock:
            delay = self.interval - (time.monotonic() - self.last_started)
            if delay > 0:
                time.sleep(delay)
            self.last_started = time.monotonic()


def resolve_item(
    item: dict[str, Any], gate: RequestGate, retries: int
) -> tuple[str, dict[str, Any] | None, str | None]:
    key = str(item["key"])
    last_error = "unresolved"
    for attempt in range(max(1, retries + 1)):
        try:
            gate.wait()
            result = douban_lookup(str(item.get("title", "")), item.get("year"))
            match = DOUBAN_SUBJECT.fullmatch(str(result.get("doubanURL", "")))
            if not match:
                raise MediaProviderError("Douban did not return a canonical subject URL.")
            try:
                score = float(result.get("rating"))
            except (TypeError, ValueError) as error:
                raise MediaProviderError("Douban subject has no numeric score.") from error
            if not 0 <= score <= 10:
                raise MediaProviderError("Douban returned an invalid score.")
            return key, {
                "subjectID": match.group(1),
                "url": str(result["doubanURL"]),
                "score": round(score, 1),
                "ratingSourceURL": str(result.get("ratingSourceURL", "")),
                "retrievedAt": str(result.get("ratingRetrievedAt", utc_now())),
            }, None
        except Exception as error:  # Network and strict matching errors share retry handling.
            last_error = str(error)
            if attempt < retries:
                time.sleep(min(2 ** attempt, 4))
    return key, None, last_error


def apply_result(item: dict[str, Any], result: dict[str, Any]) -> None:
    item["doubanSubjectID"] = result["subjectID"]
    ratings = item.setdefault("ratings", {})
    previous = ratings.get("douban", {})
    ratings["douban"] = {
        "score": result["score"],
        "count": previous.get("count"),
        "url": result["url"],
        "top250Rank": previous.get("top250Rank"),
        "resolvedBy": "douban-search-suggest-exact-title-year-v2",
        "retrievedAt": result["retrievedAt"],
    }
    item["qualityScore"] = result["score"]
    item["qualityScoreSource"] = "douban"
    if result["score"] < MIN_DOUBAN_SCORE:
        item["recommendationEligible"] = False
    elif item.get("images", {}).get("small") and item.get("images", {}).get("medium"):
        item["recommendationEligible"] = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.json")
    parser.add_argument("--report", default="data/offline-douban-report.json")
    parser.add_argument("--limit", type=int, default=0, help="0 processes every pending item")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog_path = Path(args.catalog)
    catalog = json.loads(catalog_path.read_text())
    pending = [item for item in catalog["items"] if needs_douban(item)]
    if args.limit > 0:
        pending = pending[: args.limit]
    item_index = {str(item["key"]): item for item in pending}
    gate = RequestGate(args.request_interval)
    started_at = utc_now()
    resolved = 0
    failures: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(resolve_item, item, gate, args.retries): str(item["key"])
            for item in pending
        }
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

    finished_at = utc_now()
    direct_total = sum(not needs_douban(item) for item in catalog["items"])
    below_threshold = sum(
        isinstance(item.get("ratings", {}).get("douban", {}).get("score"), (int, float))
        and float(item["ratings"]["douban"]["score"]) < MIN_DOUBAN_SCORE
        for item in catalog["items"]
    )
    summary = {
        "startedAt": started_at,
        "finishedAt": finished_at,
        "requested": len(pending),
        "resolved": resolved,
        "failed": len(failures),
        "directDoubanTotal": direct_total,
        "belowSixTotal": below_threshold,
        "failures": failures,
    }
    catalog["offlineDoubanEnrichment"] = {key: value for key, value in summary.items() if key != "failures"}
    write_json_atomic(catalog_path, catalog)
    write_json_atomic(Path(args.report), summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
