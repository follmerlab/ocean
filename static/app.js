// Flame Spectrometer UI. Plain JS, no build step.
const PALETTE = ["#000000", "#D62728", "#1F4E9E", "#6B7FA3", "#E07B00", "#555555", "#14336B", "#9DB3D9"];
const $ = (id) => document.getElementById(id);
const S = { status: null, mode: "counts", wl: null, frame: null, live: false, livePoll: null,
            runPoll: null, since: 0, runT: [], runY: [], tracesNm: [], events: [] };

// ------------------------------------------------------------------ api
async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" },
                                           body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  const j = await r.json();
  if (!j.success) throw new Error(j.error || "request failed");
  return j;
}
function banner(msg, kind = "error") {
  const b = $("banner");
  b.textContent = msg || "";
  b.className = "banner" + (msg ? "" : " hidden") + (kind === "warn" ? " warn" : "");
}
async function act(fn) {
  try { banner(""); return await fn(); } catch (e) { banner(e.message); }
}

// ------------------------------------------------------------------ plots
const FONT = { family: "Arial, Helvetica, sans-serif", size: 13, color: "#000" };
function axis(title, extra = {}) {
  return { title: { text: `<b>${title}</b>`, font: { size: 14 } }, showline: true, linecolor: "#000",
           linewidth: 1, mirror: true, ticks: "outside", tickcolor: "#000", showgrid: false,
           zeroline: false, ...extra };
}
function layout(xt, yt, extra = {}) {
  return { font: FONT, margin: { l: 70, r: 20, t: 10, b: 55 }, paper_bgcolor: "#fff", plot_bgcolor: "#fff",
           xaxis: axis(xt), yaxis: axis(yt), showlegend: false, hovermode: "closest", ...extra };
}
const CONFIG = { responsive: true, displaylogo: false,
                 modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
                 toImageButtonOptions: { format: "svg", filename: "spectrum" } };
const yTitle = () => ({ counts: "Counts", absorbance: "Absorbance", transmittance: "Transmittance (%)" })[S.mode];

function signal(frame) {
  if (!frame) return null;
  if (S.mode === "counts") return frame.counts;
  if (!frame.absorbance) return null;
  if (S.mode === "absorbance") return frame.absorbance;
  return frame.absorbance.map((a) => (a === null ? null : 100 * Math.pow(10, -a)));
}

function drawSpectrum() {
  const f = S.frame;
  const y = signal(f);
  const traces = [];
  if (f && y) traces.push({ x: f.wavelengths, y, mode: "lines", line: { color: "#000", width: 1.2 },
                            hovertemplate: "%{x:.1f} nm<br>%{y:.4g}<extra></extra>" });
  const shapes = S.tracesNm.map((nm, i) => ({ type: "line", x0: nm, x1: nm, yref: "paper", y0: 0, y1: 1,
                                              line: { color: PALETTE[i % PALETTE.length], width: 1, dash: "dot" } }));
  const L = layout("Wavelength (nm)", yTitle(), { shapes, uirevision: S.mode + (y ? ":data" : ":empty") });
  const dev = S.status && S.status.device;
  if (!f) {
    if (dev) L.xaxis.range = dev.wl_range;
    L.yaxis.showticklabels = false;
    L.annotations = [{ text: "Press <b>Capture</b> or <b>Start live</b>", xref: "paper", yref: "paper",
                       x: 0.5, y: 0.5, showarrow: false, font: { size: 15, color: "#666" } }];
  }
  if (f && !y && S.mode !== "counts") L.annotations = [{ text: "Take a reference to see absorbance", xref: "paper",
    yref: "paper", x: 0.5, y: 0.5, showarrow: false, font: { size: 15, color: "#666" } }];
  Plotly.react("plot-spectrum", traces, L, CONFIG);
  if (f) {
    const sat = f.saturated ? "  SATURATED" : "";
    $("readout").textContent = `max ${Math.round(f.max_counts).toLocaleString()} counts${sat}`;
    $("readout").style.color = f.saturated ? "#D62728" : "";
  }
}

function drawTraces() {
  const ys = S.tracesNm.map((nm, i) => ({
    x: S.runT, y: S.runY.map((row) => row[i]), mode: "lines", name: `${nm} nm`,
    line: { color: PALETTE[i % PALETTE.length], width: 1.5 },
    hovertemplate: `${nm} nm<br>t = %{x:.3f} s<br>%{y:.4g}<extra></extra>` }));
  const shapes = S.events.map((e) => ({ type: "line", x0: e.t_s, x1: e.t_s, yref: "paper", y0: 0, y1: 1,
                                        line: { color: "#999", width: 1, dash: "dash" } }));
  const annotations = S.events.map((e) => ({ x: e.t_s, yref: "paper", y: 1, yanchor: "bottom", text: e.label,
                                             showarrow: false, font: { size: 11, color: "#666" } }));
  const hasRef = S.status && S.status.reference && S.status.reference.valid;
  const L = layout("Time (s)", hasRef ? "Absorbance" : "Counts", {
    shapes, annotations, showlegend: S.tracesNm.length > 0, uirevision: S.runT.length ? "traces" : "empty",
    margin: { l: 70, r: 20, t: 24, b: 55 },
    legend: { orientation: "h", x: 0, y: -0.22, font: { size: 12 } } });
  if (!S.runT.length) placeholder(L, S.runPoll ? "Waiting for t = 0" : "Kinetic traces appear here");
  Plotly.react("plot-traces", ys, L, CONFIG);
}

function drawLatest(latest) {
  const traces = latest && S.wl ? [{ x: S.wl, y: latest.y, mode: "lines", line: { color: "#000", width: 1 } }] : [];
  const yt = latest ? (latest.kind === "absorbance" ? "Absorbance" : "Counts") : "Signal";
  const L = layout("Wavelength (nm)", yt, {
    uirevision: latest ? "latest:" + latest.kind : "empty", margin: { l: 70, r: 20, t: 24, b: 55 },
    title: { text: latest ? `Latest spectrum · t = ${latest.t.toFixed(3)} s` : "", font: { size: 12 },
             x: 0.98, xanchor: "right", y: 0.98 } });
  if (!latest) placeholder(L, "Latest spectrum appears here during a run");
  Plotly.react("plot-latest", traces, L, CONFIG);
}
function placeholder(L, text) {
  L.xaxis.showticklabels = L.yaxis.showticklabels = false;
  L.annotations = [...(L.annotations || []), { text, xref: "paper", yref: "paper", x: 0.5, y: 0.5,
                                               showarrow: false, font: { size: 14, color: "#666" } }];
}

// ------------------------------------------------------------------ status
function fmtBg(bg) {
  if (!bg) return ["none", "muted"];
  const t = bg.taken.slice(11, 16);
  const it = `${+(bg.integration_s * 1000).toPrecision(4)} ms`;
  return bg.valid ? [`${t} · ${it}`, "ok"] : [`stale: taken at ${it}`, "bad"];
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    S.status = s;
    $("dev-dot").className = "dot" + (s.connected ? " on" : "");
    $("dev-label").textContent = s.connected
      ? `${s.device.model} · ${s.device.serial}${s.mock ? " (simulated)" : ""}` : (s.error || "Not connected");
    $("data-dir").textContent = s.data_dir; $("data-dir").title = s.data_dir;
    if (s.connected && document.activeElement !== $("it-ms"))
      $("it-ms").value = +(s.integration_s * 1000).toPrecision(6);
    if (document.activeElement !== $("n-avg")) $("n-avg").value = s.n_avg;
    for (const [key, el] of [["dark", "dark-status"], ["reference", "ref-status"]]) {
      const [txt, cls] = fmtBg(s[key]);
      $(el).textContent = txt; $(el).className = cls;
    }
    $("run-h5").disabled = !s.hdf5_available;
    $("btn-save").disabled = !s.has_last;
    const lock = s.busy || !s.connected;
    for (const id of ["it-ms", "n-avg", "btn-live", "btn-capture", "btn-dark", "btn-ref"]) $(id).disabled = lock;
    $("btn-connect").disabled = s.busy;
    S.live = s.live;
    $("btn-live").textContent = s.live ? "Stop live" : "Start live";
    $("btn-live").className = s.live ? "danger" : "primary";
    if (s.live && !S.livePoll) S.livePoll = setInterval(pollLive, 200);
    if (!s.live && S.livePoll) { clearInterval(S.livePoll); S.livePoll = null; }
    if (s.busy && !S.runPoll) startRunPolling();
    updateChecklist();
    if (!S.frame && !S.drawnEmpty && s.device) { S.drawnEmpty = true; drawSpectrum(); }
  } catch (e) { banner("Lost contact with the server: " + e.message); }
}

async function pollLive() {
  try {
    const j = await api("/api/live");
    if (j.data && j.data.error) return banner(j.data.error);
    if (j.data) { S.frame = j.data; S.wl = j.data.wavelengths; drawSpectrum(); }
  } catch (e) { /* transient */ }
}

// ------------------------------------------------------------------ kinetics
function parseTraces() {
  return $("run-traces").value.split(/[,\s]+/).map(Number).filter((x) => x > 0).slice(0, 8);
}
function runConfig() {
  return { name: $("run-name").value.trim() || "kinetics", notes: $("run-notes").value,
           delay_s: +$("run-delay").value || 0, duration_s: +$("run-duration").value || 0,
           interval_s: +$("run-interval").value || 0, n_avg: Math.max(1, +$("run-avg").value || 1),
           traces_nm: parseTraces(), half_width_nm: +$("run-hw").value || 0, save_hdf5: $("run-h5").checked };
}

function updateChecklist() {
  const s = S.status; if (!s) return;
  const c = runConfig();
  const it = s.integration_s || 0;
  const items = [];
  items.push([s.connected ? "ok" : "bad", s.connected ? "Spectrometer connected" : "Spectrometer not connected"]);
  items.push(["ok", `Integration ${+(it * 1000).toPrecision(4)} ms`]);
  const d = s.dark, r = s.reference;
  items.push([!d ? "warn" : d.valid ? "ok" : "bad", !d ? "No dark (raw counts will be saved)" : d.valid ? "Dark set" : "Dark is stale: retake"]);
  items.push([!r ? "warn" : r.valid ? "ok" : "bad", !r ? "No reference (no absorbance)" : r.valid ? "Reference set: absorbance" : "Reference is stale: retake"]);
  items.push([c.traces_nm.length ? "ok" : "warn", c.traces_nm.length ? `Traces at ${c.traces_nm.join(", ")} nm` : "No trace wavelengths (spectra still saved)"]);
  $("checklist").innerHTML = items.map(([k, t]) => `<li class="${k}">${t}</li>`).join("");

  const frame = Math.max(it * c.n_avg, 1e-3);
  const period = Math.max(c.interval_s, frame);
  if (c.duration_s > 0 && it) {
    const n = Math.floor(c.duration_s / period);
    const mb = (n * 2048 * (r && r.valid ? 16 : 8)) / 1e6;
    $("estimate").textContent = `≈ ${n.toLocaleString()} spectra at ${(1 / period).toPrecision(3)} Hz · ~${mb < 1 ? mb.toFixed(1) : Math.round(mb)} MB CSV`;
  } else $("estimate").textContent = it ? `${(1 / period).toPrecision(3)} Hz until you press Stop` : "";
  if (!S.runPoll) $("btn-run").disabled = !s.connected || (d && !d.valid) || (r && !r.valid);
}

function fmtClock(sec) {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  return m ? `${m}:${(s % 60).toFixed(1).padStart(4, "0")}` : s.toFixed(1);
}

const FORM = ["run-name", "run-delay", "run-duration", "run-interval", "run-avg", "run-traces", "run-hw", "run-notes", "run-h5"];
function fillForm(c) {
  $("run-name").value = c.name; $("run-notes").value = c.notes; $("run-delay").value = c.delay_s;
  $("run-duration").value = c.duration_s; $("run-interval").value = c.interval_s; $("run-avg").value = c.n_avg;
  $("run-traces").value = c.traces_nm.join(", "); $("run-hw").value = c.half_width_nm; $("run-h5").checked = c.save_hdf5;
  updateChecklist();
}
function lockForm(on) { for (const id of FORM) $(id).disabled = on; }

function startRunPolling() {
  S.since = 0; S.runT = []; S.runY = []; S.events = []; lockForm(true);
  $("btn-run").textContent = "Stop run"; $("btn-run").className = "danger wide big"; $("btn-run").disabled = false;
  $("btn-mark").disabled = false;
  S.runPoll = setInterval(pollRun, 250);
}

async function pollRun() {
  let run;
  try { run = (await api(`/api/run/status?since=${S.since}`)).run; } catch (e) { return; }
  if (!run) return;
  if (S.since === 0) {
    S.tracesNm = run.traces_nm;
    if (run.wavelengths) S.wl = run.wavelengths;
    fillForm(run.config);
  }
  S.runT.push(...run.t); S.runY.push(...run.y); S.since += run.t.length; S.events = run.events;
  const clock = $("clock");
  if (run.state === "countdown") {
    clock.textContent = fmtClock(run.countdown_s); clock.className = "clock countdown";
    $("clock-label").textContent = "starts in";
  } else {
    clock.textContent = fmtClock(run.elapsed_s); clock.className = "clock running";
    $("clock-label").textContent = { running: "elapsed", saving: "writing files…", done: "finished",
                                     aborted: "stopped", error: "error" }[run.state];
  }
  const sat = run.saturated_frames ? ` · <span class="bad">${run.saturated_frames} saturated</span>` : "";
  const folder = run.folder.split(/[\\/]/).pop();
  $("run-msg").innerHTML = `${run.n.toLocaleString()} spectra${sat}<br>Folder: <code title="${run.folder}">${folder}</code>`;
  if (run.latest) drawLatest(run.latest);
  drawTraces();
  if (["done", "aborted", "error"].includes(run.state)) {
    clearInterval(S.runPoll); S.runPoll = null;
    $("btn-run").textContent = "Start run"; $("btn-run").className = "primary wide big";
    $("btn-mark").disabled = true; lockForm(false);
    if (run.error) banner("Run failed: " + run.error);
    refreshStatus();
  }
}

async function toggleRun() {
  if (S.runPoll) return act(() => api("/api/run/stop", {}));
  await act(async () => {
    if (!S.wl) S.wl = (await api("/api/capture", {})).data.wavelengths;
    await api("/api/run/start", runConfig());
    S.tracesNm = runConfig().traces_nm;
    drawLatest(null);
    startRunPolling();
    refreshStatus();
  });
}

async function mark() {
  if (!S.runPoll) return;
  await act(async () => {
    const ev = (await api("/api/run/mark", { label: $("mark-label").value.trim() })).event;
    $("run-msg").insertAdjacentHTML("afterbegin", `<div>Marked “${ev.label}” at ${ev.t_s.toFixed(3)} s</div>`);
  });
}

// ------------------------------------------------------------------ wiring
async function applySettings() {
  await act(async () => {
    await api("/api/settings", { integration_ms: +$("it-ms").value, n_avg: +$("n-avg").value });
    refreshStatus();
  });
}

async function takeBackground(kind) {
  await act(async () => {
    const j = await api(`/api/${kind}`, {});
    if (j.saturated) banner(`${kind === "dark" ? "Dark" : "Reference"} is saturated: lower the integration time.`, "warn");
    refreshStatus();
  });
}

function addTrace(nm) {
  const cur = parseTraces();
  if (cur.length >= 8) return;
  cur.push(Math.round(nm));
  $("run-traces").value = cur.join(", ");
  S.tracesNm = cur; drawSpectrum(); updateChecklist();
}

function init() {
  $("btn-connect").onclick = () => act(async () => { await api("/api/connect", {}); refreshStatus(); });
  $("it-ms").onchange = applySettings;
  $("n-avg").onchange = applySettings;
  $("btn-live").onclick = () => act(async () => { await api(`/api/live/${S.live ? "stop" : "start"}`, {}); refreshStatus(); });
  $("btn-capture").onclick = () => act(async () => {
    const j = await api("/api/capture", {});
    S.frame = j.data; S.wl = j.data.wavelengths; drawSpectrum(); refreshStatus();
    if (j.data.saturated) banner("Detector saturated: lower the integration time.", "warn");
  });
  $("btn-dark").onclick = () => takeBackground("dark");
  $("btn-ref").onclick = () => takeBackground("reference");
  $("btn-dark-clear").onclick = () => act(async () => { await api("/api/clear/dark", {}); refreshStatus(); });
  $("btn-ref-clear").onclick = () => act(async () => { await api("/api/clear/reference", {}); refreshStatus(); });
  $("btn-save").onclick = () => act(async () => {
    const j = await api("/api/save", { name: $("spec-name").value.trim() || "spectrum", notes: $("spec-notes").value });
    $("save-msg").innerHTML = `Saved <code>${j.file.split(/[\\/]/).pop()}</code>`;
  });
  document.querySelectorAll("#mode button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll("#mode button").forEach((x) => x.classList.toggle("on", x === b));
    S.mode = b.dataset.mode; drawSpectrum();
  }));
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    for (const t of ["spectrum", "kinetics"]) $("tab-" + t).classList.toggle("hidden", t !== b.dataset.tab);
    history.replaceState(null, "", "#" + b.dataset.tab);
    window.dispatchEvent(new Event("resize"));
  }));
  if (location.hash === "#kinetics") document.querySelector('.tabs [data-tab="kinetics"]').click();
  for (const id of ["run-delay", "run-duration", "run-interval", "run-avg", "run-traces", "run-hw"])
    $(id).addEventListener("input", () => { if (id === "run-traces") { S.tracesNm = parseTraces(); drawSpectrum(); } updateChecklist(); });
  $("btn-run").onclick = toggleRun;
  $("btn-mark").onclick = mark;
  $("mark-label").addEventListener("keydown", (e) => { if (e.key === "Enter") mark(); });
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "m" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) mark();
  });

  drawSpectrum(); drawTraces(); drawLatest(null);
  document.getElementById("plot-spectrum").on("plotly_click", (ev) => addTrace(ev.points[0].x));
  refreshStatus();
  setInterval(refreshStatus, 1500);
}
init();
