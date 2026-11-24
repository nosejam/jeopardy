let hostSocket = null;
let hostState = null;
let lastHostState = {};
const responseDialog = document.getElementById("responseDialog");
const updateHostTimer = createClueTimer(document.getElementById("hostClueTimer"));
const updateResponseTimer = createClueTimer(document.getElementById("responseTimer"), { sound: true });
responseDialog.addEventListener("cancel", event => event.preventDefault());
responseDialog.querySelectorAll("[data-verdict]").forEach(button => {
  button.addEventListener("click", () => sendHost({
    action: button.dataset.verdict,
    response_number: hostState.response_number
  }));
});
const gameBase = `/g/${window.JEOPARDY_GAME_CODE}`;
connectHost();

document.querySelectorAll("[data-action]").forEach(button => {
  button.addEventListener("click", () => sendHost({ action: button.dataset.action }));
});
document.querySelectorAll("[data-round]").forEach(button => {
  button.addEventListener("click", () => sendHost({ action: "set_round", round: button.dataset.round }));
});
document.getElementById("ddApply").addEventListener("click", () => {
  sendHost({
    action: "daily_double_setup",
    player_id: document.getElementById("ddPlayer").value,
    wager: document.getElementById("ddWager").value
  });
});
const muteToggle = document.getElementById("muteToggle");
if (window.JeopardyAudio) {
  muteToggle.checked = JeopardyAudio.isMuted();
  muteToggle.addEventListener("change", () => JeopardyAudio.setMuted(muteToggle.checked));
}
const gameSelection = document.getElementById("gameSelection");
gameSelection.addEventListener("change", () => {
  sendHost({ action: "set_game_selection", selection: gameSelection.value });
});
const finalProgressButton = document.getElementById("finalProgressButton");
finalProgressButton.addEventListener("click", () => {
  if (hostState && hostState.status === "final" && hostState.final_phase === "wagers") {
    sendHost({ action: "reveal_final" });
  } else {
    sendHost({ action: "start_final" });
  }
});

const clueUploadForm = document.getElementById("clueUploadForm");
const clueCsvInput = document.getElementById("clueCsvInput");
const clueUploadStatus = document.getElementById("clueUploadStatus");
clueUploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = clueCsvInput.files[0];
  if (!file) {
    clueUploadStatus.textContent = "Choose a CSV file.";
    return;
  }
  clueUploadStatus.textContent = "Loading clues...";
  try {
    const response = await fetch(`${gameBase}/host/clues`, {
      method: "POST",
      headers: { "Content-Type": file.type || "text/csv" },
      body: file
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "CSV upload failed.");
    clueCsvInput.value = "";
    clueUploadStatus.textContent = `Loaded ${payload.clue_count} clues.`;
  } catch (error) {
    clueUploadStatus.textContent = error.message;
  }
});

function connectHost() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  hostSocket = new WebSocket(`${protocol}://${location.host}${gameBase}/ws/host`);
  hostSocket.onopen = () => document.getElementById("hostStatus").textContent = "Connected";
  hostSocket.onclose = () => {
    document.getElementById("hostStatus").textContent = "Disconnected";
    setTimeout(connectHost, 1200);
  };
  hostSocket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") renderHost(message.state);
    if (message.type === "error") document.getElementById("hostStatus").textContent = message.message;
  };
}

function sendHost(payload) {
  if (hostSocket && hostSocket.readyState === WebSocket.OPEN) hostSocket.send(JSON.stringify(payload));
}

function renderHost(state) {
  if (window.JeopardyAudio) {
    if (!lastHostState.buzzer_open && state.buzzer_open) JeopardyAudio.play("open");
    if (!lastHostState.first_buzzer && state.first_buzzer) JeopardyAudio.play("buzz");
  }
  lastHostState = state;
  hostState = state;
  renderPlayers(state);
  renderGameSelection(state);
  renderHostBoard(state);
  renderHostClue(state);
  renderResponseDialog(state);
  renderFinalHost(state);
  renderFinalProgress(state);
}

function renderGameSelection(state) {
  const selected = state.game_selection || "random";
  const options = state.game_options || [];
  gameSelection.innerHTML = `<option value="random">Random</option>` + options.map(gameId => (
    `<option value="${escapeHtml(gameId)}">Game ${escapeHtml(gameId)}</option>`
  )).join("");
  gameSelection.value = selected;
}

function renderPlayers(state) {
  const list = document.getElementById("hostPlayers");
  list.innerHTML = state.players.map(p => `
    <div class="host-player">
      <div class="host-player-info">
        <strong>${escapeHtml(p.name)}</strong>
        <span>${p.connected ? "online" : "offline"}</span>
      </div>
      <input class="host-player-score" type="number" value="${p.score}" data-score="${p.id}" aria-label="${escapeHtml(p.name)} score">
      <div class="host-player-actions">
        <button data-plus="${p.id}">+100</button>
        <button data-minus="${p.id}">-100</button>
        <button data-reset-score="${p.id}">Reset</button>
      </div>
    </div>
  `).join("");
  list.querySelectorAll("[data-score]").forEach(input => input.addEventListener("change", () => {
    sendHost({ action: "set_score", player_id: input.dataset.score, score: input.value });
  }));
  list.querySelectorAll("[data-plus]").forEach(btn => btn.addEventListener("click", () => sendHost({ action: "adjust_score", player_id: btn.dataset.plus, delta: 100 })));
  list.querySelectorAll("[data-minus]").forEach(btn => btn.addEventListener("click", () => sendHost({ action: "adjust_score", player_id: btn.dataset.minus, delta: -100 })));
  list.querySelectorAll("[data-reset-score]").forEach(btn => btn.addEventListener("click", () => sendHost({ action: "set_score", player_id: btn.dataset.resetScore, score: 0 })));

  const ddPlayer = document.getElementById("ddPlayer");
  ddPlayer.innerHTML = `<option value="">Daily Double player</option>` + state.players.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  ddPlayer.value = state.daily_double_player || "";
}

function renderFinalProgress(state) {
  if (state.status === "final" && state.final_phase === "wagers") {
    finalProgressButton.textContent = "Reveal Final Clue";
    finalProgressButton.disabled = false;
  } else if (state.status === "final" && state.final_phase === "answers") {
    finalProgressButton.textContent = "Final Clue Revealed";
    finalProgressButton.disabled = true;
  } else {
    finalProgressButton.textContent = "Final";
    finalProgressButton.disabled = false;
  }
}

function renderHostBoard(state) {
  const html = Object.entries(state.board).map(([cat, clues]) => `
    <div class="host-board-column">
      <div class="host-category">${escapeHtml(cat)}</div>
      ${clues.map(c => `<button data-clue="${escapeHtml(c.id)}" ${c.used || state.status !== "board" ? "disabled" : ""}>${c.used ? "Used" : "$" + c.value}${c.daily_double ? " *" : ""}</button>`).join("")}
    </div>
  `).join("");
  const board = document.getElementById("hostBoard");
  board.innerHTML = html || "<p>No clues for this round.</p>";
  board.querySelectorAll("[data-clue]").forEach(button => button.addEventListener("click", () => sendHost({
    action: "select_clue", clue_id: button.dataset.clue, board_number: state.board_number
  })));
}

function renderResponseDialog(state) {
  const judging = state.status === "clue" && !state.daily_double_active && state.current_respondent && state.current_clue;
  updateHostTimer(judging ? {} : state);
  updateResponseTimer(judging ? state : {});
  if (!judging) {
    if (responseDialog.open) responseDialog.close();
    return;
  }
  document.getElementById("responseTeam").textContent = state.first_buzzer_name;
  document.getElementById("judgeResponse").textContent = state.current_clue.answer;
  const alternatives = document.getElementById("judgeAlternatives");
  alternatives.hidden = !state.current_clue.accepted_answers;
  alternatives.textContent = "Also accepted: " + state.current_clue.accepted_answers;
  if (!responseDialog.open) responseDialog.showModal();
}

function renderHostClue(state) {
  const clue = state.current_clue;
  const waitingForFinalWagers = state.status === "final" && state.final_phase === "wagers";
  const respondent = state.players.find(p => p.id === state.current_respondent);
  const locked = (state.locked_out || []).map(id => (state.players.find(p => p.id === id) || {}).name).filter(Boolean);
  const judged = state.judged_respondents || [];
  const scoringPlayer = state.daily_double_active ? state.daily_double_player : state.current_respondent;
  const alreadyJudged = scoringPlayer ? judged.includes(scoringPlayer) : false;
  document.getElementById("hostClue").innerHTML = clue ? `
    <div class="host-current">
      <div><strong>${escapeHtml(clue.category)}</strong> $${clue.value}</div>
      <p>${waitingForFinalWagers ? "Final Jeopardy clue hidden until reveal." : escapeHtml(clue.clue)}</p>
      ${clue.daily_double ? `<div class="daily-inline">Daily Double</div>` : ""}
      <div class="answer-box">Correct response: <strong>${escapeHtml(clue.answer)}</strong></div>
      ${clue.accepted_answers ? `<div class="answer-box">Accepted: ${escapeHtml(clue.accepted_answers)}</div>` : ""}
      <div>Buzzer: ${state.buzzer_open ? "OPEN" : "closed"}</div>
      <div>First: <strong>${escapeHtml(state.first_buzzer_name || "None")}</strong></div>
      <div>Respondent: <strong>${escapeHtml(respondent ? respondent.name : "None")}</strong></div>
      <div>Locked out: ${escapeHtml(locked.join(", ") || "None")}</div>
      <div>Correct response on display: <strong>${state.answer_revealed ? "yes" : "no"}</strong></div>
    </div>
  ` : "<p>No active clue.</p>";
  setActionDisabled("correct", !clue || !scoringPlayer || alreadyJudged);
  setActionDisabled("incorrect", !clue || !scoringPlayer || alreadyJudged);
  document.querySelectorAll('[data-action="correct"], [data-action="incorrect"]').forEach(button => {
    button.hidden = !state.daily_double_active || state.status !== "clue";
  });
  setActionDisabled("open_buzzers", state.status !== "clue" || state.daily_double_active || state.answer_revealed || state.buzzer_open || Boolean(state.current_respondent));
  setActionDisabled("close_buzzers", !state.buzzer_open);
  setActionDisabled("display_answer", !clue || state.answer_revealed);
}

function renderFinalHost(state) {
  const entries = state.final_entries || {};
  document.getElementById("finalHostList").innerHTML = Object.entries(entries).map(([pid, entry]) => `
    <div class="final-entry">
      <div class="final-entry-info">
        <strong>${escapeHtml(entry.player.name)}</strong>
        <span>Wager: ${finalWagerText(pid, entry)}</span>
        <span>Response: ${finalResponseText(pid, entry)}</span>
      </div>
      <div class="final-entry-actions">
        <button data-show-wager="${pid}" ${entry.locked_wager && !entry.revealed_wager ? "" : "disabled"}>Display Wager</button>
        <button data-show-response="${pid}" ${entry.locked_answer && !entry.revealed_answer ? "" : "disabled"}>Display Response</button>
        <button data-final-correct="${pid}">Correct</button>
        <button data-final-incorrect="${pid}">Incorrect</button>
        <button data-reset-wager="${pid}">Reset Wager</button>
        <button data-reset-answer="${pid}">Reset Response</button>
      </div>
    </div>
  `).join("");
  document.querySelectorAll("[data-final-correct]").forEach(btn => {
    const entry = entries[btn.dataset.finalCorrect];
    btn.disabled = entry?.judged || !entry?.locked_answer;
    btn.addEventListener("click", () => sendHost({ action: "judge_final", player_id: btn.dataset.finalCorrect, correct: true }));
  });
  document.querySelectorAll("[data-final-incorrect]").forEach(btn => {
    const entry = entries[btn.dataset.finalIncorrect];
    btn.disabled = entry?.judged || !entry?.locked_answer;
    btn.addEventListener("click", () => sendHost({ action: "judge_final", player_id: btn.dataset.finalIncorrect, correct: false }));
  });
  document.querySelectorAll("[data-show-wager]").forEach(btn => btn.addEventListener("click", () => sendHost({ action: "reveal_final_wager", player_id: btn.dataset.showWager })));
  document.querySelectorAll("[data-show-response]").forEach(btn => btn.addEventListener("click", () => sendHost({ action: "reveal_final_answer", player_id: btn.dataset.showResponse })));
  document.querySelectorAll("[data-reset-wager]").forEach(btn => btn.addEventListener("click", () => sendHost({ action: "reset_final_player", player_id: btn.dataset.resetWager, field: "wager" })));
  document.querySelectorAll("[data-reset-answer]").forEach(btn => btn.addEventListener("click", () => sendHost({ action: "reset_final_player", player_id: btn.dataset.resetAnswer, field: "answer" })));
}

function finalWagerText(playerId, entry) {
  if (!entry.locked_wager) return "pending";
  return entry.revealed_wager ? `$${entry.wager}` : "submitted";
}

function finalResponseText(playerId, entry) {
  if (!entry.locked_answer) return "pending";
  return entry.revealed_answer ? escapeHtml(entry.answer) : "submitted";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}

function setActionDisabled(action, disabled) {
  document.querySelectorAll(`[data-action="${action}"]`).forEach(button => {
    button.disabled = Boolean(disabled);
  });
}
