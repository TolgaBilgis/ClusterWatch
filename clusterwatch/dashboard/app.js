const app = document.querySelector("#app");
const REFRESH_MS = 5000;
let refreshTimer;
let eventSource;
let eventsConnected = false;
let refreshInFlight = false;
let refreshQueued = false;

const esc = (value) => String(value ?? "—").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const pct = value => value == null ? "—" : `${Number(value).toFixed(1)}%`;
const age = seconds => seconds < 2 ? "now" : seconds < 60 ? `${Math.floor(seconds)}s ago` : `${Math.floor(seconds / 60)}m ago`;
const bytes = value => {
  if (value == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let number = Number(value), index = 0;
  while (number >= 1024 && index < units.length - 1) { number /= 1024; index++; }
  return `${number.toFixed(number >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
};
const rate = value => `${bytes(value)}/s`;
const duration = value => {
  const days = Math.floor(value / 86400), hours = Math.floor((value % 86400) / 3600);
  return days ? `${days}d ${hours}h` : `${hours}h ${Math.floor((value % 3600) / 60)}m`;
};
const statusHtml = status => `<span class="status ${status.toLowerCase()}">${esc(status)}</span>`;

async function api(path) {
  const response = await fetch(path, {headers: {Accept: "application/json"}});
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function updateClock() {
  document.querySelector("#clock").textContent = new Date().toLocaleTimeString([], {hour12: false});
}
setInterval(updateClock, 1000); updateClock();

function cloneTemplate(id) {
  app.replaceChildren(document.querySelector(id).content.cloneNode(true));
}

function nodeCard(node) {
  const metric = node.latest;
  const tempValues = metric ? Object.values(metric.temperatures_c || {}) : [];
  const gpuTemp = metric?.gpu?.temperature_c;
  if (typeof gpuTemp === "number") tempValues.push(gpuTemp);
  const maxTemp = tempValues.length ? `${Math.max(...tempValues).toFixed(0)}°C` : "—";
  const reasons = node.status_reasons?.length ? `<p class="reason">${esc(node.status_reasons[0])}</p>` : "";
  return `<a class="node-card" href="/nodes/${encodeURIComponent(node.node_id)}">
    <div class="node-card-top"><div><span class="eyebrow">${esc(node.labels?.role || "NODE")}</span><h3>${esc(node.hostname)}</h3><span class="address">${esc(node.address || node.node_id)}</span></div>${statusHtml(node.status)}</div>
    <div class="mini-metrics">
      <div class="mini-metric"><span>CPU</span><strong>${pct(metric?.cpu_percent)}</strong></div>
      <div class="mini-metric"><span>MEM</span><strong>${pct(metric?.memory_percent)}</strong></div>
      <div class="mini-metric"><span>TEMP</span><strong>${maxTemp}</strong></div>
    </div>${reasons}
    <div class="node-footer"><span>${esc(node.node_id)}</span><span>SEEN ${age(node.heartbeat_age_seconds)}</span></div>
  </a>`;
}

async function renderOverview(initial = true) {
  if (initial) cloneTemplate("#overview-template");
  const data = await api("/api/v1/nodes");
  document.querySelector("#summary-grid").innerHTML = [
    ["REGISTERED NODES", data.total, ""],
    ["HEALTHY", data.counts.HEALTHY, "healthy"],
    ["WARNING", data.counts.WARNING, "warning"],
    ["OFFLINE", data.counts.OFFLINE, "offline"]
  ].map(([label, value, type]) => `<article class="summary-item ${type}"><span class="summary-label">${label}</span><strong class="summary-value">${value}</strong></article>`).join("");
  document.querySelector("#node-grid").innerHTML = data.nodes.length ? data.nodes.map(nodeCard).join("") : `<div class="empty">No agents have registered yet.<br>Start an agent to populate the cluster.</div>`;
  document.querySelector("#last-updated").textContent = `Updated ${new Date(data.generated_at * 1000).toLocaleTimeString()}`;
}

function fact(label, value) { return `<div class="fact"><span>${esc(label)}</span><span>${esc(value)}</span></div>`; }

function drawChart(canvas, series, color, max = null) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth, height = canvas.clientHeight;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const context = canvas.getContext("2d"); context.scale(ratio, ratio);
  const pad = {top: 10, right: 8, bottom: 20, left: 36};
  const innerWidth = width - pad.left - pad.right, innerHeight = height - pad.top - pad.bottom;
  const values = series.map(item => item.value).filter(Number.isFinite);
  const ceiling = max || Math.max(1, ...values) * 1.15;
  context.strokeStyle = "#283039"; context.lineWidth = 1; context.font = "9px ui-monospace"; context.fillStyle = "#687580";
  for (let i = 0; i <= 3; i++) {
    const y = pad.top + innerHeight * i / 3;
    context.beginPath(); context.moveTo(pad.left, y); context.lineTo(width - pad.right, y); context.stroke();
    context.fillText(`${Math.round(ceiling * (1 - i / 3))}`, 4, y + 3);
  }
  if (series.length < 2) { context.fillText("Waiting for history", pad.left + 10, pad.top + innerHeight / 2); return; }
  const gradient = context.createLinearGradient(0, pad.top, 0, height - pad.bottom); gradient.addColorStop(0, `${color}44`); gradient.addColorStop(1, `${color}00`);
  const points = series.map((item, index) => ({x: pad.left + index / (series.length - 1) * innerWidth, y: pad.top + (1 - Math.min(item.value, ceiling) / ceiling) * innerHeight}));
  context.beginPath(); context.moveTo(points[0].x, height - pad.bottom); points.forEach(point => context.lineTo(point.x, point.y)); context.lineTo(points.at(-1).x, height - pad.bottom); context.closePath(); context.fillStyle = gradient; context.fill();
  context.beginPath(); points.forEach((point, i) => i ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y)); context.strokeStyle = color; context.lineWidth = 2; context.stroke();
  context.fillStyle = "#687580"; const first = new Date(series[0].time * 1000), last = new Date(series.at(-1).time * 1000); context.fillText(first.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}), pad.left, height - 4); const lastText = last.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}); context.fillText(lastText, width - pad.right - context.measureText(lastText).width, height - 4);
}

async function renderDetail(nodeId, initial = true) {
  if (initial) cloneTemplate("#detail-template");
  const [node, history] = await Promise.all([api(`/api/v1/nodes/${encodeURIComponent(nodeId)}`), api(`/api/v1/nodes/${encodeURIComponent(nodeId)}/metrics?minutes=60`)]);
  const metric = node.latest;
  document.title = `${node.hostname} · ClusterWatch`;
  document.querySelector("#detail-header").innerHTML = `<div><p class="eyebrow">NODE DETAIL</p><h1>${esc(node.hostname)}</h1><div class="meta">${esc(node.node_id)} · ${esc(node.address || "address unavailable")} · heartbeat ${age(node.heartbeat_age_seconds)}</div></div>${statusHtml(node.status)}`;
  const tempValues = metric ? Object.values(metric.temperatures_c || {}) : [];
  if (typeof metric?.gpu?.temperature_c === "number") tempValues.push(metric.gpu.temperature_c);
  const maxTemp = tempValues.length ? `${Math.max(...tempValues).toFixed(1)}°C` : "—";
  const tiles = [["CPU", pct(metric?.cpu_percent)], ["MEMORY", pct(metric?.memory_percent)], ["DISK", pct(metric?.disk_percent)], ["MAX TEMP", maxTemp], ["LOAD 1M", metric?.load_1?.toFixed(2) ?? "—"]];
  document.querySelector("#metric-strip").innerHTML = tiles.map(([label, value]) => `<div class="metric-tile"><span>${label}</span><strong>${value}</strong></div>`).join("");

  const charts = [
    ["CPU utilization", "Percent", "cpu_percent", "#3ee896", 100], ["Memory utilization", "Percent", "memory_percent", "#50c8e8", 100],
    ["Network receive", "Bytes per second", "network_rx_bytes_per_sec", "#ffbd59", null], ["Network transmit", "Bytes per second", "network_tx_bytes_per_sec", "#d685ff", null]
  ];
  document.querySelector("#chart-grid").innerHTML = charts.map((chart, index) => `<article class="panel chart-panel"><h3>${chart[0]}</h3><p>${chart[1]} · LAST 60 MINUTES</p><canvas id="chart-${index}"></canvas></article>`).join("");
  requestAnimationFrame(() => charts.forEach((chart, index) => drawChart(document.querySelector(`#chart-${index}`), history.metrics.map(item => ({time: item.collected_at, value: item[chart[2]]})), chart[3], chart[4])));

  document.querySelector("#system-facts").innerHTML = [
    ["Uptime", metric ? duration(metric.uptime_seconds) : "—"], ["Memory", metric ? `${bytes(metric.memory_used_bytes)} / ${bytes(metric.memory_total_bytes)}` : "—"],
    ["Disk", metric ? `${bytes(metric.disk_used_bytes)} / ${bytes(metric.disk_total_bytes)}` : "—"], ["Load average", metric ? `${metric.load_1.toFixed(2)} / ${metric.load_5.toFixed(2)} / ${metric.load_15.toFixed(2)}` : "—"],
    ["Agent", node.agent_version], ["Labels", Object.entries(node.labels || {}).map(([k,v]) => `${k}=${v}`).join(", ") || "—"]
  ].map(item => fact(...item)).join("");
  const thermals = Object.entries(metric?.temperatures_c || {}).map(([name, value]) => [name, `${value.toFixed(1)}°C`]);
  if (metric?.gpu?.utilization_percent != null) thermals.unshift(["GPU utilization", pct(metric.gpu.utilization_percent)]);
  if (metric?.gpu?.temperature_c != null) thermals.unshift(["GPU temperature", `${metric.gpu.temperature_c.toFixed(1)}°C`]);
  document.querySelector("#thermal-facts").innerHTML = thermals.length ? thermals.map(item => fact(...item)).join("") : fact("Sensors", "Not exposed by this node");
}

async function route(initial = true) {
  if (refreshInFlight) {
    refreshQueued = true;
    return;
  }
  refreshInFlight = true;
  try {
    const match = location.pathname.match(/^\/nodes\/([^/]+)$/);
    if (match) await renderDetail(decodeURIComponent(match[1]), initial); else await renderOverview(initial);
  } catch (error) {
    if (initial) app.innerHTML = `<section class="error-state"><h2>Controller unavailable</h2><p>${esc(error.message)}</p></section>`;
  } finally {
    refreshInFlight = false;
    if (refreshQueued) {
      refreshQueued = false;
      route(false);
    }
  }
}

function stopPolling() {
  clearTimeout(refreshTimer);
  refreshTimer = undefined;
}

function schedulePolling() {
  stopPolling();
  refreshTimer = setTimeout(async () => {
    await route(false);
    if (!eventsConnected) schedulePolling();
  }, REFRESH_MS);
}

function connectEventStream() {
  if (!("EventSource" in window)) {
    schedulePolling();
    return;
  }

  eventSource = new EventSource("/api/v1/events");
  eventSource.onopen = () => {
    eventsConnected = true;
    stopPolling();
  };
  eventSource.addEventListener("cluster-update", () => route(false));
  eventSource.onerror = () => {
    eventsConnected = false;
    schedulePolling();
  };
}

window.addEventListener("resize", () => route(false));
route().finally(connectEventStream);
