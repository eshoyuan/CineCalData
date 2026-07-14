#!/usr/bin/env python3
"""Download catalog backdrops and create widget-ready crops on macOS."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


RAW_ROOT = "https://raw.githubusercontent.com/eshoyuan/CineCalData/main"
USER_AGENT = "CineCalCropper/1.0 (+https://github.com/eshoyuan/CineCalData)"


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_id(item: dict[str, Any]) -> str:
    if item.get("tmdbID"):
        return f"tmdb/{item['mediaType']}/{int(item['tmdbID'])}"
    return f"douban/{re.sub(r'[^0-9A-Za-z_-]+', '-', str(item.get('doubanSubjectID', 'unknown')))}"


def download_url(url: str) -> str:
    return url.replace("/t/p/original/", "/t/p/w1280/")


def download_image(item: dict[str, Any], cache_root: Path) -> tuple[str, Path] | None:
    source = str(item.get("images", {}).get("backdrop", ""))
    if not source:
        return None
    identifier = safe_id(item)
    destination = cache_root / f"{identifier}.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 10_000:
        return identifier, destination
    request = urllib.request.Request(download_url(source), headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read()
    if len(payload) < 10_000:
        raise RuntimeError(f"Image response was too small for {identifier}")
    destination.write_bytes(payload)
    return identifier, destination


def compile_analyzer(source: Path, destination: Path) -> None:
    subprocess.run(["swiftc", str(source), "-O", "-o", str(destination)], check=True)


def analyze_images(executable: Path, images: list[tuple[str, Path]]) -> dict[str, dict[str, Any]]:
    payload = {"items": [{"id": identifier, "path": str(path.resolve())} for identifier, path in images]}
    result = subprocess.run(
        [str(executable)],
        input=json.dumps(payload).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    if result.stderr:
        print(result.stderr.decode(errors="replace"), end="")
    return json.loads(result.stdout)


def intersection_area(a: Box, b: Box) -> float:
    width = max(0.0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    height = max(0.0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    return width * height


def candidate_crops(source_width: int, source_height: int, target_aspect: float, steps: int = 40) -> list[Box]:
    source_aspect = source_width / source_height
    if source_aspect > target_aspect:
        width = target_aspect / source_aspect
        return [Box((1 - width) * index / steps, 0, width, 1) for index in range(steps + 1)]
    height = source_aspect / target_aspect
    return [Box(0, (1 - height) * index / steps, 1, height) for index in range(steps + 1)]


def choose_crop(
    source_width: int,
    source_height: int,
    target_aspect: float,
    faces: list[Box],
    saliency: list[Box],
    *,
    size: str,
) -> Box:
    candidates = candidate_crops(source_width, source_height, target_aspect)
    if not faces and not saliency:
        return candidates[len(candidates) // 2]
    target_x, target_y = ((0.62, 0.33) if size == "small" else (0.69, 0.31))

    def score(crop: Box) -> float:
        value = -0.12 * ((crop.x + crop.width / 2 - 0.5) ** 2 + (crop.y + crop.height / 2 - 0.5) ** 2)
        regions = [*((face, 8.0, True) for face in faces), *((region, 2.5, False) for region in saliency)]
        for box, weight, is_face in regions:
            area = max(box.width * box.height, 1e-6)
            coverage = intersection_area(box, crop) / area
            center_x, center_y = box.center
            local_x = (center_x - crop.x) / crop.width
            local_y = (center_y - crop.y) / crop.height
            distance = (local_x - target_x) ** 2 + (local_y - target_y) ** 2
            value += weight * coverage - weight * 0.42 * distance
            if is_face and local_y > 0.58 and 0 <= local_x <= 0.88:
                value -= weight * 1.7
        return value

    return max(candidates, key=score)


def crop_pixels(box: Box, width: int, height: int) -> tuple[int, int, int, int]:
    left = max(0, min(width - 1, round(box.x * width)))
    top = max(0, min(height - 1, round(box.y * height)))
    right = max(left + 1, min(width, round((box.x + box.width) * width)))
    bottom = max(top + 1, min(height, round((box.y + box.height) * height)))
    return left, top, right, bottom


def box_dict(box: Box) -> dict[str, float]:
    return {"x": round(box.x, 6), "y": round(box.y, 6), "width": round(box.width, 6), "height": round(box.height, 6)}


def process_item(
    item: dict[str, Any],
    source_path: Path,
    analysis: dict[str, Any],
    output_root: Path,
    public_output_root: str,
) -> None:
    identifier = safe_id(item)
    faces = [Box(**box) for box in analysis.get("faces", [])]
    saliency = [Box(**box) for box in analysis.get("saliency", [])]
    with Image.open(source_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        small_crop = choose_crop(image.width, image.height, 1.0, faces, saliency, size="small")
        medium_crop = choose_crop(image.width, image.height, 1080 / 508, faces, saliency, size="medium")
        variants = [
            ("small", small_crop, (760, 760)),
            ("medium", medium_crop, (1080, 508)),
        ]
        for name, crop, target in variants:
            destination = output_root / f"{identifier}-{name}.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            rendered = image.crop(crop_pixels(crop, image.width, image.height)).resize(target, Image.Resampling.LANCZOS)
            rendered.save(destination, format="JPEG", quality=84, optimize=True, progressive=True)

    base = public_output_root.rstrip("/")
    item["images"]["small"] = f"{RAW_ROOT}/{base}/{identifier}-small.jpg"
    item["images"]["medium"] = f"{RAW_ROOT}/{base}/{identifier}-medium.jpg"
    item["images"]["cropSmall"] = box_dict(small_crop)
    item["images"]["cropMedium"] = box_dict(medium_crop)
    item["images"]["composition"] = {"faces": len(faces), "salientRegions": len(saliency), "analyzer": "Apple Vision attention+faces v1"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.json")
    parser.add_argument("--output-root", default="data/catalog-images")
    parser.add_argument("--cache-root", default=".cache/catalog-sources")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N image-backed items (0 means all).")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Only process entries that do not already have both widget image URLs.",
    )
    parser.add_argument("--vision-source", default="scripts/vision_analyzer.swift")
    parser.add_argument("--repo-root", default=".", help="Repository root used to build public image URLs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog_path = Path(args.catalog)
    catalog = json.loads(catalog_path.read_text())
    items = [item for item in catalog["items"] if item.get("images", {}).get("backdrop")]
    if args.missing_only:
        items = [
            item for item in items
            if not (
                item.get("images", {}).get("small")
                and item.get("images", {}).get("medium")
            )
        ]
    if not items:
        print(json.dumps({"requested": 0, "processed": 0, "failed": 0, "unchanged": True}))
        return
    if args.limit:
        items = items[: args.limit]
    cache_root = Path(args.cache_root)
    output_root = Path(args.output_root)
    repo_root = Path(args.repo_root).resolve()
    try:
        public_output_root = output_root.resolve().relative_to(repo_root).as_posix()
    except ValueError as error:
        raise SystemExit("--output-root must be inside --repo-root so its public URL is stable") from error
    downloads: list[tuple[str, Path]] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(download_image, item, cache_root): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                if result:
                    downloads.append(result)
            except Exception as error:  # Keep the batch useful when an individual asset disappears.
                failures.append(f"{item.get('key')}: {error}")
    downloads.sort()

    with tempfile.TemporaryDirectory(prefix="cinecal-vision-") as temporary:
        analyzer = Path(temporary) / "vision-analyzer"
        compile_analyzer(Path(args.vision_source), analyzer)
        analyses = analyze_images(analyzer, downloads)

    item_index = {safe_id(item): item for item in items}
    path_index = dict(downloads)
    processed = 0
    for identifier in sorted(path_index):
        process_item(
            item_index[identifier],
            path_index[identifier],
            analyses.get(identifier, {}),
            output_root,
            public_output_root,
        )
        processed += 1
    catalog["imagesMaterializedAt"] = utc_now()
    materialized_total = sum(
        bool(item.get("images", {}).get("small") and item.get("images", {}).get("medium"))
        for item in catalog["items"]
    )
    catalog["imageStats"] = {
        "requested": len(items),
        "processed": processed,
        "failed": len(failures),
        "materializedTotal": materialized_total,
    }
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    for failure in failures:
        print(f"warning: {failure}")
    print(json.dumps(catalog["imageStats"], ensure_ascii=False))


if __name__ == "__main__":
    main()
