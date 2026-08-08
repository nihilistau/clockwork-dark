# The Clockwork Dark

A local-first AI roleplaying game where a deterministic engine holds truth and two autonomous LLM agents — the **Storyteller** and the **Assistant** — narrate a living frontier world.

You can become a baker in Edgewood and never learn the clock is ticking. Or you can march inward toward the Heartlands until the **Clockwork Dark** can no longer be ignored. The evil advances either way; that is the point.

**Status:** playable. PR1–PR12 and overhaul phases P1–P11 complete. 600+ tests passing, 1 expected failure (a real defect, recorded in [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) as R-01).

---

## Requirements

| | |
|---|---|
| **Python** | 3.13 |
| **LM Studio** | running at `http://localhost:1234/v1` with a chat model loaded. Without it the game runs but the Storyteller falls back to a canned line |
| **Node** | only if you want to rebuild the client. The built UI is committed |
| **GPU services** | all optional and all **off by default** — see below |

Everything else is local and offline. The shipped art pack means you get a
picture for every scene without a diffusion model running.

## Setup

```powershell
git clone <repo> clockwork-dark
cd clockwork-dark

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### LM Studio API key

If LM Studio's **"Require API key"** toggle is on, put the key in a file called
`lmstudio.txt` at the repository root:

```powershell
"lms-your-key-here" | Out-File -Encoding ascii lmstudio.txt
```

`lmstudio.txt` is gitignored. `config/default.yaml` reads it via
`${file:lmstudio.txt}`, falling back to the `LMSTUDIO_API_KEY` environment
variable. Leave both absent only if the toggle is off — otherwise every request
401s and the Storyteller silently falls back to a canned line, which looks
exactly like a very boring game.

### Machine-specific paths

Do not edit `config/default.yaml` to point at your own directories. Create
`config/local.yaml` instead; it is gitignored and deep-merges over the default.

```yaml
stack:
  services:
    voxtral_tts:
      root: "/path/to/voxtral-mini-realtime-rs"
```

### Check it

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py     # environment, config, content, data integrity
.\.venv\Scripts\python.exe launcher.py --check   # which local services are up, and what each outage costs
.\.venv\Scripts\python.exe -m pytest tests\ -q   # expect green, 1 xfail
```

`doctor.py` exits non-zero if something is actually broken. `launcher.py --check`
reports only what is down and what you lose without it — the game still runs
with all of it missing except LM Studio.

## Play

```powershell
.\.venv\Scripts\python.exe launcher.py clockwork
# open http://localhost:5573
```

Other launcher modes:

| Command | Effect |
|---------|--------|
| `launcher.py` | Play; warn about anything down |
| `launcher.py --stack` | Start the managed local services, wait for health, then play |
| `launcher.py --check` | Print the service status table and exit |
| `launcher.py --no-stack` | Skip the service check entirely |
| `launcher.py --list-games` | List installed games, with any manifest problems |
| `launcher.py --game <slug>` | Play a specific game |

## Games

The engine is story-agnostic; the story lives in `games/<slug>/game.yaml`, which
declares the content paths, and everything under it. Two ship:


| Slug | Story |
|------|-------|
| `clockwork-dark` | The Clockwork Dark — the flagship. Edgewood, the forest edge, the gear-rot |
| `wicked-garden` | The Wicked Garden — a fae court, ten mortal days a night, no combat and no dice |

The Wicked Garden is the one that proves the seam. It shares almost nothing
with the flagship: no HP, no hunger, no travel graph, no character classes, and
a state schema whose every value is bag-backed where the flagship's is a typed
dataclass. A second story that was the flagship with different nouns proved
only that nouns are replaceable.

```powershell
.\.venv\Scripts\python.exe launcher.py --list-games
.\.venv\Scripts\python.exe launcher.py --game wicked-garden
```

Selection order is `--game`, then the `CLOCKWORK_GAME` environment variable,
then `game.default` in `config/default.yaml`. Activation happens before any
content is imported, and saves are namespaced per game (`data/saves/<slug>/`)
so two stories cannot collide.

`scripts/start.ps1` creates the venv, installs requirements and runs the suite
before pointing you at the launcher.

## Optional local services

All off by default, each for a measured reason.

| Service | Config key | Default | Why |
|---------|-----------|---------|-----|
| Live image generation | `media.live_generation` | **off** | A Grok Imagine still takes 2–3 minutes, which cannot sit inside a real-time turn. Use `scripts/generate_art.py` to fill gaps ahead of time |
| ComfyUI `:8188` | `comfyui.enabled` | **off** | Seconds rather than minutes — the backend worth turning live generation on for |
| Spoken narration | `tts.enabled` | **off** | Measured at ~21× slower than realtime on the reference machine (73.9 s of compute for 3.44 s of audio) |
| Assistant voice only | `tts.assistant_enabled` | **off** | The companion's 1–3 sentence lines are the only thing worth speaking live |
| Push-to-talk (Voxtral ASR) | `stt.mode` | CLI | Shells out to the binary; there is no HTTP route for it |

With all of it off you still get: streamed narration, dice receipts, scene art
from the shipped pack, encounters, quests, and saves.

## Optional first-run extras

```powershell
.\.venv\Scripts\python.exe scripts\seed_lore.py       # ingest data/lore/*.md into the RAG index
.\.venv\Scripts\python.exe scripts\generate_art.py    # pre-generate art for gaps in the shipped pack
```

Seeding lore improves the Storyteller's grounding. Note that it currently also
triggers R-01 — see [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md).

## Rebuilding the client

The UI is Vite + React 18 in `ui/`, built into
`content/scenes/clockwork/static/dist`. **That build output is committed on
purpose** so playing the game does not require Node.

```powershell
cd ui
npm install
npm run build     # emits into content/scenes/clockwork/static/dist
npm run dev       # hot reload against the running Flask server
```

If you change anything under `ui/src/`, rebuild and commit the `dist` output in
the same change — otherwise the browser keeps serving the old client and nothing
you did appears.

## Balance harness

Headless, no LLM, three scripted policies. Run it before changing any balance
constant.

```powershell
.\.venv\Scripts\python.exe scripts\simulate.py --turns 200 --seed 42 --policy all
.\.venv\Scripts\python.exe scripts\simulate.py --policy baker --json > baseline.json
```

Reports the evil curve, day reached, stamina and hunger distributions, per-skill
success rates, gold drift, encounter frequency per dangerous leg, and quest
outcomes.

## Documentation

| Document | Audience | Purpose |
|----------|----------|---------|
| [docs/DESIGN.md](docs/DESIGN.md) | Architects, you | System design, story bible, mechanics, measured balance |
| [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) | Anyone picking this up | What the overhaul found, what it fixed, what is still open |
| [docs/CLAUDE_CODE_BRIEF.md](docs/CLAUDE_CODE_BRIEF.md) | Coding agents | Build spec and golden rules; historical sections marked **CURRENT:** |
| [docs/CLAUDE_DESIGN_BRIEF.md](docs/CLAUDE_DESIGN_BRIEF.md) | Design agents | Art direction, UI, generation prompts, audio |
| [CLAUDE.md](CLAUDE.md) | Coding agents | Onboarding pointer and the rules that are easiest to break by accident |

Where they disagree, the code wins, then DESIGN.md.

## Parent projects

Built by merging patterns from:

- [Archives of Anubis](https://github.com/nihilistau/Achieves-Of-Anubis) — hard engine + narrative council + RAG lore
- [CosySim](https://github.com/nihilistau/CosySim) — AgentGovernor, `@skill` tools, SSE tags, dual-agent scenes
