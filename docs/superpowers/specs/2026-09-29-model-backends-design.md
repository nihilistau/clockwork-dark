# Model backends — design (v0.19.0)

Status: **written 2026-09-29 against `main` at v0.18.0 (1a4b428), for the
owner-approved roadmap row "v0.19.0 — model-server agnostic"; revised the
same day against the opus design review
(`.superpowers/sdd/2026-09-29-v0.19.0-model-backends/design-review.md`) and
the controller's rulings on it.** Each section below records a decision and
the reason for it, not a menu of options. Where this file and the code later
disagree, the code wins (AGENTS.md authority order) and this file gets
corrected.

## Goal

The game narrates through any of five model servers, chosen by one config key:

| `llm.provider` | Server | Chat route(s) the engine uses |
|---|---|---|
| `lmstudio` | LM Studio 0.3.x (today's only backend, and still the default) | native `POST /api/v1/chat` + OpenAI-compatible `POST /v1/chat/completions`, routed exactly as today |
| `vllm` | vLLM's OpenAI server (`vllm serve`) | `POST /v1/chat/completions` |
| `llamacpp` | llama.cpp's `llama-server` | `POST /v1/chat/completions` |
| `ollama` | Ollama | native `POST /api/chat` |
| `openai_compat` | anything else that speaks `/v1/chat/completions` | `POST /v1/chat/completions` |

**LM Studio does not regress.** With the shipped config, or with any existing
`config/local.yaml`, every request LM Studio receives is byte-identical to
v0.18.0: the same route, body, headers, retry and probe, and every response
parses to the same `LMSResponse`. A golden test holds this (§9) from the
first task to the release.

v0.20.0 adds Linux and a hosted mode, so nothing here assumes the model server
is on loopback. A remote `https://` base URL with a bearer key read from the
environment is a supported configuration in v0.19.0. The engine just doesn't
host anything yet.

## Non-goals

- Hosting, per-user auth, sessions, Docker and Linux. All of that is v0.20.0.
- **More than one model server per process.** One `llm.provider` and one
  `llm.base_url` serve every profile. The registry, the lane gate, the
  structured-output probe and the health check are all per-process
  singletons. Doing two servers would multiply every one of them, and no
  owner requirement asks for it. It is recorded as **NOT WIRED** in
  `docs/GOVERNANCE.md`.
- An engine-side MCP/tool loop (§7).
- **Speech and images.** TTS (`tts:`), STT (`stt:`) and ComfyUI (`comfyui:`)
  keep their own endpoints and clients, untouched. "Model server" in this
  release means the chat model only; the `stack` rows for those services are
  unchanged.
- Any change to the turn grammar itself, to intents, or to prompt wording
  for LM Studio.
- **Live vLLM.** vLLM is built and tested against authored fixtures in
  v0.19.0 and verified live in v0.20.0 on Linux (owner decision,
  2026-09-29).
- Any content-rating layer (rule 12). A provider module carries transport
  facts only.

## Findings the survey turned up (fixed in this release)

The design was written against the code, and reading it found five defects
that the migration would otherwise carry forward:

1. **The documented env fallback for the API key doesn't exist.**
   `config/default.yaml` and README ("Setup") both say `${file:lmstudio.txt}`
   "falls back to the `LMSTUDIO_API_KEY` environment variable".
   `ConfigManager._expand` returns the caller's default when the file is
   absent. It never reads the environment. So a key set only in the
   environment is silently ignored today. §2.3 fixes it with an explicit
   fallback chain.
2. **The conftest guard has a hole for remote URLs.**
   `tests/conftest.py::_model_endpoints` skips any URL without an explicit
   port (`if port is None: continue`). A hosted `https://models.example`
   base URL would therefore not be guarded at all. It also reads
   `lmstudio.native_url` and `stack.health_url`, and neither key exists.
3. **The stack probe sniffs the port.** `engine/stack.py::probe` sends the
   bearer key only when the URL contains `1234` or `lmstudio`. Any other
   server that needs a key would be reported as "refuses every request".
4. **The planner hard-codes an OpenAI-shaped grammar.**
   `engine/agents/planner.py` builds `response_format` itself, as does
   `scripts/author.py` (line 1033). On LM Studio that grammar is right and
   stays always-on (§4.1): the planner never loses it, whatever
   `llm.structured_output` says. On Ollama the OpenAI shape is not a thing
   the server reads, so it has to be translated (§6).
5. **Without the grammar, `tool_calls` in the envelope are executed.**
   `storyteller.parse_storyteller_response` keeps any `tool_calls` array,
   and `run_turn` passes it to `tool_dispatcher.execute_tool_calls`
   (`storyteller.py` 934-937). With the grammar on, the array can't be
   sampled, because the schema declares no such property and sets
   `additionalProperties: false`. With the grammar off, which is LM Studio's
   `structured_output: off` today (and `auto` whenever the probe fails), and
   rungs 2 and 3 below, a narration turn can change the world through the
   very channel rule 1 forbids. §4.4 closes this by deleting the call.

Each fix ships with a test that fails against v0.18.0.

---

## §1 — Package and provider abstraction

### 1.1 Providers are added in place; `engine/lmstudio/` becomes `engine/llm/` last

**Decision.** Every provider module is first added **in place**, under
`engine/lmstudio/` (`providers.py`, `discovery.py`, `ollama.py`), beside the
unmoved `native.py`. The package moves to `engine/llm/` in one zero-logic
task, the **last code task** of the release (after health and the MCP gate,
before live verification), guarded by a golden test that has been stable
since the first task.

`engine/lmstudio/__init__.py` then stays as a shim. For each submodule it
sets `sys.modules["engine.lmstudio.<m>"]` to the `engine.llm` module object
**and** `setattr`s that module onto the shim package
(`engine.lmstudio.backend is engine.llm.backend`). The second half matters:
a `sys.modules` hit does not set the parent package's attribute, so without
it a dotted string patch such as
`monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", ...)` would
fail to resolve. Old and new paths therefore resolve to **the same module
objects**, by import and by attribute. Every in-repo import and every string
patch target moves to `engine.llm`. A test fails if any file outside the
shim and its own test names `engine.lmstudio` in an import **or in a string
literal** (the patch targets in `tests/test_lmstudio_health.py` are string
literals). Logger names follow the module (`engine.llm.*`); no `caplog`
filter depends on the old names. The shim is removed in v0.21.0, together
with the legacy config alias (§2). CLAUDE.md records that as a deferred row.

**Why rename.** After v0.19.0 the package serves five servers. A package
named after one of them is the naming version of rule 9's problem: it tells
a reader something that is no longer true. The cost is mechanical: 11
modules and 34 importing files (counted on 2026-09-29; `backend` is
imported 25 times, `registry` 18).

**Why last, not first.** Interleaving 34 files of import churn with the
tasks the golden test guards would make every golden failure ambiguous:
a moved import, or a changed request? Moving once the provider work is done,
with nothing else in the diff, makes the rename a pure rename that the
golden proves. If it has to slip, it slips to a zero-logic v0.19.1, and the
user-facing `llm:` config rename (§2) is unaffected.

**Why an identity shim and not re-exports.** `tests/conftest.py` patches
`ModelRegistry._fetch` and `NativeClient.is_available` by attribute. So do
several test files and the owner's local scripts. A re-export module would
create a second binding, and a patch through the old path would miss the
object the engine actually calls. That is the same hole class as the
"tests talking to LM Studio" finding. Aliasing in `sys.modules`, plus the
attribute on the package, makes a patch through either path the same patch.

**Module layout after the move** (before it, each file sits under
`engine/lmstudio/` with the same name, and `lmstudio_native.py` is still
`native.py`):

| Module | Role |
|---|---|
| `engine/llm/backend.py` | Router: transport choice, structured-output ladder, starvation retry, `chat_probe`, `get_backend()` |
| `engine/llm/client.py` | OpenAI-compatible transport (`LMSClient`), used by every provider except Ollama |
| `engine/llm/lmstudio_native.py` | LM Studio native `/api/v1/chat` (was `native.py`; `NativeClient`) |
| `engine/llm/ollama.py` | **new** — Ollama native `/api/chat` (`OllamaClient`, §6) |
| `engine/llm/providers.py` | **new** — the `Provider` table: the capability matrix as code (§1.2) |
| `engine/llm/discovery.py` | **new** — per-provider model-list parsers and declared capabilities (§3) |
| `engine/llm/registry.py` | Model registry and binding, fed by `discovery` |
| `engine/llm/profiles.py`, `gate.py`, `events.py`, `routes.py`, `schemas.py`, `tools.py` | Moved unchanged, except for the config keys they read |

**Class names stay** (`LMSClient`, `LMSResponse`, `LMSStreamEvent`,
`LMStudioBackend`). An alias `LLMBackend = LMStudioBackend` is added for new
code. Renaming the response types would touch every agent and test for no
change in behaviour. The docstring says the `LMS` prefix is historical.

### 1.2 The provider is a row in a table, not a subclass tree

**Decision.** `providers.py` defines a frozen `Provider` dataclass and a
`PROVIDERS: dict[str, Provider]` with one row per server. The backend,
clients, discovery, stack and doctor read capabilities from the row and
never branch on the provider's name. An unknown `llm.provider` raises at
config load and names the five legal values. The fields are:

| Field | `lmstudio` | `vllm` | `llamacpp` | `ollama` | `openai_compat` |
|---|---|---|---|---|---|
| `chat_transport` | `lmstudio_routed` (native when possible, compat for grammar/tools, v0.18 rule) | `compat` | `compat` | `ollama_native` | `compat` |
| `structured_output` | `json_schema` via compat; `json_object` sent as permissive `json_schema` (LM Studio rejects `json_object`) | `json_schema` (guided decoding); `json_object` native | `json_schema` (server converts to GBNF); `json_object` native | `format: <schema>` on `/api/chat`; `format: "json"` for object | probed: `json_schema`, then `json_object`, then none (§4) |
| `probe` | `lmstudio_v18` (today's `{ok: boolean}` probe, byte-identical) | `constraint_won` | `constraint_won` | `constraint_won` | `constraint_won` |
| `reasoning_off` | native `reasoning: "off"`, only where the registry says the model accepts it; compat ignores every knob | `chat_template_kwargs: {enable_thinking: false}` on the same request as the grammar | `chat_template_kwargs: {enable_thinking: false}` (needs `--jinja`) | `think: false`, only where `/api/show` lists `thinking` | none, unless `llm.reasoning_off_body` declares a body patch |
| `grammar_and_reasoning_off_together` | **no** (the root cause of the two-minute turn) | yes | yes | yes | only if declared |
| `inline_think` | `pass` (the server splits reasoning out itself; unchanged) | `strip` (unless served with `--reasoning-parser`) | `strip` (unless `--reasoning-format` is not `none`) | `strip` | `strip` |
| `discovery` | `GET /api/v1/models`, shape-checked (unchanged) | `GET /v1/models` (+ `max_model_len`) | `GET /v1/models` + `GET /props` (`n_ctx`) | `GET /api/tags` + `POST /api/show` per model | `GET /v1/models` ids; capabilities declared |
| `keep_alive` | `ttl` (seconds) on compat only (unchanged) | none | none | `keep_alive` (seconds) | none |
| `context_control` | server-side; `context_length` on native | server-side (`--max-model-len`) | server-side (`-c`) | **per request**: `options.num_ctx` | server-side |
| `auth` | bearer, optional | bearer (`--api-key`), optional | bearer (`--api-key`), optional | none locally; bearer passed through if set (reverse proxy) | bearer, optional |
| `inline_tools` | compat `tools=` | `tools=` (needs `--enable-auto-tool-choice`) | `tools=` (needs `--jinja`) | `tools` on `/api/chat` | `tools=` |
| `mcp_integrations` | **yes** (native `integrations`, `mcp.json` plugin) | no | no | no | no |
| `health` | `/api/v1/models` shape | `GET /health` then `/v1/models` shape | `GET /health` (`{"status":"ok"}`, 503 while loading) | `GET /api/version` then `/api/tags` shape | `/v1/models` shape (`{"object":"list","data":[...]}`) |
| `default_base_url` | `http://localhost:1234/v1` | `http://localhost:8000/v1` | `http://localhost:8080/v1` | `http://localhost:11434` | none (must be set) |

**Why a table.** Every row is a fact about someone else's server, and each
one can be pinned by a fixture (§9). A subclass per provider would spread
those facts across five `if`-shaped overrides of the same six methods. The
table is also the documentation. `docs/MODEL_SERVERS.md` is written by hand
and carries the same matrix, and a test asserts the document's table agrees
with `PROVIDERS` cell by cell. Generating it would add tooling for one
table; the drift test catches the same failure.

**Why the `vllm`/`llamacpp` rows exist beside `openai_compat`.** They differ
from a generic server in exactly the cells that decide whether a turn takes
20 seconds or two minutes (`reasoning_off`,
`grammar_and_reasoning_off_together`) and whether the budget is right
(`discovery`'s context). The generic row is the honest fallback: grammar
if a probe proves it, no reasoning control unless the owner declares one.

**How facts are verified.** A cell recorded from a live server in this
release is marked `verified="<server> <version>"` in the row. A cell taken
from the server's documentation is marked `verified=""`, and
`docs/MODEL_SERVERS.md` shows it as unverified. The live-verification task
runs Ollama and llama.cpp's `llama-server` on the owner's workstation
(owner decision, 2026-09-29); LM Studio is already verified by the golden.
vLLM's cells stay unverified until v0.20.0.

---

## §2 — Config migration

### 2.1 One provider-neutral block, `llm:`

**Decision.** `config/default.yaml`'s `lmstudio:` block becomes `llm:`. The
keys and comments stay as they are, with three changes:

```yaml
llm:
  provider: lmstudio               # lmstudio | vllm | llamacpp | ollama | openai_compat
  base_url: "http://localhost:1234/v1"
  api_key: "${file:llm_api_key.txt|file:lmstudio.txt|env:CLOCKWORK_LLM_API_KEY|env:LMSTUDIO_API_KEY}"
  keep_alive_seconds: 900          # was ttl_seconds; LM Studio `ttl`, Ollama `keep_alive`
  declared_models: {}              # §3.2
  reasoning_off_body: {}           # openai_compat only: the body patch that turns thinking off
  prefer_native: true              # LM Studio only; ignored elsewhere (doctor says so)
  # context_tokens, reserve_output, timeout_seconds, structured_output,
  # lanes, profiles, models (legacy id map), mcp -- unchanged, moved
```

`stack.services.lmstudio` becomes `stack.services.llm`, and its
`health_url` defaults to empty, meaning "derive from the provider row"
(§8).

**Why flat, with provider-only keys documented as such.** A nested
`llm.lmstudio.prefer_native` would turn the legacy alias from a prefix
rename into a key-by-key map. It would also make a user's
`lmstudio.prefer_native: false` land somewhere new. Two keys are
provider-specific (`prefer_native`, `mcp`), and one is generic-only
(`reasoning_off_body`). The doctor says in one line when a set key is
ignored by the chosen provider.

### 2.2 Old configs keep working: a per-layer alias

**Decision.** `engine/config.py::get_config` renames each layer's `lmstudio:`
block to `llm:` **before** that layer is deep-merged: default, env,
`local.yaml` and the game overlay. Inside the renamed block it maps
`ttl_seconds` to `keep_alive_seconds`, and it renames
`stack.services.lmstudio` to `stack.services.llm`. If one layer holds both
blocks, the legacy block is deep-merged **under** `llm:` inside that layer:
`llm:` wins on any key both set, and a key only the legacy block sets is
kept, not discarded. Each aliased layer logs one WARNING naming the file and
the rename. The doctor adds a `Config / legacy lmstudio: block` WARN row
naming the file.

The read side is aliased too, so an owner's script keeps working:
`ConfigManager.get("lmstudio.x")` and `section("lmstudio.x")` are answered
from `llm.x`, and `get("lmstudio.ttl_seconds")` from
`llm.keep_alive_seconds`. `as_dict()` returns the migrated tree, which has
an `llm:` key and no `lmstudio:` key; a test pins that. A test asserts that
no engine or script source still reads a `lmstudio.` key, outside the alias
table.

**Why per layer and not a fallback read.** Precedence must survive the
rename. The shipped default will carry `llm.base_url`, and a user's
`local.yaml` still carries `lmstudio.base_url`. The user's value has to
win, as it does today. A read-time "try `llm.`, else `lmstudio.`" gets
this backwards, because the default's `llm.` key always exists.

**The other writers and readers of the old key.**
- **The Settings panel** (`engine/api/settings.py`) writes the new keys
  (`llm.profiles.big.*`, `llm.context_tokens`, `llm.prefer_native`). When
  it rewrites `config/local.yaml`, which it already does atomically, it
  moves that file's `lmstudio:` block to `llm:` by the same merge rule.
  The legacy block is then migrated the first time the player saves a
  setting. "Use LM Studio's native endpoint" is listed only when
  `llm.provider` is `lmstudio`.
- **`scripts/two_phase_live_proof.py`** (line 70) writes an `mcp` block
  into the owner's real `local.yaml` through `setdefault("lmstudio", {})`.
  It writes `llm:` instead, so it never plants a legacy block beside a
  migrated one.
- **`engine/games/manifest.py::SETTING_REFUSALS`** refuses a story's
  `settings: {lmstudio: ...}` with a reason. It gains an `llm` row with the
  same reason, and keeps the `lmstudio` row, so a story can declare neither.
- **The client's outage line** (`ui/src/core/store.js`, "check LM Studio is
  running") names "the model server". That is the release's one UI change:
  the committed `dist` is rebuilt in the same commit.

**Removal.** The alias and the `engine.lmstudio` shim are both removed in
v0.21.0. CLAUDE.md carries the deferred row, and the CHANGELOG says so.

### 2.3 Secrets: an explicit fallback chain

**Decision.** `${...}` gains `|`-separated alternatives, tried left to
right. Each one is `file:<path>` (first line, stripped), `env:<NAME>` or a
bare `NAME` (environment, as today). The first non-empty value wins. The
split happens only when the token contains `|`: a token without one is
resolved exactly as in v0.18. Expansion stays lazy, in `get()`
(`config.py` line 160), so the chain is tried each time the key is read,
not once at load; a test sets the environment variable after the config is
built and sees it. The shipped `api_key` tries `llm_api_key.txt`, then
`lmstudio.txt`, then `CLOCKWORK_LLM_API_KEY`, then `LMSTUDIO_API_KEY`. That
makes the fallback README already promises true, and keeps every existing
`lmstudio.txt` working. `llm_api_key.txt` joins `.gitignore`. No key is
ever written to a tracked file, logged, or put in a URL (rule 5). The
doctor reports only the key's length, as today.

**Why a chain rather than a second key.** A hosted v0.20 deployment
configures a secret through the environment, and a desktop user drops a
file. One expression covers both, and a shipped comment can say exactly
what is tried.

---

## §3 — Model discovery without `/api/v1/models`

### 3.1 Every provider feeds the same `ModelInfo`

**Decision.** `discovery.py` has one parser per provider row. Each turns
that server's model list into the existing `ModelInfo` dataclass, which
gains `source: str`, always naming the parser (`lmstudio_v1`,
`openai_models`, `llamacpp_props`, `ollama_show`), and `declared_fields`,
recording what a declaration (§3.2) filled that the server left empty
(`context`, `tools`, `reasoning`, `reasoning_default`); a declaration never
changes `source`. `ModelRegistry.refresh` calls
`discovery.list_models(provider, fetch)`, where `fetch` is still
`ModelRegistry._fetch`. The conftest pin therefore keeps working for every
provider. Its stub returns `provider.empty_model_list()` instead of the
LM Studio-shaped `{"models": []}`. Binding (`ModelRegistry.bind`),
profiles, the denylist and the ranking are all unchanged.

What each parser can fill in:

| Provider | `id` | `usable_context` | `supports_tools` | reasoning knob (`reasoning_configurable`, options) | `state` |
|---|---|---|---|---|---|
| `lmstudio` | yes | loaded context | `tool_use` | `capabilities.reasoning` | loaded / not-loaded |
| `vllm` | yes | `max_model_len` | declared | declared | always loaded |
| `llamacpp` | yes | `/props` `default_generation_settings.n_ctx` | declared | declared | always loaded |
| `ollama` | yes | the `num_ctx` the engine will send (§6), capped by `/api/show`'s `<arch>.context_length` | `capabilities` has `tools` | `capabilities` has `thinking` → `["off","on"]` | per `/api/ps`, else not-loaded |
| `openai_compat` | yes | `max_model_len` if the server reports it, else declared, else `llm.context_tokens` | declared | declared | always loaded |

The context precedence is the same for every provider: **reported (served
or loaded) > declared > `llm.context_tokens`**. A trained or advertised
window (llama-server's `n_ctx_train`, an unloaded LM Studio model's maximum)
is not a reported served number, and a declaration beats it.

`NotV1Models` becomes `NotAModelList(provider, body)`, and `NotV1Models`
stays as an alias. The shape check applies to every provider: a 200 whose
body isn't that server's list is a failure (the v0.2 lesson about
"returning 200 anyway").

### 3.2 Declared capabilities fill what the server does not say

**Decision.** `llm.declared_models` maps a model id to the facts the server
can't report:

```yaml
llm:
  declared_models:
    "Qwen/Qwen3-8B":
      context: 32768
      tools: true
      reasoning: ["off", "on"]        # the knob exists; values it accepts
      reasoning_default: "on"
```

A declaration fills only the fields the server left empty. A
server-reported loaded context always wins over a declared one, because
the loaded number is the one that truncates (the LM Studio lesson in
`ModelInfo.usable_context`). A declared id the server doesn't list is
ignored with a warning, and nothing binds to it. Explicit model ids per
profile keep working unchanged (`llm.profiles.<name>.model`, then the
legacy `llm.models.<name>`), and they are the recommended setup for vLLM
and llama-server, which serve one model.

A declaration is also what makes a reasoning-off patch **trusted** (§5.2):
`reasoning` listing `off` is the owner saying "this model's template
honours the patch".

**Why not declarations alone.** `/v1/models` is served by every one of
the five servers, and it is the only way to tell a typo'd model id from a
real one before the first turn 400s. The v0.18 doctor's "model not
confirmed against the server" row exists because of exactly that failure.

**Why not guess capabilities from the id.** `REASONING_ARCHES` already
guesses from LM Studio's `arch`. Nothing like `arch` exists in
`/v1/models`. A regex on model names would be a fact nobody measured.
`is_reasoning` for a non-LM Studio model therefore reads
`reasoning_default == "on"` from the declaration or from Ollama's
`thinking` capability, and nothing else.

---

## §4 — Structured output, and how the turn grammar is enforced

### 4.1 The ladder

**Decision.** `backend.structured_output(schema)` resolves a mode per
process, from `llm.structured_output` (`auto | json_schema | json_object |
off`) and the provider row:

1. **`json_schema`** — the full strict schema, in the provider's wire form:
   `response_format: {type: json_schema, json_schema: {name, strict,
   schema}}` on compat, `format: <schema>` on Ollama.
2. **`json_object`** — valid JSON, shape free. The provider's native form:
   permissive `json_schema` on LM Studio (unchanged), `{"type":
   "json_object"}` on vLLM, llama-server and generic, `format: "json"` on
   Ollama.
3. **none** — no grammar on the wire.

`auto` probes once per process, as today. On every `constraint_won` row
(vLLM, llama-server, Ollama and a generic server alike -- no cell tells them
apart, and nothing branches on a provider's name) a failed `json_schema`
probe is followed by a second probe for rung 2, and a server that accepts
neither lands on rung 3 (amended in T4's fix round, as built in
`backend._probe_ladder`). On LM Studio `auto` behaves exactly as in
v0.18: a failed probe means no grammar. The probe result is logged, and the
doctor reports it ("grammar: json_schema | json_object | none").

**The probe is per provider row** (`Provider.probe`):
- **`lmstudio_v18`** — LM Studio's probe is **byte-identical** to v0.18
  (`backend.py` 236-250: the `{ok: boolean}` schema, the same prompt, the
  same `'"ok"' in content` acceptance). The golden test pins it, answering
  yes and answering no.
- **`constraint_won`** — every other provider's `json_schema` probe sends a
  schema built from the three constructs the turn schema depends on:
  `{"answer": {"anyOf": [{"type": "string", "enum": ["yes"]}]}}`, required,
  `additionalProperties: false`. Its prompt asks for a value **outside**
  that schema: `Reply with exactly {"answer": "no", "note": "free"}`. The
  probe passes only if the reply parses to exactly `{"answer": "yes"}`, that
  is, only if the constraint beat the prompt. A server that accepts the
  request but ignores the grammar echoes the prompt and fails, which
  today's `'"ok"' in content` check cannot tell apart. The `json_object`
  probe asks for a one-sentence prose answer and passes only if the reply
  parses as a JSON object.

  *Amended in T8, from the live Ollama run:* both `constraint_won` probes
  ask for reasoning `off` (the row's patch, trusted or not), keeping the
  reasoning budget in their cap. Sent `think: true`, Ollama's `qwen3:4b`
  thought past the probe's cap and a server that enforces `format` was put
  on rung 3; with the patch beside the grammar, the grammar binds from the
  first token on both Ollama 0.34.4 and llama-server b7966, even on a
  template that ignores the patch. LM Studio's `lmstudio_v18` probe is
  untouched.

**The planner keeps its grammar on LM Studio, always.** Today
`planner.py` (line 205) sends its `json_schema` whatever
`llm.structured_output` says, including `off` (which `default.yaml`
recommends for reasoning models) and a failed probe. That stays: on the
`lmstudio` row the planner's request is byte-identical, and the golden
test proves it under `auto` (probe yes and no) and under `off`. On the
other rows the planner's `response_format` is sent in the provider's wire
form (Ollama translates it, §6), at the rung the ladder resolved; on rung 3
the planner's existing parse-failure path answers.

**`scripts/author.py`** builds its own `response_format` (line 1033) and
keeps doing so: an authoring tool must always send its schema, and fails
loudly if the JSON doesn't decode. It is not routed through the ladder. On
Ollama the client translates it (§6); on the compat providers it goes on
the wire as written.

### 4.2 Without the full grammar, the prompt carries the shape

**Decision.** When a request has a schema but the resolved rung is 2 or 3,
the backend appends one **format block** to the system message: a compact
rendering of the schema (`schemas.render_format_block(schema)`) that names
the envelope's keys, the choice ids, the hint enum, and for each intent
verb its legal targets. On rung 1 nothing is appended, so a
`json_schema`-capable LM Studio turn is byte-identical.

**On LM Studio only under `structured_output: off`** (amended in T4's fix
round, as built in `backend.format_block_due`). LM Studio's rung 2 (its
permissive `json_object`) and the turn after a failed `auto` probe (rung 3)
send no block: the golden pins both requests to v0.18's bytes (scenarios 05
and 08), and `off` is the one sanctioned difference. Every other provider
gets the block on rungs 2 and 3. The reply is conformed (§4.4) on every
rung, LM Studio's included.

**Why.** The v0.18 config comment records what happens with no grammar:
the model writes prose, "the three authored choices collapse to the
generic 'Look around / Continue' fallback and nothing streams". The prompt
side says "No output-format instructions. The JSON schema carries the
contract now" (`engine/agents/prompts.py`). That holds only while the
schema is on the wire. When it isn't, the contract has to travel as text
or not at all. This also improves an LM Studio user who sets
`structured_output: off` today: their turns gain the block. That is the
release's one recorded behaviour change on LM Studio. The golden set
records the v0.18 `off` request, and its test asserts that the only
difference is exactly the rendered block appended to the system message;
the fixture itself is never re-recorded.

### 4.3 The narration envelope still parses

The streaming path (`NarrationStreamer`, `json_stream.extract_json`) already
tolerates fenced JSON and leading prose, and on a derailed or broken
envelope it falls back to the authored-choice fallback. None of that
changes. A test feeds each provider's fixture streaming response (§9)
through `Storyteller._infer` and asserts the narration and choices come
out. On rung 3 it also covers a response wrapped in a fenced ```json
block.

### 4.4 Rule 1 on each rung

AGENTS.md rule 1 has two halves, and each rung keeps them this way:

| Rung | "An illegal target is unsamplable" | "An illegal-at-execution intent is refused in the prose" |
|---|---|---|
| 1 (`json_schema`: LM Studio, vLLM, llama-server, Ollama `format`, a generic server that passed the probe) | **Holds as today.** The per-turn `intent` enums and `additionalProperties: false` go into the grammar. On the non-LM Studio rows the `constraint_won` probe (§4.1) has shown the server enforces `enum`, `anyOf` and `additionalProperties`. | Holds (`execute_intent`, unchanged) |
| 2 (`json_object`) | **Downgraded to "unoffered".** The model can write an intent the catalogue doesn't contain. `schemas.conform` (below) drops that whole choice before the player sees it. It is never offered, so it is never executed. | Holds, unchanged. The refusal reaches the narrator as today. |
| 3 (none) | Same as rung 2. An envelope that doesn't parse yields no intents at all, and the turn falls back to the authored choices. | Holds |

**Narration never executes `tool_calls`, on any rung.** The call to
`execute_tool_calls` in `Storyteller.run_turn` (`storyteller.py` 934-937 at v0.18.0)
is deleted (finding 5): narration has no legitimate `tool_calls` on any
rung, because intents are the channel (rule 1). `tool_receipts` keeps the
intent receipts (`resolved`). The dispatcher itself is unchanged and keeps
its production caller (`engine/agents/assistant.py`). The tests that drove
a `tool_calls` array through `run_turn`
(`tests/test_storyteller.py::test_the_tool_dispatcher_executes_a_move_when_it_is_handed_one`,
and in `tests/test_turn_integration.py`
`test_the_dispatcher_executes_a_move_it_is_handed`,
`test_system_only_skill_is_refused_from_the_model` and
`test_malformed_tool_args_do_not_break_the_turn`, since renamed
`test_malformed_tool_args_are_a_failed_receipt`) are retargeted to call
`execute_tool_calls` directly, which is what their names already say they
test; a new test asserts a `run_turn` whose reply carries `tool_calls`
under `structured_output: off` leaves the player where they were.

**The parsed envelope is conformed to the schema that was built, on every
rung.** New: `schemas.conform(parsed, schema)` runs in
`Storyteller.run_turn` right after `parse_storyteller_response`. It drops:
- any top-level key the schema doesn't declare;
- **any whole choice** whose `intent` has a verb or target outside that
  turn's enums. Stripping only the intent would leave a choice whose text
  promises a walk that no mechanic performs and nothing refuses, which is
  itself a rule-1 breach;
- any `npc_id` outside the present-NPC enum.

It also holds every other declared key to its schema recursively
(`ledger_delta`: wrong types, undeclared keys, missing required keys,
`maxItems`), cuts the choices at `maxItems` (four), and keeps what it took off
the top level under `conformed_away`, where governance R003 and the
evaluator's skill-check gate read a model's claims (`schemas.claimed`)
(amended in T4's fix round).

If fewer than two choices survive, `conform` tops the list up with the
generic rows `parse_storyteller_response` already uses when an envelope
fails ("Look around", "Continue"; factored into one `_FALLBACK_CHOICES`
constant in `storyteller.py`), which carry no intent. On rung 1 the grammar
has already made every one of those unsamplable, so `conform` is a no-op
there, and the golden test stays byte-identical. Anything it drops is
logged with the key or choice named, never silently. The engine sends no
`tools=` on a narration turn on any provider. The doctor rates rung 2 or 3
as **WARN** ("choices are validated after the fact, not constrained").
Rung 1 is OK.

**Why this is enough.** Rule 1's guarantee to the player is "never read
that you walked somewhere you didn't". That half is enforced at
execution on every rung. The grammar half is an efficiency (no wasted
option slot), and a server that can't do it pays in choice quality, not
in correctness.

### 4.5 Inline `<think>` never reaches the content channel

vLLM without `--reasoning-parser`, and `llama-server` with
`--reasoning-format none`, send a reasoning model's thinking inline in
`content`, wrapped in `<think>…</think>`. Left there it reaches
`NarrationStreamer` and the tag buffer, and an `[IMAGE:]` written while
thinking would fire a real image generation.

**Decision.** On every row whose `inline_think` is `strip`, the client
moves a leading `<think>…</think>` span (streamed or not, split across
deltas or not) from the content channel to the reasoning channel before
anything downstream sees it. An unclosed `<think>` at the end of a
response is reasoning, not content, so the response reads as starved, not
as narration. The `lmstudio` row is `pass`: LM Studio splits reasoning
itself, and its parsed responses stay byte-identical. The doctor shows a
WARN when a probe response arrives with inline `<think>`, naming the server
flag that fixes it (`--reasoning-parser` for vLLM, `--reasoning-format` for
`llama-server`).

*Amended in T8 (measured on llama-server b7966).* A template that opens
`<think>` in the PROMPT makes the model's first token already thinking, so
when the server does not split it out (`--reasoning-format none`, or a
request carrying the reasoning-off patch the model ignored) the content is
`thinking</think>answer`, with no opening tag. The splitter's `hold` mode
releases nothing until that is decided, and text up to a `</think>` no
`<think>` opened is reasoning. A whole (non-streamed) answer is always read
held, at no cost. A stream is held only when its request carried an
UNTRUSTED patch (`forced_open`) and NO grammar (fix round 1), since holding
shows the player nothing until the stream ends, and under a grammar the
thinking cannot reach the content (llama-server binds the grammar from the
first token; Ollama sends it in `message.thinking`). So the remaining cost
is an ungrammared `off` stream to an undeclared model, which is shown only
when done. Under `forced_open` a `<think>` the thinking mentions before its
orphan close does not cancel it, and an answer cut at the cap with no
`</think>` is unclosed thinking and reads as starved -- unless the request
carried a grammar and it starts as JSON, which is then kept as a cut answer;
without a grammar a cut answer, prose or JSON, is the accepted loss (T9).
`--reasoning-format none` with such a template is documented as not to be
run.

---

## §5 — Reasoning control and the starvation retry

### 5.1 One question per request: can this route turn thinking off?

**Decision.** `Provider.reasoning_off_patch(model_info, route) ->
ReasoningPatch | None` returns the body fragment that turns reasoning off
on that route, and whether it is **trusted**, or `None` if nothing on that
route can:

- `lmstudio`: `{"reasoning": "off"}` on native only, gated by the
  registry's `accepts_reasoning("off")` (today's `reasoning_for`). Trusted:
  the server reported the knob. Compat gets `None`.
- `vllm`, `llamacpp`: `{"chat_template_kwargs": {"enable_thinking": false}}`.
  Trusted when the model's declared `reasoning` includes `off`. **Sent
  but untrusted** when no declaration exists: a template without that
  variable ignores it (gpt-oss and the R1 distills do), so the patch may
  help, but nothing may rely on it. If a declaration exists and excludes
  `off`, the result is `None`.

  *Amended in T8, from the live llama-server run (b7966).* A verified
  `reasoning_off` cell no longer makes the patch trusted: the cell proves
  the SERVER passes the patch to the template, and whether the template
  honours it is the model's (Qwen3-0.6B's does; Qwen3-4B-Thinking-2507's,
  which opens `<think>` in the prompt, does not). Nor does an ignored patch
  cost nothing: the server, told thinking is off, stops splitting it out,
  and the thinking arrives in `content` with no opening tag, then
  `</think>`, then the answer. So the client reads the answer to an
  untrusted patch knowing that (§4.5, amended).
- `ollama`: `{"think": false}` when `/api/show` lists `thinking`, else
  `None` (Ollama answers 400 to `think` on a model without the
  capability, the same class as LM Studio's "does not expose reasoning
  configuration"). ~~Trusted: the server reported the capability.~~
  *Amended in T8, from the live run (Ollama 0.34.4):* trusted only when a
  declaration lists `off`. `thinking` says a knob exists, not that the
  template honours `think: false`: the library's own `qwen3:4b` (a
  Thinking-2507 build) reports it and thinks anyway, into `content`, closed
  by an orphan `</think>` -- the llama-server shape, read the same way.
- `openai_compat`: `llm.reasoning_off_body` if set, trusted (the owner
  declared it), else `None`.

The profile's `reasoning` mode goes on the wire through the same function.
`on` sends nothing on compat providers and `think: true` on Ollama.

### 5.2 The wire cap follows what the route will honour

`client.compat_cap` today always adds the reasoning budget, because LM
Studio's compat route ignores `off`. **Decision:** the cap becomes
`wire_cap(content, reasoning_budget, mode if patch_trusted else "on")`. The
budget is dropped only when a **trusted** patch went on the wire. An
untrusted patch keeps the full "on" cap, so a template that ignores
`enable_thinking` still has room to think and then answer. On LM Studio
compat no patch is ever applied, so the number is unchanged (golden). On
Ollama, and on vLLM or llama-server with a declaration, an `off` request
asks for the content budget alone, which is what the native LM Studio
route already does.

**Why not trust the patch by default.** With the patch sent and the budget
dropped, a model whose template ignores the variable thinks into a cap
sized for content alone and starves on every turn. These servers report no
reasoning-token count, so the measured-room retry stands down every time.
Slower turns on a server that honours the patch, until someone declares
it, is the cheaper failure.

### 5.3 The starvation retry

`LMSResponse.starved_by_reasoning` is unchanged. **Decision:**
`_retry_without_reasoning` asks the provider for a route on which it can
send `off` **with the same grammar the starved request carried**, and
**never repeats the request that just starved**:

| Provider | Retry |
|---|---|
| `lmstudio` | Unchanged: native, `reasoning: "off"`, no grammar (native can't take one), else `_retry_with_room`, else stand down |
| `vllm`, `llamacpp` | If the starved request did **not** carry the patch: the same compat request, same `response_format`, plus the patch (the grammar survives the retry, which LM Studio can't offer), cap per §5.2. If it **already** carried the patch: `_retry_with_room`, else stand down. |
| `ollama` | If the starved request did not carry `think: false`: the same `/api/chat` request, same `format`, `think: false`. If it did: `_retry_with_room`, else stand down. |
| `openai_compat` | The declared patch if the starved request lacked it, else `_retry_with_room` (measured room), else stand down |

`_retry_with_room` is unchanged, including standing down when the starved
response reported no reasoning-token count. vLLM, llama-server and Ollama
don't report `reasoning_tokens` separately, so on those servers the
reasoning-off patch is the whole net, and a request that starved with the
patch already on stands down at once with the existing error log. That log
now names the fixes: declare the model's `reasoning` (so the patch is
trusted and the cap right), declare `reasoning_off_body` on a generic
server, or raise `max_tokens`. Estimating tokens from reasoning characters
would be a magic multiplier, which the v0.2 docstring rules out. A test
asserts a stand-down sends zero further requests.

The storyteller's own streamed-starvation recovery (`storyteller._infer`)
goes through the same rules (amended in T4's fix round:
`backend.recover_starved`). On LM Studio it is v0.18's call, byte for byte:
one non-streamed request with `reasoning="off"` and
`retry_on_starvation=False` (golden 16). On a compat row it is the table
above, given the mode the stream ran in: a stream that already carried the
patch, or one on a row with no patch, is never re-sent identically.

---

## §6 — Ollama gets a native transport

**Decision.** `ollama.py::OllamaClient` speaks `POST /api/chat` for every
Ollama request, streaming (NDJSON) and non-streaming, with `chat()` /
`chat_stream()` / `is_available()` signatures that match `LMSClient`, and
it returns the same `LMSResponse` / `LMSStreamEvent`. Here is how the
request fields map:

- `messages` → `messages` (OpenAI roles pass through)
- `format` ← §4 rung. A caller that passes an OpenAI-shaped
  `response_format` itself (the planner, `scripts/author.py`) is translated:
  `{type: json_schema, json_schema: {schema}}` → `format: <schema>`,
  `{type: json_object}` → `format: "json"`. Anything else is refused with a
  logged error naming the caller's label, never silently dropped.
- `think` ← §5.1
- `options.temperature`
- `options.num_predict` ← `wire_cap`
- `options.num_ctx` ← the profile's bound context (§3.1)
- `keep_alive` ← `llm.keep_alive_seconds`
- `tools` passes through
- `message.thinking` goes to the reasoning channel (`on_reasoning`, `reasoning.*` events); inline `<think>` in `message.content` is stripped to it too (§4.5)
- `done_reason: "length"` maps to `finish_reason: "length"`
- `prompt_eval_count` / `eval_count` map to token counts

**Why not Ollama's `/v1/chat/completions`.** That route can't set
`num_ctx`. Ollama's default context is a few thousand tokens, and it
truncates a longer prompt from the front, silently. That is the same
defect that once dropped the system persona on LM Studio
(`reserve_output`'s comment). The compat route's reasoning control is
also less direct than `think`. The native route takes grammar, `think`,
`num_ctx` and tools together in one request, which makes it strictly
better than compat for this engine. The cost is one transport of about
300 lines, mirroring `native.py`'s event translation.

---

## §7 — The MCP tool loop stays LM Studio-only

**Decision.** `llm.mcp` (the two-phase turn's Phase A,
`engine/mcp/skills_server.py`, `engine/agents/mechanics.py`) runs only when
the provider row has `mcp_integrations`, which only `lmstudio` does. It is
off by default, as it is today. With another provider and
`mcp.enabled: true`, `mechanics.mechanics_enabled()` (`mechanics.py` line
128) returns False and logs one ERROR, once per process, naming the reason.
The doctor shows a FAIL row, "`llm.mcp.enabled` is set but `<provider>` has
no MCP integrations; Phase A is off". The turn falls back to the payload it
sends with MCP off, which is byte-identical by existing test. A **NOT
WIRED** row goes into `docs/GOVERNANCE.md`:
"engine-side tool loop for non-LM Studio providers —
`engine/agents/mechanics.py`".

**Why not an engine-side loop.** The feature is off by default and has
been proven live only against LM Studio's server-side loop. An engine-run
tool loop (`tools=` → execute → append `tool` messages → repeat) is a new
turn phase with its own budgets, its own failure modes and its own audit
questions. Building it for a flag nobody has turned on would be a whole
release of untested surface. Intents (rule 1) remain the production
channel for mechanics on every provider.

---

## §8 — Availability, launcher `--check` / `--stack` and the doctor

**Decision.**

- **"Is the model server up?" asks the provider.** `LMSClient.is_available`
  (`client.py` 243-262) probes `/api/v1/models` today, which only LM Studio
  serves. It gates the summarizer (`engine/scenes/default_state.py` line
  744), so on any other server the running summary would silently fall back
  to deterministic compression forever. It now delegates to the provider
  row's health probe (below); on `lmstudio` that probe is today's request,
  byte-identical (golden). `OllamaClient.is_available` is the same probe.
  Phase A's gate (`mechanics.py` line 304) keeps
  `NativeClient.is_available`: it is reached only when
  `mechanics_enabled()` is true, which means the `lmstudio` row, and there
  the native route is the right question.
- **The service is `llm`.** `stack.services.llm` (with the legacy alias)
  has `manage: false` by default and `health_url: ""`. An empty
  `health_url` on this service means `Provider.health_probe(base_url)`,
  which runs the provider row's health check, including the shape check
  against the 200-for-anything failure. An explicit `health_url` keeps
  today's generic probe. With the default LM Studio config the probe URL
  is still `http://localhost:1234/api/v1/models`, and the check is
  byte-identical.
- **`manage: true` needs no new code.** A user who wants the stack to
  start `llama-server` or `vllm serve` sets `command`/`args`/`root` like
  any other managed service. `docs/MODEL_SERVERS.md` shows a
  `llama-server` example. Linux service management is v0.20.
- **The model server is the one FAIL-level service**, whatever its
  provider. `scripts/doctor.py::check_services` and `launcher.py::_report`
  treat the `llm` service, and the legacy `lmstudio` name, as FAIL. Their
  consequence text says "the model server" instead of "LM Studio" for
  every provider but `lmstudio`, whose text is byte-identical.
- **The key is sent to the configured origin, not to port 1234.**
  `stack.probe` attaches the bearer key when the probed URL's scheme,
  host and port match `llm.base_url`'s (finding 3).
- **The doctor's section** is named after the provider: `LM Studio` stays
  `LM Studio` (byte-identical output, against the baseline recorded in the
  golden task), and the others are shown as `Model server (vllm)` and so
  on. It has these rows:
  - liveness: the provider's health probe;
  - model bound: unchanged;
  - chat probe: `chat_probe` on the real path, unchanged;
  - the provider's transport row. For LM Studio that is the native
    availability row, as today. For the others it is a "reasoning off:
    `<patch>` (trusted | untrusted) | unavailable" row;
  - grammar rung (§4.4);
  - inline `<think>` seen (§4.5), WARN, naming the server flag;
  - any set config key the provider ignores (§2.1);
  - the MCP row (§7).
- **`scripts/start.ps1`** (line 29) stops printing "LM Studio expected at
  http://localhost:1234/v1" and prints the configured provider and base
  URL instead.

---

## §9 — Testing

1. **The LM Studio golden** (`tests/test_llm_golden_lmstudio.py`, the
   first task). Before anything moves, a recorder captures the exact
   requests v0.18.0 sends, **on untouched 1a4b428 code**, by patching
   `httpx.HTTPTransport.handle_request`. That one seam sees every request,
   including the module-level `httpx.get` / `httpx.post` calls
   (`registry.py` 339 and 395, `stack.py` 160), which take no transport
   argument; no engine file changes to make recording possible. Each
   request is captured as method, URL, headers and body bytes (canonical
   JSON), and each scenario's response is also captured **as parsed**: the
   `LMSResponse` (content, reasoning, finish reason, token counts, tool
   calls) or the stream's `LMSStreamEvent` sequence. Later tasks edit
   `client.py`, so the parse is pinned as well as the wire.

   **The config is pinned, and goes through the real layers.** The harness
   points `engine.config._CONFIG_DIR` (and `_DEFAULT_PATH`, at the repo's
   real `default.yaml`, so later changes to it are exercised) at a temp
   directory, deletes `CLOCKWORK_LLM_API_KEY`, `LMSTUDIO_API_KEY` and
   `CLOCKWORK_ENV` from the environment, and writes a temp `local.yaml`
   that sets the API key to a fixed test value. The recorded
   `Authorization` header is therefore the same on every machine, whether
   or not it holds a `lmstudio.txt`. The **legacy variant** writes a
   v0.18-shaped `local.yaml` (`lmstudio.base_url`,
   `lmstudio.profiles.big.temperature`, `lmstudio.ttl_seconds`, the key)
   through the same real layer loader, not through `set_overlay`, and
   matches its own fixtures, also recorded on v0.18.0.

   It covers:
   - a streamed narration turn with the real schema, `structured_output:
     auto`, the probe answering yes, for the flagship and for HUE & CRY;
   - the non-streamed turn;
   - turns under `structured_output: json_schema`, `json_object` and
     `off` (the `off` fixture is the one whose later diff is sanctioned,
     exactly the §4.2 block);
   - the probe answering yes, and answering no (and the turn that follows
     it, sent with no grammar);
   - a planner call, under `auto` and under `off`;
   - a native utility chat;
   - native unavailable (the conftest default): the same utility chat on
     compat;
   - both starvation retries (off, and measured room), and a stand-down
     that sends zero further requests;
   - the storyteller's streamed-starvation recovery call;
   - `chat_probe` on both paths;
   - discovery (`ModelRegistry.refresh`) and `NativeClient.is_available`;
   - the summarizer's call (`default_state` line 744 onward);
   - Phase A with MCP integrations on (`mechanics.py` line 299 onward);
   - `scripts/author.py`'s structured call;
   - the stack health probe.

   The captures are committed under `tests/fixtures/llm/golden_lmstudio/`.
   From the first task on, the test re-runs each scenario and asserts
   request equality and parse equality. It is canary-checked by adding a
   key to the compat payload and watching it fail. The same task records
   the **doctor and launcher baseline**: the text of `scripts/doctor.py`'s
   `check_llm` and `check_services` output and `launcher.py`'s `_report`
   against a mocked healthy LM Studio under the pinned config, as
   `doctor_llm.txt`, `doctor_services.txt` and `launcher_report.txt`
   beside the request fixtures. Those files are what "byte-identical doctor
   output" is later measured against.
2. **Mocked per-provider transport tests** (`tests/test_llm_request_shaping.py`,
   `tests/test_llm_discovery.py`, `tests/test_llm_ollama.py`). They use the
   same `handle_request` seam, through one shared helper
   (`tests/llm_wire.py`), so no client needs a transport argument. The tests
   assert, per provider:
   - the request body for each §4 rung and each §5 reasoning mode;
   - the wire cap, trusted and untrusted;
   - keep-alive;
   - auth header presence;
   - the starvation retry's route and body, and that a patched starved
     request is never repeated;
   - inline `<think>` stripping;
   - parsing of each fixture response back into `LMSResponse`: content,
     reasoning channel, finish reason, tokens and tool calls.

   None of them opens a socket. The conftest guard stays up for all of
   them.
3. **Fixtures** (`tests/fixtures/llm/<provider>/`). For each provider there
   is one file per shape:
   - the model list;
   - a non-streamed chat;
   - a streamed chat with reasoning;
   - a `json_schema` answer, and a probe answer that ignored the grammar;
   - the 400 for an unsupported parameter;
   - the 401;
   - the health response.

   `tests/fixtures/llm/PROVENANCE.yaml` names each file's server and
   version, and says whether it was **recorded** from a live server or
   **authored** from that server's documentation (with the documentation
   URL). A fixture is `recorded` only if a live server produced it; vLLM's
   are all `authored` in this release.
   `scripts/record_llm_fixtures.py --provider <p>` (a live script, run by
   hand) re-records a provider and rewrites its provenance rows. A test
   fails if a fixture file has no provenance row.
4. **Live tests** (`tests/test_llm_live.py`, `@pytest.mark.live`). They
   skip at module level unless `CLOCKWORK_LIVE_LLM=<provider>` is set,
   so the default suite gains exactly one skip. They run against LM
   Studio, Ollama and `llama-server` on the owner's workstation; vLLM is
   live in v0.20.0. Against the configured server they run:
   - discovery binds `big` and `small`;
   - a flagship narration turn with the real schema parses, and its
     choices come from the grammar;
   - a `reasoning: off` utility call reports zero or absent reasoning;
   - a forced starvation (`max_tokens: 8` on a reasoning model) recovers
     or stands down as §5.3 says;
   - the doctor's LLM section has no FAIL.

   Nothing is downloaded for them until the owner has consented to each
   item (server installer, server build, model file) by name, source and
   size.
5. **The conftest guard** (the config task):
   - `_model_endpoints` reads `llm.base_url` and the derived health URL,
     and applies default ports (80/443) to a URL that has no port
     (finding 2);
   - the discovery pin returns the active provider's empty list;
   - the native-probe pin also covers `OllamaClient`;
   - a test asserts that a remote `https://` base URL is guarded.
6. **Reachability.** `tests/test_reachability.py` passes with no new
   allowlist row. Every new module has a production caller
   (`get_backend` → provider → client).

---

## §10 — Docs

- **`docs/MODEL_SERVERS.md`** (new, hand-written): the §1.2 matrix, with a
  test that its table matches `PROVIDERS`; one setup section per provider,
  each with the server's launch command (including the flags §4.5 needs)
  and the `config/local.yaml` lines; declared models; secrets; the
  migration from `lmstudio:`; what the doctor rows mean. It is the single
  reference, and every other doc links to it.
- **README "Getting started"**: "LM Studio API key" becomes "Model
  server". It covers LM Studio (unchanged steps, still the default), plus
  a three-line `local.yaml` per other provider, and links
  `docs/MODEL_SERVERS.md`. The env-fallback sentence becomes true (§2.3).
- **`docs/AUTHORING.md`**: line 126's list of engine config sections says
  `llm`. The `author.py` inference note ("rides the engine's own LM
  Studio backend") says "model backend". Stories set nothing
  provider-specific. That stays true, and is stated.
- **AGENTS.md rule 11** becomes: "**Windows-aware, server-agnostic** —
  LM Studio at `http://localhost:1234/v1` is the default model server;
  vLLM, llama-server, Ollama and OpenAI-compatible servers are set by
  `llm.provider` (docs/MODEL_SERVERS.md). Use `scripts/start.ps1` or
  `launcher.py --stack`." Its "Canon IDs" and the rest are unchanged.
- **CLAUDE.md**: status, the in-flight table, and the deferred rows:
  - shim and alias removal in v0.21.0;
  - the unverified provider cells (vLLM's all, until v0.20.0);
  - multi-server NOT WIRED;
  - MCP LM Studio-only;
  - the untrusted reasoning-off patch keeping the full cap until declared.
- **`docs/GOVERNANCE.md` NOT WIRED**: the two rows from §7 and the
  non-goals.
- **`docs/DESIGN.md`**: the architecture section's LM Studio box becomes
  "model backend (provider)". The routing table in `backend.py`'s
  docstring stays as it is and is marked as the `lmstudio` row.
- **`config/default.yaml`**: the comments move with the keys, and the
  LM Studio-specific ones are prefixed "LM Studio:".
- **Root CHANGELOG `[Unreleased]`**, in each task.

## Acceptance

- `pytest` fully green, no xfail, with one new module-level skip (the
  live tests). `npm test --prefix ui` green. The one UI change (the
  outage line, §2.2) ships with a rebuilt, committed `dist`.
- The LM Studio golden is identical at every task, requests and parsed
  responses, for the shipped config and for a legacy `lmstudio:`
  `local.yaml`; the only sanctioned difference is the §4.2 block in the
  `off` scenario.
- Each of the five providers passes its mocked transport, discovery,
  grammar-ladder and starvation tests against its fixtures.
- Live: LM Studio played for a full flagship turn and a HUE & CRY turn
  after the change. Ollama and `llama-server` are played live on the
  owner's workstation, with their fixtures recorded, once the owner has
  consented to each download. vLLM, and any provider not live-verified,
  is listed as such in the CHANGELOG, CLAUDE.md and
  `docs/MODEL_SERVERS.md`.
- `tests/test_reachability.py`: no new allowlist row.
- `scripts/doctor.py` and `launcher.py --check` correct for each
  provider (mocked), and byte-identical for LM Studio against the
  baseline the golden task recorded.
