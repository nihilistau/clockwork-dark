/**
 * Matchstick (spec §6, §18.2): the swipe deck, the matches waiting for a
 * first message, and the chats. The deck is the payload's
 * `deck.matchstick` (the deck is keyed by app, T7).
 */
import React, { useState } from "react";

import CardStack from "./CardStack.jsx";
import ChatList, { threadsOf } from "./ChatList.jsx";
import Tabs, { panelProps } from "./Tabs.jsx";

export const APP = "matchstick";

export default function Matchstick({ phone, act, pending = null, blocked = false, onOpenThread = () => {} }) {
  const [tab, setTab] = useState("deck");
  const deck = (phone.deck || {})[APP] || null;
  const rows = threadsOf(phone, APP);
  const matches = rows.filter((t) => !t.last);
  const chats = rows.filter((t) => t.last);
  const unread = chats.reduce((n, t) => n + (Number(t.unread) || 0), 0);
  const waiting = Boolean(pending && pending.action === "swipe");
  return (
    <section className="rr-app rr-app--matchstick" aria-label="Matchstick">
      <h2 className="rr-app__title" tabIndex={-1}>Matchstick</h2>
      <Tabs
        idBase="rr-matchstick"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "deck", label: "Discover" },
          { id: "matches", label: "Matches", count: matches.length },
          { id: "chats", label: "Chats", count: unread },
        ]}
      />
      <div className="rr-app__body" {...panelProps("rr-matchstick", tab)}>
        {tab === "deck" && (
          <CardStack
            deck={deck}
            waiting={waiting}
            blocked={blocked}
            onSwipe={(pid, dir) => act({ action: "swipe", target: pid, args: { dir }, text: "" })}
          />
        )}
        {tab === "matches" && (
          <ChatList rows={matches} now={phone.now} onOpenThread={onOpenThread} empty="No new matches yet. Keep swiping." />
        )}
        {tab === "chats" && <ChatList rows={chats} now={phone.now} onOpenThread={onOpenThread} empty="No chats yet." />}
      </div>
    </section>
  );
}
