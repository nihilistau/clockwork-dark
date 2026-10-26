/** The engine's events (v0.24.0 spec §5.1). tests/test_sound_events.py holds this equal to engine/games/sounds.py. */
export const ENGINE_EVENTS = Object.freeze([
  "ui.press", "ui.toggle", "ui.open", "ui.close", "choice.pick", "choice.send", "turn.arrive",
  "roll.cast", "roll.crit_success", "roll.success", "roll.partial", "roll.failure", "roll.crit_failure",
  "alert.error", "link.lost", "link.back", "game.begin", "game.save", "game.ending", "cutscene.start",
  "encounter.start", "panel.wanted", "panel.job", "panel.casing", "plate.reveal",
]);
