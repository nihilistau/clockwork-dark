"""
Health check — the first thing to run when something is wrong.

Probes every external service, validates the content tree, and reports what
each failure actually costs you in play. The point is to answer "why is the
game doing that?" without reading a log.

    python scripts/doctor.py
    python scripts/doctor.py --verbose

The Games section reports which game is active and validates every manifest on
disk -- not only the active one, since a manifest with a missing path is a
launch that will fail and this is where that should be found.

The State section does the same for ``games/<slug>/state.yaml``. A malformed
schema is FATAL at load (``engine/state/schema.py`` raises rather than guessing),
so without this check the first sign of a typo in a story's meters is the game
refusing to start with a traceback -- which is exactly the class of failure a
doctor exists to find first.

Exit code 0 if nothing is broken, 1 if something is.

Version: v0.4.0 [2026-08-08]
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

    # No literal defaults here any more. They were the flagship's four content
    # paths, so a story that had lost one of these keys was reported against
    # Edgewood's file -- the doctor said "ok" about a file the running story
    # does not use. An undeclared key is now its own answer.
    for label, path_key in (
        ("economy", "paths.economy"),
        ("procgen", "paths.procgen_templates"),
        ("schedules", "paths.world_schedules"),
        ("art manifest", "paths.art_manifest"),
    ):
        path = cfg.resolve_path(path_key)
        if path is None:
            report.add("Config", label, WARN, f"{path_key} is not declared")
            continue
        exists = path.exists()
        report.add("Config", label, OK if exists else WARN,
                   str(path) if exists else f"missing: {path}")


def check_games(report: Report) -> None:
    """
    Report the active game and validate every manifest on disk.

    Deliberately validates ALL games, not just the active one: a manifest with
    a missing path is a launch that will fail, and the point of a doctor is to
    find that before somebody tries to play it.
    """
    from engine.games.caches import registered_caches
    from engine.games.registry import active_slug, catalog, discover

    current = active_slug()
    manifests = discover()
    if not manifests:
        report.add("Games", "discovery", FAIL,
                   "no games found - expected games/<slug>/game.yaml")
        return

    report.add("Games", "active", OK, f"{current} ({len(manifests)} installed)")
    if current not in manifests:
        report.add("Games", "active", FAIL,
                   f"{current} is selected but has no games/{current}/game.yaml")

    for row in catalog():
        slug = str(row["slug"])
        label = f"{slug}{' (active)' if row['active'] else ''}"
        if row["playable"]:
            report.add("Games", label, OK,
                       f"{row['title']} v{row['version']}, {len(row['paths'])} paths ok")
        else:
            # One line per problem: a manifest with four broken paths should
            # print four lines, not "invalid".
            for problem in row["problems"]:
                report.add("Games", label, FAIL, problem)

    report.add("Games", "cache registry", OK,
               f"{len(registered_caches())} caches invalidated on activation")


def check_inherited_content(report: Report) -> None:
    """
    Which stories are silently reading another story's content.

    THE DEFECT THIS SURFACES. A ``paths.*`` key a story omits does not fall back
    to nothing -- it falls back to ``config/default.yaml``, and twenty-three of
    those defaults point at The Clockwork Dark's own files. So a story that
    forgets ``quests`` does not get no quests; it gets Edgewood's, offered by
    name in a world that has never heard of Edgewood.

    Nothing announced this. It is invisible unless you happen to meet a rumour
    about grain tallies in a fae garden, and by then it looks like a content
    bug rather than a missing line in a manifest.

    THE CAUSE IS FIXED; THIS IS THE GUARD. Every content key in
    ``config/default.yaml`` is empty now, and each story declares what it reads.
    So this check should be quiet forever -- it exists to catch the regression,
    which is somebody adding a real path back to the engine default and
    reintroducing the leak for every story that omits it.

    WARN rather than FAIL because the failure mode is a trap rather than a
    break: the content is reachable but usually unreached, which is precisely
    why it survived undetected. A trap is what a doctor is for.
    """
    import yaml

    from engine.config import project_root
    from engine.games.registry import discover

    root = project_root()
    try:
        with (root / "config" / "default.yaml").open(encoding="utf-8") as handle:
            defaults = (yaml.safe_load(handle) or {}).get("paths") or {}
    except (OSError, yaml.YAMLError) as exc:
        report.add("Story paths", "defaults", WARN, f"could not read config/default.yaml: {exc}")
        return

    # Only keys whose default resolves to a file that EXISTS and is not itself
    # story-scoped or a runtime output directory. Those are the ones where an
    # omission means "read the flagship" rather than "read nothing".
    owned = {"games/", "data/saves", "data/cache", "data/media", "data/telemetry"}
    flagship = {
        key
        for key, value in defaults.items()
        if str(value)
        and not str(value).startswith(tuple(owned))
        and (root / str(value)).exists()
    }

    if not flagship:
        report.add(
            "Story paths", "engine defaults", OK, "name no story's content"
        )
    else:
        # A regression: somebody put a story's file back in the engine default.
        report.add(
            "Story paths",
            "engine defaults",
            WARN,
            f"{len(flagship)} default path(s) name content on disk, which every "
            f"story omitting them will read: {', '.join(sorted(flagship))}",
        )

    for slug, manifest in sorted(discover().items()):
        inherited = sorted(flagship - set(manifest.paths))
        if not inherited:
            report.add("Story paths", slug, OK, "declares every content path it reads")
            continue
        report.add(
            "Story paths",
            slug,
            WARN,
            f"reads {len(inherited)} path(s) it does not declare: {', '.join(inherited)}",
        )


def check_state_schemas(report: Report) -> None:
    """
    Validate every story's declared state, and report its shape.

    Reports counts by BACKING (field-backed values describe an attribute that
    already exists on GameState; bag-backed ones live in the generic containers)
    and by VISIBILITY, because those two numbers are how you tell at a glance
    whether a story has actually been described or is still running on the
    engine spine.

    A schema that will not parse is a FAIL, not a warning: the story asked for
    state it is not going to get.
    """
    from engine.games.registry import active_slug, discover
    from engine.state.schema import (
        BACKING_BAG,
        BACKING_FIELD,
        VISIBILITY_HIDDEN,
        VISIBILITY_PUBLIC,
        VISIBILITY_VEILED,
        SchemaError,
        load_schema,
    )

    current = active_slug()
    manifests = discover()
    if not manifests:
        return

    for slug, manifest in manifests.items():
        label = f"{slug}{' (active)' if slug == current else ''}"
        path = manifest.state_schema_path
        if path is None:
            # Absent is legal everywhere: a story with no state.yaml runs on the
            # engine spine, which is what both shipped games did before schemas.
            report.add("State", label, OK, "no state.yaml - runs on the engine spine")
            continue

        try:
            schema = load_schema(path, slug=slug)
        except SchemaError as exc:
            report.add("State", label, FAIL, f"{path.name}: {exc}")
            continue

        by_backing = {BACKING_FIELD: 0, BACKING_BAG: 0}
        by_visibility = {VISIBILITY_PUBLIC: 0, VISIBILITY_VEILED: 0, VISIBILITY_HIDDEN: 0}
        for spec in schema.values.values():
            by_backing[spec.backing] = by_backing.get(spec.backing, 0) + 1
            by_visibility[spec.visibility] = by_visibility.get(spec.visibility, 0) + 1

        report.add(
            "State",
            label,
            OK if schema.values else WARN,
            "{n} values ({f} field, {b} bag) - {p} public, {v} veiled, {h} hidden".format(
                n=len(schema.values),
                f=by_backing[BACKING_FIELD],
                b=by_backing[BACKING_BAG],
                p=by_visibility[VISIBILITY_PUBLIC],
                v=by_visibility[VISIBILITY_VEILED],
                h=by_visibility[VISIBILITY_HIDDEN],
            )
            if schema.values
            else f"{path.name} declares no values",
        )

        # The load-menu columns are resolved against this schema at save time,
        # where a bad name is a logged warning nobody reads. Here it is visible.
        for name in manifest.save_summary:
            spec = schema.get(name)
            if spec is None:
                report.add("State", label, FAIL,
                           f"save_summary names '{name}', which is not declared")
            elif spec.visibility == VISIBILITY_HIDDEN:
                report.add("State", label, FAIL,
                           f"save_summary names '{name}', which is hidden from the player")


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
    for check in (
        check_python,
        check_config,
        check_games,
        check_state_schemas,
        check_inherited_content,
        check_services,
        check_content,
        check_ui,
        check_saves,
    ):
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
