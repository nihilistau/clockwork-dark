/**
 * READ RECEIPTS (v0.22.0, spec §18): a dating story played on a phone.
 *
 * NOT A SKIN. Its play screen is a whole screen of its own (`PlayScreen`):
 * a phone with a lock screen, a home screen and its apps, driven by phone
 * actions (`onAct` -> `phone_action`), never by choices -- the story has none.
 * Its new run is a setup wizard (`NewRun`) over the story's creation form.
 * Both are written against the payload's `phone` block, so a story borrowing
 * this plugin loses them (core's `dressPlugin`). No engine panel is drawn
 * (`ui.panels: []` in the manifest) and none is owned.
 */
import NewRun from "./NewRun.jsx";
import PlayScreen from "./PlayScreen.jsx";
import { initialState, reduce } from "./state.js";

export default {
  slug: "read-receipts",
  title: "Read Receipts",
  documentTitle: "Read Receipts",
  beginLabel: "Set up your phone",

  theme: () => import("./theme/read-receipts.css"),

  // Scoped, like every story's palette: loading this sheet never recolours another story.
  bodyData: () => ({ storySkin: "read-receipts" }),

  initialState,
  reduce,

  PlayScreen,
  NewRun,
};
