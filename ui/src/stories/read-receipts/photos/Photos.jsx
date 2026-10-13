/**
 * The Photos app (spec §18.2): your camera roll -- the photos on your
 * profile (`player.camera_roll`), drawn as their tiles -- and what people
 * have sent you (the payload's `gallery`: each photo or video once its
 * message has arrived, its file only through the media route, `mediaSrc`).
 * A received one opens the chat it came in.
 */
import React, { useState } from "react";

import Tabs, { panelProps } from "../apps/Tabs.jsx";
import { stampOf, tileStyle } from "../phone/format.js";
import PhotoTile from "../thread/PhotoTile.jsx";
import VideoTile from "../thread/VideoTile.jsx";

const ID = "rr-photos";

export default function Photos({ phone, onOpenThread }) {
  const roll = (phone.player && phone.player.camera_roll) || [];
  const got = phone.gallery || [];
  const [tab, setTab] = useState("roll");
  const tabs = [
    { id: "roll", label: "Camera roll" },
    { id: "received", label: "Received" },
  ];
  return (
    <section className="rr-app rr-app--photos" aria-label="Photos">
      <h2 className="rr-app__title" tabIndex={-1}>Photos</h2>
      <Tabs tabs={tabs} value={tab} onChange={setTab} idBase={ID} />
      <div className="rr-app__body" {...panelProps(ID, tab)}>
        {tab === "roll" ? (
          roll.length === 0 ? (
            <p className="rr-empty">No photos yet.</p>
          ) : (
            <ul className="rr-gallery">
              {roll.map((p, i) => (
                <li key={p.id} className="rr-gallery__item">
                  <figure className="rr-tile rr-tile--photo rr-tile--drawn" style={tileStyle("player", i)} data-testid={`roll-${p.id}`}>
                    <span className="rr-tile__glyph" aria-hidden="true">▣</span>
                    <figcaption className="rr-tile__caption">{p.label}</figcaption>
                  </figure>
                </li>
              ))}
            </ul>
          )
        ) : got.length === 0 ? (
          <p className="rr-empty">Nobody has sent you a photo yet.</p>
        ) : (
          <ul className="rr-gallery">
            {got.map((m) => (
              <li key={m.mid} className="rr-gallery__item">
                {m.kind === "video" ? <VideoTile media={m} /> : <PhotoTile media={m} />}
                <button type="button" className="rr-gallery__from" onClick={() => onOpenThread(m.thread_id)}>
                  {m.name}
                  {m.at != null ? ` · ${stampOf(m.at, phone.now)}` : ""}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
