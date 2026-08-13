"""
The LLM authoring tool, fully offline.

Every test injects a fake backend at the seam ``scripts/author.py`` actually
calls (``backend.chat(messages, profile=..., response_format=...)``), so the
suite proves the whole pipeline -- schema per kind, JSON-to-YAML conversion,
staged validation through the shared backbone, the repair loop's cap, the
promote gate -- without a live LM Studio anywhere near it. The fake dispatches
on the response schema's ``name``, which is also a standing assertion that
every call declares its grammar: a call without a schema has no name to
dispatch on and fails the test.

The stories under test are scaffolded by ``scripts/new_story.py`` into a temp
games root, through the same ``project_root`` seam ``tests/test_new_story.py``
established -- nothing here touches the repo's own ``games/``.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest
import yaml

from engine.games import registry, validation

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered BEFORE exec: dataclass field-type resolution looks the module
    # up in sys.modules, and a script exec'd outside it has no home to resolve
    # against (author.py carries dataclasses; new_story.py happens not to).
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


author_mod = _load_script("author")
new_story = _load_script("new_story")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def story_root(tmp_path, monkeypatch):
    """A temp repo root the registry believes in (the test_new_story seam)."""
    (tmp_path / "games").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("engine.games.manifest.project_root", lambda: tmp_path)
    monkeypatch.setattr("engine.games.registry.project_root", lambda: tmp_path)
    return tmp_path


SLUG = "probe-author"


def _augment(story_dir: pathlib.Path) -> None:
    """Give the minimal scaffold every content section the tool can draft.

    Stub files only -- empty tables that validate clean -- so each test's
    drafts are the only content that can break anything.
    """
    rel = f"games/{SLUG}"
    (story_dir / "data" / "world" / "npc_schedules.yaml").write_text(
        "version: 1\nnpcs: {}\n", encoding="utf-8"
    )
    (story_dir / "data" / "world" / "rumors.yaml").write_text(
        "version: 1\nrumors: []\n", encoding="utf-8"
    )
    quests = story_dir / "data" / "quests"
    quests.mkdir(parents=True)
    (quests / "arcs.yaml").write_text("arcs:\n  beginnings: {order: 1}\n", encoding="utf-8")
    scenes = story_dir / "data" / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "visit.yaml").write_text(
        "id: visit\ndraw: 0\ncards:\n"
        "  - id: v1\n    title: A Card\n    text: The worked example.\n"
        "    tags: [sequence]\n    beats: []\n",
        encoding="utf-8",
    )
    (story_dir / "data" / "encounters").mkdir(parents=True)
    (story_dir / "data" / "lore").mkdir(parents=True)

    manifest_path = story_dir / "game.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    data["paths"].update(
        {
            "npc_schedules": f"{rel}/data/world/npc_schedules.yaml",
            "world_rumors": f"{rel}/data/world/rumors.yaml",
            "quests": f"{rel}/data/quests",
            "decks": f"{rel}/data/scenes",
            "encounters": f"{rel}/data/encounters",
            "lore": f"{rel}/data/lore",
        }
    )
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def story(story_root):
    """A scaffolded minimal story with every draftable section declared."""
    destination = new_story.scaffold(SLUG, template="minimal", games_root=story_root / "games")
    _augment(destination)
    manifest = registry.get(SLUG)
    assert manifest is not None
    issues = validation.validate_story(manifest)
    assert not validation.errors_only(issues), "the fixture story must start clean"
    return destination


class FakeBackend:
    """Stands in for engine.lmstudio.backend.LMStudioBackend.

    Scripts are keyed by the response schema's name; a list is consumed one
    payload per call, holding on the last entry -- which is how the repair
    tests express "broken, then fixed" and "broken forever".
    """

    def __init__(self, scripts: dict[str, object]) -> None:
        self.scripts = {
            name: list(payloads) if isinstance(payloads, list) else [payloads]
            for name, payloads in scripts.items()
        }
        self.calls: list[tuple[str, str]] = []

    def chat(self, messages, *, profile="big", response_format=None, temperature=None,
             max_tokens=None, label="", **_kw):
        assert response_format is not None, "every authoring call must carry a schema"
        name = response_format["json_schema"]["name"]
        self.calls.append((name, label))
        queue = self.scripts[name]
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return SimpleNamespace(content=json.dumps(payload))


def _author(backend: FakeBackend) -> "author_mod.Author":
    return author_mod.Author(SLUG, backend=backend)


# ---------------------------------------------------------------------------
# canned payloads -- one valid example per kind, referencing the fixture's ids
# ---------------------------------------------------------------------------

GARDEN = {
    "id": "garden",
    "name": "The Garden",
    "ring": 1,
    "summary": "A walled garden behind the house, overgrown at the edges and "
    "full of good hiding places for small things.",
    "tags": ["outdoors"],
    "connections": [{"to": "front_room", "hours": 0}],
}

CANNED = {
    "author_location": {"locations": [GARDEN]},
    "author_npc": {
        "npcs": [
            {
                "id": "marta",
                "name": "Marta",
                "role": "gardener",
                "home": "front_room",
                "routine": [
                    {"hours": [8, 9, 10], "location": "front_room", "activity": "watering the window plants"}
                ],
            }
        ]
    },
    "author_item": {
        "items": [
            {
                "id": "pressed_flower",
                "name": "Pressed Flower",
                "description": "A flower flattened between book pages, keeping "
                "its colour rather better than its shape.",
                "tags": ["curio"],
                "weight": 0.01,
                "value": 1,
            }
        ]
    },
    "author_quest": {
        "id": "tea_for_two",
        "arc": "beginnings",
        "name": "Tea for Two",
        "summary": "Alex wants tea, the cups live in the back room, and the "
        "kettle has opinions about being hurried.",
        "start_text": "Alex looks up hopefully. 'Any chance of tea? Cups are in the back.'",
        "stages": [
            {
                "id": "fetch_the_cup",
                "objective": "Pick up the cup of tea from the back room.",
                "complete_when": {"all": [{"has_item": "cup_of_tea"}]},
                "complete_text": "Warm, full, and only slightly chipped.",
            }
        ],
    },
    "author_deck": {
        "id": "evening_visit",
        "draw": 0,
        "cards": [
            {
                "id": "ev_01_arrival",
                "title": "Arrival",
                "text": "INTENT: the house takes your coat before anyone speaks.",
                "tags": ["sequence"],
                "beats": [
                    {
                        "id": "ev_01_door",
                        "text": "The door answers before you knock twice.",
                        "gate": {
                            "on_pass": {
                                "text": "In you go.",
                                "effects": [{"type": "value", "name": "standing", "delta": 2}],
                            }
                        },
                    }
                ],
            }
        ],
    },
    "author_card": {
        "deck_id": "visit",
        "cards": [
            {
                "id": "v2_second_thoughts",
                "title": "Second Thoughts",
                "text": "INTENT: the pause on the doorstep. MENU.",
                "tags": ["menu"],
                "beats": [{"id": "v2_a", "text": "You knock anyway."}],
            }
        ],
    },
    "author_encounter": {
        "band": "house",
        "encounters": [
            {
                "id": "loose_dog",
                "tier": 1,
                "weight": 10,
                "triggers": {"edges": ["front_room>doorstep"]},
                "intro": "A dog with opinions has taken up a position between "
                "you and the street, and it is not moving first.",
                "threat": {"name": "A dog with opinions", "resolve": 1},
                "approaches": [
                    {"key": "talk_it_down", "skill": "sympathy", "difficulty": "easy", "text": "Soothe it"},
                    {"key": "edge_past", "skill": "stealth", "difficulty": "easy", "text": "Edge past it"},
                ],
                "outcomes": {
                    "crit_success": {"text": "It decides you are a friend for life."},
                    "success": {"text": "It lets you pass with dignity intact."},
                    "partial": {"text": "You pass, at the cost of a sleeve."},
                    "failure": {"text": "You retreat indoors to think again."},
                },
            }
        ],
    },
    "author_rumor": {
        "rumors": [
            {
                "id": "someone_new",
                "text": "Someone new is staying at the house, and the kettle "
                "has been on twice as often.",
                "tier": 1,
                "min_awareness": 0,
            }
        ]
    },
    "author_lore": {
        "title": "The House",
        "sections": [
            {
                "heading": "The Kettle",
                "body": "The kettle is older than the house's current arrangement "
                "of walls, and it has outlived two stoves and at least one "
                "argument about replacing it. Nobody remembers buying it.",
            }
        ],
    },
    "author_prompt": {
        "name": "narrator_notes",
        "persona": "You narrate a small house on an ordinary street. Speak in "
        "second person, present tense, close to the ground: kettles, coats, "
        "chairs, the exact quality of the light. Never explain a feeling the "
        "furniture could imply instead. Keep beats under two hundred words.",
    },
    "author_spoilers": {
        "spoilers": [
            {"term": "the misdelivered letter", "instead": "an unopened envelope"}
        ]
    },
}

ALL_KINDS = sorted(author_mod.KINDS)


# ---------------------------------------------------------------------------
# 1. every kind drafts something the shared validator accepts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_each_kind_drafts_clean_against_the_shared_validator(story, kind):
    """The point of the tool: a draft is valid before anyone reads it."""
    fake = FakeBackend(CANNED)
    author = _author(fake)
    path = author.draft(kind, "a small test brief")
    assert path.is_file()
    assert (story / "data" / "drafts" / kind) in path.parents

    report = author.validate_drafts()
    assert not report.by_draft, f"{kind} draft attracted errors: {report.by_draft}"
    assert not report.errors, [str(i) for i in report.errors]


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_drafting_never_writes_outside_the_drafts_tree(story, kind):
    before = {p for p in story.rglob("*") if p.is_file()}
    author = _author(FakeBackend(CANNED))
    author.draft(kind, "a small test brief")
    added = {p for p in story.rglob("*") if p.is_file()} - before
    assert added, "the draft went nowhere at all"
    drafts_root = story / "data" / "drafts"
    for path in added:
        assert drafts_root in path.parents, f"{path} landed outside data/drafts"


def test_yaml_drafts_carry_a_generated_by_header(story):
    author = _author(FakeBackend(CANNED))
    path = author.draft("item", "one keepsake item, sentimental value only")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Drafted by scripts/author.py")
    assert "keepsake" in text  # the brief is named
    body = yaml.safe_load(text)
    assert body["items"][0]["id"] == "pressed_flower"


def test_an_unknown_kind_is_refused(story):
    author = _author(FakeBackend(CANNED))
    with pytest.raises(author_mod.AuthorError, match="unknown kind"):
        author.draft("dragon", "no")


def test_prose_instead_of_json_fails_loudly_after_one_reprompt(story):
    class ProseBackend(FakeBackend):
        def chat(self, messages, **kw):
            self.calls.append(("prose", kw.get("label", "")))
            return SimpleNamespace(content="Once upon a time there was no JSON.")

    author = _author(ProseBackend({}))
    with pytest.raises(author_mod.AuthorError, match="valid JSON"):
        author.draft("item", "anything")
    assert len(author._backend.calls) == 2  # the reprompt happened, then it gave up


# ---------------------------------------------------------------------------
# 2. the schemas themselves are grammar-safe
# ---------------------------------------------------------------------------


def _walk_schemas(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_schemas(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_schemas(value)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_every_object_schema_is_strict(story, kind):
    """LM Studio grammars need closed objects; an open one samples anything."""
    author = _author(FakeBackend(CANNED))
    envelope = author_mod.SCHEMA_BUILDERS[kind](author.vocabulary(), 1)
    assert envelope["strict"] is True and envelope["name"] == f"author_{kind}"
    for node in _walk_schemas(envelope["schema"]):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, f"open object in {kind}"
            assert isinstance(node.get("required"), list), f"no required list in {kind}"


def test_schemas_enum_constrain_the_storys_own_vocabulary(story):
    """The npc-ids trick, applied to authoring: unsampleable > repairable."""
    author = _author(FakeBackend(CANNED))
    vocab = author.vocabulary()

    quest = author_mod.SCHEMA_BUILDERS["quest"](vocab, 1)["schema"]
    assert quest["properties"]["arc"] == {"enum": ["beginnings"]}

    encounter = author_mod.SCHEMA_BUILDERS["encounter"](vocab, 1)["schema"]
    approach = encounter["properties"]["encounters"]["items"]["properties"]["approaches"]["items"]
    assert set(approach["properties"]["skill"]["enum"]) == set(vocab.skills)
    assert set(approach["properties"]["difficulty"]["enum"]) == set(vocab.bands)

    # The fixture story has no npcs, so the rumor schema must not offer a
    # source_npc field at all -- an empty enum is unsatisfiable.
    rumor = author_mod.SCHEMA_BUILDERS["rumor"](vocab, 1)["schema"]
    assert "source_npc" not in rumor["properties"]["rumors"]["items"]["properties"]


# ---------------------------------------------------------------------------
# 3. validation ignores the drafts tree
# ---------------------------------------------------------------------------


def test_validate_story_ignores_broken_yaml_under_data_drafts(story):
    """The convention: games/<slug>/data/drafts is invisible to the build."""
    junk = story / "data" / "drafts" / "items"
    junk.mkdir(parents=True)
    (junk / "broken.yaml").write_text("items: [unclosed", encoding="utf-8")
    (junk / "ghost.yaml").write_text(
        "items:\n  - id: ghost\n", encoding="utf-8"  # no name/desc/tags: 4 errors if swept
    )
    issues = validation.validate_story(registry.get(SLUG))
    assert not issues, [str(i) for i in issues]


def test_section_walkers_skip_a_drafts_dir_nested_in_declared_content(story):
    """Even a drafts/ subtree INSIDE a declared directory is not content."""
    nested = story / "data" / "items" / "drafts"
    nested.mkdir(parents=True)
    (nested / "half_finished.yaml").write_text(
        "items:\n  - id: half_finished\n", encoding="utf-8"
    )
    issues = validation.validate_story(registry.get(SLUG))
    assert not issues, [str(i) for i in issues]
    items, item_issues = validation.load_story_items(registry.get(SLUG))
    assert "half_finished" not in items and not item_issues


# ---------------------------------------------------------------------------
# 4. the repair loop
# ---------------------------------------------------------------------------

BROKEN_GARDEN = {
    "locations": [dict(GARDEN, connections=[{"to": "nowhere", "hours": 1}])]
}


def test_repair_feeds_errors_back_and_fixes_the_draft(story):
    fake = FakeBackend({"author_location": [BROKEN_GARDEN, CANNED["author_location"]]})
    author = _author(fake)
    path = author.draft("location", "a garden behind the house")

    report = author.validate_drafts()
    assert path in report.by_draft
    assert any("edge target does not exist" in e for e in report.by_draft[path])

    final = author.repair()
    assert final.clean, final.by_draft
    fixed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "front_room" in fixed["locations"]["garden"]["connections"]

    # The repair prompt carried the offending YAML and the error text.
    assert fake.calls == [("author_location", "author:draft:location"),
                          ("author_location", "author:repair:location")]


def test_repair_stops_at_the_cap_and_reports_what_still_fails(story):
    fake = FakeBackend({"author_location": [BROKEN_GARDEN]})  # broken forever
    author = _author(fake)
    path = author.draft("location", "a garden behind the house")

    final = author.repair()
    assert path in final.by_draft, "the report must name what it could not fix"
    repair_calls = [c for c in fake.calls if c[1] == "author:repair:location"]
    assert len(repair_calls) == author_mod.MAX_REPAIR_ATTEMPTS


def test_a_draft_colliding_with_a_live_id_is_an_attributed_error(story):
    payload = {"locations": [dict(GARDEN, id="front_room")]}
    fake = FakeBackend({"author_location": payload})
    author = _author(fake)
    path = author.draft("location", "redecorating the front room")
    report = author.validate_drafts()
    assert any("already exists" in e for e in report.by_draft[path])


# ---------------------------------------------------------------------------
# 5. promote
# ---------------------------------------------------------------------------


def test_promote_refuses_while_errors_exist_and_touches_nothing(story):
    author = _author(FakeBackend({"author_location": BROKEN_GARDEN}))
    draft_path = author.draft("location", "a garden")
    live = story / "data" / "world" / "locations.yaml"
    before = live.read_text(encoding="utf-8")

    with pytest.raises(author_mod.AuthorError, match="refusing to promote"):
        author.promote("all")

    assert live.read_text(encoding="utf-8") == before
    assert draft_path.is_file(), "a refused promote must leave the draft in place"


def test_promote_merges_a_single_file_kind_and_keeps_the_banner(story):
    author = _author(FakeBackend(CANNED))
    author.draft("location", "a garden behind the house")
    live = story / "data" / "world" / "locations.yaml"
    first_line = live.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#")

    written = author.promote("location")
    assert written == [live]
    text = live.read_text(encoding="utf-8")
    assert text.splitlines()[0] == first_line, "the live file's banner was lost"
    doc = yaml.safe_load(text)
    assert {"front_room", "back_room", "doorstep", "garden"} <= set(doc["locations"])
    assert not (story / "data" / "drafts" / "location").exists()

    issues = validation.validate_story(registry.get(SLUG))
    assert not validation.errors_only(issues), [str(i) for i in issues]


def test_promote_copies_a_directory_kind_and_appends_cards(story):
    author = _author(FakeBackend(CANNED))
    author.draft("quest", "a small errand")
    author.draft("card", "one more card for the visit deck")
    author.promote("all")

    quest = story / "data" / "quests" / "tea_for_two.yaml"
    assert quest.is_file()
    assert yaml.safe_load(quest.read_text(encoding="utf-8"))["arc"] == "beginnings"

    deck = yaml.safe_load((story / "data" / "scenes" / "visit.yaml").read_text(encoding="utf-8"))
    assert [c["id"] for c in deck["cards"]] == ["v1", "v2_second_thoughts"]

    issues = validation.validate_story(registry.get(SLUG))
    assert not validation.errors_only(issues), [str(i) for i in issues]


def test_promote_moves_markdown_kinds_into_their_declared_dirs(story):
    author = _author(FakeBackend(CANNED))
    author.draft("lore", "the house's history")
    author.draft("prompt", "notes for the narrator voice")
    author.promote("all")

    lore = story / "data" / "lore" / "the_house.md"
    assert lore.is_file() and "## The Kettle" in lore.read_text(encoding="utf-8")
    prompt = story / "prompts" / "narrator_notes.md"
    assert prompt.is_file() and "second person" in prompt.read_text(encoding="utf-8")

    issues = validation.validate_story(registry.get(SLUG))
    assert not validation.errors_only(issues), [str(i) for i in issues]


def test_promote_refuses_a_kind_the_manifest_does_not_declare(story_root):
    """Drafting for an undeclared section is fine; promoting it is not."""
    destination = new_story.scaffold(SLUG, template="minimal", games_root=story_root / "games")
    _augment(destination)
    manifest_path = destination / "game.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    del data["paths"]["world_rumors"]
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    author = _author(FakeBackend(CANNED))
    author.draft("rumor", "what the street says")
    with pytest.raises(author_mod.AuthorError, match=r"paths\.world_rumors"):
        author.promote("rumor")


def test_promote_with_nothing_drafted_says_so(story):
    author = _author(FakeBackend(CANNED))
    with pytest.raises(author_mod.AuthorError, match="nothing to promote"):
        author.promote("all")


# ---------------------------------------------------------------------------
# 6. from-bible: plan, draft coherently, promote, end clean
# ---------------------------------------------------------------------------

BIBLE = """# The House and the Garden

A contemporary two-room story. A guest, a housemate named Marta, and the
walled garden nobody has weeded since spring. The stakes are entirely about
standing: who is welcome, who is tolerated, and what the kettle thinks.
"""

# Payloads for the bible run reference EACH OTHER across kinds: marta lives at
# the drafted garden, the encounter fires on the garden's drafted edge -- the
# coherence the sibling-ids context exists to make possible.
BIBLE_CANNED = dict(
    CANNED,
    author_plan={
        "locations": [{"id": "garden", "brief": "The walled garden behind the house."}],
        "npcs": [{"id": "marta", "brief": "The housemate who owns the garden fork."}],
        "items": [{"id": "pressed_flower", "brief": "A keepsake from the garden."}],
        "quests": [{"id": "tea_for_two", "brief": "Fetch and serve tea without incident."}],
        "decks": [{"id": "evening_visit", "brief": "The first evening as a guest."}],
        "encounters": [{"id": "loose_dog", "brief": "The neighbour's dog holds the path."}],
        "rumors": [{"id": "someone_new", "brief": "The street has noticed the guest."}],
    },
    author_npc={
        "npcs": [
            {
                "id": "marta",
                "name": "Marta",
                "role": "housemate",
                "home": "garden",
                "routine": [
                    {"hours": [8, 9, 10], "location": "garden", "activity": "weeding with prejudice"}
                ],
            }
        ]
    },
    author_encounter={
        "encounters": [
            dict(
                CANNED["author_encounter"]["encounters"][0],
                triggers={"edges": ["garden>front_room"]},
            )
        ],
        "band": "garden",
    },
)


def test_from_bible_plans_only_declared_sections(story_root):
    destination = new_story.scaffold(SLUG, template="minimal", games_root=story_root / "games")
    # NOT augmented: minimal declares locations, items, rules, prompts, saves.
    author = _author(FakeBackend(CANNED))
    schema = author.plan_schema()["schema"]
    assert set(schema["properties"]) == {"locations", "items"}
    assert destination.is_dir()


def test_a_full_bible_run_ends_with_a_story_that_validates_clean(story, tmp_path):
    bible_path = tmp_path / "bible.md"
    bible_path.write_text(BIBLE, encoding="utf-8")

    fake = FakeBackend(BIBLE_CANNED)
    author = _author(fake)
    written = author.from_bible(bible_path)

    # One draft per planned entry, in dependency order, all inside drafts/.
    kinds = [path.parent.name for path in written]
    assert kinds == ["location", "npc", "item", "quest", "deck", "encounter", "rumor"]
    drafts_root = story / "data" / "drafts"
    assert all(drafts_root in p.parents for p in written)

    # The plan went out once, then one draft call per piece.
    assert fake.calls[0] == ("author_plan", "author:plan")
    assert len(fake.calls) == 1 + len(written)

    # Nothing needed repairing (the canned set coheres), and promote lands it.
    report = author.repair()
    assert report.clean, report.by_draft
    author.promote("all")

    issues = validation.validate_story(registry.get(SLUG))
    assert not validation.errors_only(issues), [str(i) for i in issues]

    # The drafts tree is spent and gone; the content lives in the story now.
    assert not drafts_root.exists()
    merged = yaml.safe_load(
        (story / "data" / "world" / "npc_schedules.yaml").read_text(encoding="utf-8")
    )
    assert merged["npcs"]["marta"]["home"] == "garden"


# ---------------------------------------------------------------------------
# 7. the tool reads the registry without activating anything
# ---------------------------------------------------------------------------


def test_the_author_never_activates_a_game(story, monkeypatch):
    def _boom(*_a, **_kw):  # pragma: no cover - the point is it is never hit
        raise AssertionError("author.py must not activate a game")

    monkeypatch.setattr(registry, "activate", _boom)
    author = _author(FakeBackend(CANNED))
    author.draft("item", "anything")
    author.validate_drafts()
    author.promote("item")


def test_an_unknown_slug_is_refused_with_the_path_that_was_looked_for(story_root):
    with pytest.raises(author_mod.AuthorError, match="no-such-story"):
        author_mod.Author("no-such-story", backend=FakeBackend({}))
