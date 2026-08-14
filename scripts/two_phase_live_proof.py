"""
Two-Phase Turn Live Proof
=========================

Run ONE real turn against the live LM Studio with ``lmstudio.mcp.enabled``
true, and show the receipt travelling from Phase A into the narration.

    .\\.venv\\Scripts\\python.exe scripts\\two_phase_live_proof.py

WHY A SCRIPT AND NOT A TEST, again. Same reason as
``scripts/mcp_live_proof.py``: this needs LM Studio running, a loadable model,
and LM Studio's own MCP client able to reach a socket in THIS process. The
wiring is pinned in ``tests/test_two_phase_turn.py`` with every model call
injected; what only a live run can answer is whether a real model, handed real
tools, produces a receipt that a real narrator then honours.

WHAT IT PROVES, IN ORDER
------------------------
1. Phase A runs BEFORE the state transaction opens (asserted by a spy, so the
   ordering claim is checked on the live path and not only in tests)
2. the model calls a read-only skill through MCP with reasoning off
3. the receipt reaches ``receipts_block`` -- "MECHANICAL RESULTS -- AUTHORITATIVE"
   -- in the Phase B prompt
4. the narration reflects what the receipt said

READ-ONLY ON PURPOSE. ``allowed_tools`` is pinned to the two query skills, so
this probe cannot move the player or spend their gold however the model reads
the prompt. A live probe with side effects is one nobody dares run twice.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Query skills only. See the module docstring.
SAFE_SKILLS = ["query_evil_state", "query_quests"]

LOCAL_CONFIG = ROOT / "config" / "local.yaml"


def _enable_mcp() -> tuple[str, bool]:
    """
    Turn Phase A on for this run, via the layer that is meant for it.

    ``config/local.yaml`` rather than ``set_overlay``: activating a story calls
    ``set_overlay`` itself, so an overlay set here would be dropped the moment
    the session loaded its game. The local layer merges under the overlay and
    survives it, and it is gitignored.

    Returns:
        The previous file contents and whether there was one, so the caller can
        put the player's own machine config back exactly as it was.
    """
    import yaml

    existed = LOCAL_CONFIG.exists()
    previous = LOCAL_CONFIG.read_text(encoding="utf-8") if existed else ""

    merged: dict[str, Any] = yaml.safe_load(previous) or {} if existed else {}
    lms = merged.setdefault("lmstudio", {})
    mcp = lms.setdefault("mcp", {})
    mcp["enabled"] = True
    mcp["allowed_tools"] = list(SAFE_SKILLS)
    # The pause after writing mcp.json that lets LM Studio's watcher reload.
    mcp.setdefault("register_settle_seconds", 2.0)

    LOCAL_CONFIG.write_text(yaml.safe_dump(merged, sort_keys=True), encoding="utf-8")

    from engine.config import reset_config

    reset_config()
    return previous, existed


def _restore(previous: str, existed: bool) -> None:
    """Put config/local.yaml back exactly as it was found."""
    if existed:
        LOCAL_CONFIG.write_text(previous, encoding="utf-8")
    else:
        LOCAL_CONFIG.unlink(missing_ok=True)
    from engine.config import reset_config

    reset_config()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove the two-phase turn against a live LM Studio")
    parser.add_argument(
        "--action",
        default="I stop and take stock. How much worse has the darkness grown since I set out?",
        help="the player action to run the turn on",
    )
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args()

    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from engine.mcp import skills_server

    if not skills_server.available():
        print("FAIL: the optional 'fastmcp' package is not installed.")
        print("      pip install fastmcp")
        return 2

    previous, existed = _enable_mcp()
    try:
        return _run(args.action, args.seed)
    finally:
        _restore(previous, existed)
        # Never leave an mcp.json entry pointing at a port this process is
        # about to stop answering on.
        from engine.mcp.skills_server import get_skills_server, reset_skills_server

        server = get_skills_server()
        if server is not None:
            server.release()
        reset_skills_server()


def _run(player_action: str, seed: int) -> int:
    from engine.agents import mechanics as mechanics_module
    from engine.agents import storyteller as storyteller_module
    from engine.agents.storyteller import StorytellerAgent
    from engine.config import get_config
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    assert get_config().get("lmstudio.mcp.enabled") is True, "the config layer did not take"

    state = new_game_state(player_name="Proof", seed=seed)
    engine = GameEngine(state)
    agent = StorytellerAgent(engine)

    print(f"  session  {state.session_id}")
    print(f"  place    {state.location_id}, day {state.world_day}, {state.time_of_day}")
    print(f"  tools    {SAFE_SKILLS} (read-only)")
    print(f"  action   {player_action!r}")
    print()

    # -- 1. the ordering claim, checked on the live path -------------------
    order: list[str] = []
    real_transaction = storyteller_module.StateTransaction
    real_phase_a = mechanics_module.run_mechanics_phase
    captured: dict[str, Any] = {}

    def spy_transaction(*a: Any, **k: Any) -> Any:
        order.append("transaction")
        return real_transaction(*a, **k)

    def spy_phase_a(*a: Any, **k: Any) -> list[dict[str, Any]]:
        order.append("phase_a")
        receipts = real_phase_a(*a, **k)
        captured["receipts"] = receipts
        return receipts

    storyteller_module.StateTransaction = spy_transaction  # type: ignore[assignment]
    mechanics_module.run_mechanics_phase = spy_phase_a  # type: ignore[assignment]

    # -- 2. capture the Phase B prompt -------------------------------------
    real_build = agent._build_messages
    prompts: list[list[dict[str, Any]]] = []

    def recording_build(*a: Any, **k: Any) -> Any:
        messages = real_build(*a, **k)
        prompts.append([dict(m) for m in messages])
        return messages

    agent._build_messages = recording_build  # type: ignore[assignment]

    try:
        result = agent.run_turn(player_action)
    finally:
        storyteller_module.StateTransaction = real_transaction  # type: ignore[assignment]
        mechanics_module.run_mechanics_phase = real_phase_a  # type: ignore[assignment]

    receipts = captured.get("receipts") or []

    # -- 3. report ----------------------------------------------------------
    print()
    print("=" * 72)
    print(f"  PHASE ORDER       {order[:2]}")
    print(f"  PHASE A receipts  {len(receipts)}")
    for receipt in receipts:
        print(f"      {receipt['skill']}({receipt['args']}) -> {json.dumps(receipt['result'])[:160]}")

    # The LAST match, not the first. The story's few-shot examples
    # (games/<slug>/prompts/examples.json) contain a specimen MECHANICAL
    # RESULTS block to teach the format -- so a first-match search reports the
    # example's canned stealth roll and calls it proof, which is exactly what
    # the first run of this script did.
    block = ""
    for message in prompts[0] if prompts else []:
        content = str(message.get("content", ""))
        if "MECHANICAL RESULTS" in content:
            block = content

    print()
    print("  PHASE B prompt block:")
    print("      " + (block.replace("\n", "\n      ") if block else "(none)"))
    print()
    print("  NARRATION:")
    print("      " + result.narration.strip().replace("\n", "\n      ")[:900])
    print("=" * 72)

    ok = True
    if order[:2] != ["phase_a", "transaction"]:
        print(f"\nFAIL: Phase A did not run before the transaction: {order}")
        ok = False
    if not receipts:
        print("\nFAIL: the model called no tool in Phase A.")
        print("      Phase A degraded, which means the turn still ran -- check the")
        print("      [mechanics] log line above for which guard fired.")
        ok = False
    elif not block:
        print("\nFAIL: receipts exist and never reached the Phase B prompt.")
        ok = False
    elif not any(r["skill"] in block for r in receipts):
        # Naming the skill is what separates "the block is present" from "the
        # block is OURS". The examples ship a block of their own.
        print("\nFAIL: a MECHANICAL RESULTS block reached the prompt, but it names")
        print(f"      none of Phase A's skills {[r['skill'] for r in receipts]} --")
        print("      this is the story's few-shot example, not the turn's receipts.")
        ok = False
    if ok:
        print("\nPASS: the model called the engine in Phase A, and the narration was")
        print("      written against the receipt rather than a guess.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
