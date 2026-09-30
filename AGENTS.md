# CineCalData agent instructions

This repository is the public, static backend for the private CineCal iPhone
app. Read `docs/MAINTAINER_MEMORY.md`, `data/README.md`, and
`CONTENT_RIGHTS.md` before changing generated data, workflows, image handling,
or editorial policy.

## Invariants

- This repository must remain public; the iOS source belongs only in the private
  `eshoyuan/CineCal` repository.
- Never commit API keys, authorization headers, Apple credentials, cookies,
  provisioning profiles, or local Keychain output. Workflows receive secrets
  only from GitHub Actions secrets.
- `calendar.json` is date-keyed. The phone selects `YYYY-MM-DD` using its local
  time zone. Never publish a global `today` pointer.
- Daily Actions are lightweight. Planning, image retrieval, crop analysis,
  editorial enrichment, and embedding generation happen ahead of time or
  offline.
- Client cards require a canonical Douban subject URL and a known Douban score
  of at least 6.0.
- Editorial lines must be original CineCal copy. Do not reproduce dialogue,
  reviews, lyrics, summaries, or marketing copy.
- A remote image URL or attribution is not a redistribution license. Follow
  `CONTENT_RIGHTS.md` and preserve provenance fields.
- Small and medium crops are separate materialized files. Do not move crop
  decisions to the iPhone or the web preview.
- Keep schema version 1 unless the private iOS client is updated in the same
  release plan.

## Verification

Run the relevant Python unit tests after script changes. Validate every modified
JSON file with `python -m json.tool` or `jq`. For generated catalogs, check key
uniqueness, Douban URL completeness, score floors, image reachability, embedding
dimensions/checksum, and the GitHub Pages small/medium preview before pushing.
