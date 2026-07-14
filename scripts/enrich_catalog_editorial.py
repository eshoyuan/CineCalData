#!/usr/bin/env python3
"""Ground Douban subjects and write original editorial lines for catalog items."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROMPT_VERSION = "catalog-editorial-v1"
DOUBAN_SUBJECT = re.compile(r"^https://movie\.douban\.com/subject/(\d+)/$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def needs_enrichment(item: dict[str, Any]) -> bool:
    douban = item.get("ratings", {}).get("douban", {})
    editorial = item.get("editorial", {})
    return not (
        DOUBAN_SUBJECT.fullmatch(str(douban.get("url", "")))
        and isinstance(douban.get("score"), (int, float))
        and editorial.get("quote")
        and editorial.get("promptVersion") == PROMPT_VERSION
    )


def prompt_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": item["key"],
        "title": item.get("title", ""),
        "originalTitle": item.get("originalTitle", ""),
        "alternateTitles": item.get("alternateTitles", [])[:4],
        "year": item.get("year"),
        "mediaType": item.get("mediaType", ""),
        "creators": item.get("creators", [])[:4],
        "cast": item.get("cast", [])[:6],
        "genres": item.get("genres", []),
        "overview": item.get("overview", ""),
        "knownDoubanURL": item.get("ratings", {}).get("douban", {}).get("url", ""),
        "knownDoubanScore": item.get("ratings", {}).get("douban", {}).get("score"),
    }


def build_prompt(items: list[dict[str, Any]]) -> str:
    return f"""
You are the grounded editorial researcher for CineCal, a Chinese film-calendar widget.
Research every supplied work on the live web. Resolve the exact Douban movie subject by
cross-checking Chinese title, original title, release year, media type, director/creator and
principal cast. Reject remakes, similarly named works, wrong seasons and cross-year matches.

For each work:
1. Return only a direct canonical URL shaped https://movie.douban.com/subject/1234567/.
2. Return the current Douban score visible in grounded evidence. Never substitute a TMDB score.
3. Read enough grounded context to understand the work's emotional theme.
4. Write one ORIGINAL Chinese editorial sentence, ideally 18–34 Chinese characters and never
   over 42 characters. It should be literary, emotionally specific, spoiler-free, and work in a
   small home-screen widget. Do not quote or closely paraphrase dialogue, reviews, subtitles,
   lyrics, plot summaries, taglines or marketing copy. Do not present invented words as a quote.
5. Use contextSourceURL for the strongest grounded page that informed the sentence.
6. Set confidence below 0.85 when exact identity, rating, or context remains uncertain.

Avoid generic interchangeable lines and clichés such as “时光温柔”“岁月静好”“愿你”“治愈一切”.
If no exact Douban subject or score is verifiable, return status "unresolved" and do not guess.

Input works:
{json.dumps([prompt_item(item) for item in items], ensure_ascii=False)}

Return JSON only:
{{
  "entries": [
    {{
      "key": "exact input key",
      "status": "verified or unresolved",
      "doubanURL": "https://movie.douban.com/subject/1234567/",
      "doubanScore": 8.8,
      "quote": "原创中文编辑短句",
      "quoteType": "editorial",
      "quoteAttribution": "CineCal 原创编辑文案",
      "contextSourceURL": "https://...",
      "confidence": 0.0
    }}
  ]
}}
""".strip()


def normalize_result(
    item: dict[str, Any],
    result: dict[str, Any],
    grounded_urls: list[str],
    *,
    model: str,
    generated_at: str,
) -> str | None:
    from cinecal_agent import is_grounded_url

    if result.get("status") != "verified":
        return "agent marked unresolved"
    url = str(result.get("doubanURL", ""))
    match = DOUBAN_SUBJECT.fullmatch(url)
    if not match or not is_grounded_url(url, grounded_urls):
        return "Douban subject was not present in grounded evidence"
    try:
        score = float(result.get("doubanScore"))
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        return "invalid score or confidence"
    if not 7.0 <= score <= 10.0:
        return "Douban score is missing or below the catalog threshold"
    if confidence < 0.85:
        return "confidence below 0.85"
    quote = re.sub(r"\s+", "", str(result.get("quote", "")).strip())
    if not 12 <= len(quote) <= 42:
        return "editorial sentence is outside 12–42 characters"
    context_url = str(result.get("contextSourceURL", ""))
    if not context_url.startswith("https://") or not is_grounded_url(context_url, grounded_urls):
        return "editorial context source was not grounded"
    if result.get("quoteType") != "editorial":
        return "quote type was not editorial"

    item["doubanSubjectID"] = match.group(1)
    current = item["ratings"]["douban"]
    item["ratings"]["douban"] = {
        "score": round(score, 1),
        "count": current.get("count"),
        "url": url,
        "top250Rank": current.get("top250Rank"),
    }
    item["quote"] = quote
    item["quoteType"] = "editorial"
    item["quoteAttribution"] = "CineCal 原创编辑文案"
    item["editorial"] = {
        "quote": quote,
        "type": "editorial",
        "attribution": "CineCal 原创编辑文案",
        "contextSourceURL": context_url,
        "confidence": round(confidence, 3),
        "model": model,
        "promptVersion": PROMPT_VERSION,
        "generatedAt": generated_at,
    }
    item["recommendationEligible"] = bool(
        item.get("images", {}).get("small") and item.get("images", {}).get("medium")
    )
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.json")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not os.environ.get("MODEL_API_KEY"):
        raise SystemExit("MODEL_API_KEY is required")
    from openai import OpenAI
    from cinecal_agent import MODEL, grounded_json

    path = Path(args.catalog)
    catalog = json.loads(path.read_text())
    pending = [item for item in catalog["items"] if needs_enrichment(item)][: args.limit]
    client = OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=os.environ["MODEL_API_KEY"],
        timeout=float(os.environ.get("CINECAL_MODEL_TIMEOUT_SECONDS", "240")),
    )
    generated_at = utc_now()
    item_index = {item["key"]: item for item in pending}
    verified = 0
    failures: dict[str, str] = {}

    for start in range(0, len(pending), max(1, args.batch_size)):
        batch = pending[start : start + max(1, args.batch_size)]
        try:
            payload, sources = grounded_json(client, build_prompt(batch), search_context_size="large")
        except Exception as error:
            for item in batch:
                failures[item["key"]] = f"request failed: {error}"
            continue
        returned = payload.get("entries", [])
        if not isinstance(returned, list):
            returned = []
        seen: set[str] = set()
        for raw in returned:
            if not isinstance(raw, dict) or raw.get("key") not in item_index:
                continue
            key = str(raw["key"])
            seen.add(key)
            reason = normalize_result(
                item_index[key], raw, sources, model=MODEL, generated_at=generated_at
            )
            if reason:
                failures[key] = reason
            else:
                verified += 1
        for item in batch:
            if item["key"] not in seen:
                failures[item["key"]] = "agent omitted the item"
        print(f"processed {min(start + len(batch), len(pending))}/{len(pending)}; verified={verified}", flush=True)

    eligible = sum(bool(item.get("recommendationEligible")) for item in catalog["items"])
    catalog["editorialEnrichment"] = {
        "updatedAt": generated_at,
        "model": MODEL,
        "promptVersion": PROMPT_VERSION,
        "requested": len(pending),
        "verified": verified,
        "failed": len(failures),
        "eligibleTotal": eligible,
        "failures": failures,
    }
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(catalog["editorialEnrichment"], ensure_ascii=False))


if __name__ == "__main__":
    main()
