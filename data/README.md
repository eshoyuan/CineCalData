# CineCal data contract

`calendar.json` is the static API consumed by both the iOS app and the widget.

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

`.github/workflows/update-calendar.yml` runs at 00:15 Asia/Shanghai and can also be started
manually with an exact title and date. It uses Meta's Responses API in two distinct stages:

1. `web_search` discovers and verifies the title, current Douban score, original editorial copy,
   and explicitly licensed candidate images. The raw search results and cited URLs are retained
   for audit.
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
