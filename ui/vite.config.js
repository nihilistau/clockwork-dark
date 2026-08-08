import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds into the Flask static tree. `dist/` is committed so `python
// launcher.py clockwork` plays with no node installed -- node is needed only to
// CHANGE the UI, not to run the game.
export default defineConfig({
  plugins: [react()],
  resolve: {
    // A story lives at src/stories/<slug>/ and reaches into core constantly.
    // `../../../core/parts/Modal.jsx` from every one of them is unreadable and
    // silently wrong the moment a file moves one level; `@core` also makes the
    // dependency DIRECTION visible in the import line -- stories may import
    // core, core must never import a story.
    alias: {
      "@core": fileURLToPath(new URL("./src/core", import.meta.url)),
    },
  },
  base: "/static/dist/",
  build: {
    outDir: "../content/scenes/clockwork/static/dist",
    emptyOutDir: true,
    // Predictable filenames: the Jinja template references them directly rather
    // than parsing a manifest.
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        // A story plugin is `stories/<slug>/index.jsx`, so every one of them
        // would land on `index.js` and the second would silently overwrite the
        // first. Name a chunk after the directory it came from when its own
        // name is the meaningless "index".
        chunkFileNames: (chunk) => {
          if (chunk.name !== "index") return "[name].js";
          const id = chunk.facadeModuleId || Object.keys(chunk.modules)[0] || "";
          const dir = id.split(/[\\/]/).at(-2) || "chunk";
          return `${dir}.js`;
        },
        assetFileNames: "[name][extname]",
      },
    },
  },
  server: {
    port: 5174,
    // `npm run dev` gives HMR against the live Flask server on 5573.
    proxy: {
      "/api": "http://localhost:5573",
      "/socket.io": { target: "http://localhost:5573", ws: true },
    },
  },
});
