/**
 * The client's own test runner.
 *
 * WHY IT IS A SEPARATE FILE. `vite.config.js` is what BUILDS the committed
 * dist/ tree, and the one thing that must never happen to it is an accidental
 * change -- `npm run build` writes into content/scenes/clockwork/static/dist/
 * and that output is checked in. So the test configuration extends it rather
 * than editing it: same `@core` alias, same React plugin, same everything, plus
 * a `test` block. `npm test` and `npm run build` cannot drift apart because
 * there is only one build config and this file imports it.
 *
 * JSDOM, AND WHY IT IS HERE ON DAY ONE. Most of this suite is shape and reducer
 * work that needs no document. The exception earned itself immediately: the
 * plugin contract renders every declared slot against an empty world, because a
 * slot that throws during render does not leave a blank panel -- it unmounts the
 * client -- and every story's first paint and every RESET is exactly that state.
 * The Garden's `Toast` reads `document.documentElement.dataset.reduceMotion`
 * while rendering, which is correct in a browser and a ReferenceError in node.
 * The choice was between a fake `document` that can silently diverge from a real
 * one and the real thing; the real thing costs a devDependency and cannot lie.
 *
 * It is opted into PER FILE (`@vitest-environment jsdom` at the top of
 * `plugin-contract.test.js`) rather than set globally: jsdom's environment setup
 * measured ~20 seconds against ~1 second for the whole suite in node, and a test
 * run nobody wants to wait for is a test run nobody runs.
 *
 * Consequence to know about: under jsdom `import.meta.url` is an http:// URL,
 * not a file:// one, so `fileURLToPath(new URL(..., import.meta.url))` throws
 * there. Files that walk the source tree resolve from `process.cwd()` instead,
 * which vitest sets to `ui/`.
 *
 * NOT WIRED INTO PYTEST, deliberately. `pytest` proves the engine; this proves
 * the client. Running node from inside a Python test would make a green suite
 * depend on a node_modules tree that a player never installs -- the whole point
 * of committing dist/ is that the game plays with no node at all.
 */
import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config.js";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      // Node by default. `plugin-contract.test.js` opts into jsdom with its own
      // docblock, because jsdom costs ~20s of environment setup and only one
      // file needs it -- see the note above.
      environment: "node",
      // `.jsx` too: a test that RENDERS a component is written in JSX like the
      // component is, and @vitejs/plugin-react only transforms files whose
      // extension says so. `narrative-log.test.jsx` is the first.
      include: ["tests/**/*.test.{js,jsx}"],
      // The suite is small and fast; a reporter that prints every file is more
      // useful here than a progress bar.
      reporters: "default",
    },
  })
);
