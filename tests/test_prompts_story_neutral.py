"""
The Prompt Layer Names No Story
===============================

The engine used to ship one story's voice as every story's default. The
persona, the two few-shot exchanges and the companion's folklore were Python
string literals in ``engine/agents/prompts.py``, handed to any story that
declared no ``paths.prompts`` -- so a second story never really loaded, it wore
the flagship's narrator. Nothing failed. The model simply announced it was
somewhere else, and only a human reading the output would ever notice.

That is what these tests exist to make noisy. They assert on the STRINGS THE
MODEL ACTUALLY RECEIVES rather than on the module's source, because the defect
is what reaches the model: this module's comments still discuss Edgewood at
length, and correctly so -- explaining a bug requires naming it.

Version: v0.1.0 [2026-08-09]
"""

from __future__ import annotations

import logging

import pytest

from engine.agents import prompts
from engine.config import project_root, set_overlay
from engine.game.state import GameState
from engine.games import registry

#: Every shipped story, as (slug, manifest title). A new story is a one-line
#: addition here and the cross-checks below stay exhaustive.
SHIPPED = (
    ("clockwork-dark", "The Clockwork Dark"),
    ("wicked-garden", "The Wicked Garden"),
    ("dev-story", "Dev Story"),
)


@pytest.fixture(autouse=True)
def _restore_active_game():
    """Leave the process on whatever story it was running."""
    before = registry.active_slug()
    yield
    set_overlay(None)
    registry.activate(before)


@pytest.mark.parametrize("slug,_title", SHIPPED)
def test_each_story_narrates_from_its_own_file(slug, _title):
    """
    The persona the model receives IS the story's own storyteller.md.

    Stated as file identity rather than as "contains its own title", because a
    story is allowed to open however it likes -- dev-story deliberately never
    names itself -- and the invariant under test is whose words arrive, not
    what they say.
    """
    registry.activate(slug)
    own = (project_root() / "games" / slug / "prompts" / "storyteller.md")
    assert own.is_file(), f"{slug} ships no storyteller.md"
    assert prompts.storyteller_persona() == own.read_text(encoding="utf-8").strip()


def test_no_two_stories_are_handed_the_same_narrator():
    """
    The defect, stated directly. This is the test that would have caught it.

    Before the fix all three of these were byte-identical: the flagship's
    persona, because only the flagship had one and the engine handed it out.
    """
    seen: dict[str, str] = {}
    for slug, _title in SHIPPED:
        registry.activate(slug)
        seen[slug] = prompts.storyteller_persona()
    assert len(set(seen.values())) == len(SHIPPED), {k: v[:60] for k, v in seen.items()}


def test_the_flagship_owns_its_own_voice_on_disk():
    """
    The persona is a file in the story's package, not a literal in the engine.

    Asserting the FILE exists as well as the string it produces, because the
    string alone would still pass if someone put the flagship back in Python.
    """
    directory = project_root() / "games" / "clockwork-dark" / "prompts"
    assert (directory / "storyteller.md").is_file()
    assert (directory / "examples.json").is_file()

    registry.activate("clockwork-dark")
    assert prompts._prompts_dir() == directory
    assert prompts.storyteller_persona().startswith(
        'You are the STORYTELLER of "The Clockwork Dark"'
    )


def test_the_flagship_still_ships_its_two_worked_examples():
    """Extracting the literals to a file must not have dropped the few-shots."""
    registry.activate("clockwork-dark")
    rows = prompts.storyteller_examples()
    assert len(rows) == 5
    assert [r["role"] for r in rows] == [
        "user",
        "assistant",
        "system",
        "user",
        "assistant",
    ]
    assert "Maris" in rows[0]["content"]


@pytest.mark.parametrize("slug", ["wicked-garden", "dev-story"])
def test_a_story_with_no_examples_gets_none_rather_than_the_flagship_s(slug):
    """
    A few-shot is the strongest signal in the prompt about what a turn looks
    like, so an inherited one teaches every story to sound like Edgewood. None
    is the correct answer; the flagship's is not.
    """
    registry.activate(slug)
    assert prompts.storyteller_examples() == []


def test_an_undescribed_story_gets_a_neutral_persona_and_a_loud_warning(caplog):
    """
    The fallback exists, and it says so.

    A blank narrator would be harder to diagnose than a plain one -- the model
    still answers, so the symptom surfaces as strange prose several turns later
    rather than as a stack trace at activation. So the engine narrates plainly
    and logs the key the author has to declare.
    """
    registry.activate("clockwork-dark")
    prompts.reset_prompt_warnings()
    set_overlay({"paths": {"prompts": "games/no-such-story/prompts"}})

    with caplog.at_level(logging.WARNING, logger="engine.agents.prompts"):
        persona = prompts.storyteller_persona()

    assert "paths.prompts" in caplog.text
    assert "clockwork-dark" in caplog.text

    # Neutral means neutral: it may name the running story's TITLE, and nothing
    # else about any story.
    for word in ("Edgewood", "Maris", "Odran", "Sophia", "frontier", "fae"):
        assert word.lower() not in persona.lower()
    assert "second person, present tense" in persona.lower()


def test_the_warning_is_said_once_per_story_not_once_per_turn(caplog):
    """``storyteller_persona`` runs every turn, and a per-turn WARNING is noise."""
    registry.activate("clockwork-dark")
    prompts.reset_prompt_warnings()
    set_overlay({"paths": {"prompts": "games/no-such-story/prompts"}})

    with caplog.at_level(logging.WARNING, logger="engine.agents.prompts"):
        for _ in range(5):
            prompts.storyteller_persona()

    said = [r for r in caplog.records if "paths.prompts" in r.getMessage()]
    assert len(said) == 1


@pytest.mark.parametrize("slug,title", SHIPPED)
def test_the_companion_is_story_owned_too(slug, title):
    """
    The Grey Wanderer is Edgewood folklore and lived in the engine's f-string.

    The volatile half stays the engine's -- forms, hint tier and place are
    state, not voice -- so those are asserted present as well.
    """
    registry.activate(slug)
    state = GameState()
    prompt = prompts.assistant_system_prompt(state, hint_tier=2)

    assert title in prompt
    assert "HINT TIER: 2" in prompt
    assert "FORMS:" in prompt
    if slug != "clockwork-dark":
        for word in ("Grey Wanderer", "Cat Who Knows", "Edgewood"):
            assert word.lower() not in prompt.lower()


def test_the_directive_block_describes_escalation_not_a_setting():
    """
    ``EvilPhaseTone`` shipped the flagship's imagery -- "cosy frontier life",
    "brass glints" -- into every story's directives, one layer quieter than the
    persona did. The curve is the engine's; the images are the story's.
    """
    from engine.agents.governance import EvilPhaseTone

    joined = " ".join(EvilPhaseTone._TONE.values()).lower()
    for word in ("frontier", "brass", "village", "wheat"):
        assert word not in joined


# ---------------------------------------------------------------------------
# The spoiler vocabulary
#
# The awareness gate rewrites terms the player has not earned yet. WHICH terms
# was a Python list in `engine/lore/interceptors.py` naming one story's nouns,
# so every story masked The Clockwork Dark's vocabulary: a fae court below the
# threshold had its narration rewritten to talk about wheat, and a story with
# no `evil_progress` paid the regex on every turn regardless.
#
# The engine owns the GATE -- when to redact, and the leading-article match
# that keeps the replacement readable. The story owns the WORDS.
# ---------------------------------------------------------------------------


SPOILER_LINE = "The Clockwork Dark stirs; evil_progress rises toward CONSUMING."


def test_the_flagship_still_redacts_exactly_what_it_did():
    """
    The compatibility bar. These three substitutions shipped for months and a
    player below the threshold must see the same sentence they always saw.
    """
    from engine.lore.interceptors import AwarenessGateInterceptor, spoiler_terms

    registry.activate("clockwork-dark")
    assert len(spoiler_terms()) == 3
    gated = AwarenessGateInterceptor().gate(SPOILER_LINE, 0.0)
    assert gated == (
        "something wrong in the wheat stirs; the village's unease rises "
        "toward the worst of it."
    )


@pytest.mark.parametrize("slug", ["wicked-garden", "dev-story"])
def test_another_story_is_not_made_to_talk_about_wheat(slug):
    """
    A story that declares no spoilers redacts NOTHING, which is the correct
    nothing -- the gate still runs, it has simply been told no vocabulary.

    Asserted on the Garden specifically because it is the case that was wrong:
    a fae court has no wheat, no village and no `evil_progress`, and rewriting
    its narration into Edgewood's idiom is a bug the player would read.
    """
    from engine.lore.interceptors import AwarenessGateInterceptor, spoiler_terms

    registry.activate(slug)
    assert spoiler_terms() == ()
    assert AwarenessGateInterceptor().gate(SPOILER_LINE, 0.0) == SPOILER_LINE


def test_no_story_vocabulary_is_left_in_the_interceptor_module():
    """
    Source-level, deliberately. The table is gone; this stops it coming back as
    a convenient default the next time somebody wants redaction to "just work".

    Comments and docstrings are stripped before the scan, and that is not a
    loophole -- the module's docstring QUOTES the old phrases to explain what
    went wrong, which is the house style and worth keeping. What must not come
    back is a phrase the engine can actually substitute, so the test reads the
    module the way Python does: as an AST, with the prose removed.
    """
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "engine" / "lore" / "interceptors.py"
    ).read_text(encoding="utf-8")

    # Every string literal that is NOT a docstring. A docstring is the first
    # statement of a module, class or function; anything else is a value the
    # code can reach.
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    live = " ".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    )

    for phrase in ("something wrong in the wheat", "the village's unease", "the worst of it"):
        assert phrase not in live, f"{phrase!r} is a live string in the engine again"
