---
name: clockwork-dark-design
description: Use this skill to generate well-branded interfaces and assets for The Clockwork Dark, a local-first AI roleplaying game, either for production or throwaway prototypes/mocks. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `readme.md` file within this skill, and explore the other available files.

The Clockwork Dark is a moody, local-first AI roleplaying game — *a traveler's journal crossed with a clockmaker's ledger*. The register is **worn, quiet, and slowly wrong**; never epic high fantasy. Honor the canon constraints in `readme.md` (magic is grounded, the Assistant is ambiguous, corruption is organic-mechanical, hidden mechanics stay hidden).

Key files:
- `styles.css` — link this one file to get all tokens + fonts.
- `tokens/` — colors (Hearth Ledger palette + phase themes), typography (4 voices), spacing, effects.
- `components/` — React primitives (Button, ChoiceChip, Badge, StatLine, AssistantBubble, DiceToast, ScenePanel, WorldClock), each with a `.prompt.md`.
- `ui_kits/clockwork-scene/` — the full game scene to copy from.
- `templates/clockwork-scene/` — a one-file **Clockwork Scene** starter (`.dc.html`) consuming projects copy to spin up a styled build fast.
- `assets/` — wordmark, gear motif, woodcut divider, ComfyUI prompt templates.

If creating visual artifacts (slides, mocks, throwaway prototypes), copy assets out and create static HTML files for the user to view. If working on production code, copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without other guidance, ask them what they want to build or design, ask a few questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.
