/**
 * The studio — authoring a story without a terminal.
 *
 * Four panes, and the order they sit in is the order the work happens:
 * pick a story, read what is in it, change something, see whether the engine
 * still agrees. The review queue sits alongside because a drafted entry is
 * exactly the same kind of object as a hand-written one — the only difference
 * is that nobody has looked at it yet.
 *
 * WHY THE REVIEW QUEUE IS THE REASON THIS EXISTS. `author.py --promote` is
 * all-or-nothing and blind: it validates, then moves every draft into the live
 * tree at once. Validation catches the shapes that are WRONG — four such were
 * found in one nine-day draft and are now ungrammatical — but what remains is
 * taste, and no validator will ever have any. "Keep this location, rewrite
 * that one, throw the third away" is the verb the tool did not have.
 *
 * Reached by `?studio=1` on a server started with `launcher.py --studio`,
 * riding the same lazy-chunk mechanism as the component kit: a player never
 * fetches it, and a machine that was not started for authoring has no routes
 * to serve it.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";

const EMPTY = { stories: [] };
const TEMPLATES = ["minimal", "graph", "deck"];
const PANES = [
  { id: "stories", label: "Stories" },
  { id: "files", label: "Files" },
  { id: "editor", label: "Editor" },
];

async function json(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

/** Health, as a word rather than a number, because 0 errors is the only good one. */
function Health({ health }) {
  if (!health) return null;
  const { errors = 0, advisories = 0 } = health;
  if (errors > 0) return <span className="st__bad">{errors} error{errors === 1 ? "" : "s"}</span>;
  if (advisories > 0) return <span className="st__warn">{advisories} advisory</span>;
  return <span className="st__ok">clean</span>;
}

function folderOf(path) {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? "(root)" : path.slice(0, cut);
}

function fileNameOf(path) {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? path : path.slice(cut + 1);
}

function groupFiles(files) {
  const groups = new Map();
  for (const file of files) {
    const folder = folderOf(file.path);
    if (!groups.has(folder)) groups.set(folder, []);
    groups.get(folder).push(file);
  }
  return [...groups.entries()];
}

export default function Studio() {
  const [stories, setStories] = useState(EMPTY);
  const [slug, setSlug] = useState("");
  const [story, setStory] = useState(null);
  const [path, setPath] = useState("");
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [issues, setIssues] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [status, setStatus] = useState("");
  const [pane, setPane] = useState("stories");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ slug: "", template: "minimal", title: "" });

  const refreshStories = useCallback(() => {
    json("/api/studio/stories").then(setStories).catch((e) => setStatus(String(e.message)));
  }, []);

  useEffect(refreshStories, [refreshStories]);

  const loadStory = useCallback((next) => {
    json(`/api/studio/story/${next}`).then(setStory).catch((e) => setStatus(String(e.message)));
    json(`/api/studio/drafts/${next}`)
      .then((d) => setDrafts(d.drafts || []))
      .catch(() => setDrafts([]));
  }, []);

  const openStory = useCallback((next) => {
    setSlug(next);
    setPath("");
    setText("");
    setDirty(false);
    setIssues(null);
    setPane("files");
    loadStory(next);
  }, [loadStory]);

  const openFile = useCallback(
    (next) => {
      if (dirty && !window.confirm("Discard unsaved changes?")) return;
      setPath(next);
      setPane("editor");
      json(`/api/studio/file?slug=${encodeURIComponent(slug)}&path=${encodeURIComponent(next)}`)
        .then((f) => {
          setText(f.text);
          setDirty(false);
        })
        .catch((e) => setStatus(String(e.message)));
    },
    [slug, dirty]
  );

  const save = useCallback(() => {
    if (!path || !dirty) return;
    setStatus("Saving…");
    json("/api/studio/file", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, path, text }),
    })
      .then((body) => {
        setDirty(false);
        const errors = body.health?.errors ?? 0;
        setStatus(errors ? `Saved — ${errors} error(s) now` : "Saved — clean");
        refreshStories();
        if (slug) loadStory(slug);
      })
      .catch((e) => setStatus(`Not saved: ${e.message}`));
  }, [slug, path, text, dirty, refreshStories, loadStory]);

  useEffect(() => {
    function onKey(event) {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s") return;
      if (!path || !dirty) return;
      event.preventDefault();
      save();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [path, dirty, save]);

  const validate = useCallback(() => {
    json(`/api/studio/validate/${slug}`)
      .then((b) => setIssues(b.issues || []))
      .catch((e) => setStatus(String(e.message)));
  }, [slug]);

  const reject = useCallback(
    (draftPath) => {
      if (!window.confirm(`Throw away ${draftPath}?`)) return;
      json("/api/studio/draft/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, path: draftPath }),
      })
        .then(() => {
          setDrafts((rows) => rows.filter((r) => r.path !== draftPath));
          setStatus(`Rejected ${draftPath}`);
          refreshStories();
        })
        .catch((e) => setStatus(String(e.message)));
    },
    [slug, refreshStories]
  );

  const accept = useCallback(
    (draftPath) => {
      setStatus("Keeping…");
      json("/api/studio/draft/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, path: draftPath }),
      })
        .then((body) => {
          setDrafts((rows) => rows.filter((r) => r.path !== draftPath));
          const errors = body.health?.errors ?? 0;
          setStatus(
            errors
              ? `Kept as ${body.live} — ${errors} error(s) now`
              : `Kept as ${body.live}`
          );
          refreshStories();
          loadStory(slug);
        })
        .catch((e) => setStatus(`Could not keep: ${e.message}`));
    },
    [slug, refreshStories, loadStory]
  );

  const scaffold = useCallback(
    (event) => {
      event.preventDefault();
      const next = form.slug.trim();
      if (!next) return;
      json("/api/studio/scaffold", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: next,
          template: form.template,
          title: form.title.trim(),
        }),
      })
        .then(() => {
          setStatus(`Scaffolded ${next}`);
          setCreating(false);
          setForm({ slug: "", template: "minimal", title: "" });
          refreshStories();
          openStory(next);
        })
        .catch((e) => setStatus(`Could not scaffold: ${e.message}`));
    },
    [form, refreshStories, openStory]
  );

  const files = useMemo(
    () => groupFiles((story?.files || []).filter((f) => !f.draft)),
    [story]
  );

  return (
    <div className="st" data-pane={pane}>
      <header className="st__top">
        <h1 className="st__brand">Studio</h1>
        <button
          type="button"
          className="st__btn"
          onClick={() => setCreating((on) => !on)}
          aria-expanded={creating}
        >
          New story
        </button>
        <span className="st__status" role="status">{status}</span>
      </header>

      {creating && (
        <form className="st__create" onSubmit={scaffold}>
          <label className="st__field">
            <span>Slug</span>
            <input
              value={form.slug}
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
              placeholder="my-story"
              autoFocus
              required
            />
          </label>
          <label className="st__field">
            <span>Template</span>
            <select
              value={form.template}
              onChange={(e) => setForm({ ...form, template: e.target.value })}
            >
              {TEMPLATES.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>
          <label className="st__field">
            <span>Title</span>
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="optional"
            />
          </label>
          <button type="submit" className="st__btn">Create</button>
          <button type="button" className="st__btn" onClick={() => setCreating(false)}>
            Cancel
          </button>
        </form>
      )}

      <nav className="st__tabs" aria-label="Studio panes">
        {PANES.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={`st__tab ${pane === entry.id ? "is-on" : ""}`}
            onClick={() => setPane(entry.id)}
          >
            {entry.label}
            {entry.id === "files" && drafts.length > 0 ? ` (${drafts.length})` : ""}
          </button>
        ))}
      </nav>

      <div className="st__grid">
        <nav className="st__pane st__stories">
          <h2 className="st__h">Stories</h2>
          {stories.stories.length === 0 && (
            <p className="st__hint">No stories on disk, or the studio routes are not mounted.</p>
          )}
          <ul className="st__list">
            {stories.stories.map((row) => (
              <li key={row.slug}>
                <button
                  type="button"
                  className={`st__row ${row.slug === slug ? "is-on" : ""}`}
                  onClick={() => openStory(row.slug)}
                >
                  <span className="st__name">{row.title}</span>
                  <Health health={row.health} />
                  {row.drafts > 0 && (
                    <span className="st__badge">
                      {row.drafts} draft{row.drafts === 1 ? "" : "s"}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <nav className="st__pane st__files">
          <h2 className="st__h">Files</h2>
          {!story && <p className="st__hint">Pick a story.</p>}
          {files.map(([folder, rows]) => (
            <div key={folder} className="st__group">
              <h3 className="st__folder">{folder}</h3>
              <ul className="st__list">
                {rows.map((f) => (
                  <li key={f.path}>
                    <button
                      type="button"
                      className={`st__row ${f.path === path ? "is-on" : ""}`}
                      onClick={() => openFile(f.path)}
                    >
                      {fileNameOf(f.path)}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          <h2 className="st__h st__h--later">Review queue</h2>
          {drafts.length === 0 ? (
            <p className="st__hint">
              Nothing waiting. Drafts the model writes land here to be read
              before they become part of the story.
            </p>
          ) : (
            drafts.map((draft) => (
              <article key={draft.path} className="st__draft">
                <h3 className="st__draftname">
                  <span className="st__kind">{draft.kind}</span> {fileNameOf(draft.path)}
                </h3>
                <pre className="st__pre">{draft.text}</pre>
                <div className="st__actions">
                  <button type="button" className="st__btn st__btn--keep" onClick={() => accept(draft.path)}>
                    Keep
                  </button>
                  <button
                    type="button"
                    className="st__btn"
                    onClick={() => openFile(draft.path)}
                  >
                    Edit in place
                  </button>
                  <button type="button" className="st__btn" onClick={() => reject(draft.path)}>
                    Throw away
                  </button>
                </div>
              </article>
            ))
          )}
        </nav>

        <section className="st__pane st__editor">
          <h2 className="st__h">
            {path || "Nothing open"}
            {dirty && <span className="st__dirty"> • unsaved</span>}
          </h2>
          {!path && (
            <p className="st__hint">
              Open a file from the list. Ctrl+S saves when something has changed.
            </p>
          )}
          <textarea
            className="st__text"
            value={text}
            spellCheck={false}
            onChange={(e) => {
              setText(e.target.value);
              setDirty(true);
            }}
            disabled={!path}
          />
          <div className="st__actions">
            <button type="button" className="st__btn" onClick={save} disabled={!path || !dirty}>
              Save
            </button>
            <button type="button" className="st__btn" onClick={validate} disabled={!slug}>
              Validate
            </button>
          </div>

          {issues && (
            <div className="st__issues">
              {issues.length === 0 ? (
                <p className="st__ok">No errors, no advisories.</p>
              ) : (
                <ul className="st__list">
                  {issues.map((issue, index) => (
                    <li key={index} className={`st__issue st__issue--${issue.severity}`}>
                      <code>{issue.source}</code> {issue.ref_id} — {issue.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
