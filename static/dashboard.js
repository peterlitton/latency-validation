(() => {
  "use strict";

  const rowsEl = document.getElementById("rows");
  const liveCountEl = document.getElementById("live-count");
  const upcomingCountEl = document.getElementById("upcoming-count");
  const clockEl = document.getElementById("clock");
  const apiTennisAgeEl = document.getElementById("api-tennis-age");
  const apiTennisDotEl = document.getElementById("api-tennis-dot");
  const polymarketAgeEl = document.getElementById("polymarket-age");
  const polymarketDotEl = document.getElementById("polymarket-dot");

  // Liveness color thresholds (Design Notes §8). Initial guesses; TBD
  // after first session of use.
  const API_TENNIS_YELLOW_MS = 30 * 1000;
  const API_TENNIS_RED_MS = 90 * 1000;
  const POLYMARKET_YELLOW_MS = 10 * 1000;
  const POLYMARKET_RED_MS = 30 * 1000;

  // Latest source timestamps from the most recent WS/REST snapshot.
  // These are what the liveness counters tick against, NOT the
  // backend-to-frontend snapshot cadence.
  let sourceTimestamps = {api_tennis: null, polymarket: null};

  // ---------- clock ----------
  function tickClock() {
    const d = new Date();
    let h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, "0");
    const s = String(d.getSeconds()).padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    clockEl.textContent = `${h}:${m}:${s} ${ampm}`;
  }
  tickClock();
  setInterval(tickClock, 1000);

  // ---------- liveness counters ----------
  function formatAge(ms) {
    if (ms == null) return "—";
    const sec = Math.max(0, Math.round(ms / 1000));
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function dotClassFor(ms, yellowMs, redMs) {
    if (ms == null) return "dot-unknown";
    if (ms >= redMs) return "dot-red";
    if (ms >= yellowMs) return "dot-yellow";
    return "dot-ok";
  }

  function tickLiveness() {
    const now = Date.now();

    const apiAge = sourceTimestamps.api_tennis == null
      ? null
      : now - sourceTimestamps.api_tennis;
    apiTennisAgeEl.textContent = formatAge(apiAge);
    apiTennisDotEl.className = "dot " + dotClassFor(apiAge, API_TENNIS_YELLOW_MS, API_TENNIS_RED_MS);

    const pmAge = sourceTimestamps.polymarket == null
      ? null
      : now - sourceTimestamps.polymarket;
    polymarketAgeEl.textContent = formatAge(pmAge);
    polymarketDotEl.className = "dot " + dotClassFor(pmAge, POLYMARKET_YELLOW_MS, POLYMARKET_RED_MS);
  }
  setInterval(tickLiveness, 500);

  // ---------- rendering ----------
  function flagSvg(iso3) {
    // Phase 1A: placeholder rect for everything. Wire in real flags
    // (downloaded from Polymarket S3 CDN per Design Notes §6) at 1B/1C.
    return `<span class="flag flag-placeholder" aria-label="${iso3 || "flag"}"></span>`;
  }

  const TENNIS_BALL = `
    <svg class="ball" viewBox="0 0 24 24" aria-label="serving">
      <circle cx="12" cy="12" r="11" fill="#D4E157"/>
      <path d="M 1.5 8 Q 12 14, 22.5 8" stroke="#FFFFFF" stroke-width="1.5" fill="none"/>
      <path d="M 1.5 16 Q 12 10, 22.5 16" stroke="#FFFFFF" stroke-width="1.5" fill="none"/>
    </svg>`;

  function setScoreHtml(sets) {
    if (!sets || sets.length === 0) return "—";
    return sets
      .map(s => s.tiebreak != null
        ? `${s.games}<sup class="tb">${s.tiebreak}</sup>`
        : `${s.games}`)
      .join(" · ");
  }

  function startTimeHtml(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    let h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${h}:${m} ${ampm}`;
  }

  function priceHtml(cents) {
    return cents == null ? "—" : `${cents}¢`;
  }

  function renderRow(m) {
    const isLive = m.status === "live";
    const p1Serves = m.server === 1;
    const p2Serves = m.server === 2;

    const statusBlock = isLive
      ? `<div class="status-live-line"><span class="dot"></span><span class="status-text">${m.set_label || ""}</span></div>
         <div class="status-meta">${m.venue} · ${m.tour} · ${m.round}</div>`
      : `<div class="status-text">${startTimeHtml(m.start_time)}</div>
         <div class="status-meta">${m.venue} · ${m.tour} · ${m.round}</div>`;

    const matchBlock = `
      <div class="player">
        ${flagSvg(m.p1.country_iso3)}
        <span class="player-name">${m.p1.name}</span>
        ${p1Serves ? TENNIS_BALL : ""}
      </div>
      <div class="player">
        ${flagSvg(m.p2.country_iso3)}
        <span class="player-name">${m.p2.name}</span>
        ${p2Serves ? TENNIS_BALL : ""}
      </div>`;

    const setsBlock = isLive
      ? `<div>${setScoreHtml(m.p1_sets)}</div><div>${setScoreHtml(m.p2_sets)}</div>`
      : `<div class="placeholder">—</div><div class="placeholder">—</div>`;

    const gameBlock = isLive
      ? `<div class="${p1Serves ? "serving" : ""}">${m.p1_game ?? ""}</div>
         <div class="${p2Serves ? "serving" : ""}">${m.p2_game ?? ""}</div>`
      : `<div class="placeholder">—</div><div class="placeholder">—</div>`;

    const priceBlock = `<div>${priceHtml(m.p1_price_cents)}</div><div>${priceHtml(m.p2_price_cents)}</div>`;

    return `
      <div class="row ${isLive ? "" : "upcoming"}">
        <div>${statusBlock}</div>
        <div>${matchBlock}</div>
        <div class="score-cell">${setsBlock}</div>
        <div class="score-cell">${gameBlock}</div>
        <div class="price-cell">${priceBlock}</div>
      </div>`;
  }

  function applySnapshot(snapshot) {
    const matches = snapshot.matches || [];
    sourceTimestamps = snapshot.source_timestamps || sourceTimestamps;

    const live = matches.filter(m => m.status === "live").length;
    const upcoming = matches.filter(m => m.status === "upcoming").length;
    liveCountEl.textContent = `${live} live`;
    upcomingCountEl.textContent = upcoming > 0 ? `+ ${upcoming} starting within 1h` : "";
    rowsEl.innerHTML = matches.map(renderRow).join("");

    // Recompute liveness immediately so the counter doesn't lag a half-second.
    tickLiveness();
  }

  // ---------- websocket ----------
  let ws;
  let reconnectDelayMs = 1000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/matches`);

    ws.addEventListener("message", evt => {
      try {
        const snapshot = JSON.parse(evt.data);
        applySnapshot(snapshot);
        reconnectDelayMs = 1000;
      } catch (e) {
        console.error("bad ws frame", e);
      }
    });

    ws.addEventListener("close", () => {
      setTimeout(connect, reconnectDelayMs);
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 15000);
    });

    ws.addEventListener("error", () => {
      try { ws.close(); } catch (_) { /* ignore */ }
    });
  }

  // Hydrate once via REST so the page has data before the first WS frame.
  fetch("/api/matches")
    .then(r => r.json())
    .then(applySnapshot)
    .catch(e => console.error("initial fetch failed", e))
    .finally(connect);
})();
