# CineCalData

This is the public static backend and daily editorial agent for the private
CineCal iPhone app. It publishes one film or television entry per day with a
short original editorial sentence and a link to its Douban subject page.

- `data/calendar.json` is the public feed read by the app and widget.
- `data/plan.json` is the 365–730 day date-specific editorial plan.
- `data/today.json` is the tiny pointer published each day without calling a model.
- `data/catalog.json` is the model-free, deduplicated recommendation pool used for
  future search and embedding-based personalization.
- `.github/workflows/precache-plan.yml` builds the long-range plan in parallel batches.
- `.github/workflows/precache-cards.yml` prepares complete cards 30+ days ahead.
- `.github/workflows/publish-today.yml` performs the lightweight daily publish.
- `.github/workflows/update-calendar.yml` is the manual one-card editor/debug workflow.
- `.github/workflows/bootstrap-catalog.yml` builds the initial high-quality movie and
  television catalog from Douban Top 250 plus TMDB rating/popularity lists.
- `.github/workflows/refresh-catalog.yml` performs the daily model-free incremental merge.
- `META_AI_API_KEY` is stored only as an encrypted GitHub Actions secret and
  is never included in this repository or its generated JSON.
- `TMDB_API_TOKEN` (v4) or `TMDB_API_KEY` (v3) is the encrypted credential used
  to resolve exact works, metadata, and stable landscape artwork.

## Live preview

[Open the interactive iPhone and Widget preview](https://eshoyuan.github.io/CineCalData/).
The page reads the public JSON directly, supports date navigation and shuffle,
and renders both the small and medium Widget layouts.

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

The daily job does no search, copywriting, or image processing. Preparation
runs separately and ahead of time:

1. Bootstrap or monthly planning caches date-specific selections for up to 730
   days using holidays, release anniversaries, notable people, festivals,
   seasonal mood, and sourced cultural events.
2. Weekly materialization prepares the next uncached seven-day slice at least
   30 days ahead. TMDB supplies structured metadata and backdrop candidates;
   Douban's structured suggestion response supplies the rating and subject URL.
   The model only writes original copy and judges the two crops.
3. At 00:05 Asia/Shanghai, the daily publisher only points `today.json` at the
   already cached card and records whether it is complete.

## Recommendation catalog

The catalog builder does not call Meta or any other LLM. Bootstrap mode combines
Douban Top 250, TMDB top-rated movies and series, popular titles, and weekly
trending titles. Incremental mode checks stable TMDB IDs before merging popular,
trending, and recently released titles into the existing snapshot.

Every recommendation has a quality score of at least 7.0. A known Douban score
below 7.0 always excludes the title, even when its TMDB score is higher. Rich
records retain genres, creators, cast, keywords, overview, rating counts,
popularity signals, images, source ranks, and a normalized `searchableText` field
that can be embedded later without changing the catalog contract.
