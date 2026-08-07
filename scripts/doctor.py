"""
Health check — the first thing to run when something is wrong.

Probes every external service, validates the content tree, and reports what
each failure actually costs you in play. The point is to answer "why is the
game doing that?" without reading a log.

    python scripts/doctor.py
    python scripts/doctor.py --verbose

Exit code 0 if nothing is broken, 1 if something is.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK, WARN, FAIL = "ok", "warn", "fail"
GLYPH = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}


class Report:
    """Collects check results and prints them grouped."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, section: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append((section, name, status, detail))

    @property
    def failed(self) -> bool:
        return any(status == FAIL for _, _, status, _ in self.rows)

    def render(self) -> str:
        out: list[str] = []
        width = max((len(n) for _, n, _, _ in self.rows), default=12)
        current = None
        for section, name, status, detail in self.rows:
            if section != current:
                out.append(f"\n{section}")
                current = section
            out.append(f"  {GLYPH[status]}  {name:<{width}}  {detail}")
        return "\n".join(out)


def check_python(report: Report) -> None:
    version = sys.version_info
    status = OK if version >= (3, 11) else FAIL
    report.add("Runtime", "python", status, f"{version.major}.{version.minor}.{version.micro}")

    for module in ("flask", "flask_socketio", "httpx", "yaml"):
        try:
            __import__(module)
            report.add("Runtime", module, OK, "installed")
        except ImportError:
            report.add("Runtime", module, FAIL, "missing — run pip install -r requirements.txt")


def check_services(report: Report) -> None:
    from engine.stack import STATUS_DISABLED, STATUS_DOWN, STATUS_FAILED, StackManager

    consequences = {
        "lmstudio": "no narration - the Storyteller falls back to a canned line",
        "voxtral_tts": "no spoken narration (off by default anyway)",
        "voxtral_asr": "no push-to-talk",
        "comfyui": "no live image generation - the shipped art pack still works",
        "grok": "no live image generation - the shipped art pack still works",
    }

    for status in StackManager().status():
        if status.status == STATUS_DISABLED:
            report.add("Services", status.name, OK, "disabled in config")
        elif status.status in (STATUS_DOWN, STATUS_FAILED):
            # Only LM Studio genuinely breaks the game; everything else degrades.
            level = FAIL if status.name == "lmstudio" else WARN
            report.add("Services", status.name, level,
                       f"{status.detail} -> {consequences.get(status.name, 'reduced features')}")
        else:
            report.add("Services", status.name, OK, status.detail)


def check_config(report: Report) -> None:
    from engine.config import get_config

    cfg = get_config()

    key = str(cfg.get("lmstudio.api_key", "") or "")
    if key:
        report.add("Config", "lmstudio key", OK, f"resolved ({len(key)} chars)")
    else:
        report.add("Config", "lmstudio key", WARN,
                   "not set - fine only if LM Studio's 'Require API key' is off")

    for label, path_key, default in (
        ("economy", "paths.economy", "data/economy.yaml"),
        ("procgen", "paths.procgen_templates", "data/procgen_templates/edgewood.yaml"),
        ("schedules", "paths.world_schedules", "data/world/schedules.yaml"),
        ("art manifest", "paths.art_manifest", "data/art/manifest.yaml"),
    ):
        path = cfg.resolve_path(path_key, default)
        exists = path is not None and path.exists()
        report.add("Config", label, OK if exists else WARN,
                   str(path) if exists else f"missing: {path}")


def check_content(report: Report) -> None:
    """Load every content tree and count it, so an empty file is visible."""
    from engine.game.locations import LOCATIONS

    report.add("Content", "locations", OK if LOCATIONS else FAIL, f"{len(LOCATIONS)} places")

    probes = [
        ("skills", "engine.game.checks", "load_skill_rules", ("skills",)),
        ("archetypes", "engine.game.checks", "load_archetypes", ("archetypes",)),
        ("npc schedules", "engine.world.npc_sim", "load_npc_schedules", None),
        ("factions", "engine.game.reputation", "load_factions", ("factions",)),
    ]
    for label, module_path, func_name, sub in probes:
        try:
            module = __import__(module_path, fromlist=[func_name])
            data = getattr(module, func_name)()
            if sub:
                for key in sub:
                    data = (data or {}).get(key, data)
            count = len(data or {})
            report.add("Content", label, OK if count else WARN, f"{count} entries")
        except (ImportError, AttributeError) as exc:
            report.add("Content", label, WARN, f"not available: {exc}")

    art = Path("content/scenes/clockwork/static/art")
    files = list(art.rglob("*.jpg")) + list(art.rglob("*.png")) if art.exists() else []
    report.add("Content", "art pack", OK if files else WARN,
               f"{len(files)} images" if files else "no shipped art - falling back to procedural SVG")


def check_ui(report: Report) -> None:
    dist = Path("content/scenes/clockwork/static/dist")
    built = (dist / "app.js").exists() and (dist / "index.css").exists()
    report.add("UI", "build output", OK if built else FAIL,
               "dist present" if built else "missing - run: cd ui && npm run build")

    fonts = list((dist / "fonts").glob("*.woff2")) if dist.exists() else []
    report.add("UI", "fonts", OK if fonts else WARN,
               f"{len(fonts)} self-hosted" if fonts else "not self-hosted - will not render offline")


def check_saves(report: Report) -> None:
    try:
        from engine.persistence import get_save_store

        saves = get_save_store().list_saves()
        report.add("Saves", "store", OK, f"{len(saves)} run(s)")
        if saves:
            newest = saves[0]
            report.add("Saves", "newest", OK,
                       f"{newest.player_name}, day {newest.world_day}, turn {newest.turn_number}")
    except Exception as exc:  # noqa: BLE001 — diagnostics must not crash
        report.add("Saves", "store", WARN, str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Clockwork Dark — health check")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.verbose:
        import logging

        logging.disable(logging.WARNING)

    report = Report()
    for check in (check_python, check_config, check_services, check_content, check_ui, check_saves):
        try:
            check(report)
        except Exception as exc:  # noqa: BLE001 — one bad check must not hide the rest
            report.add("Errors", check.__name__, FAIL, repr(exc))

    print("The Clockwork Dark — doctor")
    print(report.render())

    if report.failed:
        print("\nSomething is broken. See [FAIL] above.")
        return 1
    print("\nAll good. Play with:  python launcher.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
