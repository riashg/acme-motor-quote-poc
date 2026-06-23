"use strict";

// ACME Motor Quote — live operational dashboard.
// Connects to the platform's SSE endpoint (same origin) and renders four
// live views: Event Timeline, Quote Sessions, Tool Activity, API Activity.

const state = {
  events: [],            // all events, in arrival order
  sessions: new Map(),   // quoteId -> { quoteId, journeyState, status, count, ts, seq }
};

// ----- helpers -------------------------------------------------------------

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toLocaleTimeString(undefined, { hour12: false }) +
    "." + String(d.getMilliseconds()).padStart(3, "0");
}

function el(tag, opts = {}) {
  const n = document.createElement(tag);
  if (opts.class) n.className = opts.class;
  if (opts.text != null) n.textContent = opts.text;
  if (opts.html != null) n.innerHTML = opts.html;
  return n;
}

function peek(value, max = 240) {
  let s;
  try { s = typeof value === "string" ? value : JSON.stringify(value); }
  catch { s = String(value); }
  if (s == null) return "";
  return s.length > max ? s.slice(0, max) + "…" : s;
}

function badge(category) {
  const b = el("span", { class: `badge badge--${category}`, text: category });
  return b;
}

// ----- session derivation --------------------------------------------------

// Extract a quoteId from a QUOTE_* event payload (it may live at several keys).
function quoteIdOf(payload) {
  if (!payload || typeof payload !== "object") return null;
  return payload.quoteId || payload.quote_id || payload.id || null;
}

function updateSessions(ev) {
  if (ev.category !== "domain") return;
  if (ev.type !== "QUOTE_CREATED" && ev.type !== "QUOTE_UPDATED") return;
  const qid = quoteIdOf(ev.payload);
  if (!qid) return;

  let s = state.sessions.get(qid);
  if (!s) {
    s = { quoteId: qid, journeyState: "", status: "", count: 0, ts: ev.ts, seq: ev.seq };
    state.sessions.set(qid, s);
  }
  s.count += 1;
  s.ts = ev.ts;
  s.seq = ev.seq;
  const p = ev.payload || {};
  if (p.journeyState != null) s.journeyState = p.journeyState;
  if (p.status != null) s.status = p.status;
  if (p.currentOutcome != null) s.status = s.status || p.currentOutcome;
}

// ----- rendering -----------------------------------------------------------

function renderTimelineRow(ev, isNew) {
  const tr = el("tr", { class: isNew ? "row-new" : "" });
  tr.appendChild(el("td", { class: "mono", text: ev.seq }));
  tr.appendChild(el("td", { class: "mono", text: fmtTime(ev.ts) }));
  const cat = el("td"); cat.appendChild(badge(ev.category)); tr.appendChild(cat);
  tr.appendChild(el("td", { class: "type", text: ev.type }));
  tr.appendChild(el("td", { html: `<span class="payload">${escapeHtml(peek(ev.payload))}</span>` }));
  return tr;
}

function renderToolRow(ev, isNew) {
  const tr = el("tr", { class: isNew ? "row-new" : "" });
  tr.appendChild(el("td", { class: "mono", text: ev.seq }));
  tr.appendChild(el("td", { class: "mono", text: fmtTime(ev.ts) }));
  tr.appendChild(el("td", { class: "type", text: ev.type }));
  tr.appendChild(el("td", { html: `<span class="payload">${escapeHtml(peek(ev.payload))}</span>` }));
  return tr;
}

function renderApiRow(ev, isNew) {
  const p = ev.payload || {};
  const tr = el("tr", { class: isNew ? "row-new" : "" });
  tr.appendChild(el("td", { class: "mono", text: ev.seq }));
  tr.appendChild(el("td", { class: "mono", text: fmtTime(ev.ts) }));
  tr.appendChild(el("td", { class: "type", text: p.api != null ? p.api : ev.type }));
  tr.appendChild(el("td", { html: `<span class="payload">${escapeHtml(peek(p.request))}</span>` }));
  tr.appendChild(el("td", { html: `<span class="payload">${escapeHtml(peek(p.response))}</span>` }));
  return tr;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function prependRow(tbodyId, emptyId, row) {
  const body = document.getElementById(tbodyId);
  document.getElementById(emptyId).style.display = "none";
  body.insertBefore(row, body.firstChild);
}

function renderSessions() {
  const body = document.getElementById("sessions-body");
  const empty = document.getElementById("sessions-empty");
  const rows = [...state.sessions.values()].sort((a, b) => b.seq - a.seq);
  body.innerHTML = "";
  if (rows.length === 0) { empty.style.display = ""; return; }
  empty.style.display = "none";
  for (const s of rows) {
    const tr = el("tr");
    tr.appendChild(el("td", { class: "mono", text: s.quoteId }));
    tr.appendChild(el("td", { text: [s.journeyState, s.status].filter(Boolean).join(" / ") || "—" }));
    tr.appendChild(el("td", { class: "mono", text: s.count }));
    tr.appendChild(el("td", { class: "mono", text: fmtTime(s.ts) }));
    body.appendChild(tr);
  }
}

// Apply a single event to all relevant views.
function ingest(ev, isNew) {
  state.events.push(ev);
  document.getElementById("event-count").textContent = `${state.events.length} events`;

  prependRow("timeline-body", "timeline-empty", renderTimelineRow(ev, isNew));

  if (ev.category === "tool") {
    prependRow("tools-body", "tools-empty", renderToolRow(ev, isNew));
  }
  if (ev.category === "api") {
    prependRow("api-body", "api-empty", renderApiRow(ev, isNew));
  }

  updateSessions(ev);
  renderSessions();
}

// ----- connection ----------------------------------------------------------

function setConn(status) {
  const dot = document.getElementById("conn-dot");
  const text = document.getElementById("conn-text");
  dot.className = "dot " + (
    status === "live" ? "dot--on" : status === "connecting" ? "dot--wait" : "dot--off"
  );
  text.textContent =
    status === "live" ? "live" : status === "connecting" ? "connecting…" : "disconnected — retrying";
}

let firstBatch = true;

function connect() {
  setConn("connecting");
  const es = new EventSource("/events");

  es.onopen = () => setConn("live");

  es.onmessage = (msg) => {
    let ev;
    try { ev = JSON.parse(msg.data); }
    catch { return; }
    // The server replays history on connect, then tails live. Flash only
    // genuinely new rows (everything after the initial replay batch).
    ingest(ev, !firstBatch);
  };

  // History replay arrives back-to-back; after a short quiet period we treat
  // subsequent events as live (so they get the flash highlight).
  let quietTimer = setInterval(() => {
    if (es.readyState === EventSource.OPEN) { firstBatch = false; clearInterval(quietTimer); }
  }, 800);

  es.onerror = () => {
    setConn("disconnected");
    // EventSource auto-reconnects, but if the connection is closed we rebuild
    // it ourselves after a short backoff (and reset views to avoid dupes).
    if (es.readyState === EventSource.CLOSED) {
      clearInterval(quietTimer);
      setTimeout(reconnect, 2000);
    }
  };
}

function reconnect() {
  // Clear current state; the new connection replays full history.
  state.events = [];
  state.sessions.clear();
  firstBatch = true;
  for (const id of ["timeline-body", "tools-body", "api-body", "sessions-body"]) {
    document.getElementById(id).innerHTML = "";
  }
  for (const id of ["timeline-empty", "tools-empty", "api-empty", "sessions-empty"]) {
    document.getElementById(id).style.display = "";
  }
  document.getElementById("event-count").textContent = "0 events";
  connect();
}

// ----- tabs ----------------------------------------------------------------

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("tab--active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("panel--active"));
    btn.classList.add("tab--active");
    document.getElementById("panel-" + btn.dataset.tab).classList.add("panel--active");
  });
});

connect();
