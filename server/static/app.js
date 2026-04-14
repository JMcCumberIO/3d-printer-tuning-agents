// Escape user data before inserting into the DOM.
function escHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// SSE connection
const es = new EventSource("/stream/events");
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (data.type === "ha_state")   updateStatus(data);
  if (data.type === "orca_event") handleOrcaEvent(data);
};
es.onerror = () => {
  document.getElementById("print-status").textContent = "disconnected";
};

function updateStatus(d) {
  document.getElementById("print-status").textContent = d.print_status ?? "\u2014";
  document.getElementById("nozzle-temp").textContent =
    d.nozzle_temp != null ? d.nozzle_temp.toFixed(1) + "\u00b0C" : "\u2014";
  document.getElementById("bed-temp").textContent =
    d.bed_temp != null ? d.bed_temp.toFixed(1) + "\u00b0C" : "\u2014";

  const pct = d.progress ?? 0;
  document.getElementById("progress-bar").style.width = pct + "%";
  document.getElementById("progress-pct").textContent =
    d.progress != null ? Math.round(d.progress) + "%" : "\u2014";

  const layerEl = document.getElementById("layer-info");
  layerEl.textContent = (d.current_layer != null && d.total_layers != null)
    ? "Layer " + d.current_layer + " / " + d.total_layers : "";

  document.getElementById("print-status").style.color =
    d.print_status === "printing" ? "var(--accent2)" : "var(--text2)";
}

function handleOrcaEvent(d) {
  const banner = document.getElementById("orca-banner");
  const fileEl = document.getElementById("orca-file");
  const base = (d.file || "").split("/").pop() || d.file || "\u2014";
  if (d.event === "model_opened") {
    fileEl.textContent = "Opened: " + base;
    banner.classList.remove("hidden");
  }
  if (d.event === "slice_complete") {
    fileEl.textContent = "Sliced: " + base;
    banner.classList.remove("hidden");
  }
}

// Capture + Analyze button
document.getElementById("capture-btn").addEventListener("click", async () => {
  const btn = document.getElementById("capture-btn");
  const scoresEl = document.getElementById("scores");
  btn.disabled = true;
  btn.textContent = "Analyzing\u2026";
  scoresEl.classList.add("hidden");

  // Remove existing child nodes safely
  while (scoresEl.firstChild) { scoresEl.removeChild(scoresEl.firstChild); }

  try {
    const resp = await fetch("/api/capture", { method: "POST" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    ["stringing", "layer_adhesion", "warping", "surface_finish", "overall"].forEach((k) => {
      const row = document.createElement("div");
      row.className = "score-row";

      const labelSpan = document.createElement("span");
      labelSpan.textContent = k.replace(/_/g, " ");

      const valSpan = document.createElement("span");
      valSpan.className = "score-val";
      valSpan.textContent = data[k] != null
        ? Math.round(data[k] * 100) + "%" : "\u2014";

      row.appendChild(labelSpan);
      row.appendChild(valSpan);
      scoresEl.appendChild(row);
    });
    scoresEl.classList.remove("hidden");
  } catch (err) {
    const errSpan = document.createElement("span");
    errSpan.style.color = "var(--warn)";
    errSpan.textContent = "Error: " + err.message;
    scoresEl.appendChild(errSpan);
    scoresEl.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "Capture + Analyze";
  }
});

// Load filament data on page load
async function loadFilament() {
  try {
    const resp = await fetch("/api/filament");
    if (!resp.ok) return;
    const d = await resp.json();
    document.getElementById("filament-name").textContent =
      (d.filament || "\u2014") + " \u00b7 " + (d.nozzle || "");
    renderBaseline(d);
    renderPareto(d.speed_pareto || []);
    renderLog(d.recent_runs || []);
  } catch (_) {}
}

function renderBaseline(d) {
  const el = document.getElementById("baseline-content");
  const bl = d.baseline || {};
  const rb = (d.research_baseline) || {};

  // Clear children
  while (el.firstChild) { el.removeChild(el.firstChild); }

  const badge = document.createElement("div");
  badge.className = "tier-badge";
  badge.textContent = "Tier " + (d.tier != null ? d.tier : "\u2014");
  el.appendChild(badge);

  ["nozzle_temp", "bed_temp", "flow_rate", "max_speed", "cooling_fan"].forEach((p) => {
    const v = bl[p] ?? rb[p]?.recommended ?? null;
    const row = document.createElement("div");
    row.className = "baseline-row";

    const key = document.createElement("span");
    key.className = "baseline-key";
    key.textContent = p.replace(/_/g, " ");

    const val = document.createElement("span");
    val.className = "baseline-val";
    val.textContent = v != null ? String(v) : "\u2014";

    row.appendChild(key);
    row.appendChild(val);
    el.appendChild(row);
  });
}

function renderPareto(points) {
  const el = document.getElementById("pareto-content");
  while (el.firstChild) { el.removeChild(el.firstChild); }

  if (!points.length) {
    const msg = document.createElement("span");
    msg.style.cssText = "color:var(--text2);font-size:12px";
    msg.textContent = "No speed data yet";
    el.appendChild(msg);
    return;
  }

  const maxQ = Math.max(...points.map((p) => p.quality_score || 0)) || 1;
  points.slice(-8).forEach((p) => {
    const pct = ((p.quality_score / maxQ) * 100).toFixed(0);

    const row = document.createElement("div");
    row.className = "pareto-row";

    const label = document.createElement("span");
    label.className = "pareto-label";
    label.textContent = (p.speed || 0) + " mm/s";

    const barWrap = document.createElement("div");
    barWrap.className = "pareto-bar-wrap";
    const bar = document.createElement("div");
    bar.className = "pareto-bar";
    bar.style.width = pct + "%";
    barWrap.appendChild(bar);

    const scoreSpan = document.createElement("span");
    scoreSpan.textContent = Math.round((p.quality_score || 0) * 100) + "%";

    row.appendChild(label);
    row.appendChild(barWrap);
    row.appendChild(scoreSpan);
    el.appendChild(row);
  });
}

function renderLog(runs) {
  const el = document.getElementById("log-content");
  while (el.firstChild) { el.removeChild(el.firstChild); }

  if (!runs.length) {
    const msg = document.createElement("span");
    msg.style.cssText = "color:var(--text2);font-size:12px";
    msg.textContent = "No runs yet";
    el.appendChild(msg);
    return;
  }

  runs.slice(-5).reverse().forEach((r) => {
    const ts = r.timestamp ? r.timestamp.slice(0, 16).replace("T", " ") : "\u2014";
    const row = document.createElement("div");
    row.className = "log-row";
    row.textContent = ts + " \u00b7 " + (r.param || "\u2014") + " = " + (r.value ?? "\u2014");
    el.appendChild(row);
  });
}

loadFilament();
