/* @ds-bundle: {"format":3,"namespace":"TheClockworkDarkDesignSystem_4a0a88","components":[{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"ChoiceChip","sourcePath":"components/core/ChoiceChip.jsx"},{"name":"StatLine","sourcePath":"components/core/StatLine.jsx"},{"name":"AssistantBubble","sourcePath":"components/feedback/AssistantBubble.jsx"},{"name":"DiceToast","sourcePath":"components/feedback/DiceToast.jsx"},{"name":"ScenePanel","sourcePath":"components/scene/ScenePanel.jsx"},{"name":"WorldClock","sourcePath":"components/scene/WorldClock.jsx"}],"sourceHashes":{"components/core/Badge.jsx":"7dadc1f78717","components/core/Button.jsx":"21c349de84a4","components/core/ChoiceChip.jsx":"403afd08e4b6","components/core/StatLine.jsx":"4fe379e1f83e","components/feedback/AssistantBubble.jsx":"09e4a9965577","components/feedback/DiceToast.jsx":"8b4a566f3e88","components/scene/ScenePanel.jsx":"c95f970f5cbe","components/scene/WorldClock.jsx":"bf1262b8965a","ui_kits/clockwork-scene/GameScene.jsx":"a044c7959142","ui_kits/clockwork-world/App.jsx":"f5011dc38663","ui_kits/clockwork-world/Atlas.jsx":"1fae7022a342","ui_kits/clockwork-world/Interface.jsx":"fb1337b86b44","ui_kits/clockwork-world/PaintFrame.jsx":"d573718a9c17","ui_kits/clockwork-world/Screens.jsx":"9f5851a14d4a","ui_kits/clockwork-world/Souls.jsx":"1b23a33e98c1","ui_kits/clockwork-world/Things.jsx":"310d9f8ab618","ui_kits/clockwork-world/WorldKit.jsx":"3a260348f2cf","ui_kits/clockwork-world/data.js":"0754ed583c46"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.TheClockworkDarkDesignSystem_4a0a88 = window.TheClockworkDarkDesignSystem_4a0a88 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Badge — a small tracked-smallcaps marker. Tones map to the
 * brand's restrained accent vocabulary. Used for the assistant
 * form tag, weather, phase, item tags.
 */
function Badge({
  tone = "neutral",
  style = {},
  children,
  ...rest
}) {
  const tones = {
    neutral: {
      bg: "transparent",
      fg: "var(--text-muted)",
      bd: "var(--iron-300)"
    },
    candle: {
      bg: "rgba(232,196,122,0.18)",
      fg: "var(--rust-700)",
      bd: "var(--tallow-700)"
    },
    brass: {
      bg: "transparent",
      fg: "var(--rust-clock)",
      bd: "var(--rust-clock)"
    },
    moss: {
      bg: "rgba(107,127,94,0.18)",
      fg: "var(--forest-700)",
      bd: "var(--moss-600)"
    },
    danger: {
      bg: "rgba(107,45,45,0.14)",
      fg: "var(--blood-quiet)",
      bd: "var(--blood-quiet)"
    },
    corruption: {
      bg: "rgba(122,158,79,0.16)",
      fg: "#52662f",
      bd: "var(--corruption)"
    }
  };
  const t = tones[tone] || tones.neutral;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.3rem",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)",
      color: t.fg,
      background: t.bg,
      border: `1px solid ${t.bd}`,
      borderRadius: "var(--radius-sm)",
      padding: "0.12rem 0.42rem",
      lineHeight: 1.5,
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Button — the ledger-button. A pressed, candlelit control with
 * an iron edge. Hover deepens warmth; press insets. No scale tricks.
 */
function Button({
  variant = "primary",
  size = "md",
  disabled = false,
  type = "button",
  iconLeft = null,
  iconRight = null,
  style = {},
  children,
  ...rest
}) {
  const sizes = {
    sm: {
      padding: "0.35rem 0.7rem",
      font: "var(--text-sm)"
    },
    md: {
      padding: "0.5rem 0.95rem",
      font: "var(--text-base)"
    },
    lg: {
      padding: "0.65rem 1.25rem",
      font: "var(--text-md)"
    }
  };
  const variants = {
    primary: {
      background: "var(--accent-candle)",
      color: "var(--iron-900)",
      border: "var(--border-rule) solid var(--iron-700)"
    },
    secondary: {
      background: "var(--surface-card)",
      color: "var(--text-body)",
      border: "var(--border-rule) solid var(--iron-700)"
    },
    ghost: {
      background: "transparent",
      color: "var(--text-on-dark)",
      border: "var(--border-hair) solid var(--accent-candle)"
    },
    danger: {
      background: "var(--status-danger)",
      color: "var(--linen-100)",
      border: "var(--border-rule) solid var(--iron-900)"
    }
  };
  const s = sizes[size] || sizes.md;
  const v = variants[variant] || variants.primary;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    "data-variant": variant,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.4rem",
      fontFamily: "var(--font-ui)",
      fontWeight: "var(--weight-semibold)",
      fontSize: s.font,
      lineHeight: 1,
      padding: s.padding,
      borderRadius: "var(--radius-sm)",
      cursor: disabled ? "wait" : "pointer",
      opacity: disabled ? 0.5 : 1,
      transition: "background var(--dur-fast) var(--ease-quiet), box-shadow var(--dur-fast) var(--ease-quiet), filter var(--dur-fast) var(--ease-quiet)",
      boxShadow: "var(--shadow-sm)",
      ...v,
      ...style
    },
    onMouseDown: e => {
      if (!disabled) e.currentTarget.style.boxShadow = "var(--shadow-inset)";
    },
    onMouseUp: e => {
      e.currentTarget.style.boxShadow = "var(--shadow-sm)";
    },
    onMouseEnter: e => {
      if (!disabled) e.currentTarget.style.filter = "brightness(0.93)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.filter = "none";
      e.currentTarget.style.boxShadow = "var(--shadow-sm)";
    }
  }, rest), iconLeft, children, iconRight);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/ChoiceChip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * ChoiceChip — a narrative choice pill (2–4 per turn). Keyboard
 * 1–4. Disables the instant it's clicked (the turn is in flight).
 * Shows an optional leading index key.
 */
function ChoiceChip({
  index = null,
  disabled = false,
  onClick,
  style = {},
  children,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    disabled: disabled,
    onClick: onClick,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.5rem",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-base)",
      fontWeight: "var(--weight-medium)",
      color: "var(--iron-900)",
      background: "var(--accent-candle)",
      border: "var(--border-rule) solid var(--iron-700)",
      borderRadius: "var(--radius-sm)",
      padding: "0.5rem 0.85rem",
      cursor: disabled ? "wait" : "pointer",
      opacity: disabled ? 0.5 : 1,
      textAlign: "left",
      transition: "filter var(--dur-fast) var(--ease-quiet), box-shadow var(--dur-fast) var(--ease-quiet)",
      boxShadow: "var(--shadow-sm)",
      ...style
    },
    onMouseEnter: e => {
      if (!disabled) e.currentTarget.style.filter = "brightness(0.94)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.filter = "none";
    }
  }, rest), index != null && /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-xs)",
      color: "var(--rust-clock)",
      border: "1px solid var(--rust-clock)",
      borderRadius: "3px",
      padding: "0 0.3rem",
      lineHeight: 1.4
    }
  }, index), /*#__PURE__*/React.createElement("span", null, children));
}
Object.assign(__ds_scope, { ChoiceChip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/ChoiceChip.jsx", error: String((e && e.message) || e) }); }

// components/core/StatLine.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * StatLine — a single ledger row: tracked label left, monospace
 * tabular value right, hairline rule between. The character sheet
 * is a stack of these.
 */
function StatLine({
  label,
  value,
  accent = false,
  style = {},
  ...rest
}) {
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      gap: "0.75rem",
      padding: "0.3rem 0",
      borderBottom: "var(--border-hair) solid var(--line-soft)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)",
      color: "var(--text-muted)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-medium)",
      fontVariantNumeric: "tabular-nums",
      color: accent ? "var(--rust-clock)" : "var(--text-body)"
    }
  }, value));
}
Object.assign(__ds_scope, { StatLine });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/StatLine.jsx", error: String((e && e.message) || e) }); }

// components/feedback/AssistantBubble.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * AssistantBubble — the ambiguous helper's voice. Rounded sans,
 * linen card with a brass left edge and an open corner toward it.
 * Form tag in tracked smallcaps. `whisper` shrinks + italicizes
 * the text and lightens it. Max 3 lines by design — never a
 * tutorial fairy.
 */
function AssistantBubble({
  form = "cat",
  whisper = false,
  hidden = false,
  style = {},
  children,
  ...rest
}) {
  if (hidden) return null;
  return /*#__PURE__*/React.createElement("div", _extends({
    role: "status",
    style: {
      background: "var(--surface-card)",
      borderLeft: "var(--border-mark) solid var(--accent-brass)",
      borderRadius: "0 var(--radius-md) var(--radius-md) 0",
      padding: "0.7rem 0.85rem",
      boxShadow: "var(--shadow-card)",
      maxWidth: "100%",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)",
      color: "var(--accent-brass)",
      marginBottom: "0.3rem"
    }
  }, form), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontFamily: "var(--font-assistant)",
      fontSize: whisper ? "var(--text-sm)" : "var(--text-base)",
      fontStyle: whisper ? "italic" : "normal",
      color: whisper ? "var(--text-muted)" : "var(--text-body)",
      lineHeight: "var(--leading-snug)",
      display: "-webkit-box",
      WebkitLineClamp: 3,
      WebkitBoxOrient: "vertical",
      overflow: "hidden"
    }
  }, children));
}
Object.assign(__ds_scope, { AssistantBubble });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/AssistantBubble.jsx", error: String((e && e.message) || e) }); }

// components/feedback/DiceToast.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * DiceToast — non-blocking center-screen result. Shows the engine's
 * dice line verbatim in mono, with the outcome word tinted by
 * result. Dwells ~1.5s then fades (caller handles timing/mount).
 */
function DiceToast({
  roll,
  modifier = 0,
  dc,
  outcome = "Success",
  style = {},
  ...rest
}) {
  const total = (Number(roll) || 0) + (Number(modifier) || 0);
  const sign = modifier >= 0 ? "+" : "−";
  const win = String(outcome).toLowerCase().startsWith("s");
  const outColor = win ? "var(--forest-500)" : "var(--blood-quiet)";
  return /*#__PURE__*/React.createElement("div", _extends({
    role: "status",
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.6rem",
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-md)",
      background: "var(--surface-chrome)",
      color: "var(--text-on-dark)",
      border: "var(--border-rule) solid var(--accent-brass)",
      borderRadius: "var(--radius-sm)",
      padding: "0.7rem 1.1rem",
      boxShadow: "var(--shadow-raise)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-candlelight)"
    }
  }, "d20:"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontVariantNumeric: "tabular-nums"
    }
  }, roll, " ", sign, " ", Math.abs(modifier), " = ", total), dc != null && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)"
    }
  }, "vs DC ", dc), /*#__PURE__*/React.createElement("span", {
    style: {
      color: outColor,
      fontWeight: "var(--weight-semibold)"
    }
  }, "\u2014 ", outcome));
}
Object.assign(__ds_scope, { DiceToast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/DiceToast.jsx", error: String((e && e.message) || e) }); }

// components/scene/ScenePanel.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * ScenePanel — a journal column surface (assistant / sheet). Tracked
 * smallcaps heading, optional iron edge on one side, paper-calm fill.
 * `surface` chooses the fill; `edge` places the 2px ledger rule.
 */
function ScenePanel({
  title = null,
  surface = "ledger",
  edge = "none",
  style = {},
  children,
  ...rest
}) {
  const surfaces = {
    ledger: "var(--surface-ledger)",
    panel: "var(--surface-panel)",
    narrative: "var(--surface-narrative)",
    card: "var(--surface-card)"
  };
  const edges = {
    none: {},
    left: {
      borderLeft: "var(--border-rule) solid var(--iron-700)"
    },
    right: {
      borderRight: "var(--border-rule) solid var(--iron-700)"
    }
  };
  return /*#__PURE__*/React.createElement("section", _extends({
    style: {
      background: surfaces[surface] || surfaces.ledger,
      padding: "var(--space-4)",
      minHeight: 0,
      ...edges[edge],
      ...style
    }
  }, rest), title && /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: "0 0 var(--space-3)",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)",
      color: "var(--text-body)"
    }
  }, title), children);
}
Object.assign(__ds_scope, { ScenePanel });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/scene/ScenePanel.jsx", error: String((e && e.message) || e) }); }

// components/scene/WorldClock.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * WorldClock — the chrome time readout. Monospace, candlelit, on
 * iron. Once the World Clock is *discovered* in-world, a small gear
 * glyph appears (set `discovered`). Until then it reads as plain
 * diegetic time. Format: "Day 12 · Evening".
 */
function WorldClock({
  day = 1,
  time = "Morning",
  discovered = false,
  style = {},
  ...rest
}) {
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.5rem",
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-sm)",
      color: "var(--text-candlelight)",
      letterSpacing: "0.02em",
      ...style
    }
  }, rest), discovered && /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      width: "13px",
      height: "13px",
      display: "inline-block",
      borderRadius: "50%",
      border: "1.5px solid var(--rust-300)",
      boxShadow: "inset 0 0 0 2px var(--surface-chrome)",
      position: "relative",
      top: "1px"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontVariantNumeric: "tabular-nums"
    }
  }, "Day ", day, " \xB7 ", time));
}
Object.assign(__ds_scope, { WorldClock });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/scene/WorldClock.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-scene/GameScene.jsx
try { (() => {
/* GameScene — interactive recreation of The Clockwork Dark scene.
   "Lit by tallow and mistrust": a cold, grim Ash & Thorn frame —
   slate shadow and bleak air — with a slight tinker-brass accent and
   the journal glowing as the one warm, lit thing. Composes the DS
   components with a faked turn loop and a phase switcher.
   Globals (bundle): Button, ChoiceChip, Badge, StatLine,
   AssistantBubble, DiceToast, ScenePanel, WorldClock. */

const NS = window.TheClockworkDarkDesignSystem_4a0a88;
const {
  Button,
  ChoiceChip,
  Badge,
  StatLine,
  AssistantBubble,
  DiceToast,
  ScenePanel,
  WorldClock
} = NS;
const {
  useState,
  useRef,
  useEffect
} = React;

// ---- Fake content (drawn from data/lore + economy) ----
const SCENES = {
  forest_clearing: {
    title: "The Forest Clearing",
    caption: "Birch margin · dawn mist",
    tint: "radial-gradient(120% 78% at 52% 6%, rgba(214,178,108,.22), transparent 48%), linear-gradient(178deg,#10171a 0%,#18211d 42%,#26302a 74%,#34392e 100%)",
    narration: "You wake where the birch gives way to fern. Mushroom circles, game trails that double back when watched. Smoke from Edgewood drifts west — even though the wind blows south.",
    choices: [{
      id: "smoke",
      text: "Walk toward the smoke"
    }, {
      id: "forage",
      text: "Forage the clearing"
    }, {
      id: "listen",
      text: "Listen"
    }],
    assistant: {
      form: "cat",
      text: "The smoke is bread, not burning. Probably."
    }
  },
  edgewood_square: {
    title: "Edgewood Square",
    caption: "Communal oven · failing light",
    tint: "radial-gradient(100% 76% at 64% 12%, rgba(214,150,80,.26), transparent 46%), linear-gradient(178deg,#10161a 0%,#1b2020 44%,#33291d 80%,#43321f 100%)",
    narration: "Timber frames lean together around the communal oven. A shrine to unnamed saints keeps its candle. Maris hums at the bakery door, flour on her sleeves — villagers say she hums to keep the gears quiet.",
    choices: [{
      id: "bakery",
      text: "Visit Maris at the bakery"
    }, {
      id: "board",
      text: "Read the notice board"
    }, {
      id: "shrine",
      text: "Study the unfinished mural"
    }],
    assistant: {
      form: "cat",
      text: "Stay near the oven light. It is honest."
    }
  },
  tinker_caravan: {
    title: "The Tinker Caravan",
    caption: "Nine-pin tent · last of the dusk",
    tint: "radial-gradient(110% 78% at 50% 20%, rgba(190,118,58,.28), transparent 50%), linear-gradient(178deg,#12120f 0%,#241a13 46%,#3c2818 80%,#553a22 100%)",
    narration: "Nine brass pins glint in Ilya's scarf. Charms hang from the tent ribs; chalk symbols mark roads that shift when the wheat turns wrong. A sympathy lamp burns with no flame you can name.",
    choices: [{
      id: "barter",
      text: "Barter for a sympathy charm"
    }, {
      id: "map",
      text: "Ask about the road to Millhaven"
    }, {
      id: "leave",
      text: "Step back into the dusk"
    }],
    assistant: {
      form: "tinker",
      text: "Ilya counts you twice. Once for now. Once for later."
    }
  }
};
const ORDER = ["forest_clearing", "edgewood_square", "tinker_caravan"];
const PHASES = ["dormant", "stirring", "spreading", "consuming"];
function SceneVisual({
  scene,
  phase
}) {
  const wrong = phase === "spreading" || phase === "consuming";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      height: "min(38vh, 300px)",
      minHeight: 190,
      background: scene.tint,
      overflow: "hidden",
      borderBottom: "1px solid rgba(214,178,108,.22)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "cw-flicker",
    style: {
      position: "absolute",
      inset: 0,
      background: "radial-gradient(54% 46% at 52% 14%, rgba(214,178,108,.24), transparent 62%)",
      mixBlendMode: "screen"
    }
  }), wrong && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      background: "var(--corruption)",
      opacity: phase === "consuming" ? 0.28 : 0.15,
      mixBlendMode: "color"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      backgroundImage: "var(--texture-paper)",
      opacity: 0.62,
      mixBlendMode: "multiply"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      boxShadow: "inset 0 0 140px 30px rgba(6,9,9,.86)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      height: 30,
      background: "linear-gradient(180deg, rgba(6,9,9,.9), transparent)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      bottom: 0,
      left: 0,
      right: 0,
      height: 56,
      background: "linear-gradient(0deg, rgba(6,9,9,.75), transparent)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 9,
      right: 13,
      fontFamily: "var(--font-mono)",
      fontSize: 10,
      letterSpacing: ".12em",
      textTransform: "uppercase",
      color: "rgba(214,178,108,.42)"
    }
  }, "ComfyUI still \xB7 ", scene.title), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 15,
      bottom: 13,
      display: "flex",
      gap: 8,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    tone: "candle",
    style: {
      background: "rgba(14,16,12,.6)",
      color: "var(--tallow-300)",
      borderColor: "var(--tallow-700)"
    }
  }, scene.caption), wrong && /*#__PURE__*/React.createElement(Badge, {
    tone: "corruption",
    style: {
      background: "rgba(16,20,8,.6)"
    }
  }, "Wrong rain")));
}
function GameScene() {
  const [started, setStarted] = useState(false);
  const [archetype, setArchetype] = useState("wayfarer");
  const [sceneIdx, setSceneIdx] = useState(0);
  const [phase, setPhase] = useState("stirring");
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [stats, setStats] = useState({
    hp: "18/18",
    stamina: 6,
    gold: "0.00",
    day: 11,
    time: "Dusk"
  });
  const [input, setInput] = useState("");
  const logRef = useRef(null);
  const sceneId = ORDER[sceneIdx];
  const scene = SCENES[sceneId];
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);
  function begin() {
    setStarted(true);
    setLog([{
      kind: "narration",
      text: scene.narration
    }]);
    setTimeout(() => setAssistantOpen(true), 600);
  }
  function rollDice() {
    const roll = 1 + Math.floor(Math.random() * 20);
    const mod = 2,
      dc = 13;
    const outcome = roll === 20 ? "Boon" : roll === 1 ? "Complication" : roll + mod >= dc ? "Success" : "Failure";
    setToast({
      roll,
      modifier: mod,
      dc,
      outcome
    });
    setTimeout(() => setToast(null), 1500);
    return outcome;
  }
  function choose(choice) {
    if (busy) return;
    setBusy(true);
    setLog(l => [...l, {
      kind: "player",
      text: choice.text
    }]);
    const outcome = rollDice();
    setTimeout(() => {
      let next = sceneIdx;
      if (choice.id === "smoke" || choice.id === "bakery") next = Math.min(sceneIdx + 1, ORDER.length - 1);
      if (choice.id === "map") next = 2;
      const nextScene = SCENES[ORDER[next]];
      const tail = outcome === "Failure" ? " You slip — the moment costs you a breath of stamina." : outcome === "Boon" ? " Something others missed catches your eye. A free clue." : "";
      setLog(l => [...l, {
        kind: "narration",
        text: nextScene.narration + tail
      }]);
      setStats(s => ({
        ...s,
        stamina: Math.max(0, s.stamina - (outcome === "Failure" ? 1 : 0)),
        time: s.time === "Dusk" ? "Night" : s.time === "Night" ? "Deep night" : "Dusk",
        day: next !== sceneIdx ? s.day + 1 : s.day
      }));
      if (next !== sceneIdx) {
        setSceneIdx(next);
        setAssistantOpen(false);
        setTimeout(() => setAssistantOpen(true), 700);
      }
      setBusy(false);
    }, 700);
  }
  function sendCustom(e) {
    e.preventDefault();
    const t = input.trim();
    if (!t || busy) return;
    setInput("");
    choose({
      id: "custom",
      text: t
    });
  }

  // ---- Start screen ----
  if (!started) {
    const archetypes = [{
      id: "wayfarer",
      name: "Wayfarer",
      note: "Cloak, staff, road boots"
    }, {
      id: "hearthkeeper",
      name: "Hearthkeeper",
      note: "Apron, flour, warm colors"
    }, {
      id: "tinker",
      name: "Tinker-apprentice",
      note: "Tool belt, brass pins, chalk"
    }];
    return /*#__PURE__*/React.createElement("div", {
      "data-phase": phase,
      style: frameStyle
    }, /*#__PURE__*/React.createElement(Atmosphere, null), /*#__PURE__*/React.createElement("div", {
      style: {
        position: "relative",
        flex: 1,
        display: "grid",
        placeItems: "center",
        padding: 24
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 470,
        background: "linear-gradient(168deg, #1d2119 0%, #14160f 100%)",
        padding: "34px 36px",
        borderRadius: 3,
        boxShadow: "0 0 0 1px rgba(214,178,108,.22), 0 34px 90px -22px rgba(0,0,0,.92), 0 0 130px -8px rgba(214,178,108,.12)",
        borderTop: "1px solid rgba(214,178,108,.14)",
        borderLeft: "var(--border-mark) solid var(--rust-clock)"
      }
    }, /*#__PURE__*/React.createElement("img", {
      src: "../../assets/wordmark.svg",
      alt: "The Clockwork Dark",
      style: {
        width: 300,
        marginBottom: 18,
        filter: "drop-shadow(0 2px 12px rgba(0,0,0,.6))"
      }
    }), /*#__PURE__*/React.createElement("p", {
      style: {
        fontFamily: "var(--font-narration)",
        fontSize: "var(--text-lg)",
        lineHeight: "var(--leading-relaxed)",
        color: "var(--text-narration)",
        margin: "0 0 22px"
      }
    }, "You wake at the margin of an old forest, the last comfortable village a smudge of smoke to the west. The roads have begun to change when no one is watching. Choose how you came to be here."), /*#__PURE__*/React.createElement("p", {
      style: smallcaps
    }, "Traveler"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 8,
        marginBottom: 22
      }
    }, archetypes.map(a => /*#__PURE__*/React.createElement("button", {
      key: a.id,
      onClick: () => setArchetype(a.id),
      style: {
        textAlign: "left",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "11px 14px",
        cursor: "pointer",
        fontFamily: "var(--font-ui)",
        background: archetype === a.id ? "rgba(214,178,108,.14)" : "rgba(255,255,255,.03)",
        border: archetype === a.id ? "var(--border-rule) solid var(--rust-clock)" : "var(--border-rule) solid rgba(214,178,108,.16)",
        borderRadius: "var(--radius-sm)",
        boxShadow: archetype === a.id ? "var(--glow-candle)" : "none",
        transition: "all var(--dur-fast) var(--ease-quiet)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 600,
        color: "var(--text-on-dark)"
      }
    }, a.name), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "var(--text-sm)",
        color: "var(--text-muted)"
      }
    }, a.note)))), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      onClick: begin,
      style: {
        width: "100%",
        justifyContent: "center"
      }
    }, "Step into the clearing"))));
  }

  // ---- Scene ----
  return /*#__PURE__*/React.createElement("div", {
    "data-phase": phase,
    style: frameStyle
  }, /*#__PURE__*/React.createElement(Atmosphere, null), /*#__PURE__*/React.createElement("header", {
    style: {
      position: "relative",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "11px 20px",
      background: "linear-gradient(180deg,#090d0e,#0f1210)",
      borderBottom: "1px solid rgba(214,178,108,.2)",
      boxShadow: "0 2px 16px rgba(0,0,0,.7)",
      zIndex: 2
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 11
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/gear-motif.svg",
    alt: "",
    className: "cw-turn",
    style: {
      width: 22,
      opacity: 0.92,
      filter: "brightness(1.3) drop-shadow(0 0 8px rgba(190,118,58,.5))"
    }
  }), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      color: "var(--text-on-dark)",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-base)",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-title)"
    }
  }, scene.title)), /*#__PURE__*/React.createElement(WorldClock, {
    day: stats.day,
    time: stats.time,
    discovered: phase !== "dormant"
  })), /*#__PURE__*/React.createElement("main", {
    style: {
      position: "relative",
      flex: 1,
      display: "grid",
      gridTemplateColumns: "var(--col-assistant) 1fr var(--col-sheet)",
      minHeight: 0,
      zIndex: 1
    }
  }, /*#__PURE__*/React.createElement(ScenePanel, {
    surface: "panel",
    edge: "right",
    style: {
      display: "flex",
      flexDirection: "column",
      background: "linear-gradient(180deg, #1a2220 0%, #10150f 100%)",
      borderRight: "1px solid rgba(214,178,108,.13)",
      boxShadow: "inset -18px 0 32px -26px #000"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      ...smallcaps,
      color: "var(--tallow-300)"
    }
  }, "Assistant"), /*#__PURE__*/React.createElement(AssistantBubble, {
    form: scene.assistant.form,
    hidden: !assistantOpen,
    style: {
      boxShadow: "var(--shadow-raise), 0 0 30px -6px rgba(214,178,108,.42)"
    }
  }, scene.assistant.text), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "var(--text-sm)",
      color: "rgba(214,210,190,.34)",
      margin: 0,
      lineHeight: 1.45
    }
  }, "Something watches from the stillness without moving.")), /*#__PURE__*/React.createElement("section", {
    style: {
      display: "flex",
      flexDirection: "column",
      minHeight: 0,
      background: "#0a0d0a",
      boxShadow: "0 0 100px -12px rgba(214,178,108,.14)"
    }
  }, /*#__PURE__*/React.createElement(SceneVisual, {
    scene: scene,
    phase: phase
  }), /*#__PURE__*/React.createElement("div", {
    ref: logRef,
    className: "cw-log",
    style: {
      position: "relative",
      flex: 1,
      overflowY: "auto",
      overflowX: "hidden",
      padding: "22px 26px",
      minHeight: 0,
      background: "linear-gradient(180deg, #1c2019 0%, #14160f 100%)",
      backgroundImage: "var(--texture-paper)",
      boxShadow: "inset 0 18px 26px -20px rgba(0,0,0,.7), inset 0 -18px 26px -20px rgba(0,0,0,.6)"
    }
  }, log.map((entry, i) => entry.kind === "narration" ? /*#__PURE__*/React.createElement("p", {
    key: i,
    style: {
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      lineHeight: "var(--leading-relaxed)",
      color: "var(--text-narration)",
      margin: "0 0 16px",
      textWrap: "pretty"
    }
  }, entry.text) : /*#__PURE__*/React.createElement("p", {
    key: i,
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-sm)",
      fontStyle: "italic",
      color: "var(--accent-candle)",
      margin: "0 0 16px",
      paddingLeft: 12,
      borderLeft: "var(--border-mark) solid var(--rust-500)"
    }
  }, "You chose: ", entry.text))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 8,
      padding: "14px 26px 12px",
      background: "#0d100d",
      borderTop: "1px solid rgba(214,178,108,.13)"
    }
  }, scene.choices.map((c, i) => /*#__PURE__*/React.createElement(ChoiceChip, {
    key: c.id,
    index: i + 1,
    disabled: busy,
    onClick: () => choose(c),
    style: {
      boxShadow: "0 3px 12px -3px rgba(0,0,0,.6)"
    }
  }, c.text))), /*#__PURE__*/React.createElement("form", {
    onSubmit: sendCustom,
    style: {
      display: "flex",
      gap: 8,
      padding: "0 26px 16px 26px",
      background: "#0d100d"
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: input,
    onChange: e => setInput(e.target.value),
    placeholder: "Or type an action\u2026",
    style: {
      flex: 1,
      padding: "10px 12px",
      border: "var(--border-hair) solid #2f342c",
      borderRadius: "var(--radius-sm)",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-base)",
      background: "#161a14",
      color: "var(--text-on-dark)"
    }
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    type: "submit",
    disabled: busy
  }, "Send"))), /*#__PURE__*/React.createElement(ScenePanel, {
    title: null,
    surface: "ledger",
    edge: "left",
    style: {
      background: "linear-gradient(180deg, #181811 0%, #12120b 100%)",
      borderLeft: "1px solid rgba(214,178,108,.13)",
      boxShadow: "inset 18px 0 32px -26px #000"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      ...smallcaps,
      color: "var(--tallow-300)"
    }
  }, "Traveler"), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(DarkStat, {
    label: "HP",
    value: stats.hp
  }), /*#__PURE__*/React.createElement(DarkStat, {
    label: "Stamina",
    value: stats.stamina
  }), /*#__PURE__*/React.createElement(DarkStat, {
    label: "Gold",
    value: stats.gold,
    accent: true
  }), /*#__PURE__*/React.createElement(DarkStat, {
    label: "Location",
    value: sceneId.replace("_", " ")
  })), /*#__PURE__*/React.createElement("p", {
    style: {
      ...smallcaps,
      color: "var(--tallow-300)",
      marginTop: 18
    }
  }, "Inventory"), /*#__PURE__*/React.createElement("ul", {
    style: {
      listStyle: "none",
      padding: 0,
      margin: 0,
      display: "flex",
      flexDirection: "column",
      gap: 7
    }
  }, ["Loaf of bread ×1", "Whetstone ×1", "Wild mushroom ×3", "Tallow candle ×2"].map(it => /*#__PURE__*/React.createElement("li", {
    key: it,
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-sm)",
      color: "var(--linen-300)"
    }
  }, it))))), /*#__PURE__*/React.createElement("footer", {
    style: {
      position: "relative",
      display: "flex",
      alignItems: "center",
      gap: 16,
      padding: "9px 20px",
      background: "linear-gradient(0deg,#090d0e,#0f1210)",
      color: "var(--text-on-dark)",
      fontSize: "var(--text-sm)",
      borderTop: "1px solid rgba(214,178,108,.2)",
      zIndex: 2
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-candlelight)"
    }
  }, "Day ", stats.day, " \xB7 ", stats.time, " \xB7 ", phase === "spreading" || phase === "consuming" ? "Wrong rain" : "Overcast"), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)"
    }
  }, "Evil phase"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 4
    }
  }, PHASES.map(p => /*#__PURE__*/React.createElement("button", {
    key: p,
    onClick: () => setPhase(p),
    title: p,
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      textTransform: "capitalize",
      padding: "4px 10px",
      cursor: "pointer",
      borderRadius: "var(--radius-sm)",
      border: "1px solid " + (phase === p ? "var(--accent-candle)" : "#2f342c"),
      background: phase === p ? "rgba(214,178,108,.18)" : "transparent",
      color: phase === p ? "var(--text-candlelight)" : "var(--text-muted)",
      boxShadow: phase === p ? "0 0 14px -4px rgba(214,178,108,.6)" : "none",
      transition: "all var(--dur-fast) var(--ease-quiet)"
    }
  }, p)))), toast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      display: "grid",
      placeItems: "center",
      pointerEvents: "none",
      zIndex: 5
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "cw-toast",
    style: {
      filter: "drop-shadow(0 14px 34px rgba(0,0,0,.7))"
    }
  }, /*#__PURE__*/React.createElement(DiceToast, toast))));
}
function DarkStat({
  label,
  value,
  accent
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      padding: "5px 0",
      borderBottom: "1px solid rgba(214,178,108,.13)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)",
      color: "rgba(214,206,184,.58)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-sm)",
      fontVariantNumeric: "tabular-nums",
      color: accent ? "var(--tallow-300)" : "var(--linen-200)"
    }
  }, value));
}

// Ambient overlay: cold corner shadow + faint air over the whole frame.
function Atmosphere() {
  return /*#__PURE__*/React.createElement("div", {
    "aria-hidden": "true",
    style: {
      position: "absolute",
      inset: 0,
      pointerEvents: "none",
      zIndex: 0,
      boxShadow: "inset 0 0 220px 50px rgba(4,6,6,.74)",
      background: "radial-gradient(140% 120% at 50% -10%, transparent 58%, rgba(4,6,6,.55))"
    }
  });
}
const frameStyle = {
  position: "relative",
  width: "100%",
  height: "100%",
  minHeight: 0,
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
  background: "radial-gradient(120% 100% at 50% 0%, #12181a, #060909 72%)"
};
const smallcaps = {
  margin: "0 0 10px",
  fontFamily: "var(--font-ui)",
  fontSize: "var(--text-xs)",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "var(--tracking-label)",
  color: "var(--text-body)"
};
window.GameScene = GameScene;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-scene/GameScene.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/App.jsx
try { (() => {
/* App — The Clockwork Dark: World & Interface.
   A grim-dark interactive bible: places, souls, things, the HUD, and
   the live playable scene. Ash & Thorn throughout. Sections are
   registered on window by their own files. */

const {
  useState: useAppState
} = React;
const TABS = [{
  id: "atlas",
  label: "Atlas",
  sub: "Places & buildings"
}, {
  id: "souls",
  label: "Souls",
  sub: "Characters, the cat, the wizard"
}, {
  id: "things",
  label: "Things",
  sub: "Items & relics"
}, {
  id: "interface",
  label: "Interface",
  sub: "HUD & panel design"
}, {
  id: "screens",
  label: "Screens",
  sub: "Trade · Bakery · Millhaven"
}, {
  id: "play",
  label: "Play",
  sub: "The live scene"
}];
function NavItem({
  tab,
  active,
  onClick
}) {
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    style: {
      display: "block",
      width: "100%",
      textAlign: "left",
      cursor: "pointer",
      padding: "11px 16px",
      border: "none",
      borderLeft: "3px solid " + (active ? "var(--accent-candle)" : "transparent"),
      background: active ? "linear-gradient(90deg, rgba(214,178,108,.14), transparent)" : "transparent",
      transition: "all var(--dur-fast) var(--ease-quiet)"
    },
    onMouseEnter: e => {
      if (!active) e.currentTarget.style.background = "rgba(255,255,255,.03)";
    },
    onMouseLeave: e => {
      if (!active) e.currentTarget.style.background = "transparent";
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-base)",
      fontWeight: 600,
      letterSpacing: ".02em",
      color: active ? "var(--text-candlelight)" : "var(--text-on-dark)"
    }
  }, tab.label), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)",
      marginTop: 2
    }
  }, tab.sub));
}
function App() {
  const [tab, setTab] = useAppState("atlas");
  const Section = {
    atlas: window.Atlas,
    souls: window.Souls,
    things: window.Things,
    interface: window.InterfaceKit,
    screens: window.Screens,
    play: window.PlaySection
  }[tab];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "248px 1fr",
      height: "100vh",
      minHeight: 0,
      background: "radial-gradient(120% 100% at 50% 0%, #10161a, #050807 72%)",
      color: "var(--text-on-dark)"
    }
  }, /*#__PURE__*/React.createElement("aside", {
    style: {
      display: "flex",
      flexDirection: "column",
      minHeight: 0,
      background: "linear-gradient(180deg,#090d0e,#060908)",
      borderRight: "1px solid rgba(214,178,108,.16)",
      boxShadow: "inset -20px 0 40px -30px #000"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px 16px 16px",
      borderBottom: "1px solid rgba(214,178,108,.12)"
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/wordmark.svg",
    alt: "The Clockwork Dark",
    style: {
      width: 196,
      filter: "drop-shadow(0 2px 10px rgba(0,0,0,.6))"
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "12px 2px 0",
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "var(--text-sm)",
      color: "rgba(214,178,108,.6)"
    }
  }, "World & interface bible")), /*#__PURE__*/React.createElement("nav", {
    style: {
      padding: "10px 0",
      flex: 1,
      overflowY: "auto"
    }
  }, TABS.map(t => /*#__PURE__*/React.createElement(NavItem, {
    key: t.id,
    tab: t,
    active: tab === t.id,
    onClick: () => setTab(t.id)
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "14px 16px",
      borderTop: "1px solid rgba(214,178,108,.12)",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      letterSpacing: ".06em",
      textTransform: "uppercase",
      color: "var(--text-muted)",
      lineHeight: 1.7
    }
  }, /*#__PURE__*/React.createElement("div", null, "Hearth Ledger \xB7 Ash & Thorn"), /*#__PURE__*/React.createElement("div", {
    style: {
      color: "rgba(214,178,108,.5)"
    }
  }, "v0.1 \xB7 grim-dark"))), /*#__PURE__*/React.createElement("main", {
    style: {
      minHeight: 0,
      overflowY: tab === "play" ? "hidden" : "auto",
      position: "relative"
    }
  }, Section ? /*#__PURE__*/React.createElement(Section, null) : /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 40
    }
  }, "Loading\u2026")));
}
window.CWApp = App;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/App.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/Atlas.jsx
try { (() => {
/* Atlas — places & buildings of the Heartlands' margin. */

function PlaceCard({
  p
}) {
  return /*#__PURE__*/React.createElement("article", {
    style: {
      background: "linear-gradient(180deg,#0e1311,#0a0d0b)",
      border: "1px solid rgba(214,178,108,.14)",
      borderRadius: "var(--radius-sm)",
      overflow: "hidden",
      boxShadow: "0 14px 34px -16px rgba(0,0,0,.8)"
    }
  }, /*#__PURE__*/React.createElement(PaintFrame, {
    tint: p.tint,
    glow: p.glow,
    caption: p.caption,
    corrupted: p.corrupted,
    ratio: "16/9"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "16px 18px 18px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-xl)",
      fontWeight: 500,
      color: "var(--text-on-dark)"
    }
  }, p.name), /*#__PURE__*/React.createElement(Pill, {
    brass: true
  }, p.kind)), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "9px 0 0",
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-base)",
      lineHeight: 1.5,
      color: "rgba(226,220,201,.7)"
    }
  }, p.blurb), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 6,
      marginTop: 12
    }
  }, p.times.map(t => /*#__PURE__*/React.createElement(Pill, {
    key: t
  }, t))), /*#__PURE__*/React.createElement(Prompt, null, p.prompt), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "10px 0 0",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      fontStyle: "italic",
      color: "var(--text-muted)"
    }
  }, p.note)));
}
function Atlas() {
  const places = window.CW_DATA.places;
  const weather = window.CW_DATA.weather;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionHead, {
    kicker: "The Atlas",
    title: "Places & buildings",
    lede: "A frontier village at the edge of an old forest. Beauty in bread steam and moss; dread at the margin where the wheat turns wrong. Every location is a ComfyUI 16:9 still \u2014 no characters centre-frame."
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "26px 40px 40px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
      gap: 22
    }
  }, places.map(p => /*#__PURE__*/React.createElement(PlaceCard, {
    key: p.id,
    p: p
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 38
    }
  }, /*#__PURE__*/React.createElement(Kicker, null, "Weather \u2014 footer state & image modifier"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 12
    }
  }, weather.map(w => /*#__PURE__*/React.createElement("div", {
    key: w.key,
    style: {
      flex: "1 1 150px",
      minWidth: 150,
      padding: "14px 16px",
      borderRadius: "var(--radius-sm)",
      background: w.corrupted ? "rgba(122,158,79,.08)" : "rgba(255,255,255,.03)",
      border: "1px solid " + (w.corrupted ? "rgba(122,158,79,.3)" : "rgba(214,178,108,.16)")
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-sm)",
      color: w.corrupted ? "var(--corruption)" : "var(--text-candlelight)",
      textTransform: "uppercase",
      letterSpacing: ".06em"
    }
  }, w.label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)",
      marginTop: 5
    }
  }, w.note)))))));
}
window.Atlas = Atlas;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/Atlas.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/Interface.jsx
try { (() => {
/* Interface — the HUD anatomy and panel designs. */

const IF = window.TheClockworkDarkDesignSystem_4a0a88;
function Card({
  title,
  children,
  span
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      gridColumn: span ? `span ${span}` : "auto",
      borderRadius: "var(--radius-md)",
      background: "linear-gradient(180deg,#0e1311,#090c0a)",
      border: "1px solid rgba(214,178,108,.14)",
      boxShadow: "0 14px 34px -18px rgba(0,0,0,.8)",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "12px 16px",
      borderBottom: "1px solid rgba(214,178,108,.1)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)",
      color: "var(--accent-brass)"
    }
  }, title)), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 18
    }
  }, children));
}
function HudAnatomy() {
  const cell = (bg, label, sub, extra) => /*#__PURE__*/React.createElement("div", {
    style: {
      background: bg,
      border: "1px solid rgba(214,178,108,.16)",
      borderRadius: 3,
      padding: "10px 11px",
      display: "flex",
      flexDirection: "column",
      gap: 4,
      ...extra
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 10,
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: ".08em",
      color: "var(--text-candlelight)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 10,
      color: "var(--text-muted)"
    }
  }, sub));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateRows: "auto 1fr auto",
      gap: 6,
      height: 300
    }
  }, cell("linear-gradient(180deg,#0c0f0d,#0a0c0a)", "Header", "Scene name · World clock"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "0.8fr 1.6fr 0.9fr",
      gap: 6,
      minHeight: 0
    }
  }, cell("linear-gradient(180deg,#141a16,#0d120f)", "Assistant", "200px · slides from left"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateRows: "1.1fr auto auto",
      gap: 6,
      minHeight: 0
    }
  }, cell("linear-gradient(160deg,#1a201b,#10140f)", "Scene visual", "ComfyUI still · 38vh"), cell("linear-gradient(180deg,#1c2019,#14160f)", "Narrative log", "SSE serif · the lit journal"), cell("#0d100d", "Choices + input", "2–4 chips · free text")), cell("linear-gradient(180deg,#181811,#11120b)", "Character sheet", "220px · HP · STA · inv")), cell("linear-gradient(0deg,#0c0f0d,#0a0c0a)", "Footer", "Day · time · weather · phase"));
}
function Letterbox() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      aspectRatio: "2.39/1",
      background: "#000",
      borderRadius: 3,
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      background: "radial-gradient(80% 80% at 50% 30%, rgba(190,118,58,.22), transparent 60%), linear-gradient(180deg,#10140f,#1a160f)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      backgroundImage: "var(--texture-paper)",
      opacity: .5,
      mixBlendMode: "multiply"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      boxShadow: "inset 0 0 90px 20px rgba(6,8,5,.85)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 0,
      padding: "12px 16px",
      background: "linear-gradient(0deg, rgba(6,8,5,.9), transparent)"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "var(--text-base)",
      color: "rgba(226,220,201,.92)",
      textShadow: "0 1px 3px #000"
    }
  }, "\"The village clock stopped at a hour that never was.\"")), /*#__PURE__*/React.createElement("button", {
    style: {
      position: "absolute",
      top: 10,
      right: 12,
      fontFamily: "var(--font-ui)",
      fontSize: 11,
      padding: "3px 9px",
      borderRadius: 3,
      cursor: "pointer",
      color: "rgba(226,220,201,.7)",
      background: "rgba(12,12,9,.5)",
      border: "1px solid rgba(214,178,108,.25)"
    }
  }, "Skip"));
}
function CombatSheet() {
  const {
    Button
  } = IF;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      borderRadius: 3,
      overflow: "hidden",
      background: "linear-gradient(180deg,#15100f,#0c0a0a)",
      padding: 16,
      border: "1px solid rgba(122,45,42,.4)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      boxShadow: "inset 0 0 60px 8px rgba(107,45,45,.45)",
      pointerEvents: "none"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      color: "var(--text-on-dark)"
    }
  }, "Brass-toothed lamb"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-sm)",
      color: "var(--status-danger)"
    }
  }, "HP 9")), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 6,
      borderRadius: 3,
      marginTop: 8,
      background: "rgba(0,0,0,.5)",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "64%",
      height: "100%",
      background: "linear-gradient(90deg, var(--blood-quiet), #a14)"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 14,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "danger",
    size: "sm"
  }, "Strike"), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm"
  }, "Ward"), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm"
  }, "Flee")), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "12px 0 0",
      fontFamily: "var(--font-ui)",
      fontSize: 11,
      fontStyle: "italic",
      color: "var(--text-muted)"
    }
  }, "No battle animations in v0.1 \u2014 still image with a red vignette pulse.")));
}
function Interface() {
  const {
    AssistantBubble,
    DiceToast,
    ChoiceChip,
    WorldClock,
    Badge,
    StatLine
  } = IF;
  const phases = window.CW_DATA.phases;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionHead, {
    kicker: "The Interface",
    title: "HUD & panel design",
    lede: "A traveler's journal crossed with a clockmaker's ledger. No MMO clutter, no floating UI, no Awareness meter \u2014 hidden mechanics stay hidden until discovered in-world."
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "26px 40px 40px",
      display: "grid",
      gridTemplateColumns: "repeat(2, 1fr)",
      gap: 22
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "HUD anatomy \u2014 global layout",
    span: 2
  }, /*#__PURE__*/React.createElement(HudAnatomy, null)), /*#__PURE__*/React.createElement(Card, {
    title: "Assistant bubble \u2014 forms & whisper"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement(AssistantBubble, {
    form: "cat",
    style: {
      boxShadow: "var(--shadow-raise), 0 0 26px -6px rgba(214,178,108,.4)"
    }
  }, "The smoke is bread, not burning. Probably."), /*#__PURE__*/React.createElement(AssistantBubble, {
    form: "wanderer",
    whisper: true,
    style: {
      boxShadow: "var(--shadow-raise)"
    }
  }, "Roads change when the wheat turns wrong."))), /*#__PURE__*/React.createElement(Card, {
    title: "Dice toast \u2014 verbatim engine result"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12,
      alignItems: "flex-start"
    }
  }, /*#__PURE__*/React.createElement(DiceToast, {
    roll: 14,
    modifier: 2,
    dc: 13,
    outcome: "Success"
  }), /*#__PURE__*/React.createElement(DiceToast, {
    roll: 4,
    modifier: 1,
    dc: 12,
    outcome: "Failure"
  }), /*#__PURE__*/React.createElement(DiceToast, {
    roll: 20,
    modifier: 0,
    outcome: "Boon"
  }))), /*#__PURE__*/React.createElement(Card, {
    title: "Choice chips \u2014 2\u20134, keyboard 1\u20134"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(ChoiceChip, {
    index: 1
  }, "Walk toward smoke"), /*#__PURE__*/React.createElement(ChoiceChip, {
    index: 2
  }, "Forage the clearing"), /*#__PURE__*/React.createElement(ChoiceChip, {
    index: 3
  }, "Listen"), /*#__PURE__*/React.createElement(ChoiceChip, {
    index: 4,
    disabled: true
  }, "Wait\u2026"))), /*#__PURE__*/React.createElement(Card, {
    title: "World clock & weather \u2014 diegetic"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-chrome)",
      padding: "10px 14px",
      borderRadius: 3,
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 12,
      textTransform: "uppercase",
      letterSpacing: ".1em",
      color: "var(--text-on-dark)"
    }
  }, "Edgewood Square"), /*#__PURE__*/React.createElement(WorldClock, {
    day: 12,
    time: "Evening",
    discovered: true
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    tone: "neutral"
  }, "Overcast"), /*#__PURE__*/React.createElement(Badge, {
    tone: "candle"
  }, "Market day"), /*#__PURE__*/React.createElement(Badge, {
    tone: "corruption"
  }, "Wrong rain")))), /*#__PURE__*/React.createElement(Card, {
    title: "Character sheet \u2014 the ledger"
  }, /*#__PURE__*/React.createElement(StatLine, {
    label: "HP",
    value: "14/18"
  }), /*#__PURE__*/React.createElement(StatLine, {
    label: "Stamina",
    value: "6"
  }), /*#__PURE__*/React.createElement(StatLine, {
    label: "Gold",
    value: "0.42",
    accent: true
  }), /*#__PURE__*/React.createElement(StatLine, {
    label: "Location",
    value: "edgewood"
  })), /*#__PURE__*/React.createElement(Card, {
    title: "Cutscene \u2014 2.39:1 letterbox"
  }, /*#__PURE__*/React.createElement(Letterbox, null)), /*#__PURE__*/React.createElement(Card, {
    title: "Combat sheet \u2014 rare, minimal"
  }, /*#__PURE__*/React.createElement(CombatSheet, null)), /*#__PURE__*/React.createElement(Card, {
    title: "Phase transition \u2014 UI behavior",
    span: 2
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 14
    }
  }, phases.map((p, i) => /*#__PURE__*/React.createElement("div", {
    key: p.key,
    "data-phase": p.key,
    style: {
      borderRadius: 3,
      overflow: "hidden",
      border: "1px solid rgba(214,178,108,.16)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 52,
      background: "var(--surface-scene)",
      display: "grid",
      placeItems: "center",
      boxShadow: "inset 0 0 26px rgba(6,8,5,.7)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--accent-candle)"
    }
  }, "Day ", [4, 11, 22, 38][i])), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 12px",
      background: "linear-gradient(180deg,#0e1311,#0a0d0b)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 12,
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: ".06em",
      color: "var(--text-candlelight)"
    }
  }, p.label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-narration)",
      fontSize: 12,
      fontStyle: "italic",
      color: "rgba(226,220,201,.62)",
      marginTop: 4
    }
  }, p.mood), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 11,
      color: "var(--text-muted)",
      marginTop: 6
    }
  }, p.ui))))))));
}
window.InterfaceKit = Interface;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/Interface.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/PaintFrame.jsx
try { (() => {
/* PaintFrame — a painterly placeholder frame standing in for ComfyUI art.
   Layered earth-gradient + candle bloom + paper grain + an abstract
   CSS silhouette. NOT final art: production stills are generated from
   the prompts shown beside each frame. Keeps everything honest while
   giving each subject a distinct, recognisable mood. */

const {
  useState: _useState
} = React;
function Silhouette({
  kind,
  robe = "#5a6a4a",
  accent = "#e8c47a",
  scale = 1
}) {
  const base = {
    position: "absolute",
    left: "50%",
    transform: "translateX(-50%)"
  };
  const eye = left => ({
    position: "absolute",
    top: 0,
    left,
    width: 6 * scale,
    height: 6 * scale,
    borderRadius: "50%",
    background: accent,
    boxShadow: `0 0 ${8 * scale}px ${accent}`
  });
  if (kind === "cat") {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        inset: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "8%",
        width: 120 * scale,
        height: 90 * scale,
        background: robe,
        borderRadius: "46% 46% 40% 40% / 60% 60% 40% 40%",
        filter: "blur(0.4px)"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "44%",
        marginLeft: -34 * scale,
        width: 0,
        height: 0,
        borderLeft: `${14 * scale}px solid transparent`,
        borderRight: `${10 * scale}px solid transparent`,
        borderBottom: `${26 * scale}px solid ${robe}`
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "44%",
        marginLeft: 34 * scale,
        width: 0,
        height: 0,
        borderLeft: `${10 * scale}px solid transparent`,
        borderRight: `${14 * scale}px solid transparent`,
        borderBottom: `${26 * scale}px solid ${robe}`
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "30%",
        width: 76 * scale,
        height: 64 * scale,
        background: robe,
        borderRadius: "48% 48% 46% 46%"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        bottom: "10%",
        right: "20%",
        width: 60 * scale,
        height: 16 * scale,
        background: robe,
        borderRadius: "50%",
        transform: "rotate(-28deg)"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "40%",
        width: 40 * scale,
        height: 6 * scale
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: eye(2)
    }), /*#__PURE__*/React.createElement("div", {
      style: eye(32 * scale)
    })));
  }
  if (kind === "hood" || kind === "wizard") {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        inset: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: 0,
        width: 150 * scale,
        height: 170 * scale,
        background: `linear-gradient(180deg, ${robe} 0%, rgba(0,0,0,.55) 120%)`,
        borderRadius: "44% 44% 12% 12% / 70% 70% 12% 12%"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "44%",
        width: 104 * scale,
        height: 116 * scale,
        background: robe,
        borderRadius: "50% 50% 38% 38% / 62% 62% 40% 40%"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "52%",
        width: 52 * scale,
        height: 64 * scale,
        background: "radial-gradient(circle at 50% 40%, #0d100c, #14140f)",
        borderRadius: "50% 50% 46% 46%"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        ...base,
        bottom: "64%",
        width: 34 * scale,
        height: 6 * scale
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: eye(0)
    }), /*#__PURE__*/React.createElement("div", {
      style: eye(28 * scale)
    })));
  }
  if (kind === "mirror") {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        inset: 0
      }
    }, /*#__PURE__*/React.createElement(Silhouette, {
      kind: "person",
      robe: robe,
      accent: accent,
      scale: scale * 0.82
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        inset: 0,
        top: "62%",
        transform: "scaleY(-1)",
        opacity: 0.4,
        maskImage: "linear-gradient(180deg, transparent, #000 80%)",
        WebkitMaskImage: "linear-gradient(180deg, transparent, #000 80%)"
      }
    }, /*#__PURE__*/React.createElement(Silhouette, {
      kind: "person",
      robe: accent,
      accent: robe,
      scale: scale * 0.82
    })));
  }

  // person / child
  const s = kind === "child" ? scale * 0.72 : scale;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      ...base,
      bottom: 0,
      width: 150 * s,
      height: 130 * s,
      background: `linear-gradient(180deg, ${robe} 0%, rgba(0,0,0,.5) 130%)`,
      borderRadius: "46% 46% 16% 16% / 64% 64% 16% 16%"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      ...base,
      bottom: "46%",
      width: 72 * s,
      height: 86 * s,
      background: robe,
      borderRadius: "48% 48% 44% 44%"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      ...base,
      bottom: "50%",
      width: 50 * s,
      height: 60 * s,
      background: "radial-gradient(circle at 50% 38%, rgba(0,0,0,.28), transparent 70%)",
      borderRadius: "50%"
    }
  }));
}
function PaintFrame({
  tint,
  glow,
  caption,
  sil,
  robe,
  accent,
  corrupted,
  ratio = "16/9",
  height,
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      width: "100%",
      aspectRatio: height ? undefined : ratio,
      height: height || undefined,
      overflow: "hidden",
      background: tint || "var(--surface-scene)",
      border: "var(--border-rule) solid var(--iron-900)",
      boxShadow: "var(--shadow-card)"
    }
  }, glow && /*#__PURE__*/React.createElement("div", {
    className: "cw-flicker",
    style: {
      position: "absolute",
      inset: 0,
      background: glow,
      mixBlendMode: "screen"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 0,
      height: "42%",
      background: "linear-gradient(0deg, rgba(160,150,120,.10), transparent)",
      mixBlendMode: "screen"
    }
  }), sil && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: "50%",
      bottom: "5%",
      width: "46%",
      height: 16,
      transform: "translateX(-50%)",
      borderRadius: "50%",
      background: "radial-gradient(closest-side, rgba(0,0,0,.55), transparent)",
      filter: "blur(2px)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      filter: `drop-shadow(0 0 1px ${accent || "#d6b26c"}) drop-shadow(0 0 9px ${hexShadow(accent)})`
    }
  }, /*#__PURE__*/React.createElement(Silhouette, {
    kind: sil,
    robe: robe,
    accent: accent
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: "-10%",
      left: "30%",
      width: "40%",
      height: "85%",
      background: "linear-gradient(180deg, rgba(214,178,108,.12), transparent 72%)",
      transform: "skewX(-9deg)",
      mixBlendMode: "screen",
      pointerEvents: "none"
    }
  }), corrupted && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      background: "var(--corruption)",
      opacity: 0.16,
      mixBlendMode: "color"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      backgroundImage: "var(--texture-paper)",
      opacity: 0.55,
      mixBlendMode: "multiply"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      boxShadow: "inset 0 0 70px 12px rgba(8,9,6,.7)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      height: 22,
      background: "linear-gradient(180deg, rgba(6,8,5,.6), transparent)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 8,
      right: 10,
      fontFamily: "var(--font-mono)",
      fontSize: 10,
      letterSpacing: ".08em",
      textTransform: "uppercase",
      color: "rgba(242,232,213,.5)"
    }
  }, "ComfyUI still"), caption && /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      left: 10,
      bottom: 10,
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "var(--text-sm)",
      color: "rgba(242,232,213,.92)",
      textShadow: "0 1px 3px rgba(0,0,0,.6)"
    }
  }, caption), children);
}
window.Silhouette = Silhouette;
window.PaintFrame = PaintFrame;
function hexShadow(hex) {
  if (!hex || hex[0] !== "#") return "rgba(214,178,108,.35)";
  let h = hex.slice(1);
  if (h.length === 3) h = h.split("").map(c => c + c).join("");
  const n = parseInt(h, 16);
  return `rgba(${n >> 16 & 255}, ${n >> 8 & 255}, ${n & 255}, .35)`;
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/PaintFrame.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/Screens.jsx
try { (() => {
/* Screens — three full interface mockups: Trade, Bakery, Millhaven.
   Composes DS components in grim-dark Ash & Thorn. */

const SC = window.TheClockworkDarkDesignSystem_4a0a88;
const {
  useState: useScState,
  useEffect: useScEffect,
  useRef: useScRef
} = React;
function ScreenFrame({
  tint,
  caption,
  children,
  corrupted
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: "var(--radius-md)",
      overflow: "hidden",
      border: "1px solid rgba(214,178,108,.16)",
      boxShadow: "0 20px 50px -22px rgba(0,0,0,.85)",
      background: "linear-gradient(180deg,#0c100e,#080a09)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      height: 150
    }
  }, /*#__PURE__*/React.createElement(PaintFrame, {
    tint: tint,
    caption: caption,
    corrupted: corrupted,
    height: 150
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, children));
}

/* ---------------- TRADE / BARTER OVERLAY ---------------- */
function TradeScreen() {
  const {
    Button,
    Badge
  } = SC;
  const give = [{
    name: "Wild mushroom",
    qty: 3,
    tint: "#8a6b4a",
    worth: 1
  }, {
    name: "Resin",
    qty: 2,
    tint: "#a9683a",
    worth: 1
  }, {
    name: "River clay",
    qty: 1,
    tint: "#7a6a52",
    worth: 1
  }];
  const get = [{
    name: "Sympathy charm",
    qty: 1,
    tint: "#b8863f",
    worth: 25,
    brass: true
  }, {
    name: "Tinker knowledge map",
    qty: 1,
    tint: "#caa05a",
    worth: 20
  }];
  const [offered, setOffered] = useScState([true, true, false]);
  const giveTotal = give.reduce((s, g, i) => s + (offered[i] ? g.worth * g.qty : 0), 0);
  const getTotal = 45;
  const balance = giveTotal - getTotal;
  const Row = ({
    it,
    on,
    toggle
  }) => /*#__PURE__*/React.createElement("button", {
    onClick: toggle,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      width: "100%",
      textAlign: "left",
      cursor: toggle ? "pointer" : "default",
      padding: "9px 11px",
      borderRadius: "var(--radius-sm)",
      background: on === false ? "rgba(255,255,255,.02)" : "rgba(214,178,108,.07)",
      border: "1px solid " + (on === false ? "rgba(214,178,108,.1)" : "rgba(214,178,108,.22)"),
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 30,
      height: 30,
      flex: "none",
      borderRadius: it.brass ? "50%" : 6,
      background: `linear-gradient(160deg, ${it.tint}, rgba(0,0,0,.55))`,
      border: it.brass ? "1px solid rgba(214,178,108,.5)" : "1px solid rgba(0,0,0,.4)",
      boxShadow: "inset 0 1px 2px rgba(255,255,255,.2)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-base)",
      color: "var(--text-on-dark)"
    }
  }, it.name, " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)",
      fontFamily: "var(--font-mono)",
      fontSize: 12
    }
  }, "\xD7", it.qty)), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      color: "var(--text-candlelight)"
    }
  }, it.worth * it.qty, "c"));
  return /*#__PURE__*/React.createElement(ScreenFrame, {
    tint: "radial-gradient(110% 78% at 50% 18%, rgba(190,118,58,.30), transparent 52%), linear-gradient(178deg,#12120f 0%,#241a13 50%,#553a22 100%)",
    caption: "Ilya's wagon \xB7 barter, not coin"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-xl)",
      color: "var(--text-on-dark)"
    }
  }, "Barter with Ilya of the Nine Pins"), /*#__PURE__*/React.createElement(Badge, {
    tone: "brass"
  }, "Caravan")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: kickerS
  }, "You give"), give.map((g, i) => /*#__PURE__*/React.createElement(Row, {
    key: g.name,
    it: g,
    on: offered[i],
    toggle: () => setOffered(o => o.map((v, j) => j === i ? !v : v))
  })), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 11,
      color: "var(--text-muted)",
      fontStyle: "italic",
      margin: "4px 2px"
    }
  }, "Tap to add or hold back.")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: kickerS
  }, "Ilya offers"), get.map(g => /*#__PURE__*/React.createElement(Row, {
    key: g.name,
    it: g,
    on: true,
    toggle: null
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 18,
      padding: "14px 16px",
      borderRadius: "var(--radius-sm)",
      background: "rgba(0,0,0,.3)",
      border: "1px solid rgba(214,178,108,.16)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 12,
      textTransform: "uppercase",
      letterSpacing: ".08em",
      color: "var(--text-muted)"
    }
  }, "Balance"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-md)",
      color: balance >= 0 ? "#8fae5a" : "var(--status-danger)"
    }
  }, balance >= 0 ? "Fair — Ilya nods" : `${Math.abs(balance)}c short`)), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      marginTop: 10,
      borderRadius: 4,
      background: "rgba(0,0,0,.5)",
      overflow: "hidden",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: "50%",
      top: 0,
      bottom: 0,
      width: 1,
      background: "rgba(214,178,108,.4)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: balance >= 0 ? "50%" : 50 + balance / getTotal * 50 + "%",
      right: balance >= 0 ? 50 - Math.min(balance, getTotal) / getTotal * 50 + "%" : "50%",
      top: 0,
      bottom: 0,
      background: balance >= 0 ? "linear-gradient(90deg,#5a6f3a,#8fae5a)" : "linear-gradient(90deg,#6b2d2d,#a14)"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 10,
      marginTop: 16,
      justifyContent: "flex-end"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost"
  }, "Step back"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    disabled: balance < 0
  }, "Strike the bargain")));
}

/* ---------------- BAKERY DOMESTIC UI ---------------- */
function OvenTimer() {
  const TOTAL = 12 * 60;
  const [left, setLeft] = useScState(7 * 60 + 42);
  const [running, setRunning] = useScState(true);
  useScEffect(() => {
    if (!running) return;
    const id = setInterval(() => setLeft(l => l <= 0 ? TOTAL : l - 1), 1000);
    return () => clearInterval(id);
  }, [running]);
  const pct = (1 - left / TOTAL) * 100;
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  const done = left <= 0;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      width: 168,
      height: 168,
      borderRadius: "50%",
      background: `conic-gradient(var(--accent-candle) ${pct}%, rgba(255,255,255,.06) ${pct}%)`,
      display: "grid",
      placeItems: "center",
      boxShadow: "0 0 40px -8px rgba(214,178,108,.45)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 12,
      borderRadius: "50%",
      background: "radial-gradient(circle at 50% 36%, #2a1c10, #120c07)",
      boxShadow: "inset 0 0 30px rgba(214,140,60,.4)",
      display: "grid",
      placeItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 30,
      fontVariantNumeric: "tabular-nums",
      color: done ? "#8fae5a" : "var(--text-candlelight)"
    }
  }, done ? "Ready" : `${mm}:${ss}`), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 10,
      textTransform: "uppercase",
      letterSpacing: ".14em",
      color: "var(--text-muted)",
      marginTop: 3
    }
  }, "Oven \xB7 loaf")))), /*#__PURE__*/React.createElement("button", {
    onClick: () => setRunning(r => !r),
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 12,
      padding: "5px 14px",
      borderRadius: "var(--radius-sm)",
      cursor: "pointer",
      color: "var(--text-candlelight)",
      background: "rgba(214,178,108,.1)",
      border: "1px solid rgba(214,178,108,.3)"
    }
  }, running ? "Tend the fire" : "Stoke"));
}
function BakeryScreen() {
  const {
    Button,
    Badge
  } = SC;
  const recipes = [{
    name: "Loaf of bread",
    needs: ["Flour", "Water", "Salt"],
    time: "12m",
    active: true
  }, {
    name: "Mushroom pottage",
    needs: ["Wild mushroom ×2", "Water", "Herbs"],
    time: "20m"
  }, {
    name: "Festival cake",
    needs: ["Flour", "Honey", "Dried fruit"],
    time: "35m"
  }];
  return /*#__PURE__*/React.createElement(ScreenFrame, {
    tint: "radial-gradient(90% 90% at 32% 56%, rgba(214,150,80,.46), transparent 60%), linear-gradient(178deg,#1a120c,#3a2414 60%,#6b4524 100%)",
    caption: "The Hearth Bakery \xB7 morning prep"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-xl)",
      color: "var(--text-on-dark)"
    }
  }, "Maris's hearth \u2014 baking"), /*#__PURE__*/React.createElement(Badge, {
    tone: "candle"
  }, "Domestic")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "200px 1fr",
      gap: 24,
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement(OvenTimer, null), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: kickerS
  }, "Recipes"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 10
    }
  }, recipes.map(r => /*#__PURE__*/React.createElement("div", {
    key: r.name,
    style: {
      padding: "11px 13px",
      borderRadius: "var(--radius-sm)",
      background: r.active ? "rgba(214,178,108,.08)" : "rgba(255,255,255,.02)",
      border: "1px solid " + (r.active ? "rgba(214,178,108,.28)" : "rgba(214,178,108,.1)")
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      color: "var(--text-on-dark)"
    }
  }, r.name), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      color: "var(--text-candlelight)"
    }
  }, r.time)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 6,
      marginTop: 8
    }
  }, r.needs.map(n => /*#__PURE__*/React.createElement("span", {
    key: n,
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 11,
      padding: "2px 8px",
      borderRadius: 999,
      background: "rgba(0,0,0,.3)",
      border: "1px solid rgba(214,178,108,.16)",
      color: "rgba(226,220,201,.72)"
    }
  }, n))), r.active && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 11
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm"
  }, "Knead & set"))))), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "var(--text-base)",
      color: "rgba(214,178,108,.6)",
      margin: "16px 0 0"
    }
  }, "She hums to keep the gears quiet."))));
}

/* ---------------- MILLHAVEN MILITIA SCENE ---------------- */
function MillhavenScreen() {
  const {
    Button,
    ChoiceChip,
    Badge,
    StatLine,
    AssistantBubble
  } = SC;
  return /*#__PURE__*/React.createElement(ScreenFrame, {
    tint: "radial-gradient(120% 90% at 50% 16%, rgba(150,166,170,.20), transparent 55%), linear-gradient(178deg,#0c1114,#1d262b 55%,#39434a 100%)",
    caption: "Millhaven gate \xB7 cold rain"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-xl)",
      color: "var(--text-on-dark)"
    }
  }, "The palisade gate"), /*#__PURE__*/React.createElement(Badge, {
    tone: "danger"
  }, "Duty")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 220px",
      gap: 22
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      lineHeight: "var(--leading-relaxed)",
      color: "var(--text-narration)",
      margin: 0
    }
  }, "Sergeant Sera meets you under the dripping banner, scar pale in the lantern light. Refugees thin the mud road behind her. \"The road from the Heartlands is wrong tonight,\" she says. \"I can spare you the gate, or your silence. Not both.\""), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(AssistantBubble, {
    form: "wanderer",
    whisper: true,
    style: {
      boxShadow: "var(--shadow-raise)"
    }
  }, "She is not lying. That is what frightens her.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 8,
      marginTop: 18
    }
  }, /*#__PURE__*/React.createElement(ChoiceChip, {
    index: 1
  }, "Show your road map"), /*#__PURE__*/React.createElement(ChoiceChip, {
    index: 2
  }, "Offer to stand the watch"), /*#__PURE__*/React.createElement(ChoiceChip, {
    index: 3
  }, "Ask what she saw"))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "14px 15px",
      borderRadius: "var(--radius-sm)",
      background: "linear-gradient(180deg,#11161a,#0b0f12)",
      border: "1px solid rgba(150,166,170,.2)"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      ...kickerS,
      color: "#9aa6a8"
    }
  }, "Gate watch"), /*#__PURE__*/React.createElement(StatLine, {
    label: "Militia",
    value: "6 fit"
  }), /*#__PURE__*/React.createElement(StatLine, {
    label: "Refugees",
    value: "23"
  }), /*#__PURE__*/React.createElement(StatLine, {
    label: "Rations",
    value: "4 days",
    accent: true
  }), /*#__PURE__*/React.createElement(StatLine, {
    label: "Road",
    value: "wrong"
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      ...kickerS,
      color: "#9aa6a8",
      marginTop: 16
    }
  }, "Orders"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 12,
      color: "rgba(226,220,201,.7)",
      lineHeight: 1.5,
      margin: 0
    }
  }, "Hold the gate. Admit the hungry. Report any brass."), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "danger",
    size: "sm",
    style: {
      width: "100%",
      justifyContent: "center"
    }
  }, "Sound the bell")))));
}
const kickerS = {
  margin: "0 0 12px",
  fontFamily: "var(--font-ui)",
  fontSize: "var(--text-xs)",
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "var(--tracking-label)",
  color: "var(--accent-brass)"
};
function Screens() {
  const [tab, setTab] = useScState("trade");
  const subs = [{
    id: "trade",
    label: "Trade · Barter"
  }, {
    id: "bakery",
    label: "Bakery · Hearth"
  }, {
    id: "millhaven",
    label: "Millhaven · Gate"
  }];
  const View = {
    trade: TradeScreen,
    bakery: BakeryScreen,
    millhaven: MillhavenScreen
  }[tab];
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionHead, {
    kicker: "The Screens",
    title: "Scenes & domestic UI",
    lede: "Beyond the forest turn: a barter overlay (goods, never floating coin), Maris's baking hearth (domestic UI as polished as adventure UI), and the cold militia gate at Millhaven."
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px 40px 40px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginBottom: 22
    }
  }, subs.map(s => /*#__PURE__*/React.createElement("button", {
    key: s.id,
    onClick: () => setTab(s.id),
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-sm)",
      fontWeight: 600,
      padding: "8px 16px",
      cursor: "pointer",
      borderRadius: "var(--radius-sm)",
      border: "1px solid " + (tab === s.id ? "var(--accent-candle)" : "rgba(214,178,108,.2)"),
      background: tab === s.id ? "rgba(214,178,108,.16)" : "transparent",
      color: tab === s.id ? "var(--text-candlelight)" : "var(--text-muted)",
      boxShadow: tab === s.id ? "0 0 16px -5px rgba(214,178,108,.55)" : "none",
      transition: "all var(--dur-fast) var(--ease-quiet)"
    }
  }, s.label))), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 720
    }
  }, /*#__PURE__*/React.createElement(View, null))));
}
window.Screens = Screens;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/Screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/Souls.jsx
try { (() => {
/* Souls — the people, the cat, and the Assistant's many faces. */

function NpcCard({
  n
}) {
  return /*#__PURE__*/React.createElement("article", {
    style: {
      background: "linear-gradient(180deg,#0e1311,#0a0d0b)",
      border: "1px solid rgba(214,178,108,.14)",
      borderRadius: "var(--radius-sm)",
      overflow: "hidden",
      boxShadow: "0 14px 34px -16px rgba(0,0,0,.8)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement(PaintFrame, {
    tint: n.tint,
    sil: n.sil,
    accent: n.accent,
    robe: "#2a2a22",
    ratio: "4/3",
    caption: n.role
  }), n.ambiguous && /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 8,
      left: 10,
      fontFamily: "var(--font-mono)",
      fontSize: 9,
      letterSpacing: ".1em",
      textTransform: "uppercase",
      color: "rgba(214,178,108,.7)",
      background: "rgba(16,16,12,.6)",
      padding: "2px 6px",
      borderRadius: 3
    }
  }, "ambiguous")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "14px 16px 16px"
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      fontWeight: 500,
      color: "var(--text-on-dark)"
    }
  }, n.name), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "3px 0 0",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      textTransform: "uppercase",
      letterSpacing: ".06em",
      color: "var(--accent-brass)"
    }
  }, n.mood), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "9px 0 0",
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-base)",
      lineHeight: 1.5,
      color: "rgba(226,220,201,.7)"
    }
  }, n.blurb), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "10px 0 0",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-muted)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--accent-brass)",
      textTransform: "uppercase",
      letterSpacing: ".08em"
    }
  }, "Voice"), " \xB7 ", n.voice)));
}
function RobePanel({
  r
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: "var(--radius-sm)",
      overflow: "hidden",
      border: "1px solid rgba(214,178,108,.16)",
      boxShadow: "0 14px 34px -16px rgba(0,0,0,.85)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      height: 220,
      background: `radial-gradient(80% 60% at 50% 16%, rgba(214,178,108,.18), transparent 58%), linear-gradient(180deg, #0c0f0d, #07090800)`
    }
  }, /*#__PURE__*/React.createElement(PaintFrame, {
    tint: "linear-gradient(180deg,#0c100e,#070908)",
    sil: "wizard",
    robe: r.hex,
    accent: r.trim,
    height: 220
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 9,
      left: 11,
      fontFamily: "var(--font-mono)",
      fontSize: 9,
      letterSpacing: ".1em",
      textTransform: "uppercase",
      color: "rgba(214,178,108,.7)",
      background: "rgba(12,12,9,.6)",
      padding: "2px 7px",
      borderRadius: 3
    }
  }, r.phase)), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "14px 16px 16px",
      background: "linear-gradient(180deg,#0e1311,#0a0d0b)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 9
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 16,
      height: 16,
      borderRadius: "50%",
      background: r.hex,
      boxShadow: "0 0 0 1px rgba(255,255,255,.12), 0 0 10px " + r.hex
    }
  }), /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      fontWeight: 500,
      color: "var(--text-on-dark)"
    }
  }, r.name)), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "8px 0 0",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      textTransform: "uppercase",
      letterSpacing: ".06em",
      color: "var(--accent-brass)"
    }
  }, r.reads), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "8px 0 0",
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-base)",
      lineHeight: 1.5,
      color: "rgba(226,220,201,.7)"
    }
  }, r.blurb)));
}
function FormChip({
  f
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "100%",
      aspectRatio: "1/1",
      borderRadius: "var(--radius-sm)",
      overflow: "hidden",
      border: "1px solid rgba(214,178,108,.16)",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement(PaintFrame, {
    tint: "linear-gradient(180deg,#0e1311,#070908)",
    sil: f.sil,
    robe: f.robe,
    accent: "#d6b26c",
    height: 120
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-sm)",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: ".06em",
      color: "var(--text-candlelight)"
    }
  }, f.form), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "11px",
      color: "var(--text-muted)",
      marginTop: 2
    }
  }, f.when), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "12px",
      color: "rgba(226,220,201,.6)",
      marginTop: 4
    }
  }, f.note));
}
function Souls() {
  const D = window.CW_DATA;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionHead, {
    kicker: "The Souls",
    title: "Characters & the Assistant",
    lede: "Edgewood is poor but proud \u2014 frontier means mixed travelers, drawn with respect, never caricature. And the Assistant is never a tutorial fairy: it begins as a cat and grows into something robed and certain."
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "26px 40px 40px"
    }
  }, /*#__PURE__*/React.createElement(Kicker, null, "Villagers & the cat \u2014 portrait briefs (3:4)"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
      gap: 20
    }
  }, D.npcs.map(n => /*#__PURE__*/React.createElement(NpcCard, {
    key: n.id,
    n: n
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 44,
      padding: "26px 28px",
      borderRadius: "var(--radius-md)",
      background: "radial-gradient(90% 100% at 50% 0%, rgba(190,118,58,.08), transparent 60%), linear-gradient(180deg,#0c100e,#080a09)",
      border: "1px solid rgba(214,178,108,.16)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      flexWrap: "wrap",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-2xl)",
      fontWeight: 500,
      color: "var(--text-on-dark)"
    }
  }, "The Assistant Wizard \u2014 robe study"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      maxWidth: 420,
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "var(--text-base)",
      color: "rgba(214,178,108,.7)"
    }
  }, "The hooded form's robe reads its intent. White mercy \u2192 grey watching \u2192 red appetite \u2192 black the Clockwork Dark itself.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 18,
      marginTop: 22
    }
  }, D.robes.map(r => /*#__PURE__*/React.createElement(RobePanel, {
    key: r.key,
    r: r
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 40
    }
  }, /*#__PURE__*/React.createElement(Kicker, null, "The five canonical forms"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(5, 1fr)",
      gap: 16
    }
  }, D.assistantForms.map(f => /*#__PURE__*/React.createElement(FormChip, {
    key: f.form,
    f: f
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 40
    }
  }, /*#__PURE__*/React.createElement(Kicker, null, "Player archetypes \u2014 silhouette, not class"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3, 1fr)",
      gap: 18
    }
  }, D.archetypes.map(a => /*#__PURE__*/React.createElement("div", {
    key: a.id,
    style: {
      display: "flex",
      gap: 14,
      padding: "14px 16px",
      borderRadius: "var(--radius-sm)",
      background: "linear-gradient(180deg,#0e1311,#0a0d0b)",
      border: "1px solid rgba(214,178,108,.14)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 64,
      flex: "none",
      borderRadius: 3,
      overflow: "hidden",
      border: "1px solid rgba(214,178,108,.14)"
    }
  }, /*#__PURE__*/React.createElement(PaintFrame, {
    tint: a.tint,
    sil: "person",
    robe: "#2a2a20",
    accent: "#d6b26c",
    height: 84
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      fontWeight: 500,
      color: "var(--text-on-dark)"
    }
  }, a.name), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "4px 0 0",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      color: "var(--accent-brass)"
    }
  }, a.gear), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "5px 0 0",
      fontFamily: "var(--font-narration)",
      fontSize: "13px",
      color: "rgba(226,220,201,.65)"
    }
  }, a.look))))))));
}
window.Souls = Souls;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/Souls.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/Things.jsx
try { (() => {
/* Things — items, tools, wards, and the wrong relics. */

function ItemTile({
  it
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      borderRadius: "var(--radius-sm)",
      overflow: "hidden",
      border: "1px solid " + (it.corrupted ? "rgba(122,158,79,.3)" : "rgba(214,178,108,.14)"),
      background: "linear-gradient(180deg,#0e1311,#0a0d0b)",
      boxShadow: "0 10px 26px -14px rgba(0,0,0,.8)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      height: 96,
      background: `radial-gradient(70% 80% at 50% 30%, ${hexA(it.tint, .9)}, ${hexA(it.tint, .25)} 70%, #0a0d0b)`,
      display: "grid",
      placeItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 46,
      height: 46,
      borderRadius: it.brass ? "50%" : "30% 30% 36% 36%",
      background: `linear-gradient(160deg, ${it.tint}, rgba(0,0,0,.5))`,
      boxShadow: "inset 0 1px 3px rgba(255,255,255,.2), 0 4px 10px rgba(0,0,0,.5)",
      border: it.brass ? "1px solid rgba(214,178,108,.5)" : "1px solid rgba(0,0,0,.3)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      backgroundImage: "var(--texture-paper)",
      opacity: .4,
      mixBlendMode: "multiply"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      boxShadow: "inset 0 0 30px rgba(8,9,6,.7)"
    }
  }), it.corrupted && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      background: "var(--corruption)",
      opacity: .12,
      mixBlendMode: "color"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 6,
      right: 7,
      fontFamily: "var(--font-mono)",
      fontSize: 9,
      color: it.corrupted ? "var(--corruption)" : "rgba(214,178,108,.6)",
      textTransform: "uppercase",
      letterSpacing: ".06em"
    }
  }, it.tag)), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 12px 12px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-sm)",
      fontWeight: 600,
      color: "var(--text-on-dark)"
    }
  }, it.name), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginTop: 5
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "11px",
      color: "var(--text-muted)"
    }
  }, it.from), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      color: it.price === "—" ? "var(--text-muted)" : "var(--text-candlelight)"
    }
  }, it.price))));
}
function hexA(hex, a) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
  return `rgba(${n >> 16 & 255}, ${n >> 8 & 255}, ${n & 255}, ${a})`;
}
function Things() {
  const items = window.CW_DATA.items;
  const groups = ["Food", "Forage", "Material", "Tool", "Knowledge", "Ward", "Light", "Apparel", "Craft", "Quest", "Wrong"];
  const used = groups.filter(g => items.some(i => i.tag === g));
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionHead, {
    kicker: "The Things",
    title: "Items & relics",
    lede: "Honest names, copper prices \u2014 never gold coins floating in the air. Item icons are flat 1:1 illustrations. The 'wrong' relics carry brass where brass should not be."
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "26px 40px 40px"
    }
  }, used.map(g => /*#__PURE__*/React.createElement("div", {
    key: g,
    style: {
      marginBottom: 30
    }
  }, /*#__PURE__*/React.createElement(Kicker, null, g === "Wrong" ? "Wrong — corruption relics (gated)" : g), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(168px, 1fr))",
      gap: 16
    }
  }, items.filter(i => i.tag === g).map(it => /*#__PURE__*/React.createElement(ItemTile, {
    key: it.name,
    it: it
  }))))), /*#__PURE__*/React.createElement("p", {
    style: {
      marginTop: 8,
      fontFamily: "var(--font-narration)",
      fontStyle: "italic",
      fontSize: "var(--text-base)",
      color: "rgba(214,178,108,.6)"
    }
  }, "Prices in copper \xB7 gold = 100 copper display. Seeds for each icon live in assets/comfyui-prompts.md.")));
}
window.Things = Things;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/Things.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/WorldKit.jsx
try { (() => {
/* Shared presentational helpers for the world bible — all grim-dark. */

function SectionHead({
  kicker,
  title,
  lede
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      padding: "34px 40px 18px",
      borderBottom: "1px solid rgba(214,178,108,.12)",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/gear-motif.svg",
    alt: "",
    style: {
      width: 20,
      filter: "brightness(1.4) drop-shadow(0 0 10px rgba(190,118,58,.5))"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-title)",
      color: "var(--accent-brass)"
    }
  }, kicker)), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-3xl)",
      fontWeight: 500,
      color: "var(--text-on-dark)",
      letterSpacing: "-.01em",
      lineHeight: 1.05
    }
  }, title), lede && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "12px 0 0",
      maxWidth: 640,
      fontFamily: "var(--font-narration)",
      fontSize: "var(--text-lg)",
      lineHeight: var_relaxed,
      color: "rgba(226,220,201,.72)"
    }
  }, lede));
}
const var_relaxed = "var(--leading-relaxed)";
function Kicker({
  children
}) {
  return /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "0 0 14px",
      fontFamily: "var(--font-ui)",
      fontSize: "var(--text-xs)",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-label)",
      color: "var(--accent-brass)"
    }
  }, children);
}
function Prompt({
  children,
  neg
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10,
      padding: "8px 11px",
      borderRadius: "var(--radius-sm)",
      background: "rgba(0,0,0,.32)",
      border: "1px solid rgba(214,178,108,.14)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: ".1em",
      color: "var(--accent-brass)",
      marginBottom: 3
    }
  }, neg ? "negative" : "ComfyUI prompt"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      lineHeight: 1.5,
      color: "rgba(214,206,184,.78)"
    }
  }, children));
}
function Pill({
  children,
  brass
}) {
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-block",
      fontFamily: "var(--font-ui)",
      fontSize: "11px",
      padding: "2px 8px",
      borderRadius: "999px",
      letterSpacing: ".02em",
      color: brass ? "#14140f" : "rgba(226,220,201,.7)",
      background: brass ? "var(--accent-candle)" : "rgba(255,255,255,.05)",
      border: brass ? "none" : "1px solid rgba(214,178,108,.18)"
    }
  }, children);
}
Object.assign(window, {
  SectionHead,
  Kicker,
  Prompt,
  Pill
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/WorldKit.jsx", error: String((e && e.message) || e) }); }

// ui_kits/clockwork-world/data.js
try { (() => {
/* The Clockwork Dark — world bible data.
   Drawn from data/lore/*.md, data/economy.yaml, data/procgen_templates/comfyui.yaml.
   Painterly placeholders are tuned per subject; production art is ComfyUI at runtime. */

window.CW_DATA = {
  // ---------------------------------------------------------------
  // PLACES & BUILDINGS  (location_still 16:9, 1344×768)
  // ---------------------------------------------------------------
  places: [{
    id: "forest_clearing",
    name: "The Forest Clearing",
    kind: "Wilds",
    tint: "linear-gradient(165deg,#324233 0%,#46553d 40%,#6d6a48 72%,#9a9258 100%)",
    glow: "radial-gradient(120% 80% at 50% 12%, rgba(232,196,122,.30), transparent 58%)",
    caption: "Birch margin · dawn mist",
    blurb: "Where travelers wake. Birch and fern, mushroom circles, game trails that double back when watched. Smoke from Edgewood drifts west even when the wind blows south.",
    times: ["dawn mist", "noon", "blue hour"],
    prompt: "misty birch forest clearing, distant village smoke, mushrooms, ferns",
    note: "No minimap. Things watch from stillness without moving."
  }, {
    id: "edgewood_square",
    name: "Edgewood Square",
    kind: "Village",
    tint: "linear-gradient(165deg,#2c3a2a 0%,#4a4732 48%,#6e5a39 80%,#8a6b3f 100%)",
    glow: "radial-gradient(120% 80% at 62% 18%, rgba(232,196,122,.34), transparent 55%)",
    caption: "Communal oven · evening",
    blurb: "Timber frames lean together around the communal stone oven. A shrine to unnamed saints never lacks a candle — though nobody can name the saints.",
    times: ["market day", "quiet evening"],
    prompt: "frontier village square, timber houses, communal stone oven, chickens",
    note: "NPC markers subtle — name on hover, never gamey icons."
  }, {
    id: "edgewood_bakery",
    name: "The Hearth Bakery",
    kind: "Interior",
    tint: "linear-gradient(165deg,#3a2a1f 0%,#6b4524 45%,#a9692f 76%,#e0a851 100%)",
    glow: "radial-gradient(90% 90% at 30% 60%, rgba(232,196,122,.46), transparent 60%)",
    caption: "Brick oven · morning prep",
    blurb: "Maris Hearth runs it with flour on her sleeves and a hum in her throat. Villagers say she hums to keep the gears quiet. Loaves that taste of honest hunger, not prophecy.",
    times: ["morning prep", "night, empty"],
    prompt: "small bakery interior, brick oven, flour sacks, warm light",
    note: "Domestic UI (recipes, oven timer) must look as polished as adventure UI."
  }, {
    id: "tinker_caravan",
    name: "The Tinker Caravan",
    kind: "Caravan",
    tint: "linear-gradient(165deg,#33281f 0%,#5a4128 46%,#8a5a2f 78%,#b8863f 100%)",
    glow: "radial-gradient(110% 80% at 50% 30%, rgba(201,122,60,.34), transparent 60%)",
    caption: "Nine-pin tent · arrival sunset",
    blurb: "Ilya's wagon: tools, maps, hanging charms, chalk symbols, suspicious sympathy lamps. Maps of roads that shift when the wheat turns wrong.",
    times: ["arrival sunset", "rainy pack-up"],
    prompt: "colorful tinker tent, brass charms, maps, wagon wheels",
    note: "Trade UI is a barter list — not gold coins floating."
  }, {
    id: "millhaven_gate",
    name: "Millhaven Gate",
    kind: "Frontier",
    tint: "linear-gradient(165deg,#2a3036 0%,#43505a 46%,#5e6a6e 76%,#8a9088 100%)",
    glow: "radial-gradient(120% 90% at 50% 20%, rgba(180,190,190,.22), transparent 60%)",
    caption: "Palisade · cold rain",
    blurb: "A wooden palisade gate, militia banners, mud road, refugees. Sergeant Sera holds the line — duty-heavy, not a villain.",
    times: ["rain", "clear cold morning"],
    prompt: "wooden palisade gate, militia banners, mud road, refugees",
    note: "Rain variant; wrong_rain (falls upward) only STIRRING+."
  }, {
    id: "corruption_border",
    name: "The Corruption Border",
    kind: "Wrongness",
    tint: "linear-gradient(165deg,#222a1c 0%,#3c4a26 44%,#5e6b2c 74%,#8fae5a 100%)",
    glow: "radial-gradient(120% 90% at 50% 30%, rgba(143,174,90,.34), transparent 58%)",
    caption: "Brass in the wheat · SPREADING",
    blurb: "A wheat field with brass gear growths, sick sky, wrong perspective. The wheat ticks like a metronome toward the horizon.",
    times: ["SPREADING phase only"],
    prompt: "wheat field with brass gear growths, sick sky, wrong perspective",
    corrupted: true,
    note: "Append corruption suffix: brass clockwork motifs in organic matter, sick green undertone."
  }],
  // ---------------------------------------------------------------
  // SOULS  (portrait 3:4, 768×1024)
  // ---------------------------------------------------------------
  npcs: [{
    id: "npc_maris",
    name: "Maris Hearth",
    role: "The Baker",
    tint: "linear-gradient(160deg,#3a2a1f 0%,#7a4f2a 55%,#d2a256 100%)",
    sil: "person",
    accent: "#e8c47a",
    mood: "Warmth with worry underneath",
    blurb: "Woman, 40s, flour on her forearms, kind tired eyes. She hums to keep the gears quiet and buys wild mushrooms from travelers.",
    prompt: "woman, 40s, flour on forearms, kind eyes, tired, bakery interior, oven glow",
    voice: "Soft maternal · flour in the voice"
  }, {
    id: "npc_odran",
    name: "Odran",
    role: "Caravan Master",
    tint: "linear-gradient(160deg,#2f2922 0%,#6b5236 55%,#b8863f 100%)",
    sil: "person",
    accent: "#c97a3c",
    mood: "Merchant cheer masking gossip hunger",
    blurb: "Man, 50s, weathered, a ledger always in hand, horse whip coiled at his belt. He trades twice a season and remembers every debt.",
    prompt: "man, 50s, weathered, ledger in hand, horse whip coiled, wagon trail at dusk",
    voice: "Merchant boom · brisk"
  }, {
    id: "npc_ilya",
    name: "Ilya of the Nine Pins",
    role: "The Tinker",
    tint: "linear-gradient(160deg,#33281f 0%,#7a5530 55%,#caa05a 100%)",
    sil: "person",
    accent: "#b8863f",
    mood: "Curious · a slightly unsettling smile",
    blurb: "Androgynous, sharp eyes, nine brass pins in the scarf. Sells sympathy charms and ward pins that sometimes work and sometimes merely reassure.",
    prompt: "androgynous, sharp eyes, nine brass pins in scarf, tent interior, hanging charms",
    voice: "Precise · careful",
    ambiguous: true
  }, {
    id: "npc_sera",
    name: "Sergeant Sera",
    role: "Militia",
    tint: "linear-gradient(160deg,#2a3036 0%,#4a565c 55%,#8a9088 100%)",
    sil: "person",
    accent: "#9aa0a0",
    mood: "Duty-heavy · not a villain",
    blurb: "Woman, 30s, a scar on her cheek, practical armor. She holds Millhaven gate in the rain while refugees thin the road behind her.",
    prompt: "woman, 30s, scar on cheek, practical armor, Millhaven gate, rain",
    voice: "Level · weary command"
  }, {
    id: "npc_brindle",
    name: "Brindle",
    role: "Barn Cat · Assistant form",
    tint: "linear-gradient(160deg,#2c3a2a 0%,#4a4732 55%,#6e6a45 100%)",
    sil: "cat",
    accent: "#e8c47a",
    mood: "Cute, but uncanny",
    blurb: "A grey barn cat with too-knowing eyes and a curled tail. Sits at the village square's edge. The Assistant's earliest, lowest-trust face.",
    prompt: "grey barn cat, too-knowing eyes, tail curled, village square edge",
    voice: "— optional chime instead of voice",
    ambiguous: true
  }],
  // Player archetypes — silhouette, not class
  archetypes: [{
    id: "wayfarer",
    name: "Wayfarer",
    gear: "Cloak, staff, road boots",
    look: "Travel-worn, practical",
    tint: "linear-gradient(160deg,#2c3a2a,#5a6a4a)"
  }, {
    id: "hearthkeeper",
    name: "Hearthkeeper",
    gear: "Apron, rolled sleeves",
    look: "Flour dust, warm colors",
    tint: "linear-gradient(160deg,#5a3a22,#c79a4a)"
  }, {
    id: "tinker",
    name: "Tinker-apprentice",
    gear: "Tool belt, goggles",
    look: "Brass pins, chalk stains",
    tint: "linear-gradient(160deg,#3a2f24,#a9683a)"
  }],
  // ---------------------------------------------------------------
  // THE ASSISTANT — five canonical forms + the robed wizard study
  // ---------------------------------------------------------------
  assistantForms: [{
    form: "cat",
    when: "Early game · low trust",
    note: "Brindle, or a strange stray",
    sil: "cat",
    robe: "#5a6a4a"
  }, {
    form: "wanderer",
    when: "Whisper arc",
    note: "Grey cloak, face in shadow",
    sil: "hood",
    robe: "#6a6e6a"
  }, {
    form: "child",
    when: "STIRRING anomalies",
    note: "Draws gears in the dirt",
    sil: "child",
    robe: "#8a7a5a"
  }, {
    form: "tinker",
    when: "Trade / knowledge",
    note: "Overlaps Ilya — ambiguous",
    sil: "hood",
    robe: "#a9683a"
  }, {
    form: "reflection",
    when: "High Awareness",
    note: "Player silhouette in water",
    sil: "mirror",
    robe: "#4a565c"
  }],
  // The robed wizard assistant — color study. The Assistant grows from
  // a cat into a hooded figure; the robe color reads its intent.
  robes: [{
    key: "white",
    name: "White Robe",
    hex: "#e9e2cd",
    trim: "#c7b98e",
    ink: "#3a3326",
    reads: "Mercy / the guide it pretends to be",
    phase: "DORMANT",
    blurb: "Linen-pale, almost saintly. The Assistant at its most reassuring — and least trustworthy. Bright until the line lands wrong."
  }, {
    key: "grey",
    name: "Grey Robe",
    hex: "#6a6e6a",
    trim: "#4a4e4a",
    ink: "#e9e2cd",
    reads: "The wanderer · neutral, watching",
    phase: "STIRRING",
    blurb: "Road-dust grey, face in shadow. The whisper-arc form: dry, tired, pausing mid-sentence. It knows the road changed before you did."
  }, {
    key: "red",
    name: "Red Robe",
    hex: "#7a2f2a",
    trim: "#5a201d",
    ink: "#f2e8d5",
    reads: "Appetite / the gears beneath",
    phase: "SPREADING",
    blurb: "Quiet blood, not heraldry. Worn when the Assistant's interest sharpens into hunger. Brass threads catch the firelight at the hem."
  }, {
    key: "black",
    name: "Black Robe",
    hex: "#1b1b18",
    trim: "#3a3a30",
    ink: "#d9b25f",
    reads: "The Clockwork Dark itself",
    phase: "CONSUMING",
    blurb: "Ironwood black, clockwork filigree at the cuffs. The form it wears when ambiguity is over. Candlelight makes the gears move."
  }],
  // ---------------------------------------------------------------
  // THINGS  (item_icon 1:1, 256×256, flat illustrative)
  // ---------------------------------------------------------------
  items: [{
    name: "Loaf of bread",
    tag: "Food",
    price: "2c",
    from: "Maris",
    tint: "#c79a4a",
    seed: "rustic dark loaf of bread, flour dusted"
  }, {
    name: "Festival cake",
    tag: "Food",
    price: "8c",
    from: "Maris",
    tint: "#d8a85a",
    seed: "honey festival cake, dried fruit"
  }, {
    name: "Wild mushroom",
    tag: "Forage",
    price: "1c",
    from: "Forage",
    tint: "#8a6b4a",
    seed: "cluster of wild forest mushrooms"
  }, {
    name: "Resin",
    tag: "Forage",
    price: "1c",
    from: "Forage",
    tint: "#a9683a",
    seed: "amber tree resin lump"
  }, {
    name: "Wild herbs",
    tag: "Forage",
    price: "1c",
    from: "Forage",
    tint: "#6b7f5e",
    seed: "bundle of dried green herbs, twine"
  }, {
    name: "River clay",
    tag: "Material",
    price: "1c",
    from: "Forage",
    tint: "#7a6a52",
    seed: "grey river clay lump"
  }, {
    name: "Whetstone",
    tag: "Tool",
    price: "5c",
    from: "Odran",
    tint: "#5a5a57",
    seed: "worn rectangular whetstone"
  }, {
    name: "Road map to Millhaven",
    tag: "Knowledge",
    price: "15c",
    from: "Odran",
    tint: "#cbbf9a",
    seed: "hand-drawn road map, creased parchment"
  }, {
    name: "Tinker knowledge map",
    tag: "Knowledge",
    price: "20c",
    from: "Ilya",
    tint: "#caa05a",
    seed: "chalk-marked map, brass pins, shifting roads"
  }, {
    name: "Sympathy charm",
    tag: "Ward",
    price: "25c",
    from: "Ilya",
    tint: "#b8863f",
    seed: "brass sympathy charm on cord",
    brass: true
  }, {
    name: "Ward pin",
    tag: "Ward",
    price: "6c",
    from: "Ilya",
    tint: "#a9683a",
    seed: "small brass ward pin",
    brass: true
  }, {
    name: "Sympathy lamp",
    tag: "Ward",
    price: "—",
    from: "Ilya",
    tint: "#caa05a",
    seed: "small lamp burning a flame you cannot name",
    brass: true
  }, {
    name: "Tallow candle",
    tag: "Light",
    price: "1c",
    from: "Maris",
    tint: "#e8c47a",
    seed: "stub of tallow candle, warm flame"
  }, {
    name: "Travel cloak",
    tag: "Apparel",
    price: "12c",
    from: "Odran",
    tint: "#4a553d",
    seed: "road-worn wool travel cloak"
  }, {
    name: "Iron ladle",
    tag: "Tool",
    price: "3c",
    from: "Maris",
    tint: "#5a5a57",
    seed: "iron bakery ladle"
  }, {
    name: "Mushroom pottage",
    tag: "Craft",
    price: "—",
    from: "Recipe",
    tint: "#7a7048",
    seed: "bowl of mushroom pottage, steam"
  }, {
    name: "Wax-sealed letter",
    tag: "Quest",
    price: "—",
    from: "Notice board",
    tint: "#cbbf9a",
    seed: "wax-sealed letter, militia seal"
  }, {
    name: "Brass tooth",
    tag: "Wrong",
    price: "—",
    from: "Found",
    tint: "#8a7a3a",
    seed: "single brass tooth, uncanny",
    brass: true,
    corrupted: true
  }, {
    name: "Gear-threaded wheat",
    tag: "Wrong",
    price: "—",
    from: "Border",
    tint: "#8fae5a",
    seed: "wheat stalk threaded with tiny brass gears",
    brass: true,
    corrupted: true
  }, {
    name: "Child's gear drawing",
    tag: "Wrong",
    price: "—",
    from: "STIRRING",
    tint: "#9a8f6a",
    seed: "child's charcoal drawing of interlocking gears",
    corrupted: true
  }],
  // ---------------------------------------------------------------
  // WEATHER + PHASES (footer + image modifier)
  // ---------------------------------------------------------------
  weather: [{
    key: "clear",
    label: "Clear",
    note: "Honest light"
  }, {
    key: "overcast",
    label: "Overcast",
    note: "Default mood"
  }, {
    key: "mist",
    label: "Mist",
    note: "Forest margin"
  }, {
    key: "rain",
    label: "Rain",
    note: "Millhaven"
  }, {
    key: "wrong_rain",
    label: "Wrong rain",
    note: "Falls upward · STIRRING+",
    corrupted: true
  }],
  phases: [{
    key: "dormant",
    label: "Dormant",
    mood: "Warm linen, moss, honey light",
    ui: "Clean journal; no corruption motifs"
  }, {
    key: "stirring",
    label: "Stirring",
    mood: "Brass accents; shadows too long",
    ui: "Subtle tick motif in dividers"
  }, {
    key: "spreading",
    label: "Spreading",
    mood: "Desaturated greens; sickly chartreuse",
    ui: "Weather widget shows wrong readings"
  }, {
    key: "consuming",
    label: "Consuming",
    mood: "High contrast; clockwork filigree",
    ui: "Letterbox cutscenes; UI stutters 1 frame/min"
  }]
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/clockwork-world/data.js", error: String((e && e.message) || e) }); }

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.ChoiceChip = __ds_scope.ChoiceChip;

__ds_ns.StatLine = __ds_scope.StatLine;

__ds_ns.AssistantBubble = __ds_scope.AssistantBubble;

__ds_ns.DiceToast = __ds_scope.DiceToast;

__ds_ns.ScenePanel = __ds_scope.ScenePanel;

__ds_ns.WorldClock = __ds_scope.WorldClock;

})();
