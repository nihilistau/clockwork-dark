"""
The texter's latency probe, live (v0.23.0 spec §20.2, T9): run by hand against a REAL server.

Skipped, module and all, unless ``CLOCKWORK_LIVE_LLM`` names the provider the
config names (the same switch as ``tests/test_llm_live.py``, whose
``live_config`` fixture this module uses, so the owner's ``config/`` is read
from a temp copy and nothing under it is written)::

    $env:CLOCKWORK_LIVE_LLM = "lmstudio"
    .\\.venv\\Scripts\\python.exe -m pytest tests\\test_texter_latency_probe.py -v -s

One request per voice mode through the ``texter`` profile (reasoning off, the
mode's own ``max_tokens``, a prompt the size of the stub voice's measured p50,
``scripts/simulate_social.py``'s ``also.prompt_tokens.*``), asking for a reply
long enough to reach the cap. Each call's output tokens over its wall time is a
PROMPT-EVAL-WEIGHTED tokens-per-second figure; their median feeds
``simulate_social.latency_table``, which prints each mode's p50 and p95, and the
p95 with the starvation retry. Without this run the figure is ASSUMED, 20
tokens a second (``simulate_social.ASSUMED_TOKENS_PER_SECOND``;
docs/MODEL_SERVERS.md § The texter's latency). It asserts only that each call
answered; the numbers are for the record (T31 re-measures them live).
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import pytest

PROVIDER = os.environ.get("CLOCKWORK_LIVE_LLM", "").strip()
if not PROVIDER:
    pytest.skip("the texter latency probe: set CLOCKWORK_LIVE_LLM=<provider> to run it", allow_module_level=True)

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # scripts.* importable

from tests.social_fixtures import receipts_active  # noqa: E402,F401
from tests.test_llm_live import live_config  # noqa: E402,F401  (autouse: the temp config, the provider check)

#: The prompt's size: the stub voice's p50 prompt over T9's runs (``also.prompt_tokens.*.p50``, 1,830-2,110).
PROMPT_TOKENS = 2000

SYSTEM = ("You are texting someone you met on a dating app. Write your reply as plain text: warm, chatty, "
          "several sentences, and ask them something back.")


def _filler(tokens: int) -> str:
    from engine.social import memory

    line = ("Earlier today they told you about their week: work ran late, they tried a new cafe on the corner, "
            "and they are thinking about a weekend away by the sea. ")
    text = ""
    while memory._estimate({"text": text}) < tokens:
        text += line
    return text


def test_the_texter_throughput_and_each_modes_latency(receipts_active) -> None:
    import scripts.simulate_social as sim
    from engine.llm.backend import get_backend
    from engine.social import voicing

    backend = get_backend()
    context = _filler(PROMPT_TOKENS)
    rates: list[float] = []
    for mode in ("quick", "chatting", "deep"):
        cap = int(voicing.mode_caps(mode)["max_tokens"])
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": context + "\nTell me everything about your day, at length."}]
        began = time.perf_counter()
        reply = backend.chat(msgs, profile="texter", reasoning="off", label="social_voice_probe", max_tokens=cap)
        seconds = time.perf_counter() - began
        out = int(reply.output_tokens or 0) or max(1, len(str(reply.content or "")) // 4)
        rates.append(out / max(seconds, 1e-6))
        print(f"{mode}: cap {cap}, {out} output tokens, {reply.input_tokens} prompt tokens, {seconds:.1f} s, "
              f"finish {reply.finish_reason!r}")
        assert str(reply.content or "").strip(), f"{mode}: the texter answered nothing"
    rate = statistics.median(rates)
    print(f"tokens/s (prompt-eval weighted, median of {len(rates)}): {rate:.1f}")
    for mode, row in sim.latency_table(rate).items():
        print(f"  {mode}: p50 {row['p50_s']} s, p95 {row['p95_s']} s, p95 with the retry {row['p95_with_retry_s']} s")
    assert rate > 0
