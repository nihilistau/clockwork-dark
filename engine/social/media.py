"""
Phone media (v0.22.0 spec §13.1-13.4, §16.1 step 3): photos, voice notes and
videos as special events -- rare, earned, sometimes unprompted, and when asked
for, sometimes declined -- and the people's portraits.

WHO DECIDES (rule 1). The ENGINE decides whether anything is sent, from data
(`media.yaml`, rule 10): a person's per-kind **budget** (refilled each
time a conversation with them closes, `budget.<kind>.per_episode` to `cap`: v0.23.0 spec §6.4), the kind's **unlock stage**, the
**app** (a thread can carry only its app's `capabilities`), and a draw on
`SOCIAL_MEDIA` (rule 4): the player's `ask {what}` is answered at the
person's next read (`decide_request`: accept, decline or "later"), a model's
`offer_*` proposal draws at `unsolicited.offered_mult` x the per-episode odds
(`offer`), and as each conversation closes a person may send one unasked
(`after_episode`). The model only WORDS the message that carries it (the voice schema's `media`
caption, spec §11.2).

THE ROW (`state.social["media"][mid]`, spec §13.2), written only through
`social_media` (rule 3): born `requested` when the message carrying it lands
(`attach`), `submitted` once the job worker took it, then `ready` (a file
and its URL) or `fallback` (the procedural tile: the provider is off, the
day's cap is spent, the job failed or no workflow makes that kind). The
person still sent "a photo"; it did not load.

THE PIPELINE. `run_mechanics` step 3 (`submit_due`, also run after a voiced
commit): `jobs_for` lists the rows whose message has committed words (the
caption is in the prompt) and the portraits due by `phone_media.portraits`
(`on_match`: everyone matched; `on_view`: the deck's shown cards too;
`off`: none), each a `JobSpec`; the worker takes it or, past
`phone_media.daily_job_cap`, the row is procedural at once. With
`phone_media.provider: procedural` no job is made at all. A finished job
comes back through `hand_off` (the worker's `on_done`): the session found by
id, `saves.alive` asked, the turn lock TRIED -- taken: `apply_media_result`
and the `media_ready` push; busy: parked in the session's inbox for the next
holder (`voicer.drain_inbox`). A result for a run that is not live writes
nothing. On resume every unfinished row is resubmitted with its stored
request (`resubmit_unfinished`: the same seed and prompt, so idempotent).

VOICE NOTES (spec §13.6, T21). The engine decides a voice note exactly as
a photo (above); the model writes only its TRANSCRIPT (the voice schema's
`media.caption` when the medium is voice), held and checked as a reply's
bubbles are (`voicing.transcript_failures`), and cut here by LENGTH only:
`media.yaml` `voice.max_seconds` of words at `VOICE_WORDS_PER_MINUTE`
(rule 12: nothing reads what it says). With `tts.enabled` (config, off by
default) the transcript is spoken in the person's own voice (`voice_id`,
drawn from `tts.voices` of their sex) on the process's `SpeechWorker`,
uncached, and the WAV -- typed by its magic bytes, at most `tts.max_bytes`,
at most `VOICE_AUDIO_SLACK` x the cap long -- is stored beside the save's
other media and handed back through `hand_off`; each new note is one of
the account's `phone_media.daily_job_cap` jobs (`MediaJobWorker.charge`),
and a resubmission of one still queued is retargeted, never queued twice
(`SpeechWorker.submit(key=)`). With TTS off, down, too
slow (`tts.job_timeout_seconds`) or the person voiceless, the row is
`fallback` (`voice_fallback`): the waveform tile, the estimated `seconds`
and the transcript. A voice row is `{transcript, seconds, url | ""}` on top
of the common row. The player's own voice note is a transcript only
(`messaging.send`, spec §13.7): its audio is never kept.

THE PROMPT (`photo_request`, spec §13.3): the person's fixed `appearance`,
the subject's scene, the caption as written (at most 200 characters), the
time of day and their status, and the story's `style`, joined. There is no
negative prompt and nothing here reads, filters or rewrites what is asked
for (AGENTS.md rule 12): the only processing is the length cap.

Version: v0.2.0 [2026-10-12]
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Any, Optional

from engine import social
from engine.config import get_config
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.rng import SOCIAL_MEDIA, _mix
from engine.game.state import GameState
from engine.social import apps, behaviour, events, messaging, population, relationships
from engine.social.kinds import MEDIA_KINDS, Decision, recorded, stage_rank
from engine.social.payload import section

logger = logging.getLogger(__name__)

#: A row's kinds (spec §13.2): a person's photo, voice note or video, their portrait, the player's own.
ROW_KINDS: tuple[str, ...] = ("photo", "voice", "video", "portrait", "own")
#: A row's statuses (spec §13.2).
STATUSES: tuple[str, ...] = ("requested", "submitted", "running", "ready", "failed", "fallback")
#: Statuses a resume resubmits (§13.2) -- `requested` waits for the next mechanics action instead.
IN_FLIGHT: tuple[str, ...] = ("submitted", "running")
#: The worker's order (spec §13.4 "Scheduling"): thread media, the player's own, portraits.
PRIORITY: tuple[tuple[str, int], ...] = (("photo", 0), ("voice", 0), ("video", 0), ("own", 1), ("portrait", 2))
#: Which `comfyui.workflows.<name>` makes each kind; a kind with none is procedural (a voice note is the
#: speech worker's, never ComfyUI's: `voice_due`).
WORKFLOW_FOR: tuple[tuple[str, str], ...] = (("photo", "photo"), ("video", "video"), ("portrait", "portrait"))
#: `phone_media.portraits` (spec §13.4).
PORTRAIT_POLICIES: tuple[str, ...] = ("off", "on_match", "on_view")
#: The request's answers (spec §13.1).
ANSWERS: tuple[str, ...] = ("accept", "decline", "later")
#: A request's answer -> the request row's status.
ANSWER_STATUS: tuple[tuple[str, str], ...] = (("accept", "yes"), ("decline", "no"), ("later", "later"))
#: Every block media.yaml must carry.
BLOCKS: tuple[str, ...] = ("budget", "request", "unsolicited", "subjects", "player_subjects", "portrait", "style",
                           "voice")
#: A caption's cap in the image prompt (spec §13.3: "<= 200 chars, as written").
CAPTION_PROMPT_CHARS = 200
#: How a refusal names one of a kind ("It's too soon to ask Kai for a voice note.").
ONE_OF: tuple[tuple[str, str], ...] = (("photo", "a photo"), ("voice", "a voice note"), ("video", "a video"))
#: A voice note's reading pace (spec §13.6): its seconds are its words at this rate.
VOICE_WORDS_PER_MINUTE = 150
#: A spoken note may run this many times `voice.max_seconds` before its audio is refused (a bound on the file).
VOICE_AUDIO_SLACK = 2.0
#: A voice row's `provider` once the speech worker took it.
VOICE_PROVIDER = "tts"
#: The hand-off's outcomes, reported as the `phone` metric's `media_job` event.
HAND_OFF_STATUSES: tuple[str, ...] = ("ok", "failed", "fallback", "dropped")


# -- the data (media.yaml, rule 10) ------------------------------------------------------------


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: media.yaml: {key}: {message}")


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def media_faults(data: dict[str, Any], population_data: Optional[dict[str, Any]] = None,
                 relationships_data: Optional[dict[str, Any]] = None) -> list[tuple[str, str]]:
    """
    Every fault of media.yaml as (key, message): its blocks and their shapes,
    every `requires_flag` a population.yaml `flags` fact, every subject's
    `when` a schedule status, every `unlock_stage` a stage, every
    `mood_mult` key a relationships.yaml mood value.
    """
    out: list[tuple[str, str]] = []
    if not data:
        return out
    for name in BLOCKS:
        if name not in data:
            out.append((name, "required (spec §13.1)"))
    if out:
        return out
    from engine.social.kinds import STAGES

    budget = data["budget"]
    for kind in MEDIA_KINDS:
        row = budget.get(kind) if isinstance(budget, dict) else None
        if not isinstance(row, dict):
            out.append((f"budget.{kind}", "required: {start, per_episode, cap, unlock_stage}"))
            continue
        for key in ("start", "per_episode", "cap"):
            if not _num(row.get(key)) or row[key] < 0:
                out.append((f"budget.{kind}.{key}", f"must be a number, 0 or more, not {row.get(key)!r}"))
        if row.get("unlock_stage") not in STAGES:
            out.append((f"budget.{kind}.unlock_stage", f"{row.get('unlock_stage')!r} is no stage"))
    request = data["request"] if isinstance(data["request"], dict) else {}
    accept = request.get("accept") if isinstance(request.get("accept"), dict) else {}
    for key in ("base", "trust_per_10", "warmth_per_10"):
        if not _num(accept.get(key)):
            out.append((f"request.accept.{key}", "required: a number"))
    share = request.get("later_share")
    if not _num(share) or not 0 <= share <= 1:
        out.append(("request.later_share", f"must be a number from 0 to 1, not {share!r}"))
    mood_mult = request.get("mood_mult")
    if not isinstance(mood_mult, dict) or not all(_num(v) for v in mood_mult.values()):
        out.append(("request.mood_mult", "must map mood values to numbers"))
    elif relationships_data:
        values = ((relationships_data.get("mood") or {}).get("values")) or []
        for mood in mood_mult:
            if mood not in values:
                out.append((f"request.mood_mult.{mood}", "is no relationships.yaml mood value"))
    unsolicited = data["unsolicited"] if isinstance(data["unsolicited"], dict) else {}
    per_stage = unsolicited.get("per_episode_at_stage")
    if not isinstance(per_stage, dict) or not per_stage:
        out.append(("unsolicited.per_episode_at_stage", "must map stages to chances"))
    else:
        for stage, p in per_stage.items():
            if stage_rank(stage) < 0:
                out.append((f"unsolicited.per_episode_at_stage.{stage}", "is no live stage"))
            if not _num(p) or not 0 <= p <= 1:
                out.append((f"unsolicited.per_episode_at_stage.{stage}", f"must be a chance 0-1, not {p!r}"))
    if not _num(unsolicited.get("offered_mult")):
        out.append(("unsolicited.offered_mult", "required: a number"))
    flags = set(((population_data or {}).get("flags") or {}).keys()) if population_data else None
    subjects = data["subjects"]
    if not isinstance(subjects, list) or not subjects:
        out.append(("subjects", "must be a non-empty list of {id, when, label, scene}"))
        subjects = []
    seen: set[str] = set()
    for i, row in enumerate(subjects):
        where = f"subjects[{i}]"
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            out.append((where, "must be {id, when, label, scene}"))
            continue
        if row["id"] in seen:
            out.append((f"{where}.id", f"{row['id']!r} is listed twice"))
        seen.add(row["id"])
        when = row.get("when")
        whens = when if isinstance(when, list) else [when]
        if not whens or any(w not in behaviour.STATUSES for w in whens):
            out.append((f"{where}.when", f"each must be one of {', '.join(behaviour.STATUSES)}, not {when!r}"))
        flag = row.get("requires_flag")
        if flag is not None and flags is not None and flag not in flags:
            out.append((f"{where}.requires_flag", f"{flag!r} is no population.yaml flag"))
        for key in ("label", "scene"):
            if not isinstance(row.get(key), str) or not row[key]:
                out.append((f"{where}.{key}", "required: text"))
    players = data["player_subjects"]
    if not isinstance(players, list):
        out.append(("player_subjects", "must be a list of {id, kinds, label, scene}"))
        players = []
    for i, row in enumerate(players):
        where = f"player_subjects[{i}]"
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            out.append((where, "must be {id, kinds, label, scene}"))
            continue
        kinds = row.get("kinds")
        if not isinstance(kinds, list) or not kinds or any(k not in ("photo", "video") for k in kinds):
            out.append((f"{where}.kinds", "each must be photo or video"))
        for key in ("label", "scene"):
            if not isinstance(row.get(key), str) or not row[key]:
                out.append((f"{where}.{key}", "required: text"))
    if not isinstance((data["portrait"] or {}).get("scene") if isinstance(data["portrait"], dict) else None, str):
        out.append(("portrait.scene", "required: text"))
    if not isinstance(data["style"], str):
        out.append(("style", "must be text"))
    voice = data["voice"] if isinstance(data["voice"], dict) else {}
    if not _num(voice.get("max_seconds")) or voice["max_seconds"] <= 0:
        out.append(("voice.max_seconds", "required: seconds, above 0"))
    return out


def check_data(data: dict[str, Any], population_data: Optional[dict[str, Any]] = None,
               relationships_data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """media.yaml whole, at load: the first fault a ValueError naming the file and the key."""
    faults = media_faults(data, population_data, relationships_data)
    if faults:
        key, message = faults[0]
        raise _fault(key, message)
    return data


def _data() -> dict[str, Any]:
    return social.data("media")


def _block(name: str) -> Any:
    data = _data()
    if name not in data:
        raise _fault(name, "required (spec §13.1)")
    return data[name]


def _budget_row(kind: str) -> dict[str, Any]:
    return dict((_block("budget") or {}).get(kind) or {})


# -- reading a person --------------------------------------------------------------------------


def _person(state: GameState, pid: str) -> dict[str, Any]:
    """READ ONLY: a person's dynamic slice, {} when there is none."""
    return ((state.social or {}).get("people") or {}).get(pid) or {}


def budget_of(person_state: dict[str, Any], kind: str) -> float:
    """What `kind` budget a person holds now (their `media_budget`, else the data's `start`)."""
    held = person_state.get("media_budget")
    if isinstance(held, dict) and kind in held:
        return float(held[kind] or 0)
    return float(_budget_row(kind).get("start", 0))


def unlocked(state: GameState, pid: str, kind: str) -> bool:
    """The person's stage has reached the kind's `unlock_stage` (a live stage at or past it)."""
    stage = _person(state, pid).get("stage")
    need = stage_rank(_budget_row(kind).get("unlock_stage"))
    return need >= 0 and stage_rank(stage) >= need


def can_carry(state: GameState, thread_id: str, kind: str) -> bool:
    """The thread is open and its app can carry `kind` (apps.yaml `capabilities`)."""
    t = messaging.thread(state, thread_id)
    return t is not None and not t.get("closed") and kind in apps.capabilities(str(t["app"]))


def media_thread(state: GameState, pid: str, kind: str, prefer: str = "") -> Optional[str]:
    """Where they would send `kind`: `prefer` if it can carry it, else their last thread, else the first that can."""
    threads = (state.social or {}).get("threads") or {}
    order = [prefer, str(_person(state, pid).get("last_thread") or "")]
    order += sorted(tid for tid, t in threads.items() if t.get("pid") == pid)
    for tid in order:
        if tid and threads.get(tid, {}).get("pid") == pid and can_carry(state, tid, kind):
            return tid
    return None


def offer_open(state: GameState, pid: str, kind: str) -> bool:
    """An `offer_<kind>` proposal is open (spec §10.5): budget >= 1, the stage unlocked, a thread that can carry it."""
    if apps.gone(state, pid) or kind not in MEDIA_KINDS:
        return False
    return (budget_of(_person(state, pid), kind) >= 1 and unlocked(state, pid, kind)
            and media_thread(state, pid, kind) is not None)


# -- time of day and subjects ------------------------------------------------------------------


def daypart(hour: float) -> str:
    """`morning` 5-12, `afternoon` 12-17, `evening` 17-22, else `night` (engine words)."""
    h = float(hour) % 24
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


def now_for(state: GameState, person: population.Person, at: Optional[float] = None) -> dict[str, Any]:
    """
    `payload.now_block(state)` plus `daypart` and the person's schedule
    `status` at in-game hour ``at`` (now by default): the producer of
    `photo_request`'s `now`.
    """
    from engine.social import payload

    at = state.world_clock_hours if at is None else float(at)
    out = dict(payload.now_block(state))
    out["daypart"] = daypart(at)
    out["status"] = behaviour.status_at(person, at)
    return out


def _subjects() -> list[dict[str, Any]]:
    return [row for row in _data().get("subjects") or () if isinstance(row, dict)]


def subject_row(subject_id: str) -> dict[str, Any]:
    """A person's subject (`subjects`) or the player's (`player_subjects`) by id; {} for none."""
    for row in _subjects() + player_subjects():
        if row.get("id") == subject_id:
            return dict(row)
    return {}


def subject_label(subject_id: str) -> str:
    """The words the voice prompt names a subject by (its `label`), else the id with spaces."""
    row = subject_row(subject_id)
    return str(row.get("label") or subject_id.replace("_", " "))


def subjects_for(state: GameState, pid: str, at: float) -> list[str]:
    """The subject ids that fit `pid` at hour `at`: `when` holds their status; `requires_flag` a fixed FLAG."""
    person = population.profile(state, pid)
    status = behaviour.status_at(person, at)
    out = []
    for row in _subjects():
        when = row.get("when")
        whens = when if isinstance(when, list) else [when]
        if status not in whens:
            continue
        flag = row.get("requires_flag")
        if flag and not person.has_flag(str(flag)):
            continue
        out.append(str(row["id"]))
    return out


def player_subjects(kind: str = "") -> list[dict[str, Any]]:
    """The player's `player_subjects` rows (those that may be sent as `kind`, when given)."""
    rows = [dict(row) for row in (_data().get("player_subjects") or ()) if isinstance(row, dict)]
    return [row for row in rows if not kind or kind in (row.get("kinds") or ())]


def player_photos(state: GameState) -> list[str]:
    """The player's camera roll: their profile photos (`photo_set` ids, spec §3.3)."""
    return [str(p) for p in ((state.social or {}).get("player") or {}).get("photos") or ()]


def _situation(kind: str, subject: str) -> str:
    if kind == "photo":
        return "send_selfie" if subject == "selfie_now" else "send_photo"
    return f"send_{kind}"


def send_decision(kind: str, subject: str, request_id: str = "") -> Decision:
    """The due message that carries `kind` (spec §11.2: its `media` caption declared)."""
    return Decision(situation=_situation(kind, subject), kind=kind, media_kind=kind, subject=subject,
                    request_id=request_id)


# -- the image request (spec §13.3) ------------------------------------------------------------


def _sampler_values() -> dict[str, Any]:
    """The five sampler keys every image workflow binds (comfyui.*, spec §13.4)."""
    cfg = get_config()
    return {"checkpoint": str(cfg.get("comfyui.checkpoint", "sd_xl_base_1.0.safetensors")),
            "steps": int(cfg.get("comfyui.steps", 28)),
            "cfg_scale": float(cfg.get("comfyui.cfg_scale", 6.5)),
            "sampler": str(cfg.get("comfyui.sampler", "dpmpp_2m")),
            "scheduler": str(cfg.get("comfyui.scheduler", "karras"))}


def photo_request(person: population.Person, subject: dict[str, Any], caption: str, now: dict[str, Any], *,
                  mid: str, seed: int, workflow: Any) -> dict[str, Any]:
    """
    The bind values of one image or video job (spec §13.3, complete; rule
    12: the only processing is the length cap). No negative prompt. Only the
    sampler keys the workflow binds are carried (T20 fix round 1): an
    unbound one would change the request's digest and bind nothing.
    """
    style = str(social.data("media").get("style") or "")
    parts = [person.appearance, str(subject.get("scene") or subject.get("label") or ""),
             caption[:CAPTION_PROMPT_CHARS], f"{now['daypart']}, {now['status']}", style]
    positive = ", ".join(p.strip() for p in parts if p and p.strip())
    return {"positive": positive, "seed": seed, "width": workflow.size["width"],
            "height": workflow.size["height"], "filename_prefix": f"phone/{mid}",
            **{k: v for k, v in _sampler_values().items() if k in workflow.bindings},
            **({"frames": workflow.size["frames"]} if "frames" in workflow.size else {})}


def _label_of(table: str, ident: Any) -> str:
    for row in population.table(table):
        if isinstance(row, dict) and row.get("id") == ident:
            return str(row.get("label", ident))
    return str(ident or "")


def player_look(state: GameState) -> SimpleNamespace:
    """The player as an image subject: their creation profile's age, sex and looks, joined (spec §3.3)."""
    player = (state.social or {}).get("player") or {}
    attrs = player.get("attributes") or {}
    parts = [f"{player.get('age', '')}-year-old {player.get('sex', '')}".strip(" -"),
             _label_of("hair", attrs.get("hair")), str(attrs.get("build") or ""), _label_of("style", attrs.get("style"))]
    return SimpleNamespace(appearance=", ".join(p for p in parts if p))


def face_seed(state: GameState, pid: str) -> int:
    """A person's portrait seed: the same face in every process (spec §13.3)."""
    return _mix(state.rng_seed, f"{SOCIAL_MEDIA}:face:{pid}", 0) % 2**31


def media_seed(state: GameState, pid: str, mid: str) -> int:
    """A sent medium's seed (spec §13.3)."""
    return _mix(state.rng_seed, f"{SOCIAL_MEDIA}:{pid}:{mid}", 0) % 2**31


# -- decisions (spec §13.1, §10.5) -------------------------------------------------------------


def _mood_mult(state: GameState, pid: str) -> float:
    """The mood's multiplier on accepting, held inside relationships.yaml `mood.media_mult`."""
    mood = relationships.mood_now(_person(state, pid), state.world_clock_hours)
    raw = float(((_block("request") or {}).get("mood_mult") or {}).get(mood, 1.0))
    low, high = (relationships._block("mood") or {}).get("media_mult") or [raw, raw]
    return max(float(low), min(float(high), raw))


def accept_p(state: GameState, pid: str, mult: float = 1.0) -> float:
    """The accept odds (spec §13.1): base + trust and warmth per 10, x archetype, x mood, x the ask's repeat."""
    person_state = _person(state, pid)
    accept = (_block("request") or {}).get("accept") or {}
    base = (float(accept.get("base", 0)) + float(accept.get("trust_per_10", 0)) * float(person_state.get("trust", 0)) / 10
            + float(accept.get("warmth_per_10", 0)) * float(person_state.get("warmth", 0)) / 10)
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    p = base * float(arch.media.get("accept_mult", 1.0)) * _mood_mult(state, pid) * float(mult)
    return max(0.0, min(1.0, p))


def _draw(state: GameState, pid: str) -> float:
    """One draw on SOCIAL_MEDIA for `pid` (inside a social_* handler: its counter is state)."""
    return behaviour.person_rng(state, SOCIAL_MEDIA, pid).random()


def unsolicited_draw(state: GameState, pid: str, kind: str, mult: float = 1.0) -> bool:
    """
    Whether they send `kind` unasked now: one draw at the stage's
    `unsolicited.per_episode_at_stage` (the highest listed stage at or below
    theirs) x the archetype's `media.offer_mult` x `mult`.
    """
    stage_p = _stage_chance(_person(state, pid).get("stage"))
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    p = max(0.0, min(1.0, stage_p * float(arch.media.get("offer_mult", 1.0)) * float(mult)))
    return _draw(state, pid) < p


def _stage_chance(stage: Any) -> float:
    rank = stage_rank(stage)
    best, chance = -1, 0.0
    for name, p in ((_block("unsolicited") or {}).get("per_episode_at_stage") or {}).items():
        r = stage_rank(name)
        if 0 <= r <= rank and r > best:
            best, chance = r, float(p)
    return chance


def decide_request(state: GameState, pid: str, what: str, *, at: Optional[float] = None) -> dict[str, Any]:
    """
    The person's answer to the player's ask for `what` (spec §13.1),
    decided by the engine through `social_media_decision`: ``{"answer":
    accept | decline | later, "draw", "p", "subject", "why"}``. An accept
    spends one of their budget.
    """
    return apply_effect(state, {"type": "social_media_decision", "op": "request", "pid": pid, "what": what,
                                "at": state.world_clock_hours if at is None else float(at)})


def offer(state: GameState, pid: str, kind: str, *, thread_id: str = "") -> dict[str, Any]:
    """A model's `offer_<kind>` proposal (spec §10.5), re-checked and drawn by the engine; on success a new due message."""
    return apply_effect(state, {"type": "social_media_decision", "op": "offer", "pid": pid, "what": kind,
                                "thread_id": thread_id})


def _decide(state: GameState, pid: str, what: str, at: float, *, mult: float, later: bool,
            spend: bool = True) -> dict[str, Any]:
    """INSIDE a handler: the request decision (draws; spends on accept unless ``spend`` is False)."""
    person_state = state.social["people"].setdefault(pid, {})
    out: dict[str, Any] = {"answer": "decline", "draw": None, "p": 0.0, "subject": "", "why": ""}
    if what not in MEDIA_KINDS:
        out["why"] = "kind"
        return out
    if not unlocked(state, pid, what):
        out["why"] = "stage"
        return out
    if budget_of(person_state, what) < 1:
        out["why"] = "budget"
    subject = ""
    if not out["why"] and what != "voice":
        fits = subjects_for(state, pid, at)
        if not fits:
            out["why"] = "subject"
        else:
            subject = fits[int(_draw(state, pid) * len(fits)) % len(fits)]
    if not out["why"]:
        p = accept_p(state, pid, mult)
        draw = _draw(state, pid)
        out.update(p=p, draw=draw)
        if draw < p:
            out.update(answer="accept", subject=subject)
            if spend:
                _spend(person_state, what)
            return out
        out["why"] = "draw"
    if later and _draw(state, pid) < float((_block("request") or {}).get("later_share", 0)):
        out["answer"] = "later"
    return out


def _spend(person_state: dict[str, Any], kind: str) -> None:
    """INSIDE a handler: one of `kind` spent."""
    held = person_state.get("media_budget")
    if not isinstance(held, dict):
        held = person_state["media_budget"] = {}
    held[kind] = round(budget_of(person_state, kind) - 1.0, 6)
    relationships.touch(person_state)


@effect_kind("social_media_decision")
@recorded
def _e_decision(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: a media decision and its budget spend (spec §13.1, §10.5).
    `op: request` -- the player's ask answered (the pending request's repeat
    multiplier read); `op: offer` -- a model's `offer_<kind>` proposal: open
    now, then the unsolicited draw at `offered_mult`; on success the budget
    spent and a NEW due message of that kind lands at once, its media
    attached (its own decision, its own voicing).
    """
    if not state.social:
        return {"type": "social_media_decision", "ok": False, "text": "no social slice"}
    pid, what = str(effect.get("pid") or ""), str(effect.get("what") or "")
    op = str(effect.get("op") or "request")
    if op == "request":
        waiting = relationships._pending(state, pid, "player", what)
        mult = float(waiting[0].get("mult", 1.0)) if waiting else 1.0
        decided = _decide(state, pid, what, float(effect.get("at", state.world_clock_hours)), mult=mult, later=True)
        return {"type": "social_media_decision", "ok": True, "text": f"{pid}: {what} {decided['answer']}",
                **decided}
    if op == "offer":
        tid = media_thread(state, pid, what, prefer=str(effect.get("thread_id") or ""))
        if not offer_open(state, pid, what) or tid is None:
            return {"type": "social_media_decision", "ok": False, "text": f"offer_{what} is not open"}
        mult = float((_block("unsolicited") or {}).get("offered_mult", 1.0))
        if not unsolicited_draw(state, pid, what, mult):
            return {"type": "social_media_decision", "ok": True, "text": f"{pid} did not send a {what}",
                    "sent": False}
        at = state.world_clock_hours
        subject = ""
        if what != "voice":
            fits = subjects_for(state, pid, at)
            if not fits:
                return {"type": "social_media_decision", "ok": True, "text": f"{pid}: no {what} subject now",
                        "sent": False}
            subject = fits[int(_draw(state, pid) * len(fits)) % len(fits)]
        _spend(state.social["people"].setdefault(pid, {}), what)
        decision = send_decision(what, subject)
        message = messaging.new_message(state, tid, pid, what, at=at, bubbles=(), voiced=False,
                                        decision=_asdict(decision))
        mid = attach(state, pid, tid, message["id"], what, subject)
        return {"type": "social_media_decision", "ok": True, "text": f"{pid} sent a {what}", "sent": True,
                "message_id": message["id"], "mid": mid}
    if op == "episode":
        return _after_episode(state, pid, float(effect.get("at", state.world_clock_hours)))
    return {"type": "social_media_decision", "ok": False, "text": f"{op!r} is no decision op"}


def _asdict(decision: Decision) -> dict[str, Any]:
    import dataclasses

    return dataclasses.asdict(decision)


def answer_request(state: GameState, pid: str, request: dict[str, Any], thread_id: str, at: float,
                   shape: Decision) -> dict[str, Any]:
    """
    At their read (inside the read handler): the player's media ask decided,
    the request answered (`yes`, `no` or `later`), and the answer due at the
    read's own minute (v0.23.0 §4.3) -- the medium itself (`send_*`), or the
    decline in their words -- in the conversation's `shape` (`convo.decide`:
    its mode, bubbles and end).
    """
    import dataclasses

    what = str(request["what"])
    decided = decide_request(state, pid, what, at=at)
    status = dict(ANSWER_STATUS)[decided["answer"]]
    apply_effect(state, {"type": "social_request", "op": "answer", "request_id": request["id"],
                         "status": status, "at": at})
    where = thread_id if can_carry(state, thread_id, what) else (media_thread(state, pid, what) or thread_id)
    if decided["answer"] == "accept":
        own = send_decision(what, str(decided.get("subject") or ""), str(request["id"]))
        decision = dataclasses.replace(shape, situation=own.situation, kind=own.kind, media_kind=own.media_kind,
                                       subject=own.subject, request_id=own.request_id)
    else:
        decision = dataclasses.replace(shape, situation=f"decline_{what}", kind="decline",
                                       request_id=str(request["id"]))
    messaging.queue_due(state, pid, where, decision, at)
    return {"ok": True, what: decided["answer"]}


def ask_refusal(state: GameState, pid: str, thread_id: str, what: str) -> str:
    """
    Why the player may not ask `pid` for `what` in this thread now: the app
    cannot carry it, their stage is too early, or past `asks.per_episode`
    asks of the kind this episode ("Give it a while", spec §6.4, §10.6).
    Never the budget: that is theirs to decline.
    """
    name = relationships._name(state, pid)
    t = messaging.thread(state, thread_id)
    noun = dict(messaging.NOUNS).get(what, what)
    if t is not None and what not in apps.capabilities(str(t["app"])):
        return f"{apps.label(str(t['app']))} can't send {noun}"
    if not unlocked(state, pid, what):
        return f"It's too soon to ask {name} for {dict(ONE_OF).get(what, what)}."
    if relationships.asks_this_episode(state, pid, what) >= int(relationships._block("asks")["per_episode"]):
        return relationships.GIVE_IT_A_WHILE
    return ""


# -- the rows (spec §13.2) ---------------------------------------------------------------------


def _rows(state: GameState) -> dict[str, Any]:
    return (state.social or {}).get("media") or {}


def row(state: GameState, mid: str) -> Optional[dict[str, Any]]:
    """READ ONLY: one media row, or None."""
    return _rows(state).get(mid)


def attach(state: GameState, pid: str, thread_id: str, message_id: str, kind: str, subject: str) -> str:
    """A media row `requested` for a message of theirs (or the player's own: `kind="own"`); its `mid`."""
    result = apply_effect(state, {"type": "social_media", "op": "attach", "pid": pid, "thread_id": thread_id,
                                  "message_id": message_id, "kind": kind, "subject": subject})
    if not result.get("ok"):
        raise ValueError(f"social: media.attach: {result.get('text')}")
    return str(result["mid"])


def attach_own(state: GameState, thread_id: str, message_id: str, sends: str, subject: str, photo_id: str) -> str:
    """The player's own photo or video (spec §13.7): a row `own`, priority 1."""
    result = apply_effect(state, {"type": "social_media", "op": "attach", "pid": "player", "thread_id": thread_id,
                                  "message_id": message_id, "kind": "own", "subject": subject,
                                  "photo_id": photo_id, "sends": sends})
    if not result.get("ok"):
        raise ValueError(f"social: media.attach_own: {result.get('text')}")
    return str(result["mid"])


def mark_procedural(state: GameState, mid: str) -> None:
    """A row straight to `fallback` with its procedural tile (no service, the cap, no workflow)."""
    apply_effect(state, {"type": "social_media", "op": "procedural", "mid": mid})


def mark_submitted(state: GameState, mid: str, request: dict[str, Any], *, account: str, provider: str,
                   digest: str = "") -> None:
    """The worker took the job: the row `submitted`, with the request a resume resubmits unchanged and its
    digest (`JobSpec.digest`), which a result must carry to be applied (review I1)."""
    apply_effect(state, {"type": "social_media", "op": "submitted", "mid": mid, "request": request,
                         "account": account, "provider": provider, "digest": digest})


def apply_media_result(state: GameState, result: Any, digest: str = "") -> dict[str, Any]:
    """
    A finished job's `JobResult` on its row, through `social_media` (CALLER
    HOLDS the turn lock). With ``digest`` (the job's request), a row whose
    own request differs refuses it: another request under a reused `mid`.
    """
    return apply_effect(state, {"type": "social_media", "op": "result", "mid": str(result.mid), "digest": digest,
                                "status": str(result.status), "url": str(result.url or ""),
                                "poster_url": str(result.poster_url or ""), "path": str(result.path or ""),
                                "error": str(result.error or ""), "attempts": int(result.attempts or 0),
                                "seconds": float(getattr(result, "seconds", 0.0) or 0.0)})


def _priority(kind: str) -> int:
    return dict(PRIORITY).get(kind, 0)


@effect_kind("social_media")
@recorded
def _e_media(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: a media row (spec §13.2). Ops: `attach` (a new row
    `requested`; a thread message's `media_id` set; a portrait recorded on
    the person), `submitted` (the job taken, its request kept), `result`
    (`ready`: the file's URL, a voice note's measured `seconds`; `failed`:
    the procedural stand-in for good, `fallback`, the error kept),
    `procedural` (`fallback` at once) and `voice` (a voice note's
    transcript, cut to `voice.max_seconds`, and its estimated `seconds`, on
    the row and its message; with `fallback`, the transcript tile for good).
    """
    if not state.social:
        return {"type": "social_media", "ok": False, "text": "no social slice"}
    rows = state.social.setdefault("media", {})
    op = str(effect.get("op") or "")
    at = state.world_clock_hours
    if op == "attach":
        kind = str(effect.get("kind") or "")
        if kind not in ROW_KINDS:
            return {"type": "social_media", "ok": False, "text": f"{kind!r} is no media kind"}
        pid = str(effect.get("pid") or "")
        tid, message_id = str(effect.get("thread_id") or ""), str(effect.get("message_id") or "")
        message = None
        if message_id:
            t = (state.social.get("threads") or {}).get(tid) or {}
            message = next((m for m in t.get("messages") or [] if m["id"] == message_id), None)
            if message is None:
                return {"type": "social_media", "ok": False, "text": f"no message {message_id} in {tid}"}
        counters = state.social.setdefault("counters", {})
        counters["media"] = int(counters.get("media", 0)) + 1
        mid = f"x{counters['media']}"
        if kind == "portrait":
            seed = face_seed(state, pid)
        elif kind == "own":
            seed = media_seed(state, "player", mid)
        else:
            seed = media_seed(state, pid, mid)
        row_ = {"mid": mid, "kind": kind, "pid": pid, "thread_id": tid, "message_id": message_id,
                "subject": str(effect.get("subject") or ""), "caption": "", "seed": seed,
                "priority": _priority(kind), "account": "", "status": "requested", "provider": "",
                "prompt_id": "", "attempts": 0, "url": "", "poster_url": "", "error": "",
                "created_at": at, "finished_at": None}
        if kind == "own":
            row_["sends"] = str(effect.get("sends") or "photo")
            row_["photo_id"] = str(effect.get("photo_id") or "")
            if message is not None and message.get("bubbles"):
                row_["caption"] = str(message["bubbles"][0])
        rows[mid] = row_
        if message is not None:
            message["media_id"] = mid
        if kind == "portrait":
            person_state = state.social.setdefault("people", {}).setdefault(pid, {})
            person_state["portrait"] = mid
            relationships.touch(person_state)
        return {"type": "social_media", "ok": True, "text": f"{mid} attached ({kind})", "mid": mid}
    mid = str(effect.get("mid") or "")
    row_ = rows.get(mid)
    if row_ is None:
        return {"type": "social_media", "ok": False, "text": f"no media row {mid!r}"}
    if op == "submitted":
        if row_["status"] not in ("requested", "submitted", "running"):
            return {"type": "social_media", "ok": False, "text": f"{mid} is {row_['status']}"}
        row_.update(status="submitted", request=dict(effect.get("request") or {}),
                    account=str(effect.get("account") or ""), provider=str(effect.get("provider") or ""),
                    digest=str(effect.get("digest") or ""))
        return {"type": "social_media", "ok": True, "text": f"{mid} submitted"}
    if row_["status"] in ("ready", "fallback"):
        return {"type": "social_media", "ok": False, "text": f"{mid} is already {row_['status']}"}
    if op == "voice":
        if row_["kind"] != "voice":
            return {"type": "social_media", "ok": False, "text": f"{mid} is no voice note"}
        transcript = voice_transcript(str(effect.get("transcript") or ""))
        row_.update(transcript=transcript, seconds=voice_note_seconds(transcript))
        message = _message_of(state, row_)
        if message is not None:
            message["transcript"] = transcript
        if effect.get("fallback"):
            row_.update(status="fallback", url="", poster_url="", finished_at=at)
        return {"type": "social_media", "ok": True, "text": f"{mid} voice ({row_['status']})", "mid": mid}
    if op == "procedural":
        row_.update(status="fallback", url="", poster_url="", finished_at=at)
        return {"type": "social_media", "ok": True, "text": f"{mid} procedural", "mid": mid}
    if op == "result":
        digest = str(effect.get("digest") or "")
        if digest and row_.get("digest") and digest != row_["digest"]:
            return {"type": "social_media", "ok": False, "text": f"{mid}: a result of another request"}
        status = str(effect.get("status") or "")
        if status == "ready":
            from pathlib import PurePath

            row_.update(status="ready", url=str(effect.get("url") or ""), poster_url=str(effect.get("poster_url") or ""),
                        file=PurePath(str(effect.get("path") or "")).name, error="",
                        attempts=int(effect.get("attempts") or 0), finished_at=at)
            if row_["kind"] == "voice" and float(effect.get("seconds") or 0) > 0:
                row_["seconds"] = round(float(effect["seconds"]), 2)   # the audio's own length
        else:
            row_.update(status="fallback", url="", poster_url="", error=str(effect.get("error") or status)[:300],
                        attempts=int(effect.get("attempts") or 0), finished_at=at)
        return {"type": "social_media", "ok": True, "text": f"{mid} {row_['status']}", "mid": mid}
    return {"type": "social_media", "ok": False, "text": f"{op!r} is no media op"}


# -- what the client sees ------------------------------------------------------------------------


def media_view(state: GameState, mid: str) -> Optional[dict[str, Any]]:
    """A row as the client may see it: kind, `sending|ready|fallback`, the URLs and the caption (a voice note's
    transcript and seconds too). No seed, no prompt."""
    row_ = row(state, mid)
    if row_ is None:
        return None
    status = row_["status"] if row_["status"] in ("ready", "fallback") else "sending"
    view = {"mid": mid, "kind": row_["kind"], "status": status, "url": row_.get("url") or "",
            "poster_url": row_.get("poster_url") or "", "caption": row_.get("caption") or ""}
    if row_["kind"] == "voice":
        view.update(transcript=row_.get("transcript") or "", seconds=float(row_.get("seconds") or 0.0))
    return view


#: The Photos app's received media, at most (newest first): a bound on the payload, not a balance number.
GALLERY_MAX = 60
#: What the Photos app shows as received: their photos and videos (voice notes stay in their threads).
GALLERY_KINDS: tuple[str, ...] = ("photo", "video")


@section("gallery", time_varying=True)
def _gallery_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """
    The Photos app's received media (v0.22.0 T29, spec §18.2): each photo or video a person sent,
    newest first, as `media_view` shows it, with who sent it and where. Only what their thread would
    show: a thread unmatched or blocked away, a message not yet voiced (its words are still "...")
    or withdrawn, shows nothing here either. The player's own camera roll is `player.camera_roll`.
    """
    from engine.social import matching   # lazily: matching reaches this module through messaging

    out: list[dict[str, Any]] = []
    threads = state.social.get("threads") or {}
    for row_ in sorted(_rows(state).values(), key=lambda r: (-float(r.get("created_at") or 0.0),
                                                            -int(str(r.get("mid") or "x0")[1:] or 0))):
        if row_.get("kind") not in GALLERY_KINDS or row_.get("pid") in ("", "player"):
            continue
        t = threads.get(str(row_.get("thread_id") or ""))
        if t is None or not matching.listed(t):
            continue
        message = next((m for m in t.get("messages") or () if m.get("id") == row_.get("message_id")), None)
        if message is not None and (message.get("voiced") is False or not messaging.shown(message)):
            continue
        view = media_view(state, str(row_["mid"]))
        if view is None:
            continue
        out.append({**view, "pid": str(row_["pid"]), "name": relationships._name(state, str(row_["pid"])),
                    "thread_id": str(row_["thread_id"]), "message_id": str(row_.get("message_id") or ""),
                    "at": row_.get("created_at")})
        if len(out) >= GALLERY_MAX:
            break
    return out


def portrait_url(state: GameState, pid: str) -> str:
    """The person's ready portrait's URL, else "" (the client draws the procedural tile)."""
    mid = _person(state, pid).get("portrait")
    row_ = row(state, str(mid)) if mid else None
    return str(row_.get("url") or "") if row_ is not None and row_["status"] == "ready" else ""


def ready_payload(state: GameState, mid: str, session: Any = None) -> dict[str, Any]:
    """`media_ready` (spec §17.3): `{message_id, mid, url, poster_url, kind, thread}`, the thread's row built with the session."""
    from engine.social import payload

    row_ = row(state, mid) or {}
    tid = str(row_.get("thread_id") or "")
    return {"message_id": row_.get("message_id") or "", "mid": mid, "url": row_.get("url") or "",
            "poster_url": row_.get("poster_url") or "", "kind": row_.get("kind") or "",
            "thread": payload.thread_row(state, tid, session) if tid else None}


def _push(session: Any, mid: str) -> None:
    """`media_ready` through the room-checked emitter (CALLER HOLDS the turn lock); never raises."""
    from engine.social import voicer

    voicer.emit(str(session.session_id), "media_ready", ready_payload(session.engine.state, mid, session))


def _report(session: Any, status: str, ms: float = 0.0) -> None:
    """One hand-off's outcome (`HAND_OFF_STATUSES`) to the `phone` metric's `media_job` event."""
    from engine.scenes import default_scene

    if status not in HAND_OFF_STATUSES:
        raise ValueError(f"social: media: {status!r} is no hand-off status")

    default_scene._report_phone(session, "media_job", status, ms)


# -- the jobs (spec §13.4, §16.1 step 3) -----------------------------------------------------------


def portrait_policy() -> str:
    raw = str(get_config().get("phone_media.portraits", "on_match") or "on_match")
    return raw if raw in PORTRAIT_POLICIES else "off"


def portraits_due(state: GameState) -> list[str]:
    """
    Who is owed a portrait job now, by `phone_media.portraits` (spec §13.4):
    `on_match` everyone matched; `on_view` also the top card of each deck
    (what the deck shows); `off` nobody. Never twice for one person, never
    for someone gone (unmatched, blocked: never seen again).
    """
    policy = portrait_policy()
    if policy == "off":
        return []
    people = (state.social or {}).get("people") or {}
    due = [pid for pid, p in people.items()
           if p.get("matched_at") is not None and not p.get("portrait") and not apps.gone(state, pid)]
    if policy == "on_view":
        for name in apps.dating_apps():
            top = apps.top_card(state, name)
            if top and not _person(state, top).get("portrait") and not apps.gone(state, top):
                due.append(top)
    return sorted(set(due))


def _workflow(name: str) -> Any:
    """`comfyui.workflows.<name>`, or None when it is not declared or does not load (procedural)."""
    from engine.media.comfy.workflows import BindingError, load_workflow

    try:
        return load_workflow(name)
    except BindingError as exc:
        logger.info("[social] No workflow makes this medium, a procedural tile (operation=jobs_for, workflow=%s): %s",
                    name, exc)
        return None


def _message_of(state: GameState, row_: dict[str, Any], directory: Any = None) -> Optional[dict[str, Any]]:
    """
    The media row's message: in state, else -- given the save's `directory`
    -- the archive's copy (a save may have spilled it before its job ran,
    T26), else None.
    """
    t = messaging.thread(state, str(row_.get("thread_id") or ""))
    if t is None:
        return None
    found = next((m for m in t.get("messages") or [] if m["id"] == row_.get("message_id")), None)
    if found is None and directory is not None:
        from engine.social import archive

        found = archive.archived_message(directory, str(row_["thread_id"]), str(row_.get("message_id") or ""))
    return found


def _save_dir(session: Any) -> Any:
    from engine.social import archive

    try:
        return archive.save_dir(session)
    except ValueError:
        return None


def _reference(session: Any, pid: str, workflow: Any) -> Optional[bytes]:
    """The person's first ready portrait's bytes, when the workflow binds `reference_image` (spec §13.3)."""
    if "reference_image" not in workflow.bindings:
        return None
    from engine.media.comfy import storage

    state = session.engine.state
    mid = _person(state, pid).get("portrait")
    row_ = row(state, str(mid)) if mid else None
    if row_ is None or row_["status"] != "ready" or not row_.get("file"):
        return None
    try:
        return (storage.phone_media_dir(session.owner, session.save_id) / storage.check_name(row_["file"])).read_bytes()
    except (OSError, ValueError):
        return None


def _request_for(state: GameState, row_: dict[str, Any], workflow: Any, directory: Any = None) -> dict[str, Any]:
    """The bind values of one row's job (stored at submission; a resume reuses them unchanged)."""
    kind = row_["kind"]
    caption = str(row_.get("caption") or "")
    if kind == "own":
        subject = subject_row(row_.get("subject") or "") or (
            {"scene": next((str(r.get("scene") or r.get("label") or "") for r in population.table("photo_set")
                            if isinstance(r, dict) and r.get("id") == row_.get("photo_id")), "")})
        now = {"daypart": daypart(state.world_clock_hours), "status": "free"}
        return photo_request(player_look(state), subject, caption, now, mid=row_["mid"], seed=int(row_["seed"]),
                             workflow=workflow)
    person = population.profile(state, row_["pid"])
    if kind == "portrait":
        subject = {"scene": str((_block("portrait") or {}).get("scene") or "")}
        return photo_request(person, subject, "", now_for(state, person), mid=row_["mid"], seed=int(row_["seed"]),
                             workflow=workflow)
    message = _message_of(state, row_, directory) or {}
    at = float(message.get("at", state.world_clock_hours))
    return photo_request(person, subject_row(str(row_.get("subject") or "")), caption, now_for(state, person, at),
                         mid=row_["mid"], seed=int(row_["seed"]), workflow=workflow)


def _workflow_name(row_: dict[str, Any]) -> str:
    kind = row_["sends"] if row_["kind"] == "own" else row_["kind"]
    return dict(WORKFLOW_FOR).get(kind, "")


def _spec(session: Any, row_: dict[str, Any], workflow: Any, values: dict[str, Any]) -> Any:
    from engine.media.comfy.jobs import JobSpec

    pid = str(row_.get("pid") or "")
    return JobSpec(mid=row_["mid"], kind=workflow.output_kind, owner=str(session.owner or ""),
                   save_id=str(session.save_id or ""), session_id=str(session.session_id), epoch=int(session.epoch),
                   workflow=workflow.name, values=dict(values), priority=int(row_.get("priority", 0)),
                   account=str(session.owner or ""),
                   reference=_reference(session, pid, workflow) if pid and pid != "player" else None)


def jobs_for(session: Any) -> list[Any]:
    """
    The ComfyUI jobs due now (CALLER HOLDS the turn lock), each a `JobSpec`:
    rows `requested` whose message has committed words, then the portraits
    due by policy (their rows made here). With `phone_media.provider:
    procedural` none: every `requested` row goes straight to `fallback`, and
    no portrait row is made. A row no workflow makes (a kind whose workflow
    is not declared), or a run with no save yet, is procedural at once. A
    voice note is never one of these (`voice_due`).
    """
    from engine.media.comfy.workflows import phone_media_provider

    state = session.engine.state
    rows = _rows(state)
    waiting = sorted((r for r in rows.values() if r["status"] == "requested" and r["kind"] != "voice"),
                     key=lambda r: int(r["mid"][1:]))          # a voice note is the speech worker's (`voice_due`)
    if phone_media_provider() == "procedural":
        for r in waiting:
            mark_procedural(state, r["mid"])
        return []
    out: list[Any] = []
    for r in waiting:
        if r["thread_id"] and r["kind"] != "portrait":
            message = _message_of(state, r, _save_dir(session))
            if message is None or message.get("voiced") == messaging.WITHDRAWN:
                if message is None:
                    logger.info("[social] A media row's message is in neither state nor the archive, a procedural "
                                "tile (operation=jobs_for, mid=%s)", r["mid"])
                mark_procedural(state, r["mid"])        # never shown: nothing to make
                continue
            if message.get("voiced") is False:
                continue                                # its words (the caption) are not committed yet
        built = _build(session, r)
        if built is None:
            mark_procedural(state, r["mid"])
        else:
            out.append(built)
    for pid in portraits_due(state):
        mid = attach(state, pid, "", "", "portrait", "portrait")
        built = _build(session, _rows(state)[mid])
        if built is None:
            mark_procedural(state, mid)
        else:
            out.append(built)
    return out


def _build(session: Any, row_: dict[str, Any]) -> Any:
    name = _workflow_name(row_)
    workflow = _workflow(name) if name else None
    if workflow is None or not session.save_id:
        return None
    values = row_.get("request") or _request_for(session.engine.state, row_, workflow, _save_dir(session))
    return _spec(session, row_, workflow, values)


def submit_due(session: Any) -> int:
    """
    `run_mechanics` step 3 (spec §16.1), also run after a voiced commit
    (CALLER HOLDS the turn lock): the voice notes due to the speech worker
    (`voice_due`), then each due job to the media worker; one it refuses
    (the day's cap) is a procedural tile at once. Returns how many were taken.
    """
    from engine.media.comfy.jobs import get_media_worker
    from engine.media.comfy.workflows import phone_media_provider

    state = session.engine.state
    taken, fell_back = voice_due(session)
    for spec in jobs_for(session):
        if not get_media_worker().submit(spec):
            mark_procedural(state, spec.mid)          # the daily cap: a procedural tile at once
            fell_back.append(spec.mid)
            continue
        mark_submitted(state, spec.mid, spec.values, account=spec.account, provider=phone_media_provider(),
                       digest=spec.digest())
        taken += 1
    for mid in fell_back:
        _report(session, "fallback")
        _push(session, mid)
    if taken or fell_back:
        from engine.social import saves

        saves.mark_dirty(session, "media")
    return taken


def resubmit_unfinished(session: Any) -> int:
    """
    On resume (spec §13.2; CALLER HOLDS the turn lock): every row the last
    run had handed to the worker and not seen finish, submitted again with
    its stored request (the same seed and prompt, so idempotent). Under
    `procedural`, or past the cap, such a row is a procedural tile. Returns
    how many were taken.
    """
    from engine.media.comfy.jobs import get_media_worker
    from engine.media.comfy.workflows import phone_media_provider

    state = session.engine.state
    rows = sorted((r for r in _rows(state).values() if r["status"] in IN_FLIGHT), key=lambda r: int(r["mid"][1:]))
    if not rows:
        return 0
    procedural = phone_media_provider() == "procedural"
    taken = 0
    for r in rows:
        if r["kind"] == "voice":                        # the speech worker's, whatever the image provider
            request = dict(r.get("request") or {})
            transcript = str(request.get("transcript") or r.get("transcript") or "")
            if _submit_voice(session, r, transcript, voice=str(request.get("voice") or "")):
                taken += 1
            else:
                voice_fallback(state, r["mid"], transcript)
            continue
        built = None if procedural else _build(session, r)
        if built is not None and get_media_worker().submit(built):
            mark_submitted(state, r["mid"], built.values, account=built.account, provider=phone_media_provider(),
                           digest=built.digest())
            taken += 1
        else:
            mark_procedural(state, r["mid"])
    logger.info("[social] Unfinished media resubmitted on resume (operation=resubmit_unfinished, id=%s, "
                "taken=%d, of=%d)", session.session_id, taken, len(rows))
    return taken


# -- voice notes (spec §13.6) -----------------------------------------------------------------------


def voice_max_seconds() -> float:
    """`media.yaml` `voice.max_seconds`: a voice note's longest transcript, in seconds of speech."""
    return float((_block("voice") or {}).get("max_seconds", 15))


def voice_max_words() -> int:
    """The most words a voice note holds: `voice.max_seconds` at `VOICE_WORDS_PER_MINUTE`."""
    return max(1, int(voice_max_seconds() * VOICE_WORDS_PER_MINUTE / 60.0))


def voice_transcript(text: str) -> str:
    """
    A transcript cut by LENGTH only (rule 12: never by what it says): to
    `voice_max_words` words, then whole words off its end until it fits
    `tts.max_chars` (the speech server's one-utterance limit) -- never mid-word.
    """
    words = str(text or "").split()[:voice_max_words()]
    limit = int(get_config().get("tts.max_chars", 400))
    while words and len(" ".join(words)) > limit:
        words.pop()
    return " ".join(words)


def voice_note_seconds(text: str) -> float:
    """A transcript's estimated length: its words at 150 a minute, at least 1 s, at most `voice.max_seconds`."""
    words = len(str(text or "").split())
    if not words:
        return 0.0
    return round(min(voice_max_seconds(), max(1.0, words * 60.0 / VOICE_WORDS_PER_MINUTE)), 2)


def voice_fallback(state: GameState, mid: str, transcript: str) -> None:
    """A voice note as its waveform tile for good: `fallback`, the transcript (cut) and its estimated `seconds`."""
    apply_effect(state, {"type": "social_media", "op": "voice", "mid": mid, "transcript": transcript,
                         "fallback": True})


def _voice_words(state: GameState, row_: dict[str, Any], directory: Any = None) -> str:
    """What they say: the committed transcript (the model's `media.caption`), else the message's own words."""
    caption = str(row_.get("caption") or "").strip()
    if caption:
        return caption
    message = _message_of(state, row_, directory) or {}
    return " ".join(str(b) for b in message.get("bubbles") or [] if str(b).strip())


def _voice_spec(session: Any, row_: dict[str, Any], values: dict[str, Any]) -> Any:
    """The voice note's `JobSpec`: the same identity, digest and hand-off as a ComfyUI job's (`workflow: voice`)."""
    from engine.media.comfy.jobs import JobSpec

    return JobSpec(mid=row_["mid"], kind="audio", owner=str(session.owner or ""),
                   save_id=str(session.save_id or ""), session_id=str(session.session_id), epoch=int(session.epoch),
                   workflow="voice", values=dict(values), priority=int(row_.get("priority", 0)),
                   account=str(session.owner or ""), created=time.monotonic())


def wav_seconds(data: bytes) -> float:
    """A WAV's length from its header; ValueError for anything that is not a readable WAV."""
    import io
    import wave

    from engine.media.tts import is_wav

    if not is_wav(data):
        raise ValueError("not a WAV")
    try:
        with wave.open(io.BytesIO(data), "rb") as clip:
            rate = clip.getframerate()
            return clip.getnframes() / float(rate) if rate > 0 else 0.0
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"not a readable WAV: {exc}") from exc


def _voice_done(spec: Any, _request: Any, outcome: dict[str, Any]) -> None:
    """
    The speech worker's word on one voice note (its thread, never under a
    lock): the WAV checked (type, length), stored beside the save's other
    media (the save must still exist), and the result handed to `hand_off`
    like any job's -- `failed` (the transcript tile) for anything else.
    """
    from engine.media.comfy import storage
    from engine.media.comfy.jobs import JobResult, SaveGone, write_media

    try:
        if not outcome.get("ok"):
            raise ValueError(str(outcome.get("error") or "no audio"))
        data = bytes(outcome.get("audio") or b"")
        seconds = wav_seconds(data)
        if seconds <= 0 or seconds > voice_max_seconds() * VOICE_AUDIO_SLACK:
            raise ValueError(f"the audio is {seconds:.1f} s long")
        name = f"{spec.stem()}.wav"
        target = write_media(spec, name, data)
        result = JobResult(spec.mid, "ready", url=storage.url_for(spec.save_id, name), path=str(target),
                           kind="audio", attempts=1, seconds=round(seconds, 2))
        logger.info("[social] Voice note stored (operation=voice_note, mid=%s, bytes=%d)", spec.mid, len(data))
    except SaveGone:
        logger.info("[social] Voice note dropped: its save is gone (operation=voice_note, mid=%s)", spec.mid)
        result = JobResult(spec.mid, "failed", error="save_gone", kind="audio", attempts=1)
    except (OSError, ValueError) as exc:
        logger.info("[social] Voice note failed, the transcript tile (operation=voice_note, mid=%s): %s",
                    spec.mid, exc)
        result = JobResult(spec.mid, "failed", error=str(exc)[:300], kind="audio", attempts=1)
    hand_off(spec, result)


def _submit_voice(session: Any, row_: dict[str, Any], transcript: str, *, voice: str = "") -> bool:
    """
    One voice note to the speech worker (CALLER HOLDS the turn lock): its
    transcript recorded, the request `{transcript, voice}` submitted with
    its deadline, the row `submitted`. A note still queued or speaking
    under the same (owner, save, mid, digest) -- a resume's resubmission --
    is not queued again: the pending request is retargeted to this run
    (review I1). A NEW note is one of the account's `phone_media.daily_job_cap`
    jobs, counted with its images and videos (review I2). False -- and
    nothing submitted -- when TTS is off, the run has no save, the note has
    no words, the person no voice, or the day's cap is spent.
    """
    from engine.media import tts

    state = session.engine.state
    transcript = voice_transcript(transcript)
    if not tts.tts_enabled() or not session.save_id or not transcript:
        return False
    voice = voice or population.profile(state, str(row_["pid"])).voice_id
    if not voice:
        return False
    from engine.media.comfy.jobs import get_media_worker

    spec = _voice_spec(session, row_, {"transcript": transcript, "voice": voice})
    key = (spec.owner, spec.save_id, spec.mid, spec.digest())
    worker = tts.get_speech_worker()
    if not worker.holds(key) and not get_media_worker().charge(spec):
        logger.info("[social] Voice note over the daily job cap, the transcript tile (operation=voice_note, "
                    "mid=%s, account=%s)", spec.mid, spec.account or "local")
        return False
    apply_effect(state, {"type": "social_media", "op": "voice", "mid": row_["mid"], "transcript": transcript})
    deadline = time.monotonic() + float(get_config().get("tts.job_timeout_seconds", 1800))
    queued = worker.submit(
        transcript, voice=voice, session_id=str(session.session_id), kind="voice_note",
        on_done=lambda request, outcome: _voice_done(spec, request, outcome), deadline=deadline, key=key)
    if queued != 1:
        return False
    mark_submitted(state, row_["mid"], spec.values, account=spec.account, provider=VOICE_PROVIDER,
                   digest=spec.digest())
    return True


def voice_due(session: Any) -> tuple[int, list[str]]:
    """
    The voice notes due now (CALLER HOLDS the turn lock): each `requested`
    voice row whose message has committed words, spoken (`_submit_voice`)
    or, failing that, the transcript tile at once. Returns how many the
    speech worker took and the mids that fell back (to push).
    """
    state = session.engine.state
    taken, fell_back = 0, []
    waiting = sorted((r for r in _rows(state).values() if r["status"] == "requested" and r["kind"] == "voice"),
                     key=lambda r: int(r["mid"][1:]))
    directory = _save_dir(session)
    for r in waiting:
        message = _message_of(state, r, directory)
        if message is None or message.get("voiced") == messaging.WITHDRAWN:
            if message is None:
                logger.info("[social] A voice note's message is in neither state nor the archive, its transcript "
                            "tile (operation=voice_due, mid=%s)", r["mid"])
            mark_procedural(state, r["mid"])            # never shown: nothing to say
            continue
        if message.get("voiced") is False:
            continue                                    # its words (the transcript) are not committed yet
        transcript = _voice_words(state, r, directory)
        if _submit_voice(session, r, transcript):
            taken += 1
        else:
            voice_fallback(state, r["mid"], transcript)
            fell_back.append(r["mid"])
    return taken, fell_back


# -- the hand-off (spec §13.4 step 8, §16.4) -------------------------------------------------------


def _default_store() -> Any:
    from engine.scenes.default_scene import get_store

    return get_store()


def apply_and_push(session: Any, result: Any, ms: float = 0.0, digest: str = "") -> bool:
    """
    A job's result applied to a live run (CALLER HOLDS its turn lock, after
    the liveness check): `apply_media_result`, the run marked dirty, the
    `media_ready` push and the metric. False when the row was not waiting
    for it (gone, or already finished).
    """
    from engine.social import saves

    applied = apply_media_result(session.engine.state, result, digest)
    if not applied.get("ok"):
        logger.info("[social] Media result not applied (operation=hand_off, mid=%s): %s",
                    getattr(result, "mid", ""), applied.get("text"))
        _report(session, "dropped", ms)
        return False
    saves.mark_dirty(session, "media")
    _push(session, str(result.mid))
    _report(session, "ok" if str(result.status) == "ready" else "failed", ms)
    return True


def hand_off(spec: Any, result: Any, *, store: Any = None) -> None:
    """
    The worker's `on_done` (spec §13.4 step 8): the run found by id in the
    store; not live, another build or another owner -- dropped, nothing
    written; else its turn lock TRIED: taken -- applied and pushed; busy --
    parked in its inbox for the next holder (§16.4), and a voicing pass
    requested, which drains it ticketless once the lock is free. Never
    raises into the worker.
    """
    from engine.social import saves

    ms = max(0.0, (time.monotonic() - float(spec.created)) * 1000.0) if getattr(spec, "created", 0) else 0.0
    store = store or _default_store()
    session = next((s for s in store.live_sessions() if s.session_id == spec.session_id), None)
    if session is None or str(session.owner or "") != str(spec.owner or "") or not saves.alive(session, spec.epoch, store):
        logger.info("[social] Media result dropped: its run is not live (operation=hand_off, mid=%s, id=%s)",
                    spec.mid, spec.session_id)
        _report(session if session is not None else SimpleNamespace(owner=spec.owner), "dropped", ms)
        return
    if not session.lock.acquire(blocking=False):
        session.inbox.put({"kind": "media", "payload": result, "epoch": spec.epoch, "account": str(spec.owner or ""),
                           "ms": ms, "digest": spec.digest()})
        logger.info("[social] Media result parked in the inbox (operation=hand_off, mid=%s)", spec.mid)
        # Nothing else drains it if the player never acts again (final review I1):
        # a pass is requested, which drains the inbox without a narration ticket.
        try:
            from engine.social import voicer

            voicer.request(session)
        except Exception as exc:  # noqa: BLE001 -- never raises into the worker; the next action drains it
            logger.warning("[social] Drain pass not requested (operation=hand_off, mid=%s): %s", spec.mid, exc)
        return
    try:
        if saves.alive(session, spec.epoch, store):
            apply_and_push(session, result, ms, spec.digest())
        else:
            _report(session, "dropped", ms)
    finally:
        saves.release_turn(session)


def install() -> None:
    """The process's media worker hands its results to `hand_off` (the app's registration, routes.register)."""
    from engine.media.comfy import jobs

    jobs.set_on_done(hand_off)


# -- the morning (budgets, kept or broken "later"s, unasked media) ------------------------------------


def _later_requests(state: GameState) -> list[dict[str, Any]]:
    rows = [r for r in (state.social.get("requests") or {}).values()
            if r["from"] == "player" and r["what"] in MEDIA_KINDS and r["status"] == "later"]
    return sorted(rows, key=lambda r: (float(r["at"]), int(str(r["id"])[1:] or 0)))


def _when_free(state: GameState, pid: str, day_at: float) -> Optional[float]:
    """A free hour inside the morning's day for `pid` (v0.22.0's initiation rule, §9.3, kept for media when
    initiations moved to windows in v0.23.0): one of the day's hours they are free or out, and a minute in it."""
    from engine.game.rng import SOCIAL_PACE

    person = population.profile(state, pid)
    rng = behaviour.person_rng(state, SOCIAL_PACE, pid)
    midnight = day_at - events.DAILY_HOUR

    def clock_at(hour: int) -> float:
        at = midnight + hour
        return at + 24.0 if at < day_at else at

    hours = [h for h in range(24) if behaviour.status_at(person, clock_at(h)) in messaging.FREE]
    if not hours:
        return None
    return clock_at(rng.choice(hours)) + rng.random()


def _queue_send(state: GameState, pid: str, kind: str, at: float, *, request_id: str = "", prefer: str = "") -> bool:
    """INSIDE the morning: one of `kind` decided and spent; its message queued from `pid` at `at`."""
    tid = media_thread(state, pid, kind, prefer=prefer)
    if tid is None:
        return False
    subject = ""
    if kind != "voice":
        fits = subjects_for(state, pid, at)
        if not fits:
            return False
        subject = fits[int(_draw(state, pid) * len(fits)) % len(fits)]
    _spend(state.social["people"].setdefault(pid, {}), kind)
    messaging.queue_due(state, pid, tid, send_decision(kind, subject, request_id), at)
    return True


def _daily(state: GameState) -> None:
    """
    Each morning (a `daily_hooks` step): each "later" media request kept
    (budget and a draw on the accept odds: the medium is sent today) or
    broken. Budgets refill and unasked media are drawn per episode instead
    (`after_episode`, v0.23.0 spec §6.4).
    """
    day_at = events.daily_at(state)
    for request in _later_requests(state):
        pid, what = str(request["pid"]), str(request["what"])
        at = _when_free(state, pid, day_at)
        kept = False
        if at is not None and relationships.live(_person(state, pid)) and not apps.gone(state, pid):
            decided = _decide(state, pid, what, at, mult=float(request.get("mult", 1.0)), later=False,
                              spend=False)
            if decided["answer"] == "accept":
                kept = _queue_send(state, pid, what, at, request_id=str(request["id"]),
                                   prefer=str(request.get("thread_id") or ""))
        apply_effect(state, {"type": "social_request", "op": "answer", "request_id": request["id"],
                             "status": "yes" if kept else "no", "at": day_at})


def after_episode(state: GameState, pid: str, at: float) -> dict[str, Any]:
    """A conversation with `pid` closed at `at` (convo's `close` op): `social_media_decision` `op: episode`."""
    return apply_effect(state, {"type": "social_media_decision", "op": "episode", "pid": pid, "at": float(at)})


def _after_episode(state: GameState, pid: str, at: float) -> dict[str, Any]:
    """
    INSIDE the handler: their budgets refilled (`budget.<kind>.per_episode`, to `cap`), then one draw
    per kind at the unsolicited odds (`unsolicited.per_episode_at_stage`), one sent at most, due at
    their next available minute. Nothing for someone no longer live or gone.
    """
    person_state = state.social["people"].setdefault(pid, {})
    if not relationships.live(person_state) or apps.gone(state, pid):
        return {"type": "social_media_decision", "ok": True, "text": f"{pid}: not live", "sent": False}
    held = person_state.get("media_budget")
    if not isinstance(held, dict):
        held = person_state["media_budget"] = {}
    for kind in MEDIA_KINDS:
        spec = _budget_row(kind)
        held[kind] = round(min(float(spec.get("cap", 0)),
                               budget_of(person_state, kind) + float(spec.get("per_episode", 0))), 6)
    relationships.touch(person_state)
    from engine.social import convo   # lazily: convo imports this module's own imports

    for kind in MEDIA_KINDS:
        if not offer_open(state, pid, kind) or not unsolicited_draw(state, pid, kind):
            continue
        if _queue_send(state, pid, kind, convo.next_available(state, pid, at)):
            return {"type": "social_media_decision", "ok": True, "text": f"{pid} sends a {kind}", "sent": True}
    return {"type": "social_media_decision", "ok": True, "text": f"{pid}: budgets refilled", "sent": False}


if _daily not in events.daily_hooks:
    events.daily_hooks.append(_daily)


__all__ = [
    "ANSWERS", "IN_FLIGHT", "ROW_KINDS", "STATUSES", "accept_p", "after_episode", "answer_request", "apply_and_push",
    "apply_media_result", "ask_refusal", "attach", "attach_own", "budget_of", "check_data", "daypart",
    "decide_request", "face_seed", "hand_off", "install", "jobs_for", "mark_procedural", "mark_submitted",
    "media_faults", "media_seed", "media_thread", "media_view", "now_for", "offer", "offer_open", "photo_request",
    "player_look", "player_photos", "player_subjects", "portrait_url", "portraits_due", "ready_payload",
    "resubmit_unfinished", "send_decision", "subject_label", "subject_row", "subjects_for", "submit_due",
    "unlocked", "unsolicited_draw", "voice_due", "voice_fallback", "voice_max_seconds", "voice_max_words",
    "voice_note_seconds", "voice_transcript", "wav_seconds",
]
