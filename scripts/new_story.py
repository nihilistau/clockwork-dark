"""
New Story Scaffolder
====================

Stamp out a playable story skeleton under ``games/<slug>/``:

    .\\.venv\\Scripts\\python.exe scripts\\new_story.py my-story
    .\\.venv\\Scripts\\python.exe scripts\\new_story.py brass-coast --template graph --title "The Brass Coast"
    .\\.venv\\Scripts\\python.exe scripts\\new_story.py red-court --template deck

Three templates, one per shape this engine has actually shipped:

    minimal   the smallest thing that passes validation and plays a turn.
              Three rooms, two items, two agents, one meter, a spoiler table.
              Distilled from games/dev-story/, which is the full worked
              example -- start here unless you already know your shape.
    graph     flagship-shaped: a travel graph with hours on the edges, quests,
              encounters, an economy with vendors, jobs and forage tables.
              The Clockwork Dark's skeleton with the 5,300 lines of Edgewood
              removed.
    deck      Garden-shaped: authored day-decks, progress clocks, threads
              (contracts the world remembers), gated endings and epilogue
              cards. No dice, no travel economy, no doom.

WHY TEMPLATES LIVE IN scripts/story_template/ AND NOT games/. Everything under
``games/`` with a ``game.yaml`` is a real, discoverable, activatable story:
``registry.discover()`` offers it to the picker, and the per-story tests sweep
it. A template full of ``{{slug}}`` tokens must never be either of those
things, so it sits outside the games root where discovery cannot reach it.

WHY THIS COPIES FILES INSTEAD OF GENERATING YAML. A generator that assembles
manifests from Python dicts strips the comments, and the comments are most of
the value: every file these templates ship explains WHY its keys exist, in the
same voice as the shipped stories, so the scaffold is documentation you can
run. The only rewriting done on copy is token substitution -- ``{{slug}}`` and
``{{title}}`` -- which keeps the template diffable against what it emits.

The scaffolder REFUSES to overwrite. An existing ``games/<slug>/`` is someone's
work; a tool that can silently replace it is a tool that will, eventually.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.games.manifest import SLUG_RE  # noqa: E402

TEMPLATES_ROOT = pathlib.Path(__file__).resolve().parent / "story_template"

#: Extensions that get token substitution. Anything else (images, if a
#: template ever ships one) is copied byte-for-byte.
TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".json", ".txt"}


def available_templates() -> list[str]:
    """Template kinds on disk, so the CLI's choices cannot go stale."""
    if not TEMPLATES_ROOT.is_dir():
        return []
    return sorted(
        child.name
        for child in TEMPLATES_ROOT.iterdir()
        if child.is_dir() and not child.name.startswith((".", "_"))
    )


def default_title(slug: str) -> str:
    """``brass-coast`` -> ``Brass Coast``. A placeholder, not a decision."""
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-"))


def scaffold(
    slug: str,
    template: str = "minimal",
    title: str = "",
    games_root: pathlib.Path | None = None,
) -> pathlib.Path:
    """
    Copy one template into ``<games_root>/<slug>/`` with tokens rewritten.

    Args:
        slug: Directory name and story id. Must satisfy the same ``SLUG_RE``
            the registry enforces, because it becomes a config value, a save
            namespace and a URL segment.
        template: One of ``available_templates()``.
        title: Display title; defaults to the slug, title-cased.
        games_root: Where ``<slug>/`` is created. Defaults to the repo's
            ``games/`` directory. This parameter IS the test seam -- the
            scaffolder tests emit into a temp directory and validate there,
            so scaffolding is testable without writing into the repo.

    Returns:
        The created story directory.

    Raises:
        ValueError: Bad slug, unknown template, or the slug already exists.
            All of them before a single file is written -- a partial scaffold
            is worse than none.
    """
    if not SLUG_RE.match(slug or ""):
        raise ValueError(
            f"slug {slug!r} is not usable: lowercase letters, digits and "
            "hyphens, starting with a letter or digit (2-64 chars)"
        )

    source = TEMPLATES_ROOT / template
    if template not in available_templates() or not source.is_dir():
        raise ValueError(
            f"no template {template!r}; available: {', '.join(available_templates())}"
        )

    if games_root is None:
        from engine.config import project_root

        games_root = project_root() / "games"
    destination = pathlib.Path(games_root) / slug
    if destination.exists():
        raise ValueError(
            f"{destination} already exists; the scaffolder never overwrites a story"
        )

    title = (title or "").strip() or default_title(slug)

    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            text = text.replace("{{slug}}", slug).replace("{{title}}", title)
            target.write_text(text, encoding="utf-8", newline="\n")
        else:
            target.write_bytes(path.read_bytes())

    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new story under games/<slug>/ from a template.",
    )
    parser.add_argument("slug", help="story id and directory name, e.g. brass-coast")
    parser.add_argument(
        "--template",
        default="minimal",
        choices=available_templates() or ["minimal"],
        help="which shape to start from (default: minimal)",
    )
    parser.add_argument(
        "--title",
        default="",
        help='display title, e.g. "The Brass Coast" (default: slug, title-cased)',
    )
    args = parser.parse_args(argv)

    try:
        destination = scaffold(args.slug, template=args.template, title=args.title)
    except ValueError as exc:
        parser.error(str(exc))
        return 2  # unreachable; parser.error exits

    print(f"Scaffolded games/{args.slug}/ from the '{args.template}' template.")
    print()
    print("Next steps:")
    print(f"  1. Read {destination / 'README.md'} -- every file says why it exists.")
    print("  2. Check it is sound:")
    print("       .\\.venv\\Scripts\\python.exe scripts\\doctor.py")
    print("       .\\.venv\\Scripts\\python.exe -m pytest tests\\ -q")
    print("  3. Play it:")
    print(f"       .\\.venv\\Scripts\\python.exe launcher.py --game {args.slug}")
    print()
    print(
        "The full worked example is games/dev-story/ -- the templates are "
        "distilled from it, and it shows every subsystem wired and commented."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
