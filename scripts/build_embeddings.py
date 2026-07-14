#!/usr/bin/env python3
"""Build compact 128-dimensional catalog embeddings on an Apple Silicon Mac."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_MODEL = "mlx-community/embeddinggemma-300m-4bit"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def embedding_text(item: dict[str, Any]) -> str:
    fields = [
        item.get("title", ""),
        item.get("originalTitle", ""),
        " ".join(item.get("alternateTitles", [])),
        str(item.get("year") or ""),
        " ".join(item.get("genres", [])),
        " ".join(item.get("countries", [])),
        " ".join(item.get("creators", [])),
        " ".join(item.get("cast", [])[:8]),
        " ".join(item.get("keywords", [])[:12]),
        item.get("overview", ""),
    ]
    content = " | ".join(str(value).strip() for value in fields if str(value).strip())
    return f"title: {item.get('title', '')} | text: {content}"


def normalize_mrl(vectors: np.ndarray, dimensions: int) -> np.ndarray:
    truncated = np.asarray(vectors[:, :dimensions], dtype=np.float32)
    norms = np.linalg.norm(truncated, axis=1, keepdims=True)
    return truncated / np.maximum(norms, 1e-12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.json")
    parser.add_argument("--output", default="data/embeddings.f16")
    parser.add_argument("--index", default="data/embeddings-index.json")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dimensions", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.dimensions <= 768:
        raise SystemExit("--dimensions must be between 1 and 768")

    from mlx_embeddings.utils import load

    catalog_path = Path(args.catalog)
    catalog = json.loads(catalog_path.read_text())
    items = catalog["items"]
    model, tokenizer = load(args.model)
    batches: list[np.ndarray] = []

    for start in range(0, len(items), args.batch_size):
        batch = items[start : start + args.batch_size]
        encoded = tokenizer.batch_encode_plus(
            [embedding_text(item) for item in batch],
            return_tensors="mlx",
            padding=True,
            truncation=True,
            max_length=args.max_length,
        )
        output = model(encoded["input_ids"], attention_mask=encoded["attention_mask"])
        batches.append(normalize_mrl(np.array(output.text_embeds), args.dimensions))
        print(f"embedded {min(start + len(batch), len(items))}/{len(items)}", flush=True)

    matrix = np.concatenate(batches, axis=0).astype("<f2", copy=False)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(matrix.tobytes(order="C"))
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()

    for row, item in enumerate(items):
        item["embeddingRow"] = row

    built_at = utc_now()
    index = {
        "schemaVersion": 1,
        "generatedAt": built_at,
        "model": args.model,
        "format": "little-endian float16 row-major",
        "dimensions": args.dimensions,
        "count": len(items),
        "sha256": digest,
        "keys": [item["key"] for item in items],
    }
    index_path = Path(args.index)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    catalog["embeddingIndex"] = {
        "url": "https://raw.githubusercontent.com/eshoyuan/CineCalData/main/data/embeddings-index.json",
        "vectorsURL": "https://raw.githubusercontent.com/eshoyuan/CineCalData/main/data/embeddings.f16",
        "dimensions": args.dimensions,
        "model": args.model,
        "generatedAt": built_at,
    }
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"count": len(items), "dimensions": args.dimensions, "bytes": output_path.stat().st_size, "sha256": digest}))


if __name__ == "__main__":
    main()
