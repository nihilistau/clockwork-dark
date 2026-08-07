/**
 * Clockwork Dark — scene client (vanilla JS + Socket.IO)
 */
(function () {
  "use strict";

  const logEl = document.getElementById("narrative-log");
  const choicesEl = document.getElementById("choices");
  const statusEl = document.getElementById("connection-status");
  const customForm = document.getElementById("custom-form");
  const customText = document.getElementById("custom-text");
  const assistantBubble = document.getElementById("assistant-bubble");
  const assistantText = document.getElementById("assistant-text");
  const assistantForm = document.getElementById("assistant-form");
  const sceneImage = document.getElementById("scene-image");
  const scenePlaceholder = document.getElementById("scene-placeholder");

  let sessionId = null;
  let busy = false;
  const socket = io();

  let streamEntry = null;
  let watchdog = null;

  // Auto-scroll only when the player is already at the bottom, so reading back
  // through the log is not yanked away on every token.
  function atBottom() {
    return logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  }

  function appendNarration(text, className) {
    const stick = atBottom();
    const entry = document.createElement("div");
    entry.className = className || "narrative-entry";
    entry.textContent = text;
    logEl.appendChild(entry);
    if (stick) logEl.scrollTop = logEl.scrollHeight;
    return entry;
  }

  function streamNarration(text) {
    const stick = atBottom();
    if (!streamEntry) {
      // One entry per turn, appended to. Creating a div per chunk would turn
      // every token fragment into its own paragraph.
      streamEntry = appendNarration("", "narrative-entry streaming");
    }
    streamEntry.textContent += text;
    if (stick) logEl.scrollTop = logEl.scrollHeight;
  }

  function finalizeStream() {
    if (streamEntry) {
      streamEntry.classList.remove("streaming");
      streamEntry = null;
    }
  }

  function showDice(d) {
    if (!d || typeof d.total === "undefined") return;
    const roll = Array.isArray(d.rolls) ? d.rolls[0] : d.roll;
    const mod = d.modifier || 0;
    const sign = mod < 0 ? "−" : "+";
    const parts = [`d${d.sides || 20}: ${roll} ${sign} ${Math.abs(mod)} = ${d.total}`];
    if (typeof d.dc !== "undefined") parts.push(`vs DC ${d.dc}`);
    if (typeof d.success !== "undefined") parts.push(d.success ? "— Success" : "— Failure");
    appendNarration(parts.join(" "), "dice-line");
  }

  function renderChoices(choices) {
    choicesEl.innerHTML = "";
    (choices || []).forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice-btn";
      btn.textContent = c.text;
      btn.dataset.choiceId = c.id;
      btn.addEventListener("click", () => submitChoice(c.id));
      choicesEl.appendChild(btn);
    });
  }

  function updateStats(state) {
    if (!state || !state.stats) return;
    document.getElementById("stat-hp").textContent =
      `${state.stats.hp}/${state.stats.max_hp}`;
    document.getElementById("stat-stamina").textContent = String(state.stats.stamina);
    document.getElementById("stat-gold").textContent = String(state.stats.gold);
    document.getElementById("stat-location").textContent = state.location_id || "—";
    document.getElementById("world-clock").textContent =
      `Day ${state.world_day} · ${String(state.world_hour).padStart(2, "0")}:00`;

    const inv = document.getElementById("inventory");
    inv.innerHTML = "";
    (state.inventory || []).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = `${item.name} ×${item.qty}`;
      inv.appendChild(li);
    });
  }

  function applyTurn(payload, opts) {
    const skip = opts && opts.skipNarration;
    if (payload.narration && !skip) appendNarration(payload.narration);
    renderChoices(payload.choices);
    updateStats(payload.state);
    // Four designed phase themes existed and none were reachable: the attribute
    // was hardcoded in the template and never updated.
    if (payload.state && payload.state.evil_phase) {
      document.body.dataset.phase = payload.state.evil_phase;
    }
    if (payload.assistant && payload.assistant.spoke) {
      showAssistant(payload.assistant);
    }
  }

  function showAssistant(asst) {
    assistantBubble.classList.remove("hidden");
    assistantForm.textContent = asst.form || "cat";
    assistantText.textContent = asst.text || "";
  }

  function setBusy(value) {
    busy = value;
    choicesEl.querySelectorAll("button").forEach((b) => {
      b.disabled = value;
    });
    // The text input was left enabled, so submissions could be queued mid-turn
    // and silently dropped by the busy guard with no feedback at all.
    customText.disabled = value;
    document.getElementById("send-btn").disabled = value;

    if (watchdog) clearTimeout(watchdog);
    if (value) {
      // Last line of defence. If the server dies without emitting anything,
      // every control stayed disabled forever with no message on screen.
      watchdog = setTimeout(() => {
        statusEl.textContent = "No response from the server. Try again.";
        finalizeStream();
        setBusy(false);
      }, 180000);
    }
  }

  function submitChoice(choiceId, custom) {
    if (!sessionId || busy) return;
    setBusy(true);
    appendNarration(custom || labelFor(choiceId), "player-echo");
    socket.emit("player_choice", {
      session_id: sessionId,
      choice_id: choiceId,
      custom_text: custom || null,
    });
  }

  function labelFor(choiceId) {
    const btn = choicesEl.querySelector(`[data-choice-id="${choiceId}"]`);
    return btn ? btn.textContent : choiceId;
  }

  socket.on("connect", () => {
    statusEl.textContent = "Connected";
    // Resume rather than restart. This used to call startGame() on every
    // connect, so any transient socket drop silently began a new game and
    // abandoned the run in progress.
    const saved = window.localStorage.getItem("clockwork_save_id");
    if (saved) socket.emit("resume", { save_id: saved });
    else startGame();
  });

  socket.on("disconnect", () => {
    statusEl.textContent = "Disconnected";
    setBusy(false);
  });

  socket.on("game_started", (data) => {
    sessionId = data.session_id;
    if (data.save_id) window.localStorage.setItem("clockwork_save_id", data.save_id);
    if (data.opening) applyTurn(data.opening);
    else updateStats(data.state);
  });

  socket.on("game_resumed", (data) => {
    sessionId = data.session_id;
    statusEl.textContent = "Resumed";
    updateStats(data.state);
    if (data.state && data.state.evil_phase) {
      document.body.dataset.phase = data.state.evil_phase;
    }
    setBusy(false);
  });

  socket.on("resume_failed", () => {
    window.localStorage.removeItem("clockwork_save_id");
    startGame();
  });

  socket.on("turn_update", (payload) => {
    // The narration already arrived token by token; finalize the live entry
    // rather than appending the whole paragraph again.
    if (payload.streamed) finalizeStream();
    applyTurn(payload, { skipNarration: Boolean(payload.streamed) });
    setBusy(false);
  });

  socket.on("assistant_speak", (data) => {
    showAssistant(data);
  });

  socket.on("image_ready", (data) => {
    if (data.url) {
      sceneImage.src = data.url;
      sceneImage.hidden = false;
      scenePlaceholder.hidden = true;
    }
  });

  socket.on("narration_delta", (data) => {
    const text = typeof data === "string" ? data : data && data.text;
    if (text) streamNarration(text);
  });

  socket.on("dice_result", (data) => {
    showDice(data);
  });

  socket.on("turn_error", (data) => {
    statusEl.textContent = (data && data.message) || "The turn failed.";
    finalizeStream();
    setBusy(false);
  });

  socket.on("error", (err) => {
    statusEl.textContent = err.message || "Error";
    setBusy(false);
  });

  customForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = customText.value.trim();
    if (!text) return;
    customText.value = "";
    submitChoice("custom", text);
  });

  async function startGame() {
    try {
      const res = await fetch("/api/game/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_name: "Traveler", archetype: "wayfarer" }),
      });
      const data = await res.json();
      sessionId = data.session_id;
      if (data.save_id) window.localStorage.setItem("clockwork_save_id", data.save_id);
      // Do NOT render the opening here. join_session replies with game_started
      // carrying the same opening, and rendering both printed it twice.
      socket.emit("join_session", { session_id: sessionId });
      updateStats(data.state);
    } catch (err) {
      statusEl.textContent = "Failed to start game";
      console.error(err);
    }
  }
})();