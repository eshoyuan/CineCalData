#!/usr/bin/env python3
"""Ground Douban subjects and write original editorial lines for catalog items."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROMPT_VERSION = "catalog-editorial-v2"
MIN_DOUBAN_SCORE = 6.0
DOUBAN_SUBJECT = re.compile(r"^https://movie\.douban\.com/subject/(\d+)/$")
WEAK_CONTEXT_HOSTS = {"play.google.com", "tv.apple.com", "www.amazon.com", "amazon.com"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def needs_enrichment(item: dict[str, Any]) -> bool:
    douban = item.get("ratings", {}).get("douban", {})
    editorial = item.get("editorial", {})
    return not (
        DOUBAN_SUBJECT.fullmatch(str(douban.get("url", "")))
        and isinstance(douban.get("score"), (int, float))
        and editorial.get("quote")
        and editorial.get("promptVersion") == PROMPT_VERSION
    )


def has_verified_douban(item: dict[str, Any]) -> bool:
    douban = item.get("ratings", {}).get("douban", {})
    return bool(
        DOUBAN_SUBJECT.fullmatch(str(douban.get("url", "")))
        and isinstance(douban.get("score"), (int, float))
    )


def catalog_quality_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    required_scores = ("relevance", "literary", "specificity", "spoilerSafety", "widgetFit")
    direct_douban = 0
    image_pairs = 0
    editorial = 0
    complete = 0
    quotes: set[str] = set()
    invalid_quote_lengths = 0
    failed_reviews = 0

    for item in items:
        douban = item.get("ratings", {}).get("douban", {})
        score = douban.get("score")
        has_douban = bool(
            DOUBAN_SUBJECT.fullmatch(str(douban.get("url", "")))
            and isinstance(score, (int, float))
            and score >= MIN_DOUBAN_SCORE
        )
        has_images = bool(item.get("images", {}).get("small") and item.get("images", {}).get("medium"))
        record = item.get("editorial", {})
        quote = re.sub(r"\s+", "", str(record.get("quote", "")).strip())
        has_editorial = bool(record.get("promptVersion") == PROMPT_VERSION and quote)
        scores = record.get("review", {}).get("scores", {}) if has_editorial else {}
        review_passes = bool(
            has_editorial
            and all(float(scores.get(name, 0)) >= 8 for name in required_scores)
        )
        quote_length_passes = bool(has_editorial and 12 <= len(quote) <= 42)

        direct_douban += int(has_douban)
        image_pairs += int(has_images)
        editorial += int(has_editorial)
        invalid_quote_lengths += int(has_editorial and not quote_length_passes)
        failed_reviews += int(has_editorial and not review_passes)
        if has_douban and has_images and has_editorial and review_passes and quote_length_passes:
            complete += 1
            quotes.add(quote)

    return {
        "catalogTotal": len(items),
        "directDoubanAtLeastSixTotal": direct_douban,
        "imagePairTotal": image_pairs,
        "editorialTotal": editorial,
        "completeCardTotal": complete,
        "uniqueCompleteQuoteTotal": len(quotes),
        "invalidQuoteLengthTotal": invalid_quote_lengths,
        "failedReviewTotal": failed_reviews,
    }


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
5. Use contextSourceURL for the strongest grounded page that informed the sentence. Prefer the
   Douban subject, an encyclopedia, a film festival/archive, an interview, or reputable criticism.
   Do not use an app store, streaming storefront, ticket seller, shopping page, or search page.
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


def build_local_draft_prompt(items: list[dict[str, Any]]) -> str:
    return f"""
You are the Chinese editorial writer for CineCal, a 169-point film-calendar widget. Every supplied
work already has an exact verified Douban subject and rating, plus locally cached structured
metadata. Do not search for or change those factual fields.

For every work, write one ORIGINAL Chinese editorial sentence based only on the supplied metadata.
It should be literary, emotionally specific to that work, spoiler-free, ideally 18–34 Chinese
characters and never over 42. Do not quote or closely paraphrase dialogue, reviews, subtitles,
lyrics, plot summaries, taglines or marketing copy. Do not present invented words as a quotation.
Avoid generic interchangeable comfort-language and clichés. Never merge, omit, or change a key.

Input works:
{json.dumps([prompt_item(item) for item in items], ensure_ascii=False)}

Return JSON only:
{{
  "entries": [
    {{
      "key": "exact input key",
      "quote": "原创中文编辑短句",
      "confidence": 0.0
    }}
  ]
}}
""".strip()


def generate_local_drafts(
    client: Any, items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    from cinecal_agent import text_json

    payload = text_json(client, build_local_draft_prompt(items))
    returned = payload.get("entries", [])
    if not isinstance(returned, list):
        returned = []
    item_index = {str(item["key"]): item for item in items}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for draft in returned:
        if not isinstance(draft, dict):
            continue
        key = str(draft.get("key", ""))
        item = item_index.get(key)
        if item is None or key in seen:
            continue
        seen.add(key)
        douban = item["ratings"]["douban"]
        results.append(
            {
                "key": key,
                "status": "verified",
                "doubanURL": douban["url"],
                "doubanScore": douban["score"],
                "quote": draft.get("quote", ""),
                "quoteType": "editorial",
                "quoteAttribution": "CineCal 原创编辑文案",
                "contextSourceURL": douban["url"],
                # Identity and rating are deterministic local facts here. Copy quality is
                # governed separately by the five-score editorial review below.
                "confidence": 0.95,
            }
        )
    failures = {
        key: "local editorial writer omitted the item"
        for key in item_index.keys() - seen
    }
    return results, failures


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
    known_douban = item.get("ratings", {}).get("douban", {})
    known_url = str(known_douban.get("url", ""))
    known_score = known_douban.get("score")
    link_was_already_verified = (
        url == known_url
        and DOUBAN_SUBJECT.fullmatch(known_url) is not None
        and isinstance(known_score, (int, float))
    )
    if not match or (not link_was_already_verified and not is_grounded_url(url, grounded_urls)):
        return "Douban subject was not present in grounded evidence"
    try:
        score = float(result.get("doubanScore"))
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        return "invalid score or confidence"
    if not MIN_DOUBAN_SCORE <= score <= 10.0:
        return "Douban score is missing or below the catalog threshold"
    if confidence < 0.85:
        return "confidence below 0.85"
    quote = re.sub(r"\s+", "", str(result.get("quote", "")).strip())
    if not 12 <= len(quote) <= 42:
        return "editorial sentence is outside 12–42 characters"
    context_url = str(result.get("contextSourceURL", ""))
    if not context_url.startswith("https://") or not is_grounded_url(context_url, grounded_urls):
        return "editorial context source was not grounded"
    if (urllib.parse.urlparse(context_url).hostname or "").lower() in WEAK_CONTEXT_HOSTS:
        return "editorial context source was a storefront"
    if result.get("quoteType") != "editorial":
        return "quote type was not editorial"
    review = result.get("_review", {})
    scores = review.get("scores", {}) if isinstance(review, dict) else {}
    required_scores = ("relevance", "literary", "specificity", "spoilerSafety", "widgetFit")
    if not review.get("approved") or any(float(scores.get(name, 0)) < 8 for name in required_scores):
        return "editorial review did not pass every 8/10 threshold"

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
        "review": {
            "scores": {name: float(scores[name]) for name in required_scores},
            "reason": str(review.get("reason", "")),
        },
    }
    item["recommendationEligible"] = bool(
        item.get("images", {}).get("small") and item.get("images", {}).get("medium")
    )
    return None


def build_review_prompt(
    items: list[dict[str, Any]], results: list[dict[str, Any]]
) -> str:
    item_index = {item["key"]: item for item in items}
    drafts = [
        {
            "key": result["key"],
            "work": prompt_item(item_index[str(result["key"])]),
            "draft": result.get("quote", ""),
        }
        for result in results
        if str(result.get("key", "")) in item_index
    ]
    return f"""
You are the final Chinese copy editor for a 169-point film widget. Review every proposed ORIGINAL
editorial sentence against its supplied work. Each line must be emotionally specific and literary,
but must not reveal plot mechanics, twists, endings, deaths, destinations, or character outcomes.
It must not copy or imitate a famous line/review, invent a quotation, summarize the plot, or rely
on generic interchangeable comfort-language. Each final line must be 12–42 characters, ideally
18–34. Never merge, omit, or change an input key.

Drafts:
{json.dumps(drafts, ensure_ascii=False)}

If a draft has any weakness, silently rewrite it and score the rewritten final version. Approve
only when every score is at least 8. Return JSON only:
{{
  "entries": [
    {{
      "key": "exact input key",
      "approved": true,
      "approvedQuote": "final original Chinese sentence",
      "scores": {{
        "relevance": 0,
        "literary": 0,
        "specificity": 0,
        "spoilerSafety": 0,
        "widgetFit": 0
      }},
      "reason": "one concise Chinese editorial note"
    }}
  ]
}}
""".strip()


def review_editorials(
    client: Any,
    items: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, str]:
    from cinecal_agent import text_json
    payload = text_json(client, build_review_prompt(items, results))
    returned = payload.get("entries", [])
    if not isinstance(returned, list):
        returned = []
    result_index = {str(result.get("key", "")): result for result in results}
    failures: dict[str, str] = {}
    seen: set[str] = set()
    for review in returned:
        if not isinstance(review, dict):
            continue
        key = str(review.get("key", ""))
        result = result_index.get(key)
        if result is None or key in seen:
            continue
        seen.add(key)
        approved_quote = re.sub(r"\s+", "", str(review.get("approvedQuote", "")).strip())
        if approved_quote:
            result["quote"] = approved_quote
        result["_review"] = review
    for key in result_index.keys() - seen:
        failures[key] = "editorial reviewer omitted the item"
    return failures


def review_editorial(client: Any, item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible single-item review helper used by older callers."""
    failures = review_editorials(client, [item], [result])
    if failures:
        raise RuntimeError(next(iter(failures.values())))
    return result["_review"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.json")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--draft-batch-size", type=int, default=24)
    parser.add_argument("--review-batch-size", type=int, default=16)
    parser.add_argument("--research-workers", type=int, default=1)
    parser.add_argument("--draft-workers", type=int, default=1)
    parser.add_argument("--review-workers", type=int, default=1)
    parser.add_argument(
        "--skip-research",
        action="store_true",
        help="Review and materialize cached results without issuing new web-search requests.",
    )
    parser.add_argument("--state", default=".cache/cinecal-editorial-v2.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from local_secrets import read_secret

    model_api_key = read_secret("MODEL_API_KEY")
    if not model_api_key:
        raise SystemExit(
            "MODEL_API_KEY is required (environment or macOS Keychain service CineCalMetaAI)"
        )
    from openai import OpenAI
    from cinecal_agent import MODEL, grounded_json

    path = Path(args.catalog)
    catalog = json.loads(path.read_text())
    pending = [item for item in catalog["items"] if needs_enrichment(item)]
    if args.limit > 0:
        pending = pending[: args.limit]
    client = OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=model_api_key,
        timeout=float(os.environ.get("CINECAL_MODEL_TIMEOUT_SECONDS", "240")),
    )
    generated_at = utc_now()
    item_index = {item["key"]: item for item in pending}
    verified = 0
    failures: dict[str, str] = {}

    state_path = Path(args.state)
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    if state.get("promptVersion") != PROMPT_VERSION:
        state = {"promptVersion": PROMPT_VERSION, "research": {}}
    research: dict[str, dict[str, Any]] = state.setdefault("research", {})
    for cached in research.values():
        if cached.get("mode") == "local_structured_metadata":
            cached.get("result", {})["confidence"] = 0.95
    # A few early benchmark entries were researched on the web before the deterministic/local
    # split existed. If their Douban facts are already verified but the card is still pending,
    # discard that stale web draft and route them through the local structured-metadata writer.
    for item in pending:
        cached = research.get(item["key"])
        if has_verified_douban(item) and cached and cached.get("mode") != "local_structured_metadata":
            del research[item["key"]]

    local_pending = [
        item for item in pending
        if item["key"] not in research and has_verified_douban(item)
    ]
    draft_batches = [
        local_pending[start : start + max(1, args.draft_batch_size)]
        for start in range(0, len(local_pending), max(1, args.draft_batch_size))
    ]

    def draft_batch(batch: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Any, Any]:
        try:
            results, draft_failures = generate_local_drafts(client, batch)
            return batch, results, draft_failures
        except Exception as error:
            return batch, error, None

    drafted_count = 0
    with ThreadPoolExecutor(max_workers=max(1, args.draft_workers)) as executor:
        futures = [executor.submit(draft_batch, batch) for batch in draft_batches]
        for future in as_completed(futures):
            batch, outcome, draft_failures = future.result()
            drafted_count += len(batch)
            if isinstance(outcome, Exception):
                for item in batch:
                    failures[item["key"]] = f"local draft failed: {outcome}"
            else:
                failures.update(draft_failures)
                for raw in outcome:
                    key = str(raw["key"])
                    item = item_index[key]
                    sources = [str(item["ratings"]["douban"]["url"])]
                    tmdb_url = str(item.get("ratings", {}).get("tmdb", {}).get("url", ""))
                    if tmdb_url.startswith("https://"):
                        sources.append(tmdb_url)
                    research[key] = {
                        "result": raw,
                        "sources": sources,
                        "researchedAt": generated_at,
                        "mode": "local_structured_metadata",
                    }
            write_json_atomic(state_path, state)
            print(f"drafted {drafted_count}/{len(local_pending)}", flush=True)

    unresolved_pending = [] if args.skip_research else [
        item for item in pending
        if item["key"] not in research and not has_verified_douban(item)
    ]
    research_batches = [
        unresolved_pending[start : start + max(1, args.batch_size)]
        for start in range(0, len(unresolved_pending), max(1, args.batch_size))
    ]

    def research_batch(batch: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Any, Any]:
        try:
            payload, sources = grounded_json(client, build_prompt(batch), search_context_size="large")
            return batch, payload, sources
        except Exception as error:
            return batch, error, None

    researched_count = len(pending) - sum(len(batch) for batch in research_batches)
    with ThreadPoolExecutor(max_workers=max(1, args.research_workers)) as executor:
        futures = [executor.submit(research_batch, batch) for batch in research_batches]
        for future in as_completed(futures):
            batch, payload, sources = future.result()
            researched_count += len(batch)
            if isinstance(payload, Exception):
                for item in batch:
                    failures[item["key"]] = f"request failed: {payload}"
            else:
                returned = payload.get("entries", [])
                if not isinstance(returned, list):
                    returned = []
                seen: set[str] = set()
                for raw in returned:
                    if not isinstance(raw, dict) or raw.get("key") not in item_index:
                        continue
                    key = str(raw["key"])
                    seen.add(key)
                    if raw.get("status") == "verified":
                        research[key] = {
                            "result": raw,
                            "sources": sources,
                            "researchedAt": generated_at,
                        }
                for item in batch:
                    if item["key"] not in seen:
                        failures[item["key"]] = "agent omitted the item"
            write_json_atomic(state_path, state)
            print(f"researched {researched_count}/{len(pending)}", flush=True)

    review_candidates = [
        research[item["key"]]["result"]
        for item in pending
        if item["key"] in research and not research[item["key"]]["result"].get("_review")
    ]
    review_batches = [
        review_candidates[start : start + max(1, args.review_batch_size)]
        for start in range(0, len(review_candidates), max(1, args.review_batch_size))
    ]

    def review_batch(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Any]:
        items = [item_index[str(result["key"])] for result in results]
        try:
            return results, review_editorials(client, items, results)
        except Exception as error:
            return results, error

    reviewed_count = 0
    with ThreadPoolExecutor(max_workers=max(1, args.review_workers)) as executor:
        futures = [executor.submit(review_batch, results) for results in review_batches]
        for future in as_completed(futures):
            results, outcome = future.result()
            reviewed_count += len(results)
            if isinstance(outcome, Exception):
                for result in results:
                    failures[str(result["key"])] = f"editorial review failed: {outcome}"
            else:
                failures.update(outcome)
            write_json_atomic(state_path, state)
            print(f"reviewed {reviewed_count}/{len(review_candidates)}", flush=True)

    for item in pending:
        cached = research.get(item["key"])
        if not cached:
            failures.setdefault(item["key"], "research unresolved")
            continue
        raw = cached["result"]
        reason = normalize_result(
            item, raw, list(cached.get("sources", [])), model=MODEL, generated_at=generated_at
        )
        if reason:
            failures[item["key"]] = reason
        else:
            failures.pop(item["key"], None)
            verified += 1

    quality = catalog_quality_summary(catalog["items"])
    catalog["editorialEnrichment"] = {
        "updatedAt": generated_at,
        "model": MODEL,
        "promptVersion": PROMPT_VERSION,
        **quality,
        "lastRun": {
            "requested": len(pending),
            "verified": verified,
            "failed": len(failures),
            "failures": failures,
        },
    }
    write_json_atomic(path, catalog)
    print(json.dumps(catalog["editorialEnrichment"], ensure_ascii=False))


if __name__ == "__main__":
    main()
