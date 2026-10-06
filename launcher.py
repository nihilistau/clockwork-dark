"""
Clockwork Dark Launcher
=======================

Scene launcher — optionally brings up the local service stack first.

    python launcher.py                  play; warn about anything down
    python launcher.py --stack          start managed services, then play
    python launcher.py --check          report service status and exit
                                        (1 if the model server is down)
    python launcher.py --no-stack       skip the service check entirely
    python launcher.py --list-games     list installed games and exit
    python launcher.py --game <slug>    play a specific game

Service paths live in config/default.yaml under `stack.services`, and are
overridden per machine in config/local.yaml.

WHICH GAME RUNS: `--game`, else the CLOCKWORK_GAME environment variable, else
`game.default` in config/default.yaml. Activation happens BEFORE the scene is
imported, because a scene import pulls in the content tree and a game
activated afterwards would be repointing config under already-warm caches.

WHICH SCENE RUNS: the active game's manifest, under a top-level `scene:` block
(see engine/scenes/spec.py). Both shipped games declare the engine's default
scene (engine/scenes/default_scene.py) explicitly; a story that declares
nothing gets the same default. The module used to be hardcoded here, which
meant a second story could ship its own content and never its own screens.

HOSTED MODE (`hosting.enabled`, docs/HOSTING.md) runs the supervisor in the
foreground (`python -m engine.hosting.supervisor`'s own `main`, v0.20.0 T12,
spec §7.2): a worker per `hosting.stories` slug and the front door on
`scene.clockwork.host`/`port`, each under the development server, after the
WARNING below -- the same shape as a deployment. `--check` then adds one row:
the front door's `GET /api/health` and where the instance's logs are. With
hosting off nothing here imports `engine.hosting`, and both are v0.19.0's.

Version: v0.6.0 [2026-10-05]
"""

from __future__ import annotations

import argparse
import logging
import sys

#: What the launcher says before it serves hosted mode (spec §7.2).
HOSTED_DEV_SERVER_WARNING = (
    "hosted mode under the development server: for a real deployment run "
    "`python -m engine.hosting.supervisor` on Linux, or the Docker image"
)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    # httpx logs every request at INFO. Health polling a slow-loading model
    # would bury the game's own output under hundreds of identical lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _model_server_down(statuses) -> bool:
    """
    Whether the model server is down: the one FAIL-level service, whatever
    the provider (``stack.MODEL_SERVER_NAMES``). ``--check`` exits 1 on it.
    """
    from engine.stack import MODEL_SERVER_NAMES, STATUS_DOWN, STATUS_FAILED

    return any(
        s.name in MODEL_SERVER_NAMES and s.status in (STATUS_DOWN, STATUS_FAILED)
        for s in statuses
    )


def _report(statuses) -> bool:
    """Print the status table. Returns True if nothing is outright broken."""
    from engine.stack import STATUS_DOWN, STATUS_FAILED, render_table

    print("\nLocal service stack:")
    print(render_table(statuses))
    # Report only what is actually broken. Listing every optional service every
    # time trains you to ignore the block, and it claimed narration was down
    # while narration was working.
    consequences = {
        "lmstudio": "no narration — the Storyteller falls back to a canned line",
        # The model server under any other provider (v0.19.0).
        "llm": "no narration — the model server is down, so the Storyteller "
        "falls back to a canned line",
        "voxtral_tts": "no spoken narration (off by default anyway)",
        # Only bites when stt.provider is voxtral_http. The default provider is
        # faster-whisper, in this process, with no service to be down.
        "voxtral_asr": "no push-to-talk on the voxtral_http provider",
        "comfyui": "no live image generation — the shipped art pack still works",
        "grok": "no live image generation — the shipped art pack still works",
    }

    broken = [s for s in statuses if s.status in (STATUS_DOWN, STATUS_FAILED)]
    if broken:
        print("\n  The game still runs. What you lose:")
        for status in broken:
            print(f"    {status.name:<12} {consequences.get(status.name, 'reduced features')}")
        print()
    return not broken


def _frontdoor_health(url: str) -> tuple[bool, str]:
    """``GET`` the front door's health URL (no system proxy for loopback): up, and what it said."""
    import httpx

    try:
        with httpx.Client(trust_env=False, timeout=3.0) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return False, type(exc).__name__
    return response.status_code == 200, f"HTTP {response.status_code}"


def _hosted_report() -> None:
    """
    Hosted mode's ``--check`` row (spec §7.4): the front door's ``GET
    /api/health`` at ``scene.clockwork.host``/``port`` (loopback when it binds
    every interface), and the path of the instance's logs.
    """
    from engine.persistence.storage import hosting_dir
    from engine.scenes.spec import DEFAULT_SCENE_NAME, is_wildcard, scene_host, scene_port

    host = scene_host(DEFAULT_SCENE_NAME)
    target = "127.0.0.1" if is_wildcard(host) else host
    if ":" in target and not target.startswith("["):
        target = f"[{target}]"
    url = f"http://{target}:{scene_port(DEFAULT_SCENE_NAME)}/api/health"
    alive, detail = _frontdoor_health(url)
    print("\nHosted mode (python -m engine.hosting.supervisor):")
    print(f"  front door  {'up' if alive else 'down':<5} {url} ({detail})")
    print(f"  logs        {hosting_dir() / 'logs'}")


def _run_supervisor() -> int:
    """Hosted mode: the supervisor's own ``main``, in this process, in the foreground."""
    import importlib

    module = importlib.import_module("engine.hosting.supervisor.__main__")
    return int(module.main([]))


def _list_games() -> int:
    """Print the installed games. Returns a process exit code."""
    from engine.games import registry

    rows = registry.catalog()
    if not rows:
        print("No games found under games/. Expected games/<slug>/game.yaml.")
        return 1

    width = max(len(str(row["slug"])) for row in rows)
    print("\nInstalled games:\n")
    for row in rows:
        mark = "*" if row["active"] else " "
        state = "" if row["playable"] else "  [UNPLAYABLE]"
        print(f" {mark} {str(row['slug']):<{width}}  {row['title']}  v{row['version']}{state}")
        if row["blurb"]:
            print(f"   {' ' * width}  {row['blurb'].strip()}")
        # A story may declare a bounded set of engine settings (clock rate,
        # reveal thresholds, governance chain -- see the allowlist in
        # engine/games/manifest.py). Printed because a story that runs on a
        # different clock than the engine default should say so before you
        # launch it, not after the first turn feels wrong.
        for key, value in sorted((row.get("settings") or {}).items()):
            print(f"   {' ' * width}  setting: {key} = {value}")
        # Print every problem, not the first. A manifest with four missing
        # files should say so once rather than across four launch attempts.
        for problem in row["problems"]:
            print(f"   {' ' * width}  - {problem}")
    print("\n  * = would run now.   Play one with:  python launcher.py --game <slug>\n")
    return 0


def _activate_game(slug: str | None) -> bool:
    """
    Activate the selected game before anything imports content.

    Args:
        slug: Explicit slug from ``--game``, or None to use the env var and
            config default.

    Returns:
        True to carry on launching. False only when the player explicitly
        asked for a game that will not load -- an explicit request that cannot
        be honoured must not silently drop them into a different story.
    """
    from engine.config import get_config
    from engine.games.registry import ActivationError, activate

    if slug is None and not bool(get_config().get("game.activate_on_launch", True)):
        return True

    try:
        manifest = activate(slug)
    except ActivationError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        print("  python launcher.py --list-games", file=sys.stderr)
        if slug is not None:
            return False
        # No explicit request: fall through on the raw config, which is the
        # flagship game's content. A broken manifest must never be the reason
        # the game will not start.
        print("  Continuing on the default content paths.\n", file=sys.stderr)
        return True

    print(f"\nGame: {manifest.title}  (games/{manifest.slug}, v{manifest.version})")
    return True


def main(argv: list[str] | None = None) -> int:
    """Entry point for launcher."""
    parser = argparse.ArgumentParser(
        prog="launcher.py",
        description="The Clockwork Dark — scene launcher",
    )
    parser.add_argument(
        "scene",
        nargs="?",
        default="clockwork",
        help="Scene to launch (default: clockwork)",
    )
    parser.add_argument("--list", action="store_true", help="List available scenes")
    parser.add_argument(
        "--game",
        type=str,
        default=None,
        metavar="SLUG",
        help="Game to play (default: CLOCKWORK_GAME, else config game.default)",
    )
    parser.add_argument(
        "--list-games",
        action="store_true",
        help="List installed games and exit",
    )
    parser.add_argument(
        "--studio",
        action="store_true",
        help="Serve the authoring studio alongside the game (edit stories in the browser)",
    )
    parser.add_argument("--port", type=int, default=None, help="Override scene port")
    parser.add_argument("--host", type=str, default=None, help="Override bind host")
    parser.add_argument(
        "--stack",
        action="store_true",
        help="Start managed local services (TTS, ComfyUI) before playing",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report local service status and exit",
    )
    parser.add_argument(
        "--no-stack",
        action="store_true",
        help="Skip the service check entirely",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    if args.list:
        # Port read from config rather than printed as a literal. It had four
        # homes -- this line, SCENE_METADATA, FlaskScene.run's default and
        # config/default.yaml -- so changing the config moved one of them.
        from engine.scenes.spec import scene_port

        print(f"clockwork  —  THE CLOCKWORK DARK  (port {scene_port('clockwork')})")
        return 0

    if args.list_games:
        return _list_games()

    if not _activate_game(args.game):
        return 1

    if args.check:
        from engine.config import TEST_SANDBOX_ENV, stray_sandbox_message
        from engine.stack import StackManager

        statuses = StackManager().status()
        _report(statuses)
        from engine.config import hosting_enabled

        if hosting_enabled():
            _hosted_report()
        # A stray test-suite marker (T5 re-review, N4): every service is off
        # in this process whatever the table says, so it is a FAIL of its own.
        stray = stray_sandbox_message()
        if stray is not None:
            print(f"\n  FAIL  {TEST_SANDBOX_ENV}: {stray}\n")
            return 1
        # Exit 1 only when the model server is down: every other service
        # degrades a feature, and the game still runs without it.
        return 1 if _model_server_down(statuses) else 0

    # THE STUDIO IS OPT-IN, and stays that way. It writes to `games/` on
    # request, which is exactly right for an authoring tool and exactly wrong
    # for a machine somebody is only playing on. A flag is the difference.
    if args.studio:
        import os

        from engine.config import hosting_enabled

        if hosting_enabled():
            # Spec §6.7, said here and at once (T12 fix round 1): every
            # worker would inherit the flag, refuse to start and crash-loop
            # until held down, with the reason only in the children's logs.
            print(
                "\n  Hosted mode refused to start: --studio: the studio writes to games/ and "
                "resets every cache under other players' turns; it does not run in hosted "
                "mode (start without --studio, or set hosting.enabled: false)\n",
                file=sys.stderr,
            )
            return 1
        os.environ["CLOCKWORK_STUDIO"] = "1"
        print("\n  Studio enabled — open  /?studio=1  to edit stories.\n")

    # The positional scene argument names the ACTIVE game's scene, whatever
    # that is. It was compared against the literal "clockwork", so a story
    # declaring its own scene could never be launched by name.
    from engine.scenes.spec import resolve_scene as _resolve_scene

    expected = _resolve_scene().name
    if args.scene not in (expected, "clockwork"):
        print(f"Unknown scene: {args.scene} (this game serves {expected!r})", file=sys.stderr)
        return 1

    manager = None
    if not args.no_stack:
        from engine.stack import StackManager

        manager = StackManager()
        # --stack starts what it can; the bare form only looks and reports, so
        # launching never silently spawns a multi-gigabyte model load.
        _report(manager.start_all() if args.stack else manager.status())

    from engine.config import hosting_enabled

    if hosting_enabled():
        # HOSTED MODE (spec §7.2): the supervisor, in the foreground, with a
        # development server for the front door and each worker -- the shape
        # of a deployment. It answers its own refusals (exit 1, naming the key).
        print(f"\n  WARNING: {HOSTED_DEV_SERVER_WARNING}\n")
        if args.host or args.port:
            print(
                "  --host and --port are not used in hosted mode: the front door binds "
                "scene.clockwork.host and scene.clockwork.port.\n"
            )
        try:
            return _run_supervisor()
        finally:
            if manager is not None:
                manager.stop_all()

    # The active game names its scene module, defaulting to Clockwork's. The
    # import happens AFTER activation for the reason in the module docstring:
    # a scene import warms content caches, so the game has to be chosen first.
    import importlib

    from engine.scenes.spec import resolve_scene

    spec = resolve_scene()
    try:
        scene_module = importlib.import_module(spec.module)
        run_scene = scene_module.run_scene
    except (ImportError, AttributeError) as exc:
        print(f"\nScene {spec.module!r} will not load: {exc}\n", file=sys.stderr)
        return 1

    # Local mode has no login: a bind other than loopback (`--host`, or
    # `scene.<name>.host` in config/local.yaml) is said here, in the doctor's
    # own words, before anything listens (v0.20.0).
    from engine.scenes.spec import exposure_warning, scene_host, scene_port

    warning = exposure_warning(
        args.host or scene_host(spec.name), args.port or scene_port(spec.name)
    )
    if warning:
        print(f"\n  WARNING: bound to {args.host or scene_host(spec.name)} - {warning}\n")

    try:
        run_scene(host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        if manager is not None:
            manager.stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
