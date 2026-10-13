/**
 * A photo in a thread (spec §13.5, §18.2): the generated image once its URL
 * is ready, else -- while it is made, or for good when image generation is
 * off (the default) -- a procedural tile carrying the photo's caption.
 */
import React from "react";

import { tileStyle } from "../phone/format.js";
import { mediaSrc } from "./media.js";

export default function PhotoTile({ media }) {
  const caption = media.caption || "";
  const src = media.status === "ready" ? mediaSrc(media.url) : "";
  if (src) {
    return (
      <figure className="rr-tile rr-tile--photo" data-testid={`photo-${media.mid}`}>
        <img className="rr-tile__img" src={src} alt={caption || "Photo"} />
      </figure>
    );
  }
  return (
    <figure className="rr-tile rr-tile--photo rr-tile--drawn" data-testid={`photo-${media.mid}`} style={tileStyle(media.mid)}>
      <span className="rr-tile__glyph" aria-hidden="true">▣</span>
      <span className="rr-tile__caption" aria-hidden="true">
        Photo
      </span>
      {media.status === "sending" && <span className="rr-tile__note">Sending…</span>}
      {/* Their words under the tile, as a generated tile shows them (T30 follow-up). */}
      {/* One accessible name (T30 review M3): "Photo: <caption>", or "Photo" alone. */}
      <figcaption className={caption ? "rr-tile__caption rr-tile__caption--under" : "visually-hidden"}>
        {caption ? <><span className="visually-hidden">Photo: </span>{caption}</> : "Photo"}
      </figcaption>
    </figure>
  );
}
