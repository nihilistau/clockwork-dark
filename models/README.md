# `model.yaml` overrides — no-think variants

These files are **not loaded by the game**. They are LM Studio configuration,
copied into LM Studio's own model folders, where LM Studio picks them up and
publishes each one as an **additional virtual model id** alongside the base
model.

## The problem they solve

`max_tokens` on a reasoning model caps **reasoning + content combined**. When a
utility call asks for 400 tokens and the model spends all 400 thinking, the
content channel comes back as the empty string. That is the confirmed cause of
blank narration and of the memory summarizer silently degrading to keyword
compression.

The obvious fixes do not work on LM Studio's OpenAI-compatible endpoint.
Measured against `nvidia/nemotron-3-nano-4b` on `POST /v1/chat/completions`,
asking for a three-word greeting:

| request | reasoning tokens |
| --- | --- |
| baseline | 55 |
| `reasoning: "off"` | 88 |
| `chat_template_kwargs: {enable_thinking: false}` | 143 |
| `reasoning_effort: "low"` | 113 |
| **`POST /api/v1/chat` with `reasoning: "off"`** | **0** |

Every OpenAI-compat knob is ignored. `reasoning_effort` is
[lmstudio-bug-tracker #988](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/988);
`enable_thinking` only works if the GGUF's Jinja template reads it, and
nemotron's does not.

## Two fixes, in order

1. **Automatic, no install.** `engine/lmstudio/backend.py` prefers LM Studio's
   native `POST /api/v1/chat`, which honours `reasoning: "off"`. Utility
   profiles (`small`, `draft`) ship with `reasoning: "off"` in
   `config/default.yaml`. This already works on a stock install.

2. **These files.** The native endpoint rejects `tools` and `response_format`
   outright, so tool calling and structured output *must* use the
   OpenAI-compatible route — where reasoning cannot be turned off per request.
   A `model.yaml` with `enableThinking: false` disables it at the template
   level, so the compat route stops thinking too.

Install fix 2 if the mechanics phase (which needs tools) is losing its token
budget to reasoning. Otherwise fix 1 is sufficient.

## Installing

Copy the file into the model's directory inside the LM Studio models folder,
beside the `.gguf`:

```
%USERPROFILE%\.lmstudio\models\<publisher>\<model>\<name>.model.yaml
```

Restart LM Studio, then confirm the new id exists:

```powershell
curl http://localhost:1234/api/v0/models | findstr nothink
```

Then bind the utility profiles to it in `config/local.yaml`:

```yaml
lmstudio:
  profiles:
    small:
      model: "nemotron-3-nano-4b-nothink"
    draft:
      model: "nemotron-3-nano-4b-nothink"
```

## If you skip this

Nothing breaks. `engine/lmstudio/registry.py` logs
`Configured model not on server` and binds by capability instead, preferring a
non-reasoning instruct model for the utility profiles. Only the tool-calling
mechanics pass loses the protection.

## Which profiles must not think

| profile | used by | reasoning |
| --- | --- | --- |
| `big` | narration | **on** — shown to the player as a live channel |
| `small` | summarizer, mechanics, Assistant, quest evaluation | **off** |
| `draft` | short utility completions | **off** |

Narration deliberately keeps reasoning. On a slow local turn the model's
thinking is the most interesting thing on screen, and the UI renders it as a
separate channel — it never reaches the narration text, the tag scanner, or the
image pipeline.
