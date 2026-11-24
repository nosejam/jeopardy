window.createClueTimer = function (element, { sound = false } = {}) {
  let deadline = null;
  let label = "";
  let interval = null;
  let soundedResponse = null;

  function draw() {
    const seconds = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
    element.textContent = label + " " + seconds + "s";
  }

  return function update(state) {
    clearInterval(interval);
    element.hidden = state.timer_remaining == null && !state.response_expired;
    if (state.response_expired) {
      element.textContent = "Time's up";
      if (sound && soundedResponse !== state.response_number) {
        soundedResponse = state.response_number;
        window.JeopardyAudio?.play("timeout");
      }
    } else if (!element.hidden) {
      label = state.buzzer_open ? "Buzz in" : "Respond";
      deadline = performance.now() + state.timer_remaining * 1000;
      draw();
      interval = setInterval(() => {
        draw();
        if (performance.now() >= deadline) clearInterval(interval);
      }, 100);
    }
  };
};
