# CineCal data contract

`calendar.json` is the static API consumed by both the iOS app and the widget.

`plan.json` is a separate long-range editorial cache. Its entries explain why a title belongs on
a particular date and retain grounded signals such as a holiday, original release anniversary,
principal cast/creator anniversary, festival, seasonal theme, or cultural event. Plan entries may
be generated 365–730 days ahead; complete image cards are materialized only for the near-term
window so volatile ratings and topical context do not go stale.

`today.json` is generated from the already cached card by a model-free daily workflow. It exposes
`complete`, `usedFallback`, and `missingFields` for operational health checks.

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

The client checks the exact entry for today. If the network request fails, it uses the last cached JSON and image; if no cache exists, it uses the bundled sample movies.

## Daily editorial agent

The heavy editor workflows use Meta's Responses API in focused stages:

1. Narrow `web_search` calls separately verify the Douban metadata and find image candidates;
   original copy is generated without search. The raw search results and cited URLs are retained.
2. Image understanding localizes subjects on Meta's normalized 0–1000 coordinate grid and proposes
   separate 1:1 and 2.128:1 crops. A second vision pass sees translucent overlays representing the
   real widget text zones and must approve both crops with a score of at least 7/10.

If grounding is absent, a source cannot be verified, an image is invalid, or either crop fails,
the workflow exits before modifying `calendar.json`. Approved outputs are written to `data/images`,
and the research/crop report is written to `data/reports`.

Create a GitHub Actions repository secret named `META_AI_API_KEY`. The workflow exposes it to the
process as `MODEL_API_KEY`; never put an API key in source code, workflow YAML, issue text, or logs.
The workflow uses `muse-spark-1.1` and `https://api.meta.ai/v1`.

Prototype mode requires grounded provenance and records the rights basis. Production mode also
requires an inspectable license allowing public display, commercial use, and modification. See
`CONTENT_RIGHTS.md`.
