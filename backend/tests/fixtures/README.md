# GameTora importer investigation (2026-10-26)

## Evidence and fixture provenance

Fetched from the [GameTora manifest](https://gametora.com/data/manifests/umamusume.json):

- [SSR events](https://gametora.com/data/umamusume/training_events/ssr.67768ea7.json)
- [SR events](https://gametora.com/data/umamusume/training_events/sr.ef204eb5.json)
- [Reward dictionary](https://gametora.com/data/umamusume/dict/evrew.8bda1ecc.json)
- [Support cards](https://gametora.com/data/umamusume/support-cards.09ab5a38.json)
- [Skills](https://gametora.com/data/umamusume/skills.280d81aa.json)

`gametora.json` retains the first SSR (30001) and SR (20001) records verbatim,
their support card records, and the skill id/name/rarity fields needed by them.
Reward dictionary indices are preserved; unused entries are replaced with null.
No fixture downloads are needed to run tests.

The [training event helper](https://gametora.com/ja/umamusume/training-event-helper)
loads [chunk 1374, module 41374](https://gametora.com/_next/static/chunks/1374-ccb91d5dd89e273a.js).
Its `decompressEvent` implementation establishes the structure and reference decoding:

- The outer pair is `[card_id, events]`.
- An event contains `[name_ref, choices, story_id, ...metadata]`.
- A choice contains `[choice_ref, reward_refs]`.
- Reward references are decoded by subtracting `tasty (5) + sushi (31) = 36`.
  This offset comes from the source implementation, not from matching skill numbers.
- The dictionary entry is `[type, value, details, optional_random_flag]`.
  The reward renderer labels `sk` as **Skill Hint**, with details holding skillId.
- Metadata code 9 is history. It must not add obsolete hints to current JP skills.
  All extra metadata in the fetched SSR/SR records was code 9; no SR metadata existed.

Examples: reference 472 resolves to dictionary index 436, `sk` / `+1` / 201142
(軽やかステップ), not dictionary index 472. The SSR 30001 current event hints are
軽やかステップ, 直滑降, 末脚, 全身全霊. SR 20001 grants 追込焦り.

[GameTora skill rendering](https://gametora.com/_next/static/chunks/953-dfa563f3b4c85ae0.js)
labels `sk` as Skill Hint and defines the rarity 2 style using a yellow/gold gradient
(`#ffffef` to `#ffbe28`). This is **skill rarity**, distinct from support-card rarity 2 (SR).
The skills JSON identifies 全身全霊 as rarity 2 and its normal hints as rarity 1.
The frontend `scoreCard` treats rare_skills as gold, so only resolved names
with skill rarity 2 are placed there. Event skills in general are not all gold.

## Reproduction and validation

Before: as_records discarded every array record; event_card_count was 0.
rare_skills was unconditionally assigned `[]` even when gold skills were in skills.

After, using all five full live files: 563 cards, 1926 skill names, 338 factor aliases,
393 event cards, and 316 cards with nonempty rare_skills. Against the original import
of these same files, skills arrays and factor aliases are identical: support-cards
already supplies these event skills. This does not make the event parser correct;
fixtures verify event-only hints without depending on that redundant field.
No generated production data is committed in this fix.

Run offline regression tests:

```
python -m unittest discover -s backend/tests -v
```

For offline array imports supply `--event-rewards path/to/evrew.json` alongside
`--ssr-events` and `--sr-events`. Missing dictionaries and invalid references fail
before writing output. Named-key event inputs remain supported without a dictionary.
`--download-latest` obtains dict/evrew from the same manifest as the other files.

## Actions compatibility and scope

Existing `update-gametora-data.yml` remains unchanged. Its Python 3.12 invocation
needs no new arguments or third-party dependencies. The generated JSON field types,
factor aliases, merge IDs, backup flag, and output paths are unchanged. A separate
read-only PR workflow runs offline tests on Python 3.12, with no dispatch or schedule.
The live import was exercised with separate cards/alias output paths and repeated to
check stable output. main and the data/gametora-update branch are not modified.
No Raspberry Pi access, cron, monitoring, or Discord settings were involved.

Validation: 11 unittest tests passed locally on Python 3.13. The full frontend
production build, including TypeScript, passed with freshly imported live data.
The PR workflow checks the importer on the existing updater's Python 3.12.

## Friend events (2026-10-27)

`gametora_friend.json` preserves the real char_id 9001 record from
[friend.2390ceed.json](https://gametora.com/data/umamusume/training_events/friend.2390ceed.json),
its three support cards from
[support-cards.e1d19b5b.json](https://gametora.com/data/umamusume/support-cards.e1d19b5b.json),
and referenced reward entries from `evrew.8bda1ecc.json` (indices preserved;
unrelated entries null). Skill id/name/rarity fields come from `skills.49e8ca76.json`.

Module 41374 linked above maps friend records by `supportData.char_id`, rather
than support ID. The record is `[char_id, milestones, random_events, outings]`.
Null milestone slots and the final `[null, [], [], []]` placeholder are empty.
Event metadata 2 replaces the current event for a matching support ID; metadata
14 disables the event. Metadata 9 is history and must not supply current hints.
`"no"` choices do not grant hints. Tests cover the R/SSR/alternate SSR versions
of Tazuna, including the disabled alternate event and different outing skills.

The new `--friend-events` option accepts this file offline; `--download-latest`
now downloads it automatically. Existing SSR/SR and named-event inputs keep their
formats. Friend files belong in `--friend-events`, not `--event-skills`.

Import JSON output includes `friend_event_card_count`, `missing_skill_card_count`,
and `missing_skill_cards` (source ID, name, reason). Empty imported skill lists
also emit stderr warnings. `friend_events_not_in_source` means a friend card has
no matching character record in the supplied friend file; `no_resolved_skills`
means no skill name was resolved, without asserting that source data is missing.
A present friend record with no skill hints uses the latter reason. Offline runs
without a friend file cannot assert friend-source absence. Empty data is reported
without stopping an otherwise valid update or inventing skills.

Live validation: all 23 friend card results exactly matched GameTora module
41374's own decoder. All 566 combined card skill lists matched current main
(the support-card source already redundantly supplies existing friend hints).
Only Azuma 10149/30323 were reported with empty skills and absent friend records.
18 offline tests passed. No generated production JSON, schedule, deployment,
Raspberry Pi, or notification configuration is changed by this implementation.
