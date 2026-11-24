const joinPanel = document.getElementById("joinPanel");
const gamePanel = document.getElementById("gamePanel");
const joinForm = document.getElementById("joinForm");
const joinTeamList = document.getElementById("joinTeamList");
const nameInput = document.getElementById("nameInput");
const buzzButton = document.getElementById("buzzButton");
const normalPanel = document.getElementById("normalPanel");
const cluePicker = document.getElementById("cluePicker");
const cluePickerBoard = document.getElementById("cluePickerBoard");
const updateClueTimer = createClueTimer(document.getElementById("playerClueTimer"));
const finalPanel = document.getElementById("finalPanel");
const wagerForm = document.getElementById("wagerForm");
const answerForm = document.getElementById("answerForm");
const gameBase = `/g/${window.JEOPARDY_GAME_CODE}`;
const playerIdKey = `jeopardyPlayerId:${window.JEOPARDY_GAME_CODE}`;
const playerNameKey = `jeopardyPlayerName:${window.JEOPARDY_GAME_CODE}`;
let socket = null;
let playerId = localStorage.getItem(playerIdKey) || "";
let playerName = localStorage.getItem(playerNameKey) || "";
let reconnectTimer = null;
let joined = false;

nameInput.value = playerName;
if (playerName) connect();
loadJoinTeams();
setInterval(() => {
  if (!joined) loadJoinTeams();
}, 2500);

joinForm.addEventListener("submit", (event) => {
  event.preventDefault();
  playerName = nameInput.value.trim();
  playerId = "";
  localStorage.removeItem(playerIdKey);
  localStorage.setItem(playerNameKey, playerName);
  connect();
});

buzzButton.addEventListener("click", () => send({ action: "buzz" }));
wagerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  send({ action: "final_wager", wager: document.getElementById("wagerInput").value || 0 });
});
answerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  send({ action: "final_answer", answer: document.getElementById("finalAnswerInput").value || "" });
  document.getElementById("finalAnswerInput").value = "";
});

function connect() {
  if (!playerName) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ name: playerName });
  if (playerId) params.set("player_id", playerId);
  socket = new WebSocket(`${protocol}://${location.host}${gameBase}/ws/player?${params}`);
  joinPanel.classList.add("hidden");
  gamePanel.classList.remove("hidden");
  joined = true;
  setConnection("Connecting");

  socket.onopen = () => setConnection("Connected");
  socket.onclose = () => {
    setConnection("Disconnected");
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 1200);
  };
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "joined") {
      playerId = message.player_id;
      localStorage.setItem(playerIdKey, playerId);
    }
    if (message.type === "state") render(message.state);
    if (message.type === "error") document.getElementById("buzzMessage").textContent = message.message;
  };
}

async function loadJoinTeams() {
  try {
    const response = await fetch(`${gameBase}/api/state`);
    const state = await response.json();
    const players = state.players || [];
    joinTeamList.innerHTML = players.length ? players.map(player => (
      `<button type="button" data-join-team="${escapeHtml(player.id)}" data-team-name="${escapeHtml(player.name)}">${escapeHtml(player.name)}</button>`
    )).join("") : `<p class="muted">No teams yet.</p>`;
    joinTeamList.querySelectorAll("[data-join-team]").forEach(button => {
      button.addEventListener("click", () => joinTeam(button.dataset.joinTeam, button.dataset.teamName));
    });
  } catch {
    joinTeamList.innerHTML = `<p class="muted">Teams unavailable.</p>`;
  }
}

function joinTeam(teamId, teamName) {
  playerId = teamId;
  playerName = teamName;
  localStorage.setItem(playerIdKey, playerId);
  localStorage.setItem(playerNameKey, playerName);
  nameInput.value = playerName;
  connect();
}

function send(payload) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

function setConnection(text) {
  document.getElementById("connectionStatus").textContent = text;
}

function render(state) {
  const me = state.me || {};
  document.getElementById("playerName").textContent = me.name || playerName;
  document.getElementById("playerScore").textContent = me.score ?? 0;

  const isFinal = state.status === "final";
  cluePicker.classList.toggle("hidden", !state.can_pick_clue);
  if (state.can_pick_clue) renderCluePicker(state);
  normalPanel.classList.toggle("hidden", isFinal || state.can_pick_clue);
  finalPanel.classList.toggle("hidden", !isFinal);
  updateClueTimer(state);
  renderNormal(state);
  renderFinal(state);
}

function renderCluePicker(state) {
  cluePickerBoard.replaceChildren();
  for (const [category, clues] of Object.entries(state.board)) {
    const remaining = clues.filter(clue => !clue.used);
    if (!remaining.length) continue;
    const row = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = category;
    row.append(heading);
    const values = document.createElement("div");
    values.className = "clue-picker-values";
    for (const clue of remaining) {
      const button = document.createElement("button");
      button.textContent = "$" + clue.value;
      button.setAttribute("aria-label", category + ", " + button.textContent);
      button.addEventListener("click", () => send({
        action: "select_clue", clue_id: clue.id, board_number: state.board_number
      }));
      values.append(button);
    }
    row.append(values);
    cluePickerBoard.append(row);
  }
  if (!cluePickerBoard.childElementCount) cluePickerBoard.textContent = "No clues left in this round.";
}

function renderNormal(state) {
  const clue = state.current_clue;
  document.getElementById("currentCategory").textContent = clue ? clue.category : "Waiting";
  document.getElementById("currentValue").textContent = clue && clue.value ? `$${clue.value}` : "";
  document.getElementById("currentClue").textContent = clue ? clue.clue : "Wait for the host to select a clue.";

  buzzButton.disabled = !state.eligible_to_buzz;
  buzzButton.textContent = state.eligible_to_buzz ? "BUZZ" : "WAIT";

  const message = document.getElementById("buzzMessage");
  if (state.first_buzzer === playerId) {
    message.textContent = "YOU BUZZED FIRST";
    buzzButton.textContent = "BUZZED";
  } else if (state.first_buzzer_name) {
    message.textContent = `${state.first_buzzer_name} BUZZED FIRST`;
  } else if (state.locked_out && state.locked_out.includes(playerId)) {
    message.textContent = "Locked out for this clue";
  } else if (state.buzzer_open) {
    message.textContent = "Buzzers are open";
  } else {
    message.textContent = "Buzzers are closed";
  }
}

function renderFinal(state) {
  document.getElementById("finalCategory").textContent = state.final_category || "";
  const finalStatus = document.getElementById("finalStatus");
  wagerForm.classList.toggle("hidden", state.final_phase !== "wagers" || state.final_wager_submitted);
  answerForm.classList.toggle("hidden", state.final_phase !== "answers" || state.final_answer_submitted);
  if (state.final_phase === "wagers") {
    finalStatus.textContent = state.final_wager_submitted ? "Wager submitted." : "Enter your wager.";
  } else if (state.final_phase === "answers") {
    const clue = state.current_clue;
    document.getElementById("finalClueText").textContent = clue ? clue.clue : "";
    finalStatus.textContent = state.final_answer_submitted ? "Response submitted." : "Enter your response.";
  } else {
    finalStatus.textContent = "";
  }
}
