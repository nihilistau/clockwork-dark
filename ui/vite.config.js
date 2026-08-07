import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds into the Flask static tree. `dist/` is committed so `python
// launcher.py clockwork` plays with no node installed -- node is needed only to
// CHANGE the UI, not to run the game.
export default defineConfig({
  plugins: [react()],
  base: "/static/dist/",
  build: {
    outDir: "../content/scenes/clockwork/static/dist",
    emptyOutDir: true,
    // Predictable filenames: the Jinja template references them directly rather
    // than parsing a manifest.
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "[name].js",
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
