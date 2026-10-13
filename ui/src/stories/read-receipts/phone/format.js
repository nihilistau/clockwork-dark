/**
 * Small readers of the phone payload's numbers: clock hours to a time of day,
 * ids to words, and the procedural tile a photo is drawn as until (or
 * unless) a generated image exists (spec §13.5).
 */

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const pad = (n) => String(n).padStart(2, "0");

/** The payload's `now` ({day, hour, minute, weekday}) as "21:16". */
export function clockOf(now) {
  if (!now) return "--:--";
  return `${pad(Number(now.hour) || 0)}:${pad(Number(now.minute) || 0)}`;
}

/** World clock hours (a message's or notification's `at`) as {day, hour, minute, weekday}. */
export function whenOf(at) {
  const total = Math.max(0, Number(at) || 0);
  const day = Math.floor(total / 24) + 1;
  const minutes = Math.round((total - Math.floor(total)) * 60) % 60;
  return { day, hour: Math.floor(total) % 24, minute: minutes, weekday: WEEKDAYS[(day - 1) % 7] };
}

/** `at` relative to `now`: "21:16" today, "Tue 21:16" another day. */
export function stampOf(at, now) {
  const when = whenOf(at);
  const time = `${pad(when.hour)}:${pad(when.minute)}`;
  return now && Number(now.day) === when.day ? time : `${when.weekday} ${time}`;
}

/** "dont_want" -> "Dont want"; a label the data gave is left alone. */
export function humanize(id) {
  const text = String(id || "").replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

/** A stable hue for an id: the same person's tiles keep one colour. */
export function hueOf(id) {
  let h = 0;
  for (const ch of String(id || "")) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

/** The procedural tile's background: two shades of one hue, dark enough for white text. */
export function tileStyle(id, shift = 0) {
  const hue = (hueOf(id) + shift * 37) % 360;
  return { backgroundImage: `linear-gradient(160deg, hsl(${hue} 42% 34%), hsl(${(hue + 40) % 360} 46% 20%))` };
}

/** First letter of a name, for an avatar with no portrait. */
export const initialOf = (name) => (String(name || "?").trim()[0] || "?").toUpperCase();
