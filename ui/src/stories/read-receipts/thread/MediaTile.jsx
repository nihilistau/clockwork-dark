/**
 * The tile for a message's media (spec §18.2): photo, voice note or video,
 * by the media row's kind (else the message's). A message whose media row
 * the payload lacks still draws its stand-in, from what the message holds.
 */
import React from "react";

import PhotoTile from "./PhotoTile.jsx";
import VideoTile from "./VideoTile.jsx";
import VoiceTile from "./VoiceTile.jsx";

export const MEDIA_KINDS = ["photo", "voice", "video"];

export default function MediaTile({ message }) {
  const row = message.media || {};
  const kind = MEDIA_KINDS.includes(row.kind) ? row.kind : message.kind;
  const media = {
    mid: row.mid || message.media_id || message.id,
    kind,
    status: row.status || "fallback",
    url: row.url || "",
    poster_url: row.poster_url || "",
    caption: row.caption || "",
    transcript: row.transcript || "",
    seconds: row.seconds || 0,
  };
  if (kind === "voice") return <VoiceTile media={media} transcript={message.transcript || ""} />;
  if (kind === "video") return <VideoTile media={media} />;
  if (kind === "photo") return <PhotoTile media={media} />;
  return null;
}
