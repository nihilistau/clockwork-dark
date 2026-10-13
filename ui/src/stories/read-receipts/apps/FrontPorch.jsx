/**
 * Front Porch (spec §6, §18.2): browse one profile at a time -- its photos
 * and its prompts -- and like one of them with a comment (`like {on,
 * comment}`), or pass; see who liked you and like them back (`like_back`);
 * the matches and the chats. The deck is the payload's `deck.front_porch`
 * (keyed by app, T7); "Likes you" is `likes_you`, this app's rows.
 */
import React, { useState } from "react";

import ChatList, { threadsOf } from "./ChatList.jsx";
import LikeSheet from "./LikeSheet.jsx";
import { Facts, Hobbies, PhotoTile } from "./ProfileCard.jsx";
import Tabs, { panelProps } from "./Tabs.jsx";

export const APP = "front_porch";

function LikeButton({ label, onClick, disabled }) {
  return (
    <button type="button" className="rr-heart" aria-label={label} disabled={disabled} onClick={onClick}>
      <span aria-hidden="true">♥</span>
    </button>
  );
}

function Browse({ deck, pending, onLike, onPass }) {
  const card = deck && deck.card;
  if (!card) return <p className="rr-empty">You've seen everyone for now. Check back tomorrow.</p>;
  const likes = Number(deck.likes_left) || 0;
  const waiting = Boolean(pending && (pending.action === "like" || pending.action === "pass") && pending.target === card.pid);
  const photos = card.photos || [];
  const prompts = card.prompts || [];
  // Photos and prompts interleaved, as a browse profile reads.
  const items = [];
  const longest = Math.max(photos.length, prompts.length);
  for (let i = 0; i < longest; i += 1) {
    if (photos[i]) items.push({ kind: "photo", index: i, row: photos[i] });
    if (prompts[i]) items.push({ kind: "prompt", index: i, row: prompts[i] });
  }
  return (
    <div className="rr-browse">
      <article className="rr-browse__card" data-testid={`browse-${card.pid}`} aria-label={`${card.name}, profile`}>
        <Facts card={card} />
        {card.bio && <p className="rr-card__bio">{card.bio}</p>}
        {items.map((item) =>
          item.kind === "photo" ? (
            <div key={item.row.id} className="rr-browse__item">
              <PhotoTile pid={card.pid} photo={item.row} index={item.index}>
                {likes > 0 && (
                  <LikeButton
                    label={`Like photo: ${item.row.caption}`}
                    disabled={waiting}
                    onClick={() => onLike(card, item.row.id, `Their photo: ${item.row.caption}`)}
                  />
                )}
              </PhotoTile>
            </div>
          ) : (
            <div key={item.row.id} className="rr-browse__item rr-prompt">
              <p className="rr-prompt__q">{item.row.q}</p>
              <p className="rr-prompt__a">{item.row.a}</p>
              {likes > 0 && (
                <LikeButton
                  label={`Like answer: ${item.row.q}`}
                  disabled={waiting}
                  onClick={() => onLike(card, item.row.id, `${item.row.q}: ${item.row.a}`)}
                />
              )}
            </div>
          )
        )}
        <Hobbies hobbies={card.hobbies} />
      </article>
      <div className="rr-deck__bar">
        <p className="rr-deck__left">{likes > 0 ? `${likes} likes left today` : "No likes left today"}</p>
        <div className="rr-deck__buttons">
          <button type="button" className="rr-round rr-round--pass" aria-label="Pass" disabled={waiting} onClick={() => onPass(card.pid)}>
            <span aria-hidden="true">✕</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function LikesYou({ rows, pending, onLikeBack, onPass }) {
  if (!rows.length) return <p className="rr-empty">No new likes yet.</p>;
  return (
    <ul className="rr-likes">
      {rows.map((row) => {
        const waiting = Boolean(pending && pending.target === row.pid);
        return (
          <li key={row.pid} className="rr-likes__row" data-testid={`likes-you-${row.pid}`}>
            <span className="rr-likes__who">
              {row.name}
              {row.age ? `, ${row.age}` : ""}
            </span>
            {row.comment && <span className="rr-likes__comment">“{row.comment}”</span>}
            <span className="rr-likes__actions">
              <button type="button" className="rr-btn rr-btn--quiet" disabled={waiting} onClick={() => onPass(row.pid)}>
                Pass
              </button>
              <button type="button" className="rr-btn" disabled={waiting} onClick={() => onLikeBack(row)}>
                Like back
              </button>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export default function FrontPorch({ phone, act, pending = null, notSent = null, onRetry = null, onClearNotSent = () => {}, onOpenThread = () => {} }) {
  const [tab, setTab] = useState("browse");
  const [sheet, setSheet] = useState(null);
  const deck = (phone.deck || {})[APP] || null;
  const likesYou = (phone.likes_you || []).filter((row) => row.app === APP);
  const rows = threadsOf(phone, APP);
  const matches = rows.filter((t) => !t.last);
  const chats = rows.filter((t) => t.last);

  // A like that never went comes back with its comment (spec §18.2).
  const lost = notSent && (notSent.action === "like" || notSent.action === "like_back") ? notSent : null;
  const shown = sheet || (lost ? { lost } : null);

  const send = (comment) => {
    const base = sheet || {};
    const args = base.action === "like" ? { on: base.on } : {};
    if (comment) args.comment = comment;
    act({ action: base.action, target: base.pid, args, text: "" });
    setSheet(null);
  };
  const retry = (comment) => {
    const args = { ...(lost.args || {}) };
    if (comment) args.comment = comment;
    else delete args.comment;
    onClearNotSent();
    if (onRetry) onRetry({ ...lost, args });
    else act({ ...lost, args });
  };

  return (
    <section className="rr-app rr-app--porch" aria-label="Front Porch">
      <h2 className="rr-app__title" tabIndex={-1}>Front Porch</h2>
      <Tabs
        idBase="rr-porch"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "browse", label: "Browse" },
          { id: "likes", label: "Likes you", count: likesYou.length },
          { id: "matches", label: "Matches", count: matches.length },
          { id: "chats", label: "Chats" },
        ]}
      />
      <div className="rr-app__body" {...panelProps("rr-porch", tab)}>
        {tab === "browse" && (
          <Browse
            deck={deck}
            pending={pending}
            onLike={(card, on, what) => setSheet({ action: "like", pid: card.pid, on, title: `Like ${card.name}`, what })}
            onPass={(pid) => act({ action: "pass", target: pid, args: {}, text: "" })}
          />
        )}
        {tab === "likes" && (
          <LikesYou
            rows={likesYou}
            pending={pending}
            onLikeBack={(row) => setSheet({ action: "like_back", pid: row.pid, title: `Like ${row.name} back`, what: row.comment ? `“${row.comment}”` : "" })}
            onPass={(pid) => act({ action: "pass", target: pid, args: {}, text: "" })}
          />
        )}
        {tab === "matches" && (
          <ChatList rows={matches} now={phone.now} onOpenThread={onOpenThread} empty="No new matches yet." />
        )}
        {tab === "chats" && <ChatList rows={chats} now={phone.now} onOpenThread={onOpenThread} empty="No chats yet." />}
      </div>
      {shown && shown.lost && (
        <LikeSheet
          title="Your like"
          initial={String(shown.lost.args?.comment || "")}
          notSent
          onSend={retry}
          onRetry={retry}
          onCancel={onClearNotSent}
          sendLabel="Send again"
        />
      )}
      {shown && !shown.lost && (
        <LikeSheet
          title={shown.title}
          what={shown.what}
          onSend={send}
          onCancel={() => setSheet(null)}
          sendLabel={shown.action === "like_back" ? "Like back" : "Send like"}
        />
      )}
    </section>
  );
}
