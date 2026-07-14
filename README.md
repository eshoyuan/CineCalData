# CineCalData

This is the public static backend and daily editorial agent for the private
CineCal iPhone app. It publishes one film or television entry per day with a
short original editorial sentence and a link to its Douban subject page.

- `data/calendar.json` is the public feed read by the app and widget.
- `data/plan.json` is the 365–730 day date-specific editorial plan.
- `data/today.json` is the tiny pointer published each day without calling a model.
- `.github/workflows/precache-plan.yml` builds the long-range plan in parallel batches.
- `.github/workflows/precache-cards.yml` prepares complete cards 30+ days ahead.
- `.github/workflows/publish-today.yml` performs the lightweight daily publish.
- `.github/workflows/update-calendar.yml` is the manual one-card editor/debug workflow.
- `META_AI_API_KEY` is stored only as an encrypted GitHub Actions secret and
  is never included in this repository or its generated JSON.

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

The daily job does no search, copywriting, or image processing. Heavy model work
runs separately and ahead of time:

1. Bootstrap or monthly planning caches date-specific selections for up to 730
   days using holidays, release anniversaries, notable people, festivals,
   seasonal mood, and sourced cultural events.
2. Weekly materialization prepares the next uncached seven-day slice at least
   30 days ahead, including both widget crops.
3. At 00:05 Asia/Shanghai, the daily publisher only points `today.json` at the
   already cached card and records whether it is complete.
