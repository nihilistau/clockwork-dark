/**
 * The Contacts app (spec §6): everyone you have a conversation with, once
 * each, by name (the payload's `contacts`), with where things stand in
 * words. A row opens their contact card.
 */
import React from "react";

import Avatar from "../phone/Avatar.jsx";

export default function Contacts({ phone, onOpenContact }) {
  const rows = phone.contacts || [];
  return (
    <section className="rr-app rr-app--contacts" aria-label="Contacts">
      <h2 className="rr-app__title" tabIndex={-1}>Contacts</h2>
      <div className="rr-app__body">
        {rows.length === 0 ? (
          <p className="rr-empty">No contacts yet. Match with someone first.</p>
        ) : (
          <ul className="rr-chats">
            {rows.map((c) => (
              <li key={c.pid}>
                <button type="button" className="rr-chat" data-testid={`contact-row-${c.pid}`} onClick={() => onOpenContact(c.pid)}>
                  <Avatar pid={c.pid} name={c.name} url={c.avatar_url} />
                  <span className="rr-chat__body">
                    <span className="rr-chat__name">{c.name}</span>
                    <span className="rr-chat__last">{c.stage_words || (c.open ? "" : "No longer talking")}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
