"""
Safety Policy
=============

The resolved settings one session plays under, and the ratchet that stops a
character's motivation reaching them.

THREE LAYERS, STACKED, LOWEST AUTHORITY FIRST:

    config/default.yaml   safety.*        the engine's shipped defaults
    games/<slug>/game.yaml  safety:       what THIS story is written for
    the player's own sheet                what THIS player wants

The player layer is last because it is the only one a human chose at runtime.
The story layer is above the engine's because a story knows what it contains.
Neither of the first two can raise the player above where the player put
themselves -- ``resolve`` clamps, it does not set.

WHY ``Actor`` EXISTS. Requirement: a character's motivation must never raise
the ceiling, enforced structurally rather than by prompt text. So the only
mutator on this frozen object takes an actor, and the actor decides the
direction of travel:

    Actor.PLAYER   may set the dial anywhere up to the story's ceiling
    Actor.STORY    may set the ceiling at LOAD time, through resolve() only
    Actor.AGENT    may only ever LOWER the dial

``with_intensity(tier, actor=Actor.AGENT)`` returns ``min(tier, current)``.
There is no argument, no flag and no second function that changes that. An
agent that decides Sophia wants the scene to go further gets a policy identical
to the one it had. The want has nowhere to land.

There is deliberately no global disable switch. "Off" is a data state, not a
flag: a policy with no limits and a suggestive ceiling is ``inert``, and an
inert policy short-circuits to ALLOW everywhere. That is how the two shipped
stories -- which configure nothing -- behave exactly as they did before this
package existed, without an escape hatch that a bad config could trip into
turning hard limits off.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Optional

from engine.config import get_config
from engine.safety.boundaries import (
    EMPTY_SHEET,
    NO_MARKERS,
    BoundarySheet,
    TierMarkers,
)
from engine.safety.tiers import LOWEST, IntensityTier, clamp

logger = logging.getLogger(__name__)


class Actor(Enum):
    """
    Who is asking for a change, and therefore what they may ask for.

    This is not a permission list bolted onto a setter. It is the setter's only
    parameter that matters -- see the module docstring.
    """

    #: The human, through a settings dial. May raise, up to the story ceiling.
    PLAYER = "player"
    #: The story, through its manifest, at load time. Sets the ceiling.
    STORY = "story"
    #: Anything model-originated: an agent plan, a parsed tool call, narration
    #: metadata. May lower. May never raise.
    AGENT = "agent"


@dataclass(frozen=True)
class SafetyPolicy:
    """
    One session's resolved safety settings.

    Attributes:
        ceiling: The highest tier this STORY is written for. A story that says
            nothing gets the engine default, which is the lowest tier.
        intensity: Where the player's dial sits. Never above ``ceiling`` --
            construction clamps it, so an out-of-range value cannot exist.
        sheet: The merged boundary sheet.
        fade_available: Whether Fade is offered as a player control. Content
            above the ceiling collapses to summary regardless; this is about
            the on-demand button, not the automatic behaviour.
        aftercare: Whether an aftercare beat is requested after an intense
            scene.
        source: Where this policy came from, for the log line.
    """

    ceiling: IntensityTier = LOWEST
    intensity: IntensityTier = LOWEST
    sheet: BoundarySheet = EMPTY_SHEET
    markers: TierMarkers = NO_MARKERS
    fade_available: bool = True
    aftercare: bool = False
    source: str = "default"

    def __post_init__(self) -> None:
        # Clamped at construction rather than checked at read time, for the
        # same reason BoundarySheet filters green lights at construction: an
        # invariant that holds for every instance that exists is one no reader
        # has to remember to check.
        if self.intensity > self.ceiling:
            logger.info(
                "[safety] Intensity clamped to the story ceiling "
                "(operation=SafetyPolicy, wanted=%s, ceiling=%s, source=%s)",
                self.intensity.value,
                self.ceiling.value,
                self.source,
            )
            object.__setattr__(self, "intensity", self.ceiling)

    # -- queries ----------------------------------------------------------

    @property
    def inert(self) -> bool:
        """
        True when this policy has nothing whatsoever to enforce.

        The two shipped stories are inert, and ``SafetyGate`` short-circuits on
        this so their turns take exactly the code path they took before the
        package existed -- no matching, no directive text, no prompt budget.
        """
        return (
            self.sheet.empty
            and self.markers.empty
            and self.ceiling is LOWEST
            and self.intensity is LOWEST
        )

    def allows(self, tier: IntensityTier) -> bool:
        """True when content at ``tier`` may be generated in full."""
        return tier <= self.intensity

    # -- the ratchet ------------------------------------------------------

    def with_intensity(
        self,
        tier: Any,
        *,
        actor: Actor = Actor.AGENT,
    ) -> "SafetyPolicy":
        """
        Return a policy at a new intensity, subject to who is asking.

        Args:
            tier: The wanted tier, in any parseable form.
            actor: Who wants it. Defaults to AGENT -- the restrictive case --
                so a caller that forgets the argument gets the safe behaviour
                rather than the permissive one.

        Returns:
            A new policy. For AGENT the result is never above the current
            intensity; for STORY the request is refused outright, because the
            story's authority is exercised through ``resolve`` at load time and
            a runtime story-level raise would be a story rewriting a player's
            dial mid-scene.
        """
        wanted = IntensityTier.parse(tier, default=self.intensity, source="with_intensity")

        if actor is Actor.AGENT:
            # The ratchet. min(), always, in one place.
            settled = wanted if wanted <= self.intensity else self.intensity
            if settled is not wanted:
                logger.info(
                    "[safety] Agent asked to raise intensity; refused "
                    "(operation=with_intensity, wanted=%s, in_force=%s)",
                    wanted.value,
                    self.intensity.value,
                )
        elif actor is Actor.STORY:
            logger.warning(
                "[safety] A story may not move the dial at runtime, ignoring "
                "(operation=with_intensity, wanted=%s)",
                wanted.value,
            )
            return self
        else:
            settled = clamp(wanted, self.ceiling)

        if settled is self.intensity:
            return self
        return replace(self, intensity=settled)

    def with_limits(self, sheet: Optional[BoundarySheet]) -> "SafetyPolicy":
        """
        Return a policy with more limits.

        Union only -- ``BoundarySheet.merged_with`` has no subtract, so this
        method could not remove a limit even if a caller wanted it to.
        """
        if sheet is None or sheet.empty:
            return self
        return replace(self, sheet=self.sheet.merged_with(sheet))


#: What a session gets when nothing anywhere is configured.
INERT_POLICY = SafetyPolicy()


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def _block_from_manifest() -> dict[str, Any]:
    """
    The active game's ``safety:`` block, or {}.

    Read from ``GameManifest.extras`` rather than from ``settings:``. The
    manifest keeps every unknown top-level key verbatim (the second shipped
    game already uses this for ``phase_names:``), so a story declares its
    content rating without needing a new allowlist entry -- and without the
    block passing through ``config_overlay()``, which would make a story's
    rating a config value a stale ``config/local.yaml`` could move.

    Uses ``registry.peek()``, never ``registry.active()``: resolving a policy
    must not be the thing that activates a game.
    """
    try:
        from engine.games import registry

        manifest = registry.peek()
    except Exception as exc:  # noqa: BLE001 -- never let config reading kill a turn
        logger.warning(
            "[safety] Game registry unreadable, using engine defaults "
            "(operation=_block_from_manifest): %s",
            exc,
        )
        return {}
    if manifest is None:
        return {}
    block = manifest.extras.get("safety")
    return block if isinstance(block, dict) else {}


def resolve(
    *,
    player: Optional[dict[str, Any]] = None,
    manifest_block: Optional[dict[str, Any]] = None,
) -> SafetyPolicy:
    """
    Build the policy in force from config, the active story and the player.

    Args:
        player: The player's own settings, as a mapping. Recognised keys:
            ``intensity``, ``boundaries`` (a mapping with hard_nos/soft_nos/
            green_lights), ``fade_available``, ``aftercare``.
        manifest_block: Override for the story block. Tests pass this;
            production reads the active manifest.

    Returns:
        A policy. Never raises -- every layer is read defensively and a layer
        that will not parse contributes nothing, which lands the session on the
        engine defaults rather than on no protection at all.
    """
    try:
        cfg = get_config()
        engine_ceiling = IntensityTier.parse(
            cfg.get("safety.intensity.ceiling"), source="config safety.intensity.ceiling"
        )
        engine_default = IntensityTier.parse(
            cfg.get("safety.intensity.default"), source="config safety.intensity.default"
        )
        sheet = BoundarySheet.from_mapping(
            cfg.section("safety.boundaries"), source="config"
        )
        markers = TierMarkers.from_mapping(
            cfg.section("safety.tier_markers"), source="config"
        )
        fade = bool(cfg.get("safety.fade.available", True))
        aftercare = bool(cfg.get("safety.aftercare.default", False))
        source = "config"
    except Exception as exc:  # noqa: BLE001 -- see the docstring
        logger.warning(
            "[safety] Config unreadable, using built-in defaults "
            "(operation=resolve): %s",
            exc,
        )
        return INERT_POLICY

    story = manifest_block if manifest_block is not None else _block_from_manifest()
    if story:
        # A story raises its OWN ceiling. It is repo content, reviewed like
        # code -- unlike an agent, whose ceiling requests go through the
        # ratchet above and are refused.
        #
        # ``ceiling`` is the documented spelling (docs/SAFETY.md and both
        # shipped manifests use it); ``max``/``max_intensity`` are accepted for
        # compatibility. This lookup used to read only ``max``, so a manifest's
        # declared ``ceiling:`` was silently ignored and every story got the
        # engine default.
        intensity_block = (
            story.get("intensity") if isinstance(story.get("intensity"), dict) else {}
        )
        ceiling_raw = (
            intensity_block.get("ceiling", intensity_block.get("max"))
            if intensity_block
            else story.get("max_intensity")
        )
        engine_ceiling = IntensityTier.parse(
            ceiling_raw,
            default=engine_ceiling,
            source="manifest safety.intensity.ceiling",
        )
        engine_default = IntensityTier.parse(
            (story.get("intensity") or {}).get("default")
            if isinstance(story.get("intensity"), dict)
            else story.get("default_intensity"),
            default=engine_default,
            source="manifest safety.intensity.default",
        )
        sheet = sheet.merged_with(
            BoundarySheet.from_mapping(
                story.get("boundaries"), source="manifest"
            )
        )
        story_markers = TierMarkers.from_mapping(
            story.get("tier_markers"), source="manifest"
        )
        if not story_markers.empty:
            # A story's markers replace the engine's rather than merging: the
            # words that mark a tier are genre-specific, and two vocabularies
            # interleaved would fire on neither author's intent.
            markers = story_markers
        if "fade_available" in story:
            fade = bool(story.get("fade_available"))
        if "aftercare" in story:
            aftercare = bool(story.get("aftercare"))
        source = "config+manifest"

    intensity = engine_default
    # The player's standing dial, written by the Settings screen into
    # config/local.yaml. "story" (or empty) means "follow the story's own
    # default" -- it is a sentinel, not a tier, so it must be checked before
    # parse() would log it as junk. The dial can sit anywhere on the ladder;
    # construction clamps it to the story ceiling, so a dial above the ceiling
    # is honoured as far as the story allows and no further.
    dial = str(cfg.get("safety.intensity.player", "") or "").strip().lower()
    if dial and dial != "story":
        intensity = IntensityTier.parse(
            dial, default=engine_default, source="config safety.intensity.player"
        )
    if player:
        intensity = IntensityTier.parse(
            player.get("intensity"), default=intensity, source="player"
        )
        sheet = sheet.merged_with(
            BoundarySheet.from_mapping(player.get("boundaries"), source="player")
        )
        if "fade_available" in player:
            fade = bool(player.get("fade_available"))
        if "aftercare" in player:
            aftercare = bool(player.get("aftercare"))
        source = f"{source}+player"

    policy = SafetyPolicy(
        ceiling=engine_ceiling,
        intensity=clamp(intensity, engine_ceiling),
        sheet=sheet,
        markers=markers,
        fade_available=fade,
        aftercare=aftercare,
        source=source,
    )
    logger.info(
        "[safety] Policy resolved (operation=resolve, ceiling=%s, intensity=%s, "
        "hard=%d, soft=%d, inert=%s, source=%s)",
        policy.ceiling.value,
        policy.intensity.value,
        len(policy.sheet.hard_nos),
        len(policy.sheet.soft_nos),
        policy.inert,
        policy.source,
    )
    return policy


# ---------------------------------------------------------------------------
# per-session store
# ---------------------------------------------------------------------------
#
# Process-local, keyed by GameState.session_id. It lives here rather than on
# GameState because the boundary sheet is a PRODUCT setting, not world state:
# putting it in the state object would put it in the save file, in the state
# schema's owners table, and therefore within reach of anything that can
# propose a state delta. The thing that must sit above the agents must not be
# stored in the thing the agents write to.

_POLICIES: dict[str, SafetyPolicy] = {}


def policy_for(session_id: str = "") -> SafetyPolicy:
    """
    The policy in force for a session, resolving one on first ask.

    Args:
        session_id: ``GameState.session_id``, or "" for the process default.

    Returns:
        A policy. Cached per session so the config and manifest are read once.
    """
    key = str(session_id or "")
    found = _POLICIES.get(key)
    if found is None:
        found = resolve()
        _POLICIES[key] = found
    return found


def set_policy(policy: SafetyPolicy, *, session_id: str = "") -> SafetyPolicy:
    """
    Install a policy for a session.

    This is the seam a settings screen writes through. It takes a whole policy
    rather than individual fields on purpose: a caller that wants to change one
    thing goes through ``with_intensity``/``with_limits``, which is where the
    actor rules live.
    """
    _POLICIES[str(session_id or "")] = policy
    return policy


def reset_policies() -> None:
    """
    Drop every cached policy.

    Must run whenever the config or the active game changes -- a policy
    resolved under the previous story is exactly the stale-cache failure
    ``engine/config.py::reset_config`` was written to end. See the wiring note
    in ``docs/SAFETY.md``.
    """
    _POLICIES.clear()


__all__ = [
    "INERT_POLICY",
    "Actor",
    "SafetyPolicy",
    "policy_for",
    "reset_policies",
    "resolve",
    "set_policy",
]
