# v0.24.0 T3 fix round 1

All seven review findings fixed.
1. Malformed YAML becomes a SoundError (key "yaml"); check_sounds reports it.
2. SoundError has file/key/message; check_sounds reads them; story-validator tests added.
3. check raises SoundError for non-mapping sounds/events/bind and unhashable default/choices; tests added.
4. _load_file caches the parsed AND checked entry keyed on (path, mtime, label, scope, engine file key); merged no longer re-checks. Test counts one check over three merged calls.
5. load_engine/load_story return deep copies; merge builds fresh deep-copied dicts; mutation test added.
6. Reserved-name test uses files/con.ogg.
7. Display path and root derive from sound.root (no duplicate fallback); unused loop index removed.

Tests (run_tests.py files): test_sound_schema, test_doctor_sounds, test_module_state_inventory, test_cache_reset_race, test_reachability: 137 passed, 1 skipped (pre-existing, no engine file shipped).
Concern: a file added or removed next to an unchanged sounds.yaml is not seen until its mtime changes (existence is checked at cache fill).
