/**
 * A video message (spec §13.8, §18.2): a player with its poster once the
 * clip is ready, else the poster frame (or a procedural tile when there is
 * none) and the caption. With ComfyUI off, the tile is the expected path.
 */
import React from "react";

import { tileStyle } from "../phone/format.js";
import { mediaSrc } from "./media.js";

export default function VideoTile({ media }) {
  const caption = media.caption || "";
  const src = media.status === "ready" ? mediaSrc(media.url) : "";
  const poster = mediaSrc(media.poster_url);
  if (src) {
    return (
      <figure className="rr-tile rr-tile--video" data-testid={`video-${media.mid}`}>
        <video className="rr-tile__img" controls preload="none" playsInline src={src} poster={poster || undefined} aria-label={caption ? `Video: ${caption}` : "Video"} />
        {caption && <figcaption className="rr-tile__caption rr-tile__caption--under">{caption}</figcaption>}
      </figure>
    );
  }
  return (
    <figure className="rr-tile rr-tile--video rr-tile--drawn" data-testid={`video-${media.mid}`} style={poster ? undefined : tileStyle(media.mid, 2)}>
      {poster && <img className="rr-tile__img rr-tile__poster" src={poster} alt="" />}
      <span className="rr-tile__glyph rr-tile__glyph--play" aria-hidden="true">▶</span>
      <span className="rr-tile__caption" aria-hidden="true">
        Video
      </span>
      {media.status === "sending" && <span className="rr-tile__note">Sending…</span>}
      {/* Their words under the tile, as a generated video shows them (T30 follow-up). */}
      {/* One accessible name (T30 review M3): "Video: <caption>", or "Video" alone. */}
      <figcaption className={caption ? "rr-tile__caption rr-tile__caption--under" : "visually-hidden"}>
        {caption ? <><span className="visually-hidden">Video: </span>{caption}</> : "Video"}
      </figcaption>
    </figure>
  );
}
