/**
 * An app's conversations (spec §18.2's "matches" and "chats"): each thread
 * row with its face, name, last line, time and unread count. A row with no
 * message yet is a new match.
 */
import React from "react";

import Avatar from "../phone/Avatar.jsx";
import { stampOf } from "../phone/format.js";

export function preview(row) {
  const last = row.last;
  if (row.typing) return "typing…";
  if (!last) return "You matched. Say hello.";
  if (last.pending) return "…";
  const mine = last.from === "player" ? "You: " : "";
  return `${mine}${last.preview || ""}`;
}

export default function ChatList({ rows, now, onOpenThread, empty, current = "" }) {
  if (!rows.length) return <p className="rr-empty">{empty}</p>;
  return (
    <ul className="rr-chats">
      {rows.map((row) => (
        <li key={row.thread_id}>
          <button
            type="button"
            className={`rr-chat${row.thread_id === current ? " is-current" : ""}`}
            aria-current={row.thread_id === current ? "true" : undefined}
            data-testid={`chat-${row.thread_id}`}
            onClick={() => onOpenThread(row.thread_id)}
          >
            <Avatar pid={row.pid} name={row.name} url={row.avatar_url} />
            <span className="rr-chat__body">
              <span className="rr-chat__name">{row.name}</span>
              <span className="rr-chat__last">{preview(row)}</span>
            </span>
            <span className="rr-chat__side">
              {row.last && <span className="rr-chat__at">{stampOf(row.last.at, now)}</span>}
              {row.unread > 0 && <span className="rr-chat__unread">{row.unread}</span>}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** The threads of one app. */
export function threadsOf(phone, app) {
  return (phone.threads || []).filter((t) => t.app === app);
}
