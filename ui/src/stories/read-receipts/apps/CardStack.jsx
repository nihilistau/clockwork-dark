/**
 * Matchstick's swipe deck (spec §18.2): the top card, dragged or pressed.
 * Right is like, left is pass, up is a super like (only while one is left).
 * The ←/→/↑ keys do the same -- but never while the player is typing, while
 * core's menu, settings or an overlay is up (`blocked`), or for a key aimed
 * at anything outside the phone's screen (a dialog's button): a swipe spends
 * a like or passes a profile for good.
 *
 * Every direction is one `swipe {dir}` on the top card's `pid` (spec §7.1);
 * the engine decides what it means. While an answer is awaited (`waiting`),
 * nothing more is sent: the next card is the server's to deal.
 */
import React, { useEffect, useRef, useState } from "react";

import { playSound } from "@core/sound/index.js";

import ProfileCard from "./ProfileCard.jsx";

/** How far a drag must travel, in px, to count as a swipe. */
export const SWIPE_PX = 80;

export default function CardStack({ deck, onSwipe, waiting = false, keys = true, blocked = false }) {
  const card = deck && deck.card;
  const supers = Number(deck?.supers_left) || 0;
  const likes = Number(deck?.likes_left) || 0;
  const drag = useRef(null);
  const [dx, setDx] = useState(0);

  const swipe = (dir) => {
    if (!card || waiting) return;
    if (dir === "super" && supers <= 0) return;
    if (dir !== "pass" && likes <= 0) return;
    onSwipe(card.pid, dir);
    playSound("phone.swipe");
  };
  const swipeRef = useRef(swipe);
  swipeRef.current = swipe;
  const blockedRef = useRef(blocked);
  blockedRef.current = blocked;

  useEffect(() => {
    if (!keys) return undefined;
    function onKey(event) {
      if (event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented || blockedRef.current) return;
      const target = event.target;
      // Nothing focused (the body, the window) or something on the phone's screen; never a dialog.
      const free = !target || typeof target.closest !== "function" || target === target.ownerDocument?.body;
      if (!free && (!target.closest(".rr-screen") || target.closest('[role="dialog"]'))) return;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) return;
      const dir = { ArrowRight: "like", ArrowLeft: "pass", ArrowUp: "super" }[event.key];
      if (!dir) return;
      event.preventDefault();
      swipeRef.current(dir);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keys]);

  if (!card) {
    return (
      <div className="rr-deck rr-deck--empty">
        <p className="rr-empty">No one new nearby right now. Check back later.</p>
      </div>
    );
  }

  const down = (event) => {
    drag.current = { x: event.clientX || 0, y: event.clientY || 0 };
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      /* a synthetic pointer has no capture to take */
    }
  };
  const move = (event) => {
    if (!drag.current) return;
    setDx((event.clientX || 0) - drag.current.x);
  };
  const up = (event) => {
    if (!drag.current) return;
    const ddx = (event.clientX || 0) - drag.current.x;
    const ddy = (event.clientY || 0) - drag.current.y;
    drag.current = null;
    setDx(0);
    if (ddx >= SWIPE_PX) swipe("like");
    else if (ddx <= -SWIPE_PX) swipe("pass");
    else if (ddy <= -SWIPE_PX) swipe("super");
  };
  const cancel = () => {
    drag.current = null;
    setDx(0);
  };

  const tilt = Math.max(-12, Math.min(12, dx / 12));
  const lean = dx > SWIPE_PX / 2 ? " is-liking" : dx < -SWIPE_PX / 2 ? " is-passing" : "";
  return (
    <div className="rr-deck">
      <div
        className={`rr-deck__card${lean}`}
        data-testid={`card-${card.pid}`}
        style={dx ? { transform: `translateX(${dx}px) rotate(${tilt}deg)` } : undefined}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={cancel}
      >
        <ProfileCard key={card.pid} card={card} />
      </div>
      <div className="rr-deck__bar">
        <p className="rr-deck__left">{likes > 0 ? `${likes} likes left today` : "No likes left today"}</p>
        <div className="rr-deck__buttons">
          <button type="button" className="rr-round rr-round--pass" data-sound="none" aria-label="Pass" disabled={waiting} onClick={() => swipe("pass")}>
            <span aria-hidden="true">✕</span>
          </button>
          {supers > 0 && likes > 0 && (
            <button
              type="button"
              className="rr-round rr-round--super"
              data-sound="none"
              aria-label="Super like"
              disabled={waiting}
              onClick={() => swipe("super")}
            >
              <span aria-hidden="true">★</span>
            </button>
          )}
          {likes > 0 && (
            <button type="button" className="rr-round rr-round--like" data-sound="none" aria-label="Like" disabled={waiting} onClick={() => swipe("like")}>
              <span aria-hidden="true">♥</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
