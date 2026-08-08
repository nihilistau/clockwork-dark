/**
 * Resolve a manifest art key to a URL, once per key.
 *
 * Encounters ship `art: "wolf"` and `art_kind: "enemy"`; the filename lives in
 * data/art/manifest.yaml, which the browser cannot read. Results are memoized
 * per key because a panel re-renders on every round and the answer never
 * changes for a given key.
 */
import { useEffect, useState } from "react";
import { fetchArtUrl } from "../api.js";

const cache = new Map();

export default function useArtUrl(id, kind = "enemy") {
  const key = `${kind}:${id}`;
  const [url, setUrl] = useState(() => cache.get(key) || "");

  useEffect(() => {
    if (!id) {
      setUrl("");
      return undefined;
    }
    if (cache.has(key)) {
      setUrl(cache.get(key));
      return undefined;
    }
    let live = true;
    fetchArtUrl(id, kind).then((resolved) => {
      cache.set(key, resolved);
      // The panel may have closed, or the encounter changed, while the
      // request was in flight; setting state then is a React warning and a
      // picture of the wrong monster.
      if (live) setUrl(resolved);
    });
    return () => {
      live = false;
    };
  }, [id, kind, key]);

  return url;
}
