# Canon — The Wicked Garden

The story's declared vocabulary. Read by `tests/test_wicked_garden_scenes.py`
and by nothing at runtime.

## `state-dictionary.json`

Every flag, meter, clock, thread and relationship this story is allowed to name,
plus the enum spellings each one accepts. The suite scans all ten day chapters
and the endings table against it, in both directions:

- a gate on a flag nobody writes can never open
- a flag written but never read is a typo or dead weight

It lives here rather than in `Design_files/`, where it was authored, because
that directory is local-only — 36 MB of working documents that a public
repository has no reason to carry, and that a checkout must not need. A test
reading it from there passed on the machine it was written on and failed
everywhere else.

**It is not converted to YAML**, unlike every other file this story ships. The
rest are parsed by the engine, and a runtime that has to know which of two
parsers to reach for per file is a runtime with a bug in it. This one is read
only by the suite, and keeping it byte-identical to the authored source means
the two can still be diffed.

**It is not loaded by the engine.** Nothing here changes what the game does.
The flags it names are declared for real in `../rules/`, `../scenes/` and
`../../state.yaml`; this is the list they are checked against.

Version: v0.1.0 [2026-08-09]
