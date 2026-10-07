/**
 * The shell every engine panel wears (spec §2.5): a section labelled by its
 * own h2 (the play screen's h1 is the place name, so a panel is the next
 * level down -- F11), optionally a disclosure. The h2 takes focus
 * (`tabIndex={-1}`) so a header chip can send the reader to it. Nothing here
 * is a live region: the log's own announcer speaks the turn.
 */
import React, { useEffect, useState } from "react";

/** The event a header chip sends to open a collapsed panel: `detail` is the panel id. */
export const OPEN_EVENT = "panel:open";

export default function Panel({ id, title, className = "", collapsible = false, defaultOpen = true, summary = null, children }) {
  const [open, setOpen] = useState(defaultOpen);
  const headingId = `panel-${id}-title`;
  const bodyId = `panel-${id}-body`;
  const shown = !collapsible || open;
  // A chip's press opens the panel it names, collapsed or not (spec §4.1).
  useEffect(() => {
    if (!collapsible) return undefined;
    const on = (event) => {
      if (event.detail === id) setOpen(true);
    };
    window.addEventListener(OPEN_EVENT, on);
    return () => window.removeEventListener(OPEN_EVENT, on);
  }, [collapsible, id]);
  return (
    <section className={`panel panel--${id} ${className}`.trim()} aria-labelledby={headingId}>
      <h2 className="panel__title" id={headingId} tabIndex={-1}>
        {collapsible ? (
          <button
            type="button"
            className="panel__toggle"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((value) => !value)}
          >
            <span className="panel__label">{title}</span>
            {summary && <span className="panel__summary">{summary}</span>}
            <span className="panel__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
          </button>
        ) : (
          <span className="panel__label">{title}</span>
        )}
      </h2>
      <div className="panel__body" id={bodyId} hidden={!shown}>
        {children}
      </div>
    </section>
  );
}
