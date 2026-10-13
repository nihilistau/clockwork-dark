"""
The voicing call (v0.22.0 spec §11.1-11.4): the model writes what one person
SAYS in one thread, and proposes -- inside engine bounds -- how the exchange
moved them. Nothing here writes state (rule 1): `voice` is pure over a
`PersonSnapshot`, and the commit is the voicing pass's (T14).

- **The snapshot** (`snapshot_of`, under the turn lock): one person, one
  thread, its due messages and their `Decision`s, deep copies of everything
  the prompt and the agreement checks read, and `seed` (`state.rng_seed`),
  the fallback's only seed (pre-flight F9).
- **The schema** (`reply_schema`, §11.2): bubbles (1..the decision's
  `max_bubbles`), a `media` caption only when media is attached, a regard
  proposal inside the schema's bounds (the engine's own clamp is
  relationships.yaml's, at commit), learned/shared facts, and the §10.5
  proposals legal at the snapshot. With no proposal legal the key is left
  out (`additionalProperties: false` then forbids it): `conform` cannot hold
  an items-less `maxItems: 0` array, so the empty enum is never sent.
- **The prompt** (`messages`, §11.3): the system message is `texter.md`'s
  persona section verbatim (everything above `## Instructions`, Plan
  decision 22); the user message is the six titled blocks of `BLOCK_TITLES`,
  trimmed by `memory.budgeted` (§12.4). RIGHT NOW ends with the SITUATION
  line from `texter.md`'s instruction table, so the story owns every word.
- **The call** (`voice`): one call, the reply conformed and held to the
  schema, the agreement checks (§11.5), one retry with a one-line correction
  naming only the fact the reply got wrong, then the offending bubbles and
  facts dropped, else the engine-written fallback.
- **The fallback** (`fallback_reply`, §11.4): a line from `texter.md`'s
  `fallbacks:` for the person's archetype and the situation (a decline's
  `decline` row first, then the situation's, then `reply`, then
  `FALLBACK_LINE`), picked by `stable_rng(seed, ...)` keyed by the first due
  message's id -- a pure function of the snapshot. It proposes
  relationships.yaml `regard.fallback` (the §10.2 ruling: engine-authored
  replies grow too, through the same `social_regard` path and per-day cap),
  mood `neutral`, nothing learned or shared, no proposal, and keeps the
  agreement failures that led to it (`failures`, F9).

Rule 12: no prompt block, correction line or fallback here rates content;
the register is `texter.md`'s and the owner's model's.
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
from engine.social.kinds import Decision
from engine.social.population import Person

logger = logging.getLogger(__name__)

__all__ = [
    "BLOCK_TITLES", "Decision", "LLMFn", "PersonSnapshot", "SITUATIONS", "TexterPrompt", "VoicedReply",
    "fallback_reply", "fallback_reply_for", "messages", "parse_texter", "production_llm_fn", "reply_schema", "situation_faults",
    "snapshot_of", "texter_prompt", "voice",
]

#: The voicer's model function: the messages and the `response_format` in, raw text out.
LLMFn = Callable[[list[dict[str, Any]], dict[str, Any]], str]

#: The user message's six titled blocks, in order (§11.3 blocks 2-7; block 1 is the system message).
BLOCK_TITLES: tuple[str, ...] = ("WHO YOU ARE", "WHERE YOU ARE WITH THEM", "WHAT YOU KNOW ABOUT THEM",
                                 "THE CONVERSATION", "RIGHT NOW", "FORMAT")

#: Every situation the ENGINE emits itself (messaging's openers, replies, double texts and answers;
#: engine/social/media.py's sends and declines, T19; a game's banter, T22; a meet-up's text after, T24);
#: the story's own (behaviours.yaml `instruction:`, an arc beat's) are cross-checked from its data.
#: Each must be a row of texter.md's instruction table (`situation_faults`).
SITUATIONS: tuple[str, ...] = ("opener", "reply", "double_text", "answer_request",
                               "send_selfie", "send_photo", "send_voice", "send_video",
                               "decline_photo", "decline_voice", "decline_video", "game_banter", "post_meet")

#: The fallbacks' key for a decline decision, tried before its situation's.
DECLINE_KEY = "decline"

#: The engine's own line when the story's fallbacks have none for the archetype.
FALLBACK_LINE = "hey"

#: The prompt file, in the story's `prompts/` directory.
TEXTER_FILE = "texter.md"

#: The response_format envelope's name.
SCHEMA_NAME = "texter_reply"

#: The schema's bounds (§11.2); the engine's per-reply clamp is relationships.yaml's, at commit.
BUBBLE_CHARS = 280
FACT_CHARS = 140
CAPTION_CHARS = 200
FACTS_MAX = 2
PROPOSALS_MAX = 2
#: The schema's caps (§11.2); the bounds offered are these narrowed by relationships.yaml
#: `regard.per_reply` (`regard_bounds`), so a story that narrows a reply's move narrows the offer.
WARMTH_BOUNDS: tuple[int, int] = (-4, 4)
TRUST_BOUNDS: tuple[int, int] = (-2, 2)

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
    "meeting_claimed": "Your reply said \"{detail}\", but that is not what the two of you have planned. "
                       "Rewrite it to agree with your plans.",
}
DEFAULT_CORRECTION = "Your reply did not match what has happened ({check}: {detail}). Rewrite it."

#: Situation-free words for a schedule status and an intent.
STATUS_WORDS: dict[str, str] = {"free": "free", "work": "at work", "out": "out", "asleep": "in bed"}
#: What each §10.5 proposal asks for, in the FORMAT block's words.
PROPOSAL_WORDS: dict[str, str] = {
    "offer_number": "offer them your number", "ask_meet": "ask to meet them", "offer_photo": "offer a photo",
    "offer_voice": "offer a voice note", "offer_video": "offer a video", "invite_game": "invite them to a game",
    "ask_exclusive": "ask to be exclusive", "cool_off": "pull back for a while",
}
INTENT_WORDS: dict[str, str] = {"long_term": "something long-term", "short_term": "something casual",
                                "friendship": "friendship", "unsure": "nothing settled yet"}


# -- the shared types ---------------------------------------------------------------------------


@dataclass
class PersonSnapshot:
    """Everything one voicing call reads, copied out of state under the turn lock (never the live state)."""

    pid: str
    thread_id: str
    profile: dict[str, Any]          # population.profile(...) as a dict (`Person(**profile)` rebuilds it)
    dynamic: dict[str, Any]          # deep copy of people[pid], rev included
    tail: list[dict[str, Any]]       # the thread's last social.memory.verbatim voiced messages
    summary: str
    due: list[dict[str, Any]]        # the due message rows (decision included), oldest first
    proposals: tuple[str, ...]       # §10.5 rows legal at snapshot
    player: dict[str, Any]           # the player's profile
    now: dict[str, Any]              # {day, hour, minute, weekday, status, at}
    contacts: tuple[str, ...]        # display names of everyone else with a thread (agreement: another person)
    seed: int                        # state.rng_seed: the fallback's stable_rng seed (pre-flight F9)
    meets: tuple[dict[str, Any], ...] = ()             # this person's meet rows (agreement: meeting claimed)
    player_words: tuple[str, ...] = ()                 # every word the player wrote to them still in state
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)   # the requests the due decisions answer
    games: dict[str, str] = field(default_factory=dict)                 # game id -> the engine's line about it (T22)
    recap: dict[str, Any] = field(default_factory=dict)                 # a due recap's view (meets.recap_view, T24)


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


@dataclass(frozen=True)
class TexterPrompt:
    """`texter.md`, parsed: the persona section, the instruction table, the fallbacks."""

    persona: str
    instructions: dict[str, str]
    fallbacks: dict[str, dict[str, list[str]]]


# -- texter.md ------------------------------------------------------------------------------------

#: The active story's parsed texter.md. NULLED_ATTRIBUTES row; read once into a local.
_TEXTER_CACHE: Optional[TexterPrompt] = None

_INSTRUCTIONS = re.compile(r"^## Instructions[ \t]*$", re.MULTILINE)
_FALLBACKS = re.compile(r"^## Fallbacks[ \t]*$", re.MULTILINE)
_ROW = re.compile(r"^- `([a-z][a-z0-9_]*)`: (\S.*)$")
_FENCE = re.compile(r"^```yaml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: {TEXTER_FILE}: {key}: {message}")


def parse_texter(text: str) -> TexterPrompt:
    """
    `texter.md`'s three parts (format pinned by the plan's T2 step): the
    persona above `## Instructions`; that heading's `- \\`<id>\\`: <line>`
    bullets; one fenced `yaml` block under `## Fallbacks`, archetype ->
    situation (an instruction id or `decline`) -> lines. A ValueError
    naming the key at fault.
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
    fallbacks: dict[str, dict[str, list[str]]] = {}
    for arch, rows in raw.items():
        if not isinstance(rows, dict) or not rows:
            raise _fault(f"fallbacks.{arch}", "must be a mapping of situations")
        fallbacks[str(arch)] = {}
        for situation, lines in rows.items():
            if situation != DECLINE_KEY and situation not in instructions:
                raise _fault(f"fallbacks.{arch}.{situation}", "is no row of ## Instructions (nor `decline`)")
            if (not isinstance(lines, list) or not lines
                    or not all(isinstance(x, str) and x.strip() for x in lines)):
                raise _fault(f"fallbacks.{arch}.{situation}", "must be a list of non-empty lines")
            fallbacks[str(arch)][str(situation)] = [x.strip() for x in lines]
    return TexterPrompt(persona=persona, instructions=instructions, fallbacks=fallbacks)


def situation_faults(prompt: TexterPrompt, behaviours: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Every situation the engine or the story's data can emit that the
    instruction table lacks, and every fallback archetype behaviours.yaml
    does not declare, as (key, message): `SITUATIONS`, each initiation's
    `instruction` (or its id, which messaging uses when it has none) and
    each arc beat's `instruction`.
    """
    table = prompt.instructions
    out = [(f"SITUATIONS.{s}", "the engine emits it; ## Instructions has no row for it")
           for s in SITUATIONS if s not in table]
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
            if arch not in archetypes:
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


# -- the snapshot ---------------------------------------------------------------------------------


def snapshot_of(state: Any, thread_id: str) -> Optional[PersonSnapshot]:
    """
    One person's snapshot for ``thread_id`` (CALLER HOLDS the turn lock):
    deep copies only, so `voice` may run with the lock released. None when
    the thread is unknown or holds no due message of theirs.
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
    person = population.profile(state, pid)
    voiced = [m for m in rows if m.get("voiced") is not False and m.get("voiced") != "withdrawn"]
    _older, tail = memory.split_tail(voiced, max(1, int(social.setting("memory.verbatim", 24))))
    requests = slice_.get("requests") or {}
    wanted = {str((m.get("decision") or {}).get("request_id") or "") for m in due} - {""}
    played = sorted({str((m.get("decision") or {}).get("game_id") or "") for m in due} - {""})
    notes: dict[str, str] = {}
    if played:
        from engine.social import games   # lazily: games imports messaging, which this module's package loads

        notes = {gid: games.banter_note(state, gid) for gid in played}
    at = float(state.world_clock_hours)
    total = int(round(at * 60))                    # one rounding, so 31.9999 is 08:00, never 07:00
    return PersonSnapshot(
        pid=pid, thread_id=thread_id, profile=dataclasses.asdict(person),
        dynamic=copy.deepcopy((slice_.get("people") or {}).get(pid) or {}),
        tail=copy.deepcopy(tail), summary=str(thread.get("summary") or ""), due=due,
        proposals=tuple(relationships.legal_proposals(state, pid)),
        player=copy.deepcopy(slice_.get("player") or {}),
        now={"day": int(state.world_day), "hour": (total // 60) % 24, "minute": total % 60,
             "weekday": behaviour.weekday_of(at), "status": behaviour.status_at(person, at), "at": at},
        contacts=tuple(agreement.contact_names(state, pid)), seed=int(state.rng_seed),
        meets=agreement.meets_of(state, pid), player_words=tuple(sorted(agreement.said_to(state, pid))),
        requests={rid: copy.deepcopy(requests[rid]) for rid in sorted(wanted) if rid in requests},
        games={gid: note for gid, note in notes.items() if note},
    )


def person_of(snap: PersonSnapshot) -> Person:
    """The snapshot's `Person`, rebuilt from its dict."""
    return Person(**snap.profile)


def _decision(snap: PersonSnapshot) -> Decision:
    """The first due message's `Decision` (one call voices one person's whole due burst)."""
    row = dict((snap.due[0].get("decision") if snap.due else None) or {})
    known = {f.name for f in dataclasses.fields(Decision)}
    row = {k: v for k, v in row.items() if k in known}
    row.setdefault("situation", "reply")
    return Decision(**row)


def _moods() -> tuple[str, ...]:
    from engine.social import relationships

    return tuple(str(m) for m in (social.data("relationships").get("mood") or {}).get("values")
                 or (relationships.NEUTRAL,))


# -- the schema (§11.2) ---------------------------------------------------------------------------


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


def reply_schema(decision: Decision, proposals: tuple[str, ...], moods: tuple[str, ...]) -> dict[str, Any]:
    """The reply's JSON schema for one call (§11.2): media only when attached, proposals only when legal,
    regard inside `regard_bounds`."""
    warmth, trust = regard_bounds()
    props: dict[str, Any] = {
        "bubbles": {"type": "array", "minItems": 1, "maxItems": max(1, decision.max_bubbles),
                    "items": {"type": "object", "additionalProperties": False,
                              "properties": {"text": {"type": "string", "maxLength": BUBBLE_CHARS}},
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
    if proposals:
        props["proposals"] = {"type": "array", "maxItems": PROPOSALS_MAX,
                              "items": {"type": "string", "enum": list(proposals)}}
        required.append("proposals")
    if decision.media_kind:
        cap = int(get_config().get("tts.max_chars", 400)) if decision.media_kind == "voice" else CAPTION_CHARS
        props["media"] = {"type": "object", "additionalProperties": False,
                          "properties": {"caption": {"type": "string", "maxLength": cap}},
                          "required": ["caption"]}
        required.append("media")
    return {"type": "object", "additionalProperties": False, "properties": props, "required": required}


def _envelope(schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": SCHEMA_NAME, "strict": True, "schema": schema}


# -- the prompt (§11.3) ---------------------------------------------------------------------------


def _label(table: str, row_id: str) -> str:
    from engine.social import population

    for row in population.table(table):
        if isinstance(row, dict) and str(row.get("id")) == str(row_id):
            return str(row.get("label") or row_id)
    return str(row_id).replace("_", " ")


def _labels(table: str, ids: Sequence[str]) -> str:
    from engine.social import population

    return ", ".join(population.in_sentence(_label(table, i)) for i in ids)


def _style_words(style_id: str) -> str:
    """A texting style row as a description (character notes, never rules: spec §4.3)."""
    from engine.social import population

    row = next((r for r in population.table("texting_styles") if isinstance(r, dict) and r.get("id") == style_id),
               None)
    if row is None:
        return ""
    parts = [{"short": "short messages", "medium": "medium-length messages",
              "long": "long, full messages"}.get(str(row.get("length")), "messages")]
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


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def _who(snap: PersonSnapshot) -> str:
    p = snap.profile
    app = snap.thread_id.split(":", 1)[0]
    bios = dict(p.get("bio") or {})
    bio = bios.get(app) or next(iter(bios.values()), "")
    from engine.social import population

    hobbies = tuple(p.get("hobbies") or ()) or ("",)
    words = population.template_words(social.data("population"), hobbies, str(p.get("job") or ""),
                              str(p.get("neighbourhood") or ""))
    lines = [f"You are {p.get('name')}, {p.get('age')}, {words['a_job']} living in {words['neighbourhood']}."]
    if p.get("hobbies"):
        lines.append(f"You are into {_labels('hobbies', list(p['hobbies']))}.")
    if p.get("traits"):
        lines.append(f"People would call you {_labels('traits', list(p['traits']))}.")
    style = _style_words(str(p.get("texting_style") or ""))
    if style:
        lines.append(style)
    if bio:
        lines.append(f"Your profile says: {_one_line(bio)}")
    for question, answer in p.get("prompts") or ():
        if answer:
            lines.append(f"{_one_line(question)} {_one_line(answer)}")
    return "\n".join(lines)


def _canon(snap: PersonSnapshot) -> str:
    return "\n".join(f"- {_one_line(f)}" for f in snap.dynamic.get("canon") or () if str(f).strip())


def _where(snap: PersonSnapshot) -> str:
    from engine.social import relationships

    stage = str(snap.dynamic.get("stage") or "matched")
    mood = relationships.mood_now(snap.dynamic, float(snap.now.get("at", 0.0)))
    lines = [f"Where things stand: {relationships.stage_words(stage)}.",
             f"How close you feel: {relationships.band(snap.dynamic)}.",
             f"Your mood: {mood}.",
             f"What you want: {INTENT_WORDS.get(str(snap.profile.get('intent')), 'nothing settled yet')}.",
             f"What you think they want: "
             f"{INTENT_WORDS.get(str(snap.player.get('looking_for')), 'nothing settled yet')}."]
    return "\n".join(lines)


def _history(snap: PersonSnapshot) -> str:
    rows = [r for r in snap.dynamic.get("history") or () if isinstance(r, dict) and str(r.get("text") or "").strip()]
    return "\n".join(f"Day {r.get('day')}: {_one_line(r.get('text'))}" for r in rows[-HISTORY_ROWS:])


def _knows(snap: PersonSnapshot) -> str:
    pl = snap.player
    attributes = pl.get("attributes") or {}
    from engine.social import population

    lines = [f"Their profile: {pl.get('name') or 'them'}, {pl.get('age')}"
             + (f", {population.in_sentence(_label('jobs', str(attributes['job'])))}" if attributes.get("job") else "")
             + (f", living in {_label('neighbourhoods', str(pl['neighbourhood']))}" if pl.get("neighbourhood") else "")
             + "."]
    if pl.get("hobbies"):
        lines.append(f"They are into {_labels('hobbies', list(pl['hobbies']))}.")
    lines.append(f"They are looking for {INTENT_WORDS.get(str(pl.get('looking_for')), 'nothing settled yet')}.")
    knows = [f"- {_one_line(f)}" for f in snap.dynamic.get("knows") or () if str(f).strip()]
    if knows:
        lines.append("What they have told you:")
        lines.extend(knows)
    return "\n".join(lines)


def _conversation_lines(snap: PersonSnapshot) -> str:

    them = str(snap.player.get("name") or "them")
    lines: list[str] = []
    for message in snap.tail:
        if message.get("voiced") is False or message.get("from") == "system":
            continue
        who = "you" if message.get("from") == snap.pid else them
        lines.extend(f"{memory.stamp(message.get('at'))} {who}: {_one_line(w)}"
                     for w in memory.message_words(message))
    return "\n".join(lines)


def _ago(hours: float) -> str:
    minutes = max(0, int(round(hours * 60)))
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    if minutes < 48 * 60:
        h = minutes // 60
        return f"{h} hour{'s' if h != 1 else ''}"
    d = minutes // (24 * 60)
    return f"{d} days"


def _right_now(snap: PersonSnapshot, texter: TexterPrompt) -> str:
    decision = _decision(snap)
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

        lines.append(f"What has changed: {_one_line(behaviour.canon_text(decision.reveal))}")
    if decision.request_id:
        request = snap.requests.get(decision.request_id) or {}
        what = str(request.get("what") or "something").replace("_", " ")
        answer = "no" if decision.kind == "decline" else "yes"
        if decision.kind == "decline" and request.get("why") == "not yet":
            answer = "not yet, it's too early"           # the gate, not the odds (owner bug, v0.22.0)
        asked = "They asked to meet up." if what == "meet" else f"They asked for your {what}."
        lines.append(f"{asked} Your answer: {answer}.")
    if snap.meets:
        from engine.social import meets   # lazily: meets imports this module's package

        met = next((m for m in snap.meets if m.get("id") == decision.meet_id and m.get("band")), None)
        if met is not None:
            lines.append(f"Your meet-up: {meets.place_line(str(met['venue']))}. {meets.recap_line(str(met['band']))}")
        plans = [m for m in snap.meets if m.get("status") in agreement.PLANNED]
        if plans:
            first = min(plans, key=lambda m: float(m.get("start") or 0.0))
            lines.append(f"Your plans with them: {meets.place_line(str(first['venue']))}, {meets.when_words(first)}.")
    if decision.game_id and snap.games.get(decision.game_id):
        lines.append(f"The game: {_one_line(snap.games[decision.game_id])}")
    count = max(1, decision.max_bubbles)
    lines.append(f"Send at most {count} message{'s' if count != 1 else ''}.")
    row = texter.instructions.get(decision.situation)
    if row is None:   # a content fault: `voice` falls back on it, logged at ERROR
        raise ValueError(f"social: {TEXTER_FILE}: ## Instructions: no row for situation {decision.situation!r}")
    lines.append(f"SITUATION: {row}")
    return "\n".join(lines)


def _format_note(snap: PersonSnapshot, decision: Decision) -> str:
    """What each key of the reply is for (engine words about the envelope, never about register)."""
    lines = ["How to fill it in: `bubbles` are your messages, in order. `regard` is how this exchange moved "
             "how you feel about them (warmth and trust, up or down) and your mood now. `learned` holds new "
             "facts they told you about themselves; `shared` holds facts about yourself you told them in this "
             "reply. Leave a list empty when there is nothing for it."]
    if snap.proposals:
        asks = "; ".join(f"{name} ({PROPOSAL_WORDS.get(name, name.replace('_', ' '))})" for name in snap.proposals)
        lines.append(f"`proposals` may ask for: {asks}. Leave it empty unless you mean it.")
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


def messages(snap: PersonSnapshot) -> list[dict[str, str]]:
    """Exactly seven blocks, in order (spec §11.3, pinned by test_the_voice_prompt_is_exactly_its_blocks)."""
    texter = texter_prompt()
    decision = _decision(snap)
    if decision.situation not in texter.instructions:
        raise ValueError(f"social: {TEXTER_FILE}: ## Instructions: no row for situation {decision.situation!r}")
    fixed_now = _flat(_right_now(snap, texter))
    fmt = _format_note(snap, decision) + "\n" + render_format_block(reply_schema(decision, snap.proposals, _moods()))
    reply_cap = int(get_config().get("llm.profiles.texter.max_tokens", 360) or 360)
    window = int(social.setting("voice.window_tokens", 4096)) - reply_cap
    parts = memory.budgeted({
        "persona": texter.persona, "who": _flat(_who(snap)), "canon": _flat(_canon(snap)),
        "where": _flat(_where(snap)), "history": _flat(_history(snap)), "knows": _flat(_knows(snap)),
        "summary": _flat(snap.summary), "verbatim": _flat(_conversation_lines(snap)),
        "now": fixed_now, "format": fmt,
    }, window=window)
    who = parts["who"] + (f"\nWhat you have told them about yourself:\n{parts['canon']}" if parts["canon"] else "")
    where = parts["where"] + (f"\nYour story so far:\n{parts['history']}" if parts["history"] else "")
    them = str(snap.player.get("name") or "them")
    conversation = "\n".join(filter(None, [
        f"Earlier (a summary; \"you\" in it means {them}): {parts['summary']}" if parts["summary"] else "",
        parts["verbatim"] or "No messages yet."]))
    bodies = (who, where, parts["knows"], conversation, parts["now"], _flat(fmt))
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
        text = _one_line(value) if isinstance(value, str) else ""
        if text:
            out.append(text[:chars])
    return out[:limit]


def _held(parsed: dict[str, Any], schema: dict[str, Any], decision: Decision,
          snap: PersonSnapshot, moods: tuple[str, ...]) -> dict[str, Any]:
    """
    A parsed reply held to its schema: `conform` (rung 2/3's drops, logged),
    then the bounds `conform` does not hold -- lengths, the regard's integer
    bounds (a regard dropped whole for one bad field is salvaged field by
    field: out-of-bounds clamped, an unknown mood `neutral`), the proposals
    legal at the snapshot. Bubbles are plain strings.
    """
    reply = conform(parsed, _envelope(schema))
    warmth, trust = regard_bounds()
    raw_regard = parsed.get("regard") if isinstance(parsed.get("regard"), dict) else {}
    mood = raw_regard.get("mood")
    held: dict[str, Any] = {
        "bubbles": _strings(reply.get("bubbles"), max(1, decision.max_bubbles), BUBBLE_CHARS),
        "regard": {"warmth": _int_in(raw_regard.get("warmth"), warmth),
                   "trust": _int_in(raw_regard.get("trust"), trust),
                   "mood": mood if isinstance(mood, str) and mood in moods else _neutral()},
        "learned": _strings(reply.get("learned"), FACTS_MAX, FACT_CHARS),
        "shared": _strings(reply.get("shared"), FACTS_MAX, FACT_CHARS),
        "proposals": [],
    }
    for name in parsed.get("proposals") if isinstance(parsed.get("proposals"), list) else ():
        if isinstance(name, str) and name in snap.proposals and name not in held["proposals"]:
            held["proposals"].append(name)
    held["proposals"] = held["proposals"][:PROPOSALS_MAX]
    if decision.media_kind == "voice":
        from engine.social import media as media_mod   # lazily: media imports this module's package

        media = reply.get("media") if isinstance(reply.get("media"), dict) else {}
        # A transcript is cut by whole words to the note's length and the speech server's limit,
        # never mid-word at the caption's 200 characters (T21 review M4).
        held["media"] = {"caption": media_mod.voice_transcript(_one_line(media.get("caption")))}
    elif decision.media_kind:
        media = reply.get("media") if isinstance(reply.get("media"), dict) else {}
        held["media"] = {"caption": _one_line(media.get("caption"))[:CAPTION_CHARS]}
    return held


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
    """``reply`` without the bubbles and facts the failures point at (a `number` failure cuts the rest)."""
    out = copy.deepcopy(reply)
    for where in agreement.WHERES:
        gone = {f.index for f in found if f.where == where}
        cut = min((f.index for f in found if f.where == where and f.check == "number"), default=None)
        items = out.get(where) or []
        out[where] = [item for i, item in enumerate(items) if i not in gone and (cut is None or i < cut)]
    if any(f.where == TRANSCRIPT for f in found) and isinstance(out.get("media"), dict):
        out["media"] = {**out["media"], "caption": ""}     # the note keeps the message's own words
    return out


def _voiced(snap: PersonSnapshot, reply: dict[str, Any], *, failures: Sequence[str]) -> VoicedReply:
    return VoicedReply(
        pid=snap.pid, thread_id=snap.thread_id, message_ids=tuple(str(m.get("id")) for m in snap.due),
        bubbles=list(reply.get("bubbles") or []), caption=str((reply.get("media") or {}).get("caption") or ""),
        regard=dict(reply["regard"]), learned=list(reply.get("learned") or []),
        shared=list(reply.get("shared") or []), proposals=list(reply.get("proposals") or []),
        fallback=False, failures=list(failures))


def _content_fault(snap: PersonSnapshot, decision: Decision) -> str:
    """Why this snapshot cannot be voiced from the story's content ("" when it can): texter.md broken,
    or the decision's situation not in its table."""
    try:
        texter = texter_prompt()
    except ValueError as exc:
        return str(exc)
    if decision.situation not in texter.instructions:
        return f"social: {TEXTER_FILE}: ## Instructions: no row for situation {decision.situation!r}"
    return ""


def voice(snap: PersonSnapshot, llm_fn: Optional[LLMFn]) -> VoicedReply:
    """
    One person's due burst voiced (§11.4): the prompt, the call, the reply
    held to the schema, the agreement checks, one retry with a correction,
    then the offending items dropped, else the fallback. Pure over the
    snapshot: writes no state (the commit is T14's).
    """
    decision = _decision(snap)
    if llm_fn is None:
        fault = _content_fault(snap, decision)
        if fault:
            logger.error("[social] A content fault; the reply falls back (operation=voice, pid=%s): %s",
                         snap.pid, fault)
        return fallback_reply(snap, "no model")
    try:
        moods = _moods()
        schema = reply_schema(decision, snap.proposals, moods)
        msgs = messages(snap)
        view = agreement.view_from_snapshot(snap)
    except ValueError as exc:   # a content fault (an unknown situation, a broken texter.md): never raised
        logger.error("[social] A content fault; the reply falls back (operation=voice, pid=%s): %s", snap.pid, exc)
        return fallback_reply(snap, "content fault")
    fmt = response_format(_envelope(schema))
    failures: list[str] = []
    for attempt in range(2):
        try:
            raw = llm_fn(msgs, fmt)
        except Exception as exc:  # noqa: BLE001 -- no server, a starved reply: the fallback
            logger.info("[social] Voice call failed (operation=voice, pid=%s): %s", snap.pid, exc)
            return fallback_reply(snap, "call failed", failures=failures)
        parsed = _parse(raw)
        reply = _held(parsed, schema, decision, snap, moods) if parsed is not None else None
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


# -- the fallback (§11.4) -------------------------------------------------------------------------


def _fallback_regard() -> dict[str, Any]:
    """relationships.yaml `regard.fallback` (the §10.2 ruling), mood neutral: never zero."""
    row = (social.data("relationships").get("regard") or {}).get("fallback") or {}
    return {"warmth": int(row.get("warmth", 0)), "trust": int(row.get("trust", 0)), "mood": _neutral()}


def fallback_reply(snap: PersonSnapshot, why: str, *, failures: Sequence[str] = ()) -> VoicedReply:
    """
    The engine's own reply when no model answers or both attempts fail
    (§11.4): a seeded line from `texter.md`'s fallbacks, `regard.fallback`,
    nothing learned, `fallback=True`, ``failures`` kept. A pure function of
    the snapshot (its `seed` and first due message's id).
    """
    decision = _decision(snap)
    person = person_of(snap)
    try:
        rows = texter_prompt().fallbacks.get(person.archetype) or {}
    except ValueError as exc:   # a broken texter.md: the engine's own line, never a raise
        logger.error("[social] texter.md is broken; the fallback is the engine's line "
                     "(operation=fallback_reply, pid=%s): %s", snap.pid, exc)
        rows = {}
    keys = ([DECLINE_KEY] if decision.kind == "decline" else []) + [decision.situation, "reply"]
    lines = next((rows[k] for k in keys if rows.get(k)), [FALLBACK_LINE])
    message_id = str(snap.due[0].get("id")) if snap.due else ""
    rng = stable_rng(snap.seed, f"{SOCIAL_BEHAVIOUR}:fallback:{message_id}")
    line = str(rng.choice(lines))
    logger.info("[social] Fallback reply (operation=fallback_reply, pid=%s, why=%s, failures=%s)",
                snap.pid, why, list(failures))
    return VoicedReply(
        pid=snap.pid, thread_id=snap.thread_id, message_ids=tuple(str(m.get("id")) for m in snap.due),
        bubbles=[line], caption="", regard=_fallback_regard(), learned=[], shared=[], proposals=[],
        fallback=True, failures=list(failures))


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


def production_llm_fn() -> LLMFn:
    """
    The production binding: the `texter` profile, reasoning off, not
    streamed. The intended grammar rides the backend's structured-output
    ladder (`structured_output`: rung 1, 2 or none); a reply starved at its
    cap with no content raises, so `voice` falls back.
    """
    from engine.llm.backend import get_backend

    def call(msgs: list[dict[str, Any]], fmt: dict[str, Any]) -> str:
        backend = get_backend()
        envelope = fmt.get("json_schema") if isinstance(fmt, dict) else None
        wire = backend.structured_output(envelope) if isinstance(envelope, dict) else None
        reply = backend.chat(msgs, profile="texter", response_format=wire, reasoning="off", label="social_voice")
        if reply.truncated and not str(reply.content or "").strip():
            raise RuntimeError("starved")
        return str(reply.content or "")

    return call
