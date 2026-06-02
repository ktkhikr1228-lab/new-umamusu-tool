# GameTora import files

## One-command update

From `backend`, this tries to download the latest GameTora files and update
`frontend/src/data/cards.json`.

```powershell
C:\Users\katao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tools\import_gametora_cards.py --download-latest
```

It downloads:

- `support-cards`
- `skills`
- `training_events/ssr`
- `training_events/sr`

If GameTora blocks command-line downloads, save the JSON files manually into
this folder and use the fallback command below.

## Manual fallback

Put downloaded GameTora JSON files here, for example:

- `support-cards.6e41ebb5.json`
- `skills.528f3ead.json`
- `ssr.61a5479d.json`
- `sr.5c101002.json`

Then run from `backend`:

```powershell
C:\Users\katao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tools\import_gametora_cards.py --support-cards data\import\support-cards.6e41ebb5.json --skills data\import\skills.528f3ead.json
```

With SSR/SR event skills:

```powershell
C:\Users\katao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tools\import_gametora_cards.py --support-cards data\import\support-cards.6e41ebb5.json --skills data\import\skills.528f3ead.json --ssr-events data\import\ssr.61a5479d.json --sr-events data\import\sr.5c101002.json
```

Hint skills and event skills are merged into each card's `skills` array.
`rare_skills` is kept as an empty array for compatibility with the frontend.
