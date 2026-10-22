"""
The voicing call (v0.22.0 spec §11.1-11.4; reworked in v0.23.0 spec §4.5,
§7.4, §13): the model writes what one person SAYS in one thread, and
proposes -- inside engine bounds -- how the exchange moved them. Nothing
here writes state (rule 1): `voice` is pure over a `PersonSnapshot`, and the
commit is the voicing pass's (engine/social/voicer.py).

- **The snapshot** (`snapshot_of`, under the turn lock): one person, one
  thread, its due messages and their `Decision`s, deep copies of everything
  the prompt and the agreement checks read -- their memory (story, recaps,
  bridge, the open conversation, open rows), who they are now
  (`growth.who_now`), the commitments that hold, their promises, a layer
  they are ready to open up about -- and `seed` (`state.rng_seed`), the
  fallback's only seed (pre-flight F9).
- **The mode** (spec §4.5): `Decision.mode` (quick, chatting, deep) sets the
  bubble count, each bubble's length and the call's `max_tokens`
  (`mode_caps`, conversation.yaml `modes.caps`). The prompt's window is
  derived per call (`window_for`, §7.4): min(`social.voice.window_tokens`,
  the binding's usable context) less the mode's cap. A binding under the
  configured window is DEGRADED: deep uses chatting's caps, three recaps are
  kept and the story is cut to 120 words before anything else is trimmed.
- **The schema** (`reply_schema`, §13.3): bubbles (the mode's count and
  length), a `media` caption only when media is attached, a regard proposal
  inside the schema's bounds (the engine's own clamp is relationships.yaml's,
  at commit), learned/shared facts, `followups` (at most 2, each `{about,
  when}`, `when` an enum the engine resolves), `promise` (only while the
  conversation is winding or signing off with no promise made, its window an
  enum of the windows that resolve for this person in reach) and the
  proposals legal at the snapshot (`relationships.legal_proposals`, built per
  turn, so an illegal one is unsamplable). With no proposal legal the key is
  left out (`additionalProperties: false` then forbids it).
- **The prompt** (`messages`, §13.2): the system message is `texter.md`'s
  persona section verbatim (everything above `## Instructions`, Plan
  decision 22); the user message is the eight titled blocks of
  `BLOCK_TITLES`, ordered stable to volatile so a server's prompt-prefix
  cache reuses the most, trimmed by `memory.budgeted`. RIGHT NOW carries the
  mode, the end with its reason, a promise, a follow-up and a layer to open
  up about, each as the story's own instruction row, and ends with the
  SITUATION row.
- **The call** (`voice`): one call (the mode's `max_tokens` passed through
  `backend.chat` by `production_llm_fn`), the reply conformed and held to
  the schema, the agreement checks, one retry with a one-line correction
  naming only the fact the reply got wrong, then the offending bubbles and
  facts dropped, else the engine-written fallback.
- **The fallback** (`fallback_reply`, §13.1): a line from `texter.md`'s
  fallbacks, keyed by archetype and by `situation.mode` (`any:` for every
  archetype), templated over engine facts (`FACT_FIELDS`: the reason in the
  person's words, the promise, a follow-up, a topic), picked by
  `stable_rng(seed, ...)` keyed by the first due message's id -- a pure
  function of the snapshot. It proposes relationships.yaml `regard.fallback`,
  mood `neutral`, nothing learned or shared, no proposal, and keeps the
  agreement failures that led to it (`failures`, F9).

Rule 12: no prompt block, instruction row, correction line, schema
description or fallback here rates content; the register is `texter.md`'s
and the owner's model's.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from engine import social, yamlio
from engine.config import get_config
from engine.game.rng import SOCIAL_BEHAVIOUR, stable_rng
from engine.llm.schemas import conform, render_format_block, response_format
from engine.social import agreement, memory
from engine.social.kinds import MODES, Decision, decision_from_row
from engine.social.population import Person

logger = logging.getLogger(__name__)

__all__ = [
    "BLOCK_TITLES", "Decision", "FACT_FIELDS", "LLMFn", "PersonSnapshot", "SITUATIONS", "TexterCall", "TexterPrompt",
    "VoicedReply", "bubble_limit", "fallback_reply", "fallback_reply_for", "labels", "messages", "mode_caps",
    "one_line", "parse_texter", "production_llm_fn", "reply_schema", "situation_faults", "snapshot_of",
    "style_words", "texter_prompt", "voice", "window_for",
]

#: The voicer's model function: the messages and the `response_format` in, raw text out. One that also
#: takes `max_tokens=` says so with a true `takes_max_tokens` attribute (`TexterCall`).
LLMFn = Callable[[list[dict[str, Any]], dict[str, Any]], str]

#: The user message's eight titled blocks, in order (v0.23.0 spec §13.2 blocks 2-9, stable to volatile;
#: block 1, the persona, is the system message). Each is `f"{title}\n{body}"`, blocks joined by a blank line.
BLOCK_TITLES: tuple[str, ...] = (
    "WHO YOU ARE NOW", "YOUR STORY TOGETHER", "WHAT YOU KNOW ABOUT THEM", "STILL OPEN",
    "YOU AND THEM", "THIS CONVERSATION", "RIGHT NOW", "FORMAT",
)   # the persona is the system message, block 1

#: Every situation the ENGINE emits itself (messaging's openers, replies, double texts and answers;
#: engine/social/media.py's sends and declines; a game's banter; a meet-up's text after; their number
#: offer; v0.23.0: a kept promise, a window initiation, a layer opened up about); the story's own
#: (behaviours.yaml `instruction:`, an arc beat's) are cross-checked from its data. Each must be a row
#: of texter.md's instruction table (`situation_faults`).
SITUATIONS: tuple[str, ...] = ("opener", "reply", "double_text", "answer_request",
                               "send_selfie", "send_photo", "send_voice", "send_video",
                               "decline_photo", "decline_voice", "decline_video", "game_banter", "post_meet",
                               "offer_number",                 # v0.23.0 T5: their number offer (§15.2)
                               "promised_message", "window_message", "opens_up",   # v0.23.0 T7
                               "invite", "flake", "stood_up",                    # v0.23.0 T12: a plan (engine/social/plans.py)
                               "arrived",                                        # v0.23.0 T23C: they got to a plan's place first (plans.py)
                               "news")                                           # v0.23.0 T17: a life event of theirs (engine/social/life.py)

#: The instruction rows RIGHT NOW adds beside the situation's (v0.23.0 spec §13.1): how a conversation
#: ends (`Decision.end`, with `{reason}`) and a follow-up to raise. Each must be a row of the table.
ENGINE_ROWS: tuple[str, ...] = ("winding", "sign_off", "followup")

#: `Decision.end` -> the instruction row (and fallback key) that words it.
END_ROWS: tuple[tuple[str, str], ...] = (("winding", "winding"), ("sign_off", "sign_off"))

#: Situations retired as bare rows (v0.23.0 spec §4.7, §13.1) -> the row that voices a message still
#: due under the old name (a v0.22.0 save's): never a content fault.
RETIRED_ROWS: tuple[tuple[str, str], ...] = (("good_morning", "window_message"), ("check_in", "window_message"),
                                             ("late_night", "window_message"), ("reveal_turn", "opens_up"))

#: The engine facts an instruction row or a fallback line may name, as `{field}` (§13.1): the reason a
#: conversation ends (in the person's own words for a fallback), the promise (`promise_words`, a whole
#: sentence, may be empty; `promise_when`, its window's words), a follow-up's subject, a topic of theirs
#: and the player's name.
FACT_FIELDS: tuple[str, ...] = ("reason", "promise_words", "promise_when", "followup", "topic", "them")
#: Fields a fallback line may leave empty (the line is still used, the gap closed up).
OPTIONAL_FIELDS: tuple[str, ...] = ("promise_words",)

#: The fallbacks' key for a decline decision, tried before its situation's.
DECLINE_KEY = "decline"
#: The fallbacks' block for every archetype, keyed `situation.mode` (§13.1).
ANY_KEY = "any"
#: The fallbacks' block of reasons in the person's own words, keyed as conversation.yaml `reasons:`.
REASONS_KEY = "reasons"

#: The engine's own line when the story's fallbacks have none for the archetype.
FALLBACK_LINE = "hey"

#: The prompt file, in the story's `prompts/` directory.
TEXTER_FILE = "texter.md"

#: The response_format envelope's name.
SCHEMA_NAME = "texter_reply"

#: The schema's bounds (§11.2); the engine's per-reply clamp is relationships.yaml's, at commit.
#: BUBBLE_CHARS is `quick`'s bubble cap, used when the story's data has no `modes.caps`.
BUBBLE_CHARS = 280
FACT_CHARS = 140
CAPTION_CHARS = 200
FACTS_MAX = 2
PROPOSALS_MAX = 2
#: The schema's caps (§11.2); the bounds offered are these narrowed by relationships.yaml
#: `regard.per_reply` (`regard_bounds`), so a story that narrows a reply's move narrows the offer.
WARMTH_BOUNDS: tuple[int, int] = (-4, 4)
TRUST_BOUNDS: tuple[int, int] = (-2, 2)

#: A mode's caps when the story's data names none (v0.23.0 spec §4.5's `quick`).
DEFAULT_CAPS: dict[str, Any] = {"bubbles": [1, 2], "bubble_chars": 280, "max_tokens": 300}

#: The smallest prompt window a call is given, whatever its binding (`window_for`).
MIN_WINDOW = 1024

#: Tokens the window keeps back beyond the reply's cap, for the estimator's error and the message joins
#: (T7 review M6): `memory._estimate` is a heuristic, and a strict server refuses a prompt over its context.
WINDOW_MARGIN = 128

#: A reply's follow-ups (v0.23.0 spec §7.3): `when` is one of these, resolved by
#: `relationships.followup_due_at`; `about` at most `memory.ABOUT_CHARS`.
FOLLOWUP_DAYS = 7

#: The retry's one line after a reply that did not parse or held no words.
JSON_ONLY = "Reply with the JSON object only."

#: How many of the person's history rows the voice reads (§10.4).
HISTORY_ROWS = 8

#: A model reply's failure that is not an agreement check: it did not parse, or held no words.
UNPARSED = "unparsed"
EMPTY = "empty"

#: The one-line correction per check (engine words, naming only the fact the reply got wrong).
CORRECTIONS: dict[str, str] = {
    "media_claimed": "Your reply said something was sent (\"{detail}\"); nothing is attached to this "
                     "message. Rewrite it without saying so.",
    "media_denied": "Your reply said you would not send it (\"{detail}\"); it is attached to this message. "
                    "Rewrite it to go with what you are sending.",
    "stage_claimed": "Your reply said \"{detail}\", but the two of you are not there yet. Rewrite it "
                     "without saying so.",
    "profile_contradicted": "Your reply got a fact wrong ({detail}). Rewrite it with the facts given above.",
    "another_person": "Your reply named {detail}, someone you do not know. Rewrite it without naming them.",
    "number": "Your reply had {detail}. Rewrite it within that.",
    "decline_wording": "Your reply agreed (\"{detail}\"), but your answer is no. Rewrite it saying no, "
                       "your way.",
    "plan_claimed": "Your reply said \"{detail}\", but that is not what the two of you have planned. "
                       "Rewrite it to agree with your plans.",
    "promise_claimed": "Your reply said \"{detail}\", but that is not when you said you would message them. "
                       "Rewrite it with the time given above, or without promising one.",
    "commitment_claimed": "Your reply said \"{detail}\", but that step is not one the two of you are taking "
                          "now. Rewrite it without it.",
    "arrival_claimed": "Your reply said \"{detail}\", but you are still on your way. Rewrite it without saying "
                       "you are there.",
}
DEFAULT_CORRECTION = "Your reply did not match what has happened ({check}: {detail}). Rewrite it."

#: Situation-free words for a schedule status and an intent.
STATUS_WORDS: dict[str, str] = {"free": "free", "work": "at work", "out": "out", "asleep": "in bed"}
#: How a reply runs in each mode (spec §4.5): length and shape only.
MODE_WORDS: dict[str, str] = {
    "quick": "This is quick texting: a line or two.",
    "chatting": "You are properly talking now: write full messages, ask something back, and pick up what "
                "was said earlier.",
    "deep": "This is a real conversation: take your time, say what you think, and come back to things "
            "said earlier, today or weeks ago.",
}
#: What each §10.5 proposal asks for, in the FORMAT block's words.
PROPOSAL_WORDS: dict[str, str] = {
    "offer_number": "offer them your number", "ask_meet": "ask to meet them", "offer_photo": "offer a photo",
    "offer_voice": "offer a voice note", "offer_video": "offer a video", "invite_game": "invite them to a game",
    "ask_exclusive": "ask to be exclusive", "cool_off": "pull back for a while",
    "move_in": "ask them to move in together", "propose": "ask them to marry you",   # v0.23.0 T18 (§12.1)
}
#: The proposals carried by their own keys, never the `proposals` enum (v0.23.0 spec §7.3, §13.3).
OWN_KEY_PROPOSALS: tuple[str, ...] = ("promise", "followups")
INTENT_WORDS: dict[str, str] = {"long_term": "something long-term", "short_term": "something casual",
                                "friendship": "friendship", "unsure": "nothing settled yet"}
#: A disclosure rung (growth.RUNGS) in the words YOU AND THEM gives it (spec §6.1): topics, never a tier.
RUNG_WORDS: dict[str, str] = {"small_talk": "small talk", "everyday": "everyday life",
                              "personal_stories": "personal stories", "hopes_and_fears": "hopes and fears",
                              "family_and_future": "family and the future"}
#: A commitment that holds (agreement.willing_now) in YOU AND THEM's words.
COMMITMENT_WORDS: dict[str, str] = {"number": "swapping numbers", "meet": "meeting up",
                                    "come_over": "having them over", "exclusive": "being exclusive",
                                    "move_in": "moving in together", "propose": "getting engaged"}
#: The situations a layer they are ready to tell is voiced in (spec §6.4: "as situation `opens_up`").
REVEAL_SITUATIONS: tuple[str, ...] = ("reply", "window_message", "promised_message")
#: Words too common to show a follow-up was raised (`raised_followup`).
_PLAIN_WORDS = frozenset({"about", "after", "again", "been", "from", "going", "have", "just", "message",
                          "said", "that", "their", "them", "there", "they", "this", "what", "when", "will",
                          "with", "would", "your", "you'd", "you're"})


# -- the shared types ---------------------------------------------------------------------------


@dataclass
class PersonSnapshot:
    """Everything one voicing call reads, copied out of state under the turn lock (never the live state)."""

    pid: str
    thread_id: str
    profile: dict[str, Any]          # population.profile(...) as a dict (`Person(**profile)` rebuilds it)
    dynamic: dict[str, Any]          # deep copy of people[pid], rev included
    tail: list[dict[str, Any]]       # the last social.memory.verbatim voiced messages with them, any app (T6)
    summary: str                     # their story so far and the kept episodes' recaps (memory.story_lines, T6)
    due: list[dict[str, Any]]        # the due message rows (decision included), oldest first
    proposals: tuple[str, ...]       # §10.5 rows legal at snapshot
    player: dict[str, Any]           # the player's profile
    now: dict[str, Any]              # {day, hour, minute, weekday, status, at}
    contacts: tuple[str, ...]        # display names of everyone else with a thread (agreement: another person)
    seed: int                        # state.rng_seed: the fallback's stable_rng seed (pre-flight F9)
    plans: tuple[dict[str, Any], ...] = ()             # this person's plan rows (agreement: plan claimed; v0.23.0 T12)
    player_words: tuple[str, ...] = ()                 # every word the player wrote to them still in state
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)   # the requests the due decisions answer
    games: dict[str, str] = field(default_factory=dict)                 # game id -> the engine's line about it (T22)
    through_id: str = ""             # the newest message of THIS thread's tail: what this snapshot read up to (I6)
    memory: dict[str, Any] = field(default_factory=dict)                # memory.person(...): the person's memory (T6)
    # v0.23.0 T7 (spec §6.6, §13): who they are now, what holds, what is open, what they are ready to tell.
    who_now: str = ""                                  # growth.who_now in this decision's mode
    depth: int = 0                                     # their disclosure rung (growth.depth)
    willing: tuple[str, ...] = ()                      # agreement.willing_now: the commitments that hold
    promise_rows: tuple[tuple[str, str], ...] = ()     # agreement.promise_windows_of: (id, window)
    makes_promises: bool = True                        # agreement.makes_promises
    promise_windows: tuple[str, ...] = ()              # windows a promise may name now (agreement.promise_windows_now)
    promise_when: str = ""                             # the decision's promise, its window in words
    open_promises: tuple[str, ...] = ()                # STILL OPEN's promise lines, both sides
    followup: dict[str, Any] = field(default_factory=dict)   # the open row the decision's followup_id names
    followups_max: int = 0                             # follow-ups a reply may make now (0: the key is left out)
    reveal: dict[str, Any] = field(default_factory=dict)     # {id, kind, text}: a layer they are ready to tell
    topics: tuple[str, ...] = ()                       # topic labels at their rung and below (a fallback's {topic})
    reason_key: str = ""                               # the conversation.yaml `reasons:` key of the episode's end
    lives_together: bool = False                       # they live in the player's flat (the household, T18)
    after_together: bool = False                       # this text waited while you were together (W5)


@dataclass
class VoicedReply:
    pid: str
    thread_id: str
    message_ids: tuple[str, ...]
    bubbles: list[str]
    caption: str
    regard: dict[str, Any]           # {"warmth": int, "trust": int, "mood": str}
    learned: list[str]
    shared: list[str]
    proposals: list[str]
    fallback: bool
    failures: list[str]              # agreement failures recorded in receipts
    through_id: str = ""             # its snapshot's `through_id`: the commit asks whether the player spoke since
    # v0.23.0 T7 (spec §5.2, §6.4, §7.3): what the commit applies beside the words, each re-checked there.
    followups: list[dict[str, str]] = field(default_factory=list)   # [{about, when}], at most 2
    promise: dict[str, str] = field(default_factory=dict)           # {window, about}: route 3's proposal
    followup_raised: str = ""        # the follow-up (open row id) the words raised: closed at commit
    reveal: str = ""                 # the layer (layers.yaml id) the words opened up about: revealed at commit
    stated_promise: str = ""         # a window the words promise, none made by key (review I1): adopted at commit


@dataclass(frozen=True)
class TexterPrompt:
    """`texter.md`, parsed: the persona section, the instruction table, the fallbacks and the reasons in
    the person's own words."""

    persona: str
    instructions: dict[str, str]
    fallbacks: dict[str, dict[str, list[str]]]
    reasons: dict[str, str] = field(default_factory=dict)


# -- texter.md ------------------------------------------------------------------------------------

#: The active story's parsed texter.md. NULLED_ATTRIBUTES row; read once into a local.
_TEXTER_CACHE: Optional[TexterPrompt] = None

_INSTRUCTIONS = re.compile(r"^## Instructions[ \t]*$", re.MULTILINE)
_FALLBACKS = re.compile(r"^## Fallbacks[ \t]*$", re.MULTILINE)
_ROW = re.compile(r"^- `([a-z][a-z0-9_]*)`: (\S.*)$")
_FENCE = re.compile(r"^```yaml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_FIELD = re.compile(r"\{([a-z_]+)\}")


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: {TEXTER_FILE}: {key}: {message}")


def _fields(text: str) -> set[str]:
    return set(_FIELD.findall(str(text)))


def _fallback_key_fault(key: str, instructions: dict[str, str]) -> str:
    """Why a fallback key is not one ("" when it is): `decline`, a row, or `<row>.<mode>`."""
    if key == DECLINE_KEY:
        return ""
    row, _, mode = key.partition(".")
    if row not in instructions:
        return "is no row of ## Instructions (nor `decline`)"
    if _ and mode not in MODES:
        return f"{mode!r} is no mode ({', '.join(MODES)})"
    return ""


def parse_texter(text: str) -> TexterPrompt:
    """
    `texter.md`'s three parts (format pinned by v0.22.0's T2 step): the
    persona above `## Instructions`; that heading's `- \\`<id>\\`: <line>`
    bullets; one fenced `yaml` block under `## Fallbacks`: archetype ->
    situation (an instruction id, `<id>.<mode>` or `decline`) -> lines, plus
    `any:` (every archetype, the same keys) and `reasons:` (conversation.yaml
    `reasons:` key -> the reason in the person's own words). A row or line
    may name only `FACT_FIELDS`. A ValueError naming the key at fault.
    """
    head = _INSTRUCTIONS.search(text)
    if head is None:
        raise _fault("## Instructions", "missing")
    tail = _FALLBACKS.search(text, head.end())
    if tail is None:
        raise _fault("## Fallbacks", "missing")
    persona = text[:head.start()].rstrip()
    if not persona:
        raise _fault("persona", "the persona section above ## Instructions is empty")
    instructions: dict[str, str] = {}
    for line in text[head.end():tail.start()].splitlines():
        line = line.rstrip()
        if not line:
            continue
        row = _ROW.match(line)
        if row is None:
            raise _fault("## Instructions", f"not a `- \\`<id>\\`: <line>` row: {line[:60]!r}")
        if row.group(1) in instructions:
            raise _fault(f"## Instructions.{row.group(1)}", "listed twice")
        unknown = sorted(_fields(row.group(2)) - set(FACT_FIELDS))
        if unknown:
            raise _fault(f"## Instructions.{row.group(1)}", f"names {{{unknown[0]}}}, not one of {', '.join(FACT_FIELDS)}")
        instructions[row.group(1)] = row.group(2).strip()
    if not instructions:
        raise _fault("## Instructions", "no rows")
    fence = _FENCE.search(text, tail.end())
    if fence is None:
        raise _fault("## Fallbacks", "no ```yaml block")
    try:
        raw = yamlio.safe_load(fence.group(1))
    except Exception as exc:  # noqa: BLE001 -- re-raised as the load rule's ValueError
        raise _fault("## Fallbacks", f"does not parse: {exc}") from None
    if not isinstance(raw, dict):
        raise _fault("## Fallbacks", "must be a mapping of archetypes")
    reasons: dict[str, str] = {}
    said = raw.get(REASONS_KEY)
    if said is not None:
        if not isinstance(said, dict) or not all(isinstance(v, str) and v.strip() for v in said.values()):
            raise _fault(f"fallbacks.{REASONS_KEY}", "must map each reason key to the person's own words")
        reasons = {str(k): " ".join(str(v).split()) for k, v in said.items()}
    fallbacks: dict[str, dict[str, list[str]]] = {}
    for arch, rows in raw.items():
        if arch == REASONS_KEY:
            continue
        if not isinstance(rows, dict) or not rows:
            raise _fault(f"fallbacks.{arch}", "must be a mapping of situations")
        fallbacks[str(arch)] = {}
        for situation, lines in rows.items():
            why = _fallback_key_fault(str(situation), instructions)
            if why:
                raise _fault(f"fallbacks.{arch}.{situation}", why)
            if (not isinstance(lines, list) or not lines
                    or not all(isinstance(x, str) and x.strip() for x in lines)):
                raise _fault(f"fallbacks.{arch}.{situation}", "must be a list of non-empty lines")
            for x in lines:
                unknown = sorted(_fields(x) - set(FACT_FIELDS))
                if unknown:
                    raise _fault(f"fallbacks.{arch}.{situation}",
                                 f"names {{{unknown[0]}}}, not one of {', '.join(FACT_FIELDS)}")
            fallbacks[str(arch)][str(situation)] = [x.strip() for x in lines]
    return TexterPrompt(persona=persona, instructions=instructions, fallbacks=fallbacks, reasons=reasons)


def situation_faults(prompt: TexterPrompt, behaviours: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Every situation the engine or the story's data can emit that the
    instruction table lacks, and every fallback archetype behaviours.yaml
    does not declare, as (key, message): `SITUATIONS` and `ENGINE_ROWS`
    (v0.23.0: the end rows and the follow-up), each initiation's
    `instruction` (or its id, which messaging uses when it has none) and
    each arc beat's `instruction`.
    """
    table = prompt.instructions
    out = [(f"SITUATIONS.{s}", "the engine emits it; ## Instructions has no row for it")
           for s in SITUATIONS + ENGINE_ROWS if s not in table]
    archetypes = behaviours.get("archetypes") if isinstance(behaviours.get("archetypes"), dict) else {}
    for name, row in archetypes.items():
        for i, init in enumerate((row or {}).get("initiations") or [] if isinstance(row, dict) else []):
            if not isinstance(init, dict):
                continue
            situation = str(init.get("instruction") or init.get("id") or "")
            if situation and situation not in table:
                out.append((f"behaviours.yaml archetypes.{name}.initiations[{i}].instruction",
                            f"{situation!r} has no row in ## Instructions"))
    arcs = behaviours.get("arcs") if isinstance(behaviours.get("arcs"), dict) else {}
    for name, spec in arcs.items():
        beat = (spec or {}).get("beat") if isinstance(spec, dict) else None
        situation = str((beat or {}).get("instruction") or "") if isinstance(beat, dict) else ""
        if situation and situation not in table:
            out.append((f"behaviours.yaml arcs.{name}.beat.instruction", f"{situation!r} has no row in ## Instructions"))
    if archetypes:
        for arch in prompt.fallbacks:
            if arch != ANY_KEY and arch not in archetypes:
                out.append((f"fallbacks.{arch}", "is no behaviours.yaml archetype"))
    return out


def _texter_path() -> Optional[Any]:
    directory = social.social_dir()
    return None if directory is None else directory.parent.parent / "prompts" / TEXTER_FILE


def texter_prompt() -> TexterPrompt:
    """
    The active story's `texter.md`, parsed and cross-checked (cached; the
    WARMERS loader): an empty prompt for a story without `paths.social`, a
    ValueError when the file is missing or malformed, or when a situation
    the engine or the data emits has no row (`situation_faults`).
    """
    global _TEXTER_CACHE
    cached = _TEXTER_CACHE  # read once: a reset nulls it without a lock
    if cached is not None:
        return cached
    path = _texter_path()
    if path is None:
        loaded = TexterPrompt(persona="", instructions={}, fallbacks={})
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _fault("file", f"cannot be read ({exc})") from None
        loaded = parse_texter(text)
        faults = situation_faults(loaded, social.data("behaviours"))
        if faults:
            key, message = faults[0]
            raise _fault(key, message)
    _TEXTER_CACHE = loaded
    return loaded


def _row_id(situation: str) -> str:
    """The instruction row that voices ``situation``: itself, or a retired name's successor (`RETIRED_ROWS`)."""
    return dict(RETIRED_ROWS).get(situation, situation)


# -- modes and the window (spec §4.5, §7.4) ---------------------------------------------------------


def mode_caps(mode: str, *, degraded: bool = False) -> dict[str, Any]:
    """A mode's caps (conversation.yaml `modes.caps`): `bubbles` [min, max], `bubble_chars`, `max_tokens`.
    On a degraded binding, or with `modes.deep_as_chatting` set (spec §20.2's third latency lever), `deep`
    uses `chatting`'s (§7.4). An unknown mode reads `quick`'s."""
    modes = social.data("conversation").get("modes") or {}
    caps = modes.get("caps") or {}
    if mode == "deep" and (degraded or modes.get("deep_as_chatting") is True):
        mode = "chatting"
    return dict(caps.get(mode) or caps.get("quick") or DEFAULT_CAPS)


def window_for(usable_context: int, mode: str) -> tuple[int, bool]:
    """
    The voice prompt's token budget for one call: min(social.voice.window_tokens, the binding's usable
    context) minus the MODE's reply cap (MINOR 8) and `WINDOW_MARGIN`. `degraded` is True on a binding under the configured
    window (Plan decision 33; 6144 by default since v0.23.0 T9): deep uses chatting's caps, episodes keep 3, the story is
    cut to 120 words first.
    """
    ceiling = int(social.setting("voice.window_tokens", 6144))
    degraded = usable_context < ceiling          # the configured window, not a literal (pre-flight T7 note)
    caps = mode_caps(mode, degraded=degraded)
    return max(MIN_WINDOW, min(ceiling, int(usable_context)) - int(caps["max_tokens"]) - WINDOW_MARGIN), degraded


def bubble_limit(decision: Decision, *, degraded: bool = False) -> int:
    """The most bubbles this reply may send: the decision's own `max_bubbles`, held to its mode's cap."""
    high = int((mode_caps(decision.mode, degraded=degraded).get("bubbles") or [1, 2])[1])
    return max(1, min(int(decision.max_bubbles), high))


def _bubble_floor(decision: Decision, limit: int) -> int:
    return max(1, min(limit, int(decision.min_bubbles)))


def _configured_window() -> int:
    return int(social.setting("voice.window_tokens", 6144))


# -- the snapshot ---------------------------------------------------------------------------------


def _tail_rows(thread_id: str, voiced: list[dict[str, Any]], verbatim: int,
               directory: Any, archived: int = 0) -> list[dict[str, Any]]:
    """
    The thread's voiced rows the verbatim tail is cut from: state's, and, when state holds fewer bubbles
    than the tail reads, the newest archived ones before them (v0.23.0 T9 fix round 3, review M4). A save
    spills a thread's older messages out of state, so the voice's input must not depend on when the game
    saved: a tail read through the archive is the same one before and after a spill.
    """
    from engine.social import archive, messaging

    held = sum(max(1, len(m.get("bubbles") or ())) for m in voiced)
    if directory is None or archived <= 0 or held >= verbatim:
        return voiced              # nothing of this thread was ever spilled (`thread["archived"]`): no file read
    first = archive._number(voiced[0].get("id")) if voiced else -1
    older = archive.archived_before(directory, thread_id, first, verbatim - held, frozenset(str(m.get("id")) for m in voiced))
    kept = [m for m in reversed(older) if m.get("voiced") is not False and messaging.shown(m)]
    return kept + voiced


def snapshot_of(state: Any, thread_id: str, directory: Any = None) -> Optional[PersonSnapshot]:
    """
    One person's snapshot for ``thread_id`` (CALLER HOLDS the turn lock):
    deep copies only, so `voice` may run with the lock released. None when
    the thread is unknown or holds no due message of theirs. ``directory``
    is the run's save directory: a short thread tail is filled from its
    archive (`_tail_rows`).
    """
    from engine.social import behaviour, population, relationships

    slice_ = state.social or {}
    thread = (slice_.get("threads") or {}).get(thread_id)
    if thread is None:
        return None
    pid = str(thread["pid"])
    rows = list(thread.get("messages") or [])
    due = [copy.deepcopy(m) for m in rows if m.get("voiced") is False and m.get("from") == pid]
    if not due:
        return None
    from engine.social import life   # lazily: life imports this package's peers

    person = life.person_now(state, pid)            # the job they took since you met (T17); the seed's otherwise
    voiced = [m for m in rows if m.get("voiced") is not False and m.get("voiced") != "withdrawn"]
    verbatim = max(1, int(social.setting("memory.verbatim", 40)))
    _older, own = memory.split_tail(voiced, verbatim)
    through = str(own[-1].get("id") or "") if own else ""
    _older, own = memory.split_tail(_tail_rows(thread_id, voiced, verbatim, directory, int(thread.get("archived") or 0)), verbatim)
    remembered = memory.person(state, pid)
    # The conversation with them whatever the app (spec §7.1, §15.5): this thread's tail, with what
    # their memory holds from their other threads (the bridge and the open episode), oldest first.
    mine = {str(m.get("id")) for m in own}
    elsewhere = [m for m in remembered["bridge"] + remembered["current"]
                 if m.get("thread_id") != thread_id and str(m.get("id")) not in mine]
    merged = sorted({str(m.get("id")): m for m in elsewhere + own}.values(), key=lambda m: float(m.get("at", 0.0)))
    _older, tail = memory.split_tail(merged, verbatim)
    requests = slice_.get("requests") or {}
    wanted = {str((m.get("decision") or {}).get("request_id") or "") for m in due} - {""}
    played = sorted({str((m.get("decision") or {}).get("game_id") or "") for m in due} - {""})
    notes: dict[str, str] = {}
    if played:
        from engine.social import games   # lazily: games imports messaging, which this module's package loads

        notes = {gid: games.banter_note(state, gid) for gid in played}
    at = float(state.world_clock_hours)
    total = int(round(at * 60))                    # one rounding, so 31.9999 is 08:00, never 07:00
    decision = decision_from_row((due[0].get("decision") or {}), where=f"snapshot:{due[0].get('id', '')}")
    snap = PersonSnapshot(
        pid=pid, thread_id=thread_id, profile=dataclasses.asdict(person),
        # One copy of the memory (review M6): `memory` below; `dynamic` is the rest of their row.
        dynamic={k: copy.deepcopy(v) for k, v in ((slice_.get("people") or {}).get(pid) or {}).items()
                 if k != "memory"},
        tail=copy.deepcopy(tail), summary=memory.story_lines(remembered), due=due,
        proposals=tuple(relationships.legal_proposals(state, pid)),
        player=copy.deepcopy(slice_.get("player") or {}),
        now={"day": int(state.world_day), "hour": (total // 60) % 24, "minute": total % 60,
             "weekday": behaviour.weekday_of(at), "status": behaviour.status_at(person, at), "at": at},
        contacts=tuple(agreement.contact_names(state, pid)), seed=int(state.rng_seed),
        plans=agreement.plans_of(state, pid), player_words=tuple(sorted(agreement.said_to(state, pid))),
        requests={rid: copy.deepcopy(requests[rid]) for rid in sorted(wanted) if rid in requests},
        games={gid: note for gid, note in notes.items() if note},
        through_id=through,
        memory=remembered,
    )
    return dataclasses.replace(snap, **_growth_view(state, pid, decision, remembered, at))


def _growth_view(state: Any, pid: str, decision: Decision, remembered: dict[str, Any],
                 at: float) -> dict[str, Any]:
    """The v0.23.0 parts of a snapshot (T7): who they are now, what holds, their promises, the follow-up
    the decision raises, a layer they are ready to tell, their topics, why the conversation ends. Reads."""
    from engine.social import growth, promises, relationships

    depth = growth.depth(state, pid)
    promise_rows = agreement.promise_windows_of(state, pid)
    makes = agreement.makes_promises(state, pid)
    rows = (state.social or {}).get("promises") or {}
    own = rows.get(decision.promise_id) if decision.promise_id else None
    followup = next((dict(r) for r in remembered.get("open") or () if decision.followup_id
                     and str(r.get("id")) == decision.followup_id), {})
    episode = (((state.social or {}).get("people") or {}).get(pid) or {}).get("episode") or {}
    return {
        "who_now": growth.who_now(state, pid, in_episode_mode=decision.mode),
        "lives_together": relationships.household(state) == pid,
        "after_together": bool(decision.after_together),
        "depth": depth,
        "willing": tuple(sorted(agreement.willing_now(state, pid))),
        "promise_rows": promise_rows,
        "makes_promises": makes,
        "promise_windows": agreement.promise_windows_now(state, pid),
        "promise_when": promises.window_words(own, speaker="person", now=at) if own else "",
        "open_promises": tuple(_promise_line(r, at) for r in promises.open_by(state, pid)),
        "followup": followup,
        "followups_max": relationships.followups_allowed(state, pid),
        "reveal": _reveal_row(state, pid, decision),
        "topics": tuple(str(r["label"]) for r in growth.topics_of(state, pid, up_to=depth)),
        "reason_key": str(episode.get("end_key") or "") if decision.end != "none" else "",
    }


def _promise_line(row: dict[str, Any], at: float) -> str:
    from engine.social import promises

    words = promises.window_words(row, speaker=str(row.get("by") or ""), now=at)
    about = f" ({one_line(row['about'])})" if row.get("about") else ""
    if row.get("by") == "person":
        return f"You said you'd message them {words}{about}."
    return f"They said they'd message you {words}{about}."


def _reveal_row(state: Any, pid: str, decision: Decision) -> dict[str, Any]:
    """The layer they are ready to tell (growth's `reveal_due`, spec §6.4), when this decision can carry it:
    a reply, a window message or a kept promise, not ending, with nothing attached. {} otherwise."""
    from engine.social import growth

    if (_row_id(decision.situation) not in REVEAL_SITUATIONS or decision.end != "none"
            or decision.media_kind or decision.kind == "decline" or decision.reveal):
        return {}
    layer = str(growth.record(state, pid).get("reveal_due") or "")
    row = next((r for r in social.data("layers").get("layers") or [] if str(r.get("id")) == layer), None)
    if not layer or row is None:
        return {}
    return {"id": layer, "kind": str(row.get("kind") or ""), "text": one_line(row.get("text"))}


def person_of(snap: PersonSnapshot) -> Person:
    """The snapshot's `Person`, rebuilt from its dict."""
    return Person(**snap.profile)


def _decision(snap: PersonSnapshot) -> Decision:
    """The first due message's `Decision` (one call voices one person's whole due burst)."""
    row = (snap.due[0].get("decision") if snap.due else None) or {}
    return decision_from_row(row, where=f"voicing:{snap.due[0].get('id', '') if snap.due else ''}")


def _moods() -> tuple[str, ...]:
    from engine.social import relationships

    return tuple(str(m) for m in (social.data("relationships").get("mood") or {}).get("values")
                 or (relationships.NEUTRAL,))


# -- the schema (§13.3) ---------------------------------------------------------------------------


def regard_bounds() -> tuple[tuple[int, int], tuple[int, int]]:
    """(warmth, trust) bounds a reply may propose: the schema's caps intersected with relationships.yaml
    `regard.per_reply` (the commit's own clamp, T9), so the model is never offered a move it cannot make."""
    per_reply = (social.data("relationships").get("regard") or {}).get("per_reply") or {}

    def narrowed(cap: tuple[int, int], row: Any) -> tuple[int, int]:
        if not (isinstance(row, (list, tuple)) and len(row) == 2):
            return cap
        low, high = max(cap[0], int(row[0])), min(cap[1], int(row[1]))
        return (low, high) if low <= high else cap

    return narrowed(WARMTH_BOUNDS, per_reply.get("warmth")), narrowed(TRUST_BOUNDS, per_reply.get("trust"))


def followup_whens() -> tuple[str, ...]:
    """A follow-up's `when` enum (spec §7.3): `tomorrow`, `days:1`-`days:7`, `after:<window>` for each
    initiation window (engine/social/windows.py), all resolved by `relationships.followup_due_at`."""
    from engine.social import windows

    return (("tomorrow",) + tuple(f"days:{n}" for n in range(1, FOLLOWUP_DAYS + 1))
            + tuple(f"after:{w}" for w in windows.INITIATION_WINDOWS))


def reply_schema(decision: Decision, proposals: tuple[str, ...], moods: tuple[str, ...], *,
                 promise_windows: Sequence[str] = (), followups: int = 0, degraded: bool = False,
                 followup_asked: bool = False, opened_up: bool = False) -> dict[str, Any]:
    """The reply's JSON schema for one call (§13.3): the mode's bubble count and length, media only when
    attached, proposals only when legal (`promise` and `followups` by their own keys, never the enum),
    regard inside `regard_bounds`, `followups` when ``followups`` > 0, `promise` only while the
    conversation is winding or signing off and ``promise_windows`` names a window, and the two facts the
    reply states about itself (T7 fix round 1, review I2, M7): `followup_asked` when a follow-up was
    raised to it, `opened_up` when a layer was offered -- the commit acts on true alone."""
    warmth, trust = regard_bounds()
    caps = mode_caps(decision.mode, degraded=degraded)
    props: dict[str, Any] = {
        "bubbles": {"type": "array", "minItems": 1, "maxItems": bubble_limit(decision, degraded=degraded),
                    "items": {"type": "object", "additionalProperties": False,
                              "properties": {"text": {"type": "string",
                                                      "maxLength": int(caps.get("bubble_chars", BUBBLE_CHARS))}},
                              "required": ["text"]}},
        "regard": {"type": "object", "additionalProperties": False,
                   "properties": {"warmth": {"type": "integer", "minimum": warmth[0], "maximum": warmth[1]},
                                  "trust": {"type": "integer", "minimum": trust[0], "maximum": trust[1]},
                                  "mood": {"type": "string", "enum": list(moods)}},
                   "required": ["warmth", "trust", "mood"]},
        "learned": {"type": "array", "maxItems": FACTS_MAX,
                    "items": {"type": "string", "maxLength": FACT_CHARS}},
        "shared": {"type": "array", "maxItems": FACTS_MAX,
                   "items": {"type": "string", "maxLength": FACT_CHARS}},
    }
    required = ["bubbles", "regard", "learned", "shared"]
    enum = [name for name in proposals if name not in OWN_KEY_PROPOSALS]
    if enum:
        props["proposals"] = {"type": "array", "maxItems": PROPOSALS_MAX,
                              "items": {"type": "string", "enum": enum}}
        required.append("proposals")
    if followups > 0:
        props["followups"] = {"type": "array", "maxItems": min(int(followups), _followups_cap()),
                              "items": {"type": "object", "additionalProperties": False,
                                        "properties": {"about": {"type": "string", "maxLength": memory.ABOUT_CHARS},
                                                       "when": {"type": "string", "enum": list(followup_whens())}},
                                        "required": ["about", "when"]}}
        required.append("followups")
    if decision.end in ("winding", "sign_off") and not decision.promise_id and promise_windows:
        props["promise"] = {"type": "array", "maxItems": 1,
                            "items": {"type": "object", "additionalProperties": False,
                                      "properties": {"window": {"type": "string", "enum": list(promise_windows)},
                                                     "about": {"type": "string", "maxLength": memory.ABOUT_CHARS}},
                                      "required": ["window", "about"]}}
        required.append("promise")
    if followup_asked:
        props["followup_asked"] = {"type": "boolean"}
        required.append("followup_asked")
    if opened_up:
        props["opened_up"] = {"type": "boolean"}
        required.append("opened_up")
    if decision.media_kind:
        cap = int(get_config().get("tts.max_chars", 400)) if decision.media_kind == "voice" else CAPTION_CHARS
        props["media"] = {"type": "object", "additionalProperties": False,
                          "properties": {"caption": {"type": "string", "maxLength": cap}},
                          "required": ["caption"]}
        required.append("media")
    return {"type": "object", "additionalProperties": False, "properties": props, "required": required}


def _followups_cap() -> int:
    from engine.social import relationships

    return relationships.FOLLOWUPS_MAX


def _schema_for(snap: PersonSnapshot, decision: Decision, moods: tuple[str, ...], *, degraded: bool) -> dict[str, Any]:
    return reply_schema(decision, snap.proposals, moods, promise_windows=snap.promise_windows,
                        followups=snap.followups_max, degraded=degraded,
                        followup_asked=bool(snap.followup), opened_up=bool(snap.reveal))


def _envelope(schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": SCHEMA_NAME, "strict": True, "schema": schema}


# -- the prompt (§13.2) ---------------------------------------------------------------------------


def _label(table: str, row_id: str) -> str:
    from engine.social import population

    for row in population.table(table):
        if isinstance(row, dict) and str(row.get("id")) == str(row_id):
            return str(row.get("label") or row_id)
    return str(row_id).replace("_", " ")


def labels(table: str, ids: Sequence[str]) -> str:
    """population.yaml `table`'s labels for ``ids``, in a sentence ("climbing, cooking and the sea")."""
    from engine.social import population

    return ", ".join(population.in_sentence(_label(table, i)) for i in ids)


def style_words(style_id: str, *, length: str = "") -> str:
    """A texting style row as a description (character notes, never rules: spec §4.3). ``length``,
    when given, reads in place of the row's (v0.23.0 spec §6.6: `growth.who_now`'s opened short texter)."""
    from engine.social import population

    row = next((r for r in population.table("texting_styles") if isinstance(r, dict) and r.get("id") == style_id),
               None)
    if row is None:
        return ""
    parts = [{"short": "short messages", "medium": "medium-length messages",
              "long": "long, full messages"}.get(length or str(row.get("length")), "messages")]
    caps = {"lower": "all in lower case", "sentence": "with ordinary capitals",
            "mixed": "with capitals wherever they land"}.get(str(row.get("caps")))
    if caps:
        parts.append(caps)
    punct = {"light": "light on punctuation", "full": "with full punctuation", "none": "with no punctuation",
             "ellipses": "trailing off in ellipses", "exclamations": "with plenty of exclamation marks"}.get(
        str(row.get("punctuation")))
    if punct:
        parts.append(punct)
    emoji = float(row.get("emoji") or 0)
    parts.append("lots of emoji" if emoji >= 0.5 else "some emoji" if emoji >= 0.2
                 else "the odd emoji" if emoji > 0 else "no emoji")
    questions = float(row.get("questions") or 0)
    if questions >= 0.6:
        parts.append("asking a lot of questions")
    elif questions <= 0.2:
        parts.append("rarely asking questions")
    humour = str(row.get("humour") or "")
    tail = f"; your humour is {humour}" if humour else ""
    return "You text in " + ", ".join(parts) + tail + "."


def one_line(text: Any) -> str:
    """``text`` on one line, its whitespace collapsed."""
    return " ".join(str(text or "").split())


def _part(snap: PersonSnapshot, key: str) -> Any:
    """One part of the person's memory (T6): the snapshot's copy, else the person row's (v0.22 places)."""
    return snap.memory[key] if key in snap.memory else memory.part(snap.dynamic, key)


def _who_now(snap: PersonSnapshot) -> str:
    """Block WHO YOU ARE NOW: `growth.who_now`, read at the snapshot (a hand-built one may carry none)."""
    if snap.who_now.strip():
        return snap.who_now
    p = snap.profile
    return f"You are {p.get('name')}, {p.get('age')}."


def _canon(snap: PersonSnapshot) -> str:
    return "\n".join(f"- {one_line(f)}" for f in _part(snap, "canon") or () if str(f).strip())


def _them(snap: PersonSnapshot) -> str:
    return str(snap.player.get("name") or "them")


def _story(snap: PersonSnapshot) -> str:
    return one_line(_part(snap, "story") or "")


def _episodes(snap: PersonSnapshot) -> str:
    rows = [e for e in _part(snap, "episodes") or () if isinstance(e, dict) and str(e.get("recap") or "").strip()]
    return "\n".join(f"{memory.stamp(e.get('to_at'))}: {one_line(e.get('recap'))}" for e in rows)


def _you_and_them(snap: PersonSnapshot) -> str:
    from engine.social import growth, relationships

    stage = str(snap.dynamic.get("stage") or "matched")
    mood = relationships.mood_now(snap.dynamic, float(snap.now.get("at", 0.0)))
    rung = growth.RUNG_IDS[max(0, min(len(growth.RUNG_IDS) - 1, int(snap.depth)))]
    ready = [COMMITMENT_WORDS.get(c, c.replace("_", " ")) for c in growth.PHONE_COMMITMENTS if c in snap.willing]
    lines = [f"Where things stand: {relationships.stage_words(stage)}.",
             *(["You live together, in their flat."] if snap.lives_together else []),   # the household (T18)
             *(["You were just together; this is the first you have texted since you parted."]
               if snap.after_together else []),                                         # a held text (W5)
             f"How close you feel: {relationships.band(snap.dynamic)}.",
             f"How much you share with them: {RUNG_WORDS.get(rung, rung.replace('_', ' '))}.",
             f"Your mood: {mood}.",
             f"What you want: {INTENT_WORDS.get(str(snap.profile.get('intent')), 'nothing settled yet')}.",
             f"What you think they want: "
             f"{INTENT_WORDS.get(str(snap.player.get('looking_for')), 'nothing settled yet')}.",
             f"What you would be up for with them now: {', '.join(ready)}." if ready
             else "What you would be up for with them now: nothing more yet."]
    return "\n".join(lines)


def _history(snap: PersonSnapshot) -> str:
    rows = [r for r in _part(snap, "history") or () if isinstance(r, dict) and str(r.get("text") or "").strip()]
    rows = [memory.full_history(r) if r.get("day") is None else r for r in rows]
    return "\n".join(f"Day {r.get('day')}: {one_line(r.get('text'))}" for r in rows[-HISTORY_ROWS:])


def _knows(snap: PersonSnapshot) -> str:
    pl = snap.player
    attributes = pl.get("attributes") or {}
    from engine.social import population

    lines = [f"Their profile: {pl.get('name') or 'them'}, {pl.get('age')}"
             + (f", {population.in_sentence(_label('jobs', str(attributes['job'])))}" if attributes.get("job") else "")
             + (f", living in {_label('neighbourhoods', str(pl['neighbourhood']))}" if pl.get("neighbourhood") else "")
             + "."]
    if pl.get("hobbies"):
        lines.append(f"They are into {labels('hobbies', list(pl['hobbies']))}.")
    lines.append(f"They are looking for {INTENT_WORDS.get(str(pl.get('looking_for')), 'nothing settled yet')}.")
    knows = [f"- {one_line(f)}" for f in _part(snap, "knows") or () if str(f).strip()]
    if knows:
        lines.append("What they have told you:")
        lines.extend(knows)
    return "\n".join(lines)


def _still_open(snap: PersonSnapshot) -> str:
    """Block STILL OPEN (spec §13.2 block 5): promises both ways and follow-ups (plans join with T12)."""
    at = float(snap.now.get("at", 0.0))
    lines = list(snap.open_promises)
    for row in _part(snap, "open") or ():
        if not isinstance(row, dict) or row.get("kind") != "followup" or not str(row.get("about") or "").strip():
            continue
        due = row.get("due_at")
        when = "now" if due is not None and float(due) <= at + 1e-9 else "later"
        lines.append(f"To ask them about ({when}): {one_line(row['about'])}")
    return "\n".join(lines) or "Nothing is open between you."


def _message_lines(snap: PersonSnapshot, rows: Sequence[dict[str, Any]]) -> list[str]:
    them = _them(snap)
    lines: list[str] = []
    for message in rows:
        if message.get("voiced") is False or message.get("from") == "system":
            continue
        who = "you" if message.get("from") == snap.pid else them
        lines.extend(f"{memory.stamp(message.get('at'))} {who}: {one_line(w)}"
                     for w in memory.message_words(message))
    return lines


def _bridge_ids(snap: PersonSnapshot) -> set[str]:
    return {str(m.get("id")) for m in _part(snap, "bridge") or () if isinstance(m, dict)}


def _bridge(snap: PersonSnapshot) -> str:
    return "\n".join(_message_lines(snap, [m for m in _part(snap, "bridge") or () if isinstance(m, dict)]))


def _current(snap: PersonSnapshot) -> str:
    gone = _bridge_ids(snap)
    return "\n".join(_message_lines(snap, [m for m in snap.tail if str(m.get("id")) not in gone]))


def _conversation_lines(snap: PersonSnapshot) -> str:
    """The whole tail the snapshot read, one line per bubble ("Tue 21:14 you: ...")."""
    return "\n".join(_message_lines(snap, snap.tail))


def _ago(hours: float) -> str:
    minutes = max(0, int(round(hours * 60)))
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    if minutes < 48 * 60:
        h = minutes // 60
        return f"{h} hour{'s' if h != 1 else ''}"
    d = minutes // (24 * 60)
    return f"{d} days"


def _fill(template: str, facts: dict[str, str]) -> str:
    """``template`` with each `{field}` of `FACT_FIELDS` replaced by its fact ("" when none), tidied."""
    text = _FIELD.sub(lambda m: str(facts.get(m.group(1), "")) if m.group(1) in FACT_FIELDS else m.group(0),
                      template)
    text = re.sub(r"\s+([.,;:!?])", r"\1", " ".join(text.split()))
    return re.sub(r"(?<!\.)([.!?])\.(?!\.)", r"\1", text).strip()   # "word.." closed up; "..." kept


def _facts(snap: PersonSnapshot, decision: Decision, texter: TexterPrompt) -> dict[str, str]:
    """The engine facts an instruction row or a fallback line may name (`FACT_FIELDS`), and `reason_said`:
    the reason in the person's own words (texter.md's fallback `reasons:`), which a fallback says."""
    when = snap.promise_when
    said = texter.reasons.get(snap.reason_key, "") if snap.reason_key else ""
    return {"reason": decision.reason, "reason_said": said,
            "promise_words": f"I'll message you {when}." if when and decision.end == "sign_off" else "",
            "promise_when": when, "followup": one_line(snap.followup.get("about")) if snap.followup else "",
            "topic": "", "them": str(snap.player.get("name") or "")}


def _row(texter: TexterPrompt, name: str) -> str:
    row = texter.instructions.get(_row_id(name))
    if row is None:   # a content fault: `voice` falls back on it, logged at ERROR
        raise ValueError(f"social: {TEXTER_FILE}: ## Instructions: no row for situation {name!r}")
    return row


def _clock_words(at: float) -> str:
    total = int(round(float(at) * 60))
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def whereabouts(row: dict[str, Any], at: Any) -> str:
    """Where they are for an open `now` / `tonight` plan, from the SNAPSHOT's copy of its row (A4 W4, I5): "You are
    on your way to The Anchor." between its `due_at` and `arrives_at`, "You are at The Anchor, waiting for them
    since 19:40." once `arrived`. "" before it is due, for a `soon` plan, or a row with no arrival fields. Never
    reads live state."""
    if row.get("when") == "soon" or "arrives_at" not in row or at is None:
        return ""
    from engine.social import places   # lazily: places reads the story's data, as this module does

    kind = str(row.get("kind") or "")
    place = ("their place" if kind == "your_place" else "home" if kind == "their_place"
             else places.label(str(row.get("venue") or "")))
    now = float(at)
    if row.get("arrived"):
        if kind == "their_place":
            return "You are at home, expecting them."
        return f"You are at {place}, waiting for them since {_clock_words(float(row['arrives_at']))}."
    if now >= float(row.get("due_at", row["arrives_at"])) and kind != "their_place":
        return f"You are on your way to {place}."
    return ""


def _right_now(snap: PersonSnapshot, texter: TexterPrompt, *, degraded: bool = False) -> str:
    decision = _decision(snap)
    facts = _facts(snap, decision, texter)
    now = snap.now
    at = float(now.get("at", 0.0))
    lines = [f"It is {str(now.get('weekday', '')).title()} {int(now.get('hour', 0)):02d}:"
             f"{int(now.get('minute', 0)):02d}, day {now.get('day')}. You are "
             f"{STATUS_WORDS.get(str(now.get('status')), 'free')}."]
    spoken = [m for m in snap.tail if m.get("from") in ("player", snap.pid)]
    theirs = [m for m in spoken if m.get("from") == "player"]
    mine = [m for m in spoken if m.get("from") == snap.pid]
    if theirs:
        lines.append(f"They last wrote {_ago(at - float(theirs[-1].get('at', at)))} ago"
                     + (", and you have read it." if theirs[-1].get("read_at") is not None else "."))
    if mine:
        lines.append(f"You last wrote {_ago(at - float(mine[-1].get('at', at)))} ago"
                     + (", and they have read it." if mine[-1].get("read_at") is not None
                        else ", and they have not opened it yet."))
    if not spoken:
        lines.append("Nobody has written yet.")
    if decision.media_kind:
        from engine.social import media   # lazily: media imports this module's package

        subject = media.subject_label(decision.subject) if decision.subject else ""
        lines.append(f"You are sending a {decision.media_kind} with this message" + (f": {subject}." if subject else "."))
    if decision.reveal:
        from engine.social import behaviour

        lines.append(f"What has changed: {one_line(behaviour.canon_text(decision.reveal))} Tell them now.")
    if decision.request_id:
        request = snap.requests.get(decision.request_id) or {}
        what = str(request.get("what") or "something").replace("_", " ")
        answer = "no" if decision.kind == "decline" else "yes"
        from engine.social import relationships   # lazily: relationships imports this package's peers

        if decision.kind == "decline" and request.get("why") in relationships.NOT_YET_WHYS:
            answer = "not yet, it's too early"           # the gate, not the odds (owner bug, v0.22.0)
        elif decision.kind == "decline" and request.get("why") == "not_tonight":
            answer = "not then, the time doesn't suit you"   # a plan's time, not the odds (v0.23.0 T12)
        if decision.situation == "invite":                # their own ask: no answer yet
            from engine.social import plans   # lazily: plans imports this module's package

            lines.append("You are asking them to meet up: "
                         f"{plans.words(str(request.get('kind') or ''), str(request.get('venue') or ''), str(request.get('when') or ''))}.")
        else:
            asked = "They asked to meet up." if what == "meet" else f"They asked for your {what}."
            lines.append(f"{asked} Your answer: {answer}.")
    if snap.plans:
        from engine.social import plans   # lazily: plans imports this module's package

        kept = [m for m in snap.plans if m.get("status") == "open"]
        if kept:
            lines.append(f"Your plans with them: {plans.row_words(kept[0])}.")
            for row in kept:                             # every open plan's whereabouts (fix round 1, M2)
                where = whereabouts(row, snap.now.get("at"))
                if where and where not in lines:
                    lines.append(where)
        named = next((m for m in snap.plans if decision.plan_id and m.get("id") == decision.plan_id), None)
        if named is not None:
            lines.append(f"The plan: {plans.row_words(named)}.")
            if named.get("band"):                       # a scene's end (v0.23.0 T13): how it went, in engine words
                from engine.social import scene

                lines.append(f"How it went: {scene.recap_line(str(named['band']))}")
    if decision.game_id and snap.games.get(decision.game_id):
        lines.append(f"The game: {one_line(snap.games[decision.game_id])}")
    lines.append(f"How the conversation is going: {MODE_WORDS.get(decision.mode, MODE_WORDS['quick'])}")
    if decision.end == "none" and decision.reason:
        lines.append(f"On your mind: {one_line(decision.reason)}.")
    if snap.followup:                                   # ending too: its reply says outright (re-review I2)
        lines.append(f"FOLLOW-UP: {_fill(_row(texter, 'followup'), facts)}")
    if snap.reveal:
        lines.append(f"OPENING UP: {_fill(_row(texter, 'opens_up'), facts)} What you tell them: {snap.reveal['text']}.")
    if decision.promise_id and facts["promise_when"] and _row_id(decision.situation) != "promised_message":
        lines.append(f"Your promise: you will message them {facts['promise_when']}. Say so, your way.")
    limit = bubble_limit(decision, degraded=degraded)
    low = _bubble_floor(decision, limit)
    count = f"{low}-{limit} messages" if low < limit else f"{limit} message{'s' if limit != 1 else ''}"
    lines.append(f"Send {count}.")
    end_row = dict(END_ROWS).get(decision.end)
    if end_row:
        lines.append(f"ENDING: {_fill(_row(texter, end_row), facts)}")
    lines.append(f"SITUATION: {_fill(_row(texter, decision.situation), facts)}")
    return "\n".join(lines)


def _format_note(snap: PersonSnapshot, decision: Decision) -> str:
    """What each key of the reply is for (engine words about the envelope, never about register)."""
    lines = ["How to fill it in: `bubbles` are your messages, in order. `regard` is how this exchange moved "
             "how you feel about them (warmth and trust, up or down) and your mood now. `learned` holds new "
             "facts they told you about themselves; `shared` holds facts about yourself you told them in this "
             "reply. Leave a list empty when there is nothing for it."]
    enum = [name for name in snap.proposals if name not in OWN_KEY_PROPOSALS]
    if enum:
        asks = "; ".join(f"{name} ({PROPOSAL_WORDS.get(name, name.replace('_', ' '))})" for name in enum)
        lines.append(f"`proposals` may ask for: {asks}. Leave it empty unless you mean it.")
    if getattr(snap, "followups_max", 0):
        lines.append("`followups` are things they told you about that you will ask after later (an interview, "
                     "a trip): `about` in a few words from your side, as you would ask \"How did ___ go?\" "
                     "(\"your interview\"), `when` when to ask. Leave it empty when there is none.")
    if getattr(snap, "followup", None):
        lines.append("`followup_asked` is true if your messages ask about the follow-up above, else false.")
    if getattr(snap, "reveal", None):
        lines.append("`opened_up` is true if your messages tell them what is under OPENING UP, else false.")
    if getattr(snap, "promise_windows", ()) and decision.end in ("winding", "sign_off") and not decision.promise_id:
        lines.append("`promise` is when you say you will message them next, if you say so in your messages; "
                     "leave it empty if you do not.")
    if decision.media_kind == "voice":
        from engine.social import media   # lazily: media imports this module's package

        lines.append("`media.caption` is the transcript of the voice note you are sending: the words you say "
                     f"in it, at most {media.voice_max_words()} words.")
    elif decision.media_kind:
        lines.append(f"`media.caption` is the caption on the {decision.media_kind} you are sending.")
    return "\n".join(lines)


def _flat(text: str) -> str:
    """A block body with no blank line inside it (the user message's blocks part on blank lines)."""
    return re.sub(r"\n\s*\n+", "\n", str(text)).strip("\n")


def messages(snap: PersonSnapshot, *, usable_context: Optional[int] = None) -> list[dict[str, str]]:
    """
    The system message (the persona) and the user message of exactly the eight `BLOCK_TITLES` blocks, in
    order (spec §13.2, pinned by test_the_voice_prompt_is_exactly_its_blocks), trimmed to this call's
    window (`window_for`, §7.4). ``usable_context`` is the binding's usable context (`voice` reads it from
    the production binding, `TexterCall.usable_context`); None reads the configured window, not degraded.
    """
    texter = texter_prompt()
    decision = _decision(snap)
    _row(texter, decision.situation)
    window, degraded = window_for(int(usable_context or _configured_window()), decision.mode)
    fixed_now = _flat(_right_now(snap, texter, degraded=degraded))
    schema = _schema_for(snap, decision, _moods(), degraded=degraded)
    fmt = _flat(_format_note(snap, decision) + "\n" + render_format_block(schema))
    parts = memory.budgeted({
        "persona": texter.persona, "who_now": _flat(_who_now(snap)), "story": _story(snap),
        "episodes": _flat(_episodes(snap)), "knows": _flat(_knows(snap)), "open": _flat(_still_open(snap)),
        "you_and_them": _flat(_you_and_them(snap)), "canon": _flat(_canon(snap)), "history": _flat(_history(snap)),
        "bridge": _flat(_bridge(snap)), "current": _flat(_current(snap)), "now": fixed_now, "format": fmt,
    }, window, degraded=degraded)
    them = _them(snap)
    story = "\n".join(filter(None, [parts["story"], parts["episodes"]]))
    together = (f"(Told from {them}'s side: \"you\" in it means {them}, \"they\" means you.)\n{story}" if story
                else "Nothing yet: this is the start of it.")
    you_and_them = "\n".join(filter(None, [
        parts["you_and_them"],
        f"What you have told them about yourself:\n{parts['canon']}" if parts["canon"] else "",
        f"What has happened between you:\n{parts['history']}" if parts["history"] else ""]))
    conversation = "\n".join(filter(None, [
        f"How you left it last time:\n{parts['bridge']}" if parts["bridge"] else "",
        (f"Now:\n{parts['current']}" if parts["bridge"] else parts["current"]) if parts["current"] else "",
    ])) or "No messages yet."
    bodies = (parts["who_now"], together, parts["knows"], parts["open"], you_and_them, conversation,
              parts["now"], parts["format"])
    user = "\n\n".join(f"{title}\n{body}" for title, body in zip(BLOCK_TITLES, bodies))
    return [{"role": "system", "content": texter.persona}, {"role": "user", "content": user}]


# -- the reply, held -------------------------------------------------------------------------------


def _parse(raw: Any) -> Optional[dict[str, Any]]:
    from engine.agents.json_stream import extract_json

    if not isinstance(raw, str) or not raw.strip():
        return None
    parsed = extract_json(raw)
    return parsed if isinstance(parsed, dict) else None


def _int_in(value: Any, bounds: tuple[int, int]) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(bounds[0], min(bounds[1], int(value)))


def _strings(values: Any, limit: int, chars: int) -> list[str]:
    """The non-empty strings of ``values`` (a bubble's `text` read from its object), each cut to ``chars``."""
    out: list[str] = []
    for value in values if isinstance(values, list) else ():
        if isinstance(value, dict):
            value = value.get("text")
        text = one_line(value) if isinstance(value, str) else ""
        if text:
            out.append(text[:chars])
    return out[:limit]


def _followups(values: Any, limit: int) -> list[dict[str, str]]:
    """A reply's follow-ups held to the schema: at most ``limit``, each `{about, when}` with `when` one of
    `followup_whens` and `about` non-empty (the commit resolves and records them)."""
    whens = set(followup_whens())
    out: list[dict[str, str]] = []
    for item in values if isinstance(values, list) else ():
        if not isinstance(item, dict):
            continue
        about = one_line(item.get("about"))[:memory.ABOUT_CHARS]
        when = str(item.get("when") or "")
        if about and when in whens:
            out.append({"about": about, "when": when})
    return out[:max(0, limit)]


def _promise(value: Any, windows: Sequence[str]) -> dict[str, str]:
    """A reply's `promise` held to the schema: its window one offered (`snap.promise_windows`), else {}."""
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict) or str(value.get("window") or "") not in windows:
        return {}
    return {"window": str(value["window"]), "about": one_line(value.get("about"))[:memory.ABOUT_CHARS]}


def _held(parsed: dict[str, Any], schema: dict[str, Any], decision: Decision,
          snap: PersonSnapshot, moods: tuple[str, ...], *, degraded: bool = False) -> dict[str, Any]:
    """
    A parsed reply held to its schema: `conform` (rung 2/3's drops, logged),
    then the bounds `conform` does not hold -- lengths, the regard's integer
    bounds (a regard dropped whole for one bad field is salvaged field by
    field: out-of-bounds clamped, an unknown mood `neutral`), the proposals
    legal at the snapshot, the follow-ups and the promise the schema offered.
    Bubbles are plain strings.
    """
    reply = conform(parsed, _envelope(schema))
    warmth, trust = regard_bounds()
    raw_regard = parsed.get("regard") if isinstance(parsed.get("regard"), dict) else {}
    mood = raw_regard.get("mood")
    chars = int(mode_caps(decision.mode, degraded=degraded).get("bubble_chars", BUBBLE_CHARS))
    props = schema.get("properties") or {}
    held: dict[str, Any] = {
        "bubbles": _strings(reply.get("bubbles"), bubble_limit(decision, degraded=degraded), chars),
        "regard": {"warmth": _int_in(raw_regard.get("warmth"), warmth),
                   "trust": _int_in(raw_regard.get("trust"), trust),
                   "mood": mood if isinstance(mood, str) and mood in moods else _neutral()},
        "learned": _strings(reply.get("learned"), FACTS_MAX, FACT_CHARS),
        "shared": _strings(reply.get("shared"), FACTS_MAX, FACT_CHARS),
        "proposals": [],
        "followups": _followups(reply.get("followups"), int((props.get("followups") or {}).get("maxItems", 0))),
        "promise": _promise(reply.get("promise"), snap.promise_windows) if "promise" in props else {},
        # True, False, or None when the reply carries no such key (a reply no grammar held: the words decide).
        "followup_asked": _flag(parsed.get("followup_asked")) if "followup_asked" in props else None,
        "opened_up": _flag(parsed.get("opened_up")) if "opened_up" in props else None,
    }
    offered = set(((props.get("proposals") or {}).get("items") or {}).get("enum") or ())
    for name in parsed.get("proposals") if isinstance(parsed.get("proposals"), list) else ():
        if isinstance(name, str) and name in offered and name not in held["proposals"]:
            held["proposals"].append(name)
    held["proposals"] = held["proposals"][:PROPOSALS_MAX]
    if decision.media_kind == "voice":
        from engine.social import media as media_mod   # lazily: media imports this module's package

        media = reply.get("media") if isinstance(reply.get("media"), dict) else {}
        # A transcript is cut by whole words to the note's length and the speech server's limit,
        # never mid-word at the caption's 200 characters (T21 review M4).
        held["media"] = {"caption": media_mod.voice_transcript(one_line(media.get("caption")))}
    elif decision.media_kind:
        media = reply.get("media") if isinstance(reply.get("media"), dict) else {}
        held["media"] = {"caption": one_line(media.get("caption"))[:CAPTION_CHARS]}
    return held


def _flag(value: Any) -> Optional[bool]:
    """A reply's boolean, or None when it is missing or not a boolean."""
    return value if isinstance(value, bool) else None


def _neutral() -> str:
    from engine.social import relationships

    return relationships.NEUTRAL


#: Where a voice note's transcript is checked (`transcript_failures`): beside `agreement.WHERES`.
TRANSCRIPT = "transcript"


def transcript_failures(reply: dict[str, Any], decision: Decision,
                        view: agreement.AgreementView) -> list[agreement.Failure]:
    """
    A voice note's transcript (`media.caption` when the medium is voice,
    spec §13.6) checked as a reply's bubble is -- they SAY it -- each
    failure placed at `TRANSCRIPT`. [] for any other medium or no words.
    """
    if decision.media_kind != "voice":
        return []
    words = str(((reply.get("media") or {}) if isinstance(reply.get("media"), dict) else {}).get("caption") or "")
    if not words.strip():
        return []
    found = agreement.check({"bubbles": [words], "shared": [], "learned": []}, decision, view)
    return [dataclasses.replace(f, where=TRANSCRIPT) for f in found]


def _correction(found: Sequence[agreement.Failure]) -> str:
    """ONE line naming what the first failure got wrong, in engine words (never a judgement of register)."""
    first = found[0]
    template = CORRECTIONS.get(first.check, DEFAULT_CORRECTION)
    return template.format(detail=first.detail, check=first.check)


def _drop(reply: dict[str, Any], found: Sequence[agreement.Failure]) -> dict[str, Any]:
    """``reply`` without the bubbles and facts the failures point at (a `number` failure cuts the rest);
    a `promise_claimed` failure drops the reply's own `promise` too (its words no longer say it)."""
    out = copy.deepcopy(reply)
    for where in agreement.WHERES:
        gone = {f.index for f in found if f.where == where}
        cut = min((f.index for f in found if f.where == where and f.check == "number"), default=None)
        items = out.get(where) or []
        out[where] = [item for i, item in enumerate(items) if i not in gone and (cut is None or i < cut)]
    if any(f.where == TRANSCRIPT for f in found) and isinstance(out.get("media"), dict):
        out["media"] = {**out["media"], "caption": ""}     # the note keeps the message's own words
    if any(f.check == "promise_claimed" for f in found):
        out["promise"] = {}
    return out


def _key_words(text: str) -> set[str]:
    return {w for w in agreement.words_of(str(text or "")) if len(w) >= 4 and w not in _PLAIN_WORDS}


def words_carry(bubbles: Sequence[str], text: str) -> bool:
    """Whether ``bubbles`` say ``text``'s substance (T7 fix round 1, review I2): two of its key words (four
    letters or more, not the plainest, `_PLAIN_WORDS`), or one of six letters or more. Matched only: read
    only for a reply no grammar held, which carries no `followup_asked` or `opened_up` of its own."""
    said: set[str] = set()
    for bubble in bubbles:
        said |= agreement.words_of(str(bubble))
    shared = _key_words(text) & said
    return len(shared) >= 2 or any(len(w) >= 6 for w in shared)


def raised_followup(bubbles: Sequence[str], followup: dict[str, Any]) -> bool:
    """Whether ``bubbles`` raise ``followup`` by its `about` (`words_carry`): the ungrammared reply's test."""
    return words_carry(bubbles, str((followup or {}).get("about") or ""))


def _voiced(snap: PersonSnapshot, reply: dict[str, Any], *, failures: Sequence[str]) -> VoicedReply:
    """A held reply as the commit applies it: the follow-up it raised and the layer it opened up about by
    its own statement (`followup_asked`, `opened_up`), or by its words when it carries neither
    (`words_carry`), and the promise its words state when it made none by key (review I1)."""
    decision = _decision(snap)
    bubbles = list(reply.get("bubbles") or [])
    asked, opened = reply.get("followup_asked"), reply.get("opened_up")
    raised = ""
    if snap.followup and (asked is True or (asked is None and raised_followup(bubbles, snap.followup))):
        raised = str(snap.followup.get("id") or "")
    told = ""
    if snap.reveal and (opened is True or (opened is None and words_carry(bubbles, snap.reveal.get("text", "")))):
        told = str(snap.reveal.get("id") or "")
    stated = ""
    if not decision.promise_id and not reply.get("promise"):
        window = agreement.stated_promise(bubbles)
        stated = window if window in snap.promise_windows else ""
    return VoicedReply(
        pid=snap.pid, thread_id=snap.thread_id, message_ids=tuple(str(m.get("id")) for m in snap.due),
        bubbles=bubbles, caption=str((reply.get("media") or {}).get("caption") or ""),
        regard=dict(reply["regard"]), learned=list(reply.get("learned") or []),
        shared=list(reply.get("shared") or []), proposals=list(reply.get("proposals") or []),
        fallback=False, failures=list(failures), through_id=snap.through_id,
        followups=[dict(f) for f in reply.get("followups") or ()], promise=dict(reply.get("promise") or {}),
        followup_raised=raised, reveal=told, stated_promise=stated)


def _content_fault(snap: PersonSnapshot, decision: Decision) -> str:
    """Why this snapshot cannot be voiced from the story's content ("" when it can): texter.md broken,
    or the decision's situation not in its table."""
    try:
        texter = texter_prompt()
    except ValueError as exc:
        return str(exc)
    if _row_id(decision.situation) not in texter.instructions:
        return f"social: {TEXTER_FILE}: ## Instructions: no row for situation {decision.situation!r}"
    return ""


def _usable_context(llm_fn: Any) -> Optional[int]:
    """The binding's usable context when ``llm_fn`` can tell (`TexterCall.usable_context`), else None."""
    getter = getattr(llm_fn, "usable_context", None)
    if not callable(getter):
        return None
    try:
        value = int(getter() or 0)
    except Exception as exc:  # noqa: BLE001 -- no binding to ask: the configured window
        logger.info("[social] The texter's context could not be read; the configured window is used "
                    "(operation=voice): %s", exc)
        return None
    return value if value > 0 else None


def voice(snap: PersonSnapshot, llm_fn: Optional[LLMFn]) -> VoicedReply:
    """
    One person's due burst voiced (§13): the prompt in this call's window, the
    call with its mode's `max_tokens`, the reply held to the schema, the
    agreement checks, one retry with a correction, then the offending items
    dropped, else the fallback. Pure over the snapshot: writes no state.
    """
    decision = _decision(snap)
    if llm_fn is None:
        fault = _content_fault(snap, decision)
        if fault:
            logger.error("[social] A content fault; the reply falls back (operation=voice, pid=%s): %s",
                         snap.pid, fault)
        return fallback_reply(snap, "no model")
    usable = _usable_context(llm_fn)
    _window, degraded = window_for(int(usable or _configured_window()), decision.mode)
    try:
        moods = _moods()
        schema = _schema_for(snap, decision, moods, degraded=degraded)
        msgs = messages(snap, usable_context=usable)
        view = agreement.view_from_snapshot(snap)
    except ValueError as exc:   # a content fault (an unknown situation, a broken texter.md): never raised
        logger.error("[social] A content fault; the reply falls back (operation=voice, pid=%s): %s", snap.pid, exc)
        return fallback_reply(snap, "content fault")
    fmt = response_format(_envelope(schema))
    cap = int(mode_caps(decision.mode, degraded=degraded)["max_tokens"])
    failures: list[str] = []
    for attempt in range(2):
        try:
            if getattr(llm_fn, "takes_max_tokens", False):
                raw = llm_fn(msgs, fmt, max_tokens=cap)            # type: ignore[call-arg]
            else:
                raw = llm_fn(msgs, fmt)
        except Exception as exc:  # noqa: BLE001 -- no server, a starved reply: the fallback
            logger.info("[social] Voice call failed (operation=voice, pid=%s): %s", snap.pid, exc)
            return fallback_reply(snap, "call failed", failures=failures)
        parsed = _parse(raw)
        reply = _held(parsed, schema, decision, snap, moods, degraded=degraded) if parsed is not None else None
        if reply is None or not reply["bubbles"]:
            failures.append(UNPARSED if reply is None else EMPTY)
            msgs = msgs + [{"role": "assistant", "content": str(raw)}, {"role": "user", "content": JSON_ONLY}]
            continue
        found = agreement.check(reply, decision, view) + transcript_failures(reply, decision, view)
        if not found:
            return _voiced(snap, reply, failures=failures)
        failures.extend(f.check for f in found)
        if attempt == 0:
            msgs = msgs + [{"role": "assistant", "content": str(raw)},
                           {"role": "user", "content": _correction(found)}]
            continue
        trimmed = _drop(reply, found)          # the offending bubbles/facts dropped, never stored
        if trimmed.get("bubbles"):
            return _voiced(snap, trimmed, failures=failures)
    return fallback_reply(snap, "two failures", failures=failures)   # the record of why survives (F9)


# -- the fallback (§13.1) -------------------------------------------------------------------------


def _fallback_regard() -> dict[str, Any]:
    """relationships.yaml `regard.fallback` (the §10.2 ruling), mood neutral: never zero."""
    row = (social.data("relationships").get("regard") or {}).get("fallback") or {}
    return {"warmth": int(row.get("warmth", 0)), "trust": int(row.get("trust", 0)), "mood": _neutral()}


def _fallback_keys(decision: Decision, snap: PersonSnapshot) -> list[tuple[str, str]]:
    """Where the fallback looks, in order, as (block, key): a decline's `decline`; for a reply, how it ends
    (`sign_off.<mode>`, `winding.<mode>`) and then a follow-up it raises; then the situation by mode --
    the archetype's own `<situation>.<mode>`, its plain `<situation>` (its quick lines), `any`'s
    `<situation>.<mode>`, its plain `<situation>` again in any mode -- then `reply` the same way."""
    arch, mode = person_of(snap).archetype, decision.mode
    situation = _row_id(decision.situation)
    keys: list[tuple[str, str]] = [(arch, DECLINE_KEY)] if decision.kind == "decline" else []

    def by_mode(name: str) -> list[tuple[str, str]]:
        plain = [(arch, name)] if mode == "quick" else []
        return [(arch, f"{name}.{mode}"), *plain, (ANY_KEY, f"{name}.{mode}"), (arch, name), (ANY_KEY, name)]

    if situation == "reply" and decision.kind != "decline":
        end_row = dict(END_ROWS).get(decision.end)
        if end_row:
            keys += by_mode(end_row)
        elif snap.followup:
            keys += by_mode("followup")
    keys += by_mode(situation)
    if situation != "reply":
        keys += by_mode("reply")
    return keys


def _usable_lines(lines: Sequence[str], facts: dict[str, str]) -> list[str]:
    """The lines whose every field has a fact (an `OPTIONAL_FIELDS` one may be empty)."""
    return [x for x in lines if all(facts.get(f) or f in OPTIONAL_FIELDS for f in _fields(x))]


def fallback_reply(snap: PersonSnapshot, why: str, *, failures: Sequence[str] = ()) -> VoicedReply:
    """
    The engine's own reply when no model answers or both attempts fail
    (§13.1): a seeded line from `texter.md`'s fallbacks (`_fallback_keys`),
    its fields filled from engine facts, `regard.fallback`, nothing learned,
    `fallback=True`, ``failures`` kept. A pure function of the snapshot (its
    `seed` and first due message's id). A follow-up line raises the
    follow-up (closed at commit); nothing is revealed.
    """
    decision = _decision(snap)
    try:
        texter = texter_prompt()
    except ValueError as exc:   # a broken texter.md: the engine's own line, never a raise
        logger.error("[social] texter.md is broken; the fallback is the engine's line "
                     "(operation=fallback_reply, pid=%s): %s", snap.pid, exc)
        texter = TexterPrompt(persona="", instructions={}, fallbacks={})
    message_id = str(snap.due[0].get("id")) if snap.due else ""
    rng = stable_rng(snap.seed, f"{SOCIAL_BEHAVIOUR}:fallback:{message_id}")
    facts = _facts(snap, decision, texter)
    facts["reason"] = facts.pop("reason_said", "")     # a fallback says the reason in the person's own words
    facts["topic"] = str(rng.choice(snap.topics)) if snap.topics else ""
    line, key = FALLBACK_LINE, ""
    for block, name in _fallback_keys(decision, snap):
        usable = _usable_lines((texter.fallbacks.get(block) or {}).get(name) or (), facts)
        if usable:
            line, key = _fill(str(rng.choice(usable)), facts) or FALLBACK_LINE, name
            break
    logger.info("[social] Fallback reply (operation=fallback_reply, pid=%s, why=%s, failures=%s)",
                snap.pid, why, list(failures))
    raised = str(snap.followup.get("id") or "") if snap.followup and key.split(".")[0] == "followup" else ""
    return VoicedReply(
        pid=snap.pid, thread_id=snap.thread_id, message_ids=tuple(str(m.get("id")) for m in snap.due),
        bubbles=[line], caption="", regard=_fallback_regard(), learned=[], shared=[], proposals=[],
        fallback=True, failures=list(failures), through_id=snap.through_id, followup_raised=raised)


def fallback_reply_for(state: Any, pid: str, thread_id: str, wanted: Sequence[dict[str, Any]], why: str,
                       *, failures: Sequence[str] = ()) -> VoicedReply:
    """
    The fallback for ``wanted`` (due message rows of ``pid`` in ``thread_id``)
    built from the LIVE state, with no snapshot kept (CALLER HOLDS the turn
    lock): the voicing pass's commit, when the state-dependent re-checks
    (spec §16.3 step 3) leave a reply no bubble. The same line `fallback_reply`
    picks for a snapshot of those messages.
    """
    ids = [str(m.get("id")) for m in wanted]
    snap = snapshot_of(state, thread_id)
    if snap is None or snap.pid != pid:
        raise ValueError(f"social: fallback_reply_for: {thread_id} holds no due message of {pid}")
    due = [m for m in snap.due if str(m.get("id")) in ids] or [copy.deepcopy(dict(m)) for m in wanted]
    return fallback_reply(dataclasses.replace(snap, due=due), why, failures=failures)


# -- production ------------------------------------------------------------------------------------


class TexterCall:
    """
    The production binding (`production_llm_fn`): the `texter` profile,
    reasoning off, not streamed, with the mode's `max_tokens` per call (spec
    §4.5: the profile's own is a ceiling). The intended grammar rides the
    backend's structured-output ladder (`structured_output`: rung 1, 2 or
    none); a reply starved at its cap with no content raises, so `voice`
    falls back. `usable_context` is the binding's (spec §7.4).
    """

    takes_max_tokens = True

    def usable_context(self) -> int:
        from engine.llm.profiles import resolve_profile

        return int(resolve_profile("texter").context_tokens)

    def __call__(self, msgs: list[dict[str, Any]], fmt: dict[str, Any], *, max_tokens: Optional[int] = None) -> str:
        from engine.llm.backend import get_backend

        backend = get_backend()
        envelope = fmt.get("json_schema") if isinstance(fmt, dict) else None
        wire = backend.structured_output(envelope) if isinstance(envelope, dict) else None
        ceiling = int(get_config().get("llm.profiles.texter.max_tokens", 800) or 800)
        cap = min(ceiling, int(max_tokens)) if max_tokens else None
        reply = backend.chat(msgs, profile="texter", response_format=wire, reasoning="off", label="social_voice",
                             max_tokens=cap)
        if reply.truncated and not str(reply.content or "").strip():
            raise RuntimeError("starved")
        return str(reply.content or "")


def production_llm_fn() -> LLMFn:
    """The production binding: a `TexterCall`."""
    return TexterCall()
