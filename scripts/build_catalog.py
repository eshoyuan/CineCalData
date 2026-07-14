#!/usr/bin/env python3
"""Build CineCal's model-free recommendation catalog from structured sources."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from media_provider import MediaProviderError, TMDB_API, TMDB_IMAGE, TMDBProvider, douban_lookup, normalized_title


DOUBAN_TOP250 = "https://movie.douban.com/top250"
USER_AGENT = "CineCalCatalog/1.0 (+https://github.com/eshoyuan/CineCalData)"
MIN_SCORE = 7.0
MIN_MOVIE_VOTES = 100
MIN_TV_VOTES = 50


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://movie.douban.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def subject_id(url: str) -> str:
    match = re.search(r"/subject/(\d+)", url)
    return match.group(1) if match else ""


def parse_douban_top250_page(page: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for block in re.findall(r'<div class="item">(.*?)(?=<div class="item">|$)', page, re.S):
        url_match = re.search(r'href="(https://movie\.douban\.com/subject/\d+/)"', block)
        rank_match = re.search(r'<em[^>]*>(\d+)</em>', block)
        titles = [clean_html(value) for value in re.findall(r'<span class="title">(.*?)</span>', block, re.S)]
        rating_match = re.search(r'<span class="rating_num"[^>]*>([0-9.]+)</span>', block)
        count_match = re.search(r'<span>(\d+)人评价</span>', block)
        info_match = re.search(r'<div class="bd">\s*<p[^>]*>(.*?)</p>', block, re.S)
        if not (url_match and rank_match and titles and rating_match):
            continue
        info = clean_html(info_match.group(1)) if info_match else ""
        year_match = re.search(r"(?:^|\s)(19\d{2}|20\d{2})(?:\s|$)", info)
        records.append(
            {
                "rank": int(rank_match.group(1)),
                "title": titles[0],
                "alternateTitles": titles[1:],
                "year": int(year_match.group(1)) if year_match else None,
                "rating": float(rating_match.group(1)),
                "ratingCount": int(count_match.group(1)) if count_match else None,
                "url": url_match.group(1),
                "subjectID": subject_id(url_match.group(1)),
                "metadataText": info,
            }
        )
    return records


def fetch_douban_top250() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for start in range(0, 250, 25):
        query = urllib.parse.urlencode({"start": start, "filter": ""})
        page_records: list[dict[str, Any]] = []
        for attempt in range(2):
            page_records = parse_douban_top250_page(read_text(f"{DOUBAN_TOP250}?{query}"))
            if page_records:
                break
            time.sleep(2 + attempt)
        records.extend(page_records)
        if start < 225:
            time.sleep(1.25)
    unique = {record["subjectID"]: record for record in records if record["subjectID"]}
    return sorted(unique.values(), key=lambda item: item["rank"])


def write_douban_top250_snapshot(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "source": DOUBAN_TOP250,
        "count": len(records),
        "items": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_douban_top250_snapshot(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    return list(payload.get("items", []))


def source_rank_score(source_ranks: dict[str, int]) -> float:
    bonuses = {"douban_top250": 35, "trending_week": 24, "popular": 16, "top_rated": 12, "recent": 10}
    return sum(bonuses.get(source, 0) / max(1, math.sqrt(rank)) for source, rank in source_ranks.items())


def quality_score(item: dict[str, Any]) -> tuple[float, str]:
    douban = item.get("ratings", {}).get("douban", {})
    if isinstance(douban.get("score"), (int, float)):
        return float(douban["score"]), "douban"
    tmdb = item.get("ratings", {}).get("tmdb", {})
    return float(tmdb.get("score", 0) or 0), "tmdb"


def ranking_score(item: dict[str, Any]) -> float:
    score, _ = quality_score(item)
    tmdb = item.get("ratings", {}).get("tmdb", {})
    votes = int(tmdb.get("count", 0) or 0)
    popularity = float(item.get("popularity", {}).get("tmdb", 0) or 0)
    return round(score * 10 + math.log10(votes + 1) * 4 + min(popularity, 250) / 18 + source_rank_score(item.get("sourceRanks", {})), 4)


def tmdb_key(kind: str, tmdb_id: int) -> str:
    return f"tmdb:{kind}:{tmdb_id}"


def catalog_key(item: dict[str, Any]) -> str:
    if item.get("tmdbID"):
        return tmdb_key(str(item["mediaType"]), int(item["tmdbID"]))
    return f"douban:{item.get('doubanSubjectID', '')}"


def title_year_keys(item: dict[str, Any]) -> set[tuple[str, int | None]]:
    titles = [item.get("title", ""), item.get("originalTitle", ""), *(item.get("alternateTitles") or [])]
    return {(normalized_title(str(title)), item.get("year")) for title in titles if normalized_title(str(title))}


class CatalogBuilder:
    def __init__(self, provider: TMDBProvider, *, generated_at: str):
        self.provider = provider
        self.generated_at = generated_at
        self.genre_names = self._genre_names()

    def _genre_names(self) -> dict[str, dict[int, str]]:
        result: dict[str, dict[int, str]] = {}
        for kind in ("movie", "tv"):
            payload = self.provider.request(f"{TMDB_API}/genre/{kind}/list?language=zh-CN")
            result[kind] = {int(item["id"]): str(item["name"]) for item in payload.get("genres", [])}
        return result

    def collect(self, endpoint: str, *, kind: str, source: str, pages: int) -> dict[str, dict[str, Any]]:
        collected: dict[str, dict[str, Any]] = {}
        for page in range(1, pages + 1):
            separator = "&" if "?" in endpoint else "?"
            payload = self.provider.request(f"{TMDB_API}{endpoint}{separator}language=zh-CN&page={page}")
            for position, raw in enumerate(payload.get("results", []), start=(page - 1) * 20 + 1):
                if raw.get("adult") is True:
                    continue
                votes = int(raw.get("vote_count", 0) or 0)
                rating = float(raw.get("vote_average", 0) or 0)
                minimum_votes = MIN_MOVIE_VOTES if kind == "movie" else MIN_TV_VOTES
                if rating < MIN_SCORE or votes < minimum_votes:
                    continue
                key = tmdb_key(kind, int(raw["id"]))
                existing = collected.setdefault(key, {"raw": raw, "kind": kind, "sourceRanks": {}})
                existing["sourceRanks"][source] = min(position, existing["sourceRanks"].get(source, position))
        return collected

    def details(self, raw: dict[str, Any], kind: str) -> dict[str, Any]:
        params = urllib.parse.urlencode({"language": "zh-CN", "append_to_response": "credits,keywords,external_ids"})
        return self.provider.request(f"{TMDB_API}/{kind}/{int(raw['id'])}?{params}")

    def make_tmdb_item(self, candidate: dict[str, Any], *, include_details: bool) -> dict[str, Any]:
        raw = candidate["raw"]
        kind = candidate["kind"]
        detail = self.details(raw, kind) if include_details else raw
        title = str(detail.get("title") or detail.get("name") or raw.get("title") or raw.get("name") or "")
        original_title = str(detail.get("original_title") or detail.get("original_name") or raw.get("original_title") or raw.get("original_name") or "")
        release_date = str(detail.get("release_date") or detail.get("first_air_date") or raw.get("release_date") or raw.get("first_air_date") or "")
        year = int(release_date[:4]) if re.match(r"^\d{4}", release_date) else None
        genres = [str(value.get("name")) for value in detail.get("genres", []) if value.get("name")]
        if not genres:
            genres = [self.genre_names[kind][genre_id] for genre_id in raw.get("genre_ids", []) if genre_id in self.genre_names[kind]]
        crew = detail.get("credits", {}).get("crew", [])
        creator_jobs = {"Director", "Creator", "Executive Producer", "Screenplay", "Writer"}
        creators = list(dict.fromkeys(str(person["name"]) for person in crew if person.get("job") in creator_jobs and person.get("name")))[:8]
        cast = [str(person["name"]) for person in detail.get("credits", {}).get("cast", []) if person.get("name")][:10]
        keyword_payload = detail.get("keywords", {})
        keyword_rows = keyword_payload.get("keywords", keyword_payload.get("results", []))
        keywords = [str(keyword["name"]) for keyword in keyword_rows if keyword.get("name")][:20]
        countries = [str(country.get("name")) for country in detail.get("production_countries", []) if country.get("name")]
        backdrop_path = str(detail.get("backdrop_path") or raw.get("backdrop_path") or "")
        poster_path = str(detail.get("poster_path") or raw.get("poster_path") or "")
        item = {
            "key": tmdb_key(kind, int(raw["id"])),
            "tmdbID": int(raw["id"]),
            "doubanSubjectID": "",
            "mediaType": kind,
            "title": title,
            "originalTitle": original_title,
            "alternateTitles": [],
            "year": year,
            "releaseDate": release_date,
            "overview": str(detail.get("overview") or raw.get("overview") or ""),
            "genres": genres,
            "countries": countries,
            "originalLanguage": str(detail.get("original_language") or raw.get("original_language") or ""),
            "creators": creators,
            "cast": cast,
            "keywords": keywords,
            "ratings": {
                "tmdb": {"score": round(float(raw.get("vote_average", 0) or 0), 1), "count": int(raw.get("vote_count", 0) or 0), "url": f"https://www.themoviedb.org/{kind}/{int(raw['id'])}"},
                "douban": {"score": None, "count": None, "url": "", "top250Rank": None},
            },
            "popularity": {"tmdb": round(float(raw.get("popularity", 0) or 0), 3)},
            "sourceRanks": dict(candidate["sourceRanks"]),
            "images": {
                "backdrop": f"{TMDB_IMAGE}{backdrop_path}" if backdrop_path else "",
                "poster": f"https://image.tmdb.org/t/p/w780{poster_path}" if poster_path else "",
            },
            "firstSeenAt": self.generated_at,
            "lastSeenAt": self.generated_at,
        }
        return item


def merge_douban_top250(items: list[dict[str, Any]], top250: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    index: dict[tuple[str, int | None], dict[str, Any]] = {}
    for item in items:
        for key in title_year_keys(item):
            index.setdefault(key, item)
    for record in top250:
        match = None
        for title in [record["title"], *record["alternateTitles"]]:
            match = index.get((normalized_title(title), record["year"]))
            if match:
                break
        if match:
            match["doubanSubjectID"] = record["subjectID"]
            match["ratings"]["douban"] = {"score": record["rating"], "count": record["ratingCount"], "url": record["url"], "top250Rank": record["rank"]}
            match["sourceRanks"]["douban_top250"] = record["rank"]
            match["alternateTitles"] = list(dict.fromkeys([*match.get("alternateTitles", []), *record["alternateTitles"]]))
            continue
        standalone = {
            "key": f"douban:{record['subjectID']}",
            "tmdbID": None,
            "doubanSubjectID": record["subjectID"],
            "mediaType": "movie",
            "title": record["title"],
            "originalTitle": record["alternateTitles"][0] if record["alternateTitles"] else "",
            "alternateTitles": record["alternateTitles"],
            "year": record["year"],
            "releaseDate": "",
            "overview": "",
            "genres": [],
            "countries": [],
            "originalLanguage": "",
            "creators": [],
            "cast": [],
            "keywords": [],
            "ratings": {"tmdb": {"score": None, "count": None, "url": ""}, "douban": {"score": record["rating"], "count": record["ratingCount"], "url": record["url"], "top250Rank": record["rank"]}},
            "popularity": {"tmdb": None},
            "sourceRanks": {"douban_top250": record["rank"]},
            "images": {"backdrop": "", "poster": ""},
            "metadataText": record["metadataText"],
            "firstSeenAt": generated_at,
            "lastSeenAt": generated_at,
        }
        items.append(standalone)
        for key in title_year_keys(standalone):
            index.setdefault(key, standalone)
    return items


def enrich_douban(items: list[dict[str, Any]], limit: int) -> None:
    candidates = [item for item in items if not item.get("doubanSubjectID") and item.get("tmdbID")]
    candidates.sort(key=ranking_score, reverse=True)
    for item in candidates[:limit]:
        try:
            result = douban_lookup(str(item["title"]), item.get("year"))
        except (MediaProviderError, OSError, ValueError):
            continue
        rating = result.get("rating")
        numeric = float(rating) if rating not in {None, "", "暂无"} else None
        item["doubanSubjectID"] = subject_id(str(result["doubanURL"]))
        item["ratings"]["douban"] = {"score": numeric, "count": None, "url": result["doubanURL"], "top250Rank": None}
        time.sleep(0.08)


def merge_existing(new_items: list[dict[str, Any]], existing_items: Iterable[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    merged = {catalog_key(item): item for item in existing_items if catalog_key(item)}
    for item in new_items:
        key = catalog_key(item)
        previous = merged.get(key)
        if previous:
            item["firstSeenAt"] = previous.get("firstSeenAt", generated_at)
            old_ranks = previous.get("sourceRanks", {})
            item["sourceRanks"] = {**old_ranks, **item.get("sourceRanks", {})}
            old_douban = previous.get("ratings", {}).get("douban", {})
            new_douban = item.get("ratings", {}).get("douban", {})
            if old_douban.get("top250Rank") is not None:
                item["doubanSubjectID"] = previous["doubanSubjectID"]
                item["ratings"]["douban"] = old_douban
            elif not item.get("doubanSubjectID") and previous.get("doubanSubjectID"):
                item["doubanSubjectID"] = previous["doubanSubjectID"]
                item["ratings"]["douban"] = old_douban
            elif item.get("doubanSubjectID") == previous.get("doubanSubjectID"):
                if new_douban.get("count") is None and old_douban.get("count") is not None:
                    new_douban["count"] = old_douban["count"]
        merged[key] = item
    return list(merged.values())


def searchable_text(item: dict[str, Any]) -> str:
    fields: list[str] = [
        str(item.get("title", "")),
        str(item.get("originalTitle", "")),
        " ".join(item.get("alternateTitles", [])),
        str(item.get("overview", "")),
        " ".join(item.get("genres", [])),
        " ".join(item.get("countries", [])),
        " ".join(item.get("creators", [])),
        " ".join(item.get("cast", [])),
        " ".join(item.get("keywords", [])),
        str(item.get("metadataText", "")),
        str(item.get("mediaType", "")),
        str(item.get("year") or ""),
    ]
    return re.sub(r"\s+", " ", " ".join(value for value in fields if value)).strip()


def finalize(items: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    final: list[dict[str, Any]] = []
    for item in items:
        score, source = quality_score(item)
        if score < MIN_SCORE:
            continue
        douban_score = item.get("ratings", {}).get("douban", {}).get("score")
        if isinstance(douban_score, (int, float)) and float(douban_score) < MIN_SCORE:
            continue
        item["qualityScore"] = round(score, 1)
        item["qualityScoreSource"] = source
        item["rankingScore"] = ranking_score(item)
        item["searchableText"] = searchable_text(item)
        item["lastSeenAt"] = item.get("lastSeenAt") or generated_at
        final.append(item)
    final.sort(key=lambda item: (-float(item["rankingScore"]), str(item["title"])))
    return final


def build_catalog(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = utc_now()
    provider = TMDBProvider()
    builder = CatalogBuilder(provider, generated_at=generated_at)
    movie_pages = args.movie_pages if args.movie_pages is not None else (13 if args.mode == "bootstrap" else 3)
    tv_pages = args.tv_pages if args.tv_pages is not None else (10 if args.mode == "bootstrap" else 3)
    collections: list[dict[str, dict[str, Any]]] = []
    if args.mode == "bootstrap":
        collections.extend(
            [
                builder.collect("/movie/top_rated", kind="movie", source="top_rated", pages=movie_pages),
                builder.collect("/tv/top_rated", kind="tv", source="top_rated", pages=tv_pages),
            ]
        )
    collections.extend(
        [
            builder.collect("/movie/popular", kind="movie", source="popular", pages=min(movie_pages, 5)),
            builder.collect("/tv/popular", kind="tv", source="popular", pages=min(tv_pages, 5)),
            builder.collect("/trending/movie/week", kind="movie", source="trending_week", pages=1),
            builder.collect("/trending/tv/week", kind="tv", source="trending_week", pages=1),
        ]
    )
    if args.mode == "incremental":
        since = (date.today() - timedelta(days=60)).isoformat()
        movie_recent = f"/discover/movie?include_adult=false&include_video=false&sort_by=popularity.desc&primary_release_date.gte={since}"
        tv_recent = f"/discover/tv?include_adult=false&sort_by=popularity.desc&first_air_date.gte={since}"
        collections.extend(
            [
                builder.collect(movie_recent, kind="movie", source="recent", pages=3),
                builder.collect(tv_recent, kind="tv", source="recent", pages=3),
            ]
        )

    candidates: dict[str, dict[str, Any]] = {}
    for collection in collections:
        for key, candidate in collection.items():
            existing = candidates.get(key)
            if not existing:
                candidates[key] = candidate
                continue
            existing["sourceRanks"].update(candidate["sourceRanks"])

    ranked_candidates = sorted(candidates.values(), key=lambda candidate: source_rank_score(candidate["sourceRanks"]), reverse=True)
    detail_keys = {tmdb_key(candidate["kind"], int(candidate["raw"]["id"])) for candidate in ranked_candidates[: args.detail_limit]}
    items = [builder.make_tmdb_item(candidate, include_details=tmdb_key(candidate["kind"], int(candidate["raw"]["id"])) in detail_keys) for candidate in ranked_candidates]

    top250: list[dict[str, Any]] = []
    if not args.skip_douban_top250:
        cache_path = Path(args.douban_top250_cache)
        try:
            top250 = fetch_douban_top250()
            if len(top250) >= 200:
                write_douban_top250_snapshot(cache_path, top250)
            else:
                top250 = read_douban_top250_snapshot(cache_path)
        except (OSError, ValueError) as error:
            print(f"warning: Douban Top 250 unavailable: {error}")
            top250 = read_douban_top250_snapshot(cache_path)
        if top250:
            items = merge_douban_top250(items, top250, generated_at)
        else:
            print("warning: no Douban Top 250 live response or offline snapshot was available")
    enrich_douban(items, args.douban_enrich_limit)

    existing_items: list[dict[str, Any]] = []
    output_path = Path(args.output)
    if args.mode == "incremental" and output_path.exists():
        existing_items = json.loads(output_path.read_text())["items"]
    items = merge_existing(items, existing_items, generated_at)
    items = finalize(items, generated_at)
    stats = {
        "count": len(items),
        "movies": sum(item["mediaType"] == "movie" for item in items),
        "tv": sum(item["mediaType"] == "tv" for item in items),
        "doubanRated": sum(isinstance(item["ratings"]["douban"].get("score"), (int, float)) for item in items),
        "doubanTop250": sum(item["ratings"]["douban"].get("top250Rank") is not None for item in items),
        "withBackdrop": sum(bool(item["images"].get("backdrop")) for item in items),
    }
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "mode": args.mode,
        "filters": {"minimumScore": MIN_SCORE, "minimumMovieVotes": MIN_MOVIE_VOTES, "minimumTVVotes": MIN_TV_VOTES},
        "sources": [
            "https://movie.douban.com/top250",
            "https://api.themoviedb.org/3/movie/top_rated",
            "https://api.themoviedb.org/3/tv/top_rated",
            "https://api.themoviedb.org/3/movie/popular",
            "https://api.themoviedb.org/3/tv/popular",
            "https://api.themoviedb.org/3/trending/movie/week",
            "https://api.themoviedb.org/3/trending/tv/week",
        ],
        "stats": stats,
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bootstrap", "incremental"), default="bootstrap")
    parser.add_argument("--output", default="data/catalog.json")
    parser.add_argument("--movie-pages", type=int)
    parser.add_argument("--tv-pages", type=int)
    parser.add_argument("--detail-limit", type=int, default=400)
    parser.add_argument("--douban-enrich-limit", type=int, default=180)
    parser.add_argument("--skip-douban-top250", action="store_true")
    parser.add_argument("--douban-top250-cache", default="data/sources/douban-top250.json")
    parser.add_argument("--snapshot-douban-top250", metavar="PATH")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.snapshot_douban_top250:
        records = fetch_douban_top250()
        if len(records) != 250:
            raise SystemExit(f"Expected 250 Douban records, received {len(records)}")
        write_douban_top250_snapshot(Path(args.snapshot_douban_top250), records)
        print(json.dumps({"doubanTop250": len(records)}, ensure_ascii=False))
        return
    catalog = build_catalog(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(catalog["stats"], ensure_ascii=False))


if __name__ == "__main__":
    main()
