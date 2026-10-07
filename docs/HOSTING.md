# Hosting and platforms

How to run The Clockwork Dark somewhere other than the Windows workstation it
grew up on (v0.20.0): **§ Linux**, **§ Hosted mode: what it is and is not**
(and **upgrading**), **§ Accounts** (with ownership, one live run per player,
the shared model server and the limits), **§ Orchestration** (the
supervisor, its workers, the front door players reach them through, the
reverse proxy in front of it, the WebSocket relay, gunicorn on Linux and the
model server's one queue for every story), **§ The admin panel** (its first
admin, re-auth, Users, Sessions, Saves, Stories, the Model server and its
apply, the Queue, Metrics and Errors, and the audit log), **§ Docker** (the
image, Compose with several stories in one container, `/data` and its
ownership, reaching a model server from a container), **§ Configuration**
(the layer order, the admin layer, the doctor's hosted rows) and **§ What
hosted mode turns off**.

- [Linux](#linux)
- [Hosted mode: what it is and is not](#hosted-mode-what-it-is-and-is-not)
- [Accounts](#accounts)
- [Orchestration](#orchestration)
- [The admin panel](#the-admin-panel)
- [Docker](#docker)
- [Configuration](#configuration)
- [What hosted mode turns off](#what-hosted-mode-turns-off)

---

## Linux

Windows and Linux are both supported (AGENTS.md rule 11). Nothing in the
engine assumes a path separator, a drive letter, a case-insensitive
filesystem or an `.exe`, and `tests/test_portable_paths.py` checks the
content's own paths for the same on every platform, so a case slip made on
Windows fails the suite there before it reaches a Linux host. Other POSIX
systems, macOS included, should work but are untested: only Linux was run.

### Start

```sh
./scripts/start.sh
```

`scripts/start.sh` is `scripts/start.ps1`'s POSIX twin, line for line. It
creates `.venv` with `python3.11` (or `python3`, if that is 3.11 or newer;
otherwise it stops and says so), installs `requirements.txt` under
`constraints.txt`, runs the suite, and prints the same next steps with
`.venv/bin/python` where the Windows script says `.\.venv\Scripts\python.exe`.
`tests/test_start_scripts.py` keeps the two scripts' next steps the same.

**Debian and Ubuntu:** install the venv package first,
`sudo apt install python3.11-venv` (for the Python you use). Without it,
`python3 -m venv` fails at ensurepip after half-making `.venv`. `start.sh`
checks for that: a failed creation removes the half-made `.venv` and names
the package. An existing `.venv` is never replaced for you: one whose Python
does not run, is older than 3.11, or has no pip is refused, with the reason,
and you remove it yourself.

`constraints.txt` pins what the suite was proven green on (the Windows `.venv`
plus, for the few distributions only Linux installs, the container run below).
Install with it everywhere:

```sh
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
```

The doctor's `platform` row (`scripts/doctor.py`, under Runtime) names the
system and its release (Windows 11 by its build, since it reports itself as
"10"), and whether the filesystem under the checkout is case-sensitive,
probed in a temporary directory it makes in the repository root and removes
(on a read-only checkout, under the storage root instead, and the row says
which it probed).

### Services on Linux

What the engine ships runs on Linux unchanged. Everything else is an external
service reached by URL, and none of it is started, installed or measured by
v0.20.0: each keeps its `enabled: false` default.

| Service | Engine side | On Linux |
|---|---|---|
| Model servers | `engine/llm/` (v0.19.0) | LM Studio has a Linux AppImage; llama-server, Ollama and vLLM are native. vLLM was verified live in v0.20.0, in its Docker image (docs/MODEL_SERVERS.md § vLLM) |
| STT: faster-whisper | in process, optional | pip wheel, CPU or CUDA (CTranslate2); unchanged. Its versions are pinned in `constraints.txt` from the Linux run |
| STT/TTS: Voxtral | `stack.services.voxtral_*`, by URL | the Rust servers build from source (`cargo build --release`). The shipped commands carry no `.exe` (`target/release/tts-server`, `target/release/voxtral`), so the Linux build is found by name, and on Windows the stack tries each `PATHEXT` suffix and finds `tts-server.exe` as before |
| ComfyUI | by URL, `manage: true` runs `python main.py` | native; set `command: python3` where `python` is absent (documented, not defaulted) |
| Grok image CLI | subprocess | whatever the CLI supports; not verified here |

LM Studio's `mcp.json` (the optional tool layer, `llm.mcp`) is looked for in
`~/.cache/lm-studio/` and then `~/.lmstudio/`, the same two places as on
Windows (`tests/test_mcp_json_posix.py`).

### Running the suite in a Linux container

This is how the Linux suite was run on the Windows workstation for v0.20.0.
Two things shape it:

- **The suite does not run on the bind mount.** A Docker Desktop bind mount of
  an NTFS directory is case-insensitive inside the container, which is the
  very property the Linux run exists to test, and its file sharing is slow for
  a small-file-heavy, SQLite-using suite. So the checkout is mounted
  **read-only**, only as a clone source, and the suite runs on a clone in a
  named volume, on the container's own case-sensitive filesystem.
- **It runs the committed `HEAD`.** The clone carries `.git`, so the tests
  that read history run rather than skip. Commit first; after a fix,
  `git -C /work/repo pull` and run again.

The image is pinned by digest. Run the commands from the checkout's root:
`"$PWD"` is it in `sh`; in PowerShell write `${PWD}` instead, and put the
`docker run` on one line (or end its lines with a backtick). From Git Bash,
set `MSYS_NO_PATHCONV=1` first so `/src` and `/work` are not rewritten as
Windows paths.

```sh
docker volume create cwd-linux-work
docker run -d --name cwd-linux \
  --mount type=bind,source="$PWD",target=/src,readonly \
  --mount type=volume,source=cwd-linux-work,target=/work \
  python:3.11-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b \
  sleep infinity

docker exec cwd-linux sh -c 'apt-get update && apt-get install -y --no-install-recommends git'
docker exec cwd-linux git clone /src /work/repo
docker exec -w /work/repo cwd-linux python -m venv .venv
docker exec -w /work/repo cwd-linux .venv/bin/python -m pip install -r requirements.txt -c constraints.txt
docker exec -w /work/repo cwd-linux .venv/bin/python -m pytest tests -q -rs
```

Docker Desktop shows the bind mount as owned by root, the container's own
user, so git clones from it with no `safe.directory` entry. If git ever
answers "detected dubious ownership" there (another engine, a rootless
setup), name it safe inside the container only, in the container's own
`~/.gitconfig`: `docker exec cwd-linux git config --global --add
safe.directory /src`. Never on the host.

`-rs` lists every skip's reason. A fresh clone skips what the owner's
checkout skips (the stamina soft-lock test, the live model-server module) plus
the Garden test that reads the gitignored `Design_files/`. The measured run,
with its pass count, skips and time, is in CLAUDE.md's status.

The client build is checked the same way, in
`node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0`,
against a second clone in the same volume (so the suite's clone is not
rebuilt under it):

```sh
docker exec cwd-linux git clone /work/repo /work/repo-node
docker run --rm --mount type=volume,source=cwd-linux-work,target=/work \
  -w /work/repo-node \
  node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 \
  sh -c 'npm ci --prefix ui && npm test --prefix ui && npm run build --prefix ui'
docker exec -w /work/repo-node cwd-linux git diff --exit-code content/scenes/clockwork/static/dist
```

Measured in v0.20.0 T4: every file Vite writes was byte-identical to the
committed Windows build except `dist/index.html`, whose committed copy
carried the CRLF of a Windows checkout's `ui/index.html`. Since T5 both are
LF in every working tree (`.gitattributes`) and `dist` was rebuilt, so the
diff above is expected to be empty; CI's `client` job
(`.github/workflows/ci.yml`) runs the same diff.

The same checks run in CI (GitHub Actions, `ubuntu-latest`) once the
workflow is pushed: the suite on Python 3.11 installed with
`-c constraints.txt`, and the client's install, tests, build and that diff.
No secret and no model server is needed: the suite's child processes run
under a sandbox config on the discard port (AGENTS.md "Tests").

When done: `docker stop cwd-linux && docker rm cwd-linux`, and
`docker volume rm cwd-linux-work` to drop the clone. The images stay until
removed with `docker image rm`.

---

## Hosted mode: what it is and is not

**What it is.** One host serving your stories to a small group of people you
made accounts for: the login guards every HTTP route and every Socket.IO
event, every run and save belongs to one account (§ Ownership and errors),
the players share the model server through one queue in arrival order, and
every account is held to an action rate, input caps and a connection count
(§ Sharing the model server, § Limits). A supervisor runs one worker
process per story behind one front door (§ Orchestration); on Linux every
process runs under gunicorn, on Windows on Werkzeug's development server (a
trial: the doctor WARNs), and the Docker image runs the whole instance in
one container (§ Docker). An admin manages it from `/admin` (§ The admin
panel). Put it behind a TLS reverse proxy (§ Reverse proxy).

**What it is not** (each a NOT WIRED row in docs/GOVERNANCE.md where it is
debt rather than a choice):

- **Public-internet scale.** One host, one process per story, a handful of
  players. Several workers for one story, workers on another host, sticky
  sessions and a message queue are not built.
- **Self-service accounts.** No sign-up page, invite link, OAuth/SSO or
  reverse-proxy header login: the operator makes accounts
  (`scripts/users.py`) or an admin does in the panel.
- **Per-player settings.** The Settings panel describes the machine and is
  read-only hosted; the model server's settings are the admin's.
- **Several stories in one process**, or **one instance under a URL
  sub-path**: the client fetches `/api/...` and connects Socket.IO at the
  root, so an instance owns the root of its host name.
- **A view of what was played, or any moderation.** The panel, the metrics
  and the audit log hold metadata only (below), and nothing rates, filters
  or moderates what a player writes (AGENTS.md rule 12).
- **TLS in the engine** (your proxy terminates it), **two-factor login**,
  **editing a secret in the panel**, and **a published image** (it is built
  locally and in CI, never pushed).
- **New UI for the server's own pages.** The login, account, picker and
  admin pages are server-rendered. A player's place in the queue is not
  shown (docs/GOVERNANCE.md). Since v0.21.0 the game page reconnects on its
  own after the server closes its socket or goes away (§ When the
  connection drops).

**What the operator can read, and what the panel shows.** It is your
server: every save, transcript and log file under `storage.root` is
readable on disk, and a player's error reference leads to its traceback in
that process's log (§ Metrics and errors). Generated pictures and spoken
lines are one shared cache (§ Ownership and errors). The admin panel, the
metrics store and the audit log deliberately carry none of it: no prompt,
narration, choice, typed action, player name, save content, model output or
log text -- ids, times, counts, states and enum values only, under closed
schemas a test pins (`tests/test_admin_no_play_text.py` plays a sentinel
through every surface and finds it on none). An API key and the cookie key
are shown only as set or not, and where from.

### Upgrading

Stop the instance, update the checkout (or rebuild the image), and start it
again; the data under `storage.root` (`/data` in the image) carries over.

- **From local play (v0.19.0 or earlier).** Saves stay where they were
  (`data/saves/<slug>/`, the default `storage.root`). To make them an
  account's, run `python scripts/users.py adopt <name>` (optionally
  `--game <slug>`) with the game stopped (§ Making accounts).
- **`paths.saves`** in `config/local.yaml`, an environment layer, a
  `CLOCKWORK_CONFIG` file or the admin layer is refused at startup since
  v0.21.0: `"paths.saves" is no longer read (v0.21.0). Saves live under
  storage.root as <root>/saves: set storage.root (or CLOCKWORK_DATA_DIR) to
  the folder that holds your saves folder, or move the saves there.` A
  story's `game.yaml` that still declares `saves:` plays, with an advisory:
  delete the line.
- **The `lmstudio:` config block** is refused at startup since v0.21.0: `the
  "lmstudio:" block was renamed "llm:" in v0.19.0 and is no longer read
  (v0.21.0). Rename the block; "ttl_seconds" inside it is now
  "keep_alive_seconds".` Likewise `stack.services.lmstudio` (renamed
  `stack.services.llm`). The supervisor refuses to start, naming the file;
  the `engine.lmstudio` import path is gone (use `engine.llm`).
- **Local mode now binds `127.0.0.1`.** To keep LAN play, set
  `scene: {clockwork: {host: "0.0.0.0"}}` in `config/local.yaml` (README §
  Play), or serve the group through hosted mode.
- **Install with the constraints**: `pip install -r requirements.txt -c
  constraints.txt` (and `-r requirements-server.txt` for gunicorn on
  Linux), so the versions are the ones the suite was proven on.
- **Docker**: `docker build -t clockwork-dark .` then `docker compose up -d
  game` replaces the container and keeps the `clockwork-data` volume. Run
  `docker compose exec game python scripts/doctor.py` after.

---

## Accounts

Hosted mode is **off** by default (`hosting.enabled: false`), and then none
of it exists: `engine/hosting/` is never imported. Turn it on in
`config/local.yaml` or in a file named by `CLOCKWORK_CONFIG`:

```yaml
hosting:
  enabled: true
  public_origin: "https://play.example.org"   # the address players type; "" = same origin only
  trusted_proxies: 1                           # reverse proxies in front; 0 = none
```

The `hosting:` block is a **closed schema** (`engine/hosting/config.py`,
defaults and comments in `config/default.yaml`): an unknown key, a wrong type
or a value out of range stops the server at startup with the key named. It
holds the service's knobs and nothing that judges what a player writes
(AGENTS.md rule 12). `threads` is each process's pool: gunicorn's threads
on Linux, the front door's long holds and every process's HTTP turn slots
(§ Limits), and the doctor's sizing row.

### Making accounts

There is no sign-up page. The operator makes every account:

```sh
python scripts/users.py add alice           # asks for the password twice
python scripts/users.py add root --admin    # an admin: how the first admin is made
python scripts/users.py admin alice on      # grant (or `off`: revoke) the admin role; every login of alice ends
python scripts/users.py passwd alice        # a new password; every login of alice ends
python scripts/users.py disable alice       # refuse alice's logins; every login ends
python scripts/users.py enable alice
python scripts/users.py list
python scripts/users.py remove alice [--purge]      # --purge deletes alice's saves (asks first)
python scripts/users.py adopt alice [--game <slug>] # move YOUR local runs into alice's saves
```

A name is 2 to 32 characters of `a-z`, `0-9`, `_` and `-`; a password is at
least 10 characters, with no other rules. Passwords are read with `getpass`,
never from the command line, the environment or a file. The script works on a
running server, and every change it makes is written to the audit log first,
as the actor `cli` (§ The admin panel); a change whose row cannot be written
is refused. Revoking, disabling or removing the last enabled admin asks you
to type its name first.

Accounts live in `<storage.root>/hosting/users.json` (`data/hosting/` by
default, or under `CLOCKWORK_DATA_DIR`). Each has an id minted at random
(`u_` and 12 hex digits), which is the only thing ever used in a path, a
scrypt password hash (Werkzeug's), the admin role, `must_change` (a password
an admin generated, § The admin panel), and an **epoch**: a password change,
a reset, a disable or a change of role raises it (and a removal ends the
account outright). Every login
made under an older epoch ends: a browser on its next request, and an open
game connection at once (§ Ownership and errors). `engine/hosting/accounts.py` is the file's only writer; every
change is a read-modify-write under an operating-system lock on
`users.json.lock` beside it, so the CLI and a browser changing passwords at
once cannot lose either change. The system frees that lock when its holder
exits or is killed, so nothing is ever left locked (the file itself stays;
it is harmless). No backup of `users.json` is kept: it would hold the hashes
a password change retires.

**Who can read these files.** On Linux and other POSIX systems the hosting
folder is made `0700` and every file in it (`users.json`, the lock files,
the cookie key) `0600`, so only the account that runs the server can read
them. On Windows the files take the permissions (ACLs) of the folder they are
made in, normally inherited from your user profile. Keep `storage.root`
(`data/` in the checkout by default) in a folder only your account can read:
check it with `icacls data\hosting` (it should list your account, SYSTEM and
Administrators, and no group such as `Users` or `Everyone`).

`adopt` moves the local player's runs (`<root>/saves/<slug>/`) into the
account's (`<root>/users/<id>/saves/<slug>/`), one story or all: a rename,
or across two volumes (a Docker volume, say) a copy checked file by file and
only then removed, never a duplicate. It refuses the whole move if any save
id is already there. It takes the hosting folder's `adopt.lock` while it
works: it refuses while a hosted server is running (each holds a
`server-*.lock` there), and a hosted server started meanwhile refuses to
start until it is done. **Run it with the game stopped**, the local game
included, whose autosave writes the folder being moved. If a move across
volumes is interrupted (a file the local game holds, say), exactly one
complete copy is left and the message says what happened; run `adopt`
again to finish. Without it your local runs are not visible to any account.

**Keep `storage.root` on a local disk.** The accounts lock and the server
locks are the operating system's file locks, which are unreliable on network
file systems (NFS, SMB/CIFS shares): two writers could both believe they hold
the lock. A Docker volume on the host's own disk is fine.

### Logging in

Under the supervisor these pages are the **front door's** (§ The front
door): a player logs in once there, and every story's worker reads the same
cookie and never writes it.

Players log in at `/login` and change their own password at `/account` (the
current password and the new one twice; every other browser of theirs is
logged out, the one they used is not). The game page shows an **Account**
link and a **Log out** button in its top corner. Without a login, `GET /`
redirects to `/login` and every other route answers `401 {"error": "login
required"}`; only `/api/health`, `/login`, `/logout` and `/static/*` are
open, and the media, art and audio routes are not.

The login is Flask's signed cookie, `clockwork_session` (`HttpOnly`,
`SameSite=Lax`, `Secure` unless `hosting.cookie_secure: false`), valid for
`hosting.session_days` (14) after the last login or password change. It is
signed with `hosting.secret_key` (`CLOCKWORK_SECRET_KEY` by default), which
must be at least 32 characters, must not be one shorter pattern repeated, and
must use at least 16 different characters, or 10 for a hex key of 64 digits or
more, as `openssl rand -hex 32` prints (a shorter or repetitive key, such as
`changeme` four times, stops startup:
anyone holding one captured cookie could find a weak key offline and forge a
login for any account). Make one with `python -c "import secrets;
print(secrets.token_urlsafe(32))"`. Left empty, a 32-byte key is generated once
into `<storage.root>/hosting/secret_key` (0600 on POSIX; on Windows, the
folder's ACL, above). Deleting that file logs everyone out.

**Logging out ends this browser only.** The cookie is signed, not stored on
the server, so a copy of it taken before logout (from the browser's storage,
say) keeps working until `hosting.session_days` after it was issued. What
ends every copy at once is the account's epoch: change the password
(`/account`, or `users.py passwd`) or disable the account. That also closes
every game connection the account has open, in every tab; logging out does
not close a connection another tab already has open (it keeps playing until
that tab is closed or the epoch changes).

What protects the login:

- a wrong name, a wrong password and a disabled account get the same answer
  and the same scrypt work, so the page cannot be used to find out who has
  an account;
- attempts are limited to `hosting.rate_limits.logins_per_minute` (5) per
  address, where an IPv6 address counts by its /64 (a client owns the whole
  prefix); to half that (3) per address and name, so one address guessing
  one name is stopped first; and, for every address with a failed login in
  the last minute, to `rate_limits.logins_per_minute_all` (60) between them
  all, so guessers spread over many addresses share one small allowance. An
  address with no recent failure is exempt from that one, so a flood of
  guesses never stops a player who types their password right. Never per
  name alone, so nobody can lock a friend out by typing their name;
- at most `hosting.max_concurrent_logins` (4) password checks run at once,
  each about 32 MiB and a tenth of a second of scrypt, so a flood of logins
  cannot take every core and the memory from the players' turns; an attempt
  that finds them all busy waits up to two seconds, then gets the same "too
  many attempts" answer as the limits above;
- a failure is logged with the name and the address, never the password;
- every form carries a CSRF token, and any `POST`, `PUT`, `PATCH` or
  `DELETE` whose `Origin` (or `Referer`) is neither this request's own
  origin nor `hosting.public_origin`, scheme included (`http://` is not
  `https://`), is refused;
- Socket.IO checks a browser's origin (the same origin, or
  `hosting.public_origin` when it is set), caps a message at 64 KiB, refuses
  a connection without a login, and re-checks the account on every event
  (§ Ownership and errors).

What the login limits still allow, by design:

- **a slow guesser.** The server-wide allowance counts only addresses with a
  failed login in the last minute, so a guesser who waits a minute after
  each failure is never counted in it: about one guess a minute from each
  address (each IPv6 /64), and still bound by the per-address and
  per-address-and-name limits. A long password is what defeats that;
- **the price for a mistyper.** A player who has just mistyped their
  password counts with the guessers for a minute, so while guessers have
  spent the server-wide allowance, that player's next try may be refused
  ("too many attempts") until the minute is up.

**Plain HTTP.** With `cookie_secure: true` (the default) the browser keeps
the cookie only over HTTPS, so a login over `http://` would fail silently.
The login page says so instead, naming `hosting.cookie_secure`. For a trial
on a private network without TLS, set it to `false`, and back to `true`
before anyone else can reach the server.

**Behind a reverse proxy**, set `hosting.trusted_proxies` to the number of
proxies in front (usually 1) and `hosting.public_origin` to the address
players type (§ Reverse proxy). With `trusted_proxies: 0` the forwarded
headers are ignored and deleted: every player then shares the proxy's
address, so one person's failed logins lock everyone out, and the server
logs one WARNING the first time a request carries `X-Forwarded-For`. The
public name is also added to the server's Host allowlist, so the proxy may
pass it on as the `Host`.

### Ownership and errors

**Every run and every save belongs to one account.** A game started or a
save loaded is owned by the account that did it, and saves live in that
account's own folder (`<storage.root>/users/<id>/saves/<story>/`). Every door
that names a session or a save asks whose it is, the owner coming from the
login cookie and never from the request: `GET /api/game/state`, `POST
/api/game/choice`, the save routes (`GET`/`POST /api/saves`, `POST
/api/saves/<id>/load`, `DELETE /api/saves/<id>`), `POST
/api/voice/transcribe`, the story's screens, and the socket's
`join_session`, `player_choice` and `resume`. Another player's id is
answered **exactly** as an id that does not exist -- the same status and the
same words -- so ids cannot even be probed for existence. The story's
screens that also work without a run (the codex, items and recipes) answer
another player's id with the same story-wide view a request with no run
gets. A socket joins a run's room (where its turn is streamed) only after
the run is found and found to be the player's own. A request that somehow
reached a run door with no owner set is refused, not served.

**The socket door.** Every Socket.IO handler is registered through one
wrapper (`FlaskScene.on`, `engine/hosting/sockets.py`): a connection without
a login is refused, and on every event the account is read again. A
password change, a disable or a removal closes every open connection of the
account **at once**, including one that sends nothing and only listens to a
run's story as it streams. Under the supervisor the `/account` page is the
FRONT DOOR's, and every game connection passes through its relay (§ The
front door), so the front door closes them itself: a change made there
closes every relayed connection of the account at once, and each relayed
connection re-reads its login every 2 seconds, which catches a change made
by another process (`scripts/users.py`). Inside the story, every
connection in a run's room is also checked against `users.json` before each
piece of a turn is sent, and a stale one is closed before it receives it.
(Without the supervisor, a single hosted process hears its own `/account`
page directly.) (The player who changed their own
password has their game connections closed too: the game page's banner
says "Your login has ended. Taking you to sign in…" and takes them to `/`
once, where they log in again and the page resumes the run. Another tab of
the same account does the same; a page that is sent back to sign in twice in
a minute stops and offers "Sign in again" instead of looping.) One residual: the check and the send are two steps, so a change
another process makes in the instant between them lets exactly one piece of
the turn (one fragment of narration) through before the next check closes the
connection. A test walks every registered
event in every namespace and fails if one was registered around the wrapper.

**Errors name nothing internal.** In local mode a failure's words (a model
server's address, a file path, an exception) go to the owner's own screen.
Hosted, a player sees a generic sentence with a reference instead -- "The
turn could not be completed (ref 3f9a1c2b)", "Transcription failed (ref
...)", "The request could not be completed (ref ...)" -- and the server's log
holds the full exception under the same reference, so a player can quote it
and you can find it. The speech-to-text server's own reply (`raw`) is never
passed on. A save from a newer version of the game keeps its own message,
which tells the player why it will not load; a missing save, or one that is
not theirs, gets the missing save's. `GET /api/settings` omits the path of
the server's config file. A test drives every route and socket event, normally
and with the model server down, speech-to-text failing and broken saves, and
checks no answer carries a key, a password hash, a server address, an
exception's name or another account's details.

**Media is a shared cache.** Generated pictures and spoken lines are named by
a hash of what was asked for, so two players who ask for the same one share
a file; the media routes need a login, and any logged-in player can fetch a
generated file whose name they know (per-player media folders are not
built). And as the operator you can read every save and transcript on disk:
it is your server.

**Running it.** `python launcher.py` with hosting on runs the supervisor in
the foreground -- a worker per story and the front door, under gunicorn on
Linux when `requirements-server.txt` is installed, otherwise on the
development server with a WARNING (§ The supervisor on a Linux host, §
Docker). A startup refusal is printed with its key and exits
1. `python launcher.py --check` adds a row for the front door's `GET
/api/health` and the path of the instance's logs.

**A Socket.IO connection id is not bound to the account that opened it
(NOT WIRED; `engine/scenes/flask_scene.py`, `engine/hosting/ws_relay`).** The
socket guard re-reads the account on every Socket.IO *event*, but an Engine.IO
transport request (a polling `GET`/`POST`, or a WebSocket upgrade) that names
a connection id is served to whoever presents a live cookie. The id's
randomness (about 120 bits) is the only barrier, and the shipped client
connects WebSocket-only, so no id appears in a URL. Polling is not disabled
server-side in hosted mode: if your reverse proxy logs query strings, those
logs hold live connection ids, so keep them private. Binding an id to its
account, or serving WebSocket only, is later work (docs/GOVERNANCE.md).

### One live run per player

Each account has **at most one live run** in a server. Starting a new game
or loading a save (from the menu, or the page's own reconnect) first
releases the player's other run: it is saved already (every turn autosaves),
so nothing is lost, and the old browser tab stops receiving it (it is taken
out of the run's channel before the new tab joins). If that other run's turn
is still being narrated, the new request is refused with 409, "A turn is
still running in your other window." -- wait for it, or play on in that
window. Loading the save the live run came from rebuilds the same run, and
the released copy can never save over it. The old tab is told why (since
v0.21.0, § When the connection drops): "This run is open in another
window." with **Play here**, which takes the run back -- and releases it
from the other window in turn.

A run nobody touches is released after `session.idle_ttl_minutes` (60 by
default; hosted mode always sweeps, whatever `session.idle_sweep_enabled`
says). The sweep runs when a game connection closes (whatever `disconnect`
handler a story adds), at most once a minute on any request, and when a run
is started; it never releases a run whose turn
is in progress. The page that held it says "This session was ended. Your
run is saved." with **Resume**, which reopens it from the autosave. Each server therefore holds at
most one run per player in memory, and each player has at most one turn in
flight, which is what makes the queue below fair.

### When the connection drops

The game page (v0.21.0, `ui/src/core/link.js`) keeps one connection state
and says it in a banner under the header; the controls are off in every
state but a live one with no turn running, so a press never reaches a
socket that is down.

- **The server or the network went away** (a restart, a story restarted
  from the admin panel, a blip): "Connection lost.", with **Try now**. After
  five failed attempts, "The server is not answering."; while the front door
  answers 503 for that story the banner adds its words, "(story
  unavailable)". When the connection is back the page **rejoins** its run
  ("Reconnected — picking up your run…"). If the run's worker kept it, the
  page picks up where it was, including a turn that finished meanwhile; if
  a turn is still being narrated, "Your move is still being played…" until
  it lands. If the worker was restarted, the join misses and the page
  resumes the run from its autosave ("Opening your run…"); the prose of a
  turn that finished during the restart is not recovered, its effects are
  (docs/GOVERNANCE.md).
- **The login ended** (a password change, a disable, a removal, an expired
  cookie): the page checks `/api/games/active`, says "Your login has ended.
  Taking you to sign in…" and goes to `/` once. A page sent back twice in a
  minute stops there and offers **Sign in again**.
- **Too many windows** (`hosting.max_connections_per_account`): the front
  door refuses the extra WebSocket with an HTTP 429 the browser cannot
  read, so the page learns why from its login check instead:
  `/api/games/active` answers 429 with the cap's words while the account
  holds its cap, and the banner shows them (as "Connection lost. (…)" on a
  page with a run to rejoin). The page keeps retrying until a window is
  closed, and never navigates.

- **The run was released by the server** (v0.21.0, spec §6.5): before it
  closes a released run's channel the server tells it
  `session_ended {"reason", "session_id"}`, and the tab that held the run
  says why. `elsewhere` -- the same account began or loaded a run in
  another window (one live run per player) -- reads "This run is open in
  another window." with **Play here**; `ended` (an admin's **End session**)
  and `idle` (the idle sweep) read "This session was ended. Your run is
  saved." with **Resume**. Either button resumes the run from its autosave.
  Nothing happens by itself after it: an automatic resume would release
  the other window, whose own would release this one. A tab that pressed
  Begin or Load has already left its old run, so the event about that run
  is ignored there, and the new run goes live on its own answer. A story
  stopped or restarted by the operator sends no such event (the worker
  just goes away): its players see the connection banner above. Local
  mode never sends it.

The page never resumes a run that may still be live (only the join's exact
"session not found" resumes), so a reconnect cannot release the account's
run in another window. Local mode behaves the same, minus the login.

### Sharing the model server

Every player's turn goes to the one model server you configured, so the
game rations it in **lanes** (`llm.lanes`): `narration`, the story the
player is watching, and `utility`, the summarizer, the companion, the agents'
plans and the like. Hosted, **`narration` is the number of turns in flight
across the whole server**: a turn holds its narration place from the moment
it is admitted until it ends, utility work included. Set each to the number
of requests your server really runs at once:

- LM Studio: its parallel-requests setting;
- vLLM: it batches natively, so 4 is a sane start on a 12 GB card;
- llama-server: `--parallel`;
- Ollama: `OLLAMA_NUM_PARALLEL`.

**The queue.** Hosted, each lane serves the requests waiting for it in the
order they arrived (local play keeps its simple semaphore). A turn takes its
place in the narration lane **before it changes anything**: until it gets
one, the clock has not moved, no dice were rolled and nothing was saved. Once
it has one, every narration call the turn makes -- the storyteller, its
retry, a second attempt with more room -- uses that same place, so an
admitted turn never waits in line again and never falls back to stock prose
because the server was busy. A turn that waits longer than
`hosting.queue_wait_seconds` (600) is refused, unchanged, with "The
storyteller is busy with other players. Try again in a moment." (the page
keeps what it shows and the player tries again). Five players behind one
narration slot on a reasoning model are five turns deep, which is why the
wait is ten minutes rather than local play's three.

The utility lane is optional by design, so it waits only
`hosting.utility_wait_seconds` (5). If the summarizer, the companion, an
agent's plan or a voice reply cannot get a utility slot in that time, it is
skipped exactly as if it had failed (no new summary that turn, the companion
silent, the agent quiet), and the turn keeps its narration and is saved. The
short wait is what keeps one player's companion chatter from holding the
narration place idle while everyone else waits behind it.

An admitted turn also has a wall-clock deadline,
`hosting.turn_deadline_seconds` (900), its utility calls included: past it
no model call starts and the one running is cut, and the turn ends the way a
model failure ends one, with the story's fallback narration (§ Model server:
one queue for every story).

A turn whose player is gone when its place comes up (the game connection
closed while it waited) is not played; nothing changes and the place passes
on at once. When that player's page reconnects (§ When the connection
drops), it sees its move was never answered and offers **Try again**; it
never re-sends the move on its own. A turn sent over plain HTTP whose browser gave up cannot be seen
to have gone, and is played when its place comes up.

A player is not shown their place in the queue yet: the game can measure it
and nothing tells the player yet: it needs a per-waiter event across the
supervisor's bus, which v0.21.0 left for a later release (docs/GOVERNANCE.md).

Under the supervisor these lanes are one queue for every story (§ Model
server: one queue for every story).

### Limits

- **Actions:** each account may take `hosting.rate_limits.actions_per_minute`
  (12) actions a minute, refilled evenly: a new game, a choice, loading a
  save, writing a save and a voice transcription, over HTTP and over the
  game connection alike. Every action costs the same, resting included.
  Past it, HTTP answers 429 and the game connection a "slow down" message,
  "You are acting faster than this server allows. Wait a moment, then try
  again."; reading (the state, the save list, the story's screens) is not
  counted.
- **Typed input:** any text a player sends -- a typed action, a chosen
  option's id, a save's label, an archetype, a seed -- longer than
  `hosting.max_input_chars` (1000 characters), and a player name longer than
  40, is **refused, not cut** -- "That is longer than this server accepts
  (1000 characters)." -- because a sentence cut short is an action the player
  did not choose. A voice transcript longer than that is returned to the
  player with the same words and no companion reply. It is a length and
  nothing else.
- **Saves:** each account keeps at most `hosting.max_saves_per_story` (50)
  runs and saves in one story (a run's autosave counts as one). Past it a new
  game or a save under a new name is refused, "This story already keeps 50 of
  your runs and saves on this server, the most it allows. Delete one to make
  room."; saving over an existing save always works. The count and the
  write are one step (under the story's save-folder lock), so two saves at
  once at 49 cannot both get in.
- **Message and upload size:** a game connection's message is capped at 64
  KiB, and a request body (the voice upload) at `hosting.max_upload_mb` (16
  MB), refused 413 past it (at the front door as well as at the worker).
- **HTTP turns in flight:** a turn sent over HTTP (a new game, a choice, a
  voice transcription) holds its server thread while it waits in the model
  server's queue -- up to `queue_wait_seconds`, ten minutes -- and then
  while it runs. So each process lets at most `hosting.threads` less 4 of
  them in at once (28 of the default 32), and answers one more 429 at once,
  "Every turn slot on this server is in use. Try again in a moment.",
  instead of letting turns hold every thread while logins, pages and
  everything else wait behind them. One account may have only **one** HTTP
  turn in flight at a time; its next is answered 429 at once, "Your last
  turn is still on its way. Wait for it, then try again.", so no one player
  can take the slots from the rest. Such a request must send its whole body
  within `hosting.body_read_seconds` (30) -- it is read in full before it may
  take a slot, and answered 408 past it -- so a client that sends a body
  slowly, or not at all, never holds one. A body sent in chunks
  (`Transfer-Encoding: chunked`), whose reads no deadline can bound, is
  refused 411 on every route at both doors: the game page and Socket.IO
  always send a body's length. The front door counts its own, for
  every story together. A turn over the game connection is not counted:
  Socket.IO runs each event on a thread of its own, outside the pool.
- **Open connections at the front door:** a game connection (a WebSocket)
  holds one of the front door's threads for as long as the tab is open, and
  a long-poll for up to 45 s. The front door counts them together with its
  HTTP turns against the same `hosting.threads` less 4, and refuses one
  more at once (503, "Every connection this server keeps open is in use.
  Try again in a moment."), so the 4 threads kept for logging in, the
  picker and the static files are free however many tabs are open.
  Every request a story serves comes through the front door, so each story
  is held to the same count. The doctor's `hosting.threads` row gives the
  arithmetic: about (threads - 4) / 2 players with two tabs each, across
  all the stories.
- **Connections per player:** one account may hold at most
  `hosting.max_connections_per_account` (4) of those open connections at
  once -- a tab is one -- so no single player (or script) can take every
  place from the rest; one more is refused 429, "You already have 4 game
  connections open on this server, the most it allows one player. Close a
  tab, then try again.", and a story's worker refuses a connection past the
  same count.
- **Slow bodies and slow clients:** every request body the front door
  passes on must arrive whole within `hosting.body_read_seconds` (30), on
  every route, or it is answered 408; under gunicorn, whose reads wait as
  long as bytes keep coming, a timer shuts the connection's reading side at
  the deadline. A game connection whose browser stops reading what it is
  sent for 30 s is closed. The reserve of 4 threads assumes the reverse
  proxy in front buffers slow clients' headers and bodies (nginx does by
  default; set `client_header_timeout` and `client_body_timeout`; Caddy
  does not buffer bodies): a client that sends its HTTP headers a byte at a
  time holds a thread while gunicorn reads them.
- **Disk:** there is no per-player quota in bytes. The save cap above bounds
  how many runs a player keeps and the action limit how fast they are made;
  a run's transcript grows with the run.

---

## Orchestration

A hosted instance is a **supervisor**, one **worker** process per story and
the **front door**, on one host:

```sh
python -m engine.hosting.supervisor        # or: python launcher.py, with hosting on
```

The supervisor serves no HTTP and runs no turn. It starts each worker and
then the front door, watches them, restarts one that crashes, stops and
restarts stories on request, and keeps every process's log. Players reach
only the front door, on `scene.clockwork.host`/`port` (5573); each worker
listens on a loopback port nobody outside reaches. Local play never starts
any of it: `launcher.py` with hosting off is the single-player game exactly
as before.

### Stories

`hosting.stories` names the stories to serve, one worker each, started in
that order:

```yaml
hosting:
  enabled: true
  stories: ["clockwork-dark", "hue-and-cry"]
```

Each slug must be an installed story that validates
(`python launcher.py --list-games`). An empty list, or a slug that is not
installed or does not validate, stops the supervisor at startup with the key
named -- once, not as a crash loop per story -- and so do the other startup
refusals (§ What hosted mode turns off). `scripts/doctor.py` shows the list as
a `hosting.stories` row and FAILs the same cases.

On start the supervisor checks the storage root can be written, makes the
cookie key (`<root>/hosting/secret_key`, unless `hosting.secret_key` is set)
before any worker starts, so every worker signs with the same one, and binds
**the bus**: the loopback connection each child keeps to the supervisor (on
`127.0.0.1`, a port the operating system picks). Each child start gets its own
one-time credential in its environment, never on its command line, in a file
or in a log, and deletes it from its environment once read. (That deletion
hides it from the programs the child starts, not from the operating system:
on Linux a process's starting environment stays readable in
`/proc/<pid>/environ` by any process running as the same user, and by
root. Run the instance under a user of its own, which nothing else runs as.)
A connection that has not presented
its credential within `hosting.supervisor.hello_seconds` (2) is closed, and
when many are waiting the oldest is dropped first, so no other program on
the machine can keep a child out by holding connections open. A child
whose connect is lost or not answered tries again on a fresh connection, 5 s
apart and 30 s at most, sending the same credential; the supervisor accepts
it once, and refuses and logs each other attempt (`hello refused ...
credential=live`), which is a retry, not a stolen credential. A child whose bus connection drops
exits at once (it must not serve outside the supervisor's reach), and the
supervisor starts it again.

A worker is the hosted game for one story (everything above this section),
on `127.0.0.1` at a port the system picks, reported to the supervisor. On
Linux with gunicorn installed it runs under gunicorn (below); on Windows, or
without gunicorn, on Werkzeug's development server, with the WARNING saying
so. Each child runs in a process group of its own, so a Ctrl+C in the
supervisor's terminal reaches the supervisor alone, which then stops its
children itself.

### The supervisor on a Linux host

Install the server requirements (the game's, without speech-to-text and the
MCP layer, plus gunicorn) and start the supervisor:

```sh
.venv/bin/python -m pip install -r requirements-server.txt -c constraints.txt
.venv/bin/python -m engine.hosting.supervisor
```

To keep it running, give it a user of its own and a systemd unit. The data
(accounts, the cookie key, saves, logs, metrics) goes where
`CLOCKWORK_DATA_DIR` says, your settings in the file `CLOCKWORK_CONFIG`
names, and the stop timeout must be above
`hosting.supervisor.shutdown_seconds` (180), or systemd kills the drain
short (its default is 90 s):

```ini
# /etc/systemd/system/clockwork.service
[Unit]
Description=The Clockwork Dark (hosted)
After=network-online.target
Wants=network-online.target

[Service]
User=clockwork
Group=clockwork
WorkingDirectory=/opt/clockwork-dark
Environment=CLOCKWORK_DATA_DIR=/var/lib/clockwork
Environment=CLOCKWORK_CONFIG=/etc/clockwork/config.yaml
# Secrets: an environment file only root and this user can read.
EnvironmentFile=-/etc/clockwork/secrets.env
ExecStart=/opt/clockwork-dark/.venv/bin/python -m engine.hosting.supervisor
# SIGTERM starts the drain; give it longer than shutdown_seconds (180).
KillSignal=SIGTERM
KillMode=mixed
TimeoutStopSec=210
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`KillMode=mixed` sends the SIGTERM to the supervisor alone (it stops its
children itself, over the bus) and keeps the final SIGKILL for whatever is
left at the timeout. `sudo systemctl daemon-reload && sudo systemctl enable
--now clockwork`; `journalctl -u clockwork` shows what `docker logs` would.

With gunicorn importable, the supervisor starts every child as

```sh
python -m gunicorn -c deploy/gunicorn.conf.py engine.hosting.wsgi:app            # a story
python -m gunicorn -c deploy/gunicorn.conf.py engine.hosting.frontdoor.wsgi:app  # the front door
```

and logs each command as it starts it (`Started worker-<slug>
(operation=spawn, ..., command=-m gunicorn -c ...)`). Do not start these
yourself: a process without the supervisor's bus refuses to boot, and so
does one with hosting off ("local mode is served by launcher.py; gunicorn
serves hosted mode only"). `deploy/gunicorn.conf.py` sets:

- **one** worker with `hosting.threads` threads (`gthread`). The sessions,
  the limits and the queue's client live in that one process's memory;
- the front door on `scene.clockwork.host`/`port`, each story on
  `127.0.0.1` at a port the system picks, which the worker reports to the
  supervisor once it is up;
- **no forwarded header trusted by gunicorn** (`forwarded_allow_ips` and
  `secure_scheme_headers` empty; gunicorn's default trusts any loopback
  peer's `X-Forwarded-Proto`): which proxy to believe is decided once, by
  `hosting.trusted_proxies` at the front door and the proxy token at each
  story (§ Reverse proxy);
- no worker recycling (`max_requests` 0: a worker gunicorn replaced would
  lose its link to the supervisor).

**Nothing overrides the file.** gunicorn reads its settings from its
defaults (`WEB_CONCURRENCY` is only the default worker count, which the file
sets), then this file, then the `GUNICORN_CMD_ARGS` environment variable,
then the command line. The supervisor never passes `GUNICORN_CMD_ARGS` or
`WEB_CONCURRENCY` to a child, and puts nothing on the command line but the
file and the app; and should anything still change what the file sets (the
worker count or class, recycling, the forwarded-header trust, or the bind:
a story off loopback, or the front door off its configured address), the
file's start hook refuses to start, naming it.
- gunicorn's own heartbeat of 120 s (not a request limit: turns stream over
  the game connection) and a 30 s graceful stop; no access log (the game's
  own log names every operation).

**Restarts under gunicorn.** The process the supervisor starts is gunicorn's
master, and the link to the supervisor belongs to the master's one worker.
When gunicorn restarts that worker itself (a missed heartbeat, a crash), the
link closes: the supervisor takes that as the story down, stops the master
and starts it again with a fresh one-time credential, with the same backoff
and hold-down as any crash (§ Restarts and the hold-down). gunicorn's new
worker cannot take the old credential's place -- its `hello` is refused --
so a story is always one process on one link. A `shutdown` from the
supervisor, or a lost link, stops the master along with its worker -- the
master the worker noted when it started, by its process id AND start time:
if that id now belongs to another process (the master already gone, its id
reused), or the worker's parent has changed, nothing is signalled and the
worker only logs it.

### The front door

The front door (`engine/hosting/frontdoor/`) is the one process players
reach. It activates no story and runs no turn. It answers these itself:

- `/login`, `/logout` and `/account`: a player logs in **once**, here, and
  the same signed cookie is read by every story's worker;
- `GET /stories` (the picker) and `POST /stories/<slug>` (the choice);
- `GET /api/health` (200 while its link to the supervisor is up);
- `/admin` and everything under it (the admin panel, § The admin panel,
  behind its own checks; an unknown `/admin` path is a 404 after them --
  never passed to a story);
- `/static/hosting/...`, its pages' stylesheet;

and passes every other request -- the game page, its API, its static files,
Socket.IO's long polling -- to the chosen story's worker. Every request
meets the login check first, so one without a login never reaches a story
(`GET /` goes to `/login`, anything else is 401).

**The game connection (WebSocket).** The game page connects to the server
by WebSocket and never falls back to polling, so this is how every player
plays. The front door does not pass the connection's bytes through: it
**relays messages**. When a browser asks to open one, the front door checks
that the request is a well-formed WebSocket handshake (400), the login and
the chosen story (401, 409 for no story chosen, 503 for a story that is not
running), the page's `Origin` against the address the player used -- the
scheme and host the front door resolved, never a forwarded header it was
not told to trust -- or `hosting.public_origin` (403), and a free place
among its open connections (§ Limits: 503, or 429 past the player's own
`max_connections_per_account`). Only
then does it open its own WebSocket to the story's worker, carrying the
login cookie, the page's `Origin`, the player's address as it resolved it
and the instance's proxy token; the worker checks the origin again and
authenticates the connection as it always has, so an account disabled in
between is refused there. If the worker refuses (a stale session id, say),
the browser gets a plain 502 and no WebSocket. Only once the worker has
accepted does the front door accept the browser's, and it then carries each
message across as it came, text as text and binary as binary, until either
side closes, when it closes the other with the same code. A message from
the browser over 64 KiB closes the connection, as at a worker (the story's
own messages, which the server makes, are not capped). A login that ends --
a password change, a reset, a disable, a change of role or a removal, made
at the front door (the account page, the admin panel) or by
`scripts/users.py` -- closes the account's game connections (§ Ownership
and errors); the close runs on the connection's own thread, so a browser
that has stopped reading cannot hold up the change. A player opening a few
tabs at once is not refused for the moment each tab's last poll and its new
WebSocket are both open: the WebSocket that upgrades from a poll names the
same Engine.IO session and counts as one connection with it toward
`max_connections_per_account`. Every other poll or WebSocket counts on its
own, even one naming a session already held (the game's Socket.IO server
does not refuse several polls of one session at once, so they could
otherwise take every place). The refused WebSocket's 429 is a body the
browser cannot read, so while an account holds its cap the front door also
answers the game page's login check, `GET /api/games/active`, 429 with the
same words, and the page shows them (§ When the connection drops). A story
that refuses a connection past that cap says why, in words the game page
shows. Because the browser only ever
talks HTTP to the front door, nothing it sends after a refused upgrade can
reach a story unchecked.

**Choosing a story.** The picker lists the stories that are running, by
title. The choice is kept in the login cookie, so the browser's next request
goes to that story. `GET /` with no choice goes to the picker, unless
exactly one story is running, which is then chosen for you. A story that is
not running answers 503: the game page says "<title> is restarting", "was
stopped by the operator" or "is not running", and everything else answers
`{"error": "story unavailable"}`. The front door keeps its own copy of the
supervisor's story table, which the supervisor sends it on every change, so
routing a request costs nothing extra.

**One story per browser, and what that costs.** The choice is one cookie,
so a browser plays one story at a time:

- choosing another story in one tab moves every tab of that browser there
  at its next request (the old story's page then answers "session not
  found", and offers a new game or a load);
- the page remembers the run to resume in one slot per site, so after a
  switch the other story's run is loaded from the menu rather than resumed
  on its own;
- a game connection already open stays with the old story until it closes.

Two stories in two tabs of one browser is not built (docs/GOVERNANCE.md);
two browsers (or a private window) work. A per-story address for the game
connection is the planned way out, with the UI changes of v0.21.0.

**The cookie has one writer.** Only the front door sets
`clockwork_session`, and only on a request that changed it (a login, the
account page, a story choice); a worker never sends it, and the front door
strips one a worker sends anyway. So a page still loading from one story
can never undo a story switch or a password change made meanwhile. The
price: the login lasts `hosting.session_days` from the last login, story
choice or password change, not from the last request.

**Its timeouts.** The front door waits for a story's answer according to
what was asked: 60 s for a long-poll (Socket.IO holds one open for up to 45
s), `queue_wait_seconds` + `turn_deadline_seconds` + 60 s for a request that
may run a turn (a new game, a choice, a voice upload: the longest it may
wait for its place, then the longest an admitted turn may run, and a
minute; 600 + 900 + 60 = 1560 s by default), and 30 s for anything else. A
story that cannot be reached is 503; one that does not answer in time, 504.
A story's redirect is passed to the browser as it was sent, never followed.
A request that may run a turn must send its whole body within
`hosting.body_read_seconds` (30) before it is passed on (408 past it), so a
client that trickles a body never holds a turn slot.

### Reverse proxy

Under the supervisor there is **one port** to publish: the front door's
(`scene.clockwork.port`, 5573, on `scene.clockwork.host`). Put your TLS
proxy (Caddy, nginx) in front of it alone; the workers' ports are loopback
and change at every start. One upstream, then:

```
# Caddyfile: automatic TLS; WebSocket upgrades pass as they are.
play.example.org {
    reverse_proxy 127.0.0.1:5573
}
```

```nginx
# nginx, in the http block
server {
    listen 443 ssl;
    server_name play.example.org;
    # ssl_certificate ... ; ssl_certificate_key ... ;
    location / {
        proxy_pass http://127.0.0.1:5573;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 1560s;
    }
}
```

With either, set `hosting.trusted_proxies: 1`,
`hosting.public_origin: "https://play.example.org"` and leave
`hosting.cookie_secure: true`. **Count your proxies exactly.**
`trusted_proxies` higher than the proxies really in front lets any client
write its own `X-Forwarded-For` and be counted as another address (the login
and action limits key on it); lower, and every player is counted as the
proxy. **Outside a container**, bind the front door to loopback
(`scene.clockwork.host: 127.0.0.1`) when the proxy runs on the same host, so
nothing reaches it around the proxy. **In Docker, never change
`scene.clockwork.host`**: the front door must listen on every interface of
the container, its own network; keep the port off the network at the
publish instead (`"127.0.0.1:5573:5573"`, the compose file's default,
§ Docker). In the image a loopback front door makes the health check fail
and the doctor WARN, since nothing published could reach it. To keep the
admin panel off the internet, deny `/admin` there (§ The admin panel,
Getting in).

- `hosting.trusted_proxies` is the **front door's**: with `N` proxies in
  front, its `ProxyFix` takes the client's address, scheme and host from the
  forwarded headers, and then deletes them; with `0` it ignores and deletes
  them. Set `hosting.public_origin` to the address players type.
- A worker trusts exactly one hop, the front door, and only on a request
  carrying the instance's **proxy token** (`X-Clockwork-Proxy`, minted by the
  supervisor at each start and handed to each child in its environment: never
  on a command line, in a file or in a log; each child deletes it from its
  environment once read, though on Linux `/proc/<pid>/environ` keeps the
  starting environment readable to the same user and root, as for the bus
  credentials above). The front door **replaces** `X-Forwarded-For`,
  `-Proto` and `-Host` with what it resolved itself, and drops RFC 7239's
  `Forwarded`, so a client's claim never reaches a story as fact; a request
  to a worker without the token (or with a wrong one) has every forwarded
  header deleted before Socket.IO or the game sees it. The token itself
  never reaches the game.
- The browser's `Host` is passed to the worker unchanged, so Socket.IO's
  same-origin check at the worker sees the address the player used.
- Set your proxy's read timeout above the front door's longest:
  `proxy_read_timeout` in nginx (Caddy's default has none) at least
  `queue_wait_seconds` + `turn_deadline_seconds` + 60 (1560 s by default),
  or a queued turn's answer is cut off by the proxy while the game still
  plays it. The long-polls are answered within 45 s, well inside either.
- Your proxy must pass WebSocket upgrades (the game connects by nothing
  else): Caddy's `reverse_proxy` does so as it is; in nginx, pass
  `Upgrade` and `Connection` (`proxy_http_version 1.1; proxy_set_header
  Upgrade $http_upgrade; proxy_set_header Connection "upgrade";`). The
  connection stays open while the tab does, carrying Socket.IO's own pings
  every 25 s, so a proxy's idle timeout above that is enough.

### Health, and `degraded`

Every `hosting.supervisor.health_interval_seconds` (10) the supervisor asks
each child over the bus and with `GET /api/health` on its port (5 s timeout).
The two mean different things:

- **the bus check** asks whether the process is alive and serving its link.
  `health_failures` (3) failures in a row restart the child, as an exit does;
- **the HTTP check** asks whether its web server answers. A failure marks the
  story `degraded` in the supervisor's log (an `unhealthy` event) and
  **restarts nothing**: a server whose threads are all busy with players'
  connections answers slowly, and restarting it would drop every player on
  the busiest story. A pass clears it.

A child that has not said `ready` within `boot_seconds` (120) of starting is
restarted: warming a story's caches can be slow, but not forever.

### Restarts and the hold-down

A crashed child -- an exit, failed bus checks, a lost bus link, the boot
deadline, a worker hung on a reclaimed place in the model server's queue
(§ Model server below; the reclaim itself is never a crash) -- is restarted after a backoff of 1, 2, 4 ... up to 60 seconds. A
child that crashes again after `max_restarts` (5) crash restarts within
`restart_window_minutes` (10) is **held down**: logged at ERROR and not
restarted until an operator restarts (or starts) it from the admin panel's
Stories page, or the supervisor itself is restarted. A restart an operator
chose never counts toward the limit, and does not forgive either: the
story's recent crashes (and the backoff they earned) still stand after it,
unless the restart revives a held-down story, which starts it afresh. A
crashed or held-down child's one-time bus credential is cancelled at once,
and the supervisor accepts a child's `hello` and `ready` only while that
child is starting, once each. Restarting the supervisor itself, if it
dies, is the container's or systemd's job (docs/GOVERNANCE.md).

### Operations

Starting, stopping and restarting a story are **operations**, run one at a
time by the supervisor (a second while one runs is refused, "another
operation is running"). Each is answered with an id at once and followed in an
operations table -- `queued`, `draining`, `restarting`, `done` or `refused`,
with the time of each step -- so the admin panel's request never waits for a
drain.

A stop or restart first **drains** the worker, through the model server's
queue (§ Model server below): the story's new turns are paused there, and
the stop waits until the story holds no place in any lane, for at most
`drain_seconds` (120: a streamed turn on a reasoning model regularly runs
past a minute). A turn already admitted finishes in its own time -- its
summary, companion and plans are still served -- and the drain ends the
moment it does, not at the deadline. Turns still waiting in line are then
answered busy (they never started, so nothing is lost, and the page's
reconnect picks the run up from its autosave once the story is back), and
the worker is given what is left of `drain_seconds` to finish the requests
it is still answering. A drain that runs out before the story is idle
changes nothing: the story is resumed, its waiting turns keep their places,
and the operation is `refused`, "turns are still running; the story was not
stopped". (If the worker's own last step runs out instead, the story is
resumed and the operation refused the same way, but the turns that were
waiting have already been answered busy: never started, nothing lost, gone
from the line.) Then the worker is asked to exit over the bus, given
`stop_seconds` (30), terminated, and finally killed. If any of that fails,
the story is still resumed, never left refusing every turn.

### Model server: one queue for every story

Under the supervisor, the lanes of § Sharing the model server are held by
**the supervisor, once, for every story**: each worker asks it for a place
over the bus, so five stories share one model server exactly as five
players of one story do. `llm.lanes` is sized as before -- the number of
requests your server really runs at once -- and now counts across every
story, not per worker. Each place costs one round trip on the loopback bus,
against a model call of seconds.

- **Arrival order across stories.** Waiters are served in the order they
  arrived, whichever story asked.
- **One turn per player, across stories.** A player with two stories open
  (two browsers) still has one turn in flight: a turn whose player already
  holds or awaits a narration place in another story is answered at once,
  busy, "A turn is still running in your other window." The utility lane has
  no such rule (its calls are made inside the player's own turn).
- **What a pause stops, and what it does not.** A drain pauses one story; a
  model-settings change (the admin panel's Model server page) pauses all,
then resumes each story as its worker is back. A pause means
  **no new turns** for that story: its waiting turns keep their places, and
  the line skips them, so a paused story at the front never holds up another
  story's player. It does **not** stop a turn already admitted: that turn's
  summary, companion and plans are served as always (pausing them would hold
  the turn, and the drain waiting on it, for minutes). A voice reply outside
  any turn, from a paused story, waits with its turns. When the pause lifts,
  the paused story's waiters are served in their original order.
- **A crashed worker frees its places.** Everything a worker held or waited
  for is freed the moment its bus connection closes, so a crash never leaks
  a slot.
- **A player who leaves frees their place.** A turn still waiting in line
  when its player's game connection closes is withdrawn at once: no place
  held, and no "other window" for that player in another story. (A turn
  sent over plain HTTP whose browser gave up cannot be seen to have gone.)
- **Every turn has a deadline.** `hosting.turn_deadline_seconds` (900) is an
  admitted turn's wall-clock budget, counted from the moment it gets its
  place, its summary, companion and plans included. Past it no model call
  starts and the one running is cut -- at the deadline itself, even one
  whose model server has gone silent mid-answer -- so the turn ends the way
  any model failure ends one -- the story's fallback narration, the
  companion silent -- and gives its place back on time.
  (`llm.timeout_seconds` cannot do this: it is how long the model server may
  go silent, not how long a call may take, and a model that keeps sending
  words is never silent.) Raise it for a slow model: fifteen minutes is the
  narration's whole answer budget at five words a second.
- **No place held forever.** A place held longer than
  `hosting.supervisor.max_hold_seconds` (1200) means a turn is hung, since
  every turn ends by its deadline. It is **reclaimed**: an ERROR (an
  `unhealthy` event), the place passed to the next player at once, and the
  worker told, whose turn then makes no further model call. A worker that
  acknowledges is left running -- a reclaim never counts toward the
  hold-down -- and one that does not answer within seconds is hung, and is
  restarted (that does count). It must be at least `turn_deadline_seconds`
  + 120 (checked at startup, naming the key); your model's
  `llm.timeout_seconds` plays no part in it.
- **Lanes named nowhere.** A profile that asks for a lane `llm.lanes` does
  not size opens it with one place, under the supervisor as in a single
  process.
- **Whose turn it is, is the worker's word.** The supervisor takes the
  player's account id from the worker asking, which read it from that
  player's own login; it checks only that it looks like an id. Workers are
  the supervisor's own children, each with its own one-time credential, so
  this is inside the trust boundary: the one-turn-per-player rule is
  fairness between your players, not a lock against them.
- **Fail closed.** A worker whose link to the supervisor is down refuses
  every turn, busy, rather than run one outside the queue, and exits (its
  lifeline); the supervisor starts it again.

A slow or heavily loaded host may need `hosting.supervisor.hello_seconds`
(2) raised: a child that cannot say hello on its bus connection within it
is closed and restarted.

### Logs

Each process's output is written to `<root>/hosting/logs/<process>.log`
(`worker-<slug>.log`, `frontdoor.log`, `supervisor.log`),
rotated at `hosting.observability.log_max_mb` (20 MB), keeping
`log_keep` (5) older files (`.log.1` the newest), and echoed on the
supervisor's own output with a `[<process>]` prefix, so `docker logs` and a
terminal show everything. The files are yours to read on disk; the admin
panel will never show log text.

Two things the logs never do: **stop the supervisor**, and **stop a child**.
If nothing reads the supervisor's output for a while (a Windows console with
a selection made in it, a paused pager), the echo drops lines rather than
wait, says how many once it moves again, and the files keep every line. If a
log cannot be rotated (on Windows, another program holding the file open,
say an editor or `Get-Content -Wait`), it goes on writing past the size,
notes the failure in the file, and tries again later.

### Shutdown

SIGTERM or SIGINT on Linux (`docker stop`, Ctrl+C), Ctrl+C or Ctrl+Break on
Windows: from that moment nothing is restarted, whatever exits; every worker
is drained and stopped as above, together, and only then the front door, so
a turn drained to its end still reaches its player through the relay before
the connection closes; all within
`shutdown_seconds` (180), after which anything still running is killed, and
the supervisor exits 0. A front door that keeps crashing is held down like
a worker, and then the supervisor stops everything and exits 1: an
instance nobody can reach is better restarted whole by the container or
systemd. On
Windows, Ctrl+Break reaches every program on the console: the workers ignore
it, so it drains them through the supervisor like Ctrl+C. A stop is a drain,
then `stop_seconds`, then 5 s after `terminate()`, then 2 s for the kill,
and the front door's own stop after the workers' is kept 10 s (3 s for it to
exit, then the same 5 and 2), so `shutdown_seconds` must be at least
`drain_seconds + stop_seconds + 17` (checked at startup; 167 by default), and
a container's stop grace must be above it.

That order -- every worker first, the front door last -- holds for a
shutdown the supervisor runs: a signal, Ctrl+C or Ctrl+Break, or a fatal
error it catches. A supervisor killed outright (SIGKILL, the OOM killer, a
crash it cannot catch) takes the front door and every worker down at once:
each child's bus link closes and each exits (the lifeline), with no drain
and no order, and turns in flight are lost to the last autosave.

If the bus itself ever stops answering (it should not: no bytes from any
local program can stop it, and a program on this machine that is not a child
is refused), the supervisor shuts down and exits 1 rather than run deaf,
which is a container's or systemd's cue to start it again.

---

## The admin panel

`/admin` on the front door: server-rendered pages, one stylesheet and one
small script, no build step (`engine/hosting/admin/`). Every page works with
JavaScript off; the script only refreshes the read-only views. It is
**observability and administration**: it shows how the service runs and
manages its accounts. It shows no play text, and it rates, filters and
moderates nothing (AGENTS.md rule 12).

Its pages: **Overview** (each story's state, the accounts counted),
**Users**, **Sessions**, **Saves**, **Stories**, **Model server**, **Queue**,
**Metrics**, **Errors** and **Audit**. Every list comes a page at a time.

### The first admin

An admin is an account with the admin role. The first one is made on the
command line, by someone with a shell on the server:

```sh
python scripts/users.py add root --admin      # a new account, as an admin
python scripts/users.py admin alice on        # or: an existing account
```

The panel can grant and revoke the role after that. The doctor's `admins`
row counts the enabled admins and warns at zero.

### Getting in

Log in at `/login` as usual, then open `/admin`. Every request under
`/admin` meets these checks, in order, whatever the path -- a page added
later and an unknown path included (an unknown one is a 404 after them,
and never reaches a story):

1. no login: a page goes to `/login`; anything else is 401;
2. not an admin: 403, with one fixed body for every path;
3. **re-auth**: the panel asks for your password again
   (`/admin/reauth`) when your last re-auth is older than
   `hosting.admin.reauth_minutes` (15). It counts against the login limits,
   and a failure is written to the audit log;
4. every change is a form `POST` and carries a CSRF token tied to your
   account and its epoch (a password change retires every old one), passes
   the same-site `Origin` check, and spends one of your
   `hosting.rate_limits.admin_actions_per_minute` (30; past it, 429).

The account is re-read on every request, so a disabled or demoted admin is
logged out on their next one (a role change raises the epoch). Every
`/admin` response carries `Content-Security-Policy` (`default-src 'self'`,
no inline script or style, `frame-ancestors 'none'`), `X-Frame-Options:
DENY`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer` and
`X-Content-Type-Options: nosniff`. Two-factor login for admins and a
network allowlist inside the engine are not built (docs/GOVERNANCE.md).

**Why it shares the game's address.** Cookies are scoped to a host name,
not a port, so a second port would not isolate the admin's login; it would
only add a second block and certificate to your proxy. What a separate
origin would protect against -- script on a game page reading `/admin` -- is
covered another way: the game's client never turns text into HTML (no
`innerHTML` or the like anywhere under `ui/src`, held by
`tests/test_ui_no_html_injection.py`), so neither the model's prose nor a
player's text can become script on this origin.

**Keeping it off the internet.** If only you administer the server, deny
`/admin` at your reverse proxy and use it over an SSH tunnel or the LAN:

```
# Caddy, inside your site block
@admin path /admin /admin/*
respond @admin 404
```

```
# nginx, inside your server block
location = /admin  { return 404; }
location ^~ /admin/ { return 404; }
```

### Users

`/admin/users` lists every account: its name, id, when it was made, its
role, whether it is disabled, whether it must change its password, and its
live sessions (counted from the first page of the Sessions list; `?` when
the stories could not be asked), and its last successful login (from the
metrics, § Metrics and errors; blank when none is kept). Each action is a
button:

- **Make an account** (a name): the panel generates a one-time password and
  shows it **once**, on the page the form sends you to, and nowhere else.
  It waits for that one showing in the front door's memory only (never a
  file, a URL, the login cookie, a log or the audit log), and a reload of
  that page says it was already shown -- it never makes the account or
  resets the password again. If you lose it, reset the password. Several
  made or reset at once (two tabs) each wait for their own showing. The
  waiting passwords live in the memory of the front door process, which is
  one process as shipped: a front door that restarts forgets them (reset
  again), and a front door run as several processes behind a balancer
  would show "already shown" whenever the form and the page landed on
  different ones -- run one. Give it to
  the player; at their first login they must choose their own, different
  from it, before they can play (the front door sends every page to
  `/account`, and a story treats them as logged out until then). An admin
  never knows a player's real password.
- **Reset password**: the same, and every login of the account ends.
- **Disable / Enable**: a disable ends every login of the account at once,
  its open game connections included, and its live sessions in every story.
  A session whose turn is running finishes that turn -- a turn is never cut
  -- but the turn saves nothing, its player is told so ("This turn was not
  saved: your account was closed by the server's operator."), and the
  session is released the moment it ends. A new game or a save the account
  sent just before the disable is refused the same way, nothing written.
  The audit row counts them.
- **Make admin / Revoke admin**: the account's logins end, so a demoted
  admin's open panel is logged out on its next request.
- **Delete**: type the account's name to confirm, and choose to **keep** its
  saves on disk (`<storage.root>/users/<id>/` is left; ids are never reused)
  or **purge** them, deleting them too. The account is disabled first (its
  sessions ended, as above), then removed. A purge is **refused** while one
  of its turns is still running, or a story did not answer ("try the delete
  again in a moment"): the account stays disabled, and its saves are not
  deleted until nothing of it can still write them. After deleting them the
  purge asks the stories once more, and deletes again if anything of the
  account was still there.

Every action that changes something answers by sending you back to its page
with a one-line note of what was done, so reloading the page never repeats
it.

An admin cannot revoke their own role, or disable or delete themselves, from
the panel, and the last enabled admin cannot be demoted, disabled or
deleted there ("at least one admin must remain; use scripts/users.py"). Both
are checked inside the accounts file's lock, so two admins revoking each
other at the same moment cannot leave none. `scripts/users.py` can do each,
after asking you to type the name.

### Sessions

`/admin/sessions` lists every story's live sessions, 50 a page: the story,
the owner's account name, a short reference to the session, a short
reference to its save (a keyed hash of the save's id -- the key is random
and lives only in the front door's memory, so the id cannot be worked back
from it, and a restart changes every reference -- which a player may have
chosen; the same reference the Saves page shows), when it was made, its last activity, its turns, whether a turn is running now,
and how many game connections are in it. Nothing from the game itself: no
player name, place, day or text. The supervisor asks every running story
for its list at once, and waits at most 5 seconds for them all; a story that
does not answer, or whose list would not fit one
message on the supervisor's link (64 KiB), is shown as an error row, and the
rest of the page is served.

**End session** releases a run, exactly as the idle sweep does: the
player's tab is told (`session_ended`, reason `ended`) and reads "This
session was ended. Your run is saved." with **Resume** (§ When the
connection drops), and their run stays on disk, autosaved every turn, so
Resume reopens it.
A session whose turn is running **cannot be ended** ("a turn is running;
try again in a moment"): a turn is never cut mid-flight. Each end is
audited (`session.end`, the session's id as the target).

### Saves

`/admin/saves` shows each account's saves in each story, 20 accounts a page,
read from each story's save index on disk: a short reference to the save (a
keyed hash of its id, as on the Sessions page -- never the id, which a
player may have chosen), whether it
is an autosave or a manual one, its turn, when it was written, its save format and
its size on disk. Never a manual save's label (the player typed it), the
player's name, place or story values, a thumbnail, the save itself or its
transcript: the page opens no file but the index. A missing or damaged index
shows as no saves. Downloading, restoring or deleting one save here is not
built (docs/GOVERNANCE.md). Deleting an account with **purge** removes all
of its saves; with **keep**, they stay on disk.

### Stories

`/admin/stories` shows each story's state (`starting`, `ready`, `degraded`,
`draining`, `restarting`, `held_down`, `stopped`; § Health above), its pid,
port, uptime, crash restarts in the window, its last exit (code and time),
when it was held down, its live sessions and its last operation's progress.

**Start, Stop, Restart** are the operations of § Operations: each answers at
once with its id (`op-3`), and the page shows it moving through `draining`,
`restarting` and `done`, or `refused` with the reason. One runs at a time; a
second is refused, "another operation is running". If the supervisor's answer
does not come at all, the page says so and the operation's own row below
tells you whether it was queued.

What a **stop** does to players: the story's new turns are paused in the
model server's queue; the turns already running finish; turns still waiting
are answered busy (they never started, so nothing is lost); then the story's
process exits, and its players get the front door's "stopped by the
operator" page (or `{"error": "story unavailable"}`) until it is started
again. Their runs are on disk. A stop lasts until the next **Start**, or the
next start of the whole server. A **restart** does the same and starts it
again, and its players' pages reconnect to their runs.

Why a stop can be **refused**: the drain waits at most
`hosting.supervisor.drain_seconds` (120) for the turns already running. If
one is still running then, nothing is stopped -- the story keeps serving,
its waiting turns keep their places -- and the operation shows `refused`,
"turns are still running; the story was not stopped". Try again once the
turn is over, or raise `drain_seconds` for a slow model.

A **held-down** story (§ Restarts and the hold-down) shows its last exit and
when it was held down; **Restart** (or **Start**) clears the hold and starts
it afresh. A restart or start you choose never counts as a crash.

Each operation is audited across the two processes: the front door writes
the `started` row before it asks the supervisor (and refuses the operation,
asking nothing, if that row cannot be written), and the supervisor writes
the outcome under the same reference when the operation finishes.

### Model server

`/admin/model` shows what the **supervisor** reads (the front door never
reads `llm.*`): the provider, its base URL, the health probe's status, detail
and latency, the models the server lists (id, loaded, context,
capabilities) and `llm.declared_models`, each checked at most every 10
seconds. A URL set in a file with `user:pass@` or a query in it is shown
without them. The **API key** is shown only as "set, from the environment
(`CLOCKWORK_LLM_API_KEY`)", "set, from a file (`llm_api_key.txt`)" or "not
set" -- never its value or length -- and as **withheld** when the base URL
was moved to another host without it (below). Setting a key in the panel is
not built (docs/GOVERNANCE.md): it goes in the environment or a key file.

**What it edits**: `llm.provider`, `llm.base_url`, `llm.lanes.narration`,
`llm.lanes.utility` (1 to 16 each), `llm.context_tokens`,
`llm.prefer_native` and `llm.profiles.big.{model, temperature, max_tokens,
reasoning_budget, reasoning}`, and nothing else (the rest is not built:
docs/GOVERNANCE.md). The keys the Settings panel also has are checked by its
rules (a number out of range is clamped, and the page says so). The provider
must be one this build speaks. The base URL must be `http://` or `https://`
with a host and no `user:pass@`, no query and no fragment: the page shows it
and the audit log records it, so a credential in it is refused, never
displayed. A key your `CLOCKWORK_CONFIG` file sets is shown **locked**, with
the file, and an edit of it is refused "set in `<file>`" (§ Configuration).

**Only what you changed is applied.** The form carries the values it showed,
and the admin layer's version. Only the fields you changed are sent; a field
you left alone is never sent, even if another admin changed it meanwhile. If
the admin layer changed since you loaded the page (another tab, another
admin), the whole apply is refused, "These settings changed since you loaded
the page", and nothing is written: reload and apply again.

**Any host, by design -- and the key only on your word.** An admin may point
`llm.base_url` at any `http(s)` host: the panel's admins are the operator's
own people (operator trust), and the supervisor and every story will reach
whatever host is named, a host on the internal network included. The API
key does **not** follow the URL to a new origin (a different scheme, host or
port) unless the same apply ticks **Send the API key to this host**, which is
recorded in the audit row (`send_key`). Without it, the new host is sent no
`Authorization` header at all -- not by the probe, not by the supervisor's
health checks, not by any story's turns -- and this page shows the key as
withheld; to send it later, tick the box and apply again. Moving
`llm.base_url` back to the origin the key was last allowed to (the one
recorded) restores the key without the box: it is that host's key already.
(The admin layer records where the key may go, `llm.api_key_origin`, written
by the supervisor alone.) An operator who never wants the panel to move the model
server sets `llm.base_url` in their `CLOCKWORK_CONFIG` file, which locks it.

**Where edits live**: the admin layer, `<storage.root>/hosting/admin.yaml`,
written by the supervisor alone (§ Configuration). Not `config/local.yaml`
(the owner's hand-kept local file, whose comments a rewrite would drop) and
not your `CLOCKWORK_CONFIG` file (yours to write; the panel would fight your
edits). The previous version is kept beside it as `admin.yaml.prev`.

**What an apply does** -- never a change in place. Your **Apply** answers at
once with an operation id, and the page follows it:

1. `validating`: the changed keys are checked again by the supervisor, and
   held in memory; nothing is written;
2. a new provider or base URL is **probed** first; if it does not answer, the
   apply is refused, "the new model server does not answer: nothing was
   changed" -- unless you ticked **Apply anyway** (recorded in the audit
   row);
3. `draining`: new turns are paused for **every** story, and the turns
   already running finish. If one is still running after
   `hosting.supervisor.drain_seconds` (120), everything resumes and the
   apply is refused, "turns are still running; nothing was changed";
4. only then is `admin.yaml` copied to `admin.yaml.prev`, the new file
   written, the supervisor's config re-read and the lanes resized;
5. `restarting`: each story's worker is restarted **one at a time**, in
   `hosting.stories` order, and its story's turns resume once it is ready.

For players: their story goes away and comes back, one story at a time, and
their page waits for it with no reload: its banner reads "Connection lost.",
then "The server is not answering." with the front door's own words for a
story that is down, "(story unavailable)", and once the worker is back the
page rejoins, finds its run gone with the old process, and resumes it from
its autosave ("Opening your run…"; § When the connection drops). A turn
waiting in the queue when its worker restarts is answered busy (it never
started, so nothing is lost). This is
the only way a model setting changes under live players,
which is why the game's own Settings panel stays refused in hosted mode
(§ What hosted mode turns off). A worker that crashes during the drain
restarts under the settings the instance is running (nothing is written until
the drain is done), and none of an apply's restarts counts toward
`max_restarts`. A stopped or held-down story is not started; it reads the new
settings when you start it.

**The rollback, and what it covers.** If a worker is not ready within
`hosting.supervisor.boot_seconds` under the new file (or exits while
starting), the supervisor puts `admin.yaml.prev` back (or removes the new
file, if there was none before), re-reads, resizes the lanes, and restarts
the workers it had already restarted, with the one that failed: the
operation ends `rolled_back`, audited `llm.rollback` (actor `supervisor`). It
covers a configuration that does not **boot**. It does not cover a model
server that is down, or a model name it does not serve: a worker does not
call the model server while it starts, so it boots fine and every turn
then fails. The probe in step 2 is the only guard for the server, and only
at the moment of the apply -- after that, watch the health row on this page.

If the apply fails some other way after the new file is written, it is
rolled back the same way. If the server is shut down part-way through the
restarts, the operation ends `done` -- the new file is written and applies at
the next start -- and its audit row says so (`error`, "the new settings are
written, and apply at its next start"). If the **supervisor itself** dies
mid-apply, nothing rolls back: the new `admin.yaml` is in force when it
starts again, and the file before it is beside it as `admin.yaml.prev`, to
copy back by hand if you need to.

One operation runs at a time, story operations included: a second is refused,
"another operation is running".

### Queue

`/admin/queue` shows the model server's queue, shared by every story: per
lane (`narration`, `utility`, and any lane a profile opened), its size,
whether it is paused (a model apply drains everything), who holds a slot and
for how long, and who waits, in order, with their story and wait so far.
Who is an account, by id and name; nothing of what they play is shown. The
stories paused on their own (a stop or restart draining) are listed below,
and below that the last hour's waits from the metrics (§ Metrics and
errors): a turn's wait for its place, and each lane's wait and hold, as
medians (p50) and 95th percentiles.

### Metrics and errors

**Observability, not moderation.** The supervisor keeps how the service ran
-- timings, waits, counts, and errors by reference -- in
`<storage.root>/hosting/metrics.sqlite3` (SQLite, WAL), and NOTHING of what
was played: no prompt, narration, choice, typed action, player name, save,
model output, reasoning or log message text. No field rates, classifies,
flags or filters anything a player writes, and none can be added: the
schema is closed (`engine/hosting/metrics_schema.py`) and a test pins it
(AGENTS.md rule 12). The supervisor is the store's only writer and reader;
the panel asks it for one of a fixed set of named queries, a page at a time,
so no SQL ever crosses the bus.

What is recorded, six kinds, every field a time, a number, an id (an
account, a story, a process, a reference), a Python class or logger name, or
one of a fixed list of words:

| Kind | What | Sent by |
|---|---|---|
| `turn` | its story and account, its wait for admission, its run time, and `ok`, `busy`, `error`, or refused over a cap or the rate | each worker |
| `lane` | a model-server slot's story, account, lane (`narration`, `utility`), wait and hold, and `granted`, `timeout`, `cancelled` or `other_window` | the supervisor |
| `session` | a run `created`, `resumed`, `released` (the account's other run), `swept` (idle) or `ended_by_admin` | each worker |
| `login` | the account (none for a name that is no account) and `ok`, `failed`, `limited`, `disabled` or `must_change` | the front door |
| `error` | the process, the player's reference (when one was shown), the exception's class and the logger's name | every process |
| `process` | a child `started`, `ready`, `unhealthy`, `exited` (with its code), `restarted`, `held_down` or `stopped` | the supervisor |

A lane a profile opened under its own name is not recorded (the schema names
only `narration` and `utility`). The supervisor stamps each metric's process
and story itself, from the connection it came on, so a process can only ever
report for itself. A metric that does not fit the schema is dropped and
counted (the Errors page's "rejected"), never kept as text, and a process
never waits to send one: its queue drops (and counts) when full.

**Bounded.** Rows older than `hosting.observability.retention_days` (30)
are deleted every hour, and the file cannot grow without limit whatever a
client does:

- a **refusal** -- a failed, limited or disabled login, an action over a cap
  or the rate -- is not kept one row each: it is counted per minute, one row
  per (minute, login or action, story, outcome), with no account, so a script
  hammering `/login` adds a few rows a minute;
- the supervisor takes at most 100 metrics a second from each process (a
  burst of 400); past that they are dropped and counted;
- the file is capped at `hosting.observability.metrics_max_mb` (512): a
  write that would pass it first deletes the oldest tenth of every table,
  so the newest are always kept. Its `-wal` file is cut back to 4 MB after
  each checkpoint. The cap cannot shrink a file already larger than it
  (SQLite keeps the pages it has, and reuses them).

The page queries count and rank in SQLite, one statement at a time, so a
page never loads a month of rows. The file and its `-wal`/`-shm` are
readable by the server's user only on Linux (0600, as `users.json` and the
audit log are).

**It never stops a start.** A CORRUPT file (torn by a power cut, not a
database, a directory in its place) is moved aside as
`metrics.sqlite3.bad-<UTC time>` (with its `-wal` and `-shm`) and a new one
made, with a WARNING in the supervisor's log; the three newest moved-aside
files are kept and older ones deleted. A file that will not open for any
other reason -- locked by another program, a full disk, no permission -- is
left where it is (it may be sound), and the supervisor starts without
metrics, as it does if even a new file will not open: a WARNING, a
`metrics.disabled` audit row, and the panel's Metrics and Errors pages say
the metrics could not be read. At each start a store of at most 64 MB has
every page checked (`PRAGMA quick_check`); a larger one is not read whole
on every start, and is checked by its use. The doctor's `metrics store` row
WARNs on a file that will not open (a read-only check, bounded the same
way; it changes nothing). The file is yours to back up or delete; the
supervisor makes a new one when it starts.

**The Metrics page** (`/admin/metrics`): over the last 24 hours, the turn
duration's p50 and p95 per story and hour, the admission and lane waits,
turns by outcome per story and hour (busy and error among them), the
refusals per hour, and each account's turns, sessions and active days, per
day, over the last 30 days (or the retention, when shorter; the page says
which). Below them, each
story's own checks -- the Oracle's numbers that local mode shows at
`/api/metrics`, which hosted mode answers 404: turns, the engine's rule
violations by rule id, stat changes the model claimed that the engine never
made (counted, with the largest; the stat names it claimed are never kept,
since a model can write anything there), how often the companion spoke, the
average turn and the challenges started by kind (`other` for anything that
is not one of the engine's own kinds). They pass through a projection in the
story's worker and again in the supervisor, so play state (the doom track)
and model text never leave the worker. The **Users** page shows each
account's last login from the same store.

**The Errors page** (`/admin/errors`): the recent errors, newest first. A
player who saw "The turn could not be completed (ref 3fa9c2e1)" -- or
"Transcription failed (ref ...)" -- is found by that reference, typed into
the page's **Find** box (`/admin/errors/find?ref=3fa9c2e1`; each lookup
spends one of the admin's `rate_limits.admin_actions_per_minute`, and is
answered from an index on the reference): its row names
the process (`frontdoor`, `supervisor` or
`worker-<slug>`), the exception's class and the logger. The full traceback
is in that process's log file, `<storage.root>/hosting/logs/<process>.log`
(or a rotated `.log.1`, `.log.2` ...): search it for the reference, e.g.
`grep 3fa9c2e1 data/hosting/logs/worker-clockwork-dark.log*`. The panel never
shows log text. A row with no reference is an ERROR a process logged on its
own (its class and logger only, never the message). The page also counts
the metrics rejected and dropped since the supervisor started -- by the
store (its queue full, a process past its rate, the size cap) and by each
process before it sent them (as its last health check reported) -- and
lists the recent process events.

Exporting metrics (Prometheus, OpenMetrics) and alerting on a crash loop or
a held-down story are not built (docs/GOVERNANCE.md, NOT WIRED).

### The audit log

`<storage.root>/hosting/audit.jsonl`: one line per row, appended by
`engine/hosting/audit.py` alone, under its own lock, by the panel, by
`scripts/users.py` (actor `cli`) and by the supervisor (actor `supervisor`:
a story held down after a crash loop, a model apply rolled back; it also
writes a model apply's outcome, for the admin who asked). Each row has exactly these fields:
when, who (an account id, `cli` or `supervisor`, and its name), the
address the panel saw, the action (`account.create`, `account.disable`,
`account.enable`, `account.reset_password`, `account.delete`,
`account.set_admin`, `account.passwd`, `admin.reauth`,
`admin.reauth_failed`, `story.held_down`, `session.end`, `story.start`,
`story.stop`, `story.restart`, `llm.apply`, `llm.rollback`,
`metrics.disabled`), its
target, the options chosen (`purge`, `admin`, a new account's name, a story,
the sessions a disable ended, an operation's id, `apply_anyway`; for an
`llm.apply` outcome each key's old and new value -- the allowlist holds no
secret, and a base URL cannot carry one), the result and an 8-digit
reference. Never a password, a
hash, a key or anything played.

**No change without its row.** An action writes its row (result `started`)
**before** it acts. If that row cannot be written -- a full disk, a lock it
cannot take -- the action is refused with an error page and nothing changes.
Its outcome (`ok`, `refused` or `error`) follows as a second row with the
same reference. A request refused before it starts (a bad name, a guard) is
one `refused` row. So the log can show a `started` with no outcome (the
process died mid-action), but never a change with no row.

**Rotation.** Past `hosting.observability.audit_max_mb` (20) the file is
renamed `audit.jsonl.1` (older ones shift to `.2`, `.3` ...) and a new one
started; `hosting.observability.audit_keep` (10) rotated files are kept and
the oldest beyond that is deleted. To keep more history, copy the rotated
files somewhere only you can read before they age out.

The **Audit** page shows the newest rows first, 50 a page, filtered by
action or actor, across the current and rotated files. It reads only the
tail it needs, and goes back at most 5000 rows; a filtered view searches
at most the newest 8 MiB (some 25,000 rows) and says "Older rows not
searched" when it stopped there. Read older rows in the files themselves.

## Docker

One image, one container, every story you list: the
container runs the supervisor, which starts the front door on 5573 and one
gunicorn worker per story on the container's loopback (§ Orchestration).

```sh
docker build -t clockwork-dark .
docker compose up -d game
docker compose exec game python scripts/users.py add <you> --admin
```

then open `http://localhost:5573` on the same machine: compose publishes
the port on the host's loopback only. For anyone else, put a TLS reverse
proxy in front (§ Reverse proxy). **Plain HTTP from another machine** (a LAN
trial at `http://<ip>:5573`, the publish widened to `"5573:5573"`) logs in
to nothing, silently: the login cookie is `Secure`, which a browser sends
only over HTTPS or to `localhost`. Set `hosting.cookie_secure: false` in
`/data/config.yaml` for such a trial (the doctor WARNs, and passwords then
cross the network in the clear), or use TLS.

A plain `docker run` (no compose) needs **`--init`**, compose's `init: true`
(the entrypoint warns without it: the supervisor would be PID 1 and nothing
would reap an orphaned worker), the volume and the stop grace by hand:

```sh
docker run -d --init --name clockwork -p 127.0.0.1:5573:5573 \
  -v clockwork-data:/data --stop-timeout 210 clockwork-dark
```

### The image

`Dockerfile` (multi-stage) builds from `python:3.11-slim-bookworm`, pinned
by digest, and installs `requirements-server.txt` under `constraints.txt`:
the game's core plus gunicorn, **without** faster-whisper and without the
MCP layer (hosted
mode refuses it). It copies `engine/`, `games/`, `content/` (the committed
client build included: no node in the image), `deploy/`,
`config/default.yaml`, `config/docker.yaml`, `launcher.py` and three
scripts (`users.py`, `doctor.py`, `seed_lore.py`), and builds every shipped
story's lore index at build time. `.dockerignore` keeps out the history,
the tests, the client's sources, `data/`, `config/local.yaml` and every key
file (`llm_api_key.txt`, `lmstudio.txt`, `*.key`, `*.token`, `.env*`).

At run time it:

- runs as the user `clockwork`, **uid and gid 10001**, who cannot write the
  application (`/app`);
- keeps everything it makes on the **`/data` volume** (`CLOCKWORK_DATA_DIR`):
  accounts, the cookie key, saves, media, logs, metrics, the audit log, the
  admin layer, and your settings in **`/data/config.yaml`**
  (`CLOCKWORK_CONFIG`), made empty on the first start if absent;
- reads `config/docker.yaml` (`CLOCKWORK_ENV=docker`): the front door on
  every interface **of the container**, hosting **on**, runs released after
  30 idle minutes, `llm.base_url` at `http://host.docker.internal:1234/v1`,
  and every managed service off but the model server (their shipped
  `localhost` URLs point at nothing inside a container; enable one in
  `/data/config.yaml` with its real URL);
- **push-to-talk is effectively off**: `stt.provider: voxtral_http` with
  nothing at its URL, so every press answers an empty transcript and no
  model is downloaded. With a transcription server, set `stt.base_url` in
  `/data/config.yaml`; or build with `--build-arg WITH_WHISPER=1` (adds
  faster-whisper, CPU only, its model downloaded on first use into
  `HF_HOME=/data/cache/hf` on the volume) and set `stt.provider:
  faster_whisper` there;
- has `/app/deploy/entrypoint.sh` check `/data` is writable (stopping with
  the fix if not) and then `exec` the supervisor, so the supervisor gets the
  container's signals itself;
- reports healthy while `GET /api/health` answers 200 **at the address the
  front door binds** (`/app/deploy/healthcheck.py`). A front door bound to
  the container's loopback (a `scene.clockwork.host: 127.0.0.1` in
  `/data/config.yaml`) is **unhealthy** whatever it answers there: the
  published port reaches the container's interface, never its loopback. In
  the image leave `scene.clockwork.host` alone; keep the port private at
  the publish instead.

Hosting cannot be turned off in the image: a container exists to publish a
port, and gunicorn and the supervisor both refuse local mode. Local
single-player is `launcher.py`, outside a container.

**Secrets** reach the container two ways, and none is in the image:

- **the environment**: `CLOCKWORK_SECRET_KEY` and `CLOCKWORK_LLM_API_KEY`,
  passed through by name in `docker-compose.yml` from the shell (or an
  `.env` file beside the compose file, which `.dockerignore` keeps out of
  the build) that runs compose;
- **files on `/data`**, named by ABSOLUTE path in `/data/config.yaml` (a
  relative `${file:...}` is read against `/app`, where you cannot write):

  ```yaml
  hosting:
    secret_key: "${file:/data/secrets/cookie_key}"
  llm:
    api_key: "${file:/data/secrets/llm_api_key.txt}"
  ```

  `docker compose cp` the file in and make it readable by uid 10001 only.
  `llm.api_key` is not one of the admin panel's keys, so setting it here
  locks nothing in the Model server page (which shows the key as present,
  and its source as that file, never the value).

Without either, the cookie key is generated once into
`/data/hosting/secret_key` (mode 0600) and kept with the volume; the shipped
key chain's own files (`llm_api_key.txt`, `lmstudio.txt`) are read relative
to `/app` and so never exist in the image.

### Docker Compose

`docker-compose.yml`'s `game` service:

- publishes **5573 and nothing else** (the workers' ports are the
  container's loopback), and **on the host's loopback only**,
  `"127.0.0.1:5573:5573"`: a reverse proxy on the same host reaches it,
  nothing else does. A port Docker publishes on every interface bypasses
  ufw and firewalld on Linux, carries passwords in plain HTTP, and lets a
  client that connects to it around your proxy write its own
  `X-Forwarded-For` under `trusted_proxies` (and be counted as any address it
  likes by the login and action limits). Widening it to `"5573:5573"` (a
  proxy on another host, a LAN trial) is your explicit edit; then firewall
  the port to that proxy;
- mounts the named volume `clockwork-data` on `/data`;
- adds `host.docker.internal:host-gateway` (needed on Docker Engine on
  Linux; Docker Desktop names the host already);
- sets **`init: true`**: Docker's init (tini) is PID 1, forwards the stop
  signal to the supervisor and reaps any gunicorn worker left orphaned by a
  crash;
- sets **`stop_grace_period: 210s`**, above
  `hosting.supervisor.shutdown_seconds` (180). `docker compose stop` sends
  SIGTERM; the supervisor drains every story's turns and stops its children
  within `shutdown_seconds`; only after the grace does Docker SIGKILL.
  Compose's own default grace is 10 s, which would cut every drain short.
  If you raise `shutdown_seconds`, raise the grace with it (a test reads
  both files and holds the one above the other). The front door is stopped
  last, after every story has drained, so a player mid-turn sees the turn's
  end before the connection closes;
- is **hardened**: `no-new-privileges`, every capability dropped
  (`cap_drop: [ALL]`; nothing needs one at uid 10001 on port 5573), a
  read-only root filesystem (`read_only: true`) with a tmpfs on `/tmp` for
  scratch (gunicorn's heartbeat files, SQLite's temporary files); what the
  game keeps goes to `/data`;
- is **built, never pulled** (`pull_policy: build`): `docker compose pull`
  or `up --pull always` would otherwise ask Docker Hub for an image named
  `clockwork-dark`.

**Several stories in one container.** Which stories run is
`hosting.stories` in `/data/config.yaml` (the flagship alone by default),
never an environment variable: the supervisor sets `CLOCKWORK_GAME` for
each worker itself, and the front door lets each player pick. Accounts and
the cookie key are shared by construction (one `/data`, one key made before
any worker starts), so one login works for every story; saves stay apart
by story and by account.

```yaml
# /data/config.yaml -- edit it in the volume, then: docker compose restart game
hosting:
  stories: ["clockwork-dark", "hue-and-cry"]
  public_origin: "https://play.example.org"
  trusted_proxies: 1    # safe only while 5573 is published on 127.0.0.1 (the default) or firewalled to the proxy
```

To edit it: `docker compose cp game:/data/config.yaml .`, change it, `docker
compose cp config.yaml game:/data/config.yaml`, restart. **Set each
`llm.*` key in one place** (§ Configuration): a key in this file is locked
in the admin panel's Model server page, so if you mean to use that page,
leave the model server's keys out of this file; `config/docker.yaml`'s
`llm.base_url` ranks below the panel and is only its starting value.

The `vllm` service sits under the compose profile `vllm` (a GPU vLLM server
beside the game, reached at `http://vllm:8000/v1`); `docker compose up -d
game` never starts it. Its image (`vllm/vllm-openai:v0.31.0`, by digest)
and command line are the ones v0.20.0 ran live on an RTX 2060
(Qwen/Qwen3-1.7B, `--dtype half`, `--reasoning-parser qwen3`;
docs/MODEL_SERVERS.md § vLLM). `--gpu-memory-utilization` reads
`VLLM_GPU_MEMORY_UTILIZATION` from the shell that runs compose (default
0.90, the value measured there): set it just under free ÷ total GPU memory
as `nvidia-smi` reports it with nothing else on the card. The game
container narrating through `http://vllm:8000/v1` has not itself been run:
vLLM was verified from the host, not over the compose network.

**Do not run `docker compose config` with secrets in your environment.**
Compose passes `CLOCKWORK_SECRET_KEY`, `CLOCKWORK_LLM_API_KEY` and `HF_TOKEN`
through by name, and `docker compose config` expands every one into its
output (and so into a terminal scrollback, a paste or a CI log). Run it in a
shell that holds none of them, or redact its output before sharing it.

### `/data` ownership

A **named volume** (the compose file's) needs nothing: the image gives
`/data` to uid 10001 before declaring the volume, so a new volume starts
writable. A **host directory** bind-mounted on `/data` is owned by root
until you give it to the image's user:

```sh
sudo chown -R 10001:10001 /srv/clockwork-data
```

Without that the container stops at once, saying so
(`deploy/entrypoint.sh`), and keeps restarting (`restart:
unless-stopped`), so there is no running container to `exec` into. Run the
doctor in a container of its own instead, past the entrypoint, against the
same mount:

```sh
docker compose run --rm --no-deps --entrypoint python game scripts/doctor.py
```

Its `storage` row FAILs naming the same `chown`. (In a container of its
own, `localhost` is that container: a model server the running instance
reaches on its loopback shows as unreachable there.)

### Reaching a model server from a container

Inside the container `localhost` is the container. The model server is
reached by a name for the host:

- **Docker Desktop (Windows, macOS):** `host.docker.internal` reaches a
  server bound to the host's **loopback** -- measured on Windows 11 with
  Docker Desktop (engine 29.8.1) in v0.20.0 T18: a stub bound to
  `127.0.0.1` on the host answered the container. LM Studio needs no
  "serve on local network" for it.
- **Docker Engine on Linux:** `host.docker.internal` (the compose file's
  `host-gateway`) is the `docker0` bridge address, and a server bound to the
  host's loopback does **not** answer there. Do not bind the model server to
  every interface (that puts an unauthenticated model server on your LAN):
  bind it to the bridge address (`ip -4 addr show docker0`, usually
  `172.17.0.1`), or firewall its port to the bridge.
- **The `vllm` profile**: `http://vllm:8000/v1`, on the compose network.

Point the game at it on the admin panel's Model server page, or with
`llm.base_url` in `/data/config.yaml` (which then locks it in the panel).

### Checking it

`docker compose exec game python scripts/doctor.py` reads the instance's
config as the supervisor does and shows the hosted rows (§ Configuration);
when the container will not start, `docker compose run --rm --no-deps
--entrypoint python game scripts/doctor.py` (§ `/data` ownership). The
opt-in smoke test drives a built image end to end -- the hardening, the
built-in lore read as uid 10001, the doctor both ways, two accounts on two
stories over the WebSocket, ownership, the admin panel, a gunicorn master
killed, and a stop that drains a turn in flight to its player -- with a stub
model server inside the container:

```sh
docker build -t clockwork-dark .
CLOCKWORK_DOCKER_SMOKE=1 python -m pytest tests/test_docker_smoke.py -s
```

It starts its own compose project (`cwd-t18-smoke`), publishes on the
host's loopback only, and removes its containers and volume at the end.

---

## Configuration

Hosted mode reads the same layered config as local play, with one more
layer. Later wins:

```
config/default.yaml → config/<CLOCKWORK_ENV>.yaml → config/local.yaml
  → the admin layer (hosted only) → $CLOCKWORK_CONFIG (each file, left to right)
  → the story's own overlay
```

**The admin layer**, `<storage.root>/hosting/admin.yaml`, is where the admin
panel keeps its edits to the model server's settings (§ The admin panel,
Model server), written by the supervisor alone. It is read whenever `hosting.enabled`
is on in the other layers and the file exists -- by the supervisor, every
worker and the front door, and equally by the doctor, `launcher.py --check`
and `scripts/users.py` -- so every tool sees the model server the instance
runs. No environment variable selects it, and with hosting off it is never
read. It may hold only the panel's keys: `llm.provider`, `llm.base_url`,
`llm.lanes.narration`, `llm.lanes.utility`, `llm.context_tokens`,
`llm.prefer_native` and `llm.profiles.big.{model, temperature, max_tokens,
reasoning_budget, reasoning}`, and `llm.api_key_origin`, which the supervisor
writes (§ The admin panel, Model server); a file with any other key (`hosting.*`
included, so it can never turn hosting on), or one that does not parse,
stops startup naming the file and the key. The doctor's `admin layer` rows
show its path and the keys it sets (never the values).

**Set each `llm.*` key in one place.** Your `CLOCKWORK_CONFIG` file outranks
the admin layer: a key set there wins over the panel's edit (the panel will
refuse to edit it, and the doctor warns per key both set). Keep the model
server's settings either in your file or in the panel, not both. A key (an
API key) never goes in either: put it in the environment or a key file
(docs/MODEL_SERVERS.md).

In the Docker image `CLOCKWORK_ENV` is `docker`, so `config/docker.yaml` is
the second layer, and `CLOCKWORK_CONFIG` is `/data/config.yaml` (§ Docker).

**The doctor, hosted.** With `hosting.enabled`, `python scripts/doctor.py`
adds these rows to its Config section (and asks no live process anything):

| Row | Says | FAIL / WARN |
|---|---|---|
| `hosting` | hosted, the front door's address, every request behind a login | WARN in the image when the front door binds the container's loopback (the published port reaches nothing) |
| `hosting block` | the `hosting:` block validates | FAIL naming the key that does not |
| `accounts` | how many are enabled | FAIL at zero: "nobody can log in: `python scripts/users.py add <name>`" |
| `secret key` | where the cookie key comes from (the environment, a config file, or the generated file's path) -- never the value | |
| `cookie_secure`, `public_origin`, `trusted_proxies` | their values | WARN when `cookie_secure` is false |
| `refusals` | the studio and the skills server off; the Settings panel read-only | FAIL for each startup refusal that would fire |
| `production server` | gunicorn, one gthread worker per process | WARN on Windows ("use Docker, or accept the development server for a trial"), or with gunicorn not installed |
| `llm.lanes` | each lane's size, and how to size `narration` for your server | |
| `hosting.threads`, `hosting.stories`, `admins`, `admin layer`, `metrics store` | as in § Orchestration and § The admin panel | |
| `storage` | the data root and whether it can be written | FAIL when not; in the image, naming the `chown` (§ Docker, `/data` ownership) |

## What hosted mode turns off

| Feature | Hosted | Why |
|---|---|---|
| Settings panel, `POST /api/settings` | 403, "Set by the server's operator."; `GET` still answers, with `writable: false` | a save rewrites the machine's `config/local.yaml` and resets every cache under other players' turns, and its keys describe the machine |
| The studio (`launcher.py --studio`, `CLOCKWORK_STUDIO=1`) | startup refused, naming `CLOCKWORK_STUDIO` | it writes to `games/` and resets caches |
| `llm.mcp.enabled: true` | startup refused, naming `llm.mcp.enabled` | the skills server opens its own port and edits LM Studio's `mcp.json` on this machine; it was built for one player |
| `/api/metrics` | 404, always | process-wide numbers about every player's turns |
| `launcher.py --stack` | unchanged | a service the operator runs is theirs |

"Refused" means the server does not start, rather than start with the
feature silently off: an operator who turned something on meant it. The
supervisor applies the same refusals itself before it starts any worker
(§ Orchestration), so the operator sees one error, not one per story.
