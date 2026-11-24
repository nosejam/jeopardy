window.roomReconnect = function (connect, onStop) {
  let attempts = 0;
  return {
    connected() {
      attempts = 0;
    },
    disconnected(event) {
      if (event.code === 4004 || event.code === 1008 || attempts >= 6) {
        onStop(event);
        return;
      }
      setTimeout(connect, 1000 * 2 ** attempts);
      attempts += 1;
    }
  };
};

window.showRoomUnavailable = function (message, canCreateGame = false) {
  const panel = document.createElement("main");
  panel.className = "room-unavailable";
  const heading = document.createElement("h1");
  heading.textContent = message;
  panel.append(heading);
  if (canCreateGame) {
    const link = document.createElement("a");
    link.className = "choice-button primary";
    link.href = "/display";
    link.textContent = "Start a new game";
    panel.append(link);
  }
  document.body.replaceChildren(panel);
};
