"""
The README's runs, built the same way every time (v0.21.0, spec §11).

Two modes, one storage root (``CLOCKWORK_DATA_DIR``):

    python scripts/screenshot_runs.py --root <fresh dir>
        builds every story's runs at a fixed seed and name, and writes
        <root>/runs.json: {story: {tag: {save_id, player}}}
    python scripts/screenshot_runs.py --root <same dir> --serve <slug> [--port N]
                                      [--exit-with-parent]
        serves that story on 127.0.0.1 over those saves, for
        `npm run screenshots --prefix ui` (ui/tools/screenshots.mjs). It
        refuses a port that already answers, and notes its own pid AND
        creation time in <root>/serve-<port>.json (removed when it stops, also
        under --exit-with-parent; a file left by a killed server is replaced when
        its process is gone and refused while it is alive). Start
        it with the shell's background task, never a bare `&`, which orphans it.

NO MODEL, NO OWNER FILE. The config is pinned to <root>/config/local.yaml
(``pinned_layer``: ``llm.base_url`` at the discard port with no key, every
service the test sandbox turns off turned off, the wall-clock tick out of
reach), so ``config/local.yaml`` is never read and no model server is ever
reached (plan decision 6); a set ``CLOCKWORK_CONFIG``, whose files would
layer above the pin, is refused. Every narration is the story's own
``entry.fallback_narration`` -- the words a player sees when the model is
down -- so nothing invented reaches a README image.

A MOVE IS ONLY EVER ONE THE ENGINE OFFERED. Every story opens on its
AUTHORED opening, so the new game's reply is the story's own; each later
reply (the scripted model's) offers the next scripted move taken from that
turn's OWN intent enum (``intents.legal_intents``), exactly the rule a model
meets. The script then presses the choice, whatever its id, whose intent is
that move -- like a player, so the engine resolves it before narration. A
move that no choice of the turn carries stops the script, naming it
(``ScriptStop``).

It is a script, not a test: it refuses to run unless ``CLOCKWORK_DATA_DIR``
names ``--root`` and that directory is absent or empty.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The discard port (nothing listens, so a stray model call fails at once):
# the same origin the test sandbox pins, from its one source in engine.config.
from engine.config import TEST_SANDBOX_BASE_URL as DISCARD_BASE_URL  # noqa: E402

#: Every story the README photographs.
STORIES: tuple[str, ...] = ("clockwork-dark", "wicked-garden", "neon-city", "the-long-con", "hue-and-cry", "dev-story")
#: One seed and one name for every run, so a re-run photographs the same world.
SEED = 1021
#: The player's name per run tag: an in-world name on the README's side
#: sheet, still distinct per save row (the capture finds a run by it).
PLAYERS: dict[str, str] = {
    "play": "Wren Ashby",
    "panels": "Wren Tallis",
    "deck": "Wren Hollow",
    "encounter": "Wren Marley",
    "wanted": "Wren Marsh",
    "held": "Wren Kell",
}
#: Each story's archetype, named rather than left to the manifest's default.
ARCHETYPES: dict[str, str] = {
    "clockwork-dark": "wayfarer",
    "wicked-garden": "human",
    "neon-city": "runner",
    "the-long-con": "gumshoe",
    "hue-and-cry": "cutpurse",
    "dev-story": "human",
}
RUNS_FILE = "runs.json"

#: A step: ("opening", text) picks the opening choice whose text contains
#: `text`; ("intent", action, target) offers and picks `action` on `target`
#: ("" = the enum's first legal target); ("repeat", action, max) does the
#: same up to `max` times, while `action` is legal, then the run goes on;
#: ("alternate", action, "a|b", max) does the same, its target taking each
#: of the `|`-separated ids in turn; ("offer", action), a run's LAST step
#: (``expand`` refuses one anywhere else), has the last reply offer `action`
#: on every legal target and presses none, and stops the script unless that
#: reply carries the action on EVERY legal target (none lost on the way to
#: the screen). The save stands in that state. Its choices are the save's last
#: turn only: the capture resumes each save, and a resume rebuilds the
#: choices (`default_state.resume_opening`) -- in an open encounter, from the
#: same enum, so the approaches are on screen and pressable there too.
Step = tuple[str, ...]

#: story -> run tag -> moves. A tag is one save; screenshots.mjs names it.
RUNS: dict[str, dict[str, tuple[Step, ...]]] = {
    "clockwork-dark": {
        "play": (("intent", "travel", ""),),
        # The layout's encounter check (v0.21.0 T6): walk the forest road
        # (danger_dc 8) back and forth until it deals a scene, which takes the
        # stage. Travel stops being legal once an encounter owns the turn, so
        # the run stands in it.
        # The last reply offers every approach as an `encounter` intent, as a
        # model meets the turn (v0.21.0 T10), and the build stops unless every
        # approach reaches the turn's choices. The approach buttons press them.
        "encounter": (
            ("alternate", "travel", "forest_clearing|edgewood_square", "24"),
            ("offer", "encounter"),
        ),
    },
    # Stepping through the gate deals the ten-card prologue: "deck" stops on
    # its first card, "play" deals it out to the garden beyond.
    "wicked-garden": {
        "deck": (("intent", "travel", "gate_of_briars"),),
        # (21 picks at this seed; the repeat stops when no card is dealt.)
        "play": (("intent", "travel", "gate_of_briars"), ("repeat", "card", "24")),
    },
    "neon-city": {"play": (("intent", "travel", ""),)},
    "the-long-con": {"play": (("intent", "travel", ""),)},
    "hue-and-cry": {
        # Going quietly deals the Lantern House's interrogation deck first;
        # custody's exit (`pay_fine`) is legal only once it is played out.
        "play": (("opening", "go quietly"), ("repeat", "card", "6"), ("intent", "pay_fine", "")),
        "panels": (
            ("opening", "go quietly"),
            ("repeat", "card", "6"),
            ("intent", "pay_fine", ""),
            # Silk Row is two streets from the Lantern House, by Wickmarket.
            ("intent", "travel", "wickmarket"),
            ("intent", "travel", "silk_row"),
            ("intent", "case", ""),
            ("intent", "burgle", ""),
        ),
        # The wanted poster's painted states (v0.21.0 T8 fix round 1), each
        # reached by engine-offered intents only. "wanted": lifting from the
        # Lantern on the Quay until the Quay names the thief, then walked
        # back to the Lantern House (the longest place name beside the chip).
        "wanted": (
            ("opening", "go quietly"),
            ("repeat", "card", "6"),
            ("intent", "pay_fine", ""),
            ("intent", "travel", "tallow_docks"),
            ("repeat", "lift", "8"),
            ("intent", "travel", "wickmarket"),
            ("intent", "travel", "lantern_house"),
        ),
        # "held": the arrest's deck played out, the fine not yet paid: the
        # poster's "Held" stamp with both ways out.
        "held": (("opening", "go quietly"), ("repeat", "card", "6")),
        # "encounter" (v0.21.0 T10): the panels run's job walked stage by
        # stage on the first offered approach until the watch takes the
        # thief (`caught`, at this seed on the eighth stage), which begins
        # the Law's `watch_stop`; the last reply offers each of its approaches
        # as an `encounter` intent, and the save stands in the stop.
        "encounter": (
            ("opening", "go quietly"),
            ("repeat", "card", "6"),
            ("intent", "pay_fine", ""),
            ("intent", "travel", "wickmarket"),
            ("intent", "travel", "silk_row"),
            ("intent", "case", ""),
            ("intent", "burgle", ""),
            ("repeat", "job", "12"),
            ("offer", "encounter"),
        ),
    },
    "dev-story": {"play": (("intent", "travel", ""),)},
}


class ScriptStop(RuntimeError):
    """A scripted move the engine did not offer, or a run that could not be built."""


def _same_path(a: Any, b: Any) -> bool:
    """One directory, however its case or separators were typed (Windows folds case)."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def require_fresh(root: Path) -> None:
    env = os.environ.get("CLOCKWORK_DATA_DIR", "").strip()
    if not env:
        raise ScriptStop("set CLOCKWORK_DATA_DIR to --root: this script never writes the owner's storage")
    if not _same_path(env, root):
        raise ScriptStop(f"CLOCKWORK_DATA_DIR ({env}) must name --root ({root})")
    if root.exists() and any(root.iterdir()):
        raise ScriptStop(f"{root} is not empty: give a fresh directory")


def pinned_layer() -> dict[str, Any]:
    """
    The one layer over ``config/default.yaml``: what the test sandbox's
    ``engine.config._force_sandbox`` holds a child to -- no model server (the
    discard URL, no key), no MCP bridge, no ComfyUI, no TTS, no STT server, no
    managed service -- plus no live image generation, and a wall-clock world
    tick no build or capture reaches (issue R-03: ``_background_tick`` grants
    hours by REAL time elapsed between turns, so a slow turn would build a
    different world; 0 is not "off", it grants the full tick every turn).
    """
    import yaml

    from engine.config import _DEFAULT_PATH, TEST_SANDBOX_SERVICE_URL

    default = yaml.safe_load(Path(_DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    services = ((default.get("stack") or {}).get("services") or {})
    return {
        "llm": {"base_url": DISCARD_BASE_URL, "api_key": "", "mcp": {"enabled": False}},
        "comfyui": {"enabled": False, "base_url": TEST_SANDBOX_SERVICE_URL},
        "tts": {"enabled": False, "assistant_enabled": False, "base_url": TEST_SANDBOX_SERVICE_URL},
        "stt": {"base_url": TEST_SANDBOX_SERVICE_URL},
        "media": {"live_generation": False},
        "stack": {"services": {name: {"manage": False} for name in services}},
        "world": {"tick_interval_seconds": TICK_NEVER_SECONDS},
    }


#: A wall-clock tick interval no build or capture reaches (one day).
TICK_NEVER_SECONDS = 86400


def pin_config(root: Path) -> Path:
    """
    <root>/config/local.yaml (``pinned_layer``) as the only layer over the
    default. Refuses while ``CLOCKWORK_CONFIG`` is set: the files it names
    merge ABOVE local.yaml, so they would override the pin (fail closed).
    """
    import yaml

    import engine.config as config

    if os.environ.get("CLOCKWORK_CONFIG", "").strip():
        raise ScriptStop(
            "CLOCKWORK_CONFIG is set: its files would layer over the pinned config "
            "(and could reach a real model server); unset it for this script"
        )
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "local.yaml").write_text(yaml.safe_dump(pinned_layer()), encoding="utf-8")
    config._CONFIG_DIR = config_dir
    config.reset_config()
    return config_dir


class Director:
    """
    The scripted model. Every reply offers, as choices "a", "b", ..., the
    moves queued in ``offer`` -- each taken from the LIVE turn's own intent
    enum -- and a plain last choice. A queued REQUIRED move the enum does not
    hold is recorded in ``missing``; an optional one (a repeat's) is simply
    not offered.
    """

    def __init__(self, fallback: str) -> None:
        self.scene: Any = None
        self.fallback = fallback or "The world waits."
        self.offer: list[Step] = []
        self.missing = ""

    def state(self) -> Any:
        # The script's own process holds exactly one live run.
        sessions = list(self.scene.store._sessions.values())
        return sessions[0].engine.state

    def choices_for(self, step: Step) -> list[dict[str, Any]]:
        """
        The step's move as choices: one, on its target (or the enum's first);
        for an "offer" step, one per legal target. Empty when not legal.
        """
        from engine.game.intents import legal_intents

        action, target = step[1], step[2]
        for verb in legal_intents(self.state()):
            if verb.action != action:
                continue
            targets = list(verb.targets)
            if not targets:
                return [{"text": action.replace("_", " "), "intent": {"action": action}}]
            if step[3:] == ("offer",):
                chosen = targets
            else:
                chosen = [target if target else targets[0]]
            return [
                {"text": verb.label_for(one) or one, "intent": {"action": action, "target": one}}
                for one in chosen
                if one in targets
            ]
        return []

    def __call__(self, *_args: Any, **_kwargs: Any) -> str:
        choices: list[dict[str, Any]] = []
        for step in self.offer:
            offered = self.choices_for(step)
            if offered:
                choices += offered
            elif step[3:] != ("optional",) and not choices and not self.missing:
                # Missing only when nothing before it was offered: while a
                # repeat still goes on, the move after it is not due yet.
                self.missing = " ".join(part for part in step[1:3] if part)
        choices.append({"text": "Look about you"})
        for letter, choice in zip("abcdefgh", choices):
            choice["id"] = letter
        return json.dumps({"narration": self.fallback, "choices": choices})


def expand(steps: tuple[Step, ...]) -> list[Step]:
    """
    ("repeat", action, n) as n OPTIONAL intent steps, ("offer", action) as an
    OFFER intent step; every intent step padded to 4 parts.
    """
    out: list[Step] = []
    for number, step in enumerate(steps):
        if step[0] == "offer" and number != len(steps) - 1:
            # A step after it would run against the offer's stale queue.
            raise ScriptStop(f"an ('offer', {step[1]!r}) step must be a run's last, not step {number + 1} of {len(steps)}")
        if step[0] == "repeat":
            out += [("intent", step[1], "", "optional")] * int(step[2])
        elif step[0] == "alternate":
            targets = step[2].split("|")
            out += [("intent", step[1], targets[i % len(targets)], "optional") for i in range(int(step[3]))]
        elif step[0] == "intent":
            out.append((step[0], step[1], step[2], "required"))
        elif step[0] == "offer":
            out.append(("intent", step[1], "", "offer"))
        else:
            out.append(step)
    return out


def _queue(moves: list[Step], start: int) -> list[Step]:
    """
    The moves the next reply offers: the next one and, while that one is
    optional (a repeat's, which may stop being legal), the first move after
    its repeat too -- so a run goes on past a deck that ended early.
    """
    queued: list[Step] = []
    for step in moves[start:]:
        if step[0] != "intent":
            break
        if step in queued:
            continue
        queued.append(step)
        if step[3] != "optional":
            break
    return queued


def _turn_choice_cap() -> int:
    """The most choices a turn shows: the turn schema's own `maxItems`."""
    from engine.llm.schemas import storyteller_turn_schema

    return int(storyteller_turn_schema()["schema"]["properties"]["choices"]["maxItems"])


def _offered(turn: dict[str, Any], step: Step) -> Optional[str]:
    """
    The id of the turn's first choice whose intent is `step`'s move (its
    action, and its target when the step names one), whatever that id is:
    an authored opening's or a dealt card's as much as the scripted model's.
    None when no choice carries it.
    """
    for choice in turn.get("choices") or []:
        intent = choice.get("intent") or {}
        if intent.get("action") != step[1]:
            continue
        if step[2] and intent.get("target") != step[2]:
            continue
        return str(choice.get("id"))
    return None


def _play(story: str, tag: str, steps: tuple[Step, ...]) -> dict[str, str]:
    from engine.games import registry
    from engine.scenes.default_scene import create_app, reset_store

    manifest = registry.activate(story)
    try:
        reset_store()
        moves = expand(steps)
        director = Director(manifest.fallback_narration)
        scene, app = create_app(testing=True, llm_fn=director)
        director.scene = scene
        client = app.test_client()
        player = PLAYERS[tag]
        started = client.post(
            "/api/game/new", json={"seed": SEED, "player_name": player, "archetype": ARCHETYPES[story]}
        ).get_json()
        session_id = started["session_id"]
        last: dict[str, Any] = started.get("opening") or {}

        for index, step in enumerate(moves):
            if step[0] == "opening":
                matches = [c for c in last.get("choices") or [] if step[1] in str(c.get("text") or "")]
                if not matches:
                    raise ScriptStop(f"{story}/{tag}: no opening choice reads {step[1]!r}")
                choice_id = str(matches[0]["id"])
            elif step[3] == "offer":
                # Offered by the last reply, pressed by nobody: the run stands.
                if _offered(last, step) is None:
                    raise ScriptStop(f"{story}/{tag}: the engine did not offer {step[1]}")
                # EVERY legal target reached the turn's choices, none lost on
                # the way (the pipeline's merge once displaced one) -- up to
                # the turn's own cap on choices, which no target list beats.
                legal = [c["intent"]["target"] for c in director.choices_for(step)][:_turn_choice_cap()]
                shown = [
                    (c.get("intent") or {}).get("target")
                    for c in last.get("choices") or []
                    if (c.get("intent") or {}).get("action") == step[1]
                ]
                if shown != legal:
                    raise ScriptStop(f"{story}/{tag}: the turn offered {step[1]} on {shown}, not every legal target {legal}")
                continue
            else:
                offered = _offered(last, step)
                if offered is not None:
                    choice_id = offered
                elif step[3] == "optional":
                    continue  # a repeat ends when its verb stops being legal
                else:
                    raise ScriptStop(f"{story}/{tag}: the engine did not offer {' '.join(p for p in step[1:3] if p)}")
            director.offer = _queue(moves, index + 1)
            director.missing = ""
            answer = client.post("/api/game/choice", json={"session_id": session_id, "choice_id": choice_id})
            if answer.status_code != 200:
                raise ScriptStop(f"{story}/{tag}: {step} answered {answer.status_code}")
            last = answer.get_json()
            if director.missing:
                raise ScriptStop(f"{story}/{tag}: the engine did not offer {director.missing}")

        # Written over the run's own save, so the Saves screen holds ONE row
        # per player name (a new id would sit beside the autosave, and the
        # capture could not tell the two apart).
        saved = client.post("/api/saves", json={"session_id": session_id, "save_id": started["save_id"]}).get_json()
        if str(saved.get("save_id")) != str(started["save_id"]):
            raise ScriptStop(f"{story}/{tag}: the save was written under another id ({saved})")
        return {"save_id": str(saved["save_id"]), "player": player}
    finally:
        registry.deactivate()
        reset_store()


def build_runs(root: Path, stories: Iterable[str] = STORIES) -> dict[str, dict[str, dict[str, str]]]:
    built: dict[str, dict[str, dict[str, str]]] = {}
    for story in stories:
        built[story] = {tag: _play(story, tag, steps) for tag, steps in RUNS[story].items()}
    root.mkdir(parents=True, exist_ok=True)
    (root / RUNS_FILE).write_text(json.dumps(built, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return built


def port_answers(port: int, host: str = "127.0.0.1") -> bool:
    """Whether anything accepts a connection on ``host:port`` now."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((host, port)) == 0


def _record_identity(root: Path, port: int) -> Path:
    """
    <root>/serve-<port>.json: this server's pid AND creation time, so a tool
    that must stop it verifies the pair (engine/hosting/process_identity.py)
    rather than trusting a bare pid. Removed when the server exits.
    """
    from engine.hosting import process_identity

    me = process_identity.me()
    path = root / f"serve-{port}.json"
    if path.exists():
        # A file left by a server that was killed outright: stale when its
        # process (pid AND creation time) is gone, a refusal when it is not.
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            owner = process_identity.Identity(int(old["pid"]), old.get("created"))
        except (OSError, ValueError, KeyError, TypeError):
            owner = None
        if owner is not None and process_identity.alive(owner):
            raise ScriptStop(f"{path.name} names a live server (pid {owner.pid}); stop it first")
        path.unlink(missing_ok=True)
    path.write_text(json.dumps({"pid": me.pid, "created": me.created}) + "\n", encoding="utf-8")
    return path


def _exit_with_parent(
    record: Path,
    parent: Any = None,
    poll: float = 2.0,
    leave: Any = os._exit,
) -> Any:
    """
    A daemon thread that removes ``record`` and ends this process once its
    parent is gone. The parent is its pid AND creation time
    (engine/hosting/process_identity.py), so a pid reused by a stranger is not
    followed: a parent that started AFTER this process cannot be its launcher,
    so it is treated as already gone. A parent that cannot be verified here
    (no way to read its creation time) is a WARNING, never a silent no-op.
    Returns the thread, or None when nothing is watched.
    """
    import threading
    import time

    from engine.hosting import process_identity

    parent = parent or process_identity.identify(os.getppid())
    if parent.created is None:
        print(
            f"screenshot_runs: WARNING --exit-with-parent cannot verify its parent (pid {parent.pid}); "
            "this server will NOT exit when its launcher does",
            file=sys.stderr, flush=True,
        )
        return None
    mine = process_identity.me().created

    def watch() -> None:
        gone = mine is not None and parent.created > mine
        while not gone and process_identity.alive(parent):
            time.sleep(poll)
        record.unlink(missing_ok=True)
        print("screenshot_runs: the parent process is gone; exiting", flush=True)
        leave(0)

    thread = threading.Thread(target=watch, name="exit-with-parent", daemon=True)
    thread.start()
    return thread


def serve(root: Path, slug: str, port: Optional[int], exit_with_parent: bool = False) -> None:
    from engine.games import registry
    from engine.scenes.default_scene import create_app
    from engine.scenes.spec import scene_port

    chosen = int(port or scene_port("clockwork"))
    # Werkzeug binds with SO_REUSEADDR, which on Windows lets a second server
    # share a port the first still answers on: a stale build or root would then
    # answer the gate's probes. Refuse before anything starts.
    if port_answers(chosen):
        raise ScriptStop(f"port {chosen} is already served; stop that server first")
    manifest = registry.activate(slug)
    fallback = manifest.fallback_narration or "The world waits."
    scene, _app = create_app(llm_fn=lambda *_a, **_k: json.dumps({"narration": fallback, "choices": []}))
    record = _record_identity(root, chosen)
    if exit_with_parent:
        _exit_with_parent(record)
    print(f"serving {slug} over {root} on http://127.0.0.1:{chosen}", flush=True)
    try:
        scene.run(host="127.0.0.1", port=chosen)
    finally:
        record.unlink(missing_ok=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="screenshot_runs.py", description=__doc__.splitlines()[1])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--only", action="append", choices=STORIES, help="build only these stories")
    parser.add_argument("--serve", choices=STORIES, help="serve this story over an existing root")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--exit-with-parent", action="store_true",
        help="with --serve: exit when the launching process is gone (never leaves an orphan)",
    )
    args = parser.parse_args(argv)
    try:
        if args.serve:
            env = os.environ.get("CLOCKWORK_DATA_DIR", "").strip()
            if not env or not _same_path(env, args.root) or not (args.root / RUNS_FILE).is_file():
                raise ScriptStop("--serve needs CLOCKWORK_DATA_DIR = --root, holding a runs.json from a build")
            pin_config(args.root)
            serve(args.root, args.serve, args.port, args.exit_with_parent)
            return 0
        require_fresh(args.root)
        pin_config(args.root)
        built = build_runs(args.root, args.only or STORIES)
    except ScriptStop as exc:
        print(f"screenshot_runs: {exc}", file=sys.stderr)
        return 2
    print(f"built {sum(len(tags) for tags in built.values())} runs under {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
