"""
What a player reads for a choice the ENGINE words: a card beat, a rest.

K1 (v0.21.0 final review, finding 1). A card beat's ``text`` is the
narrator's direction -- ``prompts._scene_block`` prints it under "render it,
do not replace it" -- and authors write notes into it ("Sets
`resisted_call`, which is the only thing on this day that changes..."). The
same text was the intent enum's label, so it reached the player as the
resumed frame's chip text and as the hint line under every card chip.

The player now reads ``director.player_label``: the beat's authored
``label``, else the first sentence of its text with backticked spans removed.
The narrator's prompt and the enum keep the full text.

Finding 3: a rest entry's catalogue label is its de-underscored id ("sleep
flophouse"); the player reads the entry's authored ``label``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from engine.content import director

ROOT = Path(__file__).resolve().parents[1]
#: Every shipped story's deck files.
DECK_FILES = sorted(ROOT.glob("games/*/data/scenes/*.yaml"))
SNAKE = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b")


def _menu_beats() -> list[tuple[str, str, dict[str, Any], str]]:
    rows = []
    for path in DECK_FILES:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        for card in data.get("cards") or []:
            if "menu" not in (card.get("tags") or []):
                continue
            for beat in card.get("beats") or []:
                if isinstance(beat, dict) and beat.get("id"):
                    rows.append((path.parent.parent.parent.name, str(card.get("id")), beat, str(card.get("title") or "")))
    return rows


MENU_BEATS = _menu_beats()


def test_there_are_menu_beats_to_check() -> None:
    assert len(MENU_BEATS) > 100, len(MENU_BEATS)


def test_every_menu_beat_has_a_clean_player_label() -> None:
    """For every story, every deck, every menu beat: non-empty, no code span, no id."""
    bad = []
    for story, card_id, beat, title in MENU_BEATS:
        label = director.player_label(beat, fallback=title)
        if not label or "`" in label or SNAKE.search(label):
            bad.append(f"{story} {card_id}/{beat['id']}: {label!r}")
    assert not bad, "\n".join(bad)


def test_no_menu_beat_label_reads_as_an_authors_note() -> None:
    notes = re.compile(r"^(Sets\b|Resolve\b|Always\.|RARE\b|INTENT\b|CONSTRAINTS\b|MENU\b)")
    bad = [
        f"{story} {card_id}/{beat['id']}: {director.player_label(beat)!r}"
        for story, card_id, beat, _title in MENU_BEATS
        if notes.match(director.player_label(beat))
    ]
    assert not bad, "\n".join(bad)


def test_the_label_is_authored_or_the_first_sentence_without_code() -> None:
    assert director.player_label({"label": "Refuse and walk", "text": "Sets `x`."}) == "Refuse and walk"
    beat = {"text": "Refuse and walk. The path relocates. Sets `resisted_call`, which matters."}
    assert director.player_label(beat) == "Refuse and walk."
    assert director.player_label({"text": "Take the `brass_key` from the hook. Then go."}) == (
        "Take the from the hook."
    )
    assert director.player_label({"text": "Sets `x`, which routes the night."}) == (
        "Sets, which routes the night."
    )
    assert director.player_label({"text": "`a_b`"}, fallback="The Card") == "The Card"


@pytest.mark.parametrize("story", sorted({row[0] for row in MENU_BEATS}))
def test_the_validator_advises_on_no_shipped_beat(story: str) -> None:
    """With the labels authored, no shipped story trips the beat-label advisory."""
    from engine.games import registry
    from engine.games.validation import StoryValidator

    manifest = registry.activate(story)
    issues = StoryValidator(manifest).run()
    hits = [str(i) for i in issues if "author's note" in i.message]
    assert not hits, "\n".join(hits)


def test_the_validator_advises_on_a_note_with_no_label() -> None:
    from engine.games import registry
    from engine.games.validation import StoryValidator

    validator = StoryValidator(registry.activate("wicked-garden"))
    card = {"tags": ["menu"], "beats": [
        {"id": "a", "text": "Refuse. Sets `resisted_call`."},
        {"id": "b", "text": "Always. She goes."},
        {"id": "c", "text": "Walk on.", },
        {"id": "d", "label": "Walk", "text": "Sets `x`."},
    ]}
    validator.issues = []
    validator._check_beat_shapes("deck.yaml", "C1", card)
    flagged = sorted(i.ref_id for i in validator.issues if "author's note" in i.message)
    assert flagged == ["C1/a", "C1/b"], flagged
    assert all(i.severity == "warning" for i in validator.issues if "author's note" in i.message)


def _deal_menu_card(story: str, card_id: str) -> Any:
    """Activate ``story`` and open a scene on the deck holding ``card_id``."""
    from engine.game.state import GameState
    from engine.games import registry

    registry.activate(story)
    deck_id, _ = director._deck_holding_card(card_id)
    assert deck_id, card_id
    state = GameState(session_id="labels")
    state.scene = {"deck_id": deck_id, "card_ids": [card_id], "cursor": 0, "source": "test"}
    return state


def test_card_chips_read_the_player_label_on_resume_and_on_a_turn() -> None:
    """
    The Wicked Garden's prologue threshold card, dealt: the resumed chips and
    an ordinary turn's hint line both read the label; the prompt's options
    keep the narrator's text.
    """
    from engine.game import intents
    from engine.memory.ledger import StoryLedger
    from engine.scenes.default_state import _label_intents, resume_opening

    state = _deal_menu_card("wicked-garden", "P1_threshold_slip")
    texts = [c["text"] for c in resume_opening(state, StoryLedger())["choices"]]
    assert "Refuse and walk" in texts, texts
    assert not any("`" in t or "Sets " in t for t in texts), texts

    labelled = _label_intents(state, [
        {"id": "x", "text": "Walk away from it", "intent": {"action": "card", "target": "turn_away_hard"}},
        {"id": "y", "text": "turn_away_hard", "intent": {"action": "card", "target": "turn_away_hard"}},
    ])
    assert labelled[0].get("intent_label") == "Refuse and walk", labelled[0]
    assert labelled[1]["text"] == "Refuse and walk", labelled[1]

    narrator = dict(intents.find_verb(intents.legal_intents(state), "card").options)
    assert "Sets `resisted_call`" in narrator["turn_away_hard"]


def test_a_cell_offers_the_rest_entries_by_their_labels() -> None:
    """Finding 3: a resume in custody on HUE & CRY reads the survival labels."""
    from engine.game.effects import apply_effect
    from engine.game.procgen import new_game_state
    from engine.games import registry
    from engine.memory.ledger import StoryLedger
    from engine.scenes.default_state import resume_opening
    from engine.world import law

    registry.activate("hue-and-cry")
    state = new_game_state(seed=1021)
    state.location_id = "wickmarket"
    apply_effect(state, {"type": "arrest"})
    assert law.in_custody(state)
    texts = [c["text"] for c in resume_opening(state, StoryLedger())["choices"]]
    assert "The plank bench in the cells" in texts, texts
    assert not any(t.casefold() in ("sleep flophouse", "rest short", "sleep cell") for t in texts), texts


@pytest.mark.parametrize("story", ["wicked-garden", "clockwork-dark", "hue-and-cry", "neon-city"])
def test_every_epilogue_echo_carries_a_speaker_name(story: str) -> None:
    """Finding 5: the epilogue card printed an echo's speaker id ("npc ilya")."""
    from engine.game import epilogue
    from engine.games import registry

    registry.activate(story)
    shipped = re.findall(r"speaker:\s*([a-z0-9_]+)", " ".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "games" / story / "data").rglob("*.yaml")
        if "epilogue" in p.name
    ))
    rows = [{"speaker": s, "text": "x"} for s in sorted(set(shipped)) + ["npc_ilya", "ashen_vale"]]
    for echo in epilogue._echoes(rows):
        assert echo["speaker_name"], echo
        assert "_" not in echo["speaker_name"] and not echo["speaker_name"].lower().startswith("npc "), echo
