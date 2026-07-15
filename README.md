# CineCalData

This is the public static backend and daily editorial agent for the private
CineCal iPhone app. It publishes one film or television entry per day with a
short original editorial sentence and a link to its Douban subject page.

- `data/calendar.json` is the public feed read by the app and widget.
- `data/plan.json` is the 365–730 day date-specific editorial plan.
- `data/catalog.json` is the model-free, deduplicated recommendation pool used for
  future search and embedding-based personalization.
- `.github/workflows/precache-plan.yml` builds the long-range plan in parallel batches.
- `.github/workflows/precache-cards.yml` prepares complete cards 30+ days ahead.
- `.github/workflows/extend-calendar.yml` keeps a complete 732-day date-keyed feed.
- `.github/workflows/update-calendar.yml` is the manual one-card editor/debug workflow.
- `.github/workflows/bootstrap-catalog.yml` builds the initial high-quality movie and
  television catalog from Douban Top 250 plus TMDB rating/popularity lists.
- `.github/workflows/refresh-catalog.yml` performs the daily model-free incremental merge.
- `META_AI_API_KEY` is stored only as an encrypted GitHub Actions secret and
  is never included in this repository or its generated JSON.
- `TMDB_API_TOKEN` (v4) or `TMDB_API_KEY` (v3) is the encrypted credential used
  to resolve exact works, metadata, and stable landscape artwork.

## Live preview

[Open the interactive Widget preview](https://eshoyuan.github.io/CineCalData/).
The page reads the full public catalog directly, maps every date to three stable
candidates, supports date navigation and shuffle, and renders only the small and
medium Widget layouts. It does not imitate the surrounding iPhone UI.

## Content and copyright

The project does not treat a remote image URL or attribution as permission to
redistribute an image. The current workflow is explicitly marked as prototype
mode: it records the source and rights status but may accept official
promotional imagery without a commercial license. Unlicensed local prototype
stills are excluded from the public repository. Production mode requires an
explicit, verifiable license that permits public display and cropping.

Movie titles and individual ratings are stored as factual references with a
link to the source. Review excerpts, plot summaries, lyrics, and copied
marketing text are not published. Widget sentences are original CineCal
editorial copy. See [CONTENT_RIGHTS.md](CONTENT_RIGHTS.md) for the full policy.

Douban and all film/television titles and marks belong to their respective
owners. CineCal is not affiliated with or endorsed by Douban or any studio.

## Cache strategy

The daily calendar job does no search, copywriting, or image processing.
Preparation runs separately and ahead of time:

1. Bootstrap or monthly planning caches date-specific selections for up to 730
   days using holidays, release anniversaries, notable people, festivals,
   seasonal mood, and sourced cultural events.
2. Weekly materialization prepares the next uncached seven-day slice at least
   30 days ahead. TMDB supplies structured metadata and backdrop candidates;
   Douban's structured suggestion response supplies the rating and subject URL.
   The model only writes original copy and judges the two crops.
3. The lightweight daily job extends `calendar.json` to a complete 732-day
   horizon. The iPhone derives `YYYY-MM-DD` from its own system calendar and
   timezone; there is intentionally no global “today” pointer.

## Recommendation catalog

The catalog builder does not call Meta or any other LLM. Bootstrap mode combines
Douban Top 250, TMDB top-rated movies and series, popular titles, and weekly
trending titles. Incremental mode checks stable TMDB IDs before merging popular,
trending, and recently released titles into the existing snapshot.

The current snapshot contains 1,183 unique recommendations, including the stable
offline pool, the complete Douban Top 250, and the latest incremental additions.
1,173 titles have separate widget-ready small and medium images; 1,002 complete
public cards also have a canonical Douban subject,
a Douban score of at least 6.0, and independently reviewed original editorial copy.
Every recommendation has a source quality score of at least 7.0. A known Douban
score below 6.0 always excludes the title, even when its TMDB score is higher. Rich
records retain genres, creators, cast, keywords, overview, rating counts,
popularity signals, images, source ranks, and a normalized `searchableText` field
that is embedded locally with the 300M-parameter EmbeddingGemma MLX model. The
first 128 Matryoshka dimensions are re-normalized and stored as compact float16
rows for on-device cosine ranking.

## Offline assets and embeddings

Install `requirements-offline.txt` on an Apple Silicon Mac, then run:

```sh
python scripts/materialize_catalog_images.py
python scripts/build_embeddings.py
```

The image job downloads each source backdrop once, uses Apple Vision face and
attention saliency analysis, and writes independent 760×760 and 1080×508 JPEGs
under `data/catalog-images`. The embedding job writes `data/embeddings.f16` plus
`data/embeddings-index.json`; no model or image analysis runs on the iPhone.
