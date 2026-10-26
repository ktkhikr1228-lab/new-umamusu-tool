# Missing-card skill research

The normal GameTora importer produces `missing_skill_cards`. The updater passes
that report to `research_missing_card_skills.py`, which searches **only** those
card IDs whose imported skill lists remain empty. No-missing-card runs make no
search or source-page requests. This does not detect partially missing skill lists.

Each query uses character, card title and rarity. If no matching evidence is
returned, shorter character/rarity and character-only queries are tried, with
the same exact page identity checks. Yahoo Japan's public search HTML is used without credentials; its layout,
rate limits or access restrictions can change. At most six supported links per
query (three queries per card, deduplicated URLs) are fetched with 15-second timeouts and response-size limits. The initial
source adapters cover GameWith, Game8 and Kamigame's Umamusume sections.

A page must identify the character and exact rarity in its title and the card
version in its text. R does not match SSR. Candidate names must exactly match a
normal/gold GameTora skill name in a designated skill section. Recommendation
sections, scripts, arbitrary snippets and skill-name substrings are excluded.
This is candidate gathering, not proof of actual in-game acquisition: old source
pages, incomplete articles or source errors still require human review.

`backend/data/missing_skill_research.json` contains queries, candidate names,
source URLs, skill-section labels and statuses. Candidate skill names do not
modify cards.json, rare_skills, factor aliases or frontend behavior. The current
Azuma R/SSR findings are included for review only.

Statuses: `needs_review`, `not_found`, `search_failed`, `fetch_failed`. Fetch
failures are recorded instead of being presented as success. Prior evidence is
kept separately as `previous_evidence` if a later search fails. Missing entries
are retried on **every data-update run**, even when GameTora hashes are unchanged.
Scheduled runs now occur daily at **12:15, 15:00, 18:00 and 21:00 JST** (03:15,
06:00, 09:00 and 12:00 UTC). The normal GameTora import still runs first, so a
resolved card is excluded before web searches. With no empty skill lists there
are no search/source-page requests. Existing manual and Pi-triggered runs retain
the same behavior. GitHub scheduled jobs can be delayed; these are target times,
not a guarantee of execution at the exact minute. Serialized workflow runs avoid
simultaneous writes to the same update PR; pending runs may be coalesced by GitHub.
Research-only changes skip Node installation and frontend builds, while still
updating the review report/PR and run artifacts. A card
leaves the report when the normal import supplies skills. No automated approval,
manual override or cross-site skill application is included.

The updater attaches JSON/Markdown artifacts and writes the summary to its run
page even if frontend data is unchanged. Research changes also qualify for the
existing data-update PR. The report excludes timestamps to avoid daily PR churn;
CLI output includes check time and added/changed/resolved card IDs. Source URLs
and candidate changes are reviewable in the JSON diff. Findings become the next
baseline when the update PR is merged. Searches do not send external messages.

Example (after importing with stdout redirected to import-report.json):

```sh
python backend/tools/research_missing_card_skills.py \
  --import-report import-report.json \
  --skills /path/to/skills.hash.json \
  --summary /path/to/missing-skill-research.md
```

`--cards-json` and `--report-json` allow isolated validation outputs. Production
card/alias files are not changed by the researcher. All tests are offline:

```sh
python -m unittest discover -s backend/tests -v
```

Live validation on 2026-10-27 JST found three normal skill candidates for Azuma R
and those same three plus 神速 for SSR. The SSR page lists came from GameWith
and Game8; R came from GameWith. 28 tests passed, including source identity,
section isolation, missing-only searches, shorter-query fallback, stable output,
changed candidates, resolved cards, failure handling and no-network CLI runs.
