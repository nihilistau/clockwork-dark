/**
 * Texts and Natter (spec §6): the conversations moved off the dating apps
 * once numbers are swapped. Their threads open like any other.
 */
import React from "react";

import ChatList, { threadsOf } from "./ChatList.jsx";

export default function Messenger({ phone, app, label, onOpenThread }) {
  return (
    <section className={`rr-app rr-app--${app}`} aria-label={label}>
      <h2 className="rr-app__title" tabIndex={-1}>{label}</h2>
      <div className="rr-app__body">
        <ChatList
          rows={threadsOf(phone, app)}
          now={phone.now}
          onOpenThread={onOpenThread}
          empty="No conversations here yet. Swap numbers with someone first."
        />
      </div>
    </section>
  );
}

/** An app the phone has no screen for (an app kind apps.yaml adds that this client does not draw). */
export function NotYet({ label }) {
  return (
    <section className="rr-app" aria-label={label}>
      <h2 className="rr-app__title" tabIndex={-1}>{label}</h2>
      <div className="rr-app__body">
        <p className="rr-empty">{label} isn't on this phone yet.</p>
      </div>
    </section>
  );
}
