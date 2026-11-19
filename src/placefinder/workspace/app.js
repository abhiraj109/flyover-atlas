const byId = id => document.getElementById(id);
const form = byId("setup");
const key = document.querySelector('meta[name="workspace-key"]').content;
const custom = () => form.elements.mode.value === "custom";
let running = false;

function updateFields() {
  byId("custom").hidden = !custom();
  byId("example-help").hidden = custom();
  const timed = !byId("second").value.trim();
  byId("clock").hidden = !timed;
  byId("utc").required = custom() && timed;
  for (const name of ["media", "tracks", "first", "box"]) byId(name).required = custom();
}
form.addEventListener("change", updateFields);
byId("second").addEventListener("input", updateFields);

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...options.headers, "X-Workspace-Key": key } });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "The app could not complete that request.");
  return data;
}

function show(state) {
  const {phase, message, files = []} = state;
  if (message) byId("status").textContent = message;
  byId("status").dataset.phase = phase;
  running = phase === "running";
  byId("progress").hidden = !running;
  byId("inputs").disabled = running;
  byId("run").disabled = running;
  byId("run").textContent = running ? "Searching…" : "Find location";
  byId("output").hidden = phase !== "done";
  if (phase !== "done") return;
  drawFootprint(files);
  for (const [id, name] of [["map","results.geojson"], ["ranking","ranked-flights.csv"]]) {
    byId(id).hidden = !files.includes(name);
    byId(id).href = "/result/" + name;
  }
  for (const [id, name] of [["winner","winner.png"], ["runner","runner-up.png"], ["spectrum","spec.png"]]) {
    byId(id).hidden = !files.includes(name);
    if (!byId(id).hidden) {
      const url = "/result/" + name;
      byId(id + "-link").href = url;
      byId(id + "-img").removeAttribute("src");
      byId(id + "-img").src = url;
    }
  }
}

async function drawFootprint(files) {
  const figure = byId("footprint");
  figure.hidden = true;
  if (!files.includes("winner.png")) return;
  try {
    const {features} = await request("/result/results.geojson");
    if (running || byId("output").hidden || !features.length) return;
    const [winner] = features;
    if (winner.properties.verdict === "insufficient evidence") return;
    const points = features.filter(({properties}) => properties.cluster > 0);
    if (!points.length) return;
    const canvas = byId("points");
    const context = canvas.getContext("2d");
    const [lon, lat] = winner.geometry.coordinates;
    const longitudeScale = 111320 * Math.cos(lat * Math.PI / 180);
    const offsets = points.map(({geometry}) => [
      (geometry.coordinates[0] - lon) * longitudeScale,
      (geometry.coordinates[1] - lat) * 111320
    ]);
    const radius = offsets.reduce((max, [east, north]) => Math.max(max, Math.abs(east), Math.abs(north)), 50);
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const scale = 140 / radius;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.lineWidth = 1;
    context.strokeStyle = "#354353";
    context.beginPath();
    context.moveTo(40, centerY); context.lineTo(canvas.width - 40, centerY);
    context.moveTo(centerX, 30); context.lineTo(centerX, canvas.height - 30);
    context.stroke();
    context.fillStyle = "#b3c0d1";
    context.font = "20px system-ui";
    context.fillText("North", centerX + 12, 28);
    context.fillText("East", canvas.width - 65, centerY - 10);
    const barMetres = Math.max(10, Math.round(radius / 30) * 10);
    context.fillRect(40, canvas.height - 25, barMetres * scale, 3);
    context.fillText(`${barMetres} m`, 40, canvas.height - 31);
    context.fillStyle = "#a5f4cd";
    for (const [east, north] of offsets) {
      context.beginPath();
      context.arc(centerX + east * scale, centerY - north * scale, 4, 0, Math.PI * 2);
      context.fill();
    }
    context.strokeStyle = "#fff";
    context.lineWidth = 3;
    context.beginPath();
    context.arc(centerX, centerY, 10, 0, Math.PI * 2);
    context.stroke();
    figure.hidden = false;
  } catch {
    // The downloadable GeoJSON remains available if the preview cannot render.
  }
}

async function poll() {
  try {
    const state = await request("/status");
    show(state);
    if (running) setTimeout(poll, 850);
  } catch {
    show({phase:"error", message:"The app lost its connection. Reopen Flyover Atlas if you closed the launcher."});
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (running) return;
  const ownRecording = custom();
  show({phase:"running", message:ownRecording ? "Reading your selected files…" : "Starting the example…"});
  try {
    const options = {method:"POST"};
    if (ownRecording) {
      const start = byId("utc").value;
      const fields = [byId("first").value, byId("second").value, byId("box").value,
                start && String(Date.parse(start + "Z") / 1000)];
      const media = byId("media").files[0];
      const tracks = byId("tracks").files[0];
      options.headers = {
        "X-Search-Settings": encodeURIComponent(JSON.stringify(fields)),
        "X-Recording-Bytes": String(media.size)
      };
      options.body = new Blob([media, tracks]);
    }
    show(await request("/search", options));
    poll();
  } catch (error) {
    show({phase:"error",message:error.message});
  }
});

updateFields();
poll();
