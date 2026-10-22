# A recorded v0.22.0 READ RECEIPTS save

`save.json`, `memory.json` and `phone_archive.jsonl` are a READ RECEIPTS run saved by **v0.22.0's own code,
at commit `60215f4`**, for `tests/test_social_migrate.py` (v0.23.0 spec §16.3, T20). They are never
written by the suite; re-record them only with the commands below.

What `record_v022.py` does, with v0.22.0's own functions:

- seed **7**; `scripts/simulate_social.py`'s **`picky`** policy (`Phone`, the `romantic_model` stub voice,
  on a real save store in a throwaway `CLOCKWORK_DATA_DIR`) for **10 in-game days**. The `attentive`
  policy's save was 224 KB alone, over the 200 KB bound, so the run uses `picky` (fewer matches); the days
  are not cut;
- one meet-up `agreed` through `meets.propose`, its gate forced open and its stage floor forced to
  `matched` (a picky run has nobody at `numbers` by day 10);
- one player message sent in the newest live thread and left unanswered (nothing advanced after it);
- the queue's `daily` left in place; the archive spilled and the save written through v0.22's
  `SessionStore`/`SaveStore`, as `write_day_save` does.

It calls no model and writes nothing outside its temporary storage root and `--out`. Sizes at recording:
`save.json` 134,634 bytes, `memory.json` 167, `phone_archive.jsonl` 18,702 (153,503 together, under 200 KB).
`save.json` carries the wall-clock time it was written, so a re-recording differs there (the archive is
byte-identical).

## Recording it

Windows (PowerShell), from the repository root:

```text
git worktree add ..\cd-v022 60215f4
cd ..\cd-v022
..\clockwork-dark\.venv\Scripts\python.exe ..\clockwork-dark\tests\fixtures\social\v022_save\record_v022.py --out ..\clockwork-dark\tests\fixtures\social\v022_save --policy picky
cd ..\clockwork-dark
git worktree remove ..\cd-v022
```

POSIX `sh`:

```sh
git worktree add ../cd-v022 60215f4
cd ../cd-v022
../clockwork-dark/.venv/bin/python ../clockwork-dark/tests/fixtures/social/v022_save/record_v022.py --out ../clockwork-dark/tests/fixtures/social/v022_save --policy picky
cd ../clockwork-dark
git worktree remove ../cd-v022
```

The script puts the worktree's root (the working directory) first on the import path and asserts that
`engine` was imported from there, so it always runs v0.22.0's code, never this checkout's.
