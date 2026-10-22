# Task 13 report: scenes -- meet-ups played in person

Status: DONE_WITH_CONCERNS. One commit: a749465 on release/v0.23.0 (base 0490326).

## What was built

- **engine/social/scene.py (new).**
  - `open_scene` is called from `plans.arrive`, through `_on_arrival_scene`. It:
    - marks the plan `met`;
    - closes any chat episode going on, with end `met`;
    - writes the scene row and draws its prior inside the handler (`_prior_draw`, forceable);
    - opens a `social_episode` of kind `scene`, which never lapses and closes only at the scene's end (m9).
  - `scene_verbs` offers `scene`, `close` and `do` (the shared activities), at most eight of each, by a fixed rank.
  - `move` follows the brief's arithmetic. The score and band are computed inside the `social_scene` `moment` op (rule 3), and `_moment_draw` is forceable. Then:
    - the move's minutes are spent through `clock.advance_time`;
    - growth takes `gain("moment", band=...)`, or `loss("too_deep")` for a question above their rung (a `too_deep_band` flat, never a refusal);
    - when they close (energy out, two missteps, or their schedule boundary under `talk.boundary_minutes`), the scene ends with `then: stay`.
  - `close` handles every closer target from Plan decision 5:
    - `call_it_a_night` with a promise, a plan or `:stay`;
    - `another_round`, `go_somewhere_else:<venue>` and `walk_them_home`;
    - `back_to_yours` and `back_to_theirs`, offered only when `willing(come_over)` / `willing(go_to_theirs)` holds;
    - `stay_the_night` is listed in the data but held back for T16 (`LATER_CLOSERS`).
    - `go` through a closer uses `world.go` with a single target, so travel is charged and `resume` is cleared.
    - The commitments a closer made are written to `people[pid]["recorded"]`, which `agreement._view` reads into `AgreementView.recorded`.
  - `end_scene(state, reason, *, then)` does all of the following in one place:
    - bands the evening from a running average (great to bad);
    - updates `scenes_done` and `meets_good`;
    - writes the band onto the plan row and the episode row;
    - closes the episode with `scene_end`, which queues its recap;
    - swaps numbers at `fine` or better through v0.22's number path;
    - moves `numbers` to `meeting`, then `advance_stage` (the branch);
    - writes a history line;
    - queues `post_meet` at `convo.next_available` after their pace, unless the band is in `none_after` or the archetype in `none_from`;
    - clears the scene.
  - Also in the module:
    - `phone_in_company`;
    - `archive_turn`;
    - `check_data` (F23: move keys closed, `fit.traits` must be population traits);
    - `meets_faults`;
    - the `scene` payload section (F18), words only;
    - `narration_line`.
- **meets.py deleted.**
  - Venues, `place_line`, `pick_venue` and `venue_faults` moved to `places.py`.
  - `quality` became scenes.yaml's `prior`.
  - `band`, `recap_line` and `post_meet` moved to `scene.py`.
  - The v0.22 recap card pipeline (`voice_recap`, `recap_snapshot`, `is_recap`, and so on) moved to `scene.py`, because `voicer.py` still voices a v0.22 save's due card. T19 deletes it with `date_recap.md`.
  - The `social_meet` handler is gone. `kinds`: `+social_scene`, `-social_meet` (F1).
- **Shared files.** All are gated on `paths.social` or a social slice.
  - `intents`:
    - `_social_scene_open` exists and is used by `scene_owns_turn`.
    - The scene branch sits before `at_work`, inside the `_social_world` block.
    - `SOCIAL_WORLD_ACTIONS` is now `{do, go, scene, close}`.
    - The skill, refusal and `to_tool_call` rows are in. `to_tool_call` passes `{"target": ...}`, which the skill splits.
  - New WORLD skills `social_scene` and `social_close`.
  - The evaluator's `_CLAIMS_LANDED` branch is verbatim.
  - The `run_turn` hook is verbatim, placed before `_record_memory` and `_autosave`.
- **Other changes.**
  - `world`: `scene_verbs`, the scene line in `narration_block`, `do` for a shared activity during a scene (done together, not interruptible), and `pick_up` charges `phone_in_company`.
  - `plans.make(in_person=True)`: a closer's `now` plan has no time check and no flake.
  - `convo._close` of a chat clears `recorded`.
  - `memory.DUE_KEYS` gains `band`, so the recap fallback uses the band's words.
  - `growth._STUBBED` is now `{support}`.
  - `validation`: `_check_meets` uses the new checks, and there is a new `_check_scenes`.
  - `config`: `social.meets_kept` (unread now) is replaced by `social.scene_moments_kept: 12`, which bounds the scene's moments; the band reads a running sum.
- **Data.**
  - scenes.yaml has the brief's values verbatim, plus first-value keys I needed. Each is listed in GOVERNANCE:
    - `moment.topic_fit {theirs, shared}`;
    - `moment.energy_cost` per band;
    - `close.another_round_minutes` (30), `another_round_energy` (0.34) and `walk_extra_minutes` (10), which are the brief's numbers moved into data.
  - relationships.yaml `meets:` is cut to `post_meet`, `recap_lines` and `recap_tone`. Any other key is a load fault.

## Decisions and concerns

1. **The `meeting` stage gate (70/70) is unread.** A scene's end moves `numbers` to `meeting` directly, as T12's stub did, whatever the band. The GOVERNANCE plans row says so; left for T18.
2. **The v0.22 recap card lives in `scene.py` until T19.** The brief says to delete meets.py, and `voicer.py` needs the card pipeline, so it moved rather than being deleted. Its tests moved too, on a planted v0.22 card.
3. **`AgreementView.recorded` lasts longer than "this turn".** It holds from the closer until the person's next chat episode closes, because the post-scene phone conversation is where those commitments get said. The GOVERNANCE scenes row records this.
4. **Closing behaviour.**
   - When they close, the scene ends `then: stay`, so the player stays at the venue and "Head home" is first.
   - `walk_them_home` charges their home's travel plus 10 minutes, then the way home from the venue.
   - A shared activity during a scene runs non-interruptibly.
5. **The phone move.** With someone whose `in_company` habit is `rude_not_to`, the `phone` move is a misstep whatever the draw, and picking up the real phone costs the phone row's misstep regard. With `glances` it is scored normally.
6. **Unrelated test change: `test_social_voicer.py::test_a_sweep_mid_pass_ends_it_and_frees_the_engine`.** It failed in my big batch because `sweep_idle` also released 19 idle sessions left in the process-global store by earlier files. It passes alone. Fix: `reset_store()` at its start.
7. **Spec §10.6 is T15's, not done here.** The companion block and the fact checks on the narration are T15's. The director's no-deal check is T14's. The client is T23's.
8. **Rule 12.** Moves, bands, closers and the scene words are conversation, activity, mood and self-disclosure only. There are no gates or floors, and the guard tests are un-skipped and green.

## Tests

- **Main batch: 986 passed, 3 skipped.** It covered:
  - the brief's list: scene, plans, growth, world, convo, agreement, evaluator, seam (with pin 10), slice_v2;
  - packing, voicing, voicer, voice_v2, memory, intents, relationships, messaging, turn_intent and turn_intent_per_game;
  - the guards: cache_warming, cache_reset_race, module_state_inventory, reachability, finales;
  - the goldens: local_mode and llm_lmstudio;
  - test_ui_contract, test_admin_no_play_text and test_release_hygiene.
- **Every other social file, test_state_schema and test_screenshot_runs: 647 passed, 3 skipped.**
- **Content integrity: 69 passed.**
- `validate_content.py --game read-receipts`: 0 errors.
- **Not run, by the cost rules.**
  - `test_social_save_size`: scene state is transient, bounded by test, and the harness never makes plans.
  - `test_simulate_social`: its players go to no plan, so no balance the harness measures moved.
  - `test_social_commit_scope`: no commit or transaction code was touched.

## Processes

No server or background process left running.

## Fix round 1

- Minor 3: `end_scene(..., continues=True)` (the `social_scene` `end` effect's `continues`) is passed by the go-on closers (`back_to_yours`, `back_to_theirs`, `go_somewhere_else`), so `post_meet` is held; it queues when the last scene ends (`_queue_post_meet`), and at once if the follow-on plan is refused ("not tonight"). Test: `test_post_meet_waits_for_the_last_scene_of_the_evening` (failed before).
- Minor 1: CLAUDE.md had no row naming the 70/70 gate any more (T9 had already replaced those rows); added one truthful row that the `meeting` gate is dead data, removed at T18. The gate itself is untouched.
- Minor 6: venues.yaml header now names `places.py` / `plans.py`. Minor 7: root CHANGELOG `[Unreleased]` now has `### Changed`, `### Fixed`, `### Added`; the story CHANGELOG has the fix line.
- Tests: test_social_scene, test_social_plans, test_release_hygiene: 115 passed. No slow test run. Balance: the harness never makes plans, so nothing it measures moved.
