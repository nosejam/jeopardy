const screens = {
  lobby: document.getElementById("displayLobby"),
  board: document.getElementById("displayBoard"),
  clue: document.getElementById("displayClue"),
  scoreboard: document.getElementById("displayScoreboard")
};
let lastState = {};
const gameBase = `/g/${window.JEOPARDY_GAME_CODE}`;
connectDisplay();

function connectDisplay() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}${gameBase}/ws/display`);
  socket.onclose = () => setTimeout(connectDisplay, 1200);
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") renderDisplay(message.state);
  };
}

function show(which) {
  Object.entries(screens).forEach(([name, node]) => node.classList.toggle("hidden", name !== which));
}

function renderDisplay(state) {
  if (window.JeopardyAudio) {
    if (!lastState.buzzer_open && state.buzzer_open) JeopardyAudio.play("open");
    if (!lastState.first_buzzer && state.first_buzzer) JeopardyAudio.play("buzz");
    if (state.status === "daily_double_intro" && lastState.status !== "daily_double_intro") JeopardyAudio.play("daily");
    if (state.status === "final" && lastState.status !== "final") JeopardyAudio.play("final");
  }
  lastState = state;

  document.getElementById("joinUrl").textContent = state.join_url || location.origin;
  document.getElementById("playerCount").textContent = state.players.length;
  document.getElementById("lobbyPlayers").innerHTML = state.players.map(p => `<div>${escapeHtml(p.name)}</div>`).join("");
  renderScores(state.players);

  if (state.status === "lobby") show("lobby");
  else if (["board"].includes(state.status)) { show("board"); renderBoard(state); }
  else if (["scoreboard", "final_standings"].includes(state.status)) { show("scoreboard"); renderRankings(state); }
  else { show("clue"); renderClue(state); }
}

function renderScores(players) {
  document.getElementById("scoreStrip").innerHTML = players.map(p => `<div><span>${escapeHtml(p.name)}</span><strong>$${p.score}</strong></div>`).join("");
}

function renderBoard(state) {
  document.getElementById("boardRound").textContent = state.current_round;
  const categories = Object.entries(state.board);
  const html = categories.map(([cat, clues]) => `
    <div class="board-column">
      <div class="board-category">${escapeHtml(cat)}</div>
      ${clues.map(c => `<div class="board-cell ${c.used ? "used" : ""}">${c.used ? "" : "$" + c.value}</div>`).join("")}
    </div>
  `).join("");
  document.getElementById("gameBoard").innerHTML = html;
}

function renderClue(state) {
  const clue = state.current_clue || {};
  const waitingForFinalWagers = state.status === "final" && state.final_phase === "wagers";
  document.getElementById("dailyDoubleBanner").classList.toggle("hidden", state.status !== "daily_double_intro");
  document.getElementById("clueCategory").textContent = clue.category || "";
  document.getElementById("clueValue").textContent = clue.value ? `$${clue.value}` : "";
  document.getElementById("clueText").textContent = waitingForFinalWagers ? "" : (state.answer_revealed ? (state.revealed_answer || "") : (state.status === "daily_double_intro" ? "DAILY DOUBLE" : (clue.clue || "")));
  const buzzerState = document.getElementById("buzzerState");
  if (state.answer_revealed) buzzerState.textContent = "CORRECT RESPONSE";
  else if (waitingForFinalWagers) buzzerState.textContent = "FINAL JEOPARDY";
  else if (state.first_buzzer_name) buzzerState.textContent = `${state.first_buzzer_name} BUZZED FIRST!`;
  else if (state.buzzer_open) buzzerState.textContent = "BUZZERS OPEN";
  else if (state.status === "clue_complete") buzzerState.textContent = "CLUE COMPLETE";
  else buzzerState.textContent = "BUZZERS CLOSED";
  renderFinalReveals(state);
}

function renderFinalReveals(state) {
  const list = document.getElementById("finalRevealList");
  const reveals = state.status === "final" ? (state.final_reveals || []) : [];
  list.classList.toggle("hidden", reveals.length === 0);
  list.innerHTML = reveals.map(entry => `
    <div class="final-reveal-row">
      <strong>${escapeHtml(entry.player.name)}</strong>
      ${entry.revealed_wager ? `<span>Wager: $${entry.wager}</span>` : ""}
      ${entry.revealed_answer ? `<span>Response: ${escapeHtml(entry.answer || "")}</span>` : ""}
    </div>
  `).join("");
}

function renderRankings(state) {
  document.getElementById("scoreboardTitle").textContent = state.status === "final_standings" ? "Final Standings" : "Scoreboard";
  document.getElementById("rankings").innerHTML = state.players.map((p, i) => `
    <div class="ranking-row"><span>${i + 1}. ${escapeHtml(p.name)}</span><strong>$${p.score}</strong></div>
  `).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}
