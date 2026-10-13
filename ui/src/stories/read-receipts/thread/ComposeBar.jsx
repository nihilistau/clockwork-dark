/**
 * The thread's compose bar (spec §18.2, §13.7): text up to 600 characters
 * with a live count, and only the attachments the thread's app allows
 * (`apps[].capabilities` in the payload):
 *
 * - photo: one of the camera roll (`player.camera_roll`, `photo_id`) or a
 *   `player_subjects` row that may be a photo (`subject`); the text is its caption;
 * - video: a `player_subjects` row that may be a video (`subject`);
 * - voice: a voice note, its transcript held to the mic (`MicButton`,
 *   `POST /api/voice/transcribe`) or typed -- sent as `send {kind: voice,
 *   audio_transcript}`, its audio never kept.
 *
 * And "Ask": their number, a photo, a voice note, a video, to meet up or to
 * be exclusive (`ask {what}`); the engine refuses one it will not take, in
 * words (rule 1), and the menu offers no media its app cannot carry. "Their
 * number" is greyed until the thread row's `asks` (the engine's
 * `messaging.ready_asks`: its gate holds) lists it -- never a client guess.
 *
 * A send that never went (`lost`, spec §18.2) comes back WHOLE -- its text
 * and its attachment -- with "Not sent — tap to retry".
 *
 * Focus never falls to the page (T28 review I1): a pick, the chip's removal
 * and a send or retry (whose button may unmount) put it in the text box; an
 * ask back on the Ask toggle, whose menu just closed.
 */
import React, { useEffect, useRef, useState } from "react";

import MicButton from "../../../core/parts/MicButton.jsx";
import { ASK_MENU } from "./media.js";

/** The catalogue's cap on a text (`social.max_text_chars`, spec §7.1). */
export const TEXT_MAX = 600;

/** The attachment a lost send carried, put back as the bar holds it. */
function attachmentOf(intent, player) {
  const args = (intent && intent.args) || {};
  if (args.kind === "photo" || args.kind === "video") {
    const roll = (player.camera_roll || []).find((p) => p.id === args.photo_id);
    const subject = (player.subjects || []).find((s) => s.id === args.subject);
    const label = (roll || subject || {}).label || "";
    return args.photo_id ? { kind: "photo", photo_id: args.photo_id, label } : { kind: args.kind, subject: args.subject || "", label };
  }
  return null;
}

export default function ComposeBar({
  threadId,
  app,
  player = {},
  sessionId = "",
  act,
  sending = false,
  lost = null,
  onSend,
  inputRef = null,
  readyAsks = null,
}) {
  const caps = (app && Array.isArray(app.capabilities) ? app.capabilities : ["text"]).map(String);
  const dating = app && app.kind === "dating";
  const [text, setText] = useState("");
  const [voice, setVoice] = useState(false);
  const [attachment, setAttachment] = useState(null);
  const [menu, setMenu] = useState(null); // "photo" | "video" | "ask" | null
  const ownInput = useRef(null);
  const box = inputRef || ownInput;
  const askToggle = useRef(null);
  const focusBox = () => box.current?.focus?.();

  // A send that never went puts its words and its attachment back (spec §18.2).
  useEffect(() => {
    if (!lost) return;
    const args = lost.args || {};
    setVoice(args.kind === "voice");
    setText(args.kind === "voice" ? String(args.audio_transcript || "") : String(lost.text || ""));
    setAttachment(attachmentOf(lost, player));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lost]);

  const tooLong = text.length > TEXT_MAX;
  const words = text.trim();
  const ready = !tooLong && !sending && (attachment ? true : Boolean(words));

  const send = () => {
    if (!ready) return;
    let intent;
    if (voice && !attachment) {
      intent = { action: "send", target: threadId, args: { kind: "voice", audio_transcript: words }, text: "" };
    } else if (attachment) {
      const args = attachment.photo_id
        ? { kind: "photo", photo_id: attachment.photo_id }
        : { kind: attachment.kind, subject: attachment.subject };
      intent = { action: "send", target: threadId, args, text: words };
    } else {
      intent = { action: "send", target: threadId, args: { kind: "text" }, text: words };
    }
    setText("");
    setAttachment(null);
    setVoice(false);
    setMenu(null);
    onSend(intent);
    focusBox();
  };

  const pick = (row) => {
    setAttachment(row);
    setVoice(false);
    setMenu(null);
    focusBox();
  };
  const ask = (what) => {
    setMenu(null);
    act({ action: "ask", target: threadId, args: { what }, text: "" });
    askToggle.current?.focus?.();
  };

  const photos = [
    ...(player.camera_roll || []).map((p) => ({ kind: "photo", photo_id: p.id, label: p.label, key: `roll-${p.id}` })),
    ...(player.subjects || [])
      .filter((s) => (s.kinds || []).includes("photo"))
      .map((s) => ({ kind: "photo", subject: s.id, label: s.label, key: `subject-${s.id}` })),
  ];
  const videos = (player.subjects || [])
    .filter((s) => (s.kinds || []).includes("video"))
    .map((s) => ({ kind: "video", subject: s.id, label: s.label, key: `subject-${s.id}` }));
  const asks = ASK_MENU.filter(([what]) => (what === "number" ? dating : ["photo", "voice", "video"].includes(what) ? caps.includes(what) : true));

  // A row with no `asks` (an older payload) greys nothing.
  const numberOpen = !Array.isArray(readyAsks) || readyAsks.includes("number");

  const toggle = (name) => setMenu((m) => (m === name ? null : name));

  return (
    <form
      className="rr-compose"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      {lost && (
        <button type="button" className="rr-notsent" onClick={send}>
          Not sent — tap to retry
        </button>
      )}
      {menu && (
        <div className="rr-compose__menu" role="group" aria-label={menu === "ask" ? "Ask for" : menu === "photo" ? "Choose a photo" : "Choose a video"}>
          {(menu === "photo" ? photos : menu === "video" ? videos : []).map((row) => (
            <button key={row.key} type="button" className="rr-pick" onClick={() => pick(row)}>
              {row.label}
            </button>
          ))}
          {menu === "ask" &&
            asks.map(([what, label]) => (
              <button
                key={what}
                type="button"
                className="rr-pick"
                disabled={what === "number" && !numberOpen}
                title={what === "number" && !numberOpen ? "Not yet" : undefined}
                onClick={() => ask(what)}
              >
                {label}
              </button>
            ))}
          {menu !== "ask" && (menu === "photo" ? photos : videos).length === 0 && <span className="rr-card__sub">Nothing to send yet.</span>}
        </div>
      )}
      {attachment && (
        <p className="rr-compose__chip" data-testid="compose-attachment">
          <span>
            {attachment.kind === "video" ? "Video" : "Photo"}: {attachment.label}
          </span>
          <button type="button" className="rr-compose__unchip" aria-label="Remove the attachment" onClick={() => {
              setAttachment(null);
              focusBox();
            }}>
            <span aria-hidden="true">×</span>
          </button>
        </p>
      )}
      {voice && (
        <div className="rr-compose__voice">
          <MicButton
            sessionId={sessionId}
            disabled={sending}
            onTranscript={(said) => {
              setText(said);
              setVoice(true);
            }}
          />
        </div>
      )}
      <div className="rr-compose__row">
        <span className="rr-compose__tools">
          {caps.includes("photo") && (
            <button type="button" className="rr-tool" aria-label="Attach a photo" aria-expanded={menu === "photo"} onClick={() => toggle("photo")}>
              <span aria-hidden="true">▣</span>
            </button>
          )}
          {caps.includes("video") && (
            <button type="button" className="rr-tool" aria-label="Attach a video" aria-expanded={menu === "video"} onClick={() => toggle("video")}>
              <span aria-hidden="true">▶</span>
            </button>
          )}
          {caps.includes("voice") && (
            <button
              type="button"
              className={`rr-tool${voice ? " is-on" : ""}`}
              aria-label="Voice note"
              aria-pressed={voice}
              onClick={() => {
                setVoice((v) => !v);
                setAttachment(null);
                setMenu(null);
              }}
            >
              <span aria-hidden="true">●</span>
            </button>
          )}
          <button ref={askToggle} type="button" className="rr-tool rr-tool--word" aria-expanded={menu === "ask"} onClick={() => toggle("ask")}>
            Ask
          </button>
        </span>
        <textarea
          ref={box}
          className="rr-input rr-compose__input"
          rows={1}
          placeholder={voice ? "Hold to speak, or type what you said" : attachment ? "Add a caption" : "Message"}
          aria-label={voice ? "Voice note transcript" : "Message"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" className="rr-btn rr-compose__send" disabled={!ready}>
          Send
        </button>
      </div>
      {text.length > 0 && (
        // Spoken only near the cap (the last 100), never on every keystroke (review M5).
        <p className={`rr-count${tooLong ? " is-over" : ""}`} data-testid="compose-count" aria-live={text.length > TEXT_MAX - 100 ? "polite" : "off"}>
          {text.length}/{TEXT_MAX}
        </p>
      )}
    </form>
  );
}
