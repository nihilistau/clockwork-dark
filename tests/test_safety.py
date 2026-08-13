"""
Tests for the safety layer (engine/safety/).

Organised by CLAIM rather than by module, because the claims are what the
package is for and several of them are properties of how two modules fit
together:

    the ceiling holds                     TestIntensityCeiling
    a motivation cannot raise it          TestTheRatchet
    a fade still applies outcomes         TestFadeKeepsOutcomes
    a block redirects in fiction          TestInWorldRedirect
    a limit can rename instead of block   TestCosmeticSubstitution
    the layer cannot take a turn down     TestNeverBlocksOnItsOwnFailure
    an unconfigured story is untouched    TestInertPolicy

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import pytest

from engine.game.state import GameState
from engine.safety.boundaries import BoundarySheet, TierMarkers, sheet_from_limits
from engine.safety.gate import SafetyGate
from engine.safety.governor import (
    META_FADE,
    META_REDIRECT_FALLBACK,
    META_SUBSTITUTIONS,
    META_VERDICT,
    SafetyCeiling,
    SafetyDirective,
    register_safety_interceptors,
)
from engine.safety.policy import (
    INERT_POLICY,
    Actor,
    SafetyPolicy,
    policy_for,
    reset_policies,
    resolve,
    set_policy,
)
from engine.safety.redirect import DEFAULT_REDIRECTS, Redirect, RedirectPack
from engine.safety.tiers import HIGHEST, LOWEST, IntensityTier, clamp
from engine.safety.verdict import Disposition, Verdict

EXPLICIT = IntensityTier.EXPLICIT
EXTREME = IntensityTier.EXTREME
SUGGESTIVE = IntensityTier.SUGGESTIVE


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_policies():
    """The per-session policy store is process-global; do not leak between tests."""
    reset_policies()
    yield
    reset_policies()


@pytest.fixture
def sheet() -> BoundarySheet:
    """A sheet with one of each kind of limit."""
    return sheet_from_limits(
        hard=[{"topic": "cruelty_to_animals", "nouns": ["kick the dog"]}],
        soft=[
            {"topic": "collars", "nouns": ["collar"], "substitute": "throat-garland"},
            {"topic": "drowning", "nouns": ["drowning"]},
        ],
    )


@pytest.fixture
def active_policy(sheet: BoundarySheet) -> SafetyPolicy:
    """A live policy: explicit ceiling, dial at suggestive, limits configured."""
    return SafetyPolicy(
        ceiling=EXTREME, intensity=SUGGESTIVE, sheet=sheet, source="test"
    )


class _Choice:
    def __init__(self, text: str = "", whisper: str = "") -> None:
        self.text = text
        self.whisper = whisper


class _Plan:
    """Duck-typed stand-in for AgentPlan. See SafetyGate.review_plan."""

    def __init__(self, beat: str = "", effects=None, choices=(), private: str = ""):
        self.beat = beat
        self.effects = list(effects or [])
        self.choices = list(choices)
        self.private = private
        self.extras: dict = {}


class _Negotiated:
    def __init__(self, accepted=None) -> None:
        self.accepted = dict(accepted or {})
        self.blocked = False
        self.block_reason = ""


class _Ctx:
    """Duck-typed stand-in for TurnContext, carrying the fields this layer uses."""

    def __init__(self, state=None, plans=None, narration="", negotiated=None):
        self.state = state
        self.plans = dict(plans or {})
        self.narration = narration
        self.negotiated = negotiated
        self.metadata: dict = {}
        self.intensity = ""
        self.safety_block = ""
        self.veto = ""


# ---------------------------------------------------------------------------
# the ladder
# ---------------------------------------------------------------------------


class TestIntensityTier:
    def test_ladder_is_ordered_by_rank_not_alphabet(self):
        # "extreme" < "suggestive" alphabetically. The whole reason this is a
        # type and not a string.
        assert SUGGESTIVE < EXPLICIT < EXTREME
        assert EXTREME > SUGGESTIVE
        assert "extreme" < "suggestive"

    def test_default_is_the_lowest(self):
        assert LOWEST is SUGGESTIVE
        assert HIGHEST is EXTREME

    @pytest.mark.parametrize(
        "raw", ["EXPLICIT", " explicit ", "Explicit", EXPLICIT]
    )
    def test_parse_is_tolerant(self, raw):
        assert IntensityTier.parse(raw) is EXPLICIT

    @pytest.mark.parametrize("raw", ["", None, "sugestive", 7, [], {"a": 1}])
    def test_junk_lands_on_the_lowest_tier_and_never_raises(self, raw):
        assert IntensityTier.parse(raw) is SUGGESTIVE

    def test_clamp_takes_the_lower(self):
        assert clamp(EXTREME, EXPLICIT) is EXPLICIT
        assert clamp(SUGGESTIVE, EXTREME) is SUGGESTIVE


# ---------------------------------------------------------------------------
# claim: a character's motivation can never raise the ceiling
# ---------------------------------------------------------------------------


class TestTheRatchet:
    def test_an_agent_may_lower_the_dial(self, active_policy):
        raised = active_policy.with_intensity(EXTREME, actor=Actor.PLAYER)
        lowered = raised.with_intensity(SUGGESTIVE, actor=Actor.AGENT)
        assert lowered.intensity is SUGGESTIVE

    def test_an_agent_may_not_raise_the_dial(self, active_policy):
        assert active_policy.intensity is SUGGESTIVE
        after = active_policy.with_intensity(EXTREME, actor=Actor.AGENT)
        assert after.intensity is SUGGESTIVE

    def test_the_default_actor_is_the_restrictive_one(self, active_policy):
        # A caller that forgets the argument must get the safe behaviour.
        assert active_policy.with_intensity(EXTREME).intensity is SUGGESTIVE

    def test_a_story_may_not_move_the_dial_at_runtime(self, active_policy):
        after = active_policy.with_intensity(EXTREME, actor=Actor.STORY)
        assert after is active_policy

    def test_the_player_is_clamped_to_the_story_ceiling(self, sheet):
        policy = SafetyPolicy(ceiling=EXPLICIT, intensity=SUGGESTIVE, sheet=sheet)
        assert policy.with_intensity(EXTREME, actor=Actor.PLAYER).intensity is EXPLICIT

    def test_out_of_range_intensity_cannot_be_constructed(self):
        policy = SafetyPolicy(ceiling=SUGGESTIVE, intensity=EXTREME)
        assert policy.intensity is SUGGESTIVE

    def test_policy_is_frozen(self, active_policy):
        with pytest.raises(Exception):
            active_policy.intensity = EXTREME  # type: ignore[misc]

    def test_limits_only_ever_accumulate(self, active_policy):
        before = len(active_policy.sheet.hard_nos)
        after = active_policy.with_limits(
            sheet_from_limits(hard=[{"topic": "extra", "nouns": ["extra"]}])
        )
        assert len(after.sheet.hard_nos) == before + 1
        # And the original is untouched -- nothing mutates a policy in place.
        assert len(active_policy.sheet.hard_nos) == before

    def test_a_green_light_cannot_lift_a_hard_no(self):
        merged = sheet_from_limits(
            hard=[{"topic": "x", "nouns": ["x"]}], green=["x"]
        )
        assert merged.green_lights == ()
        assert merged.hard_hits("x") != ()

    def test_a_story_green_light_loses_to_a_player_limit(self):
        story = sheet_from_limits(green=["collars"])
        player = sheet_from_limits(soft=[{"topic": "collars", "nouns": ["collar"]}])
        merged = story.merged_with(player)
        assert merged.green_lights == ()
        assert merged.soft_hits("a collar") != ()

    def test_merging_two_sheets_never_narrows_a_limit(self):
        left = sheet_from_limits(hard=[{"topic": "t", "nouns": ["alpha"]}])
        right = sheet_from_limits(hard=[{"topic": "t", "nouns": ["beta"]}])
        merged = left.merged_with(right)
        assert merged.hard_hits("alpha") and merged.hard_hits("beta")


# ---------------------------------------------------------------------------
# claim: content above the session's setting collapses to summary
# ---------------------------------------------------------------------------


class TestIntensityCeiling:
    def test_content_at_the_dial_is_allowed(self, active_policy):
        gate = SafetyGate(active_policy.with_intensity(EXPLICIT, actor=Actor.PLAYER))
        assert gate.review_beat("a quiet scene", declared=EXPLICIT).allowed

    def test_content_above_the_dial_fades(self, active_policy):
        gate = SafetyGate(active_policy)  # dial at suggestive
        verdict = gate.review_beat("a scene", declared=EXTREME)
        assert verdict.disposition is Disposition.FADE
        assert verdict.summary_hint

    def test_the_fade_reason_names_both_tiers(self, active_policy):
        verdict = SafetyGate(active_policy).review_beat("x", declared=EXPLICIT)
        assert verdict.reasons == ("ceiling:explicit>suggestive",)

    def test_markers_raise_the_estimate_when_the_caller_declares_nothing(self):
        markers = TierMarkers.from_mapping({"explicit": ["telltale"]})
        gate = SafetyGate(
            SafetyPolicy(ceiling=EXTREME, intensity=SUGGESTIVE, markers=markers)
        )
        assert gate.review_beat("nothing here").allowed
        assert (
            gate.review_beat("a telltale phrase").disposition is Disposition.FADE
        )

    def test_markers_can_never_lower_a_declared_tier(self):
        markers = TierMarkers.from_mapping({"explicit": ["telltale"]})
        # Caller declares EXTREME; the text carries only an EXPLICIT marker.
        assert markers.tier_of("telltale", floor=EXTREME) is EXTREME

    def test_markers_naming_an_unknown_tier_are_dropped(self):
        markers = TierMarkers.from_mapping({"filthy": ["word"]})
        assert markers.empty
        assert markers.tier_of("word") is SUGGESTIVE

    def test_shipped_markers_are_empty(self):
        # The mechanism ships; the vocabulary is the story owner's to write.
        assert resolve().markers.empty


# ---------------------------------------------------------------------------
# claim: a faded scene still applies its mechanical outcomes
# ---------------------------------------------------------------------------


class TestFadeKeepsOutcomes:
    def test_a_fade_verdict_says_outcomes_apply(self, active_policy):
        verdict = SafetyGate(active_policy).review_beat("x", declared=EXTREME)
        assert verdict.disposition is Disposition.FADE
        assert verdict.outcomes_apply is True

    def test_a_redirect_verdict_says_they_do_not(self, active_policy):
        verdict = SafetyGate(active_policy).review_input("kick the dog")
        assert verdict.disposition is Disposition.REDIRECT
        assert verdict.outcomes_apply is False

    def test_a_verdict_cannot_carry_effects_at_all(self):
        # The structural half of the claim: there is nothing here to apply, so
        # nothing here can fail to be applied.
        fields = set(Verdict().__dataclass_fields__)
        assert not fields & {"effects", "deltas", "meters", "state", "outcomes"}

    def test_the_fade_path_does_not_touch_proposed_effects(self, active_policy):
        set_policy(active_policy)
        plan = _Plan(beat="a scene", effects=[{"type": "stat", "stat": "favor"}])
        ctx = _Ctx(plans={"gm": plan})
        plan.extras["intensity"] = "extreme"

        SafetyCeiling().run_post(ctx)

        assert ctx.metadata[META_VERDICT]["disposition"] == "fade"
        assert ctx.metadata[META_VERDICT]["outcomes_apply"] is True
        assert plan.effects == [{"type": "stat", "stat": "favor"}]
        assert ctx.safety_block == ""
        assert ctx.veto == ""

    def test_the_fade_metadata_carries_a_summary_instruction(self, active_policy):
        set_policy(active_policy)
        plan = _Plan(beat="a scene")
        plan.extras["intensity"] = "extreme"
        ctx = _Ctx(plans={"gm": plan})
        SafetyCeiling().run_post(ctx)
        assert ctx.metadata[META_FADE]["summary_hint"]

    def test_fade_card_is_built_only_for_a_fade(self, active_policy):
        gate = SafetyGate(active_policy)
        faded = gate.review_beat("x", declared=EXTREME)
        allowed = gate.review_beat("a quiet scene")
        assert gate.fade_card(faded, summary="They talked.") is not None
        assert gate.fade_card(allowed) is None

    def test_fade_card_carries_the_consequences(self, active_policy):
        gate = SafetyGate(active_policy)
        card = gate.fade_card(
            gate.review_beat("x", declared=EXTREME),
            summary="The hour passed.",
            outcomes=("She keeps the gift.", "An hour passes."),
        )
        assert card is not None
        assert card.outcomes == ("She keeps the gift.", "An hour passes.")
        assert "gift" in card.to_dict()["outcomes"][0]


# ---------------------------------------------------------------------------
# claim: a block comes back as an in-world redirect, not a refusal
# ---------------------------------------------------------------------------


class TestInWorldRedirect:
    def test_a_hard_no_produces_a_beat_and_a_fallback_line(self, active_policy):
        verdict = SafetyGate(active_policy).review_input("I kick the dog")
        assert verdict.disposition is Disposition.REDIRECT
        assert verdict.redirect
        assert verdict.fallback

    def test_no_shipped_redirect_reads_as_customer_service(self):
        # SOPHIA-VOICE-BIBLE.md:93-98 -- the off-voice list.
        forbidden = (
            "as an ai",
            "i can't",
            "i cannot",
            "sorry",
            "i'm unable",
            "content policy",
            "guidelines",
            "inappropriate",
            "i'd love to help",
        )
        for redirect in DEFAULT_REDIRECTS:
            blob = f"{redirect.beat} {redirect.line}".lower()
            for phrase in forbidden:
                assert phrase not in blob, (redirect.id, phrase)

    def test_a_verdict_never_hands_the_player_their_own_limit_back(
        self, active_policy
    ):
        verdict = SafetyGate(active_policy).review_input("I kick the dog")
        # The topic is in `reasons`, which goes to the log. Never in the prose.
        assert "cruelty_to_animals" in verdict.reasons[0]
        assert "cruelty" not in verdict.redirect.lower()
        assert "cruelty" not in verdict.fallback.lower()

    def test_the_redirect_draw_is_seeded_and_replays(self, active_policy):
        set_policy(active_policy)
        first = GameState(rng_seed=1234)
        second = GameState(rng_seed=1234)
        a = SafetyGate(active_policy, state=first).review_input("kick the dog")
        b = SafetyGate(active_policy, state=second).review_input("kick the dog")
        assert a.redirect == b.redirect

    def test_the_redirect_draw_uses_its_own_stream(self, active_policy):
        from engine.safety.redirect import SAFETY_REDIRECT

        state = GameState(rng_seed=7)
        SafetyGate(active_policy, state=state).review_input("kick the dog")
        assert state.rng_counters.get(SAFETY_REDIRECT) == 1
        assert set(state.rng_counters) == {SAFETY_REDIRECT}

    def test_tags_steer_the_choice_but_a_miss_still_answers(self):
        pack = RedirectPack(
            [
                Redirect(id="a", beat="a", line="a", tags=("duty",)),
                Redirect(id="b", beat="b", line="b", tags=("time",)),
            ]
        )
        assert pack.pick(tags=("duty",)).id == "a"
        assert pack.pick(tags=("nothing-matches",)).id in {"a", "b"}

    def test_a_story_pack_replaces_the_shipped_one(self):
        pack = RedirectPack.from_block(
            [{"id": "moth", "beat": "a moth", "line": "A moth."}]
        )
        assert len(pack) == 1
        assert pack.pick().id == "moth"

    def test_an_unusable_pack_falls_back_to_the_shipped_one(self):
        assert len(RedirectPack.from_block("not a list")) == len(DEFAULT_REDIRECTS)
        assert len(RedirectPack.from_block([None, 7])) == len(DEFAULT_REDIRECTS)

    def test_the_commit_hook_marks_the_turn_and_drops_the_effects(
        self, active_policy
    ):
        set_policy(active_policy)
        plan = _Plan(beat="then I kick the dog", effects=[{"type": "stat"}])
        negotiated = _Negotiated(accepted={"gm": plan})
        ctx = _Ctx(plans={"gm": plan}, negotiated=negotiated)

        SafetyCeiling().run_post(ctx)

        assert ctx.safety_block
        assert ctx.metadata[META_REDIRECT_FALLBACK]
        assert negotiated.blocked is True
        assert negotiated.block_reason == ctx.safety_block
        # The thing did not happen, so its effects do not land.
        assert plan.effects == []
        # But the turn is not rolled back -- the hour still passed.
        assert ctx.veto == ""

    def test_a_private_motive_is_never_read(self, active_policy):
        # The knowledge partition: a motive is not content.
        plan = _Plan(beat="a quiet word", private="she wants to kick the dog")
        assert SafetyGate(active_policy).review_plan(plan).allowed


# ---------------------------------------------------------------------------
# claim: a limit can rename instead of block
# ---------------------------------------------------------------------------


class TestCosmeticSubstitution:
    def test_a_soft_limit_with_a_substitute_renames(self, active_policy):
        gate = SafetyGate(active_policy)
        verdict = gate.review_beat("she offers a collar")
        assert verdict.disposition is Disposition.SUBSTITUTE
        assert verdict.substitutions == {"collar": "throat-garland"}

    def test_the_day_one_example(self, active_policy):
        # DAY-01-GUEST.md:152 -- "same mechanics, cosmetic rename from
        # boundaries".
        gate = SafetyGate(active_policy)
        assert gate.rename("Collar of Soft Thorns") == "Throat-garland of Soft Thorns"

    def test_case_shape_is_preserved(self, active_policy):
        gate = SafetyGate(active_policy)
        assert gate.rename("COLLAR") == "THROAT-GARLAND"
        assert gate.rename("a collar") == "a throat-garland"

    def test_rename_matches_whole_words_only(self, active_policy):
        gate = SafetyGate(active_policy)
        assert gate.rename("collarbone") == "collarbone"

    def test_a_substitute_on_a_hard_no_is_refused(self):
        # Renaming a hard no generates it under another word.
        built = sheet_from_limits(
            hard=[{"topic": "t", "nouns": ["word"], "substitute": "euphemism"}]
        )
        assert built.hard_nos[0].substitute == ""
        assert built.rename("word") == "word"

    def test_a_partial_rename_fades_instead(self, active_policy):
        # "drowning" is a soft no with no substitute. One noun renameable and
        # one not must not leave the un-renameable one on the page.
        verdict = SafetyGate(active_policy).review_beat("a collar, and drowning")
        assert verdict.disposition is Disposition.FADE

    def test_a_green_light_lifts_a_soft_no(self):
        sheet = sheet_from_limits(
            soft=[{"topic": "collars", "nouns": ["collar"], "substitute": "x"}],
            green=["collars"],
        )
        assert sheet.soft_hits("a collar") == ()
        assert sheet.rename("a collar") == "a collar"

    def test_the_governor_records_the_map_without_rewriting_anything(
        self, active_policy
    ):
        # Applying the map is the renderer's job, through SafetyGate.rename, on
        # display strings only -- so an id can never be renamed.
        set_policy(active_policy)
        plan = _Plan(beat="she offers a collar", effects=[{"type": "item"}])
        ctx = _Ctx(plans={"gm": plan})

        SafetyCeiling().run_post(ctx)

        assert ctx.metadata[META_SUBSTITUTIONS] == {"collar": "throat-garland"}
        assert plan.beat == "she offers a collar"
        assert plan.effects == [{"type": "item"}]
        assert ctx.safety_block == ""

    def test_rename_cannot_be_handed_an_id(self):
        # Structural: the renaming function's only parameter is display text.
        import inspect

        params = list(
            inspect.signature(BoundarySheet.rename).parameters
        )
        assert params == ["self", "text"]


# ---------------------------------------------------------------------------
# claim: the layer cannot take a turn down
# ---------------------------------------------------------------------------


class _Exploding(BoundarySheet):
    """A sheet whose matcher raises. Stands in for any bug inside the package."""

    def hard_hits(self, text: str):  # type: ignore[override]
        raise RuntimeError("boom")


class TestNeverBlocksOnItsOwnFailure:
    @pytest.fixture
    def broken(self, active_policy) -> SafetyGate:
        return SafetyGate(
            SafetyPolicy(
                ceiling=EXTREME,
                intensity=SUGGESTIVE,
                sheet=_Exploding(hard_nos=active_policy.sheet.hard_nos),
                source="broken",
            )
        )

    def test_input_review_degrades_to_allow(self, broken):
        assert broken.review_input("anything").allowed

    def test_beat_review_degrades_to_fade_not_to_a_crash(self, broken):
        verdict = broken.review_beat("anything")
        assert verdict.disposition is Disposition.FADE
        assert verdict.reasons == ("internal:review_beat",)
        # And the turn still moves: a fade keeps its outcomes.
        assert verdict.outcomes_apply is True

    def test_narration_review_degrades_to_fade(self, broken):
        assert broken.review_narration("anything").disposition is Disposition.FADE

    def test_plan_review_degrades_to_fade(self, broken):
        assert broken.review_plan(_Plan(beat="x")).disposition is Disposition.FADE

    def test_rename_returns_the_text_unchanged(self, active_policy):
        class _BadRename(BoundarySheet):
            def rename(self, text: str) -> str:  # type: ignore[override]
                raise RuntimeError("boom")

        gate = SafetyGate(
            SafetyPolicy(ceiling=EXTREME, sheet=_BadRename(green_lights=("x",)))
        )
        assert gate.rename("Collar of Soft Thorns") == "Collar of Soft Thorns"

    def test_the_governor_survives_a_context_it_does_not_recognise(
        self, active_policy
    ):
        set_policy(active_policy)

        class _Bare:
            pass

        # No state, no plans, no metadata. Must not raise.
        SafetyCeiling().run_post(_Bare())

    def test_the_directive_survives_a_state_it_does_not_recognise(self):
        assert SafetyDirective().run_pre(object(), "prompt") == "prompt"

    def test_an_unparseable_config_layer_lands_on_the_defaults(self):
        assert resolve(manifest_block={"boundaries": "not a mapping"}).sheet.empty

    def test_junk_limits_are_dropped_not_raised(self):
        built = sheet_from_limits(hard=[None, 7, "", {"nouns": ["x"]}, "real"])
        assert [l.topic for l in built.hard_nos] == ["real"]


# ---------------------------------------------------------------------------
# claim: an unconfigured story is untouched
# ---------------------------------------------------------------------------


class TestInertPolicy:
    def test_the_default_policy_is_inert(self):
        assert INERT_POLICY.inert
        assert resolve().inert

    def test_an_inert_gate_allows_everything(self):
        gate = SafetyGate(INERT_POLICY)
        assert gate.inert
        for verdict in (
            gate.review_input("anything at all"),
            gate.review_beat("anything at all", declared=EXTREME),
            gate.review_narration("anything at all"),
            gate.review_plan(_Plan(beat="anything at all")),
        ):
            assert verdict.allowed

    def test_an_inert_gate_contributes_no_prompt_text(self):
        # R-01: the prompt budget is already over. A layer nobody configured
        # must not spend a token of it.
        assert SafetyGate(INERT_POLICY).directive_text() == ""
        assert SafetyDirective().run_pre(GameState(), "prompt") == "prompt"

    def test_an_inert_gate_draws_no_rng(self):
        state = GameState(rng_seed=99)
        SafetyGate(INERT_POLICY, state=state).review_input("kick the dog")
        assert state.rng_counters == {}

    def test_an_inert_governor_changes_nothing_but_reports_the_tier(self):
        plan = _Plan(beat="anything", effects=[{"type": "stat"}])
        ctx = _Ctx(state=GameState(), plans={"gm": plan}, narration="anything")
        SafetyCeiling().run_post(ctx)
        assert ctx.intensity == "suggestive"
        assert ctx.safety_block == ""
        assert ctx.metadata == {}
        assert plan.effects == [{"type": "stat"}]

    def test_adding_any_limit_makes_it_live(self):
        policy = INERT_POLICY.with_limits(
            sheet_from_limits(hard=[{"topic": "t", "nouns": ["x"]}])
        )
        assert not policy.inert


# ---------------------------------------------------------------------------
# resolution and the session store
# ---------------------------------------------------------------------------


class TestResolution:
    def test_a_story_raises_its_own_ceiling(self):
        policy = resolve(
            manifest_block={"intensity": {"max": "extreme", "default": "explicit"}}
        )
        assert policy.ceiling is EXTREME
        assert policy.intensity is EXPLICIT
        assert not policy.inert

    def test_a_story_default_above_its_own_max_is_clamped(self):
        policy = resolve(
            manifest_block={"intensity": {"max": "explicit", "default": "extreme"}}
        )
        assert policy.intensity is EXPLICIT

    def test_a_player_may_not_exceed_the_story_ceiling(self):
        policy = resolve(
            manifest_block={"intensity": {"max": "explicit"}},
            player={"intensity": "extreme"},
        )
        assert policy.intensity is EXPLICIT

    def test_player_limits_merge_on_top_of_story_limits(self):
        policy = resolve(
            manifest_block={
                "intensity": {"max": "extreme"},
                "boundaries": {"hard_nos": [{"topic": "story", "nouns": ["s"]}]},
            },
            player={"boundaries": {"hard_nos": [{"topic": "player", "nouns": ["p"]}]}},
        )
        topics = {l.topic for l in policy.sheet.hard_nos}
        assert topics == {"story", "player"}

    def test_the_policy_store_is_per_session(self, active_policy):
        set_policy(active_policy, session_id="a")
        assert policy_for("a") is active_policy
        assert policy_for("b").inert

    def test_reset_clears_the_store(self, active_policy):
        set_policy(active_policy, session_id="a")
        reset_policies()
        assert policy_for("a").inert

    def test_the_boundary_sheet_is_not_game_state(self):
        # It must not be reachable from anything that can propose a delta.
        state = GameState()
        assert not hasattr(state, "boundaries")
        assert not hasattr(state, "hard_nos")
        assert "boundaries" not in state.to_client_dict()
        assert "boundaries" not in state.to_save_dict()


# ---------------------------------------------------------------------------
# the directive block
# ---------------------------------------------------------------------------


class TestDirectiveBlock:
    def test_it_names_the_tier_and_the_topics(self, active_policy):
        text = SafetyGate(active_policy).directive_text()
        assert "suggestive" in text
        assert "cruelty_to_animals" in text
        assert "collars" in text

    def test_it_never_lists_the_surface_forms(self, active_policy):
        # Enumerating the exact words a player does not want to read puts them
        # in the context window, where the sampler can reach them.
        text = SafetyGate(active_policy).directive_text()
        assert "kick the dog" not in text
        assert "collar," not in text.replace("collars,", "")

    def test_it_asks_for_an_in_fiction_redirect(self, active_policy):
        text = SafetyGate(active_policy).directive_text().lower()
        assert "in fiction" in text
        assert "never announce a refusal" in text

    def test_a_green_lit_topic_is_not_listed(self):
        policy = SafetyPolicy(
            ceiling=EXTREME,
            sheet=sheet_from_limits(
                soft=[{"topic": "collars", "nouns": ["collar"]}],
                green=["collars"],
            ),
        )
        # One author saying "usually not, but yes for me". Telling the model to
        # handle it at a distance would be honouring the caution the player
        # just lifted.
        assert "collars" not in SafetyGate(policy).directive_text()

    def test_the_hook_prepends_nothing_when_the_prompt_is_empty(
        self, active_policy
    ):
        state = GameState()
        set_policy(active_policy, session_id=state.session_id)
        out = SafetyDirective().run_pre(state, "")
        assert out.startswith("CONTENT LIMITS")

    def test_the_hook_reads_the_policy_for_this_session(self, active_policy):
        # Two sessions in one process must not share a boundary sheet.
        mine, theirs = GameState(), GameState()
        set_policy(active_policy, session_id=mine.session_id)
        assert SafetyDirective().run_pre(mine, "p") != "p"
        assert SafetyDirective().run_pre(theirs, "p") == "p"


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registering_is_idempotent_and_reports_success(self):
        from engine.agents.governance import (
            PHASE_COMMIT,
            PHASE_DIRECTIVE,
            _REGISTRY,
        )

        assert register_safety_interceptors() is True
        assert register_safety_interceptors() is True
        assert _REGISTRY[PHASE_DIRECTIVE]["SafetyDirective"] is SafetyDirective
        assert _REGISTRY[PHASE_COMMIT]["SafetyCeiling"] is SafetyCeiling

    def test_the_hooks_carry_the_attributes_the_pipeline_sorts_on(self):
        for cls in (SafetyDirective, SafetyCeiling):
            assert isinstance(cls.priority, int)
            assert cls.name == cls.__name__
            # The pipeline builds hooks with no arguments.
            assert cls() is not None

    def test_safety_runs_first_in_its_chain(self):
        from engine.agents.governance import EvilPhaseTone, RulesGovernor

        assert SafetyDirective.priority < EvilPhaseTone.priority
        assert SafetyCeiling.priority < RulesGovernor.priority


class TestAgainstTheRealPipeline:
    """
    The hooks driven by the actual GovernancePipeline and the actual
    TurnContext, not by the stand-ins above.

    The stand-ins keep this package from depending on engine.agents; these
    prove the duck typing is the right shape. Chains are passed explicitly to
    exercise one hook in isolation; the CONFIGURED chain -- ``governance.commit``
    read by ``from_config`` and run by ``pipeline._commit`` -- is proven in
    tests/test_governance_commit.py.
    """

    def test_the_directive_chain_carries_the_block(self, active_policy):
        from engine.agents.governance import PHASE_DIRECTIVE, GovernancePipeline

        state = GameState()
        set_policy(active_policy, session_id=state.session_id)
        pipeline = GovernancePipeline({PHASE_DIRECTIVE: [SafetyDirective()]})
        assert "CONTENT LIMITS" in pipeline.build_directives(state)

    def test_the_commit_chain_fades_without_touching_effects(self, active_policy):
        from engine.agents.governance import (
            PHASE_COMMIT,
            GovernancePipeline,
            TurnContext,
        )
        from engine.agents.plan import AgentPlan, ProposedEffect

        state = GameState()
        set_policy(active_policy, session_id=state.session_id)
        plan = AgentPlan(
            agent="storyteller",
            beat="a scene",
            effects=[ProposedEffect(kind="stat", payload={"stat": "gold"})],
        )
        plan.extras["intensity"] = "extreme"
        ctx = TurnContext(state=state, plans={"storyteller": plan})

        GovernancePipeline({PHASE_COMMIT: [SafetyCeiling()]}).run_commit(ctx)

        assert ctx.intensity == "suggestive"
        assert ctx.metadata[META_VERDICT]["disposition"] == "fade"
        assert len(plan.effects) == 1
        assert ctx.veto == ""

    def test_the_commit_chain_redirects_and_drops_effects(self, active_policy):
        from engine.agents.governance import (
            PHASE_COMMIT,
            GovernancePipeline,
            TurnContext,
        )
        from engine.agents.negotiate import NegotiatedTurn
        from engine.agents.plan import AgentPlan, ProposedEffect

        state = GameState()
        set_policy(active_policy, session_id=state.session_id)
        plan = AgentPlan(
            agent="storyteller",
            beat="he moves to kick the dog",
            effects=[ProposedEffect(kind="stat", payload={"stat": "gold"})],
        )
        ctx = TurnContext(
            state=state,
            plans={"storyteller": plan},
            negotiated=NegotiatedTurn(lead="storyteller", accepted={"storyteller": plan}),
        )

        GovernancePipeline({PHASE_COMMIT: [SafetyCeiling()]}).run_commit(ctx)

        assert ctx.safety_block
        assert ctx.negotiated.blocked is True
        assert plan.effects == []
        # A limit costs the player the scene, not the hour.
        assert ctx.veto == ""

    def test_a_broken_hook_cannot_kill_the_chain(self, active_policy):
        from engine.agents.governance import (
            PHASE_COMMIT,
            GovernancePipeline,
            TurnContext,
        )

        class _Exploder:
            priority = 5
            name = "Exploder"

            def run_post(self, ctx):
                raise RuntimeError("boom")

        state = GameState()
        set_policy(active_policy, session_id=state.session_id)
        ctx = TurnContext(state=state, narration="a quiet evening")
        GovernancePipeline(
            {PHASE_COMMIT: [_Exploder(), SafetyCeiling()]}
        ).run_commit(ctx)
        assert ctx.intensity == "suggestive"
