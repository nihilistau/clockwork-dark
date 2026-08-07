"""
Clockwork Dark Launcher
=======================

Scene launcher — optionally brings up the local service stack first.

    python launcher.py                  play; warn about anything down
    python launcher.py --stack          start managed services, then play
    python launcher.py --check          report service status and exit
    python launcher.py --no-stack       skip the service check entirely

Service paths live in config/default.yaml under `stack.services`, and are
overridden per machine in config/local.yaml.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import argparse
import logging
import sys


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    # httpx logs every request at INFO. Health polling a slow-loading model
    # would bury the game's own output under hundreds of identical lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


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
        "voxtral_tts": "no spoken narration (off by default anyway)",
        "voxtral_asr": "no push-to-talk",
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
        print("clockwork  —  THE CLOCKWORK DARK  (port 5573)")
        return 0

    if args.check:
        from engine.stack import StackManager

        _report(StackManager().status())
        return 0

    if args.scene != "clockwork":
        print(f"Unknown scene: {args.scene}", file=sys.stderr)
        return 1

    manager = None
    if not args.no_stack:
        from engine.stack import StackManager

        manager = StackManager()
        # --stack starts what it can; the bare form only looks and reports, so
        # launching never silently spawns a multi-gigabyte model load.
        _report(manager.start_all() if args.stack else manager.status())

    from content.scenes.clockwork.clockwork_scene import run_scene

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
