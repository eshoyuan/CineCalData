# CineCal content-rights policy

This policy is a product safeguard, not legal advice.

## Text

- Allowed by default: titles, release years, stable factual metadata, an
  individual rating with its source and retrieval time, and original CineCal
  editorial copy.
- Not copied automatically: Douban reviews, plot summaries, marketing copy,
  subtitles, lyrics, or dialogue. A source link does not grant republication
  rights.
- Every displayed rating links to the relevant Douban subject page. CineCal
  does not use the Douban logo or claim affiliation.

## Images

Attribution and hotlinking are not substitutes for permission. The daily
agent may download, crop, and publish an image only when the source provides a
verifiable license that permits:

1. public redistribution/display;
2. modification and cropping; and
3. commercial use, so the feed remains safe if the app is monetized later.

The entry and editorial report retain the source page, rights holder, rights
status, license name, and license URL when available.

The current GitHub Action runs in `prototype` mode. It may use a grounded
official promotional/press image while clearly recording that this is not a
verified commercial license. Before App Store or commercial distribution,
change `CINECAL_RIGHTS_MODE` to `production`; that mode accepts only
`public_domain`, `cc0`, `cc_by`, and `cc_by_sa` with explicit commercial-use
and modification rights.

## Operational rule

If provenance cannot be verified, the workflow fails before writing an image.
In production mode, unverified rights also fail publication. Visual quality
review happens after the configured rights check.
