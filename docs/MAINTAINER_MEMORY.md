# CineCalData maintainer memory

## Role of this repository

CineCalData is a public static backend and preview site. It is deliberately not
a user-account backend: it publishes immutable JSON, processed images, compact
movie embeddings, and provenance reports. User feedback and personalization
remain on each iPhone.

## Data pipeline

1. Bootstrap and incremental catalog jobs combine Douban Top 250 seeds with
   TMDB top-rated, popular, trending, and recent titles.
2. Stable TMDB IDs are the primary deduplication key. Normalized title and year
   are the secondary fallback.
3. Douban enrichment supplies the canonical subject link and rating. A known
   Douban score below 6.0 disqualifies a widget card.
4. Apple Vision face and attention saliency analysis creates independent 1:1
   and 2.128:1 crops. Materialized assets are 760 x 760 and 1080 x 508 JPEGs.
5. Editorial enrichment produces short original CineCal copy. Metadata,
   ratings, identifiers, and image URLs come from mechanical sources rather
   than the language model.
6. Embeddings are built offline on Apple Silicon with
   `mlx-community/embeddinggemma-300m-4bit`, truncated and re-normalized to 128
   dimensions, then stored as little-endian row-major Float16.
7. `widget-catalog.json` exposes only complete client-ready cards.
8. `calendar.json` maintains a rolling date horizon; each phone chooses its own
   date key. There is no shared current-day pointer.

## Current snapshot

As of 2026-07-14:

- Embedding index: 1,183 rows, 128 dimensions.
- Structured catalog: 1,170 records.
- Records with materialized small and medium images: 1,159.
- Widget-ready cards: 996.
- Date-keyed calendar: 733 entries from 2026-07-13 through 2028-07-14.

Counts are expected to change during incremental refreshes. Treat the schemas,
quality gates, and invariants as stable; refresh these figures when publishing a
substantial new snapshot.

## Recommendation quality

The iPhone forms a taste vector from locally opened subjects and scores
candidate vectors by cosine similarity. A 2026-07-14 offline audit found 91.6
percent top-neighbor genre overlap versus 59.7 percent for random pairs. The
main metadata weakness is 125 Douban-only widget candidates that have title-only
embeddings. Enriching those records has higher priority than increasing model
size.

## Workflow intent

- `refresh-catalog.yml`: lightweight model-free incremental discovery.
- `enrich-catalog-editorial.yml`: bounded editorial completion, not metadata
  invention.
- `materialize-catalog-images.yml`: processed image generation.
- `precache-plan.yml`: long-range date-aware selection cache.
- `precache-cards.yml`: prepare near-term complete cards ahead of publication.
- `extend-calendar.yml`: maintain the complete date-keyed horizon.
- `update-calendar.yml`: manual debugging/editorial workflow.
- `pages.yml`: publish the small/medium widget preview.

Do not collapse these into a heavy daily agent. Most expensive or uncertain
work should remain offline or ahead of time.

## Secrets and rights

Local scripts may read credentials from environment variables or the macOS
Keychain. GitHub workflows use repository secrets. Generated JSON, reports, and
logs must never contain secret values. Content provenance is mandatory, and
public redistribution requires a rights basis consistent with
`CONTENT_RIGHTS.md`.
