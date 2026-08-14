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
import React, { useCallback, useEffect, useState } from "react";

const EMPTY = { stories: [] };

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

  const refreshStories = useCallback(() => {
    json("/api/studio/stories").then(setStories).catch((e) => setStatus(String(e.message)));
  }, []);

  useEffect(refreshStories, [refreshStories]);

  const openStory = useCallback((next) => {
    setSlug(next);
    setPath("");
    setText("");
    setDirty(false);
    setIssues(null);
    json(`/api/studio/story/${next}`).then(setStory).catch((e) => setStatus(String(e.message)));
    json(`/api/studio/drafts/${next}`)
      .then((d) => setDrafts(d.drafts || []))
      .catch(() => setDrafts([]));
  }, []);

  const openFile = useCallback(
    (next) => {
      if (dirty && !window.confirm("Discard unsaved changes?")) return;
      setPath(next);
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
    setStatus("Saving…");
    json("/api/studio/file", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, path, text }),
    })
      .then((body) => {
        setDirty(false);
        // The health the write CAUSED, reported rather than enforced: a story
        // mid-edit is allowed to be briefly wrong, but not silently.
        const errors = body.health?.errors ?? 0;
        setStatus(errors ? `Saved — ${errors} error(s) now` : "Saved — clean");
        refreshStories();
      })
      .catch((e) => setStatus(`Not saved: ${e.message}`));
  }, [slug, path, text, refreshStories]);

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
        })
        .catch((e) => setStatus(String(e.message)));
    },
    [slug]
  );

  const scaffold = useCallback(() => {
    const next = window.prompt("New story slug (lowercase, hyphens):");
    if (!next) return;
    const template = window.prompt("Template — minimal, graph or deck:", "minimal");
    if (!template) return;
    json("/api/studio/scaffold", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: next, template }),
    })
      .then(() => {
        setStatus(`Scaffolded ${next}`);
        refreshStories();
        openStory(next);
      })
      .catch((e) => setStatus(`Could not scaffold: ${e.message}`));
  }, [refreshStories, openStory]);

  return (
    <div className="st">
      <header className="st__top">
        <h1 className="st__brand">Studio</h1>
        <button type="button" className="st__btn" onClick={scaffold}>
          New story
        </button>
        <span className="st__status" role="status">{status}</span>
      </header>

      <div className="st__grid">
        <nav className="st__pane st__stories">
          <h2 className="st__h">Stories</h2>
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
                  {row.drafts > 0 && <span className="st__badge">{row.drafts} draft</span>}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <nav className="st__pane st__files">
          <h2 className="st__h">Files</h2>
          {!story && <p className="st__hint">Pick a story.</p>}
          <ul className="st__list">
            {(story?.files || [])
              .filter((f) => !f.draft)
              .map((f) => (
                <li key={f.path}>
                  <button
                    type="button"
                    className={`st__row ${f.path === path ? "is-on" : ""}`}
                    onClick={() => openFile(f.path)}
                  >
                    {f.path}
                  </button>
                </li>
              ))}
          </ul>
        </nav>

        <section className="st__pane st__editor">
          <h2 className="st__h">
            {path || "Nothing open"}
            {dirty && <span className="st__dirty"> • unsaved</span>}
          </h2>
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

        <section className="st__pane st__drafts">
          <h2 className="st__h">Review queue</h2>
          {drafts.length === 0 ? (
            <p className="st__hint">
              Nothing waiting. Drafts the model writes land here to be read
              before they become part of the story.
            </p>
          ) : (
            drafts.map((draft) => (
              <article key={draft.path} className="st__draft">
                <h3 className="st__draftname">
                  <span className="st__kind">{draft.kind}</span> {draft.path.split("/").pop()}
                </h3>
                <pre className="st__pre">{draft.text}</pre>
                <div className="st__actions">
                  <button type="button" className="st__btn" onClick={() => reject(draft.path)}>
                    Throw away
                  </button>
                  <button
                    type="button"
                    className="st__btn"
                    onClick={() => openFile(draft.path)}
                  >
                    Edit in place
                  </button>
                </div>
              </article>
            ))
          )}
        </section>
      </div>
    </div>
  );
}
