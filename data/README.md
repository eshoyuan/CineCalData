# CineCal data contract

`calendar.json` is the static API consumed by both the iOS app and the widget.

`plan.json` is a separate long-range editorial cache. Its entries explain why a title belongs on
a particular date and retain grounded signals such as a holiday, original release anniversary,
principal cast/creator anniversary, festival, seasonal theme, or cultural event. Plan entries may
be generated 365–730 days ahead; complete image cards are materialized only for the near-term
window so volatile ratings and topical context do not go stale.

There is intentionally no global “today” pointer. `calendar.json` contains a complete rolling
date horizon, and each iPhone selects the exact `YYYY-MM-DD` key using its own system timezone.

`catalog.json` is the larger model-free recommendation pool. It merges high-quality stable titles
with recent popularity signals, deduplicates primarily by TMDB ID and secondarily by normalized
title plus year, and keeps a precomposed `searchableText` field for future embedding generation.
Known Douban ratings below 6.0 are excluded. The general structured-source quality floor remains
7.0, so lowering the Douban-specific floor does not admit low-signal catalog entries by itself.

`catalog-images/` contains the materialized small and medium crops referenced by each catalog
record. Crops are generated locally with Apple Vision face and attention-saliency boxes, so the
web preview and iOS widget do not make runtime crop decisions.

`embeddings.f16` is a little-endian, row-major float16 matrix. `embeddings-index.json` records the
model, dimensions, checksum, and catalog-key order; each catalog item also stores its `embeddingRow`.

`sources/douban-top250.json` is an offline seed snapshot. GitHub-hosted runners may receive a
challenge page instead of the public Top 250 listing, so bootstrap uses this checked-in snapshot
when a complete live response is unavailable. The daily incremental job never re-scrapes it.

- Keep `schemaVersion` at `1` until the client model changes.
- Use local calendar dates in `YYYY-MM-DD` format.
- Store final movie images in this GitHub repository. New entries provide `imageURLSmall` and
  `imageURLMedium`; `imageURL` remains the backwards-compatible medium-image fallback.
- Keep source images at or below 1080 pixels on the longest edge. The widget also downsizes defensively.
- `rating` is a string so values such as `9.2` preserve their display formatting.
- `doubanURL` is opened when the user taps the widget.
- `quote` must be short, literary, original CineCal editorial copy. Do not copy dialogue,
  reviews, plot summaries, lyrics, or marketing text.
- Record `quoteType` as `editorial` and `quoteAttribution` as CineCal editorial copy.
- Every remotely published image must include `imageSourcePageURL`, `imageCredit`,
  `imageRightsStatus`, `imageLicenseName`, and `imageLicenseURL`. Attribution alone is not
  permission; the license must allow public display, commercial use, and cropping.

The client derives today's key from its local system calendar and checks that exact entry. If the
network request fails, it uses the last cached JSON and image; if no cache exists, it uses the
bundled sample movies.

## Daily editorial agent

The materializer deliberately separates mechanical retrieval from editorial judgment:

1. The long-range planning agent uses search only to choose a date-appropriate work and retain the
   sourced reason for that choice.
2. TMDB's API resolves the exact movie/series, metadata, and a ranked set of stable landscape
   backdrops. Douban's structured suggestion endpoint supplies the rating and subject link.
3. Meta generates only the original CineCal sentence. It does not invent metadata, ratings, or
   image URLs.
4. Image understanding localizes subjects on Meta's normalized 0–1000 coordinate grid and proposes
   separate 1:1 and 2.128:1 crops. A second vision pass sees translucent overlays representing the
   real widget text zones and must approve both crops with a score of at least 7/10.

If grounding is absent, a source cannot be verified, an image is invalid, or either crop fails,
the workflow exits before modifying `calendar.json`. Approved outputs are written to `data/images`,
and the research/crop report is written to `data/reports`.

Create `META_AI_API_KEY` plus either `TMDB_API_TOKEN` (v4 Read Access Token) or `TMDB_API_KEY`
(v3 key) as encrypted GitHub Actions repository secrets. The workflow exposes the Meta secret as
`MODEL_API_KEY`; never put credentials in source code, workflow YAML, issue text, or logs. The editorial/vision steps use `muse-spark-1.1` and
`https://api.meta.ai/v1`.

Prototype mode requires grounded provenance and records the rights basis. Production mode also
requires an inspectable license allowing public display, commercial use, and modification. See
`CONTENT_RIGHTS.md`.
