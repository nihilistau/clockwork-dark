/**
 * An app's tab row: a tablist (one button per tab, with an optional count)
 * wired to its panel (`panelProps(idBase, value)` on the app's body), the
 * ←/→ keys moving between tabs (and taken, so the deck behind them never
 * reads them as a swipe), Home and End to the ends.
 */
import React, { useRef } from "react";

export const tabId = (idBase, id) => `${idBase}-tab-${id}`;

/** The props for the panel a tab row controls. */
export function panelProps(idBase, value) {
  return { role: "tabpanel", id: `${idBase}-panel`, "aria-labelledby": tabId(idBase, value) };
}

export default function Tabs({ tabs, value, onChange, idBase }) {
  const row = useRef(null);
  const onKeyDown = (event) => {
    const at = tabs.findIndex((t) => t.id === value);
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    const next = tabs[(to + tabs.length) % tabs.length];
    onChange(next.id);
    row.current?.ownerDocument.getElementById(tabId(idBase, next.id))?.focus();
  };
  return (
    <div className="rr-tabs" role="tablist" ref={row} onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button
          key={t.id}
          id={tabId(idBase, t.id)}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          aria-controls={`${idBase}-panel`}
          tabIndex={value === t.id ? 0 : -1}
          className={`rr-tab${value === t.id ? " is-on" : ""}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
          {t.count ? <span className="rr-tab__count">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
