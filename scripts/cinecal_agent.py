#!/usr/bin/env python3
"""Create one grounded CineCal entry and publish AI-reviewed image crops.

The script intentionally refuses to publish when source provenance or either
widget crop fails validation. The API key is read only from MODEL_API_KEY.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI
from PIL import Image, ImageDraw, ImageOps

from media_provider import MediaProviderError, resolve_media


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "data" / "calendar.json"
PLAN_PATH = ROOT / "data" / "plan.json"
IMAGE_DIR = ROOT / "data" / "images"
REPORT_DIR = ROOT / "data" / "reports"
MODEL = os.environ.get("CINECAL_MODEL", "muse-spark-1.1")
MODEL_TIMEOUT_SECONDS = float(os.environ.get("CINECAL_MODEL_TIMEOUT_SECONDS", "150"))
MAX_DOWNLOAD_BYTES = 18_000_000
MEDIUM_ASPECT = 349.67 / 164.33
ALLOWED_IMAGE_RIGHTS = {
    value.strip().lower()
    for value in os.environ.get(
        "CINECAL_ALLOWED_IMAGE_RIGHTS",
        "public_domain,cc0,cc_by,cc_by_sa",
    ).split(",")
    if value.strip()
}
RIGHTS_MODE = os.environ.get("CINECAL_RIGHTS_MODE", "prototype").strip().lower()


class PublicationError(RuntimeError):
    """Raised when an entry is not safe or trustworthy enough to publish."""


def response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    payload = response.model_dump() if hasattr(response, "model_dump") else response
    fragments: list[str] = []
    for item in payload.get("output", []) if isinstance(payload, dict) else []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                fragments.append(content["text"])
    if not fragments:
        raise PublicationError("The model response did not contain output text.")
    return "\n".join(fragments).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S)
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise PublicationError("The model did not return a parseable JSON object.")


def collect_urls(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "url" and isinstance(child, str) and child.startswith("https://"):
                found.append(child)
            found.extend(collect_urls(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_urls(child))
    return list(dict.fromkeys(found))


def response_payload(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if isinstance(response, dict):
        return response
    raise PublicationError("Unsupported response object from the model SDK.")


def grounded_json(
    client: OpenAI, prompt: str, search_context_size: str = "medium"
) -> tuple[dict[str, Any], list[str]]:
    # Meta's Responses endpoint currently accepts the minimal web_search tool shape.
    # OpenAI-specific fields such as search_context_size and include cause a 400.
    response = client.responses.create(
        model=MODEL,
        input=prompt,
        tools=[{"type": "web_search"}],
        include=["web_search_call.results"],
    )
    payload = response_payload(response)
    urls = collect_urls(payload)
    if not urls:
        raise PublicationError("Search grounding returned no inspectable source URLs.")
    return parse_json_object(response_text(response)), urls


def text_json(client: OpenAI, prompt: str) -> dict[str, Any]:
    response = client.responses.create(model=MODEL, input=prompt)
    return parse_json_object(response_text(response))


def image_data_url(image: Image.Image, max_edge: int = 1600) -> str:
    prepared = image.copy().convert("RGB")
    prepared.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    prepared.save(output, format="JPEG", quality=88, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def vision_json(client: OpenAI, prompt: str, images: Iterable[Image.Image]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    content.extend(
        {"type": "input_image", "image_url": image_data_url(image)} for image in images
    )
    response = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": content}],
    )
    return parse_json_object(response_text(response))


def load_calendar() -> dict[str, Any]:
    with CALENDAR_PATH.open("r", encoding="utf-8") as handle:
        feed = json.load(handle)
    if feed.get("schemaVersion") != 1 or not isinstance(feed.get("entries"), list):
        raise PublicationError("data/calendar.json is not a supported schemaVersion 1 feed.")
    return feed


def recent_titles(feed: dict[str, Any], limit: int = 30) -> list[str]:
    entries = sorted(feed["entries"], key=lambda item: item.get("date", ""), reverse=True)
    return [str(item.get("title", "")) for item in entries[:limit] if item.get("title")]


def planned_selection(target_date: str) -> tuple[dict[str, Any], list[str]] | None:
    if not PLAN_PATH.exists():
        return None
    with PLAN_PATH.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)
    if plan.get("schemaVersion") != 1:
        raise PublicationError("data/plan.json is not a supported schemaVersion 1 plan.")
    for entry in plan.get("entries", []):
        if entry.get("date") != target_date or not entry.get("title"):
            continue
        sources = [
            str(signal.get("sourceURL"))
            for signal in entry.get("signals", [])
            if isinstance(signal, dict) and str(signal.get("sourceURL", "")).startswith("https://")
        ]
        sources.extend(
            str(url)
            for url in entry.get("researchSources", [])
            if str(url).startswith("https://")
        )
        return entry, list(dict.fromkeys(sources))
    return None


def discover_title(client: OpenAI, target_date: str, excluded: list[str]) -> tuple[str, list[str]]:
    prompt = f"""
You are selecting one film or prestige television series for a Chinese daily cinema calendar.
Today is {target_date}. Search the live web and choose one culturally notable work that has a
real Douban subject page and enough high-quality still photography for a home-screen widget.
Prefer works currently discussed, anniversaries, acclaimed classics, or newly released titles.
Do not repeat any of these recent selections: {json.dumps(excluded, ensure_ascii=False)}.

Return JSON only:
{{"title": "official Chinese title", "reason": "one short editorial reason"}}
""".strip()
    result, sources = grounded_json(client, prompt, search_context_size="medium")
    title = str(result.get("title", "")).strip()
    if not title:
        raise PublicationError("The discovery step did not select a title.")
    return title, sources


def research_title(
    client: OpenAI,
    title: str,
    *,
    original_title: str = "",
    release_year: int | None = None,
    media_type: str = "",
) -> tuple[dict[str, Any], list[str]]:
    print(f"[1/4] Resolving structured metadata and backdrops for {title}...", flush=True)
    try:
        metadata, metadata_sources = resolve_media(
            title,
            original_title=original_title,
            release_year=release_year,
            media_type=media_type,
        )
    except MediaProviderError as error:
        raise PublicationError(str(error)) from error

    print("[2/4] Writing original editorial copy...", flush=True)
    quote_prompt = f"""
Write one original CineCal editorial sentence in Chinese for “{title}”, under 42 Chinese
characters. It should feel literary and emotionally specific, but must not quote or closely
paraphrase dialogue, reviews, plot summaries, lyrics, subtitles, or marketing copy.
Return JSON only:
{{
  "quote": "original short Chinese sentence",
  "quoteType": "editorial",
  "quoteAttribution": "CineCal 原创编辑文案"
}}
""".strip()
    quote = text_json(client, quote_prompt)

    return {**metadata, **quote}, metadata_sources


def validate_research(item: dict[str, Any]) -> None:
    required = [
        "id",
        "title",
        "rating",
        "ratingSourceURL",
        "ratingRetrievedAt",
        "doubanURL",
        "quote",
        "quoteType",
        "quoteAttribution",
        "imageCandidates",
    ]
    missing = [key for key in required if not item.get(key)]
    if missing:
        raise PublicationError(f"Research is missing required fields: {', '.join(missing)}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(item["id"])):
        raise PublicationError("The entry id is not a safe lowercase ASCII slug.")
    if not re.fullmatch(r"(?:10(?:\.0)?|[0-9](?:\.[0-9])?|暂无)", str(item["rating"])):
        raise PublicationError("The Douban rating is outside the supported display format.")
    douban_host = urllib.parse.urlparse(str(item["doubanURL"])).hostname or ""
    if not (douban_host == "douban.com" or douban_host.endswith(".douban.com")):
        raise PublicationError("doubanURL does not point to a Douban domain.")
    if item["quoteType"] != "editorial":
        raise PublicationError("Only original editorial copy may be published.")
    if len(str(item["quote"])) > 84:
        raise PublicationError("The quote is too long for a widget.")
    if not isinstance(item["imageCandidates"], list) or len(item["imageCandidates"]) < 1:
        raise PublicationError("No image candidates were returned.")


def canonical_source(raw_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(raw_url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return host, path


def is_grounded_url(claimed_url: str, grounded_urls: Iterable[str]) -> bool:
    claimed_host, claimed_path = canonical_source(claimed_url)
    claimed_subject = re.search(r"/subject/(\d+)", claimed_path)
    for source in grounded_urls:
        source_host, source_path = canonical_source(source)
        if (claimed_host, claimed_path) == (source_host, source_path):
            return True
        if claimed_subject:
            source_subject = re.search(r"/subject/(\d+)", source_path)
            if source_subject and source_subject.group(1) == claimed_subject.group(1):
                return True
        if claimed_host == source_host and claimed_path and (
            source_path.startswith(claimed_path + "/") or claimed_path.startswith(source_path + "/")
        ):
            return True
    return False


def enforce_grounded_provenance(
    item: dict[str, Any], grounded_urls: list[str], rights_mode: str = RIGHTS_MODE
) -> None:
    required_grounded_fields = ["ratingSourceURL"]
    if rights_mode == "production":
        required_grounded_fields.append("doubanURL")
    for key in required_grounded_fields:
        if not is_grounded_url(str(item[key]), grounded_urls):
            raise PublicationError(f"{key} was not present in the grounded search evidence.")

    grounded_candidates = []
    for candidate in item["imageCandidates"]:
        image_url = str(candidate.get("imageURL", ""))
        source_page = str(candidate.get("sourcePageURL", ""))
        license_url = str(candidate.get("licenseURL", ""))
        rights_status = str(candidate.get("rightsStatus", "")).strip().lower()
        commercial_allowed = candidate.get("commercialUseAllowed") is True
        modification_allowed = candidate.get("modificationAllowed") is True
        grounded_asset = image_url.startswith("https://") and source_page.startswith("https://") and (
            is_grounded_url(source_page, grounded_urls) or is_grounded_url(image_url, grounded_urls)
        ) and candidate.get("credit") and candidate.get("rightsHolder") and rights_status
        production_cleared = (
            license_url.startswith("https://")
            and is_grounded_url(license_url, grounded_urls)
            and rights_status in ALLOWED_IMAGE_RIGHTS
            and commercial_allowed
            and modification_allowed
        )
        if grounded_asset and (rights_mode == "prototype" or production_cleared):
            grounded_candidates.append(candidate)
    if not grounded_candidates:
        raise PublicationError(
            "No image candidate met the grounded source and configured rights-mode requirements."
        )
    item["imageCandidates"] = grounded_candidates


def validate_public_https_url(raw_url: str) -> None:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PublicationError("Asset URLs must be public HTTPS URLs.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise PublicationError(f"Could not resolve image host {parsed.hostname}.") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise PublicationError("Image URL resolved to a non-public network address.")


def download_image(raw_url: str, source_page_url: str = "") -> Image.Image:
    validate_public_https_url(raw_url)
    parsed = urllib.parse.urlparse(raw_url)
    referers = []
    if source_page_url.startswith("https://"):
        referers.append(source_page_url)
    referers.extend([f"{parsed.scheme}://{parsed.netloc}/", ""])
    data: bytes | None = None
    last_error: Exception | None = None
    for referer in dict.fromkeys(referers):
        headers = {
            # Image CDNs commonly reject non-browser agents or require a
            # source-page Referer even for public promotional stills.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        request = urllib.request.Request(raw_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                final_url = response.geturl()
                validate_public_https_url(final_url)
                content_type = response.headers.get_content_type()
                if not content_type.startswith("image/"):
                    raise PublicationError(f"Candidate returned {content_type}, not an image.")
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_DOWNLOAD_BYTES:
                    raise PublicationError("Candidate image exceeds the download limit.")
                data = response.read(MAX_DOWNLOAD_BYTES + 1)
            break
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in {401, 403, 429}:
                raise
    if data is None:
        if last_error is not None:
            raise last_error
        raise PublicationError("Candidate image could not be downloaded.")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise PublicationError("Candidate image exceeds the download limit.")
    try:
        image = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    except Exception as error:
        raise PublicationError("Candidate image could not be decoded.") from error
    if image.width < 900 or image.height < 450:
        raise PublicationError(f"Candidate is too small ({image.width}×{image.height}).")
    return image


def crop_plan(client: OpenAI, image: Image.Image, title: str) -> dict[str, Any]:
    prompt = f"""
You are the photo editor for an iPhone movie-calendar widget. Analyze this still for “{title}”.
Return crop rectangles on the normalized 0–1000 coordinate grid of the exact image supplied.

First verify that the supplied image is visibly a genuine still or official promotional image
from the exact film/series. Reject stage adaptations, paintings, fan art, generic thematic images,
title-word associations, and images whose connection to the screen work cannot be established.

Design two crops:
- square: 1:1. The date occupies the upper-left; title, rating, and quote occupy the lower 38%.
- medium: 2.128:1. Date occupies lower-left; title/quote occupy lower-middle; rating is lower-right.

Keep faces, eyes, and the main dramatic action outside those text zones whenever possible. Do not
cut through faces or important hands. Preserve balanced negative space and cinematic tension.
Reject typography-heavy, watermarked, collage, or visually incoherent source images.

Return JSON only:
{{
  "sourceAcceptable": true,
  "workIdentityMatch": true,
  "identityReason": "visual reason this belongs to the exact screen work",
  "sourceReason": "...",
  "subjects": [{{"label": "person", "bbox": [x1, y1, x2, y2]}}],
  "square": {{"crop": [x1, y1, x2, y2], "compositionScore": 0, "reason": "..."}},
  "medium": {{"crop": [x1, y1, x2, y2], "compositionScore": 0, "reason": "..."}}
}}
Scores use a strict 0–10 scale. A score below 7 means the crop should not publish.
""".strip()
    return vision_json(client, prompt, [image])


def corrected_crop_box(
    image_size: tuple[int, int], normalized_box: list[Any], target_aspect: float
) -> tuple[int, int, int, int]:
    if not isinstance(normalized_box, list) or len(normalized_box) != 4:
        raise PublicationError("The model returned an invalid crop rectangle.")
    width, height = image_size
    values = [max(0.0, min(1000.0, float(value))) for value in normalized_box]
    x1, y1, x2, y2 = values
    if x2 <= x1 or y2 <= y1:
        raise PublicationError("The model returned an empty crop rectangle.")

    left, top = x1 / 1000 * width, y1 / 1000 * height
    right, bottom = x2 / 1000 * width, y2 / 1000 * height
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    crop_width, crop_height = right - left, bottom - top

    if crop_width / crop_height < target_aspect:
        crop_width = crop_height * target_aspect
    else:
        crop_height = crop_width / target_aspect

    scale = min(1.0, width / crop_width, height / crop_height)
    crop_width *= scale
    crop_height *= scale
    center_x = max(crop_width / 2, min(width - crop_width / 2, center_x))
    center_y = max(crop_height / 2, min(height - crop_height / 2, center_y))
    box = (
        int(round(center_x - crop_width / 2)),
        int(round(center_y - crop_height / 2)),
        int(round(center_x + crop_width / 2)),
        int(round(center_y + crop_height / 2)),
    )
    if box[2] - box[0] < 320 or box[3] - box[1] < 180:
        raise PublicationError("The proposed crop is too tight for a widget.")
    return box


def render_crop(
    image: Image.Image,
    normalized_box: list[Any],
    aspect: float,
    output_size: tuple[int, int],
) -> Image.Image:
    box = corrected_crop_box(image.size, normalized_box, aspect)
    return image.crop(box).resize(output_size, Image.Resampling.LANCZOS)


def review_overlay(image: Image.Image, variant: str) -> Image.Image:
    preview = image.convert("RGBA")
    overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = preview.size
    fill = (255, 70, 45, 92)
    outline = (255, 180, 150, 210)
    if variant == "small":
        zones = [
            (0.05, 0.06, 0.48, 0.38),
            (0.05, 0.61, 0.95, 0.95),
        ]
    else:
        zones = [
            (0.04, 0.48, 0.28, 0.94),
            (0.27, 0.56, 0.78, 0.94),
            (0.76, 0.58, 0.96, 0.80),
        ]
    for x1, y1, x2, y2 in zones:
        draw.rounded_rectangle(
            (x1 * width, y1 * height, x2 * width, y2 * height),
            radius=max(8, int(height * 0.035)),
            fill=fill,
            outline=outline,
            width=max(2, int(height * 0.008)),
        )
    return Image.alpha_composite(preview, overlay).convert("RGB")


def final_quality_review(
    client: OpenAI, small: Image.Image, medium: Image.Image, title: str
) -> dict[str, Any]:
    prompt = f"""
You are doing final visual QA for two crops of “{title}”. The first image is the square widget;
the second is the medium rectangular widget. Translucent red boxes mark the exact zones where date,
title, rating, and quote will be drawn.

Pass only if both crops are attractive and no face, eye, essential action, or identifying detail is
hidden by a red text zone. Bodies may extend behind text when faces and the dramatic focal point stay
clear. Reject awkward decapitation, edge crowding, empty crops, watermarks, embedded typography,
or a crop that loses the story of the original frame.

Return JSON only:
{{
  "small": {{"pass": true, "score": 0, "reason": "..."}},
  "medium": {{"pass": true, "score": 0, "reason": "..."}},
  "overallPass": true
}}
Use a strict 0–10 score. Both scores must be at least 7 to pass.
""".strip()
    return vision_json(client, prompt, [review_overlay(small, "small"), review_overlay(medium, "medium")])


def passes_plan(plan: dict[str, Any]) -> bool:
    try:
        return bool(plan["sourceAcceptable"]) and bool(plan["workIdentityMatch"]) and all(
            float(plan[name]["compositionScore"]) >= 7 for name in ("square", "medium")
        )
    except (KeyError, TypeError, ValueError):
        return False


def passes_final_review(review: dict[str, Any]) -> bool:
    try:
        return (
            bool(review["overallPass"])
            and bool(review["small"]["pass"])
            and bool(review["medium"]["pass"])
            and float(review["small"]["score"]) >= 7
            and float(review["medium"]["score"]) >= 7
        )
    except (KeyError, TypeError, ValueError):
        return False


def select_and_crop_image(
    client: OpenAI, research: dict[str, Any]
) -> tuple[Image.Image, Image.Image, dict[str, Any], dict[str, Any], dict[str, Any]]:
    failures: list[str] = []
    for index, candidate in enumerate(research["imageCandidates"][:12], start=1):
        try:
            print(f"[3/4] Reviewing API image candidate {index}...", flush=True)
            image_url = str(candidate["imageURL"])
            image = download_image(image_url, str(candidate.get("sourcePageURL", "")))
            plan = crop_plan(client, image, str(research["title"]))
            if not passes_plan(plan):
                raise PublicationError("AI crop plan scored below the publication threshold.")
            small = render_crop(image, plan["square"]["crop"], 1.0, (760, 760))
            medium = render_crop(image, plan["medium"]["crop"], MEDIUM_ASPECT, (1080, 508))
            review = final_quality_review(client, small, medium, str(research["title"]))
            if not passes_final_review(review):
                raise PublicationError("Final AI overlay review rejected one or both crops.")
            return small, medium, candidate, plan, review
        except Exception as error:
            failures.append(f"candidate {index}: {error}")
    raise PublicationError("No image candidate passed:\n" + "\n".join(failures))


def raw_github_url(repository: str, branch: str, relative_path: Path) -> str:
    encoded = "/".join(urllib.parse.quote(part) for part in relative_path.parts)
    return f"https://raw.githubusercontent.com/{repository}/{urllib.parse.quote(branch)}/{encoded}"


def save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, format="JPEG", quality=88, optimize=True, progressive=True)


def publish(
    feed: dict[str, Any],
    target_date: str,
    research: dict[str, Any],
    discovery_sources: list[str],
    research_sources: list[str],
    small: Image.Image,
    medium: Image.Image,
    candidate: dict[str, Any],
    plan: dict[str, Any],
    review: dict[str, Any],
) -> None:
    repository = os.environ.get("CINECAL_REPOSITORY", "eshoyuan/CineCalData")
    branch = os.environ.get("CINECAL_BRANCH", "main")
    slug = str(research["id"])
    small_rel = Path("data") / "images" / f"{target_date}-{slug}-small.jpg"
    medium_rel = Path("data") / "images" / f"{target_date}-{slug}-medium.jpg"
    report_rel = Path("data") / "reports" / f"{target_date}-{slug}.json"
    save_jpeg(small, ROOT / small_rel)
    save_jpeg(medium, ROOT / medium_rel)

    all_sources = list(dict.fromkeys(discovery_sources + research_sources))
    report = {
        "date": target_date,
        "model": MODEL,
        "researchSources": all_sources,
        "selectedImage": candidate,
        "cropPlan": plan,
        "finalReview": review,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    report_path = ROOT / report_rel
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    entry = {
        "date": target_date,
        "id": slug,
        "title": str(research["title"]),
        "rating": str(research["rating"]),
        "ratingSourceURL": str(research["ratingSourceURL"]),
        "ratingRetrievedAt": str(research["ratingRetrievedAt"]),
        "quote": str(research["quote"]),
        "quoteType": str(research["quoteType"]),
        "quoteAttribution": str(research["quoteAttribution"]),
        "imageURL": raw_github_url(repository, branch, medium_rel),
        "imageURLSmall": raw_github_url(repository, branch, small_rel),
        "imageURLMedium": raw_github_url(repository, branch, medium_rel),
        "imageSourcePageURL": str(candidate.get("sourcePageURL", "")),
        "imageCredit": str(candidate.get("credit", "")),
        "imageRightsHolder": str(candidate.get("rightsHolder", "")),
        "imageRightsStatus": str(candidate.get("rightsStatus", "")),
        "imageLicenseName": str(candidate.get("licenseName", "")),
        "imageLicenseURL": str(candidate.get("licenseURL", "")),
        "editorReportURL": raw_github_url(repository, branch, report_rel),
        "doubanURL": str(research["doubanURL"]),
        "tmdbID": research.get("tmdbID"),
        "tmdbURL": str(research.get("tmdbURL", "")),
        "mediaType": str(research.get("mediaType", "")),
        "releaseDate": str(research.get("releaseDate", "")),
    }
    feed["entries"] = [item for item in feed["entries"] if item.get("date") != target_date]
    feed["entries"].append(entry)
    feed["entries"].sort(key=lambda item: item.get("date", ""))
    feed["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    CALENDAR_PATH.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat(), help="calendar date, YYYY-MM-DD")
    parser.add_argument("--movie", default=os.environ.get("CINECAL_MOVIE", "").strip())
    args = parser.parse_args()
    try:
        target_date = date.fromisoformat(args.date).isoformat()
    except ValueError as error:
        raise SystemExit(f"Invalid --date: {error}") from error

    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("MODEL_API_KEY is required. Store it as a GitHub Actions secret.")

    feed = load_calendar()
    client = OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=api_key,
        timeout=MODEL_TIMEOUT_SECONDS,
        # A slow candidate should be skipped, not retried for another full
        # timeout while the remaining API-provided backdrops wait.
        max_retries=0,
    )
    if args.movie:
        title = args.movie
        plan_entry: dict[str, Any] = {}
        discovery_sources: list[str] = []
    elif planned := planned_selection(target_date):
        plan_entry, discovery_sources = planned
        title = str(plan_entry["title"])
        print(f"Using cached editorial plan: {title}", flush=True)
    else:
        plan_entry = {}
        print("No cached plan entry; discovering a title from the live web...", flush=True)
        title, discovery_sources = discover_title(client, target_date, recent_titles(feed))

    raw_year = plan_entry.get("releaseYear")
    try:
        release_year = int(raw_year) if raw_year else None
    except (TypeError, ValueError):
        release_year = None
    research, research_sources = research_title(
        client,
        title,
        original_title=str(plan_entry.get("originalTitle", "")),
        release_year=release_year,
        media_type=str(plan_entry.get("mediaType", "")),
    )
    validate_research(research)
    enforce_grounded_provenance(research, research_sources, RIGHTS_MODE)
    small, medium, candidate, plan, review = select_and_crop_image(client, research)
    publish(
        feed,
        target_date,
        research,
        discovery_sources,
        research_sources,
        small,
        medium,
        candidate,
        plan,
        review,
    )
    print("[4/4] Saved feed, image crops, and provenance report.", flush=True)
    print(f"Published {research['title']} for {target_date}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicationError as error:
        print(f"Publication blocked: {error}", file=sys.stderr)
        raise SystemExit(1)
