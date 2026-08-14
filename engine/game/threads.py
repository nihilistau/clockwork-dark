"""
Threads — bargains as persistent, cuttable objects
==================================================

A thread is a contract the world remembers. It is offered, its terms are
stated, it is sealed by some act, and then it *stays* -- until it is discharged,
broken, or transformed into a different contract. Nothing about it is prose the
model can quietly stop honouring three scenes later.

    Offer -> Terms -> Seal -> Thread

WHY RENEGOTIATE IS A VERB AND NOT A BUTTON. The obvious implementation of a
bargain system is accept/refuse, and it is the wrong one: it makes every deal a
coin flip between "yes" and "no deal", which is exactly the interaction a
bargain is supposed to replace. ``renegotiate`` here returns a **different
offer** -- its own terms, its own tags, its own costs, possibly no contract at
all -- drawn from variants the template declared. The player who names the price
up front does not get the same thread on better numbers; they get a thread about
knowing the price, which is a different object with different consequences when
it comes due.

WHY ACCEPTING A GIFT CREATES ONE BY ITSELF. "Gifts accepted without negotiation
auto-thread Obligation" is a rule of the fiction, and a rule of the fiction that
lives only in a prompt is a rule that holds until the model is distracted.
``accept_gift`` is the engine saying it: take the thing without asking, and a
contract exists whether or not anyone narrated one.

WHAT THIS IS BUILT ON. ``engine/memory/ledger.py`` already has ``Promise``
(from_id / to_id / due_day / status / expiry sweep) and ``NPCRelation.owed``,
and they are the closest existing fit -- a promise IS a thread with no tags, no
terms and no way to be cut. So a sealed thread mirrors itself into the ledger as
a Promise: the memory layer, the disposition predicates and the prompt shapers
keep working on promises exactly as they do today, and the thread carries the
mechanical half the ledger was never meant to hold. Two records, one of them
derived, rather than two systems that disagree about what the player owes.

WHY A THREAD CARRIES ITS OWN OUTCOME EFFECTS instead of looking them up from its
template when it resolves: a renegotiated contract is a DIFFERENT contract. If
resolution re-read the template, a thread transformed into "you named the price"
would still break with the penalty attached to "you took it without asking",
which is precisely the distinction the renegotiate verb exists to create.

Threads live in ``GameState.threads`` as plain dicts, for the same reason
``encounter`` and ``challenge`` do: the shape is story-declared and must not
force a save migration per field.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.challenges import spec as spec_module
from engine.game import effects as effects_module
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

# -- lifecycle --------------------------------------------------------------
STATUS_ACTIVE = "active"
STATUS_DISCHARGED = "discharged"
STATUS_BROKEN = "broken"
STATUS_TRANSFORMED = "transformed"
STATUSES: tuple[str, ...] = (
    STATUS_ACTIVE,
    STATUS_DISCHARGED,
    STATUS_BROKEN,
    STATUS_TRANSFORMED,
)

#: A renegotiation variant may declare ``outcome: none``, which means the
#: negotiation ended in NO contract. Refusing well is a legal move and it is not
#: the same as never having been offered anything -- the refusal still has
#: effects, and the offer still happened.
OUTCOME_NONE = "none"

#: How a thread was sealed. Open-ended by design (a story may seal with a dance
#: or a debt), but these four cover the Garden's word / kiss / blood / gift.
DEFAULT_SEAL = "word"

#: Tag on an ``InventoryItem`` binding it to a thread. Encoded as a tag rather
#: than a new field on ``InventoryItem`` because tags already serialise, already
#: round-trip through every save ever written, and are already how items carry
#: their other mechanical facts. ``bound_thread_id`` in the design dictionary is
#: this, spelled in the vocabulary the engine already had.
ITEM_THREAD_TAG_PREFIX = "thread:"

# -- bounds -----------------------------------------------------------------
#: An offer is partly model-composed, so it is bounded like a challenge spec.
MAX_TAGS = 6
MAX_TERMS_CHARS = 400
MAX_CUTTERS = 6
MAX_THREADS = 24
MAX_HISTORY = 12


@dataclass
class Offer:
    """
    A proposed contract. NOT on the state and deliberately so.

    An offer that wrote itself to the state would make "she offered and you
    walked away" indistinguishable from "you agreed", and the walking away is
    half of what a bargain system is for. Nothing exists mechanically until
    ``seal``.
    """

    template: str = ""
    thread_id: str = ""
    source: str = ""
    to_id: str = ""
    tags: list[str] = field(default_factory=list)
    terms: str = ""
    label: str = ""
    can_cut_with: list[str] = field(default_factory=list)
    due_in_days: Optional[int] = None
    on_seal: list[dict[str, Any]] = field(default_factory=list)
    on_discharge: list[dict[str, Any]] = field(default_factory=list)
    on_break: list[dict[str, Any]] = field(default_factory=list)
    #: ``none`` when this variant is "no contract" -- see OUTCOME_NONE.
    outcome: str = "thread"
    #: Renegotiation variants still available from here, by id.
    variants: dict[str, Any] = field(default_factory=dict)
    #: Which variants were walked through to reach this offer, in order. The
    #: receipt of a negotiation, so a UI can show what was traded away.
    negotiated: list[str] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "thread_id": self.thread_id,
            "source": self.source,
            "to_id": self.to_id,
            "tags": list(self.tags),
            "terms": self.terms,
            "label": self.label,
            "can_cut_with": list(self.can_cut_with),
            "due_in_days": self.due_in_days,
            "outcome": self.outcome,
            "negotiated": list(self.negotiated),
            "variants": sorted(self.variants),
            "adjustments": list(self.adjustments),
        }


# ---------------------------------------------------------------------------
# The rules file
# ---------------------------------------------------------------------------


def _table_path() -> Optional[Path]:
    """The thread table, or None when the story declares none."""
    from engine.config import get_config

    rel = str(get_config().get("paths.threads", "") or "").strip()
    return (_ROOT / rel) if rel else None


@lru_cache(maxsize=8)
def _read_table(path_str: str, _mtime: float) -> dict[str, Any]:
    """Parse threads.yaml, memoized on (path, mtime). See engine/game/survival.py."""
    try:
        with Path(path_str).open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("[threads] Unreadable thread rules: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def load_rules() -> dict[str, Any]:
    """
    The story's thread declarations.

    A missing file yields an empty table: a story with no bargain system runs
    exactly as it did before this module existed.
    """
    path = _table_path()
    if path is None:
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    return _read_table(str(path), mtime)


def is_declared() -> bool:
    """
    Whether this story has a bargain system AT ALL.

    Distinct from "the player currently owes nobody anything", and the
    distinction is the whole of how a client knows not to draw a contracts
    screen: a story with no threads table gets no block in the payload and
    therefore no permanently empty modal, while a story that ships one gets the
    block on day one with nothing in it yet, which is a real empty state.
    """
    return bool(load_rules())


def templates() -> dict[str, Any]:
    return load_rules().get("templates") or {}


def declared_tags() -> tuple[str, ...]:
    """The story's tag vocabulary. Empty means "any tag", for a story with none."""
    raw = load_rules().get("tags") or ()
    return tuple(str(t) for t in raw)


def cutters() -> dict[str, Any]:
    """What can sever a thread in this story, and what each severing costs."""
    raw = load_rules().get("cutters") or {}
    return raw if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# Bounding
# ---------------------------------------------------------------------------


def _bound_tags(raw: Any, adjustments: list[str]) -> list[str]:
    """Keep declared tags only, capped. An undeclared tag is dropped, not renamed."""
    wanted = [str(t).strip() for t in (raw or []) if str(t).strip()]
    vocabulary = declared_tags()
    if vocabulary:
        kept = [t for t in wanted if t in vocabulary]
        for dropped in [t for t in wanted if t not in vocabulary]:
            adjustments.append(f"dropped tag {dropped!r}, not in the story's vocabulary")
    else:
        kept = wanted
    if len(kept) > MAX_TAGS:
        adjustments.append(f"kept the first {MAX_TAGS} of {len(kept)} tags")
        kept = kept[:MAX_TAGS]
    return kept


def _bound_cutters(raw: Any, adjustments: list[str]) -> list[str]:
    """
    Keep only cutters the story declared.

    A thread claiming it can be cut by something that does not exist is worse
    than an uncuttable thread: the player is told there is a way out and there
    is not. Honesty here is the same requirement the ending gates have.
    """
    known = cutters()
    wanted = [str(c).strip() for c in (raw or []) if str(c).strip()]
    kept = [c for c in wanted if not known or c in known]
    for dropped in [c for c in wanted if known and c not in known]:
        adjustments.append(f"dropped cutter {dropped!r}, not declared by this story")
    return kept[:MAX_CUTTERS]


def _bound_effects(raw: Any, adjustments: list[str]) -> list[dict[str, Any]]:
    """
    Bound a hook's effects with the challenge spec's ceilings.

    Reused rather than reinvented: the question "how much may one authored
    outcome be worth" has exactly one answer in this engine, and it is now
    derived from the running story's own declared bounds
    (``engine/challenges/spec.py``). A thread that could pay more than a
    challenge would just be a challenge with a longer fuse.
    """
    return spec_module.clamp_outcome({"effects": raw or []}, adjustments)["effects"]


# ---------------------------------------------------------------------------
# Offer -> Terms -> Seal
# ---------------------------------------------------------------------------


def _offer_from_spec(
    template_id: str,
    raw: dict[str, Any],
    *,
    source: str,
    to_id: str,
    thread_id: str,
    negotiated: list[str],
    adjustments: list[str],
) -> Offer:
    """Build a bounded Offer from a template or renegotiation variant body."""
    due = raw.get("due_in_days")
    try:
        due_days = None if due is None else max(0, int(due))
    except (TypeError, ValueError):
        due_days = None

    return Offer(
        template=template_id,
        thread_id=thread_id,
        source=str(raw.get("source") or source or ""),
        to_id=str(raw.get("to_id") or to_id or source or ""),
        tags=_bound_tags(raw.get("tags"), adjustments),
        terms=str(raw.get("terms") or "").strip()[:MAX_TERMS_CHARS],
        label=str(raw.get("label") or "").strip()[:120],
        can_cut_with=_bound_cutters(raw.get("can_cut_with"), adjustments),
        due_in_days=due_days,
        on_seal=_bound_effects(raw.get("on_seal"), adjustments),
        on_discharge=_bound_effects(raw.get("on_discharge"), adjustments),
        on_break=_bound_effects(raw.get("on_break"), adjustments),
        outcome=str(raw.get("outcome") or "thread").strip().lower(),
        variants=dict(raw.get("renegotiations") or {}),
        negotiated=list(negotiated),
        adjustments=adjustments,
    )


def offer(
    state: GameState,
    template_id: str,
    *,
    source: str = "",
    to_id: str = "",
    thread_id: str = "",
) -> Optional[Offer]:
    """
    Propose a contract from a declared template. Writes nothing.

    Args:
        state: Game state, read for the id counter only.
        template_id: Key in ``threads.yaml``'s ``templates``.
        source: Who is offering. Overrides the template's own ``source``.
        to_id: The other party, for the ledger Promise. Defaults to ``source``.
        thread_id: Explicit id. Defaults to a deterministic one derived from the
            template and the number of threads already on the save, so an id is
            stable across a replay of the same seed.

    Returns:
        A bounded Offer, or None when the template is not declared.
    """
    raw = templates().get(template_id)
    if not isinstance(raw, dict):
        logger.warning(
            "[threads] Unknown thread template, ignoring (operation=offer, "
            "template=%s)",
            template_id,
        )
        return None

    adjustments: list[str] = []
    return _offer_from_spec(
        template_id,
        raw,
        source=source,
        to_id=to_id,
        thread_id=thread_id or _next_thread_id(state, template_id),
        negotiated=[],
        adjustments=adjustments,
    )


def terms_of(proposal: Offer) -> dict[str, Any]:
    """
    The contract as it would be sealed, plus what else could still be asked for.

    Separate from ``offer`` because Terms is its own step of the fiction: the
    illuminated page the player reads before deciding, carrying the options
    ("I understand / I refuse / I renegotiate") the UI renders.
    """
    return {
        **proposal.to_dict(),
        "renegotiations": [
            {
                "id": str(key),
                "label": str((body or {}).get("label") or key),
                "terms": str((body or {}).get("terms") or "")[:MAX_TERMS_CHARS],
                "outcome": str((body or {}).get("outcome") or "thread"),
            }
            for key, body in proposal.variants.items()
            if isinstance(body, dict)
        ],
    }


def renegotiate(
    state: GameState,
    proposal: Offer,
    variant_id: str,
    *,
    ledger: Optional[Any] = None,
) -> Optional[Offer]:
    """
    Turn one offer into a DIFFERENT offer.

    Not a yes/no and not a discount. The variant declares its own terms, tags,
    cutters and effects; ``outcome: none`` declares that this line of
    negotiation ends with no contract, which is a real outcome and not a
    failure.

    A variant may declare ``requires:`` -- a condition from the shared grammar.
    Renegotiating from a position you do not hold is refused rather than
    silently granted: "she will discuss it with someone who has read the laws"
    is a mechanic, not a mood.

    Args:
        state: Game state, read by the variant's ``requires`` condition.
        proposal: The offer on the table.
        variant_id: Key in the current offer's ``renegotiations``.
        ledger: Optional StoryLedger, for conditions that read disposition.

    Returns:
        A new Offer, or None when the variant is unavailable or ungated.
    """
    raw = proposal.variants.get(variant_id)
    if not isinstance(raw, dict):
        logger.info(
            "[threads] Renegotiation not on the table (operation=renegotiate, "
            "thread=%s, variant=%s)",
            proposal.thread_id,
            variant_id,
        )
        return None

    from engine.game.quests import evaluate_condition

    if not evaluate_condition(state, raw.get("requires"), ledger=ledger):
        logger.info(
            "[threads] Renegotiation refused, terms not met "
            "(operation=renegotiate, thread=%s, variant=%s)",
            proposal.thread_id,
            variant_id,
        )
        return None

    adjustments: list[str] = []
    # Inherit what the variant does not restate. A renegotiation usually
    # changes one clause; making the author re-type the whole contract to
    # change its due date is how contracts drift out of agreement with
    # themselves.
    merged = {
        "source": proposal.source,
        "to_id": proposal.to_id,
        "tags": proposal.tags,
        "can_cut_with": proposal.can_cut_with,
        "due_in_days": proposal.due_in_days,
        "on_seal": proposal.on_seal,
        "on_discharge": proposal.on_discharge,
        "on_break": proposal.on_break,
        **{k: v for k, v in raw.items() if k not in ("requires",)},
    }
    return _offer_from_spec(
        proposal.template,
        merged,
        source=proposal.source,
        to_id=proposal.to_id,
        thread_id=proposal.thread_id,
        negotiated=[*proposal.negotiated, str(variant_id)],
        adjustments=adjustments,
    )


def seal(
    state: GameState,
    proposal: Offer,
    *,
    sealed_by: str = DEFAULT_SEAL,
    ledger: Optional[Any] = None,
    by: str = "engine",
) -> dict[str, Any]:
    """
    Make an offer real.

    Args:
        state: Mutable game state.
        proposal: The offer as finally negotiated.
        sealed_by: The act that bound it -- word, kiss, blood, gift. Recorded
            because the Garden's laws care which, and because "you agreed to
            this in blood" is a different sentence from "you nodded".
        ledger: Optional StoryLedger. The thread mirrors itself in as a Promise.
        by: Writer id for the ``on_seal`` effects.

    Returns:
        A receipt: ``ok``, ``text``, the ``thread`` as stored, and the effect
        descriptions. ``ok`` is False when the negotiation ended in no contract
        (which is not an error) or the save is already at ``MAX_THREADS``.
    """
    if proposal.outcome == OUTCOME_NONE:
        # Still applies its effects: walking away from a bargain costs and
        # earns things, and the walking away is the outcome.
        applied = effects_module.apply_effects(
            state, proposal.on_seal, ledger=ledger, by=by, turn=state.turn_number
        )
        return {
            "ok": False,
            "outcome": OUTCOME_NONE,
            "thread": None,
            "negotiated": list(proposal.negotiated),
            "effects": applied,
            "text": proposal.terms or "no contract",
        }

    if len(active(state)) >= MAX_THREADS:
        logger.warning(
            "[threads] Refusing to seal, save is at the thread ceiling "
            "(operation=seal, ceiling=%d)",
            MAX_THREADS,
        )
        return {
            "ok": False,
            "thread": None,
            "effects": [],
            "text": f"too many live bargains ({MAX_THREADS})",
        }

    if get(state, proposal.thread_id) is not None:
        return {
            "ok": False,
            "thread": get(state, proposal.thread_id),
            "effects": [],
            "text": f"thread {proposal.thread_id} already exists",
        }

    due_day = (
        None if proposal.due_in_days is None else state.world_day + proposal.due_in_days
    )

    thread: dict[str, Any] = {
        "id": proposal.thread_id,
        "template": proposal.template,
        "source": proposal.source,
        "to_id": proposal.to_id,
        "tags": list(proposal.tags),
        "terms": proposal.terms,
        "status": STATUS_ACTIVE,
        "sealed_by": str(sealed_by),
        "created_day": state.world_day,
        "created_turn": state.turn_number,
        "due_day": due_day,
        "can_cut_with": list(proposal.can_cut_with),
        "bound_items": [],
        "parent_id": "",
        "promise_id": "",
        "negotiated": list(proposal.negotiated),
        # Carried, not looked up. See the module docstring.
        "on_discharge": list(proposal.on_discharge),
        "on_break": list(proposal.on_break),
        "history": [],
    }

    if ledger is not None and proposal.to_id:
        promise = ledger.add_promise(
            proposal.terms or f"a bargain with {proposal.to_id}",
            to_id=proposal.to_id,
            due_day=due_day,
            turn=state.turn_number,
        )
        thread["promise_id"] = promise.id

    state.threads.append(thread)
    _record(state, thread, "sealed", f"by {sealed_by}")

    applied = effects_module.apply_effects(
        state, proposal.on_seal, ledger=ledger, by=by, turn=state.turn_number
    )
    logger.info(
        "[threads] Thread sealed (operation=seal, thread=%s, source=%s, tags=%s)",
        thread["id"],
        thread["source"],
        thread["tags"],
    )
    return {
        "ok": True,
        "thread": thread,
        "negotiated": list(proposal.negotiated),
        "effects": applied,
        "text": f"sealed: {proposal.terms or proposal.thread_id} ({sealed_by})",
    }


# ---------------------------------------------------------------------------
# Gifts
# ---------------------------------------------------------------------------


def accept_gift(
    state: GameState,
    item_id: str,
    *,
    from_id: str,
    negotiated: bool = False,
    name: str = "",
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Take a gift. Without negotiating, that is a contract.

    Args:
        state: Mutable game state.
        item_id: The gift.
        from_id: Who gave it.
        negotiated: True when the player asked what it costs first. The item is
            granted either way; only the obligation differs.
        name: Display name for the inventory entry.
        ledger: Optional StoryLedger.

    Returns:
        Receipt with the item effect, the thread (or None), and ``obligated``.
    """
    item_receipt = effects_module.apply_effect(
        state,
        {"type": "item", "item_id": item_id, "qty": 1, "name": name or item_id},
        ledger=ledger,
    )

    if negotiated:
        return {
            "ok": True,
            "item": item_receipt,
            "thread": None,
            "obligated": False,
            "text": f"{item_receipt.get('text', item_id)}; terms were named first",
        }

    template_id = str(
        (load_rules().get("gift_obligation") or {}).get("template") or ""
    ).strip()
    proposal = offer(state, template_id, source=from_id) if template_id else None
    if proposal is None:
        # A story with no gift-obligation template simply has generous Fae.
        # Not an error, and it must not cost the player the item.
        return {
            "ok": True,
            "item": item_receipt,
            "thread": None,
            "obligated": False,
            "text": item_receipt.get("text", item_id),
        }

    proposal.terms = proposal.terms or f"an unnamed debt to {from_id}"
    sealed = seal(state, proposal, sealed_by="gift", ledger=ledger)
    thread = sealed.get("thread")
    if isinstance(thread, dict):
        bind_item(state, item_id, thread["id"])

    return {
        "ok": True,
        "item": item_receipt,
        "thread": thread,
        "obligated": thread is not None,
        "effects": sealed.get("effects", []),
        "text": f"{item_receipt.get('text', item_id)}; a thread came with it",
    }


# ---------------------------------------------------------------------------
# Items bound to threads
# ---------------------------------------------------------------------------


def bind_item(state: GameState, item_id: str, thread_id: str) -> bool:
    """
    Bind an item to a thread so that cutting one cascades to the other.

    The collar IS the bargain: severing the bargain leaves you holding a strap,
    and losing the strap does not release you but does change what the contract
    is about. Both directions are implemented -- ``cut`` removes bound items,
    ``cut_item`` cuts the bound thread.
    """
    thread = get(state, thread_id)
    if thread is None:
        return False
    tag = f"{ITEM_THREAD_TAG_PREFIX}{thread_id}"
    for entry in state.inventory:
        if entry.id != item_id:
            continue
        if tag not in entry.tags:
            entry.tags.append(tag)
        if item_id not in thread["bound_items"]:
            thread["bound_items"].append(item_id)
        return True
    return False


def item_threads(state: GameState, item_id: str) -> list[str]:
    """Thread ids an inventory item is bound to."""
    out: list[str] = []
    for entry in state.inventory:
        if entry.id != item_id:
            continue
        out.extend(
            tag[len(ITEM_THREAD_TAG_PREFIX) :]
            for tag in entry.tags
            if tag.startswith(ITEM_THREAD_TAG_PREFIX)
        )
    return out


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def get(state: GameState, thread_id: str) -> Optional[dict[str, Any]]:
    """One thread by id, whatever its status."""
    return next((t for t in state.threads if str(t.get("id")) == str(thread_id)), None)


def active(state: GameState) -> list[dict[str, Any]]:
    """Live threads. What the player is currently on the hook for."""
    return [t for t in state.threads if t.get("status") == STATUS_ACTIVE]


def by_tag(state: GameState, tag: str, *, status: str = STATUS_ACTIVE) -> list[dict[str, Any]]:
    """Threads carrying a tag. ``status=""`` means any status."""
    return [
        t
        for t in state.threads
        if tag in (t.get("tags") or []) and (not status or t.get("status") == status)
    ]


def summary(state: GameState) -> list[dict[str, Any]]:
    """
    Live threads, trimmed for a prompt block or a UI list.

    Deliberately not the whole record: the effect hooks are the engine's
    business, and putting them in front of a model invites it to narrate the
    numbers.
    """
    return [
        {
            "id": t.get("id"),
            "source": t.get("source"),
            "tags": list(t.get("tags") or []),
            "terms": t.get("terms"),
            "due_day": t.get("due_day"),
            "can_cut_with": list(t.get("can_cut_with") or []),
            # What the seal actually WAS. A contract that says only "sealed"
            # loses the one detail this story's bargains turn on -- a word said
            # aloud and a coin halved are different promises, and a screen that
            # renders the scroll has to be able to say which one this is.
            "sealed_by": t.get("sealed_by") or "",
        }
        for t in active(state)
    ]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _record(state: GameState, thread: dict[str, Any], event: str, detail: str = "") -> None:
    """Append to a thread's history, bounded. A contract remembers its own life."""
    history = thread.setdefault("history", [])
    history.append(
        {"day": state.world_day, "turn": state.turn_number, "event": event, "detail": detail}
    )
    if len(history) > MAX_HISTORY:
        del history[: len(history) - MAX_HISTORY]


def _next_thread_id(state: GameState, template_id: str) -> str:
    """Deterministic id, so the same seed replays to the same thread ids."""
    return f"{template_id}_{len(state.threads) + 1}"


def _close(
    state: GameState,
    thread_id: str,
    status: str,
    hook: str,
    *,
    why: str,
    ledger: Optional[Any],
    by: str,
) -> dict[str, Any]:
    """Shared tail of discharge / break / expire."""
    thread = get(state, thread_id)
    if thread is None:
        return {"ok": False, "thread": None, "effects": [], "text": f"no thread {thread_id}"}
    if thread.get("status") != STATUS_ACTIVE:
        return {
            "ok": False,
            "thread": thread,
            "effects": [],
            "text": f"thread {thread_id} is already {thread.get('status')}",
        }

    thread["status"] = status
    _record(state, thread, status, why)

    if ledger is not None and thread.get("promise_id"):
        # The ledger's own vocabulary: it knows kept and broken, not discharged
        # and transformed. Mapped rather than pushed, so the memory layer keeps
        # meaning what it always meant.
        ledger.resolve_promise(
            str(thread["promise_id"]),
            "kept" if status == STATUS_DISCHARGED else "broken",
        )

    applied = effects_module.apply_effects(
        state, thread.get(hook) or [], ledger=ledger, by=by, turn=state.turn_number
    )
    logger.info(
        "[threads] Thread %s (operation=_close, thread=%s, why=%s)",
        status,
        thread_id,
        why,
    )
    return {
        "ok": True,
        "thread": thread,
        "effects": applied,
        "text": f"{thread.get('terms') or thread_id}: {status}",
    }


def discharge(
    state: GameState,
    thread_id: str,
    *,
    why: str = "paid",
    ledger: Optional[Any] = None,
    by: str = "engine",
) -> dict[str, Any]:
    """Pay a contract off. The clean exit."""
    return _close(state, thread_id, STATUS_DISCHARGED, "on_discharge", why=why, ledger=ledger, by=by)


def break_thread(
    state: GameState,
    thread_id: str,
    *,
    why: str = "broken",
    ledger: Optional[Any] = None,
    by: str = "engine",
) -> dict[str, Any]:
    """Renege. Costly by construction: ``on_break`` is the price."""
    return _close(state, thread_id, STATUS_BROKEN, "on_break", why=why, ledger=ledger, by=by)


def transform(
    state: GameState,
    thread_id: str,
    variant_id: str,
    *,
    ledger: Optional[Any] = None,
    by: str = "engine",
) -> dict[str, Any]:
    """
    Renegotiate a contract that is ALREADY SEALED.

    The old thread ends as ``transformed`` -- not discharged (nothing was paid)
    and not broken (nothing was reneged on) -- and a new one is sealed in its
    place carrying ``parent_id``. That third state is why the lifecycle has four
    entries instead of three: "we agreed to something else" is a real thing that
    happens to contracts and it is not a failure of either party.
    """
    thread = get(state, thread_id)
    if thread is None or thread.get("status") != STATUS_ACTIVE:
        return {"ok": False, "thread": thread, "effects": [], "text": "no live thread there"}

    raw = templates().get(str(thread.get("template"))) or {}
    variants = (raw.get("renegotiations") or {}) if isinstance(raw, dict) else {}
    base = Offer(
        template=str(thread.get("template") or ""),
        thread_id=f"{thread_id}_t{len(state.threads) + 1}",
        source=str(thread.get("source") or ""),
        to_id=str(thread.get("to_id") or ""),
        tags=list(thread.get("tags") or []),
        terms=str(thread.get("terms") or ""),
        can_cut_with=list(thread.get("can_cut_with") or []),
        on_discharge=list(thread.get("on_discharge") or []),
        on_break=list(thread.get("on_break") or []),
        variants=dict(variants),
    )
    replacement = renegotiate(state, base, variant_id, ledger=ledger)
    if replacement is None:
        return {
            "ok": False,
            "thread": thread,
            "effects": [],
            "text": f"cannot renegotiate {thread_id} into {variant_id}",
        }

    thread["status"] = STATUS_TRANSFORMED
    _record(state, thread, STATUS_TRANSFORMED, f"into {variant_id}")

    sealed = seal(state, replacement, sealed_by="renegotiation", ledger=ledger, by=by)
    new_thread = sealed.get("thread")
    if isinstance(new_thread, dict):
        new_thread["parent_id"] = thread_id
        # Bound items follow the contract, not the paper. A collar bound to the
        # obligation you renegotiated is still around your neck.
        for item_id in thread.get("bound_items") or []:
            bind_item(state, str(item_id), new_thread["id"])
    return {
        "ok": sealed.get("ok", False),
        "thread": new_thread,
        "was": thread,
        "effects": sealed.get("effects", []),
        "text": f"{thread_id} became {variant_id}",
    }


def expire_due(
    state: GameState,
    *,
    ledger: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """
    Break every live thread whose day has passed. Silence is an answer too.

    Named after and shaped like ``StoryLedger.expire_promises``, which does the
    same job for the memory half of the same record. Called on a day tick.
    """
    out: list[dict[str, Any]] = []
    for thread in list(active(state)):
        due = thread.get("due_day")
        if due is None or state.world_day <= int(due):
            continue
        out.append(
            break_thread(state, str(thread["id"]), why="came due unpaid", ledger=ledger)
        )
    return out


# ---------------------------------------------------------------------------
# Cutting
# ---------------------------------------------------------------------------


def can_cut(state: GameState, thread_id: str, using: str, *, ledger: Optional[Any] = None) -> tuple[bool, str]:
    """
    Whether this cutter works on this thread, and why not when it does not.

    Returns:
        ``(ok, reason)``. The reason is for the player: being told a knife will
        not cut this and not being told why is the same as not being told.
    """
    thread = get(state, thread_id)
    if thread is None:
        return False, f"no thread {thread_id}"
    if thread.get("status") != STATUS_ACTIVE:
        return False, f"thread is already {thread.get('status')}"
    if using not in (thread.get("can_cut_with") or []):
        return False, f"{using} does not cut this one"

    known = cutters()
    if known and using not in known:
        # Checked again HERE and not only when the offer was bounded, because a
        # thread can reach this point without passing through `offer` -- loaded
        # from a save written by a build with a different rules file, or
        # assembled by a caller. A contract advertising an escape route the
        # world never implemented is the dishonesty the ending gates are also
        # written to avoid.
        logger.warning(
            "[threads] Thread names an undeclared cutter (operation=can_cut, "
            "thread=%s, cutter=%s)",
            thread_id,
            using,
        )
        return False, f"{using} is not a thing that cuts, in this world"

    rules = known.get(using) or {}
    if str(rules.get("kind")) == "item" and not any(
        entry.id == using for entry in state.inventory
    ):
        return False, f"you are not carrying {using}"

    from engine.game.quests import evaluate_condition

    if not evaluate_condition(state, rules.get("requires"), ledger=ledger):
        return False, str(rules.get("denied_text") or f"you cannot invoke {using}")
    return True, ""


def cut(
    state: GameState,
    thread_id: str,
    *,
    using: str,
    ledger: Optional[Any] = None,
    by: str = "engine",
) -> dict[str, Any]:
    """
    Sever a contract with an item, a law, a death or a sovereign word.

    Cutting is BREAKING, not discharging -- the contract's ``on_break`` price is
    paid. A knife that let you out of a bargain for free would make every
    bargain optional, which is the same as having none.

    Cascades: bound items go with the thread. Consuming cutters are spent.
    """
    ok, reason = can_cut(state, thread_id, using, ledger=ledger)
    if not ok:
        return {"ok": False, "thread": get(state, thread_id), "effects": [], "text": reason}

    thread = get(state, thread_id)
    assert thread is not None  # can_cut said so

    spent: list[dict[str, Any]] = []
    rules = cutters().get(using) or {}
    if str(rules.get("kind")) == "item" and bool(rules.get("consumes")):
        spent.append(
            effects_module.apply_effect(
                state, {"type": "remove_item", "item_id": using, "qty": 1}, ledger=ledger
            )
        )

    lost: list[dict[str, Any]] = []
    for item_id in list(thread.get("bound_items") or []):
        lost.append(
            effects_module.apply_effect(
                state, {"type": "remove_item", "item_id": str(item_id)}, ledger=ledger
            )
        )

    result = break_thread(state, thread_id, why=f"cut with {using}", ledger=ledger, by=by)
    result["cut_with"] = using
    result["spent"] = spent
    result["cascaded"] = lost
    result["text"] = f"cut with {using}: {thread.get('terms') or thread_id}"
    return result


def cut_item(
    state: GameState,
    item_id: str,
    *,
    using: str,
    ledger: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Cut every thread an item is bound to. The other direction of the cascade."""
    return [
        cut(state, thread_id, using=using, ledger=ledger)
        for thread_id in item_threads(state, item_id)
    ]


def cut_arbitrary(
    state: GameState,
    *,
    using: str,
    tag: str = "",
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Cut ONE live thread chosen by seeded chance.

    For the scene where the knife goes into the mirror and something is severed
    but nobody chose what (``DAY-08-MIRRORS.md`` D8-04). Drawn from
    ``world_rng(state, THREAD)`` so it replays identically from a seed -- a
    "random" cut resolved with bare ``random`` would make that scene the one
    place in the game a bug report could not be reproduced.

    Args:
        tag: Narrow the pool to threads carrying this tag.
    """
    from engine.game.rng import THREAD as RNG_THREAD
    from engine.game.rng import world_rng

    pool = [
        t
        for t in active(state)
        if can_cut(state, str(t["id"]), using, ledger=ledger)[0]
        and (not tag or tag in (t.get("tags") or []))
    ]
    if not pool:
        return {"ok": False, "thread": None, "effects": [], "text": "nothing here to cut"}

    # Sorted before the draw: `state.threads` order is insertion order and is
    # stable, but sorting makes the draw independent of the order threads
    # happened to be sealed in, which is what "same seed, same result" means.
    pool.sort(key=lambda t: str(t["id"]))
    chosen = world_rng(state, RNG_THREAD).choice(pool)
    return cut(state, str(chosen["id"]), using=using, ledger=ledger)


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def _p_thread(state: GameState, value: Any, ctx: Any) -> bool:
    """
    ``{thread: {id: ashen_service_owed, status: active}}``
    ``{thread: {tag: Service, status: active, min_count: 1}}``
    ``{thread: {source: sophia, status: active}}``

    The finale's collision table is written entirely in terms of "what is still
    live", so this predicate is what makes ``DAY-09-FINALE.md``'s F2 expressible
    in data rather than in a Python if-chain.
    """
    if isinstance(value, str):
        thread = get(state, value)
        return thread is not None and thread.get("status") == STATUS_ACTIVE
    if not isinstance(value, dict):
        return False

    status = str(value.get("status", STATUS_ACTIVE))
    pool = [t for t in state.threads if not status or t.get("status") == status]
    if "id" in value:
        pool = [t for t in pool if str(t.get("id")) == str(value["id"])]
    if "tag" in value:
        pool = [t for t in pool if str(value["tag"]) in (t.get("tags") or [])]
    if "source" in value:
        pool = [t for t in pool if str(t.get("source")) == str(value["source"])]
    if "template" in value:
        pool = [t for t in pool if str(t.get("template")) == str(value["template"])]
    if "overdue" in value:
        want = bool(value["overdue"])
        pool = [
            t
            for t in pool
            if (t.get("due_day") is not None and state.world_day > int(t["due_day"])) is want
        ]

    minimum = int(value.get("min_count", 1))
    if "max_count" in value and len(pool) > int(value["max_count"]):
        return False
    return len(pool) >= minimum


def _p_no_thread(state: GameState, value: Any, ctx: Any) -> bool:
    """``{no_thread: {tag: Service}}`` -- nothing of this shape is live."""
    return not _p_thread(state, value, ctx)


def _register() -> None:
    from engine.game.quests import register_predicate

    register_predicate("thread", _p_thread)
    register_predicate("no_thread", _p_no_thread)


_register()


__all__ = [
    "DEFAULT_SEAL",
    "ITEM_THREAD_TAG_PREFIX",
    "MAX_THREADS",
    "OUTCOME_NONE",
    "STATUSES",
    "STATUS_ACTIVE",
    "STATUS_BROKEN",
    "STATUS_DISCHARGED",
    "STATUS_TRANSFORMED",
    "Offer",
    "accept_gift",
    "active",
    "bind_item",
    "break_thread",
    "by_tag",
    "can_cut",
    "cut",
    "cut_arbitrary",
    "cut_item",
    "cutters",
    "declared_tags",
    "discharge",
    "expire_due",
    "get",
    "is_declared",
    "item_threads",
    "load_rules",
    "offer",
    "renegotiate",
    "seal",
    "summary",
    "templates",
    "terms_of",
    "transform",
]
