/**
 * The ending's plate (v0.25.0 §8.6): the `gallery` art kind (E7), keyed by the epilogue's gallery_key.
 * Drawn in place of core's "Added to the gallery: <key>" line, so the key itself is never printed.
 * Until a plate is painted the frame draws its own empty plate, as every missing picture does.
 */
import React, { useEffect, useState } from "react";
import PaintFrame from "@core/parts/PaintFrame.jsx";
import { fetchArtUrl } from "@core/api.js";

export default function EndingPlate({ ending }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let live = true;
    if (ending?.gallery_key) {
      fetchArtUrl(ending.gallery_key, "gallery")
        .then((u) => live && setUrl(u || ""))
        .catch(() => {});
    }
    return () => {
      live = false;
    };
  }, [ending?.gallery_key]);
  return (
    <PaintFrame size="tile" className="finale__plate">
      {url && <img className="paint__img is-loaded" src={url} alt="" />}
    </PaintFrame>
  );
}
