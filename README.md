# CineCalData

This is the public static backend and daily editorial agent for the private
CineCal iPhone app. It publishes one film or television entry per day with a
short original editorial sentence and a link to its Douban subject page.

- `data/calendar.json` is the public feed read by the app and widget.
- `.github/workflows/update-calendar.yml` runs the daily editorial agent.
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
