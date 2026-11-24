(function () {
  let muted = localStorage.getItem("jeopardyMuted") === "true";
  let ctx = null;

  function context() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    return ctx;
  }

  function unlock() {
    if (window.AudioContext || window.webkitAudioContext) context().resume().catch(() => {});
  }

  document.addEventListener("pointerdown", unlock, { once: true });
  document.addEventListener("keydown", unlock, { once: true });

  function tone(freq, duration, type, gainValue) {
    if (muted || !(window.AudioContext || window.webkitAudioContext)) return;
    const c = context();
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.frequency.value = freq;
    osc.type = type || "sine";
    gain.gain.value = gainValue || 0.08;
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.001, c.currentTime + duration);
    osc.stop(c.currentTime + duration);
  }

  window.JeopardyAudio = {
    setMuted(value) {
      muted = Boolean(value);
      localStorage.setItem("jeopardyMuted", muted ? "true" : "false");
    },
    isMuted() {
      return muted;
    },
    play(name) {
      if (name === "open") tone(660, 0.18, "triangle", 0.07);
      else if (name === "buzz") tone(180, 0.28, "sawtooth", 0.06);
      else if (name === "correct") { tone(523, 0.13); setTimeout(() => tone(784, 0.16), 120); }
      else if (name === "incorrect") tone(110, 0.35, "square", 0.04);
      else if (name === "timeout") tone(260, 0.6, "triangle", 0.18);
      else if (name === "daily") { tone(392, 0.14); setTimeout(() => tone(523, 0.14), 130); setTimeout(() => tone(659, 0.25), 260); }
      else if (name === "final") { tone(330, 0.2); setTimeout(() => tone(294, 0.2), 210); setTimeout(() => tone(262, 0.35), 420); }
    }
  };
})();
