# Linux and hosting — design (v0.20.0)

Status: **written 2026-09-30 against `main` at v0.19.0 (e7fdd26), for the
owner-approved roadmap row "v0.20.0 — Linux as a first-class platform, and a
hosted/web-served mode: auth, per-user sessions and saves, a production
server, Docker".** The owner does not approve this design. An opus reviewer
checked it (`.superpowers/sdd/v020-design-review.md`, 28 findings, verdict
"execute after fixes"), and every finding is folded into the sections below
rather than listed apart. One question went to the owner, who decided it on
2026-09-30 (`.superpowers/sdd/v020-owner-decisions.md`): the local default
bind becomes `127.0.0.1` (§3.6). Each section records a decision and the
reason for it, not a menu of options. Where this file and the code later
disagree, the code wins (AGENTS.md authority order) and this file gets
corrected.

**Scope added by the owner, 2026-09-30 13:10**
(`.superpowers/sdd/2026-09-30-v0.20.0-linux-and-hosting/v020-owner-decisions.md`):
"some kind of separate admin/backend panel/orchestration", with all four
areas chosen: users and sessions, the model server and its queue, the
orchestration of several stories behind one front door, and logs and
metrics with no view of play text. §14 designs it. The sections it changes
(§2.1, §3.5, §5.1, §5.3, §6.1, §6.2, §6.3, §6.7, §6.9, §7, §8, §9, §11,
§12, §13) are revised in place and point at §14, rather than being
contradicted by it. An opus review of §14
(`.superpowers/sdd/2026-09-30-v0.20.0-linux-and-hosting/admin-design-review.md`:
4 critical, 11 important and 13 minor findings, verdict "execute after
fixes") is folded in the same way; where this file departs from a
recommended fix, the section says why.

## Goal

Three things, all opt-in, and none changes the game a local player gets
today.

1. **Linux is a first-class platform.** The suite is green on Linux: in a
   Linux container on the owner's workstation, and in GitHub Actions on
   `ubuntu-latest`. Every script has a POSIX way in (`scripts/start.sh`
   beside `scripts/start.ps1`). No code assumes a path separator, a drive
   letter, a case-insensitive filesystem or an `.exe`. vLLM, the one model
   server v0.19.0 could not run, is verified live on Linux.
2. **A hosted mode.** A small group, meaning the owner and friends and not
   the public internet at large, plays one story in a browser against one
   shared model server. Players have accounts and their own sessions and
   saves, and one player can never see, resume, stream or delete another's
   run. It runs under a production server, and ships as a Docker image with
   a compose file. `hosting.enabled` is **false** by default.
3. **An operator's admin panel, and several stories behind one front door**
   (§14). A supervisor runs one worker process per story, a front door logs
   a player in once and routes them to the story they pick, and the model
   server's queue is shared across those processes. Admin accounts get a
   separate, server-rendered panel: accounts and live sessions, the model
   server and its queue (and the `llm.*` settings players cannot change),
   starting and stopping stories, and metrics and errors, **metadata only**,
   with no view of play text. Every admin action is in an audit log.

**Local single-player does not change**, bar the differences §1 enumerates
exactly (the loopback bind the owner chose, and `paths.saves` leaving the
games payloads). With the shipped config and `hosting.enabled: false`,
every other route, payload, socket event, save file and save path, and
every request the model server receives, is what v0.19.0 produced. A golden
recorded on untouched v0.19.0 code (§9.1) holds this from the first task to
the release. Local mode does not even import the hosting package, and never
starts the supervisor (§14.1).

## Non-goals

- **Public-internet scale.** This is one host, one process per story, for a
  handful of players (§5.1, §14.1). Horizontal scaling, several workers for
  one story, workers on other hosts, a message queue and sticky sessions
  are **NOT WIRED** (`docs/GOVERNANCE.md`).
- **Self-registration, invite links, OAuth/SSO and reverse-proxy header
  auth.** Accounts are created by the operator on the command line (§6.1).
  Each of these is a **NOT WIRED** row.
- **Per-user settings.** The Settings panel describes the machine. In hosted
  mode it is read-only for every player (§6.7); the operator's `llm.*`
  settings are edited in the admin panel (§14.9). **NOT WIRED.**
- **More than one story per process.** The active game is process-wide
  config (`engine/games/registry.py:321`, `set_overlay`), and `engine/games/api.py`
  deliberately never switches it at run time. Hosting several stories means
  one worker process per story under the supervisor (§14). **NOT WIRED** in
  one process.
- **A view of play text for the operator's panel, or any moderation.** The
  admin panel and the metrics store hold metadata only: no prompt,
  narration, choice, typed action, player name or save content (§14.10).
  This is observability, not moderation (rule 12), and the metrics schema
  is closed so a field of that kind cannot be added without failing a test.
- **The admin panel inside the React client, two-factor login, and editing
  secrets in the panel.** The panel is server-rendered (§14.7); a key is
  shown as present or absent, never edited there (§14.9). Each is a
  **NOT WIRED** row.
- **Serving under a URL sub-path.** The client fetches absolute `/api/...`
  URLs (`ui/src/core/api.js:17`, `:73`, `:99`) and Socket.IO connects at the
  root (`ui/src/core/socket.js:81`). A hosted instance owns the root of its
  host name, which is why the front door routes by the story a player chose
  rather than by path (§14.5). **NOT WIRED.**
- **A queue-position display, a login screen in the React client and a
  logout button in it.** The UI is v0.21.0's. v0.20.0 ships server-rendered
  login and account pages and changes nothing under `ui/src` (§6.3), so the
  committed `dist` is not rebuilt.
- **Hosted mode on Windows under a production server.** The production
  server is gunicorn, which is POSIX-only (§7.1). On Windows, hosted mode
  runs under the development server for a trial, with a WARN, or in Docker.
- **Publishing the image to a registry.** It is built locally and in CI, and
  never pushed. **NOT WIRED.**
- **TLS in the engine.** A reverse proxy terminates it (§7.3).
- **Any content-rating layer (rule 12).** Hosting adds no moderation, no
  filter, no "safety" setting, no per-user intensity and no content policy of
  any kind. The register is still `games/<slug>/prompts/storyteller.md` and
  the operator's model. The `hosting:` block is a closed schema (§6.9), so a
  key of that kind cannot be slipped in later without failing a test.
- **Speech and images in hosted mode, beyond what the operator configures.**
  TTS, STT and ComfyUI keep their endpoints. Their outputs are a shared,
  content-addressed cache (§6.8).

## Findings the survey turned up

The design was written against the code, and the review checked each item
against it again. Items 1 to 3 and 9 are defects today, in local mode, and
are fixed in all modes. Items 4 to 8 and 12 to 14 are what hosting has to
resolve. Items 10, 11 and 15 are the platform's. Items 3 to 5 carry
v0.19.0's reviews.

1. **A save id is a path, and nothing checks it.** `SaveStore._dir`
   (`engine/persistence/saves.py:335`) is `self.root / save_id`.
   `POST /api/saves` passes the request body's `save_id` straight through
   (`engine/api/saves.py:73`), so a body of `{"save_id": "../../../x"}`
   writes `save.json` and rewrites `index.json` wherever the process can
   write. `/api/saves/<id>/load`, `DELETE /api/saves/<id>` and the socket's
   `resume` (`engine/scenes/default_scene.py:371`) take any id as well, and
   `write_json_atomic` creates whatever parents it is handed
   (`engine/persistence/atomic.py:45`). Flask's default converter stops
   `/`, but not `..`, `%2e%2e` or `.`, and on Windows it passes
   `..%5c..%5cx` through as `..\..\x` and `C:%5cx` as `C:\x` (the
   reviewer's probe). So `DELETE /api/saves/..%5c..%5c..%5cconfig` unlinks
   every plain file in a directory the process can reach
   (`SaveStore.delete` unlinks each child, then `rmdir`s),
   `config/default.yaml` and `local.yaml` included, and
   `DELETE /api/saves/.` unlinks `index.json`. A `resume` naming
   `../wicked-garden/<id>` loads another story's run into this one, and
   `load` migrates it by the envelope's own `game` (`saves.py:594`), so the
   flagship's engine then runs a Garden state. The default bind is
   `0.0.0.0` (`config/default.yaml:4`), so all of this is reachable from
   the LAN today.
2. **Runtime outputs are resolved against the working directory.**
   `saves_base()` is `Path(get_config().get("paths.saves", ...))`, a
   relative path used as-is (`saves.py:208`). `MEDIA_DIR` is
   `Path("data/media")` twice (`engine/api/media.py:38`,
   `engine/media/providers/base.py:31`), and so is `AUDIO_DIR`
   (`engine/media/tts.py:48`). Config, content and the lore index are all
   resolved against the repo root. `python /path/to/launcher.py` run from
   anywhere else writes saves into that directory and serves media that
   does not exist there. A systemd unit or a container `WORKDIR` would have
   to happen to match.
3. **The secrets chain's scope syntax (v0.19.0 final re-review, N1–N3).**
   `ConfigManager._expand` splits each alternative at its first `?`
   (`engine/config.py:389`):
   - **N1:** an unscoped alternative that contains a `?`
     (`file:/srv/keys/what?.txt`, legal on POSIX) is read as scope
     `file:/srv/keys/what`, never matches, and is skipped silently.
   - **N2:** a misspelt scope (`lmstuido?file:lmstudio.txt`) is never
     reported. It just never matches.
   - **N3:** the scope test reads `self.get("llm.provider")` (`:391`), which
     expands again. So a hand-built `ConfigManager` whose `llm.provider` is
     itself a scoped chain recurses until `RecursionError`.
4. **A story's `paths.saves` outranks every config layer.** Activation
   installs the manifest's whole `paths:` block as the top layer
   (`engine/games/manifest.py:477` → `registry.py:321`). All six manifests
   restate `saves: "data/saves"`, so `config/local.yaml` cannot move saves
   (v0.19.0 carried item 3). Per-user saves need one engine-owned root.
5. **The mcp.json guard is in-process only.** `tests/conftest.py:594`
   (`_no_owner_lm_studio_files`) monkeypatches `mcp_json_path` and the two
   writers. A test that runs a script through `subprocess.run`
   (`tests/test_simulate_thief.py:71`, `tests/test_imports.py:52`) starts a
   process that has none of it (v0.19.0 carried item 4). The live-model
   guard has the same shape.
6. **The server is unauthenticated and bound to every interface, by
   design, for one player.** The pieces:
   - `scene.clockwork.host: "0.0.0.0"`;
   - Socket.IO with `cors_allowed_origins="*"`
     (`engine/scenes/flask_scene.py:57`);
   - Werkzeug's development server with `allow_unsafe_werkzeug=True`
     (`:96`);
   - no owner on any session route. `GET /api/game/state`,
     `POST /api/game/choice` and the socket's `join_session`
     (`default_scene.py:266`, `:274`, `:309`–`:313`) serve whoever names a
     `session_id`, and a `session_id` is 48 random bits
     (`engine/game/state.py:200`);
   - `join_session` calls `join_room(session_id)` **before** it checks the
     session exists (`default_scene.py:312`–`:313`), so any socket can sit
     in any room, including one for a session not yet created, and receive
     its stream.

   Right for a single player on a trusted network. It is the whole problem
   in hosted mode, and §6 answers each piece.
7. **Two tabs can drive one session, and a turn can be orphaned.**
   `session_id` is persisted in the save (`state.py:199`; `to_save_dict` is
   `asdict`), so a second `resume` of the same save rebuilds a session under
   the **same** id and replaces the `_sessions` entry (`store.py` `_build`).
   The first engine lives on only for a turn already in flight, which then
   autosaves over the new session's state (`default_state.py:884`); both
   tabs sit in room `S` and both drive the new engine. Recorded, not fixed,
   locally (§4.4). Hosted mode closes it for every account (§5.4).
8. **A Settings save resets every content cache under live turns.**
   `apply_settings` ends in `reset_config()` (`engine/api/settings.py:572`),
   which runs `reset_all_caches()`. With one player that is their own turn.
   With several, it is someone else's turn, mid-resolution.
9. **A turn's failure text reaches the client verbatim.**
   `run_guarded` returns `f"The turn could not be completed: {exc}"`
   (`default_scene.py:182`). An `httpx` error there names the model
   server's URL. So do `resume_failed` (`:373`), a save route
   (`engine/api/saves.py:85`), `POST /api/settings` (`settings.py:565`) and
   the voice route, which returns the STT provider's `message: str(exc)`
   and the STT server's `raw` JSON (`engine/media/stt.py:148`–`:160`,
   `stt_whisper.py:227`). That is harmless on the owner's own screen, and
   internal detail shown to every player in hosted mode.
10. **Windows-shaped config and tests.** Two things:
    - The shipped stack commands are `target/release/tts-server.exe` and
      `voxtral.exe` (`config/default.yaml:475`, `:500`).
    - `tests/test_studio.py:60` expects `"C:/Windows/system.ini"` to escape
      the story. On POSIX that is a relative path *inside* the story, so the
      test is predicted to fail on Linux (unmeasured).

    A scripted scan found no case mismatch between repo-rooted references
    and the files they name, and the git index holds every text file with LF
    (`git ls-files --eol`: 0 `i/crlf`). So line endings are not a Linux
    risk.
11. **The machine, as inspected read-only on 2026-09-30.**
    - **WSL2:** `Ubuntu-20.04` and `Ubuntu-22.04-sp` are both stopped, and
      this survey did not start them, so their Python versions are unknown
      (Ubuntu 22.04's system Python is 3.10, below `requires-python >=3.11`).
      A `homeassistant` distro is running and is not ours to touch.
    - **Docker:** Desktop's client is 29.1.5, but its engine is not running:
      `dockerDesktopLinuxEngine` pipe absent.
    - **GPU:** `nvidia-smi` reports an RTX 2060, 12288 MiB, driver 596.21,
      compute capability 7.5.
    - **The venv:** Flask 3.1.3, Flask-SocketIO 5.6.1, python-socketio
      5.16.4, simple-websocket 1.1.0 and Werkzeug 3.1.8. No production WSGI
      server is installed (uvicorn is there for `fastmcp` and is ASGI).
12. **Process-global state that races under threads.** The engine runs one
    turn at a time per session, and several sessions already share a
    process, but some module state assumes one turn in the whole process:
    - `engine/game/inventory.py:622`: `_evaluating_collections` is a plain
      module bool used as a re-entrancy guard. While player A's collection
      payout runs, player B's completed set returns `[]`, and B's payout is
      skipped for that turn, silently.
    - `engine/game/quests.py:830`–`:833`: `_ensure_grammar` sets
      `_grammar_loaded = True` **before** it imports the predicate modules.
      A second thread in the first turns after boot sees `True` with
      predicates missing, and an unknown predicate is unmet: the
      wrong-endings bug the function's own docstring describes, produced by
      concurrency.
    - `engine/telemetry/oracle.py`'s class docstring says "Not thread-safe
      by design. The turn loop is serial per session", and every player's
      turn thread mutates its dicts.
    - About thirty lazily built caches (§5.2's table) are built on first
      access with no lock, `get_config`'s singleton among them.

    §5.2 sorts all of it, from a mechanical scan, not from memory.
13. **A busy model server becomes a committed canned turn.** The storyteller
    swallows every exception from narration (`storyteller.py:1012`–`:1017`,
    `:690` in the stream): `InferenceBusy` included, it substitutes
    `fallback_narration()`. The turn's mechanics ran before narration (rule
    1), so the turn then commits and autosaves. Under shared load, a player
    who waited out the gate gets canned prose over a turn that advanced the
    clock. No module outside `engine/llm/gate.py` names `InferenceBusy`.
14. **Input size is unbounded.** `custom_text` goes into the prompt verbatim
    (`default_state.py:604`–`:605`), and so does `player_name`
    (`default_scene.py:252`). Socket.IO accepts about 1 MB a message. On a
    shared model server one player can send megabyte prompts that
    monopolise prefill for everyone.
15. **Dependencies are unpinned.** `requirements.txt` is all `>=`. The
    goldens pin bytes, and engineio's and Werkzeug's behaviour (CORS
    defaults, test-client routing) depends on versions, so CI, the Linux
    container and the image would not run what the owner runs.

Each fix to 1–3, 9 and 12 ships with a test that fails against v0.19.0. 13
and 14 are fixed in hosted mode only (§5.3, §6.5), and local mode keeps
v0.19.0's behaviour for both.

---

## §1 — The local-mode golden

**Decision.** The first task records, **on untouched e7fdd26 code**, the
whole surface local mode shows. Every later task asserts it is unchanged.
It sits beside v0.19.0's model-server golden
(`tests/test_llm_golden_lmstudio.py`), which keeps running unchanged and
guards the wire.

The recorder (`tests/local_golden.py record`) runs `create_app(testing=True,
llm_fn=<scripted>)` under the same pinned config harness the LLM golden uses:
`engine.config._instance` reset, `_CONFIG_DIR` patched to a temp directory,
`_DEFAULT_PATH` the repo's real `config/default.yaml`, and
`CLOCKWORK_LLM_API_KEY`, `LMSTUDIO_API_KEY`, `CLOCKWORK_ENV`,
`CLOCKWORK_CONFIG` and `CLOCKWORK_DATA_DIR` deleted from the environment
(the last two do not exist yet on e7fdd26; stripping them from the start
means the owner's shell can never leak into a later run). The save tree is
written under the conftest's existing redirect of `saves.saves_base`, so
nothing touches `data/saves`. It captures:

- **the app's shape:**
  - the URL map, as `(rule, sorted methods, endpoint)`;
  - the `before_request`/`after_request` function lists;
  - the `SocketIO` constructor's `cors_allowed_origins` and `async_mode`;
  - the Socket.IO handler names, per namespace
    (`socketio.server.handlers`);
  - the kwargs `FlaskScene.run` passes to `socketio.run`, taken by calling
    the real `default_scene.run_scene()` with `SocketIO.run` stubbed, so the
    host is the one config resolves (`run_kwargs.host`);
- `GET /`'s rendered HTML, and `GET /api/health`;
- for the flagship and HUE & CRY, each at a fixed seed with a scripted
  model:
  - `POST /api/game/new`;
  - two turns over HTTP, and two over the Socket.IO test client (every
    event, in order, with its payload);
  - `GET /api/game/state`;
  - the socket's `connect`, and `join_session` for the live session and
    for an id that does not exist;
  - a manual `POST /api/saves`, `GET /api/saves`, a load, a socket
    `resume` and a delete;
  - the story blueprint's nine routes (`engine/scenes/default_api.py:863`–`:960`:
    `/api/quests`, `/api/codex/places`, `/api/codex/souls`,
    `/api/codex/things`, `/api/items`, `/api/recipes`, `/api/trade`,
    `/api/notices`, `/api/clues`), each with the live `session_id` and, for
    the five that take an optional one, without it;
  - `POST /api/voice/transcribe` with a small fixed WAV, twice: with
    `engine.media.stt.get_stt_provider` stubbed to return a fixed
    transcript, and stubbed to fail with a fixed exception carrying a fixed
    `raw` body. The shipped provider is in-process faster-whisper, which
    would load (and could download) a model, so it is never reached. The
    local-mode error body (`message`, `raw`) is pinned as it is today;
- **the save tree those runs wrote:**
  - each file's path relative to the save base, with its normalised JSON;
  - the save base itself, as a path relative to `project_root()` (it must
    stay `data/saves/<slug>`). It is taken by calling the resolver
    (`saves.saves_base()` / `saves_root()` today, the storage function after
    §4.1) with the cwd set to `project_root()` and `saves._migrated`
    pre-filled, so no legacy migration runs, and nothing is written;
- `GET /api/settings`, `GET /api/games`, `GET /api/games/active`,
  `GET /api/games/clockwork-dark`, `GET /api/games/hue-and-cry`,
  `GET /api/archetypes`, `GET /api/art`, one shipped plate through
  `/story-art/<path>` (status, content type and a SHA-256 of the body), a
  refused `GET /api/media/../x` and a refused `GET /api/audio/../x`;
- `launcher.main(["--check"])`'s output, and `launcher.main([])` with
  `run_scene` stubbed (the lines printed, and the arguments it was called
  with). Both run with `engine.stack`'s probe stubbed to a fixed status per
  service and every start and stop call stubbed and recorded, so nothing
  is probed on the owner's machine and nothing is started, though
  `voxtral_tts` ships `enabled: true, manage: true` (`config/default.yaml`).

`session_id`, `save_id` and timestamps are replaced by stable placeholders,
the same one wherever the same value recurs. The fixtures go under
`tests/fixtures/local_mode/` (LF, under the existing `.gitattributes` rule
extended to that directory). The golden is canary-checked by adding a
`before_request` hook and watching it fail, and by adding a raw
`@socketio.on` handler and watching it fail. The runner in
`tests/local_golden.py` may follow a seam that a later task renames (the
save-base resolver above, say); the fixtures are never re-recorded.

A second test, `test_local_mode_never_imports_hosting`, runs in a fresh
subprocess (under the child sandbox of §3.5 once it exists): it calls
`launcher.main([])` with `run_scene` stubbed, then `create_app(testing=True,
llm_fn=<scripted>)`, plays one scripted turn over HTTP and one `join_session`
over the Socket.IO test client, and asserts that no `engine.hosting` module
is in `sys.modules`. Building the app matters: `FlaskScene.__init__` and
`DefaultScene` are where the hosting branch and the CORS choice live
(§6.3), and a test that stubbed them away would pass with an unconditional
import. It is canary-checked in the hosting task by importing
`engine.hosting` unconditionally in `FlaskScene`.

**Sanctioned differences in local mode, enumerated.** The golden test holds
a `SANCTIONED` list, one entry per difference, each a transform applied to
the recorded fixture before comparing; each entry also asserts that its
transform changes the fixture, so a sanction that no longer applies fails
rather than lingering as a loophole. There are exactly two, and nothing
else in the fixtures may differ:

1. **The bind** (owner decision, 2026-09-30; lands in T2 with the save-id
   fix, so the two LAN-reachable defects close together):
   `app_shape.json`'s `run_kwargs.host` goes from `"0.0.0.0"` to
   `"127.0.0.1"`. `launcher.main([])` passes `host=None` to `run_scene`, so
   its recorded call is unchanged.
2. **`paths.saves` leaves the manifests** (§4.2, T3): the `"saves":
   "data/saves"` key is removed from the `paths` object of every game row
   in `games.json`, and of the manifest in `games_active.json`,
   `games_clockwork-dark.json` and `games_hue-and-cry.json`. No other key
   of those payloads moves.

The template is **not** a sanctioned difference: the hosting block in
`clockwork.html` sits inline on an existing line with no whitespace of its
own, and `hosting` is passed to `render_template` only in hosted mode
(§6.3), so `GET /`'s bytes are unchanged and the golden asserts them as
recorded.

Local-mode behaviour that changes without touching a recorded byte, listed
so nobody mistakes it for drift: a save id, or a loaded save's
`session_id`, outside `SAVE_ID_RE` is refused (§4.3; the golden never uses
one, and every minted id matches); `join_session` joins a room only after
the session is found (§6.4); a `resume` of a malformed id answers
`resume_failed` rather than raising; runtime paths are anchored at the repo
root when the process is started elsewhere (§4.1); a manifest that still
declares `paths.saves` gets an advisory (§4.2); the doctor gains rows in
sections v0.19.0's baselines do not cover (§3.6, §4.1, §2.1, §2.3). v0.19.0's
`doctor_llm.txt`, `doctor_services.txt` and `launcher_report.txt` baselines
cover `check_llm`, `check_services` and `_report`, and those stay
byte-identical.

**Why record on the old code.** It is the v0.19.0 lesson again: a baseline
recorded after the first change is a baseline of the change.

---

## §2 — The config: one more layer, and the secrets chain fixed

### 2.1 `CLOCKWORK_CONFIG`: an operator's file outside the repo

**Decision.** `get_config` gains one optional layer. If `CLOCKWORK_CONFIG`
names a YAML file, it is merged **after** `config/local.yaml` and **before**
the game overlay, and gets the same legacy alias as the other layers. It may
name several files, separated by `os.pathsep` (`;` on Windows, `:` on
POSIX), merged left to right, so the last file wins. The order becomes:

```
config/default.yaml → config/<CLOCKWORK_ENV>.yaml → config/local.yaml
  → [the admin layer, hosted only, §14.9] → $CLOCKWORK_CONFIG (each file,
  left to right) → the game overlay
```

Several files exist for one caller, the test sandbox (§3.5): a test that
needs a hosted child names its own file, and the sandbox's file is appended
after it, so the sandbox's keys always win. An operator names one file.

A named file that does not exist or does not parse is a startup **error**:
`get_config` raises and names the path. It is not skipped with a warning,
which is what `_load_yaml` does for the other layers. An operator who
pointed at a file meant it, and running on the defaults instead would, in
hosted mode, mean running with the wrong auth settings.

**Why.** Two callers need a config file that isn't in the repo tree:

- the Docker image, whose operator config lives on the data volume
  (`/data/config.yaml`), so the image's `/app` stays what was built;
- the test suite's subprocess sandbox (§3.5).

A bind-mounted `config/local.yaml` would work for Docker, but not for tests,
and it would put the operator's config somewhere the Settings panel writes.
When the variable is unset nothing changes, which the golden asserts.

**It says what it shadows.** The layer ranks above `config/local.yaml`, so a
Settings-panel save of a key it also sets would "succeed" and change nothing.
Two places say so:

- the doctor's `check_config` gains a `CLOCKWORK_CONFIG` row naming the file
  and listing the dotted keys it sets (keys only, never values);
- `external_config_keys()` returns those dotted keys, taken **after** the
  legacy `lmstudio:` → `llm:` alias, so a `lmstudio.base_url` in the file is
  reported as `llm.base_url` (the admin panel's refusal, §14.9, reads this
  list, and a key reported under its legacy name would slip past it);
- `POST /api/settings` adds `"shadowed": [<dotted keys>]` to its response
  when a key it just wrote is also set by the external file. The key is
  present only when the list is non-empty, so with the variable unset the
  response is byte-identical.

### 2.2 The scope syntax, made exact (N1–N3)

**Decision.** The syntax is unchanged. Only how it is parsed changes:

- **A scope is a provider name and nothing else.** An alternative is
  scoped only if the text before its first `?` matches `^[a-z_]+$`.
  Anything else, like `file:/srv/keys/what?.txt`, is a whole unscoped
  alternative (N1). No legal `file:` or `env:` alternative starts that
  way, because `file:` and `env:` both contain a `:`.
- **An unknown scope is a load-time error (N2).** `get_config` walks the
  merged tree once. For every `${...}` string it finds a scope that matches
  the pattern but is not a key of `PROVIDERS`, and it raises
  `ValueError`, naming the dotted key and the bad scope. That is the same
  treatment as an unknown `llm.provider`.
- **The scope test reads the provider raw (N3).** `_expand` reads
  `llm.provider` through a new `ConfigManager._raw(path)`, a plain dict walk
  that never expands. A `${...}` in `llm.provider` itself is refused at
  load: the provider selects a code path, and it is not a secret.

The shipped `api_key` string is unchanged. So every existing key file and
variable resolves exactly as in v0.19.0, and the LLM golden's
`Authorization` header is untouched.

### 2.3 The doctor says which key sources it skipped (N4)

**Decision.** `_check_llm_keys` gains one row per scoped alternative that
was **skipped but would have produced a value**: its file exists and isn't
empty, or its variable is set. The row reads (WARN): "`lmstudio.txt` holds a
key, but `llm.provider` is `vllm`: it is LM Studio's and is not sent. Put
this server's key in `llm_api_key.txt` or `CLOCKWORK_LLM_API_KEY`." It
reports the source, never the value or its length. Under the shipped LM
Studio config nothing is skipped, so `doctor_llm.txt` is unchanged.

---

## §3 — Linux as a first-class platform

### 3.1 Rule 11 becomes platform-neutral

**Decision.** AGENTS.md rule 11 reads:

> 11. **Platform-neutral, server-agnostic.** Windows and Linux are both
>     supported: no code assumes a path separator, a drive letter, a
>     case-insensitive filesystem or an `.exe`, and every script has a
>     PowerShell and a POSIX way in (`scripts/start.ps1`, `scripts/start.sh`).
>     LM Studio at `http://localhost:1234/v1` is the default model server;
>     vLLM, llama-server, Ollama and OpenAI-compatible servers are set by
>     `llm.provider` (docs/MODEL_SERVERS.md). Local single-player is the
>     default; hosted mode (`hosting.enabled`, docs/HOSTING.md) is opt-in.
>     Use `scripts/start.ps1` / `scripts/start.sh` or `launcher.py --stack`.

The "Verify a checkout" block shows both spellings
(`.\.venv\Scripts\python.exe` and `.venv/bin/python`). CLAUDE.md's machine
notes stay what they are: facts about this workstation. The rule also
reaches the scripts that print next steps: `scripts/new_story.py:175`–`:178`
and the usage docstrings that name only `.\.venv\Scripts\python.exe` gain
the POSIX spelling beside it.

### 3.2 `scripts/start.sh`, and no Makefile

**Decision.** `scripts/start.sh` (POSIX `sh`, LF, committed with the
executable bit through `git update-index --chmod=+x scripts/start.sh`,
because this checkout has `core.fileMode=false`) does what `start.ps1`
does, line for line: it creates `.venv` with `python3.11`, else `python3`
if that is 3.11 or newer, else it fails and names the requirement. Then it
installs `requirements.txt` under `constraints.txt` (§3.10), runs the suite
and prints the same next steps. A test parses both scripts' "Next steps"
blocks and asserts they list the same commands, modulo the interpreter
path, so the two cannot drift; another reads the file's mode from the git
index (`git ls-files -s`, `100755`).

**Why no Makefile.** It would be a third copy of the same six commands, and
`make` isn't on a stock Windows box. The two start scripts are the entry
points, and the README names both.

### 3.3 Service commands without `.exe`

**Decision.** `config/default.yaml`'s stack commands drop the suffix
(`target/release/tts-server`, `target/release/voxtral`).
`StackService.resolved_command` (`engine/stack.py:80`) resolves a local
command name the way `shutil.which` already resolves a PATH one: on Windows
it tries the name, then the name plus each `PATHEXT` suffix. So the
Windows lookup finds the same `tts-server.exe` it found before, and the
doctor's services baseline prints the same resolved path. An owner's
`local.yaml` that still says `.exe` works on Windows, unchanged.

### 3.4 Case and separators, checked on every platform

**Decision.** A new `tests/test_portable_paths.py` walks every manifest
`paths:` value, every file a story's content names (art keys, deck and
scene files, lore corpus), and every relative path in `config/default.yaml`.
It asserts three things:

- the path contains no `\` and no drive letter;
- **each component matches a directory entry exactly**, by an `os.listdir`
  comparison and not by `exists()`, which is case-insensitive on Windows;
- every repo filename is unique case-insensitively.

It runs on Windows, so a case slip is caught before it reaches a Linux
host.

The studio's path check (`engine/studio/api.py::_safe_path`) refuses a
backslash or a drive-lettered path on every platform, not only where the OS
calls it absolute. A story file named `C:` is a story that can't be checked
out on Windows. `tests/test_studio.py:60`'s case then holds on both
platforms, unchanged.

### 3.5 The test guards, across processes (carried item 4)

**Decision.** At session start, the conftest writes a **sandbox config
layer** into the session's temp root and hands it, as `CLOCKWORK_CONFIG`
(§2.1), **to child processes only**. It is never exported through
`os.environ`: `CLOCKWORK_CONFIG` ranks above `local.yaml`, so an in-process
export would rewrite the config every in-process test sees, and v0.19.0's
LM Studio golden (its request fixtures, scenario 23's URL,
`doctor_llm.txt`, `doctor_services.txt`), the local golden and every test
that asserts `localhost:1234` would all diverge. Instead a session-scoped
conftest fixture wraps `subprocess.Popen.__init__` (which `subprocess.run`,
`check_output` and `call` all go through): a call with no `env=` gets a copy
of `os.environ` plus the two sandbox variables, and a call with an `env=`
gets them added to it. A `CLOCKWORK_CONFIG` the caller already set is kept,
not overwritten: the wrapper **prepends** the caller's files and **appends**
the sandbox layer last (§2.1's list), so a test can turn hosting on in a
child (`hosting.enabled`, `hosting.stories`) and the sandbox still wins on
every key it sets. A child's own children (the supervisor's workers and
front door, §14.3) inherit both variables from the child's environment, so
the whole tree is sandboxed. A test pins that no test module calls `os.system`,
`os.spawn*` or `os.exec*` (an AST scan of `tests/`), the doors the wrapper
does not cover. The conftest also removes `CLOCKWORK_CONFIG` and
`CLOCKWORK_DATA_DIR` from `os.environ` at session start, so neither the
owner's shell nor a CI runner's can reach an in-process test. The layer
sets:

- `llm.base_url: "http://127.0.0.1:9/v1"`, the discard port, which refuses
  the connection;
- `llm.mcp.enabled: false`;
- `llm.mcp.mcp_json: <temp>/lm-studio/mcp.json`;
- `storage.root: <temp>/data` (§4.1);
- `stack.services.*.manage: false`.

**CURRENT (v0.20.0 T5 fix rounds 1-2):** the marker is `<suite pid><os.pathsep><layer path>`, set in the suite's OWN environment (pid-only at conftest import, upgraded in `pytest_configure`, captured, and re-injected by the wrapper into every child whatever its `env=`), inert in the pid it names (`engine.config.child_sandbox`); a stray one fails the suite fast and is a doctor and `launcher.py --check` FAIL. In a child `get_config` merges the layer last, skips `local.yaml` and forces ComfyUI, TTS, STT, `llm.mcp` and every `stack.services.*.manage` off and `llm.base_url` to the discard port -- except that the sandbox layer's own `llm.base_url` is kept when it is loopback on the port the test registered (`tests/conftest.py::sandbox_model_stub`, `CLOCKWORK_TEST_MODEL_STUB_PORT`), which is how T16's supervisor child reaches its stub model server; the Settings panel neither reads nor writes `local.yaml` there. What follows is the original text. The same wrapper gives children `CLOCKWORK_TEST_SANDBOX=<temp root>`. The
engine honours it in exactly three places:

- `skills_server.backup_once` and `skills_server._write_json_atomic` refuse
  and log any target outside that root while it is set, so a subprocess
  that rebuilt its config from scratch still cannot write the owner's
  `mcp.json`;
- `get_config` skips `config/local.yaml` while it is set, so a child never
  reads the owner's hand-kept file. Without this a child's config depends on
  the machine: an owner's `llm.mcp.enabled: true` there would make every
  hosted child in the suite refuse to start (§6.7), and any other key it
  sets would reach the child unless the sandbox layer happened to override
  it.

Four tests cover it. One spawns a child (a script file under
`tests/probes/`, since `python -c` loses backticks on this machine) that
imports the engine and registers a session into `mcp_json_path()`, and
asserts the write landed in the temp root. The second asserts that a
child's `get_config()` reports the discard `base_url`, and that a child
given its own `CLOCKWORK_CONFIG` setting `hosting.enabled: true` and
`llm.base_url` sees hosting on and the discard `base_url` (the caller's
file kept, the sandbox's last). The third asserts that a child does not
read `config/local.yaml` (a `_CONFIG_DIR` stand-in whose `local.yaml` sets
a marker key). The fourth asserts that the **in-process** `os.environ`
holds neither variable and that `get_config().get("llm.base_url")` is still
the shipped default. The first three are canary-checked by removing the
wrapper (and, for the third, the `get_config` rule), the fourth by
exporting the variable.

**Why a config layer and not more monkeypatching.** A monkeypatch can't
cross a process boundary, and an environment variable can. The layer is
also the one mechanism the Docker image uses, so the sandbox exercises the
production path. The guards in `skills_server` and `get_config` are
defence in depth and machine independence: they are keyed on a variable no
production deployment sets, and each docstring says so.

### 3.6 The doctor on Linux

**The local default bind becomes `127.0.0.1`** (owner decision,
2026-09-30). `config/default.yaml`'s `scene.clockwork.host` goes from
`"0.0.0.0"` to `"127.0.0.1"`, and so does `FlaskScene.run`'s parameter
default. Why: finding 1 reached arbitrary directory deletion on Windows and
finding 6 any player's stream, both from every device on the LAN, and a
player never chose that exposure. v0.20.0 brings the supported way to
share, hosted mode, with accounts; LM Studio itself binds loopback by
default, so the stack is consistent. LAN play without accounts stays one
line away: `scene.clockwork.host: "0.0.0.0"` in `config/local.yaml`, which
the doctor then WARNs about (below). `config/docker.yaml` sets `0.0.0.0` for
the image (§8.1). The change lands with the save-id fix (T2), is the first
of §1's two sanctioned golden differences, and gets a README and CHANGELOG
line.

**Decision.** `check_python` gains a `platform` row:
`platform.system()`, the release, and whether the filesystem under the
repo is case-sensitive (probed with a temp file). `check_config` gains a
`storage` row (the resolved root, and whether it is writable; in the image,
a root-owned bind mount on `/data` is named as the cause, §8.1) and a
`hosting` row:

- hosting **off**: OK, "local single-player on 127.0.0.1". A WARN replaces
  it when `scene.clockwork.host` is not a loopback address: "anyone who can
  reach port 5573 can play, load and delete runs, with no login; bind
  127.0.0.1, or turn on hosting (docs/HOSTING.md)";
- hosting **on**: §7.4's rows.

`mcp_json_path` already knows the Linux locations (`~/.lmstudio`,
`~/.cache/lm-studio`), and gains a test that runs under a faked POSIX home.

### 3.7 Voice, images and model servers on Linux

What the engine ships runs on Linux unchanged. Everything else is an
external service reached by URL, and `docs/HOSTING.md` § Linux says so
service by service:

| Service | Engine side | On Linux |
|---|---|---|
| Model servers | `engine/llm/` (v0.19.0) | LM Studio has a Linux AppImage; llama-server, Ollama and vLLM are native. vLLM is verified live in §10 |
| STT: faster-whisper | in process, optional | pip wheel, CPU or CUDA (CTranslate2); unchanged |
| STT/TTS: Voxtral | `stack.services.voxtral_*`, by URL | the Rust servers build from source (`cargo build --release`), and the extension-free command (§3.3) finds them |
| ComfyUI | by URL, `manage: true` runs `python main.py` | native; `command: python3` where `python` is absent (documented, not defaulted) |
| Grok image CLI | subprocess | whatever the CLI supports; not verified here |

None of these is started, installed or measured by this release. They
keep their `enabled: false` defaults.

### 3.8 CI: GitHub Actions on `ubuntu-latest`

**Decision.** `.github/workflows/ci.yml`, run on push to `main` and
`release/**` and on pull requests, with three jobs:

- **`suite`:** Python 3.11,
  `pip install -r requirements.txt -c constraints.txt`, then
  `pytest tests -q` with `timeout-minutes: 150` (budgeted for a 2-vCPU
  runner; the owner's 33 minutes is a 12-thread desktop), using
  `fetch-depth: 0` so `test_the_committed_build_is_not_behind_its_source`
  can read history. The model-server guards keep it off any model server,
  and none exists there.
- **`client`:** Node 20, `npm ci --prefix ui`, `npm test --prefix ui`,
  `npm run build --prefix ui`, then `git diff --exit-code
  content/scenes/clockwork/static/dist`, which fails if the committed build
  is stale on a clean Linux build as well. That diff assumes Vite's output
  is byte-identical across operating systems, which is **measured first**:
  T4 builds the client in `node:20-bookworm-slim` and diffs it. If it
  differs, the job runs `npm test` and the build only, the diff step is
  left out, and the reason is a deferred row.
- **`image`:** `docker build .` (no push), then a smoke test: start the
  container with a throwaway `CLOCKWORK_SECRET_KEY` and assert
  `GET /api/health` answers.

**Why one suite job and not shards.** The suite takes about 33 minutes here.
Sharding needs `pytest-xdist` or `pytest-split`, and the suite has never
run in parallel workers: it has process-wide singletons, story activation
and temp-dir guards. Making it xdist-safe is its own work, recorded as a
deferred row. The measured CI time is written into CLAUDE.md at the
release.

**Why no Windows job.** The owner's workstation is Windows, and the suite is
run there at every release, as today. A `windows-latest` job would double a
two-hour run to prove what is already proven by hand.

A workflow file runs only once it is pushed, and nothing is pushed without
the owner's word. The first green run is recorded at the release if the
owner has pushed by then, and otherwise the container run (§3.9) is the
Linux evidence.

### 3.9 The suite in a Linux container, on this workstation

**Decision.** T4's first step writes a download manifest
(`.superpowers/sdd/v020-downloads-linux.md`), then **stops with status
`NEEDS_CONTEXT`**. The controller asks the owner in chat; the owner
consents item by item **and approves the session's permission prompt
personally**. A consent relayed by an agent is not consent: the permission
system refuses it, and no step treats it as approval. The manifest lists
the item, its source, its size read from the registry, and why:

- starting Docker Desktop's engine;
- `python:3.11-slim-bookworm`, pinned by digest;
- the Debian packages `apt-get` fetches inside it (`git`), with sizes;
- the wheels `pip` fetches inside it, listed from `requirements.txt` under
  `constraints.txt` (§3.10), with sizes;
- `node:20-bookworm-slim`, only for the client build check (§3.8).

**Not a bind mount.** A Docker Desktop bind mount of an NTFS directory is
case-insensitive inside the container (NTFS per-directory case sensitivity
is off by default), so the very property §3.4 exists for would go
untested, and its file sharing is many times slower for a small-file-heavy,
SQLite-using, 33-minute suite. So the checkout is bind-mounted **read-only**
only as a clone source: the test image (`python:3.11-slim-bookworm` plus
`apt-get install git`) runs `git clone /src /work` into a container
volume, and the suite runs on `/work`, on the container's own
case-sensitive filesystem. The clone carries `.git`, so
`test_the_committed_build_is_not_behind_its_source` runs rather than skips.
It runs the committed `HEAD`, so T4 commits its Windows-side changes before
it measures, and each round of Linux fixes is committed and pulled into
`/work` (`git -C /work pull`) before the next run; the rounds squash at the
release like every other `wip` commit.

**The expected skip set, per environment,** is written down rather than
counted after the fact, and the run's report lists each skip's reason
against it:

- the owner's Windows checkout: the stamina soft-lock test, the live module
  (`tests/test_llm_live.py`), and whatever else v0.19.0's release measured;
- a fresh clone (the container, CI): the same, plus the Design_files-only
  Garden test, because `Design_files/` is gitignored.

The run's failures are the Linux work list. The known one is
`test_studio.py:60`, and the rest are measured, not guessed. The pass count,
the skip set and the time go into CLAUDE.md.

**Why a container and not WSL.** Both distros are stopped. Ubuntu 22.04's
system Python is 3.10, which is below `requires-python`, and getting 3.11
there means a PPA or a toolchain on the owner's distro. The container image
is also the base the release's own Dockerfile uses (§8), so the platform
the suite proves green is the platform that ships.

### 3.10 `constraints.txt`: one set of versions everywhere

**Decision.** A committed `constraints.txt` pins the version of every
distribution the owner's `.venv` holds (`pip freeze --all`, taken in T4,
before the container run, with a header saying where and when it was
taken). `requirements.txt` keeps its `>=` ranges, which say what the code
supports; the constraints file says what was tested. Every installer uses
both: `scripts/start.ps1`, `scripts/start.sh`, the Linux container, CI and
the Dockerfile run `pip install -r requirements.txt -c constraints.txt`,
and `requirements-server.txt` (§8.1) opens with `-c constraints.txt`. A
constraint names a version, not a platform, and pip ignores a constraint on
a package nothing requires, so a Windows-only entry in the freeze costs a
Linux install nothing. `tests/test_constraints.py` asserts every
distribution named in `requirements.txt` and `requirements-server.txt` has
a pin, and that the installed version of each equals its pin (skipping one
that is not installed). Re-pinning is a deliberate edit, recorded in the
CHANGELOG, never a side effect.

**Why.** The goldens pin bytes, and engineio's CORS defaults, Werkzeug's
test-client routing and the save-id probe's behaviour are all
version-dependent. "The platform the suite proves green is the platform
that ships" is only true if it is the same versions.

---

## §4 — Storage: one engine-owned root

### 4.1 `storage.root`

**Decision.** A new top-level block:

```yaml
storage:
  # Where the engine writes what it makes at run time: saves, generated
  # media, and (hosted) accounts. Relative to the repo; CLOCKWORK_DATA_DIR
  # beats it. The default is the layout every release has used.
  root: "data"
```

Resolved once per `get_config()`: `CLOCKWORK_DATA_DIR`, else
`storage.root`, and a relative value is taken against `project_root()`,
never the working directory (finding 2). From it:

| Output | Local (hosting off) | Hosted |
|---|---|---|
| saves | `<root>/saves/<slug>/` | `<root>/users/<user_id>/saves/<slug>/` |
| generated images | `<root>/media/images/` | same (shared cache, §6.8) |
| synthesized audio | `<root>/media/tts/` | same |
| accounts, cookie key | none | `<root>/hosting/` |

With the default, every local path is byte-for-byte the v0.19.0 path, which
the golden asserts.

**The mechanism: functions, and the constants removed.**
`engine/persistence/storage.py` (new) holds `data_root()`,
`saves_dir(owner, slug)`, `media_dir()`, `image_dir()`, `audio_dir()` and
`hosting_dir()`, each read on call, never at import. The module constants
`MEDIA_DIR` (`engine/api/media.py:38`, `engine/media/providers/base.py:31`),
`IMAGE_DIR` (`providers/base.py:32`) and `AUDIO_DIR`
(`engine/media/tts.py:48`) are **deleted**, not kept as aliases: a module
has no properties, and `from ... import IMAGE_DIR` binds a value at import
(`providers/procedural.py:25`, `providers/__init__.py:20`,
`scripts/generate_art.py:800`), which would freeze the path before
`CLOCKWORK_DATA_DIR` is read. Those callers, and the two routes, call the
functions instead. `tests/test_generate_art_cli.py:58` monkeypatched
`base.IMAGE_DIR`; it now sets `CLOCKWORK_DATA_DIR` to its `tmp_path` with
`monkeypatch.setenv`, the production seam. A test scans `engine/` and
`scripts/` (AST) for any remaining `MEDIA_DIR`, `IMAGE_DIR` or `AUDIO_DIR`
name. This is finding 2's whole fix, saves and media together, so each
constant is touched once.

`saves.saves_base()` stays as the single seam for the local save base (the
conftest monkeypatches it, `tests/conftest.py:199`, `:321`): it becomes
`storage.saves_dir("", None)`'s parent, and `saves_root()` keeps its
legacy-migration step, now under a lock (§5.2). `save_store_for(owner,
slug)` for a non-empty owner never runs the legacy migration, which exists
only for the owner's old flat `data/saves/`.

**The lore index is not moved.** `paths.lore_db` is a derived index of
shipped content, already resolved against the repo root
(`engine/lore/manager.py:74`). The Docker image seeds it at build time
(§8.1).

### 4.2 `paths.saves` retires from manifests (carried item 3)

**Decision.** Saves are the engine's, not the story's.

- `saves` leaves `OUTPUT_PATH_KEYS`' manifest role. `config_overlay()` drops
  a manifest's `paths.saves`, so it can no longer outrank anything.
- A manifest that declares it gets an **advisory** from
  `scripts/validate_content.py` and the doctor. It is not a
  `registry.validate` problem (`engine/games/registry.py:185`), which would
  make the story unplayable. If the value differs from `data/saves`, the
  advisory says that the value is ignored and that saves live under
  `storage.root`.
- The six shipped `game.yaml` files lose the line, with each story's
  `CHANGELOG.md` saying so. That is a story change with no content effect.
- A `paths.saves` in `config/local.yaml` or `CLOCKWORK_CONFIG` is read for
  one release as a legacy alias for the **exact** save base, with one
  WARNING and a doctor WARN row naming the file. It is removed in v0.21.0,
  with the `lmstudio:` alias. `config/default.yaml` drops `paths.saves` in
  favour of `storage.root`.

**Every reader and writer of the key**, from a grep on 2026-09-30, moves in
the same task:

- the six `games/<slug>/game.yaml` files;
- `scripts/story_template/{deck,graph,minimal}/game.yaml`, or every
  scaffolded story would be born with the advisory, and
  `tests/test_new_story.py:66`, which asserts the scaffold's paths;
- `engine/games/manifest.py:84` (`OUTPUT_PATH_KEYS`) and
  `engine/games/registry.py:185`–`:196` (its validation of output keys);
- `tests/conftest.py:199`, `:321` (the `saves.saves_base` redirect, which
  stays the one seam) and `:797`;
- `scripts/doctor.py:581`;
- the `engine/api/settings.py:16` docstring;
- `docs/AUTHORING.md:88`–`:105`, which advises restating `saves:`.

**The owner's existing runs.** In hosted mode an account's saves live under
`<root>/users/<id>/`, so the owner's local `data/saves/<slug>/` runs are not
visible to any account. `scripts/users.py adopt <name> [--game <slug>]`
moves them (a rename, never a copy) into that account's directory, one
story at a time, refusing any save id already there. Without it they stay
local-only, which `docs/HOSTING.md` says.

**Why not keep the manifest key and just rank it lower.** A story author
has no legitimate reason to choose where a player's saves go. The comment
above the key in `games/clockwork-dark/game.yaml:77` already calls saves "a
runtime OUTPUT the engine owns". Keeping a key nothing should set is how
this codebase grew keys nothing reads.

### 4.3 Save ids are names, not paths (finding 1)

**Decision.** `SaveStore` checks every id against
`SAVE_ID_RE = ^[A-Za-z0-9_-]{1,64}$` in `_dir`, and so in `save`, `load`,
`exists`, `delete` and `append_transcript`. A bad id raises `ValueError`.
The four routes and the socket's `resume` answer it as they answer a
missing save (404, or `resume_failed` with the missing-save wording), so an
id that is not ours looks exactly like one that does not exist. A test
sends `../x`, `..`, `.`, `%2e%2e`, `..%5c..%5cx`, `C:%5cx`, an absolute
path and a 65-character id to every door, fails on v0.19.0, and asserts
that no file is created, changed or removed outside the store's root (a
sentinel file beside the store survives each `DELETE`). Minted ids
(`uuid4().hex[:12]`) and every id the client has ever held match the
pattern. Because `session_id` is persisted in the save (`state.py:199`),
the same pattern is checked on a loaded envelope's `session_id`, so a
hand-edited save cannot smuggle a room name.

### 4.4 A session carries its save store

**Decision.** `GameSession` gains `owner: str = ""` and `saves: SaveStore`,
set when it is built. The places that used the process singleton read the
session's store instead:

- `_autosave` (`default_state.py:884`);
- `SessionStore.create` and `resume`;
- `engine/api/saves.py`.

`get_save_store()` stays, as "the store for owner `""` and the active
story". Local mode therefore resolves the same `SaveStore` object it does
today. `save_store_for(owner, slug)` builds and caches one store per pair,
under a module lock, each store with its own index lock.

The local two-tabs case (finding 7) is recorded, not fixed. Returning the
live session on `resume` would change the frame a reconnecting local
player gets (`resume_opening`'s `resumed: true` frame against the last
turn), and local mode doesn't change. It is a deferred row in CLAUDE.md,
worded as finding 7 now is: a second `resume` rebuilds under the same id,
a turn in flight on the old engine can autosave over it, and both tabs
drive the new engine.

---

## §5 — Hosted mode: the process model and the shared model server

### 5.1 One process, many sessions, many threads

**Decision.** A hosted **worker** is **one process serving one story**:
gunicorn with exactly one `gthread` worker and a pool of threads (§7.1).
Every player's session lives in that process's `SessionStore`, keyed by
session id and owned by a user id. A hosted **instance** is a supervisor
running one such worker per story it serves, and a front door in front of
them (§14.1). The decision below is per worker and is unchanged by §14:
§14 multiplies workers by story, never by player, and moves the one thing
that must be shared across them, the model server's lanes, into the
supervisor (§14.4).

**Why not process-per-user.**
- Each process would load every content cache, the lore index and any
  in-process STT model: tens of MB to GBs, per player.
- The inference gate (`engine/llm/gate.py`) is per-process, so N processes
  would each think they owned the model server's lanes and oversubscribe
  it: the exact stall the lanes exist to prevent. (Under §14 the lanes are
  held by the supervisor for every worker, which is what makes a process
  per story safe; it would make a process per player *safe* too, but not
  cheap, for the reason above.)
- It would need a port and a process per player, created and reaped as
  players come and go. A process per story is a fixed, small set the
  operator names in config (§14.3).

**Why not several workers.** Socket.IO rooms, the `SessionStore` and the
gate are all in memory. Several workers would need sticky sessions and a
message queue (Redis) for Socket.IO, and a shared lock for the gate. For a
handful of players the bottleneck is the GPU, not the GIL.

**Why this works without an engine rewrite.** The engine is already built
for concurrent sessions in one process:

- the active engine is a `ContextVar` (`engine/game/engine.py:336`), so a
  skill never resolves against the wrong player's state;
- each session has its own turn lock (`engine/session/store.py:171`);
- the save index takes a lock (`saves.py:331`);
- the lore index is thread-safe (`engine/lore/manager.py:133`).

It is not already built for all of it: survey item 12 names module state
that assumes one turn in the whole process. §5.2 sorts every piece, fixes
the races, and pins the list so a new one cannot arrive unclassified. A
test (§9.3) then runs two players' turns interleaved and asserts neither
sees the other, and targeted tests (§9.3) force the windows a scripted
two-player run is unlikely to land in.

### 5.2 Every process-wide singleton, sorted

**How the list was made.** Not from memory. An AST scan of `engine/`
(2026-09-30) listed every module-level name that is rebound through a
`global` statement, bound to a mutable container, `None`, a
`threading`/`contextvars` object or an instance of a class (T6 fix round 1:
`SKILL_REGISTRY`, `dice._UNSEEDED`, `endings._CLOSENESS`), plus every
container in a class body (`EvilPhaseTone._TONE`), every `@lru_cache`
function (24, in 17 modules: T6's scan, `tests/module_state_scan.py`, also
matches `@functools.lru_cache`, which the first pass missed in
`lore.interceptors`, `media.art` and `media.providers.shipped`), and every
site that starts threads: 4, not the 3 this line first said -- the three
`threading.Thread(` calls (`SkillsServer.start`, `ImageWorker.start`,
`SpeechWorker.start`) and the per-turn `ThreadPoolExecutor` in
`agents/pipeline.py::_gather` (one pool a turn, as many workers as the
story's pipeline agents, joined before `_gather` returns; its workers get no
copy of the caller's ContextVars, and `plan_for` reads none); the scan also
matches `threading.Timer(`, `ProcessPoolExecutor(` and `Thread` subclasses,
of which the engine has none. `__all__` is left out of the scan. The rows
below are that list, grouped by verdict: 195 sites after T6's fix round 2.
`tests/test_module_state_inventory.py` re-runs the same scan and compares it
with `tests/fixtures/module_state.yaml`, which classifies each site under one
of the verdicts below. A new module global, class-level container, instance,
`lru_cache`, thread or pool fails the test until someone classifies it, which
is the moment to ask whether it races. A few names below are not scan sites
and are listed for completeness: a table bound to a loader's result and
reloaded in place (`locations.LOCATIONS`, `assistant.HINTS_BY_TIER`,
`LORE_SNIPPETS`).

**One lock order** (T6 fix round 1). Every lock the engine names has a place
in one total order, written once in `engine/locks.py`'s docstring, outer
first: `caches._warm_lock`; games `registry._lock`; `quests._grammar_lock`;
`backend._backend_lock`; a backend's own `_lock`; `llm.registry._registry_lock`;
`profiles._cache_lock`; `gate._lanes_lock`; `mechanics._ENGINES_LOCK`;
`skills_server._server_lock`; `stt._provider_lock`; `stt_whisper._models_lock`;
the getter locks (`client`, `ollama`, `lore.manager`, `scene_rules_engine`,
`media.queue`, `media.providers`, `media.tts`, `default_scene._store_lock`,
`oracle._oracle_lock`); `saves._stores_lock`; `saves._migrated_lock`; an
Oracle's own `_lock`; and `config._config_lock`, innermost. A thread holding
one may take only a later one. So warming holds its own lock, first, never
the config lock; activation holds the registry's lock across `set_overlay`
and the whole reset walk; and nothing holding the config lock takes another
(`reset_config` walks the resets after releasing it). `tests/lock_order.py`
wraps each lock in a checker that fails on any acquisition out of order; it
runs over every race test and over warming, activation, a reset, a Settings
save and a turn's getters racing on six threads (failing on 3c0ca34, whose
warming held the config lock over the rules engine's). Every module lock is
also renewed in a forked child (`engine.locks.renew_after_fork`,
`os.register_at_fork`), so a gunicorn master that forks while one of its
threads holds a lock does not hand the worker a lock nobody will release.

**Leaves, turn locks and lanes** (T6 fix round 2). Four per-object locks are
leaves, outside the order because nothing is taken under them: `SaveStore._lock`
(the index bound and the save's summary are now read before it is taken),
`ModelRegistry._lock`, `LoreManager._write_lock` and `SessionStore._guard` (whose
idle sweep only try-acquires turn locks, non-blocking). A session's turn lock
is held across a turn but only ever taken non-blocking (pinned by AST), so it
is never waited for; a lane semaphore is held across a model call but taken
holding no ordered lock or leaf, and with a timeout. The checker asserts all
three.

**A reset between a loader's store and its return** (T6 fix round 2). A config
reset nulls every `NULLED_ATTRIBUTES` cache with a plain `setattr`, no lock.
Every loader of one (the 15 content loaders, the recipe memo, the five
warn-once sets) now reads its cache once into a local, builds into a local,
assigns the global and returns the local, so a reset between two touches
costs a rebuild, never a `None` or a mid-turn `TypeError`;
`tests/test_cache_reset_race.py` pins the shape by AST and forces the race on
each loader with a line tracer. The rules engine left `NULLED_ATTRIBUTES` for
a RELOADER, `reset_rules_engine`, which drops it under `_rules_lock`.

**The skills server starts outside its lock** (T6 fix round 2; MCP is not
served hosted, but a local LM Studio setup had every turn queue up to ten
seconds behind a start). `get_skills_server` is single flight: one caller
starts the server outside `_server_lock`, the others get None ("not ready",
this turn runs without tools) at once; a failed start is not retried until
`llm.mcp.start_retry_seconds` (default 60) have passed; a reset during a
start keeps it from being published.

There are three verdicts that do work (**per context**, **locked**,
**warmed, then read-only**) and four that record why nothing is needed.

**Warming.** `engine/games/caches.py` already lists every per-story cache
with its reset. It gains `WARMERS` and `warm_all_caches()`, which calls each
registered loader once, in registration order, under its own lock (first in
the lock order; the config is built and the story's paths read before it
starts), the grammar first. Hosted mode's `install()` (§6.3) calls it, then
`quests._ensure_grammar()` (already loaded by then),
`get_governance()`, `get_lore_manager()`, the LLM backend, registry and
client getters, and `get_oracle()`, **before the app accepts a request**
(`wsgi.py` builds the app, which installs, before gunicorn serves it). A
warmed cache is then only read while serving, because every path that
resets one is refused in hosted mode: `POST /api/settings` (§6.7), the
studio (§6.7), and activation, which happens once, before the app is built
(§7.1). A test drives the §9.4 crawl with `reset_config` and
`reset_all_caches` patched to raise, and asserts neither is reached. A test
also asserts that `warm_all_caches()` calls every loader `caches.py`
registers, so a cache added there is warmed without anyone remembering to.

| Verdict | Names (file) | Why |
|---|---|---|
| **Per context, already** | `_active_engine` ContextVar (`engine/game/engine.py:336`); `clock._guard`, `encounter._death_guard`, `encounter._terminal_lock_guard` (`threading.local`); `pipeline._gather`'s `ThreadPoolExecutor`, per turn by design and bounded (one pool a turn, one worker per pipeline agent, joined before it returns; the workers see none of the caller's ContextVars, and `plan_for` reads none) | each is set and cleared inside one call, so gthread's thread reuse cannot carry one over (asserted in §9.3) |
| **Per context, made so** (fix) | `inventory._evaluating_collections` (`engine/game/inventory.py:622`) becomes a `threading.local` flag, like `clock._guard`; `validation._RUN_DOCS` (`engine/games/validation.py:395`) becomes a `ContextVar` | the first skips another player's payout (item 12). The second is set and restored around a validator run: two overlapping runs restore each other's dict, and the later `finally` leaves a stale document cache installed for good. Validation runs only in the doctor, `validate_content.py` and the studio, none of them served in hosted mode, but the fix is one line |
| **Locked, made so** (fix, T6) | `quests._grammar_loaded` (`engine/game/quests.py`): a lock (`_grammar_lock`, an `RLock`, with `_grammar_loading` for a same-thread re-entry) around the import loop, and the flag set **after** it (a failed import still does not retry: the attempt is recorded under the lock); the loaded hot path takes no lock; `Oracle` (`engine/telemetry/oracle.py`): one lock taken by every `record_*`, `metrics` (its snapshot) and `recent`; `config._instance`, `_instance_pid`, `_legacy_layers` and `_external_layers` (`engine/config.py`): `_config_lock`, an `RLock` around the build in `get_config` (double-checked, so a built instance costs one read), re-entrant because a manifest read on a `story_paths` miss can ask for config again; `reset_config` and `set_overlay` drop the instance (and swap the overlay) under it, so a build in flight finishes and is dropped, but walk the cache resets **after** releasing it -- the resets take the backend's, lanes', profiles' and LLM registry's locks, whose holders call `get_config`, so holding the config lock across them could deadlock (the config lock is innermost in the one lock order above); `registry.active()` double-checked under the registry's lock (two first callers activated twice); `config._story_paths_by_slug`: a miss filled under the config lock, never cleared; `saves._migrated` (`engine/persistence/saves.py`): checked, migrated and then recorded under `_migrated_lock`; the `save_store_for` cache `saves._stores` (§4.4) under `_stores_lock`; the lazy getters that built a shared object with no lock, each now double-checked under its own lock: `oracle._oracle`, `lore.manager._manager`, `llm.client._client_instance`, `llm.ollama._client_instance`, `mcp.scene_rules_engine._rules_instance`, `media.queue._queue`, `media.providers._worker`, `media.tts._worker` (built and started under the lock; a reset swaps the reference under it and stops the old worker after releasing it), `default_scene._store`. The client releases a config reset runs (`release_lms_client`, `release_ollama_client`) swap the reference under the getter lock, so a release during a build waits for it and drops what it built; the registry nulls `_rules_instance` without it (the rules engine holds no state of its own); `save_store_for` reads `_stores` once under its lock, since a reset nulls it without | the grammar is item 12's wrong-endings race. The Oracle's own docstring disclaimed thread safety. Two threads building a config at once each clear and refill `_legacy_layers` and can publish different instances. Two first calls to a worker getter start two worker threads |
| **Locked, already** | `backend._backend`, `registry._registry`, `profiles._cache`/`_cache_config`, `gate._lanes`/`_limits` (`engine/llm/`); `stt._provider`/`_provider_config`, `stt_whisper._models`; `skills_server._server`; `mechanics._ENGINES` (`_ENGINES_LOCK`); `registry._active` (`RLock`); each `SaveStore`'s index lock; the lore manager's write lock; every lock object is itself a `locked` row | checked, no change |
| **Warmed, then read-only** | each has a loader in `engine/games/caches.py::WARMERS` (T6), which `warm_all_caches()` calls: `quests._ARC_CACHE`/`_QUEST_CACHE`, `procgen._TEMPLATE_CACHE`, `reputation._FACTION_CACHE`, `set_pieces._CACHE`, `governance._GOVERNANCE`, the `_SPEC_CACHE` of `agendas`, `clues`, `jobs`, `law`, `premises` and `thievery`, `schedules._SCHEDULE_CACHE`/`_RUMOR_CACHE`, `npc_sim._SCHEDULE_CACHE`, `world_effects._EFFECTS_CACHE`, `comfyui._TEMPLATE_CACHE`, `skills.builtin.mechanics._RECIPE_CACHE`, `state.active._schema`/`_roster`, `evil_ticker._DOOM_DECLARED`; the story tables reloaded in place by activation (`locations.LOCATIONS`, `CANON_IDS`, `CANONICAL_LOCATION_IDS`, `LOCATION_IDS`; `assistant.HINTS_BY_TIER`, `LORE_SNIPPETS`, `_FALLBACK_HINT`), warmed by importing their modules; the 24 `@lru_cache` loaders (`prompts`, `challenges.spec`, `deck`, `checks`, `clocks`, `economy`, `encounter` ×2, `endings`, `epilogue`, `foraging`, `inventory` ×4, `survival`, `threads`, `trade` ×2, `lore.interceptors` ×2, `media.art`, `media.providers.shipped` ×2), all but the constant `interceptors._engine_terms` also registered for reset (T6 added `inventory` ×3, `epilogue` and `interceptors._compile_terms` to `LRU_CACHES`) | without warming, two first readers can each build one (harmless: the answers are equal) and a second reader can see a container another thread is still filling (not harmless). Warming before serving removes both, and nothing resets them while serving. `lru_cache` is internally locked, and its results are the parsed story, which callers treat as read-only |
| **Log-once flags** | `prompts._WARNED_SLUGS`, `encounter._WARNED_DEATH`, `jobs._WARNED_ARREST`, `law._WARNED_ENCOUNTERS`, `director._WARNED_FORCED`, `storage._WARNED_ALIAS`, `config._SANDBOX_WARNED`, `client._patch_ignored_warned`, `mechanics._mcp_refusal_logged`; `client._inline_think_seen` (a diagnostic counter only the doctor reads) | a race costs a duplicate log line, or one lost increment of a diagnostic count |
| **Registration tables, filled at import** | `governance._REGISTRY`, `effects._KINDS`, `challenges.runner._PRESENTERS`, `prompts._SUMMARISERS`, `quests._PREDICATES` (filled by the grammar imports, now under the grammar lock), `engine.game._LAZY`, `engine.world._LAZY`, `engine.state._EXPORTS`, `migrations.ENGINE_MIGRATIONS`/`STORY_MIGRATIONS`, `skills.registry.SKILL_REGISTRY` (filled by `@skill`), `locks.RENEWED_AFTER_FORK` | written while modules import, which Python serialises per module, and read after |
| **Constants** | the literal tables the scan also catches (`_ESCAPES`, `_INTENT_BRIEFS`, `_DEGREE_WORDS`, `_MODE_RUNGS`, `_DEFAULT_PORTS`, `PROVIDERS`, the frozen `endings._CLOSENESS`, the class-level `EvilPhaseTone._TONE`, and the like; `__all__` is not a scan site) | never written |
| **Shared by design** | `SessionStore` (every entry gains `owner`, every lookup checks it, §6.4); `SaveStore`, **per (owner, story)** (§4.4); the LLM backend and gate (one model server, v0.19.0's non-goal; the gate becomes the queue, §5.3); the image and TTS workers and their threads (jobs are queued; outputs are content-addressed files, a shared cache, §6.8); the lore manager (one story's FTS index, read-mostly, already locked for writes); `dice._UNSEEDED` (`engine/game/dice.py:22`, a scan site since T6 fix round 1: a `random.Random` whose methods are atomic under the GIL, reached only by a caller that passed no world stream, which is not replayable by definition); the active game and config overlay (one story per process, a non-goal; `config._overlay` is swapped under the config lock); `default_scene._scene` (the one app, built before serving) | one of each is the point |
| **Not served in hosted mode** | `mechanics._ENGINES` and `skills_server._server`/`_backed_up` and the MCP server thread (MCP is refused, §6.7); the studio; `validation._RUN_DOCS`'s callers; the stack manager's services (`launcher.py --stack` only; gunicorn never runs it) | refused at startup, or not mounted |

The world's background tick is not a thread: it runs inside a turn
(`default_state._background_tick`), under that session's lock.

### 5.3 The shared model server: FIFO lanes, admission and a longer wait

**Decision.** Three changes, all effective only when `hosting.enabled`. The
gate reads that key from config; `engine/llm/gate.py` never imports
`engine.hosting`. Under the supervisor (§14) the FIFO lanes below are held
by the supervisor for every worker at once, through a lane backend the
worker's `install()` plugs into the gate (§14.4); the admission, held-lane
and wait rules below are unchanged, and a standalone worker (the tests,
and T7–T9 before the supervisor exists) keeps the in-process lanes.

1. **FIFO lanes.** `gate._semaphore` builds a `FifoSemaphore`: a
   `Condition` over a deque of tickets, so waiters are served in arrival
   order. The limits are unchanged and still come from `llm.lanes`.
   `threading.BoundedSemaphore` lets a new arrival take a freed slot ahead
   of a thread that has been waiting, and under steady load one player can
   wait out a timeout while others keep getting in. Local mode keeps
   `BoundedSemaphore`. It is one player, and the golden holds its
   behaviour.
2. **Admission before the turn touches anything** (survey item 13). In
   hosted mode `run_guarded` takes a **narration ticket** before it calls
   `run_turn`: `gate.turn_admission(timeout)` waits in the narration lane's
   FIFO and, once admitted, records the held lane in a `ContextVar`. Every
   `inference_slot(lane="narration")` inside that turn (the storyteller's
   call, its `:retry` and `:room` calls, the stream) sees the held lane and
   runs without acquiring again, so an admitted turn can never time out in
   narration. If admission times out, `InferenceBusy` is raised **before
   any mechanic runs**, and `run_guarded` catches it and returns
   `(None, "The storyteller is busy with other players. Try again in a
   moment.", True)`: the `busy` shape the client already handles (the
   socket's `turn_error` with `busy: true`, HTTP 409), so the client keeps
   its state and needs no change. The state, the save on disk and the
   transcript are untouched, which a test asserts. The storyteller's
   `except Exception` that turns a failure into `fallback_narration()`
   stays as it is: in hosted mode an admitted turn cannot reach it through
   the gate, and in local mode it is v0.19.0's behaviour.

   **Utility-lane busy, decided.** The planner, the summarizer, the
   Assistant (the voice route's reply included) and quest evaluation use the
   `utility` lane, mid-turn, after the turn's mechanics have run. A busy
   there degrades exactly as a utility-call failure does today (no plan, no
   summary, the Assistant's fallback line), and the turn keeps its
   narration and commits. That is right: the player's action happened, and
   the part that failed is optional by design. A test drives each utility
   caller with `InferenceBusy` and asserts the turn completes and none of
   them raises out of `run_turn`. The utility lane is FIFO too.
3. **A longer wait.** In hosted mode admission's timeout, and the narration
   lane's, read `hosting.queue_wait_seconds` (default 600) instead of
   `DEFAULT_WAIT_SECONDS` (180). Every other lane reads
   `hosting.utility_wait_seconds` (default 5; T9 fix round 1): an admitted
   turn holds its narration place until it ends, so a utility call waiting
   minutes would hold every other turn behind someone's companion.

   Why 600: a 180-second wait assumed one player's turn ahead of you. With
   five players queued behind one narration slot on a reasoning model, the
   last is five turns deep.

**Sizing is the operator's.** `docs/HOSTING.md` § Model server tells them
to set `llm.lanes.narration` to the number of requests their server
actually runs in parallel:
- LM Studio: its parallel-requests setting;
- vLLM: batches natively, so 4 is a sane start on a 12 GB card;
- llama-server: `--parallel`;
- Ollama: `OLLAMA_NUM_PARALLEL`.

The lanes then carry that, and the rest queue in order.

**Why no queue position for the player.** The client has nowhere to show
it until v0.21.0's UI work. The gate can report it
(`FifoSemaphore.position(ticket)`), and the socket emits nothing new in
v0.20.0. That is a **NOT WIRED** row naming `engine/llm/gate.py`.

### 5.4 One live session per player

**Decision.** In hosted mode each account has **at most one live session**.
`create` and `resume` first release that account's other live session,
through `SessionStore.delete`, the single teardown door. If that session's
turn lock is held, the new request is refused with 409, "A turn is still
running in your other window". This is what closes finding 7: a resume of
the same save deletes the live session and rebuilds one **under the same
id** (the id is in the save), which is fine, because the refusal above
means no turn is in flight on the old engine to autosave over it.

**The old tab.** Releasing a session calls the scene's release hook, which
hosted mode sets to `socketio.close_room(session_id)`, **before** the new
socket joins. So the old tab leaves room `S` and goes quiet, instead of
receiving the new session's stream. Telling that tab "this run is open in
another window" needs a client event the UI does not have: a **NOT WIRED**
row (`engine/scenes/default_scene.py`), for v0.21.0.

**The idle sweep, reused.** A disconnected player's session is released by
the existing sweep (`SessionStore.sweep_idle`, `session.idle_sweep_enabled`,
`session.idle_ttl_minutes`, `config/default.yaml:551`–`:552`). Hosted mode
does not add a second key: `sweep_idle` treats `hosting.enabled` as
`idle_sweep_enabled: true`, and `config/docker.yaml` sets
`session.idle_ttl_minutes: 30`. The sweep runs only inside `_build` today,
so a quiet server would never sweep. Hosted mode also sweeps on a socket
`disconnect` (a handler `install()` registers through the socket wrapper,
§6.3, so local mode's handler list is unchanged) and on `require`, at most
once a minute. The sweep never evicts a session whose turn lock is held
(`store.py:365`). The run is on disk, autosaved every turn, and the
client's reconnect `resume` rebuilds it.

This bounds memory at one engine per account per story, and each player to
one turn in flight, which is what makes the FIFO lanes fair. The rule is
per worker; across stories the supervisor's queue grants an account at most
one narration ticket at a time, whichever worker asks (§14.4), so a player
with two stories open in two browsers still has one turn in flight.

---

## §6 — Hosted mode: accounts, ownership, and the surface

### 6.1 Local accounts, created by the operator

**Decision.** Accounts live in `<storage.root>/hosting/users.json`. Each row:

```json
{"id": "u_3f9a1c2b7d4e", "name": "alice", "hash": "scrypt:...",
 "created": 1790000000.0, "epoch": 1, "disabled": false,
 "admin": false, "must_change": false}
```

`admin` and `must_change` are §14.6's (the admin role, and a password an
admin reset that its owner must replace at next login). They land with the
admin task; a row without them reads as `false`, so `users.json` needs no
migration.

- `id` is minted once (`u_` + 12 hex digits) and is the only thing used in
  a path (`<root>/users/<id>/...`). Renaming an account moves nothing, and
  a username never becomes a path component.
- `name` must match `^[a-z0-9_-]{2,32}$`.
- `hash` is `werkzeug.security.generate_password_hash`: scrypt, salted,
  checked in constant time by `check_password_hash`. Werkzeug is already a
  Flask dependency, so this adds no new package.
- Passwords are at least 10 characters. No other composition rules.
- `epoch` is bumped by a password change, a disable, a password reset and
  a change of role (§14.6), and a cookie carrying an older epoch is dead
  (§6.2).

**One writer.** `engine/hosting/accounts.py` is the only code that writes
`users.json`, and all three of its callers go through it: `scripts/users.py`,
`POST /account`, and the admin panel's Users page (§14.8). Every write is a read-modify-write inside an
**inter-process lock**: an operating-system lock (`fcntl.flock`,
`msvcrt.locking`) on a lock file beside `users.json` that stays in place,
then `engine/persistence/atomic.write_json_atomic` with no backup. (T7
fix round 1: the first design, a lock file created with `O_CREAT | O_EXCL`
and broken after 30 seconds, could not release only its own lock or break a
stale one without a race, since no call removes a path only if it is still
the file one saw; the system frees its lock when the holder dies.) So a CLI `passwd` racing a
browser password change cannot lose either update. **`storage.root` must be
on a local file system**: `flock` and Windows byte-range locks are
unreliable on NFS and SMB (Linux emulates `flock` on NFS with per-process
POSIX locks, so two threads of one server would not exclude each other).
The server caches the parsed file keyed on `(st_ino, st_mtime_ns,
st_ctime_ns, st_size)` and re-reads when any moves; its own writes drop the
cache directly, so they never wait on a coarse mtime.

`scripts/users.py` (new): `add <name>`, `passwd <name>`, `disable <name>`,
`enable <name>`, `list`, `remove <name> [--purge]` (`--purge` also deletes
that user's saves directory, and asks to confirm on the terminal), and
`adopt <name> [--game <slug>]` (§4.2); the admin task adds `add <name>
--admin` and `admin <name> on|off`, which is how the first admin is made
(§14.6). A password is read with `getpass`, twice, and never from argv, the
environment or a file. The script works on a live instance, and each of its
changes is written to the audit log as the actor `cli` (§14.11).

**Why local accounts.** Among the auth shapes that are safe for a small
self-hosted group:

- **A reverse-proxy header** (`X-Remote-User`) is safe only if nothing can
  reach the app except through the proxy. One misconfigured port and
  anyone can type the header. It is also a second kind of config to get
  right.
- **Token links** are passwords sent in URLs, which end up in browser
  history and logs.
- **OAuth** needs a registered app, and a third party in a local-first
  tool.

A password file the operator controls needs no service, no network and no
new dependency, and it fails closed.

### 6.2 The login session: Flask's signed cookie

**Decision.** Hosted mode sets these on the Flask app:

- `SECRET_KEY`: `hosting.secret_key`, which is `${env:CLOCKWORK_SECRET_KEY}`
  by default. When that is empty, a 32-byte key is generated once into
  `<storage.root>/hosting/secret_key`, created with `O_CREAT | O_EXCL`
  (mode 0600 on POSIX), so two processes sharing the root cannot each
  write a different one: the loser reads the winner's. Under the
  supervisor the key is made once, before any child starts (§14.3), and
  the front door and every worker read the same file, so one cookie is
  valid at every door of the instance.
- `SESSION_COOKIE_NAME = "clockwork_session"`, `HttpOnly`, `SameSite=Lax`,
  and `Secure` per `hosting.cookie_secure` (default **true**).
- `PERMANENT_SESSION_LIFETIME` from `hosting.session_days` (14). Flask
  applies it only to a permanent session, so login sets
  `session.permanent = True`.

The cookie carries `{uid, epoch}` and, before login, the login form's CSRF
token. Under the supervisor it also carries the front door's two choices,
`story` (§14.5) and `admin_at` (§14.7), and nothing else. Login calls
`session.clear()` before it writes the account in. Every request and every
socket event re-reads the account (through the cache above). A missing,
disabled or older-epoch account is logged out.

**One writer of the cookie, under the supervisor.** The front door and
every worker read the same cookie, but only the front door writes it:

- a worker with a bus uses a session interface whose `save_session` does
  nothing, so it never sends `Set-Cookie`;
- the front door strips any `Set-Cookie` for `clockwork_session` from a
  proxied response;
- the front door sets `SESSION_REFRESH_EACH_REQUEST = False`, so it writes
  the cookie only on a response whose request changed the session (login,
  `/account`, `POST /stories/<slug>`, `/admin/reauth`). A proxied request
  changes nothing, so it re-issues nothing.

Otherwise a response already in flight carries the cookie as it was when
that request began, and overwrites a change made meanwhile: a story switch
set back, a password change's new epoch replaced by the old one (logging
the player out of the very window §6.2 promises to keep), a re-auth lost.
The price is that the cookie's lifetime runs from the last change, not the
last request: a player logs in again `session_days` after their last login,
story switch or password change.

**A password change keeps its own window.** `POST /account` requires the
current password as well as the new one twice. It bumps the epoch, which
logs out every other browser and socket, and re-issues **this** browser's
cookie with the new epoch, so the player is not logged out of the window
they changed it in.

**Plain HTTP is decided before CSRF.** When a login attempt arrives over
plain HTTP while `cookie_secure` is true, the browser has already dropped
the pre-login cookie that carries the CSRF token. So `POST /login` checks
the scheme **first** and answers with a page naming the key
(`hosting.cookie_secure`), instead of a CSRF refusal or a cookie the
browser will drop and a silent loop. That case is the operator trying it on
a LAN without TLS. The doctor WARNs about it too.

**Why Flask's session.** It is already there, signed with `itsdangerous`,
and Flask-SocketIO exposes the same `flask.session` to socket handlers. So
one mechanism covers both doors.

### 6.3 The gate: one hook for HTTP, one wrapper for Socket.IO

**Decision.** `engine/hosting/` (new package) provides `install(scene)`.
`FlaskScene.__init__` reads `hosting.enabled` from config and, **only when
it is true**, imports `engine.hosting` inside that branch and calls
`install(self)` right after constructing `SocketIO` and **before**
`blueprints()` and `register()`. So local mode never imports the package
(§1's subprocess test), and everything `register()` and the blueprints add
is added after the gate exists. `install` does the following.

**It warms the process** (§5.2) before anything else, so the app it returns
has no cold cache left.

**It registers `before_request`, for every HTTP route.** These routes are
open:

- `GET /api/health`;
- `GET /login` and `POST /login`, `POST /logout`;
- `/static/*`. The built client and the shipped UI assets are the same for
  everyone and are public in the repo anyway.

Everything else needs a logged-in account, including, on purpose,
`/story-art/<path>`, `/api/art`, `/api/media/<path>` and
`/api/audio/<path>` (§6.8). `GET /` without one redirects to `/login`, and
any other route answers 401 JSON `{"error": "login required"}`. The hook
also sets the owner (§6.4) for the request, and a `teardown_request` resets
it. A request carrying `X-Forwarded-For` while `hosting.trusted_proxies` is
0 logs one WARNING per process: behind a proxy every client then shares the
proxy's address, and one attacker exhausts everyone's login bucket (§6.5).
The doctor cannot see requests, so the log line and `docs/HOSTING.md` are
where this is said.

**It checks the Origin on state-changing requests.** A `POST`, `PUT`,
`PATCH` or `DELETE` whose `Origin` (else `Referer`) is present and is
neither the request's own host nor `hosting.public_origin` is refused with
403. The server-rendered forms also carry a CSRF token, because a form post
is what SameSite does not fully cover (login CSRF). The login form's token
is per-session, in the cookie (there is no account yet). Every form a
logged-in account posts (account, logout, and under the supervisor the
picker and the admin panel's) carries a **stateless** token instead: an
HMAC of `uid|epoch` under the cookie key, checked with
`hmac.compare_digest`. It needs no write to the session, so a worker can
render the logout form without writing the cookie (§6.2's one writer), and
a password change (the epoch) retires every old token at once.

**Socket.IO has its own door, and gets its own single enforcement point.**
`before_request` never runs for Socket.IO: `/socket.io/` is served by the
engineio WSGI middleware in front of Flask, and events are dispatched by
python-socketio. So:

- **Every socket handler is registered through one wrapper,
  `FlaskScene.on(event)`.** `default_scene.py`'s `connect`,
  `join_session`, `player_choice` and `resume` all move from
  `@socketio.on(...)` to `@self.on(...)`. In local mode `self.on(event)`
  **is** `self.socketio.on(event)`, a pass-through, so the registered
  handlers and the golden's handler list are unchanged. In hosted mode
  `install()` sets the scene's socket guard, and `self.on` wraps each
  handler in it. The guard, before the body runs:
  - on `connect`, refuses (returns `False`) without a live account;
  - on every other event, re-reads the account and, if it is missing,
    disabled or on an older epoch, emits `error` `{"message": "login
    required"}` and disconnects;
  - sets the owner `ContextVar` (§6.4) for the body and resets it in a
    `finally`;
  - applies the action limit and the input caps (§6.5) to the action
    events (`player_choice`, `resume`);

  and records the event name in `scene.guarded_events`.
- **A revoked login leaves at once** (T8 fix round 1). A socket that sends
  nothing still receives its run's stream through the room, so "on its
  next event" is not enough: the guard records each admitted socket's
  account and epoch; `AccountStore.on_revoke` (a password change, a
  disable, a removal in this process) disconnects every socket of that
  account whose epoch is no longer live; and before every emit to a run's
  room each member is re-checked against `users.json` (`check_room`),
  catching a change another process made. **Residual (T8 fix round 2):**
  the check and the emit are not atomic, so a change from another process
  landing between them lets exactly one delta through before the next
  emit's check drops the socket. Closing it would mean emitting to the
  checked sids rather than the room; judged not worth it.
- **A test enumerates every registered socket event**, in every namespace
  of `socketio.server.handlers`, and asserts each is in
  `scene.guarded_events`. It is canary-checked with a raw `@socketio.on`
  handler, which must fail it. A handler a story or a later release adds
  with a raw decorator is therefore caught by the suite, not by a review.
- **`join_session` checks before it joins, in every mode.** It calls
  `require` (with the owner, in hosted mode) first, and `join_room` only on
  success. A socket can no longer sit in the room of a session it cannot
  see, or of one that does not exist yet.
- **CORS is chosen at construction, from config, without importing the
  hosting package** (`FlaskScene.__init__`, before `install`): local mode
  keeps `cors_allowed_origins="*"`; hosted mode passes `[public_origin]`
  when `hosting.public_origin` is set, and otherwise `None`, which is
  python-engineio's **same-origin only**. (`[]` would **disable** the check;
  a test pins that the hosted value is never `[]` and that a cross-origin
  handshake is refused.) Hosted mode also sets
  `max_http_buffer_size` to 64 KiB (§6.5). engineio's origin check is the
  only gate on `/socket.io/`'s HTTP transport requests themselves; the
  guarded `connect` is the gate on the session.

**It adds three server-rendered pages:** `GET /login`, `POST /login`, and
`GET`/`POST /account` (change your own password, §6.2), plus `POST
/logout`. They live under `engine/hosting/templates/`, on a blueprint with
its own template folder: plain HTML with inline CSS in the flagship's
colours and no JavaScript. Under the supervisor the **front door** mounts
this blueprint and a worker does not (§14.5): a player logs in once, at the
front door, and the worker's gate below still checks the same cookie on
every request and event (defence in depth; a worker also treats an account
with `must_change` set as logged out, §14.6).

**It adds a logout link to the page.** `clockwork.html` gains one inline
Jinja block, `{% if hosting %}…{% endif %}`, a small fixed corner link to
`/account` and a logout form, whose token is the stateless one above and is
checked by whichever process owns `POST /logout` (the front door, under the
supervisor). It sits **inline on an existing line**, with
no newline or indentation of its own, and `index()` renders
`render_template("clockwork.html", scene=..., **self.template_extras)`,
where `template_extras` is `{}` unless `install()` sets `{"hosting": ...}`.
So in local mode the call and `GET /`'s bytes are unchanged, which the
golden asserts.

**Why a hook and a wrapper and not a list.** Every HTTP route the engine
and a story's blueprint mount is covered by one `before_request`, including
routes added later, and every socket event by one wrapper. A decorator per
route would be a list someone forgets to extend. Two tests (§9.3) enumerate
the URL map and the socket handler table and assert that everything outside
the open list is refused without a login.

### 6.4 Ownership: every door that names a session or a save

**Decision.** A session is owned by the account that created or resumed
it. `SessionStore.require(session_id, owner=...)` treats a session owned by
someone else as **missing**, raising the same `KeyError` and so the same
404 or `session not found`, so another player's session ids cannot even be
probed for existence. The doors:

| Door | Local (unchanged) | Hosted |
|---|---|---|
| `POST /api/game/new` | creates, owner `""` | creates, owner = the account |
| `GET /api/game/state`, `POST /api/game/choice` | any session id | own sessions only |
| socket `join_session` | `require`, then `join_room` (§6.3) | own only; the room joined only after the check |
| socket `player_choice` | any session id | own only |
| socket `resume`, `POST /api/saves/<id>/load` | the active story's store | the account's store (§4.1); another account's id is simply not there |
| `GET`/`POST /api/saves`, `DELETE /api/saves/<id>` | the active story's store | the account's store |
| `POST /api/voice/transcribe` | any session id | own only |
| the story blueprint's nine routes (`engine/scenes/default_api.py:863`–`:960`) | any | own only, through the same `require`. Five use `_optional_session` (`:857`), which answers story-wide data when the session is not found; for another account's id that is the same story-wide answer, which reveals nothing of their run, and is accepted |

The owner comes from `flask.session`, never from the request body. It
lives in a request-scoped `ContextVar`, `engine/session/store.py::current_owner`,
in the session package so that the store can read it in both modes without
importing `engine.hosting`. It is set by the HTTP `before_request` and by the
socket guard, and reset by `teardown_request` and the guard's `finally`.
`SessionStore.require`, `create`, `resume` and the save routes read it when
no `owner` is passed. So a story blueprint that calls
`store.require(session_id)`, as `default_api.py` does, is covered without
being edited, and so is one written later. With hosting off the variable is
never set, and `require` does not check, which the golden holds. In hosted
mode (the store reads `hosting.enabled` from config) an unset variable is
refused (`KeyError`), so a code path that escaped both gates fails closed.

### 6.5 Rate limits and input caps

**Decision.** In-process token buckets (one process, §5.1), in
`engine/hosting/limits.py`:

- **`actions`**, per account, `hosting.rate_limits.actions_per_minute`
  (default 12): new game, choice, resume, save write, transcribe, over HTTP
  and over the socket alike. Over it: HTTP 429, or the socket's
  `turn_error` with `busy: false` and a "slow down" message.
- **`logins`**, `hosting.rate_limits.logins_per_minute` (default 5), in two
  buckets: per `(address, username)` and per address. Not per username
  alone, which would let anyone lock a known friend out by typing their
  name. Over either: 429 on the login page, and a failure logged with the
  username and address, never the password.
- **Login work is bounded** (T7 fix round 1). An IPv6 address counts by its
  /64 (a client owns the whole prefix), an IPv4 one by itself; the
  `(address, username)` bucket holds half the per-address count, so one
  address can try one name less often than it can try names; an attempt
  from an address with a FAILED login in the last minute also spends from
  one bucket for the whole server (`rate_limits.logins_per_minute_all`, 60;
  T7 fix round 2, reasoning at §6.9), while a clean address is exempt; and at most
  `hosting.max_concurrent_logins` (4) password hashes run at once, each
  about 32 MiB and 100 ms of scrypt. An attempt that finds every slot taken
  waits up to two seconds, then gets the same 429 as any other limit.
- **Login failures are indistinguishable.** A wrong name and a wrong
  password get the same status, the same text ("That name and password do
  not match") and the same work: for an unknown name, `check_password_hash`
  runs against a fixed dummy scrypt hash, so timing does not enumerate
  accounts.
- **Input caps** (survey item 14): `custom_text` longer than
  `hosting.max_input_chars` (default 1000) and a `player_name` longer than
  40 characters are **refused**, not truncated (a cut sentence is an action
  the player did not choose): HTTP 400, or the socket's `turn_error` with
  `busy: false`, "That is longer than this server accepts (1000
  characters)". It is a length in characters, with no content semantics
  (rule 12). `SocketIO(max_http_buffer_size=65536)` bounds a socket
  message, whatever the event.
- **Upload size:** `MAX_CONTENT_LENGTH` = `hosting.max_upload_mb` (16), for
  the voice upload.

Disk quotas are **NOT WIRED**. The actions bucket bounds how fast a player
can mint runs, and each store's index is already bounded
(`saves.index_max_entries`).

### 6.6 Errors a player sees

**Decision.** In hosted mode `run_guarded`'s failure text is generic, "The
turn could not be completed (ref `<8 hex>`)", and the same reference is
logged with the full exception (finding 9). Every other door that returns
exception text does the same:

- `resume_failed`, except a save's `MigrationError`, whose message is about
  the save's version and is kept, because it tells a player why their run
  will not load; a missing or malformed id gets the missing-save wording
  (§4.3);
- the save routes (`engine/api/saves.py:85`);
- `POST /api/settings` (refused in hosted mode anyway, §6.7);
- `POST /api/voice/transcribe`: the STT result's `raw` is dropped and its
  `message` becomes "Transcription failed (ref `<8 hex>`)"; a failed
  Assistant reply there gets the same treatment.

Local mode keeps its text byte-identical, which the golden pins (it records
the voice error body, §1).

### 6.7 What hosted mode switches off, and how loudly

| Feature | Hosted behaviour | Why |
|---|---|---|
| Settings panel `POST /api/settings` | 403: "Set by the server's operator." `GET` still answers, with `writable: false` added | it rewrites `config/local.yaml` and resets every content cache under other players' live turns (finding 8); its keys describe the machine. The operator edits the model settings in the admin panel, which applies them by a drained restart rather than a reset under live turns (§14.9) |
| Studio (`CLOCKWORK_STUDIO=1`) | startup **refused**, with the reason | it writes to `games/`, and resets caches |
| `llm.mcp.enabled: true` | startup **refused**, with the reason | the skills server opens its own port with per-session bearer tokens and edits LM Studio's `mcp.json` on the host; neither was designed for more than one player |
| `/api/metrics` | 404, always (the `hosting.expose_metrics` key an earlier draft had is gone) | process-wide numbers about everyone's turns; admins read each story's Oracle numbers in the panel's Metrics page (§14.10), behind the admin checks, so there is no second way to publish them |
| `launcher.py --stack` | unchanged; gunicorn never runs it | a service the operator manages is theirs |

"Refused" means `install()` raises `HostingConfigError` naming the key.
gunicorn's worker then fails to boot, and `launcher.py` prints it and exits
1. It does not start with the feature silently off, because an operator who
turned something on meant it, and the config and the running instance
should never disagree.

### 6.8 Media is a shared cache

Generated stills and synthesized audio are named by a hash of their
request (`providers/base.py:119`, `tts.py:59`), so identical requests share
a file. In hosted mode they stay shared, and the media and art routes
require a login (§6.3). `docs/HOSTING.md` says in one sentence that any
player can fetch a generated file whose key they know, and that the
operator can read every save and transcript on disk (it is their server),
and that the admin panel deliberately shows none of it (§14.10). Per-user
media namespaces are **NOT WIRED**.

### 6.9 The `hosting:` block

```yaml
hosting:
  enabled: false                 # the whole mode; false = local single-player, unchanged
  public_origin: ""              # e.g. "https://play.example.org"; "" = same-origin only
  trusted_proxies: 0             # reverse proxies in front (ProxyFix); 0 = none
  cookie_secure: true            # false only for a plain-HTTP LAN trial
  session_days: 14
  secret_key: "${env:CLOCKWORK_SECRET_KEY}"   # empty = generated into <storage.root>/hosting/
  queue_wait_seconds: 600
  utility_wait_seconds: 5        # T9 fix round 1: a utility call's wait (in a turn, or a voice reply); then it is skipped
  turn_deadline_seconds: 900     # T11 fix round 1: an admitted turn's wall-clock budget, utility calls included; then it ends through the model-failure path
  body_read_seconds: 30          # T12 fix round 1: a turn request's whole body must arrive within this, before it takes a turn slot; then 408
  threads: 32                    # each process's gthread pool (front door and every worker); see below
  max_connections_per_account: 4  # T13 fix round 1: one account's open game connections (WebSockets, long polls) at the front door and at each worker; past it refused
  max_upload_mb: 16
  max_input_chars: 1000          # every text a player sends, in characters (T9 fix round 1: every field)
  max_saves_per_story: 50        # T9 fix round 1: runs and saves an account keeps per story
  max_concurrent_logins: 4       # T7 fix round 1: scrypt hashes at once (§6.5)
  rate_limits:
    actions_per_minute: 12
    logins_per_minute: 5
    logins_per_minute_all: 60      # T7 fix rounds 1-2: addresses with a recent failed login, together (§6.5)
    admin_actions_per_minute: 30   # §14.7 (T14)
  stories: ["clockwork-dark"]    # §14.3 (T10): one worker process per slug, under the supervisor
  supervisor:                    # §14.3 (T10; max_hold_seconds T11)
    health_interval_seconds: 10
    health_failures: 3           # consecutive failed bus health checks before a restart
    boot_seconds: 120            # from spawn to `ready`; a child slower than this is restarted
    hello_seconds: 2             # T10 fix round 2: a new bus connection's time to say hello (§14.2)
    max_restarts: 5              # crashes within restart_window_minutes; then the story is held down
    restart_window_minutes: 10
    drain_seconds: 120           # how long a stop, restart or model apply waits for turns in flight
    stop_seconds: 30             # how long a child gets to exit after a drain before it is killed
    shutdown_seconds: 180        # the whole shutdown, drain included; below the container's stop grace
    max_hold_seconds: 1200       # a lane ticket held longer than this is reclaimed (T11 fix round 1: its worker restarted only if it does not answer)
  admin:                         # §14.7 (T14)
    reauth_minutes: 15           # the panel asks for the admin's password again after this
  observability:                 # §14.3 (T10) logs, §14.10 (T17) metrics
    log_max_mb: 20               # per process log file, then rotated
    log_keep: 5
    retention_days: 30           # metrics rows older than this are pruned
    metrics_max_mb: 512          # T17 fix round 1: the metrics file's cap; past it the oldest rows go first
    audit_max_mb: 20             # §14.11 (T14 fix round 1): the audit log, then rotated
    audit_keep: 10               # rotated audit files kept
```

Each key lands with the task that first reads it (the comments name the
task), and `tests/test_hosting_config.py` is extended in the same task, so
no key sits in the schema that nothing reads. `expose_metrics`, in an
earlier draft of this block, is gone (§6.7).

The supervisor's durations are checked against each other at startup,
naming the key: `max_hold_seconds` at least `turn_deadline_seconds + 120`
(T11 fix round 1. The first rule, `3 × llm.timeout_seconds + 60`, rested
on a false premise: `llm.timeout_seconds` is httpx's per-phase timeout, not
a call's total, so a stream that keeps sending tokens is unbounded by it,
and the narration ticket also covers the turn's utility calls. Each worker
now ends every admitted turn by `turn_deadline_seconds`, measured on the
wall clock from admission, with no model call started after it and the one
in flight cut, through the model-failure path (T12, T11's N2: by a timer at
the deadline that shuts the call's socket, so a stream gone silent cannot
overshoot it by up to `llm.timeout_seconds`); `max_hold_seconds` is the
supervisor's backstop for a hung turn, a reclaim, §14.4), and `shutdown_seconds` at
least `drain_seconds + stop_seconds + 7` (T10 fix round 1, amended here in
T11: a stop ends with 5 s after `terminate()` and 2 s for the kill, and the
shutdown holds both; `engine/hosting/config.py`'s
`TERMINATE_GRACE_SECONDS` and `KILL_WAIT_SECONDS`), **amended in T18 fix
round 1** to `drain_seconds + stop_seconds + 17`: the front door is stopped
after every worker, in its own 10 s (`FRONTDOOR_STOP_RESERVE_SECONDS`), so a
drained turn reaches its player (§14.3). `drain_seconds` is 120 rather than a
minute because a streamed turn on a reasoning model regularly runs past
60 s, and a drain shorter than a turn refuses every stop made during play.

There is no hosted idle key: hosted mode reuses `session.idle_ttl_minutes`
and forces the sweep on (§5.4). There are no port keys for workers: each
binds a loopback port the OS picks and reports it to the supervisor
(§14.3), and the front door binds `scene.clockwork.host`/`port`.

**`threads` has a ceiling to respect.** Under gthread each open WebSocket
pins a pool thread for as long as it is open, so `threads` must exceed
(players × open tabs) plus the HTTP requests in flight at once, or the
next connection waits for a thread. Under the supervisor a WebSocket pins a
thread in the front door (the relay, §14.5) **and** one in its story's
worker, so the front door's pool is the one that runs out first: it
carries every story's sockets. (The relay's own reader threads run outside
the pool and do not count against it.) The doctor shows the arithmetic
(§7.4), and `docs/HOSTING.md` says it with an example.

**The login keys** (T7 fix rounds 1-2). `max_concurrent_logins` bounds the
scrypt work (CPU and memory) whatever the addresses: four hashes at once, so
about 40 checks a second and 128 MiB at most. `logins_per_minute_all` is
spent ONLY by an address (an IPv6 /64) with a failed login in the last
minute; a clean address is exempt from it and bound by its own buckets and
the hashing slots. Counting every attempt let a dozen cheap addresses (one
home IPv6 /56 holds 256 /64s) drain the bucket at about one request a
second and refuse every real login, indefinitely, while buying little that
the hashing slots do not already bound. Guessing produces failures and a
real login mostly does not, so the cap falls on the guessers: they share 60
attempts a minute however many addresses they hold, and the player who
types their password correctly is never refused by it. The price: a real
player who has just mistyped is counted with the guessers for a minute.

**It is a closed schema.** `engine/hosting/config.py` validates it at
startup: unknown keys, wrong types and out-of-range values are refused,
naming the key. A test pins the key set to this block, so adding a key
means changing the test and this spec. That is the mechanical form of rule
12's "no `safety:` block, in any form".

`hosting` and `storage` join `engine/games/manifest.py::SETTING_REFUSALS`.
A story can declare neither.

---

## §7 — The production server

### 7.1 gunicorn, one `gthread` worker

**Decision.** `engine/hosting/wsgi.py` exposes `app`, a story worker. On
import it calls `engine/hosting/boot.py::build_worker_app()` (§14.3, shared
with the development runner), which:

1. reads `CLOCKWORK_GAME`;
2. activates that story (`registry.activate`), before any content import,
   as `launcher.py` does;
3. requires `hosting.enabled`, and refuses to serve local mode under
   gunicorn ("local mode is served by `launcher.py`; gunicorn serves
   hosted mode only"), before it builds anything;
4. requires the supervisor's bus (`CLOCKWORK_BUS_ADDR`, §14.2), and refuses
   without it ("a hosted worker is started by the supervisor:
   `python -m engine.hosting.supervisor`"), so production has one shape,
   and a worker can never serve with lanes of its own beside the shared
   queue;
5. builds `create_app()`, whose `install()` validates the `hosting:` block,
   applies the §6.7 refusals, connects the bus and warms every cache
   (§5.2), so the worker either boots ready or does not boot.

`engine/hosting/frontdoor/wsgi.py` exposes the front door's `app` the same
way (hosting required, the bus required, no story activated: the front door
serves no turns, §14.5). The supervisor starts both under gunicorn on
POSIX (§14.3). Both modules and `deploy/gunicorn.conf.py` land in T13, with
the front door's WebSocket relay, so the relay is proved under gunicorn
before the admin panel is built on the front door (§12); the image (T18)
only packages them.

`deploy/gunicorn.conf.py` (new, used for the front door and every worker)
sets:

- `workers = 1`. The CLI's `-w` and `GUNICORN_CMD_ARGS` both override a
  config file's value (T13 fix round 1: `WEB_CONCURRENCY` is only the
  default the file replaces), so the supervisor strips `GUNICORN_CMD_ARGS`
  and `WEB_CONCURRENCY` from every child's environment, and the file also
  defines an `on_starting(server)` hook that refuses any value but 1 -- and
  any other override of the file: the worker class, `max_requests`, the
  forwarded-header trust and the bind (a worker off loopback) -- with a
  message that points at §5.1;
- `forwarded_allow_ips = ""` and `secure_scheme_headers = {}` (T13 fix
  round 1): gunicorn trusts no forwarded header itself (its default trusts
  loopback peers), so §7.3's one trust decision stays the engine's;
- `worker_class = "gthread"`, with `threads` from `hosting.threads`;
- `bind`: for the front door, `scene.clockwork.host`/`port`; for a worker,
  `127.0.0.1:0`, the port the OS picks, reported to the supervisor from the
  `post_worker_init` hook (§14.3). The role comes from
  `CLOCKWORK_BUS_ROLE`, which the supervisor sets;
- `timeout = 120`, the worker heartbeat, not a request limit, because turns
  stream over the socket. Under gunicorn the bus client lives in the
  gunicorn **worker**, not in the master the supervisor spawned, so a
  worker gunicorn restarts itself (a missed heartbeat, a crash) closes the
  bus connection. The supervisor treats that close as the child down,
  terminates the master and starts it again (§14.3); the respawned
  gunicorn worker's `hello` is refused, because a child's bus token is
  single-use (§14.2);
- `graceful_timeout = 30`;
- `accesslog` off. Logs go to stdout, and the engine's own logger already
  names every operation.

`gunicorn>=23` is a new optional dependency (`pyproject.toml`
`[project.optional-dependencies] server`, and `requirements-server.txt`
for the image). `requirements.txt` is unchanged, so a local install pulls
nothing new.

**Why gunicorn with threads.** The app is Flask plus Flask-SocketIO in
`async_mode="threading"` (`flask_scene.py:58`), and the engine is written
around threads and blocking `httpx` calls: locks, `threading.local`
guards, `ContextVar`s.

- Flask-SocketIO documents gunicorn with a single threaded worker as a
  supported deployment of threading mode, with WebSocket through
  `simple-websocket` (already installed).
- **eventlet** and **gevent** need monkey-patching, which would change how
  every lock and socket in the engine behaves. That is a rewrite with none
  of the evidence the engine has for threads.
- **waitress** does not speak WebSocket.
- **uvicorn** serves ASGI, and this app is WSGI.

### 7.2 Local mode keeps Werkzeug

`launcher.py` still calls `run_scene` with Werkzeug and
`allow_unsafe_werkzeug=True`, byte-identical, and never starts the
supervisor. With hosting on, `launcher.py` still runs, which is how the
owner tries hosted mode on Windows, and prints one WARNING: "hosted mode
under the development server: for a real deployment run `python -m
engine.hosting.supervisor` on Linux, or the Docker image". Until the front
door exists (T12) it runs one hosted worker in-process, as T7–T9 build it;
from T12 on it runs the supervisor in the foreground with development
servers for the front door and each worker (§14.3), so the trial is the
same shape as the deployment.

### 7.3 TLS and the reverse proxy

**Decision.** The engine speaks plain HTTP. `docs/HOSTING.md` gives a
complete Caddy file (automatic TLS, WebSocket proxying without extra
config) and an nginx server block (with the `Upgrade`/`Connection` headers
Socket.IO needs, and `proxy_read_timeout` above a long turn).

With `hosting.trusted_proxies: N`, the app is wrapped in Werkzeug's
`ProxyFix(x_for=N, x_proto=N, x_host=N)`, so the rate limit sees the real
client address and `cookie_secure` sees the real scheme. With `0`, the
default, forwarded headers are ignored, so a client can't claim an address.
Under the supervisor, `N` applies to the **front door**, the only process
the outside reaches. A worker trusts exactly one hop, the front door, and
only on a request carrying the boot's proxy token (§14.5); the front door
**replaces** `X-Forwarded-For`/`-Proto`/`-Host` with what its own
`ProxyFix` resolved, so a client's header never reaches a worker as fact.
This lands with the front door (T12), not with Docker.

**Ignoring a header means deleting it.** engineio's same-origin check reads
the raw `HTTP_X_FORWARDED_PROTO` and `HTTP_X_FORWARDED_HOST` from the
environ itself (`engineio/base_server.py:291`–`:300`), and `ProxyFix` does
not remove them. So:

- a worker's outermost WSGI middleware checks `X-Clockwork-Proxy` against
  the boot's token (`hmac.compare_digest`), removes that header from the
  environ either way, and then either applies `ProxyFix(x_for=1, x_proto=1,
  x_host=1)` (token right) or **deletes** every `HTTP_X_FORWARDED_*` key
  (token absent or wrong) before engineio or Flask sees the request;
- the front door, after its own `ProxyFix` (or at once, with
  `trusted_proxies: 0`), deletes every `HTTP_X_FORWARDED_*` key, and its
  WebSocket door's Origin check uses only the resolved `Host` and scheme,
  never a raw `X-Forwarded-Host`; the headers it sends a worker are its
  own.

**Wrap order matters.** `SocketIO(app)` replaces `app.wsgi_app` with the
engineio middleware, which answers `/socket.io/` itself. `ProxyFix` (and,
on a worker, the token middleware above) must wrap **outside** it
(`app.wsgi_app = ProxyFix(app.wsgi_app, ...)`, applied after `SocketIO` is
constructed), or socket connects see the proxy's address and the limits key
on it. On the front door, which has no engineio, the order is `ProxyFix`,
then the WebSocket door (§14.5), then Flask. A test sends a socket
handshake with `X-Forwarded-For` under `trusted_proxies: 1` and asserts the
guard saw the forwarded address.

### 7.4 The doctor, hosted

With `hosting.enabled`, `check_config` adds these rows:

- accounts: the count, and FAIL at zero ("nobody can log in: `python
  scripts/users.py add <name>`");
- secret key: its source (the environment, or the generated file), never
  the value;
- `cookie_secure`: WARN when false;
- `public_origin` and `trusted_proxies`: shown;
- studio, MCP and settings: FAIL if a startup refusal (§6.7) would fire;
- production server: WARN on Windows ("gunicorn does not run on Windows:
  use Docker, or accept the development server for a trial");
- `llm.lanes`: shown, with the §5.3 sizing hint;
- `hosting.threads`: shown with its ceiling, "about N players with two tabs
  each, leaving 4 threads for HTTP" (§6.9), and WARN below 8;
- storage: in the image, a `/data` that is not writable by uid 10001 is a
  FAIL naming the likely cause, a root-owned host bind mount, and the
  `chown` that fixes it (§8.1).

The admin panel and orchestration (§14) add these, each landing with its
task:

- `hosting.stories`: each slug shown, a FAIL for one the registry does not
  know or that does not validate, and a FAIL for an empty list (T10);
- admins: the count, and WARN at zero ("the admin panel is unreachable:
  `python scripts/users.py admin <name> on`") (T14);
- the admin layer (§14.9): its path, and the dotted keys it sets (keys, not
  values); a WARN per key that `CLOCKWORK_CONFIG` also sets ("the panel's
  edit of `<key>` is overridden by `<file>`"); a FAIL for a key outside the
  panel's allowlist (T14). The doctor reads the layer exactly as the
  instance does, because `get_config` loads it whenever hosting is on
  (§14.9), with no variable only the supervisor sets;
- the metrics store: its path and whether it is writable (T17);
- `hosting.threads`: the arithmetic restated for the front door, which
  carries every story's sockets (§6.9) (T12).

The doctor holds no bus token and does not ask the live supervisor
anything. `launcher.py --check` with hosting on adds one row (T12): the
front door's `GET /api/health` at `scene.clockwork.host`/`port` (up or
not), and the path of `<root>/hosting/logs/`. With hosting off its output
is v0.19.0's (`launcher_report.txt`).

---

## §8 — Docker

### 8.1 The image

**Decision.** A multi-stage `Dockerfile` at the repo root.

The **base** is `python:3.11-slim-bookworm`, pinned by digest, the version
the owner develops on and the one T4's Linux run proved.

The build installs `requirements-server.txt`, which opens with
`-c constraints.txt` (§3.10): the core of `requirements.txt` plus
`gunicorn`, and **without** `faster-whisper` and `fastmcp`. STT in the
container is the Voxtral HTTP provider or off, and MCP is refused in hosted
mode anyway. A build arg `WITH_WHISPER=1` adds `faster-whisper`, CPU only,
and sets `HF_HOME=/data/cache/hf`, so the model it downloads on first use
lands on the volume and not in a layer that is lost with the container. It
then copies:

- `engine/`, `games/`, `content/` (the committed client `dist` included),
  `config/default.yaml`, `config/docker.yaml`, `deploy/`, `constraints.txt`;
- `launcher.py`, and `scripts/users.py`, `scripts/doctor.py`,
  `scripts/seed_lore.py`.

`RUN python scripts/seed_lore.py` then builds every shipped story's lore
index into the image.

**Not copied**, and pinned by `.dockerignore`, with a test (§9.5) that
parses it:

- `.git`, `.venv`, `node_modules`, `ui/`, `tests/`, `Design_files/`,
  `data/`;
- `config/local.yaml`;
- `llm_api_key.txt`, `lmstudio.txt`, `*.key`, `*.token`, `.env*`.

**At run time** the image:
- creates the non-root `clockwork` user (uid 10001), then creates `/data`
  and `chown`s it to that user **before** `VOLUME /data`, so a fresh named
  volume starts writable;
- runs as that user;
- exposes 5573, with a `HEALTHCHECK` against `/api/health`;
- sets `ENV CLOCKWORK_ENV=docker`, `CLOCKWORK_DATA_DIR=/data` and
  `CLOCKWORK_CONFIG=/data/config.yaml`;
- has `ENTRYPOINT ["deploy/entrypoint.sh"]` and `CMD ["python", "-m",
  "engine.hosting.supervisor"]`. The supervisor (§14.3) starts the front
  door on 5573 and one gunicorn worker per `hosting.stories` slug on
  container loopback ports, none of them published; on `SIGTERM` (a
  `docker stop`) it drains turns and stops its children before exiting,
  within `hosting.supervisor.shutdown_seconds` (§14.3).

`deploy/entrypoint.sh` (POSIX `sh`, executable bit set in the index) is
what lets the config file be optional: a bare `CMD` cannot write a file. On
start it creates `/data/config.yaml` empty if it is absent, so the
explicit-path error (§2.1) fires only for a path the operator actually set
wrong, fails with a clear message if `/data` is not writable (a host bind
mount is root-owned unless the operator `chown`s it to 10001, which the
message names, and so do the doctor and `docs/HOSTING.md`), and then
`exec`s its arguments, so the supervisor receives the container's signals
directly and its gunicorn children are its own.

**`config/docker.yaml`** (a checked-in env layer, read only under
`CLOCKWORK_ENV=docker`) sets:

- `scene.clockwork.host: 0.0.0.0`;
- `hosting.enabled: true`;
- `session.idle_ttl_minutes: 30` (§5.4);
- `llm.base_url: "http://host.docker.internal:1234/v1"`;
- every `stack.services.*.manage: false`, and `enabled: false` for every
  service but the model server. Their shipped URLs are `localhost` (TTS on
  5051, ComfyUI on 8188), which inside the container points at nothing; an
  operator who runs one sets its URL and enables it in `/data/config.yaml`.

Everything the operator changes goes in `/data/config.yaml`, with one
exception: each `llm.*` key the admin panel edits (§14.9) is set in **one**
place. A key set in `/data/config.yaml` is locked in the panel (the
operator's file wins, and the panel refuses rather than shadow it), so an
operator who means to use the Model server page leaves those keys out of
their file; `config/docker.yaml`'s `llm.base_url` ranks below the panel's
layer and is simply its starting value. `docs/HOSTING.md` says so where it
first shows `/data/config.yaml`.

**Why hosting is on in the image, and cannot be turned off there.** A
container exists to publish a port. An image that listened on a published
port with no auth by default would be finding 6 as a product. `wsgi.py`
refuses local mode under gunicorn (§7.1), so an operator who sets
`hosting.enabled: false` in their own file gets a worker that refuses to
boot and says why, and the supervisor refuses to start at all for the same
reason. Local single-player is `launcher.py`, outside a container.

**Secrets** reach the container only through the environment
(`CLOCKWORK_LLM_API_KEY`, `CLOCKWORK_SECRET_KEY`) or files on `/data`.
None is baked in.

### 8.2 `docker-compose.yml`: the game, and optionally vLLM

The compose file has two services.

`game` (the default) builds from `.`:
- publishes the front door, and nothing else (workers listen on the
  container's loopback, §14.3), **on the host's loopback**:
  `127.0.0.1:5573:5573` (amended in T18 fix round 1, the owner's
  loopback-by-default decision carried to Docker: a port published on every
  host interface bypasses ufw/firewalld, carries passwords in plain HTTP,
  and lets a client that reaches it around the reverse proxy forge
  `X-Forwarded-For` under `trusted_proxies`). Publishing wider is the
  operator's explicit edit, for a TLS proxy elsewhere or a LAN trial;
- mounts a named volume on `/data`;
- adds `extra_hosts: ["host.docker.internal:host-gateway"]`, which Docker
  Engine on Linux needs to reach a model server on the host (Docker Desktop
  provides the name already);
- sets `init: true`, so a PID 1 init (tini) reaps any gunicorn worker
  orphaned by a crash;
- sets `stop_grace_period` above `hosting.supervisor.shutdown_seconds`
  (`210s` against the default 180): Compose's own default is 10 s before
  `SIGKILL`, which would cut every drain short. A test reads both files
  and asserts the relation (§9.5).

Which stories run is `hosting.stories` in `/data/config.yaml` (default the
flagship alone), not an environment variable: `CLOCKWORK_GAME` is set by
the supervisor for each worker it starts, and the compose file no longer
sets it.

`vllm` sits under compose profile `vllm`:
- image `vllm/vllm-openai`, pinned to the tag §10 verifies;
- GPU reservation `deploy.resources.reservations.devices: [{driver:
  nvidia, count: all, capabilities: [gpu]}]`;
- `ipc: host`;
- a named volume for the Hugging Face cache;
- `HF_TOKEN` passed through, not required for the model chosen;
- the verified `vllm serve` command line.

With `--profile vllm`, the game is pointed at `http://vllm:8000/v1` on the
admin panel's Model server page, or, on an instance run without the panel,
in `/data/config.yaml`, which then locks the key in the panel
(`docs/HOSTING.md` gives both).

**Reaching LM Studio from a container.** LM Studio binds loopback by
default, and the two platforms differ:

- **Docker Desktop (Windows, macOS):** `host.docker.internal` reaches a
  loopback-bound LM Studio without its "serve on local network" option.
  T18 measures it on this workstation, if the owner consents to starting
  Docker, and records the result either way.
- **Docker Engine on Linux:** `host-gateway` is the `docker0` bridge
  address, and a loopback-bound server is not reachable there. Turning on
  "serve on local network" would bind every interface and expose an
  unauthenticated model server to the LAN, so `docs/HOSTING.md` says to
  bind the model server to the `docker0` address (or firewall its port to
  the bridge) instead.

### 8.3 Several stories

One container, one worker process per story (§14). An earlier draft ran
one container per story, each on its own port; the owner's orchestration
scope replaces that. The operator lists the slugs in `hosting.stories`, the
supervisor starts a worker for each, and the front door on 5573 routes each
player to the story they pick. Accounts (`/data/hosting/users.json`) and
the cookie key are shared by construction (one root, one key made before
any child starts): one login works for every story. Saves stay apart by
the `<slug>` directory (§4.1).

---

## §9 — Testing

1. **The local-mode golden** (§1), recorded on e7fdd26 and asserted at
   every task, with exactly §1's two sanctions (`tests/test_local_mode_golden.py`).
   Also `test_local_mode_never_imports_hosting` (building the app and
   playing a turn in a subprocess), and v0.19.0's LM Studio golden and
   doctor/launcher baselines, unchanged.
2. **Survey fixes**, each failing on v0.19.0:
   - save-id containment at all five doors, with every encoding in §4.3
     and a sentinel file that survives each `DELETE`;
   - `join_session` joining no room for a missing session;
   - the runtime paths (saves and media) anchored at the root, run from a
     temp working directory (finding 2);
   - N1–N3 (§2.2): a `?` path read whole, an unknown scope raising at load
     and naming the key, no recursion on a hand-built manager;
   - N4's doctor row (§2.3);
   - `_safe_path` refusing a drive letter and a backslash on every
     platform;
   - item 12's races (`tests/test_thread_safety.py`), each forced with a
     `threading.Barrier` rather than hoped for:
     - two threads completing a collection each, at once: both are paid
       (on v0.19.0 one gets `[]`);
     - the first `_ensure_grammar` call held inside its import loop while
       a second thread evaluates a grammar-module predicate: the second
       waits and sees it registered (on v0.19.0 it reads unmet);
     - two overlapping validator runs leave `_RUN_DOCS` unset afterwards
       (on v0.19.0 the later `finally` installs the earlier run's dict);
     - two first calls to `get_config` return one instance (on v0.19.0,
       two);
     - the Oracle under 16 threads × 500 records keeps exact totals (the
       GIL can hide the lost update on v0.19.0, so this one is a
       regression guard, not a failing-first test; the report says so);
   - `tests/test_module_state_inventory.py` (§5.2), canary-checked by
     adding a module-level `_X: dict = {}` to an engine module.
3. **Hosted isolation**, with two accounts, A and B, split by concern:
   - **the HTTP gate** (`tests/test_hosting_gate.py`): every rule in the
     URL map, story blueprints and the studio's included, times every
     method it accepts (bar `HEAD` and `OPTIONS`), except the open list,
     answers 401 without a login (`GET /` redirects); canary: a route
     added by a test blueprint after `install()` is still refused;
   - **the socket door** (`tests/test_hosting_sockets.py`): every event in
     `socketio.server.handlers`, in every namespace, is in
     `scene.guarded_events`; canary: a raw `@socketio.on` fails it; an
     unauthenticated `connect` is refused; a cross-origin handshake is
     refused and the hosted CORS value is never `[]`; a disabled account's
     open socket is dropped on its next event;
   - **ownership** (`tests/test_hosting_ownership.py`): for every door in
     §6.4, B naming A's session or save id gets the same answer as a
     nonexistent id, and A's files are untouched on disk; `join_session`
     on A's id puts B in no room (B receives none of A's stream);
   - **no cross-talk** (`tests/test_hosting_crosstalk.py`): two players'
     turns run interleaved on two threads (scripted model, fixed seeds),
     and each player's payload sequence equals that player's solo run. The
     same test asserts the `threading.local` guards are clear when a
     thread is reused;
   - **login** (`tests/test_hosting_login.py`): Origin and CSRF refusals;
     the plain-HTTP page decided before CSRF; identical failure for a wrong
     name and a wrong password, with the dummy hash checked; the
     `(address, username)` and per-address buckets; `session.permanent`;
     the epoch invalidating a cookie on HTTP and on an open socket; a
     password change keeping its own window; the two `users.json` writers
     racing through the lock (two processes, one `passwd` each, both
     updates land);
   - **one session, admission and the sweep**
     (`tests/test_hosting_sessions.py`, `tests/test_hosting_admission.py`):
     one live session per account; the 409 while its turn runs; the old
     tab leaving room `S`; the idle sweep releasing a session on
     disconnect and on `require`, and a reconnect resuming it; a turn that
     cannot be admitted leaves the state, the save file and the transcript
     byte-identical and answers `busy: true`; each utility caller degrading
     under `InferenceBusy` with the turn committed;
   - **limits and caps** (`tests/test_hosting_limits.py`): the actions
     bucket on both doors, the input caps (refused, not truncated), the
     socket buffer size, and the upload cap;
   - **the FIFO semaphore** (`tests/test_llm_gate_fifo.py`): 20 threads,
     served in arrival order, no slot lost on a timeout or an exception,
     a held narration lane re-entered without waiting; local mode still
     builds `BoundedSemaphore` (asserted by type).
4. **Secrets and internals never leave** (`tests/test_hosting_secrets.py`).
   With a known `llm.api_key`, `CLOCKWORK_SECRET_KEY` and a password hash in
   place, a logged-in client drives **every rule and method in the URL
   map** and **every registered socket event**, each once normally and once
   under forced failures (the model server down, STT failing with a `raw`
   body that names an internal URL, a malformed and a missing save, a
   migration error). It scans every response body and every emitted
   payload, and asserts that none of the three secrets, the model server's
   URL, the STT server's URL or `raw` body, a Python exception class name,
   or any `users.json` field but the account's own name appears. The same
   crawl runs with `reset_config` and `reset_all_caches` patched to raise
   (§5.2).
5. **Static checks on the deployment files**, run everywhere
   (`tests/test_deploy_files.py`):
   - the Dockerfile's `USER` is not root, `/data` is `chown`ed before
     `VOLUME`, and its installs use `constraints.txt`;
   - `.dockerignore` excludes every secret and runtime path in §8.1;
   - `deploy/gunicorn.conf.py`'s `on_starting` refuses more than one worker
     (called with a fake `server.cfg`), its bind follows the role, and
     `post_worker_init` reports a fake worker's socket port (T13, the
     file's first tests);
   - `docker-compose.yml` sets `init: true` and a `stop_grace_period`
     above `hosting.supervisor.shutdown_seconds` (T18);
   - `deploy/entrypoint.sh` and `scripts/start.sh` are `100755` in the git
     index;
   - `config/docker.yaml` turns hosting on and disables every non-model
     service;
   - `hosting:` is a closed schema, with keys equal to §6.9's
     (`tests/test_hosting_config.py`);
   - the two start scripts' next steps agree (§3.2);
   - `constraints.txt` pins every requirement (`tests/test_constraints.py`,
     §3.10).
6. **Cross-process guards** (§3.5, `tests/test_subprocess_sandbox.py`),
   canary-checked, and the in-process environment left clean.
7. **Portable paths** (§3.4, `tests/test_portable_paths.py`), on every
   platform.
8. **Live:** the suite green in the Linux container (§3.9), and in CI once
   pushed. The front door's WebSocket relay run under gunicorn in the
   Linux container (T13), once the owner consents to the gunicorn wheel.
   The image built and smoke-tested once the owner consents (T18),
   through the front door, with two stories and the admin panel.
   vLLM `tests/test_llm_live.py` with `CLOCKWORK_LIVE_LLM=vllm` (§10).
9. **Reachability:** `tests/test_reachability.py` passes with no new
   allowlist row. `engine/hosting` has a production caller
   (`FlaskScene.__init__`'s hosted branch, `boot.py` and the two `wsgi.py`
   modules, and the supervisor's `__main__`).
10. **The admin panel and orchestration** (§14), each file a task's.

    **Real processes, shared and budgeted.** These tests start real
    supervisors, front doors and workers, and a worker warms its story's
    caches as it boots. The suite already takes over half an hour, so they
    share instances: `tests/hosting_instance.py` (T10, extended in T12) is
    the one helper that starts a supervisor, the front door and N workers
    (probe or `scripted_worker`) with the test's own `CLOCKWORK_CONFIG`
    file (§3.5), hands out logged-in clients, and stops everything in a
    `finally`; a module-scoped fixture built on it serves each test file
    once, and a test that needs a fresh instance (a crash, a held-down
    child) says so. Each of T10–T17 reports the wall time its new tests add
    (`--durations`), against a budget of two minutes per task and ten for
    T10–T17 together; a task over it shares instances more widely before it
    commits, or brings the overrun to the controller.

    - **the bus** (`tests/test_hosting_bus.py`): framing and the 64 KiB
      cap (an oversize inbound frame closes the connection; an oversize
      reply becomes `too_large` and the connection stays up; the reader's
      bounded `readline`); a token refused when wrong, when reused after its
      connection closed, and when a second `hello` names a child already
      connected; the 5 s `hello` deadline; each op refused `forbidden` to a
      role its row does not allow; `story` and `process` stamped from the
      connection whatever the arguments say; `lane.release` of another
      connection's ticket answered `bad_args`; an unknown op refused;
      requests in both directions; the lifeline (a child exits when the
      supervisor's end closes); the tokens gone from a child's `os.environ`
      once read; no token in any log line;
    - **the supervisor** (`tests/test_supervisor.py`): children started,
      in their own process groups, and restarted with backoff after an
      exit or failed bus health checks; a failing HTTP health check marks
      a child `degraded` and restarts nothing; a child not `ready` within
      `boot_seconds` restarted; a crash loop held down after
      `max_restarts`, while restarts an admin or the supervisor chose do
      not count; start, stop and restart answered at once and followed on
      the operations table; a drain bounded by `drain_seconds`; a drained
      shutdown within `shutdown_seconds` that restarts nothing once begun;
      per-process log files rotated at size; the secret key made before any
      child starts; an unknown story refused at startup; under a fake
      gunicorn, a closed bus connection terminating the master and
      starting it again; local mode never spawns it (`launcher.main([])`
      with the stack stubbed spawns no process whose argv names
      `engine.hosting`);
    - **the shared queue** (`tests/test_hosting_queue_remote.py`): two
      worker processes' threads served in global arrival order; a killed
      process's tickets freed; one narration ticket per account across
      workers; a pause while a turn holds narration and then asks for
      utility grants the utility at once; a paused story's head waiter does
      not delay another story's waiter; a drain completes in the turn's own
      time; a grant that lands after its request was abandoned is released
      at once and counted; a release is never queued behind blocked
      acquires; a ticket held past `max_hold_seconds` is reclaimed without
      a restart, and a worker that does not acknowledge is restarted;
      a held lane re-entered in-process with no second bus request; the bus
      down answering `busy` with the state, save and transcript unchanged;
    - **the front door** (`tests/test_frontdoor_routing.py`,
      `tests/test_frontdoor_socketio.py`, `tests/test_hosting_proxyfix.py`):
      one login reaches the chosen story's worker for HTTP, Socket.IO
      polling and WebSocket; a turn streams through the WebSocket relay
      event for event as it does direct; the relay refuses a missing
      cookie, a foreign Origin, no story chosen and a worker's refusal
      before upgrading the client; the front door's own routes are never
      proxied; an unknown `/admin/...` path is answered by the admin guard
      and never proxied; a stopped story answers 503; no proxied response
      carries the session cookie, and a story switch or a password change
      that races a slow worker response survives it; a client's
      `X-Forwarded-For` never reaches a worker as fact, a worker deletes
      forwarded headers without the proxy token (so engineio's own check
      never reads them), and the front door does not trust a raw
      `X-Forwarded-Host` under `trusted_proxies: 0`; the relay is run under
      gunicorn in the Linux container (T13, with consent);
    - **admin access** (`tests/test_admin_access.py`): every rule under
      `/admin`, times every method, answers 401 (or the login redirect)
      anonymous, 403 with one fixed body to a logged-in non-admin, and the
      re-auth redirect to an admin whose re-auth is stale; an unknown
      `/admin/x` answered the same way, then 404, never proxied; CSRF and
      Origin refusals on every admin `POST`; the admin actions bucket; the
      CSP and no-store headers; no worker's URL map holds an `/admin` rule;
      canary: a route added to the admin blueprint after the guard is still
      refused; and `tests/test_ui_no_html_injection.py`, which keeps
      `ui/src` free of `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
      `dangerouslySetInnerHTML` and `document.write`, the property the
      panel's origin sharing relies on (§14.7);
    - **admin operations** (`tests/test_admin_users.py`,
      `tests/test_audit_log.py`, `tests/test_admin_sessions.py`,
      `tests/test_admin_saves.py`, `tests/test_admin_stories.py`,
      `tests/test_admin_model.py`): each action's effect, its audit rows
      and its refusals (the last admin, two admins demoting each other at
      once, a turn in flight, a key outside the allowlist or set by
      `CLOCKWORK_CONFIG`, a base URL with credentials or a query, an
      unreachable new model server, a drain that times out, a rollback, an
      audit write that fails); a generated password only ever in the
      `POST`'s own response body;
    - **the admin layer** (`tests/test_config_admin_layer.py`): its rank,
      read exactly when hosting is on and never in local mode, a key
      outside the allowlist refused at load; `external_config_keys()`
      reporting a legacy `lmstudio.base_url` as `llm.base_url`;
    - **metadata only** (`tests/test_admin_no_play_text.py`): a sentinel
      string played as `player_name`, `custom_text`, a save slot's label,
      the scripted model's narration and the name of a stat the scripted
      model claims appears in no admin page or JSON, no metrics row, no
      audit line and no bus message the supervisor stores; the metrics
      schema's field set is pinned (`tests/test_metrics_schema.py`), with
      rule 12's word-list scan over its names and the Oracle projection's
      keys; the store's rejection, retention and paginated named queries
      (`tests/test_metrics_store.py`);
    - **the doctor's orchestration rows**
      (`tests/test_doctor_orchestration.py`).

---

## §10 — vLLM, live on Linux (carried item 1)

**Route: the `vllm/vllm-openai` Docker image, with the GPU through Docker
Desktop's WSL2 backend** (supported with driver 596). The fallback is
`pip install vllm` in a venv on `Ubuntu-22.04-sp` (vLLM supports that
distro's Python 3.10), and it is used only if the image cannot see the
GPU.

**Why the image.**
- It is pinned and reproducible: a tag, then a digest.
- It needs no CUDA or Python toolchain on either WSL distro, so nothing is
  installed into the owner's distros.
- It is the same artifact the compose file's `vllm` service references
  (§8.2), so verifying it also verifies the documented deployment.
- It sits on the same Docker network as the game container, which lets the
  task prove the "model server from a container" path with a real server.

The download is comparable either way: torch plus CUDA wheels cost what
the image costs.

**The GPU is shared.** The same 12 GB card drives the Windows desktop and
the owner's LM Studio. vLLM refuses to start when free memory is below
`gpu_memory_utilization × total`, so a fixed `0.90` fails whenever LM Studio
holds a model, or the compositor holds its 0.5 to 1 GB. The utilization is
therefore **measured, not chosen**: free memory is read from `nvidia-smi`
with LM Studio unloaded, and the flag is set just under it.

**The Turing (sm_75) constraints, stated as what is known and what must be
measured:**
- vLLM's documented minimum is compute capability 7.0, and the RTX 2060 is
  7.5.
- **No bfloat16 on sm_75.** The server must run `--dtype half`.
- **FlashAttention 2 needs sm_80.** vLLM picks another attention backend
  on Turing. The live risk is the V1 engine and the removal of V0, since
  pre-Ampere support has changed between releases. **Whether the current
  release runs on sm_75 is measured, not assumed**, and the fallback is not
  found by trial: the manifest names, before anything is fetched, the
  newest tag and the fallback tag (the last release that still carried the
  V0 engine or a non-FlashAttention backend for sm_75, read from vLLM's
  release notes), each with its size.
- **No FP8, and no Marlin-kernel quantisation** (both need sm_80 or
  newer). The model is an unquantised FP16 checkpoint.
- **12 GB, less what the desktop holds.** `Qwen/Qwen3-4B` in FP16 is about
  8.05 GB of weights. Its KV cache at 8192 tokens is about 1.2 GB (36
  layers × 8 KV heads × 128 × 2 × 2 bytes). It fits only with LM Studio
  unloaded, `--enforce-eager` (no CUDA-graph memory) and the measured
  utilization. `Qwen/Qwen3-1.7B` is the fallback if it does not.

  Why Qwen3-4B: it is the original hybrid-thinking checkpoint, not a
  Thinking-2507 build. So `chat_template_kwargs: {enable_thinking: false}`
  should be honoured, which exercises the trusted-patch path v0.19.0 could
  only author. And `--reasoning-parser qwen3` exercises the split-reasoning
  path.

**The task.**
1. **Write the download manifest, then stop with status `NEEDS_CONTEXT`**
   (`.superpowers/sdd/v020-downloads-vllm.md`). The controller asks the
   owner in chat; the owner consents item by item **and approves the
   session's permission prompt personally**, and a consent relayed by an
   agent is not consent. Each item is a separate yes/no, with its source and
   its size read from its registry:
   - starting Docker Desktop's engine;
   - the `vllm/vllm-openai` image at the named newest tag (compressed, about
     10 GB), and, as its own item, the named fallback tag;
   - the `Qwen/Qwen3-4B` weights (about 8 GB), and, as its own item, the
     `Qwen/Qwen3-1.7B` fallback (about 3.4 GB);
   - the WSL fallback's wheels, listed but not fetched unless the image
     route fails (and then asked for again).

   Nothing is fetched before a clear yes for that item.
2. Run the server:
   1. ask the owner, in chat, to unload LM Studio's models (or quit it) for
      the run;
   2. read the free memory with `nvidia-smi --query-gpu=memory.free,memory.total
      --format=csv`, and set `U` just under free ÷ total (two decimals,
      rounded down);
   3. `docker run --gpus all --ipc=host -p 8000:8000 -v hf-cache:/root/.cache/huggingface
      vllm/vllm-openai:<tag> --model Qwen/Qwen3-4B --dtype half --enforce-eager
      --max-model-len 8192 --gpu-memory-utilization <U> --reasoning-parser qwen3`.

   Record the startup log's engine version, engine (V0/V1) and attention
   backend, and the measured `U`.
3. From the Windows venv, run the recorder, with `CLOCKWORK_LIVE_LLM=vllm`
   and a `CLOCKWORK_CONFIG` that points at `http://localhost:8000/v1` and
   declares the model (`reasoning: ["off", "on"]`):
   `scripts/record_llm_fixtures.py --provider vllm`, then
   `tests/test_llm_live.py`. The recorder rewrites
   `tests/fixtures/llm/vllm/` from `authored` to `recorded` in
   `PROVENANCE.yaml`.
4. Set each verified cell of the `vllm` row in `engine/llm/providers.py` to
   `verified="vLLM <version>"`, as v0.19.0 did for llama-server. Amend
   `docs/MODEL_SERVERS.md` wherever the live server disagreed with the
   documentation-authored fixture, the same way v0.19.0's T8 amended its
   spec: the probe, the reasoning patch, inline `<think>`, `/health`.
5. If no vLLM release runs on sm_75, the cells stay unverified. The reason
   and the versions tried go in the CHANGELOG, CLAUDE.md and
   `docs/MODEL_SERVERS.md`, and the release ships. A driver or hardware
   limit is a fact to record, not a blocker.

---

## §11 — Docs

- **`docs/HOSTING.md`** (new): what hosted mode is and is not (§Non-goals);
  running it with Docker Compose; running it with gunicorn on a Linux host
  (a systemd unit, including `CLOCKWORK_DATA_DIR`); accounts
  (`scripts/users.py`, `adopt` included); the reverse proxy (Caddy and
  nginx, §7.3, and the `X-Forwarded-For` warning); sizing the model
  server's lanes (§5.3) and `hosting.threads` (§6.9); what hosted mode
  turns off and why (§6.7); where data lives, the `/data` ownership, and
  what the operator can read (§6.8); reaching a model server on the host
  from a container, per platform (§8.2); setting each `llm.*` key in one
  place, the panel or the operator's file, since the file locks it in the
  panel (§8.1, §14.9); upgrading; § Linux (§3.7);
  § Orchestration (the supervisor, the stories, the front door, restarts
  and logs, §14.1–§14.5); § The admin panel (the first admin, re-auth,
  every page, the audit log, §14.6–§14.11); § Metrics (what is recorded,
  retention, and what is deliberately never recorded, §14.10). Every
  other doc links here.
- **README**: "Getting started" loses "Windows is the supported platform
  today". Setup shows PowerShell and POSIX side by side, both with
  `-c constraints.txt`. The local bind is `127.0.0.1` now, with the one
  `config/local.yaml` line that restores LAN play and a pointer to hosted
  mode. There is a new "Hosting" subsection (three commands: build, add a
  user, up; the first user made an admin) linking `docs/HOSTING.md`, and
  the vLLM row in the model-server
  table says what §10 found. Status, features and roadmap are updated for
  v0.20.0, per the owner's README instruction.
- **AGENTS.md**: rule 11 (§3.1); "Verify a checkout" in both spellings,
  plus `docker build .`; the conventions paragraph on tests gains the
  cross-process guard (§3.5) and the module-state inventory (§5.2).
- **CLAUDE.md**:
  - status and the measured Windows and Linux suite numbers, with each
    environment's skip set (§3.9);
  - the in-flight table (v0.20.0 shipped, v0.21.0 next);
  - deferred rows, which gain the local two-tabs sessions (§4.4, worded as
    finding 7 now is), local mode's `cors_allowed_origins="*"` and missing
    Origin check (cross-site WebSocket hijacking by a page the local player
    visits, narrowed to the local browser by the loopback bind), the
    `paths.saves` alias's v0.21.0 removal, xdist sharding (§3.8), the CI
    client job's dist diff if T4 found Vite's output differs by OS, and
    vLLM's status whatever §10 finds;
  - the "Windows is the supported platform" sentences removed.
- **`docs/GOVERNANCE.md` NOT WIRED**:
  - several workers, sticky sessions, a message queue;
  - self-registration, invites, OAuth, proxy-header auth;
  - per-user settings;
  - more than one story per process;
  - URL sub-paths;
  - the queue position (`engine/llm/gate.py`);
  - telling a released tab its run opened elsewhere
    (`engine/scenes/default_scene.py`);
  - per-user media namespaces;
  - disk quotas;
  - image publishing;
  - every row of §14.13.
- **`docs/DESIGN.md`**: the architecture section gains the hosting layer
  (a box around the scene: auth, the socket wrapper, ownership, limits),
  the instance around it (supervisor, bus, front door, workers, §14.1),
  the storage root, and the thread-safety verdicts of §5.2 in one
  paragraph.
- **`docs/AUTHORING.md`**: `paths.saves` is no longer a story key (§4.2).
- **Each story's `CHANGELOG.md`** (`[Unreleased]`): the `saves:` line
  removed from its `game.yaml`.
- **Root `CHANGELOG.md` `[Unreleased]`**, in each task.

---

## §12 — Risks

| Risk | Mitigation |
|---|---|
| Flask-SocketIO's WebSocket under gunicorn `gthread` behaves differently from Werkzeug (upgrades, long streams, disconnects) | the client is WebSocket-first and does not fall back: it connects with `transports: ["websocket", "polling"]` (`ui/src/core/socket.js:81`), and the lock file pins socket.io-client **4.8.3** (`ui/package-lock.json`), whose `tryAllTransports` defaults to false, so a refused WebSocket is not retried over polling. WebSocket under gunicorn is therefore every player's path, and polling is a path the tests exercise, not one players use. T13 runs the front door's socket tests under gunicorn in the Linux container, and T18's smoke test plays a full streamed turn through it in the image |
| The front door's WebSocket relay behaves differently under gunicorn than under Werkzeug, and the suite on Windows can exercise only Werkzeug's | the relay takes the socket over with `simple_websocket.Server(environ)`, the same code and the same takeover the worker's engineio already relies on under both servers, and the only server-specific line is engineio's own sentinel (`StopIteration` under gunicorn, `ConnectionError` under Werkzeug) telling the server not to answer. It is proved under gunicorn in T13, before the admin panel (T14–T17) is built on the front door: T13 asks the owner for the gunicorn wheel (and Docker, if T4's consent does not cover it) and runs `tests/test_frontdoor_socketio.py` in the Linux container with the front door and workers under gunicorn. If it cannot be made to work there, T13 stops and brings it to the controller rather than improvising; there is no UI-free polling fallback to retreat to (the row above). If the owner declines, the proof moves to T18's smoke test with the same stop |
| The supervisor is a new single point of failure | it serves no HTTP and runs no turn: it owns processes, the bus, the queue and the metrics store, and little else can crash it. If it dies, every child exits on its lifeline (§14.2) rather than serve unqueued, and the container's restart policy (or systemd's) restarts the instance; every run is on disk, autosaved each turn |
| The queue stalls: a paused lane deadlocks an admitted turn, one story's waiter blocks another's, a late grant or a hung turn leaks a ticket | a pause stops new narration admissions only, and never a utility grant to an account holding narration; grants skip paused waiters; grants are answered asynchronously, releases never queue, an abandoned grant is released at once, every turn ends by `turn_deadline_seconds`, and a ticket held past `max_hold_seconds` is reclaimed, its worker restarted only if it does not answer (§14.4) |
| Load restarts a busy worker | only an exit, failed bus health checks, the boot deadline or an unacknowledged reclaim (a hung worker) restart a child; an HTTP health failure (a full gthread pool) only marks it `degraded` (§14.3) |
| An `llm.*` edit applied under live turns resets caches mid-turn (finding 8 again) | it is never applied in place: the supervisor probes the new server, drains every turn through the queue, only then writes the admin layer, and restarts the workers one at a time; a drain that times out writes and restarts nothing (§14.9) |
| A worker's response clobbers the front door's cookie change | the front door is the cookie's one writer: workers never send it, the front door strips it from proxied responses and re-issues it only when a request changed it (§6.2) |
| The admin panel leaks play text or becomes a moderation tool | metadata only, by a closed metrics schema, an allowlisted save projection and a sentinel test over every admin surface (§14.10, §9.10); rule 12 is restated in §14.10 |
| The FIFO semaphore and turn admission are new concurrency code on the turn's hot path | hosted mode only; a unit test with 20 threads asserts arrival-order service, no lost slot on timeout or exception, and re-entry of a held lane; local keeps `BoundedSemaphore` |
| A new module global races and nobody notices | the module-state inventory test fails until it is classified (§5.2); warming plus the no-reset crawl keeps caches read-only while serving |
| A socket handler is added outside the wrapper | the enumeration test over `socketio.server.handlers` (§6.3) |
| The suite times out on CI runners | `timeout-minutes: 150`; measured at the first pushed run, and sharding recorded as a deferred row, not attempted |
| The Linux container run is slow or case-blind | the suite runs on a clone inside a container volume, not an NTFS bind mount (§3.9) |
| vLLM refuses sm_75, or Docker Desktop cannot hand the GPU to a container, or the card has too little free memory | §10's fallbacks (the named older tag, the 1.7B model, WSL pip), the measured utilization with LM Studio unloaded; if everything fails, the reason is recorded and vLLM stays unverified, and the release does not wait on hardware |
| `cookie_secure: true` locks out an operator testing over plain HTTP | the login page names the key, decided before CSRF (§6.2); a doctor WARN; `docs/HOSTING.md` says it first |
| One process per story caps the player count | stated as the design (§5.1); the GPU caps it first; `hosting.threads` caps sockets (the front door's pool first, §6.9), and the doctor shows the arithmetic; the lanes and queue make the cap visible as waiting, not failure |
| The loopback bind surprises an owner who played from another device | README and CHANGELOG say so, with the one `local.yaml` line; the doctor WARN names the risk when it is set back |
| Retiring `paths.saves` from manifests moves an author's custom saves directory | only a value other than `data/saves` moves anything; the advisory names it; the config-layer alias covers an owner who set it in `local.yaml` |
| A hosted player loses a run because the idle sweep evicts their session | sessions autosave every turn and resume from disk; the sweep never evicts a session whose turn lock is held (`store.py:365`) |
| Local mode drifts without anyone noticing | the §1 golden with its exact sanctions, asserted every task, and the no-import subprocess test that builds the app |

---

## §13 — Release and tasks

Each task is independently testable, lands with its CHANGELOG
`[Unreleased]` lines and the docs it makes stale, and keeps both goldens
green (the local one with only the sanctions its own or an earlier task
introduced). The release is executed subagent-driven, one fresh subagent
per task, with review between (opus for code and reviews). The plan
(`docs/superpowers/plans/2026-09-30-v0.20.0-linux-and-hosting.md`) carries
the files, test files and steps; this list is the shape.

1. **T1 — The local-mode golden.** The recorder and fixtures, recorded on
   e7fdd26 (§1); `test_local_mode_golden.py` with an empty `SANCTIONED`
   list; `test_local_mode_never_imports_hosting`; the canaries. No engine
   change.
2. **T2 — What the survey found, and the loopback bind.** Save-id
   containment and `join_session`'s order (§4.3, §6.3); the default bind
   `127.0.0.1` and the doctor's hosting-off row (§3.6), the golden's first
   sanction; the `CLOCKWORK_CONFIG` layer and its shadow report (§2.1); the
   secrets chain N1–N3 (§2.2); the doctor's N4 row (§2.3); `_safe_path`
   made portable (§3.4). Each fix comes with a test that fails on v0.19.0.
3. **T3 — One storage root.** `storage.root`, `CLOCKWORK_DATA_DIR` and the
   storage functions, saves and media together (§4.1, finding 2);
   `paths.saves` retired from the six manifests, the templates and every
   reader, with the advisory and the config alias (§4.2), the golden's
   second sanction; `GameSession.owner`/`saves`, `save_store_for`, and the
   autosave through the session (§4.4).
4. **T4 — Linux, first class.** **First step: write
   `v020-downloads-linux.md` and stop `NEEDS_CONTEXT`; the controller asks
   the owner, who consents per item and approves the permission prompt
   personally** (§3.9). Then: `constraints.txt` (§3.10); `scripts/start.sh`
   and the scripts-agree test (§3.2); rule 11 and the scripts' next steps
   (§3.1); extension-free service commands (§3.3);
   `tests/test_portable_paths.py` (§3.4); the doctor's platform row (§3.6).
   Finally, after consent, the suite run on a clone in
   `python:3.11-slim-bookworm` and the client build diffed in
   `node:20-bookworm-slim`, with every Linux-only failure fixed and the
   count, skip set and time recorded.
5. **T5 — Guards across processes, and CI.** The child-only sandbox layer
   and `CLOCKWORK_TEST_SANDBOX` (§3.5), with their subprocess tests and
   canaries, and `.github/workflows/ci.yml` (§3.8). The `image` job is
   added in T18.
6. **T6 — Many sessions, one process: thread safety.** §5.2 whole: the
   module-state inventory and its pinning test; the per-context and locked
   fixes; `warm_all_caches()`; item 12's forced-race tests. Local mode is
   untouched in behaviour, and the golden holds with no new sanction.
7. **T7 — Hosted mode: accounts, login and the HTTP gate.** `engine/hosting/`
   (`config.py` closed schema, `accounts.py` with the inter-process lock,
   `install` with warming and the §6.7 refusals); `scripts/users.py`
   (§6.1); the cookie session and password change (§6.2); the
   `before_request` gate, Origin and CSRF, the hosted Socket.IO CORS and
   buffer size, the login and account pages and the template's inline
   block (§6.3); the login buckets and indistinguishable failures (§6.5);
   `/api/metrics` 404 hosted, always (§6.7).
8. **T8 — Hosted mode: ownership, the socket wrapper and error text.** The
   owner `ContextVar` and `require`'s ownership at every door (§6.4); the
   `scene.on` wrapper, `guarded_events` and its enumeration test (§6.3);
   the per-owner save stores in the routes; generic error text, voice
   included (§6.6); §9.4's crawl.
9. **T9 — Hosted mode: sharing one model server.** `FifoSemaphore`, turn
   admission and `queue_wait_seconds` (§5.3); one live session per account,
   the release hook and the idle sweep reused (§5.4); the actions bucket,
   the input caps and the upload cap (§6.5).
10. **T10 — The bus and the supervisor.** `engine/hosting/bus.py` (the
    framing and its bounded reads, per-child single-use tokens, the closed
    op table with its allowed roles, stamping, the lifeline, §14.2);
    `engine/hosting/supervisor/` (children in their own process groups,
    OS-picked loopback ports, bus health, `degraded`, the boot deadline,
    the restart policy and hold-down, bounded drains, the operations
    table, a bounded shutdown, the per-process logs, the secret key made
    first, §14.3); `engine/hosting/boot.py` (the worker's boot steps and
    the development runner); `hosting.stories`, `hosting.supervisor.*` and
    the log keys; the doctor's `stories` row; `tests/hosting_instance.py`,
    the shared real-process helper, and the time budget (§9.10). Tested
    with probe children.
11. **T11 — The queue across processes.** The gate's lane backend seam;
    the supervisor's own queue (`queue.py`, not T9's class): tickets per
    connection, asynchronous grants that skip paused waiters, pause as "no
    new narration admissions", one narration ticket per account across
    workers, late grants released, `max_hold_seconds`, and the snapshot
    the panel reads; the worker's remote backend, failing closed (§14.4).
12. **T12 — The front door: HTTP.** The front door app (§14.5): login,
    logout, account and the story picker mounted there; routing by the
    story in the signed cookie, the story table kept by `stories.changed`;
    the cookie's one writer (§6.2); the HTTP proxy as a Flask catch-all
    (per-route timeouts, no redirects, `Set-Cookie` stripped), the
    Socket.IO polling proxy; forwarded headers deleted and replaced and
    the proxy token (§7.3); ProxyFix and its wrap order; 503 for a story
    that is down; `launcher.py` hosted runs the supervisor (§7.2), and
    `--check`'s hosted row; the doctor's threads row.
13. **T13 — The front door: WebSockets, and gunicorn.** **First step:
    write `v020-downloads-gunicorn.md` (the gunicorn wheel under
    `constraints.txt`, and Docker's engine and the base image if T4's
    consent does not cover this task) and stop `NEEDS_CONTEXT`; the
    controller asks the owner, who consents per item and approves the
    permission prompt personally.** The files do not wait for consent: the
    WebSocket relay (§14.5), `engine/hosting/wsgi.py` and
    `engine/hosting/frontdoor/wsgi.py` with §7.1's step 4, the
    supervisor's gunicorn command for both roles and its answer to
    gunicorn's own worker restarts, `deploy/gunicorn.conf.py`,
    `requirements-server.txt` and the `server` extra (§7.1). After
    consent: the front door's socket tests run in the Linux container
    under gunicorn (§12).
14. **T14 — Admin role, the panel's shell, the audit log, Users and the
    admin layer.** The `admin` and `must_change` fields and `users.py`'s
    `--admin`/`admin` (§14.6), the guards inside the accounts lock; the
    `/admin` blueprint with its guard (unknown paths included), re-auth,
    CSRF, CSP and the admin actions bucket; the audit log and its
    write-first policy (§14.11), the supervisor's `story.held_down` row;
    the Users page (§14.8); the access enumeration test and the static
    no-HTML-injection test; the admin layer's config half, loaded whenever
    hosting is on, and its doctor rows (§14.9); the doctor's admins row.
15. **T15 — Sessions, saves and stories.** The workers' session ops on the
    bus, paginated; the Sessions page (list across stories, end a
    session); the save browser (the allowlisted projection); the Stories
    page (start, stop, restart, drained and followed as operations);
    disable and delete ending an account's live sessions everywhere
    (§14.8).
16. **T16 — The model server and the queue pages.** Health, loaded and
    declared models, key presence (§14.9); the Queue page (§14.4); the
    `llm.*` edit: validated, the new server probed, drained, then written
    and applied by restarting workers one at a time, followed as an
    operation, and rolled back when a worker cannot boot (§14.9).
17. **T17 — Metrics and errors.** The closed metrics schema, the
    supervisor's SQLite store and retention, the workers' and front
    door's events (hooks `install()` sets), the error events from
    `public_error` and the ERROR log handler, the Metrics, Errors and usage
    pages, the Oracle snapshot per story through its projection (§14.10);
    the sentinel test over every admin surface.
18. **T18 — The production server and Docker.** **First step: write
    `v020-downloads-docker.md` (Docker's engine if an earlier consent did
    not cover it, the base image by digest if not already pulled, the
    `requirements-server.txt` wheels not already fetched in T13, with
    sizes) and stop `NEEDS_CONTEXT`; the controller asks the owner, who
    consents per item and approves the permission prompt personally.** The
    files do not wait for consent: `deploy/entrypoint.sh` (§8.1); the
    hosted doctor rows (§7.4); `Dockerfile` (the supervisor as `CMD`),
    `.dockerignore`, `config/docker.yaml`, `docker-compose.yml` (with
    `init: true` and a `stop_grace_period` above the supervisor's
    `shutdown_seconds`) (§8); the static deployment tests (§9.5); the CI
    `image` job. After consent: build the image, bring it up with two
    stories, add two users (one an admin), and play one streamed turn each
    in two browser sessions through the front door against the owner's LM
    Studio via `host.docker.internal`, recording what reached it (§8.2),
    that neither saw the other's run, and that the admin's panel showed
    both sessions, the queue and the turn timings.
19. **T19 — vLLM live on Linux.** **First step: write
    `v020-downloads-vllm.md` and stop `NEEDS_CONTEXT`; the controller asks
    the owner, who consents per item and approves the permission prompt
    personally** (§10). Then: LM Studio unloaded, the free memory measured,
    the server run, the fixtures recorded, the live tests, the provider
    cells and `docs/MODEL_SERVERS.md` amended, and the compose `vllm`
    service pinned to the tag that ran. If consent allows, the game
    container narrates through it over the compose network.
20. **T20 — Docs and release.** `docs/HOSTING.md`, README, AGENTS.md,
    CLAUDE.md, GOVERNANCE, DESIGN, AUTHORING and the story CHANGELOGs
    (§11), each reviewed for anything no longer true. The suite is measured
    on Windows and, if the owner's consent stands, in the Linux container;
    `npm test --prefix ui`; `scripts/doctor.py`; `launcher.py --check`; the
    simulate runs AGENTS.md lists. `pyproject.toml` and `ui/package.json`
    go to 0.20.0, the CHANGELOG heading becomes `## [0.20.0] — <date>`, and
    the commit subject is `v0.20.0`. Nothing is pushed without the owner's
    word.

---

## §14 — The admin panel and orchestration

Added 2026-09-30 for the owner's scope (see the status note at the top).
This section is the design; the sections it changes point here. It is
reviewed on its own before its tasks run.

### 14.1 The shape: a supervisor, a front door, a worker per story

**Decision.** A hosted instance is three kinds of process on one host:

```
                 players' browsers (and the operator's)
                              │  :5573 (scene.clockwork.port), behind the operator's TLS proxy
                    ┌─────────▼──────────┐
                    │     front door     │  login, logout, account, story picker,
                    │ (gunicorn, gthread)│  /admin panel; proxies HTTP, Socket.IO
                    └──┬──────────────┬──┘  polling, and relays WebSockets
            127.0.0.1:<os-picked>     127.0.0.1:<os-picked>
          ┌────────────▼───┐      ┌───▼────────────┐
          │ worker: story A│ ...  │ worker: story B│  §5–§6 unchanged: one story,
          └──────┬─────────┘      └─────────┬──────┘  sessions, turns, the gate
                 │   the bus (127.0.0.1, token)   │
          ┌──────▼────────────────────────────────▼──┐
          │ supervisor: children, health, restarts,   │
          │ logs, the shared lanes, metrics, llm.*    │
          └───────────────────────────────────────────┘
```

- **The supervisor** (`python -m engine.hosting.supervisor`) is a plain
  Python process. It serves no HTTP and runs no turn. It starts, watches
  and restarts every other process, holds the model server's lanes for all
  of them (§14.4), owns the metrics store (§14.10) and the admin layer
  (§14.9), and captures every child's log.
- **A worker** is exactly §5–§6's hosted process for one story (gunicorn,
  one gthread worker), started with `CLOCKWORK_GAME=<slug>`, listening on a
  loopback port nobody outside reaches. Its gate, socket wrapper, ownership
  and limits are unchanged: they still check the cookie on every request
  and event.
- **The front door** is a small Flask app (gunicorn, one gthread worker)
  that activates no story and runs no turn. It owns login and the account
  page (T7's blueprint, mounted here instead of on the workers), the story
  picker and the admin panel, and passes everything else to the chosen
  story's worker (§14.5).

**Why processes and not one process with several stories.** The active
story is process-wide (`registry.py:321`, the Non-goals), and every content
cache is keyed by it. Changing that is an engine rewrite; a process per
story is none, and it keeps §5.2's analysis true per process.

**Why the supervisor is not gunicorn's master.** gunicorn's arbiter forks
workers of one app and runs hooks between; the supervisor must run
different apps, restart them one at a time, hold the queue across them and
outlive each. Keeping it a plain process with no HTTP also keeps the one
process nothing restarts small (§12).

**Local mode never starts it.** `launcher.py` with `hosting.enabled: false`
is v0.19.0's code path, and the supervisor lives under `engine/hosting/`,
which local mode never imports (§1). A test runs `launcher.main([])` with
`subprocess.Popen` spied and the stack's probe and start stubbed as T1's
golden stubs them, and asserts that no spawned argv names
`engine.hosting`. (It cannot assert that nothing spawns: local mode starts
the managed stack services through `engine/stack.py`'s `Popen`, which is
v0.19.0's behaviour.) The new environment variables (`CLOCKWORK_BUS_ADDR`,
`CLOCKWORK_BUS_TOKEN`, `CLOCKWORK_BUS_ROLE`, `CLOCKWORK_PROXY_TOKEN`) are
stripped by the local golden's pinning, a runner change (§1 allows it); the
fixtures do not move. The admin layer needs no variable: it is read only
when hosting is on (§14.9).

**One production shape.** From T13, `engine.hosting.wsgi:app` refuses to
boot without the supervisor's bus (§7.1), so a worker can never serve with
lanes of its own beside the shared queue. Tests keep building a hosted
worker in-process (T7–T9's tests), which is the standalone shape and is
used for nothing else.

### 14.2 The bus

**Decision.** The supervisor and its children talk over one TCP connection
per child on `127.0.0.1`, to a port the OS picks when the supervisor binds.

- **Credentials: one token per child start.** Each time the supervisor
  starts a child it mints a 32-byte token (`secrets.token_hex(32)`) for
  that child alone and records what the token is: the role (`frontdoor` or
  `worker`) and, for a worker, its slug. The child gets it in its
  environment only (`CLOCKWORK_BUS_ADDR`, `CLOCKWORK_BUS_TOKEN`), never on
  argv (visible in `ps`), in a file or in a log line. `CLOCKWORK_BUS_ROLE`
  also reaches the child, but only to tell its own boot which app to build
  and where to bind; the supervisor never believes it. The child reads both
  token variables (and `CLOCKWORK_PROXY_TOKEN`, §14.5) once and deletes
  them from its `os.environ`, so a grandchild (a media or TTS subprocess)
  does not inherit them.
- **`hello`.** A connection's first message must be `hello` carrying a
  token, within `supervisor.hello_seconds` (2 s; it was 5 s until T10 fix
  round 2: a real child says hello at once, and a longer wait only held a
  slot for an idle socket), or the connection is closed. Past
  `MAX_PENDING` connections waiting for `hello`, a newcomer evicts the
  oldest of them, so idle sockets cannot lock a child out. The token is compared
  with `hmac.compare_digest`, and it is **single-use**: accepted once, dead
  when that connection closes, and refused while its connection is up, so
  a second `hello` for a child already connected is refused. The
  connection's role and slug come from the supervisor's record of the
  token, and `hello` carries nothing else.
- **Framing.** One UTF-8 JSON object per line, at most 64 KiB, read with a
  bounded `readline(limit)` before anything parses it. A request is
  `{"id": n, "op": "...", "args": {...}}`, a reply `{"id": n, "ok": true,
  "result": {...}}` or `{"id": n, "ok": false, "error": "<code>"}`, and a
  message with no `id` is a notification (metrics, `stories.changed`).
  Either side may send requests. JSON and never pickle: a pickle on a
  socket is code execution for whoever holds the token.
- **Size, both ways.** An oversize or malformed **inbound** frame closes
  the connection (a child that sends one is broken). A **reply** that would
  exceed the cap is never sent: its sender replaces it with `{"id": n,
  "ok": false, "error": "too_large"}` and the connection stays up, so a
  `sessions.list` or a query that grew with use costs one page an error,
  not the front door its lifeline. Lists that grow with use (`sessions.list`,
  every named metrics query, the audit page) take `limit` and `offset`, and
  the panel's pages paginate.
- **A closed op table.** `engine/hosting/bus.py::OPS` names every op, the
  direction it may travel, **the roles allowed to call it**, and its
  argument schema; an unknown op or a bad argument gets `unknown_op` or
  `bad_args`, a caller its row does not allow gets `forbidden`, each with
  one WARNING. The roles name who may send a request **to the
  supervisor**; the requests the supervisor sends a child (`health`,
  `drain`, `shutdown`, `lane.reclaimed` (T11 fix round 1), and its fan-out of `sessions.*` and
  `oracle.snapshot` to workers -- the `sessions.*` fan-out sent as rows of
  their own, `worker.sessions.list`, `worker.sessions.end` and
  `worker.sessions.end_owner` (T15), since one op has one direction) and its
  notifications (`stories.changed`) are refused from any child:
  - front door only: `stories.*`, `ops.list`, `sessions.list`,
    `sessions.end`, `sessions.end_owner`, `llm.*`, `queue.snapshot`,
    `metrics.query`, `oracle.snapshot`;
  - workers only: `lane.acquire`, `lane.release`, `lane.cancel` (T11 fix
    round 1);
  - both: `hello`, `ready`, `metric`.

  The supervisor **stamps** what it knows from the connection: the `story`
  of a lane request and of a worker's metric, and the `process` of every
  metric, whatever the arguments say. A `lane.release` of a ticket another
  connection holds is `bad_args`. The admin a story or model op acts for
  (`actor`) is passed by the front door, the one role that can call those
  ops, and taken from its authenticated request. Each task adds its ops:
  T10 `hello`, `ready`, `health`, `drain`, `shutdown`, `stories.*`,
  `ops.list`; T11 `lane.*`, `queue.snapshot`; T12 `stories.changed`; T15
  `sessions.*`; T16 `llm.*`; T17 `metric`, `metrics.query`,
  `oracle.snapshot`.
- **The lifeline.** A child whose bus connection closes stops accepting
  requests and exits non-zero: a worker must not run turns outside the
  shared queue, and a front door cannot answer the panel without the
  supervisor. The supervisor treats a closed connection as that child down,
  and frees every lane ticket it held (§14.4). Under gunicorn the
  connection belongs to the gunicorn worker, and the supervisor answers its
  close by terminating the master and starting the child again (§7.1,
  §14.3).
- **Threads.** A child's bus client has one reader thread and a pool of
  four for requests the supervisor sends it. The supervisor reads every
  connection on one selector thread, which answers `hello`, `lane.*`,
  `health` and `ops.list` itself and never blocks (§14.4); the long
  operations (a drain, a restart, an apply) run on the supervisor's
  operations thread. Each is classified in
  `tests/fixtures/module_state.yaml` (T6's inventory).

**Why this and not the alternatives.**
- A **Unix socket** would take file permissions instead of a token, but
  not on Windows, where the owner tries hosted mode and the suite runs;
  one mechanism everywhere is one mechanism tested.
- A **file lock** for the queue has no arrival order, no position, no "who
  is waiting", different release-on-crash semantics per OS (`fcntl` against
  `msvcrt`), and no timeout without polling.
- **`multiprocessing`** primitives need a shared parent's memory; gunicorn
  workers are exec'd, and `multiprocessing.managers` is this protocol with
  pickle.
- **HTTP** between processes would need leases and a reaper for a ticket
  whose holder died. A held connection whose close frees its tickets needs
  neither.

### 14.3 The supervisor

**Decision.** `engine/hosting/supervisor/` (`__main__.py`, `process.py`,
`server.py`, `logs.py`). On start, in order:

1. requires `hosting.enabled` (the §8.1 refusal) and a non-empty
   `hosting.stories` whose every slug the registry knows and validates,
   naming any that fails; applies the §6.7 startup refusals itself, so the
   operator sees one error and not a crash loop per story;
2. checks the storage root is writable, and makes the cookie key (§6.2)
   before any child starts, so every child reads the same one;
3. binds the bus, then opens the metrics store (T17);
4. starts one worker per slug, in list order, and the front door.

**Children.** The command is built from `sys.executable`, never a
hardcoded path: on POSIX, when gunicorn is importable, gunicorn with
`deploy/gunicorn.conf.py` and the role's `wsgi` module (T13); on Windows,
and wherever gunicorn is absent, `python -m engine.hosting.boot --role
worker|frontdoor`, a Werkzeug server with the §7.2 WARNING. A worker binds
`127.0.0.1:0` and reports the port the OS gave it in its `ready` message
(gunicorn's `post_worker_init` hook, or Werkzeug's `server.server_port`);
the front door binds `scene.clockwork.host`/`port`. No port is configured
for a worker, so none collides and none is hardcoded (rule 5).

Each child starts in its own process group (`start_new_session=True` on
POSIX, `CREATE_NEW_PROCESS_GROUP` on Windows). Ctrl+C on Windows reaches
the whole console group, and SIGINT in a POSIX terminal the whole
foreground group; without this every child would die at once under the
supervisor's feet instead of being drained by it.

Under gunicorn the process the supervisor spawned is the **master**, and
the bus connection belongs to its gunicorn worker. When gunicorn restarts
that worker itself (a missed heartbeat, a crash), the connection closes;
the supervisor treats the close as the child down, terminates the master
and starts it again with a fresh token, and the respawned gunicorn
worker's `hello` is refused (the old token is single-use, §14.2). So one
child is always one connection, and nothing serves between the two.

**States.** `starting` → `ready` (after `ready` and a first passing health
check) → `draining` → `stopped`; `degraded`; `restarting`; `held_down`. The
front door holds its own copy of the table: it reads it once with
`stories.list` when it connects, and the supervisor then sends a
`stories.changed` notification on every change, so a proxied request never
waits on a bus round trip to find its worker.

**Health.** Every `supervisor.health_interval_seconds` the supervisor sends
a bus `health` request, answered on the child's request pool (so it
measures whether the process is alive and serving its bus), and makes a
`GET /api/health` on the child's port (httpx, 5 s timeout,
`trust_env=False`). What each can do differs:

- `supervisor.health_failures` consecutive failed **bus** health checks, or
  an exit, restart the child;
- a failed **HTTP** health check only marks the child `degraded` (shown on
  the Stories page, recorded as a `process` `unhealthy` event), and a pass
  clears it. It never restarts anything: under gthread every open WebSocket
  pins a pool thread (§6.9), so a full pool makes the health request wait
  and time out, and restarting on that would kill the busiest story's
  worker, drop every player on it, and repeat;
- a child that has not sent `ready` within `supervisor.boot_seconds` of its
  spawn is restarted (warming can be slow, but not forever);
- a lane ticket held past `supervisor.max_hold_seconds` is reclaimed, and
  its worker restarted only if it does not acknowledge the reclaim within
  seconds (it is hung; §14.4).

**The restart policy.** Backoff 1, 2, 4 … 60 s. More than
`supervisor.max_restarts` **crash** restarts (an exit, the bus health
checks, the boot deadline, a reclaim the worker did not acknowledge; a
reclaim itself never counts) in
`supervisor.restart_window_minutes` **holds the child down**: logged at
ERROR, recorded as a `process` event and a `story.held_down` audit row
(§14.11), shown on the Stories page, and restarted only by an admin or a
supervisor restart. A restart an admin or the supervisor chose (a story
restart, a model apply) does not count, so three edits and one crash in
ten minutes do not hold a story down. The front door follows the same
policy, except that a held-down front door ends the supervisor (exit
non-zero): an instance with no front door serves nothing, and the
container's or systemd's restart policy is the right next step.

**Draining.** To stop or restart a worker: pause new narration admissions
for that story (§14.4), wait until it holds no lane ticket, bounded by
`supervisor.drain_seconds`, send `shutdown` over the bus, and terminate
after `supervisor.stop_seconds`, then kill. A drain for an admin's stop or
restart that runs out resumes the story and changes nothing: "turns are
still running; the story was not stopped" (audited as refused). A turn
queued but not admitted when its worker stops is answered busy: it never
started (admission precedes every mechanic, §5.3), so nothing is lost, and
the client's reconnect `resume` rebuilds the session from its autosave when
the story is back.

**Operations answer at once.** `stories.start`, `stories.stop`,
`stories.restart` (and `llm.apply`, §14.9) do not hold the front door's
request open for a drain: the supervisor answers `{op_id}` at once, runs
the operation on its operations thread, one at a time (a second is refused
"another operation is running"), and keeps an operations table (`queued`,
`validating`, `draining`, `restarting`, `done`, `refused`, `rolled_back`,
with the time
of each step) that the Stories and Model pages read with `ops.list`. So no
admin `POST` waits longer than a bus round trip, far inside any proxy's
read timeout.

**Shutdown.** `SIGTERM`/`SIGINT` on POSIX (`docker stop`), Ctrl+C on
Windows: from that moment nothing is restarted, whatever exits; drain and
stop every worker, THEN the front door (T18 fix round 1: stopped alongside
them, it closed a drained turn's relay before the turn's last events
arrived), close the metrics store, exit 0, all within
`supervisor.shutdown_seconds`, after which any child still running is
killed. The container's stop grace is set above it (§8.2). Children are
stopped over the bus, so the same path works on Windows, which has no
`SIGTERM` to send.

**Logs.** Each child's stdout and stderr are read by the supervisor and
written to `<root>/hosting/logs/<process>.log` (`frontdoor`,
`worker-<slug>`, and `supervisor` for its own), rotated at
`observability.log_max_mb`, keeping `observability.log_keep` files, and
echoed to the supervisor's stdout prefixed `[<process>]`, so `docker logs`
still shows everything. The files are the operator's to read on disk; the
panel never shows log text (§14.10).

### 14.4 One queue across processes

**Decision.** The supervisor holds the lanes for every worker, in its own
structure, `engine/hosting/supervisor/queue.py`, sized by `llm.lanes`. It
is not T9's `FifoSemaphore`: that class blocks a thread per waiter and
serves strictly the head of its queue, and the supervisor needs to skip a
paused story's waiters and to answer waiters without a thread each. It
shares the idea: each lane is a deque of waiter entries `(ticket, story,
account, connection, since, deadline)` and a set of holders, and a grant
goes to the **first eligible** entry in arrival order. The gate gains a
**lane backend** seam, `gate.set_lane_backend(backend)` (startup only), and
the worker's `install()` plugs in
`engine/hosting/lanes_remote.py::RemoteLanes`, so `engine/llm/gate.py` still
never imports `engine.hosting`. Local mode sets no backend and keeps
`BoundedSemaphore`; a standalone hosted worker keeps T9's in-process FIFO.

- **Acquire and release.** `lane.acquire {lane, account, timeout}` joins
  the lane's deque and is answered `{ticket}` when granted, or `busy` at
  its deadline; `lane.release {ticket}`. The supervisor stamps the `story`
  from the connection (§14.2). Turn admission (§5.3) is a narration
  acquire.
- **Grants are asynchronous.** No supervisor thread waits for a lane: an
  acquire that cannot be granted at once is an entry in the deque, and it
  is answered by whichever event frees a slot (a release, a cancel, a
  resume) or by the deadline timer. `lane.release` and a connection's
  close are handled on the selector thread itself, so a release can never
  queue behind blocked acquires from the same worker.
- **No ticket without an owner.** A child's bus timeout for `lane.acquire`
  is strictly longer than the acquire's own `timeout`, so the supervisor
  always answers first. If a grant still arrives for a request the worker
  has abandoned (its calling thread gave up), `RemoteLanes` releases it at
  once and counts it (a `lane` event, outcome `cancelled`).
- **No ticket forever.** A worker ends each admitted turn by
  `hosting.turn_deadline_seconds` (§6.9; T11 fix round 1). A ticket still
  held past `hosting.supervisor.max_hold_seconds` (at least the deadline
  plus 120 s) is RECLAIMED: it logs an ERROR, records a `process`
  `unhealthy` event, frees the slot for the next waiter at once, and tells
  the worker (`lane.reclaimed`), whose turn then makes no further model
  call (nothing runs outside the queue) and whose later release of it is
  accepted quietly. A reclaim is never a crash. A worker that does not
  acknowledge within a grace period is hung, and is restarted as a crash.
  A hung turn thread would otherwise stall every story while its worker's
  health checks still pass.
- **A wait is cancelled when its player leaves** (T11 fix round 1). A
  hosted socket turn's admission is called off when its socket
  disconnects (`lane.cancel`), so the departed player holds no place and no
  account claim (`other_window`) for the rest of the wait.
- **The account is the worker's word.** `lane.acquire`'s `account` comes
  from the worker, which takes it from its own login-checked session; the
  supervisor checks only its shape. A worker is a token-authenticated child
  of the supervisor (§14.2), inside the trust boundary, and the rule it
  serves is fairness between one operator's players, not a security
  boundary.
- **Tickets belong to the connection.** A connection that closes releases
  every ticket it held and cancels its waits, so a crashed worker cannot
  leak a lane.
- **Held lanes stay in the worker.** §5.3's `ContextVar` is unchanged: a
  turn's `:retry`, `:room` and stream calls re-enter the held narration
  lane without a bus request.
- **One narration ticket per account, across workers.** A narration
  acquire for an account that already holds or awaits one from another
  worker answers `busy` at once with reason `other_window`, which
  `run_guarded` answers "A turn is still running in your other window."
  (the §5.4 wording). The utility lane has no such rule: its calls are made
  inside the same account's turn.
- **Pause and resume.** A pause, for one story (a drain) or for all
  (§14.9), means **no new narration admissions** for it. What it does not
  stop matters as much:
  - a utility acquire from an account that holds a narration ticket is
    granted as always. The planner, the summarizer, the Assistant and quest
    evaluation ask for the utility lane mid-turn (§5.3), after the turn was
    admitted; pausing them would hold every admitted turn for its whole
    wait and hold the drain, which waits on that turn, just as long;
  - a paused story's waiters keep their places, but grants **skip** them:
    the first eligible entry is served, so a paused story at the head of a
    lane never delays another story's waiter;
  - other utility acquires from a paused story (the voice route's
    Assistant reply, outside any turn) wait with its narration waiters.

  Grants resume in arrival order. A drain waits until the story holds no
  ticket in any lane, which an admitted turn reaches in its own time.
  Lane sizes change only while every lane is paused and **no ticket is held
  in any lane**.
- **Fail closed.** With the bus down, an acquire raises `InferenceBusy`
  at once, and the lifeline ends the worker.
- **What the panel sees.** `queue.snapshot`: per lane, the limit, whether
  paused, the holders and the waiters in order, each as `(story, account
  id, since)`. Ids and numbers only; the front door resolves names.
- **Cost.** One loopback round trip per acquire and per release, against a
  model call of seconds.

*Why not reuse T9's class.* An earlier draft did, and its review found it
would deadlock: a drain paused every grant for the story, an admitted turn
then asked for the utility lane and waited out `queue_wait_seconds` before
degrading, and the drain, waiting on that turn, took as long; one paused
story's waiter at the head of the FIFO would also have stalled every other
story. Tests pin both (§9.10).

### 14.5 The front door

**Decision.** `engine/hosting/frontdoor/` builds a Flask app that
activates no story and builds no engine. It owns these routes, and passes
every other request to the chosen story's worker:

- `GET /api/health` (its own: 200 while the bus is up);
- `/login`, `/logout`, `/account` (T7's blueprint);
- `GET /stories` and `POST /stories/<slug>` (the picker);
- `/admin` and everything under it (§14.7): the admin blueprint registers
  `/admin/<path:rest>` too, answered 404 **after** its guard, so an unknown
  admin path meets the admin checks and never falls through to a worker;
- `/static/hosting/…`, the pages' own stylesheet and script.

**One gate, two doors.** The HTTP proxy is a Flask catch-all route, so the
front door's `before_request` gate (login, `must_change`, Origin, §6.3,
§14.6) runs on every proxied request as it does on the front door's own.
The WebSocket door is WSGI middleware in front of Flask (below), which no
`before_request` reaches, so both call one function,
`frontdoor.gate.authenticate(environ)`: it opens the signed session through
`app.session_interface.open_session` inside `app.request_context(environ)`,
re-reads the account (epoch, disabled, `must_change`) and returns the
account and the chosen story, or the refusal.

**Routing by a choice in the cookie.** `POST /stories/<slug>` (CSRF-checked
like every form) writes `story` into the signed Flask session. `GET /`
without a choice goes to `/stories`, unless exactly one story is ready,
which is chosen. The picker lists the stories that are ready, with their
titles from the registry's listing (read without activating anything).
The front door's story table (state, port) is its own copy, kept current by
the supervisor's `stories.changed` notifications (§14.3), so routing a
request costs no bus round trip.

*Why not by path, port or host name.* A path prefix needs the client to
fetch relative URLs, a UI change this release does not make (the
sub-path Non-goal). A port per story means N published ports, N origins
for the Origin and CORS checks, and N blocks in the operator's TLS proxy.
A host name per story needs DNS per story. A choice in the signed cookie
needs none of them. Its costs, all of them the price of one story per
browser: a browser plays one story at a time; switching in one tab moves
the others (their next request reaches the other story's worker, which
answers "session not found"; the client then offers a new game or a load);
the client's resume key, `clockwork_save_id`, is one `localStorage` entry
per origin (`ui/src/core/socket.js:48`), so switching stories loses
auto-resume for the other one; and a WebSocket already open stays on the
old story's worker while that tab's HTTP moves to the new one. **NOT
WIRED** (§14.13).

**HTTP.** One pooled `httpx.Client` (`trust_env=False`, so no system
proxy intercepts loopback; `follow_redirects=False`, so a worker's redirect
reaches the browser as it was sent), streaming both bodies, with
`MAX_CONTENT_LENGTH` enforced at the front door too. Its read timeout is set
per route class, each above the longest legitimate wait:

- a Socket.IO polling `GET`, which engineio holds for up to
  `ping_interval` + `ping_timeout` (25 + 20 s by default): 60 s;
- a route that may run a turn or a model call (`POST /api/game/new`,
  `POST /api/game/choice`, `POST /api/voice/transcribe`):
  `hosting.queue_wait_seconds` plus `hosting.turn_deadline_seconds` plus a
  minute (T12 fix round 1: since T11 the deadline, counted from admission,
  bounds a turn, and `llm.timeout_seconds` bounds only one read; 1560 s by
  default). Such a request's whole body is read first, within
  `hosting.body_read_seconds`, before it takes a turn slot (408 past it),
  and an account has at most one HTTP turn in flight at each door;
- everything else: 30 s.

Hop-by-hop headers are dropped, `Host` is kept, `X-Forwarded-For`/`-Proto`/
`-Host` are **replaced** with what the front door's own `ProxyFix` resolved
(§7.3), and `X-Clockwork-Proxy` carries a per-boot proxy token
(`CLOCKWORK_PROXY_TOKEN`, separate from the bus tokens, the same for every
child of one supervisor start). A worker applies `ProxyFix(x_for=1,
x_proto=1, x_host=1)` only to a request carrying that token, and deletes
forwarded headers otherwise (§7.3). Any `Set-Cookie` for
`clockwork_session` is **stripped** from the worker's response: the front
door is the cookie's one writer (§6.2). A worker that does not answer gives
503: a small page for `GET /` ("<title> is restarting" or "stopped by the
operator"), JSON `{"error": "story unavailable"}` elsewhere.

**Socket.IO: the hard part.** The client is WebSocket-first and does not
fall back to polling (§12: socket.io-client 4.8.3, `tryAllTransports`
false), so the WebSocket path is every player's path, and polling is a path
the tests exercise.
- **Polling** is plain HTTP and goes through the proxy above. There is one
  worker per story, so every poll of an engineio `sid` reaches the worker
  that issued it, and no stickiness is needed.
- **WebSocket: a message relay.** `engine/hosting/frontdoor/ws_relay.py` is
  WSGI middleware in front of Flask (inside the front door's `ProxyFix`,
  §7.3). On a `/socket.io/` request asking `Upgrade: websocket`, in order:
  1. `authenticate(environ)`: a live account, a story chosen and ready;
     then `Origin` against the resolved Host or `hosting.public_origin`,
     never a raw `X-Forwarded-Host` (§7.3). A refusal is a plain HTTP
     answer (401; 403; 409 for no story chosen, as the HTTP door answers
     it -- T13's ruling; 429 past `max_connections_per_account`; or 503),
     and nothing reaches the worker;
  2. it connects to the worker as a WebSocket **client**
     (`simple_websocket.Client`, to `ws://127.0.0.1:<port>` with the same
     path and query), sending the cookie, the client's `Origin`, the
     replaced `X-Forwarded-*` headers and the proxy token. The worker's
     engineio does its own handshake and origin check (the forwarded host
     it trusts through the token), and its socket guard (§6.3) authenticates
     `connect` as before. If the worker refuses the upgrade, the client
     gets a plain HTTP 502, never an upgrade;
  3. only then does it take the client's socket over as a WebSocket
     **server** (`simple_websocket.Server(environ)`, with `max_message_size`
     equal to the workers' `max_http_buffer_size`), and relay messages both
     ways, text as text and binary as binary, until either side closes,
     when it closes the other with the same code. Engine.IO's pings are
     ordinary messages and pass through; each hop answers WebSocket-level
     pings and closes itself;
  4. it ends the WSGI call as engineio does after its own takeover
     (`engineio/async_drivers/_websocket_wsgi.py`): `raise StopIteration()`
     under gunicorn, `raise ConnectionError()` under Werkzeug, by the
     server's `ws.mode`, so the server writes nothing more on the socket.
- *Why a relay and not a byte splice.* An earlier draft spliced bytes: it
  took the raw socket, re-wrote the client's request to the worker and
  copied bytes both ways. That needed per-server socket handling and
  response suppression, and it smuggled: when the worker answered anything
  but `101` (a bad `sid`, a refused Origin) on a keep-alive connection, the
  client's next bytes reached the worker as new HTTP requests that had
  passed none of the front door's checks. A relay never lets the client
  speak HTTP to the worker at all, and its server side is the same
  `simple_websocket.Server` takeover the worker's engineio already
  performs under both servers, so there is one mechanism, not two. Its
  cost is simple-websocket's reader threads (one per end of each
  connection) plus one relay thread, outside the gthread pool; at this
  scale that is nothing.
- *Why not a per-story path prefix* (Socket.IO's `path` option). It is the
  right direction for v0.21.0, and it would make NOT WIRED row 3 go away,
  but the client would have to learn its prefix (`ui/src/core/api.js`
  fetches absolute `/api/...` paths), and this release changes nothing
  under `ui/src`. *Nor a stock reverse proxy routing by cookie*: it needs
  fixed worker ports and per-story operator config, and the image ships no
  proxy, so a LAN trial would have nothing to route with.

**Limits.** The login buckets live in the front door (one process, so
exact). The actions bucket stays in each worker (§6.5). The admin actions
bucket is the panel's (§14.7). Under gthread each relayed WebSocket pins a
front door thread for its life (§6.9). An HTTP turn (a new game, a choice, a
transcription) holds a thread while it waits in the queue, so each process,
the front door for every story together, lets at most `hosting.threads - 4`
be in flight and answers the next 429 at once (T12, from T9's review:
`engine/hosting/limits.py::TurnSlots`).

**`launcher.py`.** From T12, `launcher.py` with hosting on runs the
supervisor in the foreground (§7.2), and `launcher.py --check` gains the
hosted row (§7.4).

### 14.6 The admin role

**Decision.** An account row gains `admin` and `must_change` (§6.1).

- **The first admin** is made on the command line, by someone with a shell
  on the server: `python scripts/users.py add <name> --admin`, or `python
  scripts/users.py admin <name> on` for an existing account. The panel can
  grant and revoke the role after that.
- **Guards the panel keeps.** An admin cannot revoke their own role, or
  disable or delete themselves, from the panel; the last enabled admin
  cannot be demoted, disabled or deleted from it ("at least one admin must
  remain; use `scripts/users.py`"). The CLI can do each, with a terminal
  confirmation, because an operator with a shell already owns the server.
  The guards are checked **inside** `accounts.py`'s lock, in the same
  read-modify-write as the change, so two admins demoting each other at
  once cannot both pass the check and leave none.
- **A role change bumps the epoch**, so a demoted admin's open panel is
  logged out on its next request.
- **`must_change`** is set when an admin creates an account or resets a
  password (§14.8). The front door then sends that account to `/account`
  for every page and answers other routes 403 JSON `{"error": "password
  change required"}`; a worker treats it as logged out. `POST /account` and
  the CLI's `passwd` clear it.

### 14.7 The admin panel

**Where: a route prefix on the front door, `/admin`, not a port of its
own.** Cookies are scoped to a host name, not a port, so a second port
would not isolate the admin's cookie; it would add a second block and
certificate in the operator's TLS proxy, and a second published port in
the image. A port does scope the **script origin**, and that is the one
thing sharing the game's origin gives up: script running on the game's
pages could read `/admin`. The panel's real protection against that is
that the game's client injects no HTML: nothing under `ui/src` uses
`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`
or `document.write`, so neither model output nor a player's text can
become script on the game's origin. The panel depends on that, and
`tests/test_ui_no_html_injection.py` (a static scan of `ui/src`, T14) keeps
it true until v0.21.0's client overhaul, which must keep it or move the
panel. Binding the panel to loopback instead would put it out of reach of
the operator behind their proxy. The rest of the isolation comes from the
checks below, which a test enumerates (§9.10). An operator who wants the
panel off the internet denies `/admin` at their proxy (`docs/HOSTING.md`
gives the Caddy and nginx lines); a network allowlist inside the engine is
**NOT WIRED**.

**How it is built: server-rendered, not the `ui/` build.** Jinja templates
under `engine/hosting/admin/templates/`, one stylesheet and one small
script under `engine/hosting/admin/static/`, no build step, no framework
and no new dependency. Every page works without JavaScript: every change is
a `POST` form carrying a CSRF token. The script only refreshes the
read-only views (queue, sessions, stories, health) from
`/admin/api/*.json` every few seconds. Why not `ui/`: v0.21.0 owns the
client's overhaul, and a panel built in it now would either pre-empt that
design or be rebuilt by it; nothing under `ui/src` changes in this release,
so `dist` is not rebuilt. An operator's tables and forms need no client
framework.

**Its own checks**, one blueprint `before_request` over every `/admin`
rule, like §6.3's gate, so a route added later is covered, and so is an
unknown path (`/admin/<path:rest>`, a 404 after the checks, §14.5):

1. no login: 401 JSON, or the login redirect for a page `GET`;
2. logged in, not an admin: 403, with one fixed body for every rule;
3. an admin whose `admin_at` (set by `/admin/reauth`) is older than
   `hosting.admin.reauth_minutes`: the re-auth page for a page `GET`, 401
   JSON `{"error": "reauth required"}` otherwise. `/admin/reauth` asks for
   the password again, under the login buckets, and a failure is audited;
4. on every `POST`: the CSRF token (the stateless `uid|epoch` token of
   §6.3), T7's Origin check, and the `admin_actions_per_minute` bucket.

The account is re-read on every request (epoch, disabled, admin), as it is
everywhere. No `GET` changes anything.

**Headers on every `/admin` response:** `Content-Security-Policy:
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self';
frame-ancestors 'none'; form-action 'self'; base-uri 'none'`,
`X-Frame-Options: DENY`, `Cache-Control: no-store`,
`Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`.

**Pages:** Overview (stories, queue depth, model server health, errors in
the last hour); Users; Sessions; Saves; Stories (§14.8); Model server and
Queue (§14.9, §14.4); Metrics and Errors (§14.10); Audit (§14.11).

### 14.8 Users, sessions, saves and stories

**Users** (T14). The list shows name, id, created, admin, disabled,
`must_change`, live sessions (from T15) and last login (from T17). The
actions, each through `accounts.py` and each audited:

- **create**: a name; the panel generates a one-time password
  (`secrets.token_urlsafe(12)`), shows it **once**, in the body of the
  response to that `POST` itself, and sets `must_change`. It never travels
  any other way: not through a redirect, a flash message, the session (the
  cookie is signed, not encrypted) or a URL. It is never logged, audited or
  stored but as its hash. Why generated: an admin should never know a
  player's real password, and one they must replace at first login means
  they never do;
- **reset password**: the same, and the epoch bumped;
- **disable / enable**: the epoch bumped, and (from T15) the account's
  live sessions ended in every story;
- **grant / revoke admin**: §14.6's guards;
- **delete**: type the name to confirm, and choose **keep** (the account's
  `<root>/users/<id>/` is left where it is; ids are random and never
  reissued, so nobody inherits it) or **purge** (it is deleted). The
  account is disabled and its sessions ended first.

**Sessions** (T15). `sessions.list` fans out to every ready worker, a page
at a time (`limit`, `offset`, §14.2), and shows, per live session: the
story, the owner's name, a short reference
(the full id travels only in the form), the save id, created, last
activity, the turn count, whether a turn is running, and the sockets in its
room. Never the player's name, place, day or anything else from the state.
**End session** sends `sessions.end` to that story's worker, which releases
it through `SessionStore.delete` and the release hook (§5.4). It is refused
while the session's turn lock is held ("a turn is running; try again in a
moment"): a turn is never cut mid-flight. The player's tab goes quiet
(§5.4's NOT WIRED row), and their run is on disk.

**Saves** (T15). Per account, per story, read by the front door straight
from that store's `index.json` (read-only, no bus) through an allowlisted
projection: `save_id`, the slot's **kind** (`auto` or `manual`, never a
manual slot's label), `turn_number`, `updated_at`, `save_version`, and the
size on disk. Never `player_name`, `archetype`, `location_id`,
`evil_phase`, `values`, `thumbnail`, `save.json` or the transcript.
Downloading, restoring or deleting one save from the panel is **NOT WIRED**;
removing an account's saves is delete with purge.

**Stories** (T15). Per story: its state (§14.3, `degraded` included), pid,
loopback port, uptime, crash restarts in the window, last exit code, live
sessions. **Start**, **stop** and **restart**, each drained (§14.3) and each
an operation that answers at once and shows its progress on the page
(`draining`, `restarting`, `done`, or `refused` when turns outlast
`drain_seconds`). A held-down story shows its last exit and when, and
restart clears the hold. Which stories exist is
`hosting.stories` in config; the panel starts and stops them, and a stop
lasts until the next start or supervisor restart.

### 14.9 The model server, its queue, and the settings players cannot change

**Health and models** (T16). The supervisor runs the provider's health
probe (`engine/llm/providers.py`'s `health_probe`, as the doctor does) and
`engine/llm/discovery.py::list_models` on request, cached 10 s, and the
Model server page shows the provider, the base URL, the status and its
detail, latency, the loaded models (id, context, capabilities) and
`llm.declared_models`. The supervisor does it because it holds the
instance's config and serves no turns, so it can re-read config after an
edit (below) without §5.2's hazard; the front door never reads `llm.*`.

**Keys: presence only.** The page says "set, from the environment
(`CLOCKWORK_LLM_API_KEY`)", "set, from a file (`llm_api_key.txt`)" or "not
set", using the doctor's `_check_llm_keys` resolution. Never the value, its
length or any part of it. Setting a key in the panel is **NOT WIRED**: the
environment or a key file, as §2 describes.

**What the panel edits.** A closed allowlist,
`engine/hosting/admin/model.py::EDITABLE`: `llm.provider`, `llm.base_url`,
`llm.lanes.narration`, `llm.lanes.utility`, `llm.context_tokens`,
`llm.prefer_native`, and `llm.profiles.big.{model, temperature,
max_tokens, reasoning_budget, reasoning}`. The rows the Settings panel
already has are validated by its own row table (`engine/api/settings.py`),
reused, not copied; the provider must be a `PROVIDERS` key, the URL an
`http(s)` URL with no userinfo (`user:pass@`), query or fragment, a lane
an integer from 1 to 16. The URL rule is what keeps the allowlist free of
secrets: the base URL is shown on the Model server page and written, old
and new, to the audit log (§14.11), so a credential in it is refused
rather than displayed; a key goes in the environment or a key file (§2).

**Where edits persist: a layer of their own.**
`<storage.root>/hosting/admin.yaml`, "the admin layer", written only by the
supervisor, holding only allowlisted keys.
- Not `config/local.yaml`: that is the owner's hand-kept local-mode file,
  and a rewrite drops its comments (the deferred Settings-panel row).
- Not `CLOCKWORK_CONFIG`: that is the operator's hand-written file on the
  volume; the panel rewriting it would drop comments and fight their edits.
- `get_config` loads it exactly when **hosting is on**, in two passes: it
  merges every other layer, and if `hosting.enabled` is true there (and
  `<data_root()>/hosting/admin.yaml` exists, the root taken from
  `CLOCKWORK_DATA_DIR` or that first pass's `storage.root`), it merges again
  with the admin layer at its rank. The layer cannot turn itself on: `hosting.*` is
  outside its allowlist. The order becomes: `default.yaml` →
  `<CLOCKWORK_ENV>.yaml` → `local.yaml` → **the admin layer** →
  `$CLOCKWORK_CONFIG` → the game overlay. Local mode (hosting off) never
  reads it, so the golden is untouched, and every tool that runs beside
  the instance (the doctor, `launcher.py --check`, `scripts/users.py`,
  `docker compose exec game python scripts/doctor.py`) sees the same
  `llm.*` the instance runs. *Why not a variable only the supervisor sets*,
  as an earlier draft had (`CLOCKWORK_ADMIN_LAYER`): every tool that is not
  the supervisor's child would report a different model server from the
  one serving, and a variable left in the owner's shell would reach a
  later local run.
- The operator's named file wins, as §2.1 argues it should. So a panel
  edit of a key that `CLOCKWORK_CONFIG` also sets is **refused** ("set in
  `<file>`"), not silently shadowed, and the page shows those keys locked
  (the list is `external_config_keys()`, taken after the legacy alias,
  §2.1). `docs/HOSTING.md` tells a Docker operator to set each of these
  keys in one place (§8.1).
- A layer holding a key outside the allowlist, or one that does not parse,
  is a startup error naming it: hand edits are possible, and checked.

**Applying: never in place** (finding 8, the v0.19.0 cache-reset race). On
the admin's `POST`, the front door sends `llm.apply {changes,
apply_anyway}`; the supervisor answers `{op_id}` at once, and the Model
server page follows the operation (`validating`, `draining`, `restarting`,
`done`, `refused`, `rolled_back`) through `ops.list` (§14.3). The `POST`
never waits on a drain. The supervisor, on its operations thread:

1. validates the changes (allowlist, row validation, not set by
   `CLOCKWORK_CONFIG`) and holds them **in memory**; nothing is written
   yet;
2. when the change touches `llm.provider` or `llm.base_url`, runs the
   provider's health probe against the **new** provider and base URL, and
   refuses if it is unreachable ("the new model server does not answer:
   nothing was changed"), unless the admin ticked "apply anyway", which is
   audited in the row's `detail`;
3. pauses new narration admissions for every story (§14.4) and waits until
   no ticket is held in any lane, bounded by `supervisor.drain_seconds`.
   If that runs out, it resumes and records "turns are still running;
   nothing was changed" (audited as refused). Nothing was written, so
   nothing is restored;
4. copies `admin.yaml` to `admin.yaml.prev`, writes the new file
   atomically, re-reads its own config (`reset_config`, safe in a process
   that holds no story and runs no turn) and resizes the lanes;
5. restarts the workers **one at a time**, in `hosting.stories` order:
   each is stopped (already drained), started under the new file, and its
   story's admissions resume once it is `ready`. A worker not `ready`
   within `supervisor.boot_seconds` under the new file sends the
   supervisor back to `admin.yaml.prev`: it re-reads, resizes, restarts
   the workers already restarted, and the rollback is recorded and audited
   (`llm.rollback`).

Until step 4 the committed file is the old one, so a worker that restarts
for any other reason during the drain boots under the config the instance
is actually running, never a split between the two.

**What the rollback covers, and what it does not.** It covers a config
that fails to **boot** (a provider that fails validation at load, say).
It does not cover a model server that is down or a model name it does not
serve: workers do not call the model server while they warm, so such a
worker boots fine and every turn then fails. Step 2's probe is the guard
for the server, and only at the moment of the apply; after that, the Model
server page's health row is where an operator sees it.

Players see their story reconnect, one story at a time. A turn queued and
not yet admitted is answered busy and never started; each session is
rebuilt from its autosave by the client's reconnect `resume`. This is the
only way a model setting changes under live players, and it is why §6.7's
refusal of `POST /api/settings` stands.

*Why a restart and not a reset under a paused queue.* §5.2's thread-safety
claim rests on caches warmed before serving and never reset while serving.
A paused queue stops turns, but not the HTTP reads that hold no lane (the
state, the codex, the quest routes), which would race a reset. A restart
costs a reconnect and a few seconds of warming, for a change an operator
makes rarely.

**The Queue page** (T16) renders `queue.snapshot` (§14.4), refreshed by the
panel's script: per lane, the limit, paused or not, who holds a slot and
for how long, and who waits, in order, with their story and wait so far;
with the recent waits' p50 and p95 once T17's metrics exist.

### 14.10 Logs and metrics: metadata only

**Observability, not moderation.** The store and the panel record how the
service ran, meaning timings, waits, counts, and errors by reference, and
nothing of what was played: no prompt, narration, choice, typed action,
player name, save content, model output, reasoning or log message text is
stored or shown. No field rates, classifies, flags or filters content, and
none can be added: the schema is closed and a test pins it. Rule 12 forbids
the other thing, and this section is written so it cannot grow into it.

**The store** (T17). SQLite (`sqlite3`, the standard library),
`<root>/hosting/metrics.sqlite3`, WAL mode. The supervisor is its only
writer and reader; the front door asks with `metrics.query {name, params,
limit, offset}`, one of a closed set of named queries, so no SQL crosses the
bus, and every answer is a page (§14.2's size rule).

**The events**, in `engine/hosting/metrics_schema.py`. Every field is a
timestamp, a number, an id matching its pattern (`u_[0-9a-f]{12}`, a slug
in `hosting.stories`, an 8-hex reference), a name matching
`^[A-Za-z_][A-Za-z0-9_.]{0,127}$` (`exc_class` and `logger` only: a Python
identifier path, which carries no message text), or a member of a fixed
enum:

| Kind | Fields | Sent by |
|---|---|---|
| `turn` | ts, story, account, admit_wait_ms, duration_ms, outcome (`ok`, `busy`, `error`, `refused_cap`, `refused_rate`) | worker (`run_guarded`, the limits) |
| `lane` | ts, story, account, lane (`narration`, `utility`), wait_ms, hold_ms, outcome (`granted`, `timeout`, `cancelled`, `other_window`) | supervisor (it runs the queue) |
| `session` | ts, story, account, event (`created`, `resumed`, `released`, `swept`, `ended_by_admin`) | worker |
| `login` | ts, account (null for an unknown name), outcome (`ok`, `failed`, `limited`, `disabled`, `must_change`) | front door |
| `error` | ts, process (`frontdoor`, `supervisor` or `worker-<slug>`, the name of its log file; amended in T17 fix round 1), ref, exc_class, logger | worker and front door: `public_error` (§6.6), and a logging handler on ERROR records that keeps the logger's name and the exception's class, never `getMessage()` |
| `process` | ts, process, event (`started`, `ready`, `unhealthy`, `exited`, `restarted`, `held_down`, `stopped`), exit_code | supervisor |

A metric that arrives with an unknown kind, an unknown or missing field,
or a value that fails its pattern is dropped and counted
(`metrics_rejected`, shown on the Errors page), never stored as text.
Sending never blocks a turn: a child queues its metrics on a bounded queue
and drops and counts when it is full. The emitters sit in engine modules
local mode also loads (`engine/scenes/default_scene.py`'s hosted
`run_guarded`, `engine/session/store.py`), so they are **hooks** that
`install()` sets, `None` by default, never imports of `engine.hosting`
(§1's no-import test).

**Retention.** Rows older than `observability.retention_days` are pruned
hourly by the supervisor. Bounded by more than time (T17 fix round 1): a
refusal (`login` `failed`/`limited`/`disabled`, `turn`
`refused_cap`/`refused_rate`) is counted per minute, one row per (minute,
kind, story, outcome), not kept one row each; the supervisor caps each
connection's metric rate (dropped and counted past it); and the file is
capped at `observability.metrics_max_mb`, past which the oldest rows of
every table go first. The named queries aggregate in SQL, one statement at a
time. A store that will not open is moved aside (`metrics.sqlite3.bad-<UTC>`)
and a new one made; if that fails too, the supervisor runs without metrics
(a WARNING, a `metrics.disabled` audit row, a doctor WARN): metrics never
block a start. Log files rotate by size (§14.3), and so does the
audit log, keeping `observability.audit_keep` rotated files (§14.11).

**The pages.** Metrics: turn duration p50 and p95 per story and hour,
admission and lane waits, busy and error counts, and per-account usage
(turns, sessions and active days per day, and the last login). Errors: the
recent `error` rows, so a player's "ref 3fa9c2e1" is found, and its full
traceback read in that process's log file on disk; the log text is not
shown. And each story's Oracle numbers (`oracle.snapshot`), which is where
`/api/metrics`' numbers went (§6.7). The Oracle's `metrics()` and
`recent()` do **not** hold only numbers: `unearned_claims` is keyed by
whatever stat name the model claimed (`engine/agents/governance.py`),
`TurnRecord.evil_progress` is play state, and `assistant_intent` and
`challenge_kind` are free strings (`engine/telemetry/oracle.py`). So
`oracle.snapshot` passes through a projection in `metrics_schema.py`
before it leaves the worker:

- counts, latencies and totals, as numbers;
- rule ids only if they match `^[A-Z]\d{3}$`;
- `unearned_claims` collapsed to a count and a largest delta, with no stat
  names;
- `challenge_kind` and `assistant_intent` only when each is a member of an
  enum built from the engine's own tables (the registered challenge kinds,
  the Assistant's intents), and otherwise counted as `other`;
- no `evil_progress`, and nothing else from a turn's state.

The projection's key set is pinned beside the schema's, and the sentinel
test has the scripted model claim a stat named with the sentinel
(§9.10).

Local mode has none of this; its Oracle and `/api/metrics` are v0.19.0's.

### 14.11 The audit log

**Decision.** `<root>/hosting/audit.jsonl`, one JSON object per line,
appended by `engine/hosting/audit.py`, its only writer, under an
operating-system file lock on `audit.jsonl.lock` (`fcntl.flock`,
`msvcrt.locking`): the `users.json` mechanism as T7 fix round 1 left it,
since an `O_CREAT | O_EXCL` lock file left by a killed holder can be broken
only by racing the next holder, and its own lock, never the accounts'
(amended in T14 fix round 1). Its callers:
the panel (the front door), `scripts/users.py` (actor `cli`) and the
supervisor (actor `supervisor`: a hold-down, a rollback).

A closed field set: `ts`; `actor` (an account id, `cli` or `supervisor`);
`actor_name`; `address` (the front door's resolved client address, empty
for the other two); `action` (one of `account.create`, `account.disable`,
`account.enable`, `account.reset_password`, `account.delete`,
`account.set_admin`, `account.passwd`, `session.end`, `story.start`,
`story.stop`, `story.restart`, `story.held_down`, `llm.apply`,
`llm.rollback`, `admin.reauth`, `admin.reauth_failed`,
`metrics.disabled`); `target` (an
account id, a slug, a session reference or the dotted keys); `detail` (for
`llm.apply` each key's old and new value, since the allowlist holds no
secret and a base URL cannot carry a credential, §14.9; otherwise the
options chosen, like `purge: true` or `apply_anyway: true`); `result`
(`started`, `ok`, `refused`, `error`); `ref`. Never a password, a
generated password, a hash, a key's value, or play text.

**No action without its row.** An action that changes something appends
its row with `result: started` **before** it acts; if that append fails
(a full disk, a lock it cannot take), the action is refused with an error
page and nothing changes. The outcome is appended after, as a second row
with the same `ref` (`ok`, `refused` or `error`). A request refused before
it starts (a failed validation, a guard) is one `refused` row. So the log
can hold a `started` with no outcome, when the process died mid-action,
but never an action with no row.

It rotates by size (T14 fix round 1): past `observability.audit_max_mb` the
file becomes `audit.jsonl.1` (the older ones shifting up) and at most
`observability.audit_keep` rotated files are kept, the oldest deleted. The
Audit page reads only a bounded tail, newest first, across the current and
rotated files, a page at a time, filtered by action or actor, and goes back
at most `AUDIT_MAX_ROWS` rows (a filtered view searches at most
`FILTER_SCAN_BYTES` and says "older rows not searched", T14 fix round 2); the operator archives older files by hand
(`docs/HOSTING.md`).

### 14.12 Security, together

- **Reach.** The outside reaches the front door only. Workers and the bus
  listen on `127.0.0.1` (in the image, the container's loopback). A worker
  trusts forwarded headers only with the proxy token, and deletes them
  without it; the bus refuses a connection without a live, unused token of
  its own, and gives each connection only the ops its role may call
  (§14.2). A client never speaks HTTP to a worker over a WebSocket: the
  front door relays messages, not bytes (§14.5).
- **The cookie.** The front door is its only writer (§6.2); a logged-in
  form's CSRF token is stateless and dies with the epoch (§6.3).
- **Enumeration.** `tests/test_admin_access.py` does for `/admin` what
  T7's gate test does for players (§9.10), and §9.4's crawl is extended to
  the front door and the panel: a non-admin gets only the fixed refusals,
  and an admin's crawl finds no API key, cookie key, hash, password or bus
  or proxy token.
- **Rate limits.** Logins and re-auth (the front door's two login
  buckets), actions (per worker), admin actions (the panel).
- **The audit log**, and the panel's headers (§14.7).

### 14.13 NOT WIRED

Each is a row in `docs/GOVERNANCE.md` naming its file, added by the task
that builds the file:

1. Workers on another host; the bus beyond loopback
   (`engine/hosting/bus.py`).
2. More than one worker process per story
   (`engine/hosting/supervisor/process.py`).
3. Two stories open in two tabs of one browser at once
   (`engine/hosting/frontdoor/stories.py`). A switch moves every tab's
   HTTP to the new story, while a WebSocket already open stays on the old
   story's worker; and the client's resume key (`clockwork_save_id`, one
   `localStorage` entry per origin, `ui/src/core/socket.js:48`) keeps only
   the story played last, so the other loses auto-resume. A per-story
   Socket.IO path, with the client told its prefix, is v0.21.0's way out
   (§14.5).
4. The admin panel inside the React client (`engine/hosting/admin/`).
5. Two-factor login for admins, and a network allowlist for `/admin` in the
   engine (`engine/hosting/admin/guard.py`).
6. Setting `llm.api_key`, or any secret, in the panel
   (`engine/hosting/admin/model.py`).
7. Editing anything outside the `llm.*` allowlist in the panel (`hosting.*`
   and `hosting.stories` among them, `stack.*`, speech, images)
   (`engine/hosting/admin/model.py`).
8. Downloading, restoring or deleting a single save in the panel
   (`engine/hosting/admin/saves.py`).
9. Telling a player that an admin ended their session or that their story
   restarted: a client event, for v0.21.0 (`engine/scenes/default_scene.py`).
10. Metrics export (Prometheus, OpenMetrics) and alerting on a crash loop
    or a held-down story (`engine/hosting/supervisor/metrics.py`).
11. Memory and CPU figures per process on the Stories page
    (`engine/hosting/supervisor/process.py`).
12. Archiving the rotated audit files elsewhere, or reading past
    `AUDIT_MAX_ROWS` in the panel (`engine/hosting/audit.py`). (Rotation
    itself was built in T14 fix round 1.)
13. Restarting the supervisor itself: the container's or systemd's restart
    policy does it (`engine/hosting/supervisor/__main__.py`).

Not debt, and not rows: a view of play text, log text or save contents in
the panel. §14.10 rules them out.

## Acceptance

- `pytest` fully green on Windows and in the Linux container, with no
  xfail. Each environment's skip set is the one §3.9 writes down.
  `npm test --prefix ui` is green, and `dist` is untouched.
- The local-mode golden and v0.19.0's LM Studio golden are identical at
  every task, bar exactly §1's two sanctioned differences (the bind, and
  `paths.saves` leaving the games payloads), each asserted to apply.
- With hosting on: every §9.3 and §9.4 assertion holds, every socket event
  is guarded, and two real browsers logged in as two accounts cannot see
  each other's runs (T18's smoke test).
- With the supervisor: every §9.10 assertion holds; one login reaches every
  story the instance runs; the queue is one queue across every worker; no
  `/admin` route answers a non-admin with anything but its fixed refusal;
  every admin action has an audit row; and the sentinel test finds no play
  text on any admin surface, metrics row or audit line.
- The module-state inventory test holds, and item 12's races are fixed.
- The image builds, runs as non-root, holds no secret, refuses local mode,
  and serves a streamed turn under gunicorn.
- vLLM either verified live on the RTX 2060, with its cells and fixtures
  marked, or recorded as not runnable on sm_75, with the versions tried and
  the reason, in the CHANGELOG, CLAUDE.md and `docs/MODEL_SERVERS.md`.
- `tests/test_reachability.py`: no new allowlist row.
- Rule 12: no key, prompt line, route or document introduced by this
  release rates, filters or moderates content. The closed `hosting:` schema
  test holds, the closed metrics schema test holds, and `max_input_chars`
  is a length, nothing more.
