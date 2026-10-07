# Model servers

The game narrates through a local (or remote) model server, chosen by one key,
`llm.provider`, in `config/local.yaml`. This document is the reference for
which servers the engine speaks, what it knows about each, and how it finds out
what models a server has. It is written by hand, and
`tests/test_llm_providers_table.py` holds its matrix to the code
(`engine/llm/providers.py::PROVIDERS`) cell by cell.

> **Status (v0.19.0).** Every provider below is a legal `llm.provider`, and
> **model discovery** speaks each server's own routes. Every one gets its own
> request shaping -- the structured-output ladder, the probe, the
> reasoning-off patch, inline `<think>`, the starvation retry -- and **can
> narrate a game**: vLLM, `llama-server` and a generic server on the
> OpenAI-compatible route, Ollama on its native `/api/chat`. Each is
> **health-checked** by its own routes: the summarizer's gate, the stack, the
> doctor and `launcher.py --check`
> ([below](#health-checks-and-what-the-doctor-says)). The MCP tool loop
> (`llm.mcp`) stays LM Studio's alone ([below](#mcp-lm-studio-only)).
> **Played live:** LM Studio, [`llama-server`](#llama-server),
> [Ollama](#ollama) and, since v0.20.0, [vLLM](#vllm) (its Linux Docker
> image). **Not live-verified:** a generic OpenAI-compatible server, which
> is whatever the owner points it at.

## The matrix

One row per fact, one column per `llm.provider`. The value the engine reads
comes first, then the human half (the server flag it needs, the condition it
holds under).

- **✓** -- verified against a live server: every LM Studio cell is verified
  against **LM Studio 0.3**, measured live through v0.18 and pinned request by
  request by the LM Studio golden (`tests/test_llm_golden_lmstudio.py`);
  `tests/test_llm_live.py` was run against it again at the v0.19.0 release
  (`nvidia/nemotron-3-nano-4b`, all six green).
  llama-server's are verified against **llama.cpp server b7966** (the Windows
  Vulkan build, run in v0.19.0 with Qwen3-4B-Thinking-2507, Qwen3-0.6B and
  Phi-3.1-mini; its fixtures are recorded from it), all but
  `mcp_integrations`, which nothing measured. Ollama's are verified against
  **Ollama 0.34.4** (the portable Windows build, run in v0.19.0 with the
  library's `qwen3:4b` and a Phi-3.1-mini GGUF imported by a Modelfile), all
  but `mcp_integrations` and `auth`'s pass-through to a reverse proxy, which
  no run had. vLLM's are verified against **vLLM 0.31.0** (the
  `vllm/vllm-openai:v0.31.0` image on Docker Desktop's WSL2 backend, an
  RTX 2060, run in v0.20.0 with Qwen/Qwen3-1.7B; its fixtures are recorded
  from it), all but `mcp_integrations`.
- **†** -- **unverified**: taken from the server's own documentation, not yet
  seen on a live server.

| Field | lmstudio | vllm | llamacpp | ollama | openai_compat |
|---|---|---|---|---|---|
| `chat_transport` | `lmstudio_routed`; native `/api/v1/chat` when possible, compat for grammar and tools (v0.18's rule) ✓ | `compat` ✓ | `compat` ✓ | `ollama_native`; POST `/api/chat` ✓ | `compat` † |
| `structured_output` | `json_schema`, `json_schema_permissive`; `response_format` on compat; LM Studio rejects `json_object`, so it goes as a permissive `json_schema` ✓ | `json_schema`, `json_object`; response_format; with `--reasoning-parser` the grammar binds after the thinking ✓ | `json_schema`, `json_object`; `response_format`; the server converts the schema to GBNF ✓ | `ollama_format_schema`, `ollama_format_json`; `format: <schema>` and `format: json` on `/api/chat` ✓ | `json_schema`, `json_object`; `response_format`; probed: json_schema, then json_object, then none † |
| `probe` | `lmstudio_v18`; the {ok: boolean} probe, byte-identical ✓ | `constraint_won` ✓ | `constraint_won` ✓ | `constraint_won` ✓ | `constraint_won` † |
| `reasoning_off` | `{"reasoning": "off"}`; native only, where the registry says the model accepts it; compat ignores every knob ✓ | `{"chat_template_kwargs": {"enable_thinking": false}}`; on the same request as the grammar; whether the template honours it is the model's ✓ | `{"chat_template_kwargs": {"enable_thinking": false}}`; needs `--jinja`; whether the template honours it is the model's ✓ | `{"think": false}`; only where `/api/show` lists thinking; trusted only once declared ✓ | none; unless `llm.reasoning_off_body` declares a body patch † |
| `grammar_and_reasoning_off_together` | `no`; the root cause of the two-minute turn ✓ | `yes` ✓ | `yes` ✓ | `yes` ✓ | `if_declared`; only once `llm.reasoning_off_body` declares a patch † |
| `inline_think` | `pass`; the server splits reasoning out itself ✓ | `strip`; unless served with `--reasoning-parser` ✓ | `strip`; unless `--reasoning-format` is not none ✓ | `strip` ✓ | `strip` † |
| `discovery` | `lmstudio_v1`; GET `/api/v1/models`, shape-checked ✓ | `openai_models`; GET base_url`/models` and its `max_model_len` ✓ | `llamacpp_props`; GET base_url`/models`, then GET `/props` for n_ctx ✓ | `ollama_show`; GET `/api/tags`, POST `/api/show` per model, GET `/api/ps` ✓ | `openai_models`; GET base_url`/models` ids, and max_model_len if reported; capabilities declared † |
| `keep_alive` | `ttl`; seconds, on compat only ✓ | none ✓ | none ✓ | `keep_alive`; seconds ✓ | none † |
| `context_control` | `server`; context_length on native ✓ | `server`; `--max-model-len` ✓ | `server`; `-c` ✓ | `per_request`; options.num_ctx ✓ | `server` † |
| `auth` | `bearer`; optional ✓ | `bearer`; optional, `--api-key` ✓ | `bearer`; optional, `--api-key` ✓ | `bearer`; none locally; passed through if set, for a reverse proxy † | `bearer`; optional † |
| `inline_tools` | yes; compat tools= ✓ | yes; tools=, needs `--enable-auto-tool-choice` and a `--tool-call-parser` ✓ | yes; tools=, needs `--jinja` ✓ | yes; tools on `/api/chat` ✓ | yes; tools= † |
| `mcp_integrations` | yes; native integrations, the mcp.json plugin ✓ | no † | no † | no † | no † |
| `health` | `/api/v1/models`; shape-checked ✓ | `/health`, `/models`; `/health` answers 200, empty; nothing listens while loading; the list shape-checked ✓ | `/health`; {"status": "ok"}; 503 while loading ✓ | `/api/version`, `/api/tags`; the list shape-checked ✓ | `/models`; the list under base_url, shape-checked † |
| `default_base_url` | `http://localhost:1234/v1` ✓ | `http://localhost:8000/v1` ✓ | `http://localhost:8080/v1` ✓ | `http://localhost:11434`; no /v1 ✓ | none; must be set † |

`llm.base_url` is the server's OpenAI-style base -- for every shipped default
the URL that ends in `/v1` -- except Ollama's, which has none. The OpenAI model
list (`/models`) hangs off `base_url` itself, the same base compat chat is sent
to, so a generic server mounted elsewhere (`.../v1beta/openai`, a proxy
prefix) is asked where it serves. Every other discovery and health route
(`/props`, `/health`, Ollama's `/api/*`, LM Studio's `/api/v1/*`) hangs off the
**server root**: `base_url` with its trailing `/v1` taken off. The shipped
`default.yaml` sets LM Studio's base, so naming another provider means setting
`base_url` too:

```yaml
# config/local.yaml
llm:
  provider: vllm
  base_url: "http://localhost:8000/v1"
```

## Discovery: what the engine learns from each server

`ModelRegistry.refresh` (`engine/llm/registry.py`) asks the configured
server through `engine/llm/discovery.py`, one parser per row, each filling
the same `ModelInfo`. Its `source` says which parser (`lmstudio_v1`,
`openai_models`, `llamacpp_props`, `ollama_show`); its `declared_fields` say
what a declaration below filled, and never replace the source. Binding a
profile to a model, the denylist and the ranking are the same for every
server.

| Provider | Model ids | Context the budget uses | Tools | Reasoning knob | Loaded |
|---|---|---|---|---|---|
| `lmstudio` | `key` | the loaded context, else declared, else the advertised one | `trained_for_tool_use` | `capabilities.reasoning` (options, default) | a loaded instance |
| `vllm` | `id` | `max_model_len` (what `--max-model-len` served) | declared | declared | always |
| `llamacpp` | `id` | `/props`' `default_generation_settings.n_ctx` (what `-c` started), else declared, else the trained `meta.n_ctx_train` | declared | declared | always |
| `ollama` | `name` | the `num_ctx` the engine sends -- the declared context, else `llm.context_tokens` -- capped by `/api/show`'s `<arch>.context_length` | `capabilities` lists `tools` | `capabilities` lists `thinking`: options `off`, `on`, and it thinks by default | listed by `/api/ps` |
| `openai_compat` | `id` | `max_model_len` if the server reports it, else declared, else `llm.context_tokens` | declared | declared | always |

**The context precedence is the same everywhere: served or loaded, then
declared, then `llm.context_tokens`.** The number a server says it SERVED or
LOADED a model with is the one that truncates a prompt, so nothing beats it. A
trained or advertised window (llama-server's `n_ctx_train`, an unloaded LM
Studio model's maximum) is not that number, and a declaration beats it.

**Every body is shape-checked.** A server can answer a route it does not own
with 200 and an error body (LM Studio does), so a status code proves nothing.
A 200 carrying another server's list -- LM Studio's `{"models": [{"key"}]}` at
a vLLM, llama-server's `/v1/models` (which also carries an Ollama-style
`models` array) at Ollama -- or an `{"error": ...}` object is refused as
`NotAModelList`, naming the provider, and discovery binds nothing. The log
says what the body looked like. (`NotV1Models`, v0.18's name for it, is kept
as an alias.) The rule is about the LIST: Ollama's per-model `/api/show` is
not the list, so one model whose show errors or 404s is skipped with a warning
and the others are still listed.

**Nothing is guessed from a name.** `/v1/models` says what a model is called
and nothing about what it can do. A model id with "r1" or "qwen3" in it is not
evidence that it thinks before it answers, so for any model not from LM
Studio's list, "is this a reasoning model" reads only the declaration below or
Ollama's `thinking` capability. LM Studio's measured architecture list
(`REASONING_ARCHES`) applies to LM Studio's own models only.

**When discovery fails** (the server is down, refuses the key, or answers
with the wrong shape) every profile resolves to the offline placeholder
`local-model`, unbound, exactly as in v0.18, and the doctor reports it.

**Not supported: llama-server's multi-model router mode.** Recent
`llama-server` builds can serve several models from one process, with a
per-model `status` in `/v1/models` and `/props?model=<id>`. Discovery reads
the single-model server: every listed model counts as loaded and one `/props`
read sizes them all, and a `/props` without `default_generation_settings`
fails discovery. Run one `llama-server` per model.

**The list half of a health check** (`registry.probe_models`) asks the
configured provider's own list when it is given no URL, and names the URL that
answered; the whole check is the row's `health` cell
([below](#health-checks-and-what-the-doctor-says)).

## Structured output: the ladder

`llm.structured_output` picks a **rung**, and the engine sends it in the
configured server's own wire form (`backend.wire_form`, from the row's
`structured_output` cell):

| Rung | `llm.structured_output` | On the wire | LM Studio |
|---|---|---|---|
| 1 | `json_schema` | the full, strict turn schema: `response_format: {type: json_schema, json_schema: {name, strict, schema}}` | the same |
| 2 | `json_object` | valid JSON, shape free: `{"type": "json_object"}` | a permissive `json_schema` (LM Studio rejects `json_object` with a 400), as in v0.18 |
| 3 | `off` | nothing | nothing |

On Ollama the same rungs go as `/api/chat`'s `format`: rung 1 is `format:
<the schema>`, rung 2 `format: "json"`. A caller that builds its own
`response_format` (the planner, `scripts/author.py`) is translated the same
way; any other `response_format` is refused -- the request is not sent, and
the error names the caller -- never sent without its grammar.

**`auto` probes once per process** and caches the answer, by the row's
`probe` cell:

- **`lmstudio_v18`** (LM Studio): v0.18's probe, byte for byte -- a
  `{"ok": boolean}` schema, `Reply with {"ok": true}`, passing if `"ok"`
  appears in the reply. A no means rung 3; there is no second probe.
- **`constraint_won`** (every other server): a schema built from the three
  constructs the turn schema depends on -- `{"answer": {"anyOf": [{"type":
  "string", "enum": ["yes"]}]}}`, required, `additionalProperties: false` --
  sent with the prompt `Reply with exactly {"answer": "no", "note": "free"}`.
  It passes only if the reply parses to exactly `{"answer": "yes"}`: only if
  the **constraint beat the prompt**. A server that accepts `response_format`
  and ignores it echoes the prompt and fails, which v0.18's check could not
  tell apart. A server that fails (or answers 400) is asked for rung 2: a
  one-sentence prose question under `json_object`, passing only if the reply
  parses as a JSON object. A server that passes neither lands on rung 3.
  Both probes ask for reasoning `off` (the row's patch, trusted or not): the
  question is whether the SERVER enforces a grammar, and a reasoning model
  thinking first can starve the probe. Measured on Ollama 0.34.4 before this
  was so: `qwen3:4b` under `think: true` thought past the probe's cap and a
  server that enforces grammars was put on rung 3.

**Without the full schema on the wire, the prompt carries it.** On rungs 2
and 3 a narration turn's system message gains a **format block**
(`schemas.render_format_block`): the envelope's keys and which are required,
the choice ids, the hint values, and for each intent verb the targets legal
this turn. Rung 1 appends nothing. On LM Studio only `off` gains the block:
its `json_object` rung and the turn after a failed `auto` probe are sent
exactly as v0.18 sent them (the golden pins both). The planner's grammar
rides the same ladder on every server but LM Studio, where it is always on,
as in v0.18.

### Rule 1 on each rung

AGENTS.md rule 1 has two halves. On every rung, the reply is **conformed** to
the schema that was built for the turn (`schemas.conform`, right after the
envelope is parsed): an undeclared key is dropped, and so is any **whole
choice** whose intent verb or target the engine did not offer -- never the
intent alone, which would leave a choice promising a walk that nothing
performs. Each drop is logged by name, and a turn left with fewer than two
choices is topped up with the generic "Look around" / "Continue", which carry
no intent; one with more than four is cut at four. `ledger_delta` is held to
its schema the same way, recursively. A dropped `stat_changes` or
`skill_check` claim is kept aside (`conformed_away`) for the audits that
count such claims, and never acted on. **Narration executes no `tool_calls`
on any rung.** A choice that promises an action but carries no intent is not
caught on any rung (it is optional in the schema): a deferred row in
CLAUDE.md.

| Rung | "An illegal target is unsamplable" | "An illegal-at-execution intent is refused in the prose" |
|---|---|---|
| 1 (`json_schema`: LM Studio, vLLM, llama-server, Ollama's `format`, a generic server that passed the probe) | **Holds**: the turn's intent enums and `additionalProperties: false` are in the grammar; off LM Studio the `constraint_won` probe showed the server enforces `enum`, `anyOf` and `additionalProperties`. `conform` changes nothing | Holds (`execute_intent`) |
| 2 (`json_object`) | **Downgraded to "never offered"**: the model can write an intent the engine did not offer, and `conform` drops that whole choice before the player sees it, so it is never executed | Holds, unchanged |
| 3 (none) | The same as rung 2. A reply that does not parse offers only the fallback choices | Holds |

## Turning reasoning off

A request whose profile says `reasoning: off` asks the provider row for the
**patch** that turns thinking off on its route (`Provider.reasoning_off_patch`),
and whether that patch is **trusted**:

| Provider | The patch (for `off`; `on` sends nothing) | Trusted when |
|---|---|---|
| `lmstudio` | `reasoning: "off"` on the native route only, where the model's `capabilities.reasoning` accepts it; nothing on compat, which ignores every knob | the server reported the knob |
| `vllm`, `llamacpp` | `chat_template_kwargs: {enable_thinking: false}` (llama-server needs `--jinja`) | `declared_models` lists `off` in the model's `reasoning`. **Sent but untrusted** when the model is undeclared; **not sent** when a declaration excludes `off`. A verified cell does not make it trusted: the server passes the patch on, and whether the model's template honours it is the model's (below) |
| `ollama` | `think: false`, only where `/api/show` lists `thinking` and the model's options include `off` (`on` sends `think: true`; an effort level a declaration names is sent as that string); a model without `thinking` is sent no `think` at all, which it would refuse with a 400 | `declared_models` lists `off` in the model's `reasoning` (and does not also say `reasoning_off_trusted: false`). **Sent but untrusted** otherwise: `thinking` says a knob exists, not that the template honours `think: false` -- measured, the library's own `qwen3:4b` does not ([below](#ollama)) |
| `openai_compat` | `llm.reasoning_off_body`, if declared; else nothing | always, once declared: the owner declared it |

**The wire cap follows the trust.** A request's cap is its content budget
plus the profile's `reasoning_budget`; the budget is dropped **only** when a
trusted patch went on the wire. An untrusted patch is sent beside the full
"on" cap: a template that ignores `enable_thinking` (gpt-oss and the R1
distills do) still has room to think and then answer. Declare the model's
`reasoning: ["off", "on"]` to make an `off` request ask for its content alone.

**What an ignored patch looks like (measured on llama-server b7966 and
Ollama 0.34.4).** Qwen3-0.6B's template honours the patch: no thinking, the
answer at once. Qwen3-4B-Thinking-2507's -- which is what Ollama's library
serves as `qwen3:4b` -- opens `<think>` in the prompt whatever the patch
says, so it thinks anyway, and the server, told thinking is off, stops
splitting it out: the thinking arrives **inside the answer, with no opening
tag**, then `</think>`, then the answer. The client reads the answer to an
untrusted patch knowing that (`InlineThinkSplitter(forced_open=True)`, on
both transports): the text up to that orphan `</think>` goes to the
reasoning channel -- even when the thinking mentions `<think>` on the way
-- and an answer cut at the cap before one arrived reads as starved. The log
names the model once. Two costs remain, and they are the price of never
showing the player a model's musings:

- **An ungrammared `off` stream to an undeclared model is not streamed.**
  With no grammar on the request, nothing tells an answer from ignored
  thinking until a `</think>` arrives or the stream ends, so the reply is
  held and reaches the player all at once. A stream WITH a grammar (every
  narration turn on rungs 1 and 2) streams as it arrives: under a grammar the
  thinking cannot land in the content -- llama-server binds the grammar from
  the first token, and Ollama sends its thinking in `message.thinking`
  (both measured). On rung 3 (no grammar) an `off` narration turn to an
  undeclared model is therefore shown only when it is done.
- **An answer to an untrusted patch, cut at the cap, is read as starved
  unless the request carried a grammar.** Under a grammar the content
  provably begins as JSON, so a cut answer that starts with `{` or `[` is
  recognised as an answer and kept. Without one (rung 3) nothing tells a cut
  answer -- prose or JSON -- from thinking that never closed (a model
  drafting its JSON while it thinks opens with a brace too), so it goes to
  the reasoning channel and the request takes the starvation rules. A model that honours the patch and simply ran out of
  room loses its truncated answer; raise `max_tokens`, or declare `off` for a
  template that honours it, to avoid both costs.

**Leave such a model undeclared** (or never declare `off` for it): the patch
then stays untrusted, the cap keeps its reasoning budget, and its answers are
read as above. Do not declare `reasoning: ["on"]` to stop the patch being
sent. Measured on Ollama, that made it worse: the structured-output probe,
sent with no `think: false`, thought past its cap and the server was put on
rung 3, and a starved narration turn had no patch left to recover with.
**The patch with a grammar beside it binds the grammar from the first
token**, even on a template that ignores it (measured on both servers), which
is why the probe asks for `off` and why a starved grammared turn recovers.
On vLLM (0.31.0, `--reasoning-parser`) the patch is what makes it so: with
thinking on, vLLM lets the model think first and binds the grammar to the
answer after ([vLLM](#vllm)).

**The starvation retry.** A reply that spent the whole cap thinking (finish
`length`, empty content) is retried once:

| Provider | Retry |
|---|---|
| `lmstudio` | unchanged from v0.18: native with `reasoning: "off"`, else measured room, else stand down |
| `vllm`, `llamacpp`, `openai_compat` | if the starved request did not carry the patch: the same request, **same `response_format`** (the grammar survives), plus the patch. If it did: measured room (the reasoning tokens the server reported, plus the content budget), else stand down |
| `ollama` | if the starved request did not carry `think: false`: the same `/api/chat` request, **same `format`** and `num_ctx`, with `think: false`. If it did (or the model has no `thinking`): stand down -- Ollama reports no reasoning-token count to measure room from |

The streamed narration recovers by the same table (`backend.recover_starved`),
so a stream that starved with the patch on, or on a generic server with no
declared body, is never sent again as it was.
llama-server and Ollama report no reasoning-token count, so there a request
that starved with the patch already on stands down at once, after one
request. vLLM does report one (`completion_tokens_details.reasoning_tokens`,
measured on 0.31.0 with `--reasoning-parser`; without the parser it sends
no `completion_tokens_details`), so on vLLM measured room is available. The
log says which case it was, and only then what to do:

- **the patch was sent, untrusted (an undeclared model), and the model
  thought anyway**: the cap already kept the reasoning budget, so raise
  `max_tokens` or `reasoning_budget`, or use a model whose template honours
  the patch;
- **the patch was sent, trusted (declared), and the model thought anyway**:
  raise `max_tokens`, or mark the model `reasoning_off_trusted: false` so the
  cap keeps the reasoning budget;
- **no patch was available to send**: declare the model's `reasoning`, or
  `llm.reasoning_off_body` on a generic server, or raise `max_tokens`;
- **nothing came back at all** -- no content, no reasoning, no tokens spent:
  a stream cut before its done line, or an empty answer. That is not
  starvation, and no declaration fixes it; the log says so and points at the
  server's own log.

## Inline `<think>`

vLLM without `--reasoning-parser`, and `llama-server` with
`--reasoning-format none`, send a reasoning model's thinking **inside the
answer**, wrapped in `<think>…</think>`. On every row whose `inline_think` is
`strip`, the client moves a leading span to the reasoning channel -- streamed
and split across chunks anywhere, or not -- before the narration decoder and
the image-tag scanner see it, so an `[IMAGE:]` the model wrote while thinking
never fires. An unclosed span is reasoning, and the answer reads as starved.
The servers' own split is cleaner (and gives the player the reasoning panel
as it streams):

- **vLLM:** `vllm serve <model> --reasoning-parser <parser>` (`qwen3`,
  `deepseek_r1`, ... per the model family). Measured on 0.31.0 without it:
  Qwen3-1.7B's thinking arrives as a leading `<think>…</think>` span, whole
  and streamed (`vllm/chat_inline_think_live.json`,
  `chat_stream_inline_think_live.json`), the engine moves it, and the
  doctor's `inline <think>` row WARNs naming the flag.
- **llama-server:** leave `--reasoning-format` at its default, which splits
  it (measured on b7966 with `--jinja`), or name any value but `none`.

**Do not run `llama-server --reasoning-format none` with a model whose
template opens `<think>` in the prompt** (measured: Qwen3-4B-Thinking-2507).
Its thinking then arrives with no opening tag -- `…</think>answer` -- which
is not the leading span above. A whole answer is still split at that orphan
`</think>` (and counted as inline thinking, so the doctor names the flag), but
a stream cannot be: its thinking would reach the player before the tag that
ends it arrived.

LM Studio splits reasoning out itself (`pass`), and nothing is stripped.
**Keep LM Studio's reasoning split on** (its Developer setting that sends
thinking as a separate `reasoning_content`): that split is opt-in, and with
it off LM Studio passes a model's inline `<think>…</think>` through untouched,
so a compat reply with no grammar on it (a tools request, or the native route
unavailable) carries its thinking -- and any `[IMAGE:]` tag written while
thinking -- into the prose. That is v0.18's behaviour, kept: the row stays
`pass` because stripping would change the parsed responses the LM Studio
golden pins (a CLAUDE.md deferred row).

`ttl` (LM Studio's keep-alive) is sent to LM Studio only; Ollama gets its
own `keep_alive`, the same `llm.keep_alive_seconds`.

## vLLM

(The compose file's `vllm` service passes `HF_TOKEN` through by name for gated
models. `docker compose config` prints it: never run that with it set,
docs/HOSTING.md § Docker Compose.)

vLLM is spoken on its OpenAI-compatible route. Run live in v0.20.0 against
**vLLM 0.31.0** -- the `vllm/vllm-openai:v0.31.0` image
(`sha256:c1c9f6fd5c10…`), on Docker Desktop's WSL2 backend with the GPU
handed to the container, on an RTX 2060 (12 GB, Turing, sm_75) -- with
**Qwen/Qwen3-1.7B**: the ✓ cells above, the recorded fixtures under
`tests/fixtures/llm/vllm/`, and `tests/test_llm_live.py`, all six green.
vLLM is a Linux server; on Windows run it in Docker, as here:

```sh
docker run -d --name vllm --gpus all --ipc=host -p 127.0.0.1:8000:8000 \
  -v /path/to/hf-cache:/root/.cache/huggingface \
  vllm/vllm-openai:v0.31.0 --model Qwen/Qwen3-1.7B \
  --dtype half --enforce-eager --max-model-len 16384 \
  --gpu-memory-utilization 0.90 --reasoning-parser qwen3 \
  --enable-auto-tool-choice --tool-call-parser hermes
```

```yaml
# config/local.yaml
llm:
  provider: vllm
  base_url: "http://127.0.0.1:8000/v1"
  profiles:
    big: {model: "Qwen/Qwen3-1.7B"}       # the id /v1/models lists: the Hugging Face repo
    small: {model: "Qwen/Qwen3-1.7B"}
  declared_models:
    "Qwen/Qwen3-1.7B": {tools: true, reasoning: ["off", "on"], reasoning_default: "on"}
```

- **`--reasoning-parser <parser>`**: thinking in its own channel (vLLM
  0.31.0 names it `reasoning` in the message and the stream's deltas, not
  `reasoning_content`; the client reads both). Without it the thinking
  arrives inline ([Inline `<think>`](#inline-think)).
- **`--max-model-len`** is the context the engine budgets against (the
  list's `max_model_len`).
- **`--enable-auto-tool-choice --tool-call-parser <parser>`** (`hermes` for
  Qwen3) for `tools=`; a narration turn sends none.
- **`--api-key <key>`** (or `VLLM_API_KEY`) makes the `/v1` routes refuse
  another key, or none, with a 401 whose body is `{"error":
  "Unauthorized"}` (a string, not an object; `error_401.json`); `/health`
  still answers without one.
- **The utilization is measured, not chosen.** vLLM refuses to start when
  free GPU memory is below `--gpu-memory-utilization` x total, and the card
  is shared with the desktop (and LM Studio, which must hold no model
  during the run). Read
  `nvidia-smi --query-gpu=memory.free,memory.total --format=csv` just
  before starting and set the flag just under free / total, two decimals,
  rounded down: 11137 of 12288 MiB free gave **0.90** (with 1.7B: 3.2 GiB
  of weights, 7.2 GiB of KV cache).

**Turing (sm_75), measured on 0.31.0.** The newest release runs on it, so
no older tag was needed: the **V1** engine (V2 model runner), FlashAttention
2 refused ("FA2 is only supported on devices with compute capability >= 8",
logged as an ERROR and harmless), and the **TRITON_ATTN** backend chosen
from `TRITON_ATTN` and `FLEX_ATTENTION`; FlashInfer's sampler falls back
too. `--dtype half` is required (no bfloat16 on sm_75; the checkpoint is
cast). `--enforce-eager` skips CUDA graphs and `torch.compile`. Qwen3-4B
was not run (its download was declined); 1.7B fit with room to spare.

What was measured:

- **The patch is honoured, and trusted once declared.** Qwen3-1.7B (the
  original hybrid checkpoint, not a Thinking-2507 build) answers
  `enable_thinking: false` with no thinking and `reasoning_tokens: 0`
  (`chat_reasoning_off.json`), so the declaration above makes the doctor's
  `reasoning off` row OK, `(trusted)`.
- **With `--reasoning-parser`, the grammar binds AFTER the thinking**,
  unlike llama-server: under a `json_schema` with thinking on, the model
  thinks into the reasoning channel and then answers inside the schema
  (`chat_json_schema_thinking.json`). So a probe sent with thinking on
  starves at its 200-token cap (`chat_json_object_starved.json`); the
  engine's probes send the patch (`off`) and pass at once
  (`chat_json_schema.json`, `chat_json_object.json`: rung 1, probed). With
  the patch beside the grammar there is no thinking at all.
- **A reasoning-token count is reported** (`usage.completion_tokens_details.reasoning_tokens`,
  with the parser), so the starvation retry can measure room. The forced
  starvation in the live test starved on `on` and recovered on the patched
  retry.
- **`/health` answers 200 with an empty body**, and while the model loads
  nothing listens at all (measured: about 70 s of refused connections with
  the weights cached), so the health check reads unreachable, never
  `loading`; `GET /version` answers `{"version": "0.31.0"}`.
- **A model the server does not serve** is a 404 with an OpenAI-style
  nested error, `{"error": {"message": "The model ... does not exist.",
  "type": "NotFoundError", ...}}` (`error_404.json`); an unknown
  `response_format` is a 400 listing pydantic's validation errors
  (`error_400.json`).
- **The first start downloads the weights** into the bind-mounted
  Hugging Face cache (about 3.8 GB for Qwen3-1.7B, 24 minutes here through
  Docker Desktop's mount); later starts take about 70 s.
- **A small model can loop on whitespace under the grammar.** vLLM's
  structured outputs allow any whitespace between JSON tokens
  (`disable_any_whitespace=False`, its default). Once in six live
  narration turns -- without `--reasoning-parser`, HUE & CRY's longer
  prompt -- Qwen3-1.7B wrote its narration and then newlines until the
  4400-token cap; the engine salvaged the narration and offered the
  fallback choices. A larger model, or
  `--structured-outputs-config '{"disable_any_whitespace": true}'`, is the
  operator's lever; the engine leaves it to the server.
- **The choices carried no intents** on these turns: a 1.7B model offered
  plain choices, which the schema allows (the CLAUDE.md row on choices
  without an intent).

**From a container.** The compose file's `vllm` profile
([docs/HOSTING.md](HOSTING.md#docker-compose)) runs this image beside the
game, reached at `http://vllm:8000/v1`. That path -- the game container
narrating through the compose network -- was not run in v0.20.0 (not in the
run's consent); the server itself is the one verified here.

## llama-server

llama.cpp's `llama-server` is spoken on its OpenAI-compatible route. Run
live in v0.19.0 against **b7966** (the Windows Vulkan build) -- the ✓ cells
above, the fixtures under `tests/fixtures/llm/llamacpp/`, and
`tests/test_llm_live.py`, all green on Qwen3-4B-Thinking-2507, Qwen3-0.6B
and Phi-3.1-mini. One model per server:

```powershell
llama-server -m C:\models\Qwen3-0.6B-Q8_0.gguf --host 127.0.0.1 --port 8080 -c 16384 --jinja
```

- `--jinja` is required: it is what applies the model's own chat template,
  and with it the reasoning-off patch (`chat_template_kwargs`) and `tools=`.
- `-c` is the context the engine budgets against (`/props`' `n_ctx`).
- Leave `--reasoning-format` at its default ([Inline `<think>`](#inline-think)).
- On a machine with more than one GPU the Vulkan build lists each
  (`llama-server --list-devices`); `--device Vulkan0` keeps the model off an
  integrated one.
- `--api-key <key>` makes it refuse any other key (401); put the key where
  `llm.api_key` reads it ([Secrets](#secrets)).

```yaml
# config/local.yaml
llm:
  provider: llamacpp
  base_url: "http://127.0.0.1:8080/v1"
  profiles:
    big: {model: "Qwen3-0.6B-Q8_0.gguf"}     # the id /v1/models lists: the file name
    small: {model: "Qwen3-0.6B-Q8_0.gguf"}
  declared_models:
    "Qwen3-0.6B-Q8_0.gguf": {reasoning: ["off", "on"], reasoning_default: "on"}
```

What was measured:

- **The turn grammar binds from the first token.** Under a `json_schema` (or
  `json_object`) `response_format` a reasoning model does not think at all:
  the probe and every narration turn came back as JSON with no reasoning, so
  on llama-server a reasoning model's narration turn costs no thinking time.
  The reasoning budget is spent only by calls with no grammar.
- **No reasoning-token count.** `usage` has no `completion_tokens_details`,
  so a request that starved with the patch on stands down after one request
  ([the starvation retry](#turning-reasoning-off)). Measured: Qwen3-0.6B,
  starved on purpose, recovered on the patched retry; Qwen3-4B-Thinking-2507,
  whose template ignores the patch, stood down after it.
- **`/health` answers 503 `Loading model`** while `-m` loads (about 50 s the
  first time the Vulkan build compiles its shaders, 3 s after), then
  `{"status": "ok"}`.
- `/props` reports the build (`build_info`) and `n_ctx`; b7966 starts four
  slots sharing one unified cache, each with the whole `-c`.

## Ollama

Ollama is spoken on its **native `POST /api/chat`**, for every request,
streamed (NDJSON) and not (`engine/llm/ollama.py`). Run live in v0.19.0
against **Ollama 0.34.4** (the portable Windows build) with the library's
`qwen3:4b` and a Phi-3.1-mini GGUF imported by a Modelfile: the ✓ cells
above, the recorded fixtures under `tests/fixtures/llm/ollama/`, and
`tests/test_llm_live.py`, green on both. Its base URL has no `/v1`:

```powershell
ollama serve                  # first, unless the desktop app is already running it
ollama pull qwen3:4b          # any chat model; tools and thinking are read from /api/show
```

```yaml
# config/local.yaml
llm:
  provider: ollama
  base_url: "http://localhost:11434"
  context_tokens: 16384       # the num_ctx sent with every request (see below)
  profiles:
    big: {model: "qwen3:4b"}
    small: {model: "qwen3:4b"}
```

A GGUF already on disk (LM Studio's, say) is served without a download by a
one-line Modelfile -- `FROM C:\models\model.gguf` -- and `ollama create
<name> -f Modelfile`. `OLLAMA_MODELS` names where Ollama keeps its models, if
not under your profile.

What was measured:

- **A reasoning model thinks BEFORE the grammar binds.** Under `format` with
  `think: true`, `qwen3:4b` thought (into `message.thinking`) and then
  answered inside the schema: the grammar held. But its thinking is long --
  4881 tokens on the probe's one-line question, over 16,000 characters on a
  narration turn -- so a narration turn under the `big` profile's `on`
  starved at its 4400-token cap and was recovered by `think: false` on the
  same `format`, which binds the grammar at once. For fast turns on such a
  model set `llm.profiles.big.reasoning: "off"`.
- **`qwen3:4b` ignores `think: false`** without a grammar: its thinking
  arrives in `message.content`, closed by an orphan `</think>` ([Turning
  reasoning off](#turning-reasoning-off)). So Ollama's `think: false` is
  trusted only once declared.
- **`think` on a model without `thinking` is a 400**, in Ollama's words
  `"<model>" does not support thinking` (recorded, `chat_error_think.json`);
  the engine never sends it one. `think: false` to such a model is answered
  200.
- **`/api/ps` reports the `num_ctx` sent** as each loaded model's
  `context_length` (8192 sent, 8192 reported), and `keep_alive` is honoured
  (900 seconds sent, `expires_at` 900 seconds on).
- **No reasoning-token count.** `eval_count` covers thinking and answer
  together, so a request that starved with `think: false` on stands down.

**Why native, not Ollama's `/v1/chat/completions`.** That route cannot set
`num_ctx`. Ollama's own default context is a few thousand tokens, and it
cuts a longer prompt **from the front, silently** -- the system persona is
the first thing lost, the defect that once dropped it on LM Studio. On
`/api/chat` every request carries `options.num_ctx`: the context the
profile is bound to, which is the number the prompt budget was sized
against -- `llm.declared_models.<id>.context` if declared, else
`llm.context_tokens` -- capped by the model's trained window from
`/api/show`. Raise `context_tokens` (or declare the model's `context`) for a
longer memory; Ollama allocates that much for the model when it loads it.
The native route also takes the grammar (`format`), `think` and tools in the
same request, which the compat route cannot combine as directly.

What a request carries:

| Key | From |
|---|---|
| `messages` | the turn's messages, OpenAI roles kept |
| `format` | the structured-output rung, or a caller's own `response_format`, translated (above) |
| `think` | the profile's `reasoning`, only for a model whose `/api/show` lists `thinking` |
| `options.temperature` | the profile |
| `options.num_predict` | the wire cap: the content budget, plus the reasoning budget unless a trusted (declared) `think: false` went |
| `options.num_ctx` | the bound context, **always** |
| `keep_alive` | `llm.keep_alive_seconds`, when above 0. **0 sends nothing**, so Ollama's own default (5 minutes) applies -- not Ollama's reading of `keep_alive: 0`, which is "unload after this request" |
| `tools` | a caller's, passed through (a narration turn sends none) |

**gpt-oss-style models (NOT live-verified: the owner declined the 14 GB
download in v0.19.0).** Ollama documents that gpt-oss takes `think` as
`"low"`, `"medium"` or `"high"` and reasons whatever `true`/`false` says,
while its `/api/show` still lists `thinking`. Left undeclared, an `off`
request sends an untrusted `think: false` beside the full cap, and its
answer is read as above. Declare it so an effort level can be asked for
(unverified live, as is `reasoning_off_trusted: false`):

```yaml
llm:
  declared_models:
    "gpt-oss:20b":
      reasoning: ["low", "medium", "high"]   # no "off": nothing claims to turn it off
```

A `low`/`medium`/`high` profile is then sent that string, an `off` profile
no `think` and the full cap, and an `on` profile (the `big` profile's
default) no `think` either -- the model's own default effort applies. A
model declared with `off` whose template turns out not to honour it can be
marked `reasoning_off_trusted: false`, which keeps the cap and the careful
read without removing the declaration.

The answer's `message.thinking` is the reasoning channel (the player's "the
world is deciding" panel, never the narration), and a leading `<think>` in
`message.content` is moved there too. `done_reason: "length"` is a
truncation, so a reply that spent the whole cap thinking reads as starved and
takes the retry above. The bearer key, if one is set, is passed through for a
reverse proxy in front of Ollama; Ollama itself needs none.

## Declared models

A server that does not report a model's context, tool use or reasoning knob
can be told, per model id, in `llm.declared_models`:

```yaml
llm:
  provider: vllm
  base_url: "http://localhost:8000/v1"
  declared_models:
    "Qwen/Qwen3-8B":
      context: 32768
      tools: true
      reasoning: ["off", "on"]      # the knob exists, and these are its values
      reasoning_default: "on"       # it thinks unless told not to
```

The rules (`discovery.apply_declared`):

- **A declaration fills only what the server left empty.** A context the
  server served or loaded always wins: vLLM's `max_model_len` (from a generic
  server too, when it reports one), llama-server's `n_ctx` and LM Studio's
  loaded context are the numbers that truncate a prompt. A declaration does
  beat a trained or advertised window. `tools` and `reasoning` are filled only
  for a server whose list does not report them (vLLM, llama-server, a generic
  server); LM Studio's list does, and its word stands. Ollama's
  `thinking` capability says only that a knob exists (read as `off`/`on`),
  so for a model that reports it a declared `reasoning` list **narrows**
  those options -- it never grants a knob to a model that reports none.
- **`reasoning_off_trusted: false`** (every server but LM Studio) is the
  owner saying this model may ignore its reasoning-off patch: the patch is
  still sent, but the wire cap keeps the reasoning budget, and a request that
  starves with it on is never re-sent. Unset, nothing changes. The model's
  `declared_fields` name it. LM Studio sends no patch to trust (its compat
  route ignores every knob, its native route asks the model's own list), so
  there it is ignored -- and the doctor says so, as an `ignored key` WARN.
- **A declared id the server does not list is ignored, with a warning**, and
  nothing is ever bound to it. A declaration describes a model; it does not
  conjure one. `/v1/models` is still asked for exactly this reason: it is how a
  mistyped id is caught before the first turn is refused.
- **Name the model per profile** for vLLM and llama-server, which serve one
  model each: `llm.profiles.big.model` (then the legacy `llm.models.big`)
  works for every provider, as it did.

## Health checks, and what the doctor says

"Is the model server up?" is asked of the configured provider, by its row's
`health` cell (`Provider.health_probe`), in order, and the first "no" is the
answer. A 200 is never enough on its own -- a server can answer a route it does
not own with 200 and an error body -- so each route is read by its shape:

| Provider | Asked | Up when |
|---|---|---|
| `lmstudio` | `GET /api/v1/models` | LM Studio's list, with a model in it (v0.18's request, byte for byte) |
| `vllm` | `GET /health`, then `GET` base_url`/models` | `/health` answers 200 without an error (vLLM 0.31.0: an empty body, and no key needed); the OpenAI list has a model. While the model loads nothing listens on the port, so the check reads as unreachable, not `loading` |
| `llamacpp` | `GET /health` | `{"status": "ok"}`. A **503** is a server still loading its model: down, and the detail says `loading` |
| `ollama` | `GET /api/version`, then `GET /api/tags` | `{"version": ...}`; the tag list has a model |
| `openai_compat` | `GET` base_url`/models` | the OpenAI list, with a model in it |

Four things ask it: the summarizer's gate (`LMStudioBackend.server_available`
-- the compat client's `is_available`, or on Ollama `OllamaClient`'s; until
v0.19.0 it asked LM Studio's route whatever the provider, so every other
server's running summary fell back to deterministic compression), the stack's
`llm` service, `launcher.py --check` / `--stack`, and the doctor.

**The stack's `llm` service** ships with `health_url: ""`, which means "ask
the provider, against `llm.base_url`". A URL set there is probed as it is
instead. The bearer key goes with a health check only when the URL is the
configured server's own origin (the scheme, host and port of `llm.base_url`),
never to another service. The model server is the one **FAIL-level** service,
whatever the provider: `launcher.py --check` exits 1 when it is down, and 0
when only something optional is.

**`manage: true` needs no new code.** To have `launcher.py --stack` start a
`llama-server` (or `vllm serve`) and wait for it, declare the command like any
other managed service; the wait polls the health check above, so a 503 while
the model loads is simply waited out:

```yaml
# config/local.yaml
llm:
  provider: llamacpp
  base_url: "http://localhost:8080/v1"
stack:
  services:
    llm:
      manage: true
      root: "C:/tools/llama.cpp"            # where the binary lives
      command: "llama-server.exe"
      args: ["-m", "models/Qwen3-8B-Q4_K_M.gguf", "--port", "8080",
             "-c", "16384", "--jinja", "--reasoning-format", "deepseek"]
      startup_timeout_seconds: 600
```

The stack stops what it started when the game exits. On Linux name the
binary without `.exe` (`command: "llama-server"`); since v0.20.0 a command
the config names resolves as `shutil.which` resolves one -- on Windows with
each `PATHEXT` suffix -- so a `.exe`-less name works on both (docs/HOSTING.md
§ Linux).

**The doctor** (`scripts/doctor.py`) gives the model server its own section:
`LM Studio` for LM Studio -- its rows exactly v0.18's -- and `Model server
(<provider>)` for every other. Its rows:

| Row | What it says |
|---|---|
| `liveness` | the health check above; FAIL when down, and nothing below is asked |
| `model (<id>)` | whether the profile's model was bound from the server's own list |
| `chat probe` | one short completion on the real path, as a turn sends it |
| `native /api/v1/chat` (LM Studio) | whether the native route, the one that can turn reasoning off, is served |
| `reasoning off` (every other) | the patch an `off` profile sends, `(trusted)` (OK) or `(untrusted)` (WARN: slower turns until declared); or `unavailable` (WARN), unless the server reports the model has no thinking knob |
| `grammar rung` (every other) | `1: json_schema` (OK), `2: json_object` or `3: none` (WARN), and whether it was probed or set |
| `inline <think>` (every other) | WARN when a probe answer carried its thinking inside the content, naming the server flag that fixes it (`--reasoning-parser` for vLLM, `--reasoning-format` for llama-server) |
| `ignored key` | WARN, one per key set (changed from `default.yaml`) that this provider ignores: `llm.prefer_native` off LM Studio, `llm.keep_alive_seconds` on vLLM, llama-server and a generic server, `llm.reasoning_off_body` on a row with its own patch, a `reasoning_off_trusted` on LM Studio |
| `mcp` | shown when `llm.mcp.enabled` is set: OK on LM Studio, **FAIL** elsewhere ([below](#mcp-lm-studio-only)) |

Under `Services` the model server is FAIL when down, named `lmstudio` on LM
Studio and `llm` otherwise; under `Config` its key row (`lmstudio key` or `llm
key`) shows the key's length, never the key. For a layer still holding a
`lmstudio:` block the doctor reports a `Config` FAIL row naming the file
(`legacy lmstudio`), and the game refuses to start (v0.21.0).

## MCP: LM Studio only

`llm.mcp` (the two-phase turn's Phase A: the model calls the engine's skills
through an in-process MCP server) runs only where the provider row has
`mcp_integrations`, which is LM Studio's alone: its native API's
`integrations` is the only route that carries an MCP server. With any other
provider and `llm.mcp.enabled: true`, Phase A is **off**: one ERROR per
process says why, the doctor shows a FAIL row, and every turn is exactly the
turn MCP-off sends. There is no engine-side tool loop to fall back to (a
**NOT WIRED** row in [GOVERNANCE.md](GOVERNANCE.md)); intents carry mechanics
on every server, as they always have.

## Secrets

`llm.api_key` is a fallback chain, tried left to right each time the key is
read; the first non-empty value wins: `llm_api_key.txt`, then `lmstudio.txt`
(both gitignored, first line, at the repository root), then the
`CLOCKWORK_LLM_API_KEY` and `LMSTUDIO_API_KEY` environment variables. The two
LM Studio-named sources, `lmstudio.txt` and `LMSTUDIO_API_KEY`, are written
`lmstudio?…` in the chain and read **only while `llm.provider` is
`lmstudio`**: on any other provider the key comes from `llm_api_key.txt`,
`CLOCKWORK_LLM_API_KEY`, or an `llm.api_key` set in `config/local.yaml`, so
an owner who keeps LM Studio's key in `lmstudio.txt` and switches to another
server (a remote `openai_compat` host, say) never sends it there. The key
is sent as a bearer token to the configured server, never logged, never put in
a URL. A server started without a key needs none of them.

Since v0.20.0 the scope is read exactly. An alternative is scoped when it
holds a `?` and the text before the first one holds no `:`, so a file
alternative whose path holds a `?` (`file:/srv/keys/what?.txt`, legal on
POSIX) is read whole: `file:` and `env:` put their `:` first, and no variable
name holds a `?`. A scope is compared with the provider names ignoring case
(`LMStudio?…` is LM Studio's). A scope that names no provider (`lmstuido?…`,
`lm-studio?…`, `openai-compat?…`) stops the config from loading, naming the
key and the scope, as an unknown `llm.provider` does; and `llm.provider`
itself cannot be a `${…}` reference. The in-game Settings panel refuses any
`${…}` value, and never writes a file the config would refuse.
When a scoped source is skipped but holds a key (the file is not empty, or the
variable is set), the doctor says so in a `skipped key` WARN under the model
server's section, naming the source and never the value.

## Moving from `lmstudio:`

A `config/local.yaml` written before v0.19.0 says `lmstudio:`. It was read as
`llm:`, with a warning, through v0.20.x; since v0.21.0 the game refuses to
start with it (`LegacyConfigError`), naming the file and the fix: rename the
block `llm:`, and its `ttl_seconds` `keep_alive_seconds`. A
`stack.services.lmstudio` block is refused the same way (rename it
`stack.services.llm`).
