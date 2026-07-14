#!/usr/bin/env python3
"""Resolve CineCal metadata and stable landscape assets without an LLM."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/original"
DOUBAN_SUGGEST = "https://www.douban.com/j/search_suggest"
USER_AGENT = "CineCal/1.0 (+https://github.com/eshoyuan/CineCalData)"


class MediaProviderError(RuntimeError):
    """Raised when structured media sources cannot resolve a requested work."""


def request_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.headers.get_content_type() not in {"application/json", "text/json"}:
            raise MediaProviderError(f"Structured source returned {response.headers.get_content_type()}.")
        return json.loads(response.read())


def normalized_title(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def title_without_season(value: str) -> tuple[str, int | None]:
    match = re.search(r"\s*第\s*([0-9一二三四五六七八九十]+)\s*季\s*$", value)
    if not match:
        return value.strip(), None
    raw = match.group(1)
    chinese = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    season = int(raw) if raw.isdigit() else chinese.get(raw)
    return value[: match.start()].strip(), season


def douban_lookup(title: str, release_year: int | None = None) -> dict[str, Any]:
    query_title, _ = title_without_season(title)
    url = f"{DOUBAN_SUGGEST}?{urllib.parse.urlencode({'debug': 'true', 'q': query_title})}"
    payload = request_json(url, {"Referer": "https://www.douban.com/"})
    cards = [card for card in payload.get("cards", []) if card.get("type") in {"movie", "tv"}]
    if not cards:
        raise MediaProviderError(f"Douban suggestion API returned no match for {title}.")

    wanted = normalized_title(query_title)
    def score(card: dict[str, Any]) -> tuple[int, int]:
        exact = int(normalized_title(str(card.get("title", ""))) == wanted)
        year = int(bool(release_year) and str(card.get("year", "")) == str(release_year))
        return exact, year

    card = max(cards, key=score)
    subtitle = str(card.get("card_subtitle", ""))
    rating_match = re.search(r"(?<!\d)(10(?:\.0)?|[0-9](?:\.[0-9])?)分", subtitle)
    douban_url = str(card.get("url", ""))
    if not douban_url.startswith("https://"):
        raise MediaProviderError("Douban suggestion result did not contain a public subject URL.")
    return {
        "rating": rating_match.group(1) if rating_match else "暂无",
        "ratingSourceURL": url,
        "ratingRetrievedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "doubanURL": douban_url,
        "doubanYear": str(card.get("year", "")),
    }


class TMDBProvider:
    def __init__(self, token: str | None = None, api_key: str | None = None):
        self.token = (token or os.environ.get("TMDB_API_TOKEN", "")).strip()
        self.api_key = (api_key or os.environ.get("TMDB_API_KEY", "")).strip()
        if not self.token and not self.api_key:
            raise MediaProviderError(
                "TMDB_API_TOKEN or TMDB_API_KEY is required for stable metadata and image retrieval."
            )

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def request(self, url: str) -> dict[str, Any]:
        if self.api_key and not self.token:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urllib.parse.urlencode({'api_key': self.api_key})}"
        return request_json(url, self.headers)

    def resolve(
        self,
        title: str,
        *,
        original_title: str = "",
        release_year: int | None = None,
        media_type: str = "",
    ) -> dict[str, Any]:
        query_title, season_number = title_without_season(title)
        params = urllib.parse.urlencode(
            {"query": query_title, "language": "zh-CN", "include_adult": "false"}
        )
        search = self.request(f"{TMDB_API}/search/multi?{params}")
        results = [
            item for item in search.get("results", [])
            if item.get("media_type") in {"movie", "tv"}
        ]
        if not results and original_title:
            params = urllib.parse.urlencode(
                {"query": original_title, "language": "zh-CN", "include_adult": "false"}
            )
            search = self.request(f"{TMDB_API}/search/multi?{params}")
            results = [
                item for item in search.get("results", [])
                if item.get("media_type") in {"movie", "tv"}
            ]
        if not results:
            raise MediaProviderError(f"TMDB returned no movie/series match for {title}.")

        wanted_titles = {
            normalized_title(value) for value in (query_title, original_title) if value
        }
        wanted_type = {"series": "tv", "tv": "tv", "movie": "movie", "film": "movie"}.get(
            media_type.casefold(), ""
        )

        def score(item: dict[str, Any]) -> float:
            names = {
                normalized_title(str(item.get(key, "")))
                for key in ("title", "original_title", "name", "original_name")
                if item.get(key)
            }
            value = 100 if wanted_titles & names else 0
            date_value = str(item.get("release_date") or item.get("first_air_date") or "")
            if release_year and date_value.startswith(str(release_year)):
                value += 35
            if wanted_type and item.get("media_type") == wanted_type:
                value += 20
            value += min(float(item.get("popularity", 0) or 0), 100) / 100
            return value

        match = max(results, key=score)
        kind = str(match["media_type"])
        tmdb_id = int(match["id"])
        detail_params = urllib.parse.urlencode(
            {
                "language": "zh-CN",
                "append_to_response": "images,credits",
                "include_image_language": "zh,en,null",
            }
        )
        detail = self.request(f"{TMDB_API}/{kind}/{tmdb_id}?{detail_params}")
        backdrops = [
            image for image in detail.get("images", {}).get("backdrops", [])
            if image.get("file_path") and int(image.get("width", 0)) >= 900
            and int(image.get("height", 0)) >= 450
        ]
        backdrops.sort(
            key=lambda image: (
                int(image.get("vote_count", 0)),
                float(image.get("vote_average", 0) or 0),
                int(image.get("width", 0)),
            ),
            reverse=True,
        )
        if not backdrops:
            raise MediaProviderError(f"TMDB match {tmdb_id} has no usable landscape backdrops.")

        page_kind = "tv" if kind == "tv" else "movie"
        source_page = f"https://www.themoviedb.org/{page_kind}/{tmdb_id}"
        candidates = []
        for image in backdrops[:12]:
            image_url = f"{TMDB_IMAGE}{image['file_path']}"
            candidates.append(
                {
                    "imageURL": image_url,
                    "sourcePageURL": source_page,
                    "credit": "The Movie Database (TMDB)",
                    "rightsHolder": "respective production/rightsholder",
                    "rightsStatus": "official_promotional",
                    "licenseName": "TMDB-hosted promotional artwork; verify production rights",
                    "licenseURL": "",
                    "commercialUseAllowed": False,
                    "modificationAllowed": False,
                    "tmdbFilePath": str(image["file_path"]),
                    "width": int(image.get("width", 0)),
                    "height": int(image.get("height", 0)),
                }
            )

        display_title = str(detail.get("title") or detail.get("name") or title)
        original = str(detail.get("original_title") or detail.get("original_name") or "")
        date_value = str(detail.get("release_date") or detail.get("first_air_date") or "")
        return {
            "id": f"tmdb-{kind}-{tmdb_id}" + (f"-season-{season_number}" if season_number else ""),
            "title": display_title,
            "originalTitle": original,
            "mediaType": kind,
            "releaseDate": date_value,
            "releaseYear": int(date_value[:4]) if re.match(r"^\d{4}", date_value) else release_year,
            "overview": str(detail.get("overview", "")),
            "tmdbID": tmdb_id,
            "tmdbURL": source_page,
            "seasonNumber": season_number,
            "imageCandidates": candidates,
        }


def resolve_media(
    title: str,
    *,
    original_title: str = "",
    release_year: int | None = None,
    media_type: str = "",
) -> tuple[dict[str, Any], list[str]]:
    metadata = TMDBProvider().resolve(
        title,
        original_title=original_title,
        release_year=release_year,
        media_type=media_type,
    )
    douban = douban_lookup(title, metadata.get("releaseYear") or release_year)
    result = {**metadata, **douban}
    sources = [result["tmdbURL"], result["ratingSourceURL"], result["doubanURL"]]
    sources.extend(candidate["imageURL"] for candidate in result["imageCandidates"])
    return result, sources
