# Missing plates — Read Receipts

0 subject(s) are authored in `subjects.yaml` and have no image in
`plates/`, so each falls through the resolution chain to the procedural
silhouette.

**Generated, not written.** Every prompt below is the output of
`engine.media.art.render_prose` / `render_tags` against the shipped
`subjects.yaml`, so it is exactly what the live pipeline would send — not a
fourth copy of the art voice free to drift from the three that ship. After
editing a subject, re-run the generator rather than editing the prompts here:

```powershell
.\.venv\Scripts\python.exe scripts\art_missing.py --game read-receipts
```

## Order to work in

Any order. None of these is a fallback plate or the entry location, so
each one only shows up if the player goes there.

## Sizes

| Kind | Size | Directory |
| --- | --- | --- |
| location | 1344x768 | `scenes/` under `paths.art_root` |
| portrait | 1344x768 | `portraits/` under `paths.art_root` |
| item | 1344x768 | `items/` under `paths.art_root` |

Read from `subjects.yaml`'s `formats:` block, which is also what the live Grok
and ComfyUI providers size their requests from — so generating by hand and
generating through the pipeline land the same shape. `tests/test_story_art.py`
holds that block to the plates actually on disk. JPEG, same as the rest.

## After the files land

`scripts/generate_art.py --game read-receipts --promote` writes each plate the
generator made into `manifest.yaml` itself. For a plate made by hand, add it
under its kind: a location's plates go under `times: {<daypart>: ...}` (or
`base:` for a location whose subject declares no `times:` -- note that a
`base:` then answers every daypart); portraits and items take a bare path.
Paths are relative to `paths.art_root`. The ready-to-paste block is at the
bottom.

---

## Manifest block to paste

```yaml
```
