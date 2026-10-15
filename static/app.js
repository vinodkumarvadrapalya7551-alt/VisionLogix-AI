const cameraState = document.querySelector("#connection-state");
const connectionLabel = document.querySelector("#connection-label");
const cameraMessage = document.querySelector("#camera-message");
const startButton = document.querySelector("#start-button");
const stopButton = document.querySelector("#stop-button");
const videoFeed = document.querySelector("#video-feed");
const videoPlaceholder = document.querySelector("#video-placeholder");
const detectionList = document.querySelector("#detection-list");
const markerCount = document.querySelector("#marker-count");
const detectionHeading = document.querySelector("#detection-heading");
let startPending = false;

function setCameraState(running, message, starting = false) {
  const wasRunning = cameraState.dataset.state === "on";
  cameraState.dataset.state = running ? "on" : starting ? "starting" : "off";
  connectionLabel.textContent = running
    ? "Camera connected"
    : starting
      ? "Connecting camera"
      : "Camera offline";
  cameraMessage.textContent = message;
  startButton.disabled = running || startPending;
  stopButton.disabled = !running && !starting;

  if (running && !wasRunning) {
    videoFeed.src = `/video_feed?t=${Date.now()}`;
    videoFeed.hidden = false;
  } else if (!running) {
    videoFeed.removeAttribute("src");
    videoFeed.hidden = true;
    videoPlaceholder.hidden = false;
    document.querySelector("#frame-size").textContent = "AWAITING CAMERA";
    document.querySelector("#fps-value").textContent = "0.0 FPS";
    renderDetections([]);
  }
}

function renderDetections(detections) {
  markerCount.textContent = String(detections.length);
  detectionList.replaceChildren();
  if (detections.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const icon = document.createElement("span");
    icon.className = "empty-target";
    icon.textContent = "◎";
    const text = document.createElement("span");
    text.textContent = "No markers detected yet";
    empty.append(icon, text);
    detectionList.append(empty);
    return;
  }

  for (const detection of detections) {
    const row = document.createElement("article");
    row.className = "detection-row";
    const id = document.createElement("span");
    id.className = "detection-id";
    id.textContent = `ID ${detection.marker_id}`;
    const zone = zoneForMarker(detection.marker_id);
    const position = document.createElement("span");
    position.className = "detection-position";
    position.textContent = zone
      ? `${zone} · X ${detection.center_x} · Y ${detection.center_y}`
      : `X ${detection.center_x} · Y ${detection.center_y}`;
    const size = document.createElement("span");
    size.className = "detection-size";
    size.textContent = `${detection.side_pixels} px`;
    row.append(id, position, size);
    detectionList.append(row);
  }
}

function zoneForMarker(markerId) {
  if (markerId >= 1 && markerId <= 32) return "Zone A";
  if (markerId >= 33 && markerId <= 64) return "Zone B";
  if (markerId >= 65 && markerId <= 96) return "Zone C";
  return null;
}

function robotActivitySteps(robot) {
  const steps = [
    { label: `Marker ${robot.marker_id} captured`, state: "complete" },
    { label: `${robot.zone_name} assigned`, state: "complete" },
    {
      label: "Aisle-safe route planned",
      state: robot.status === "blocked" ? "blocked" : "complete",
    },
  ];

  if (robot.status === "blocked") {
    steps.push(
      { label: "Route unavailable", state: "blocked" },
      { label: "Delivery cannot continue", state: "blocked" },
    );
    return steps;
  }

  if (robot.status === "queued") {
    steps.push(
      { label: "Waiting for shared aisle", state: "current" },
      { label: "Delivered", state: "pending" },
    );
  } else if (robot.status === "moving") {
    steps.push(
      { label: "Robot en route", state: "current" },
      { label: "Delivered", state: "pending" },
    );
  } else {
    steps.push(
      { label: "Route completed", state: "complete" },
      { label: "Delivered", state: "complete" },
    );
  }
  return steps;
}

function renderRobotList(robots) {
  const list = document.querySelector("#robot-list");
  list.replaceChildren();
  if (robots.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No deliveries yet";
    list.append(empty);
    return;
  }

  for (const robot of [...robots].reverse()) {
    const card = document.createElement("article");
    card.className = "robot-card";
    const heading = document.createElement("div");
    heading.className = "robot-card-heading";
    const robotName = document.createElement("strong");
    robotName.textContent = `ROBOT ${robot.robot_id}`;
    const status = document.createElement("span");
    status.className = `robot-status status-${robot.status}`;
    status.textContent = robot.status.replace("_", " ").toUpperCase();
    heading.append(robotName, status);

    const details = document.createElement("p");
    details.textContent = robot.zone_name;
    const progress = document.createElement("progress");
    progress.max = 1;
    progress.value = robot.progress;
    progress.setAttribute("aria-label", `Robot ${robot.robot_id} delivery progress`);
    card.append(heading, details, progress);

    const steps = document.createElement("ol");
    steps.className = "activity-steps";
    steps.setAttribute("aria-label", `Delivery steps for marker ${robot.marker_id}`);
    for (const [index, step] of robotActivitySteps(robot).entries()) {
      const item = document.createElement("li");
      item.className = `activity-step is-${step.state}`;
      const indicator = document.createElement("span");
      indicator.className = "activity-step-indicator";
      indicator.setAttribute("aria-hidden", "true");
      indicator.textContent = step.state === "complete" ? "✓" : String(index + 1);
      const label = document.createElement("span");
      label.textContent = step.label;
      item.append(indicator, label);
      steps.append(item);
    }
    card.append(steps);

    if (robot.status === "queued") {
      const queue = document.createElement("small");
      queue.textContent = `Queue position ${robot.queue_position}`;
      card.append(queue);
    }
    list.append(card);
  }
}

async function refreshWarehouse() {
  try {
    const response = await fetch("/api/warehouse", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not read warehouse status.");
    const state = await response.json();
    document.querySelector("#warehouse-message").textContent =
      state.message.toUpperCase();
    document.querySelector("#warehouse-total").textContent = String(state.summary.total);
    document.querySelector("#warehouse-moving").textContent = String(state.summary.moving);
    document.querySelector("#warehouse-queued").textContent = String(state.summary.queued);
    document.querySelector("#warehouse-delivered").textContent =
      String(state.summary.delivered);
    renderRobotList(state.robots);
    window.updateWarehouseScene?.(state);
  } catch (error) {
    document.querySelector("#warehouse-message").textContent =
      "WAREHOUSE SERVICE UNAVAILABLE";
    document.querySelector("#robot-list").textContent = error.message;
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not read camera status.");
    const status = await response.json();
    setCameraState(status.running, status.message, status.starting);
    if (status.running && status.frame_width > 0) {
      document.querySelector("#frame-size").textContent =
        `${status.frame_width} × ${status.frame_height}`;
      document.querySelector("#fps-value").textContent = `${status.fps.toFixed(1)} FPS`;
      videoPlaceholder.hidden = true;
    }
    const currentDetections = status.detections ?? [];
    const lastDetections = status.last_detections ?? [];
    const hasCurrentDetections = currentDetections.length > 0;
    const detections = hasCurrentDetections ? currentDetections : lastDetections;
    detectionHeading.textContent =
      detections.length > 0 && !hasCurrentDetections
        ? "LAST SAVED MARKERS"
        : "DETECTED MARKERS";
    renderDetections(detections);
    await refreshWarehouse();
  } catch (error) {
    cameraState.dataset.state = "off";
    connectionLabel.textContent = "Service unavailable";
    cameraMessage.textContent = error.message;
  }
}

startButton.addEventListener("click", async () => {
  startPending = true;
  setCameraState(false, "Opening camera and waiting for the first frame.", true);
  try {
    const response = await fetch("/api/camera/start", { method: "POST" });
    const result = await response.json();
    startPending = false;
    setCameraState(result.running, result.message, result.starting);
  } catch {
    startPending = false;
    setCameraState(false, "Could not reach the camera service. Refresh and try again.");
  }
});

stopButton.addEventListener("click", async () => {
  stopButton.disabled = true;
  try {
    const response = await fetch("/api/camera/stop", { method: "POST" });
    const result = await response.json();
    setCameraState(result.running, result.message);
  } catch {
    cameraMessage.textContent = "Could not stop the camera service.";
  }
});

document.querySelector("#marker-button").addEventListener("click", () => {
  const input = document.querySelector("#marker-id");
  const markerId = Number(input.value);
  const message = document.querySelector("#marker-message");
  if (!Number.isInteger(markerId) || markerId < 0 || markerId > 96) {
    message.textContent = "Choose a marker ID from 0 to 96.";
    return;
  }

  const image = document.querySelector("#marker-image");
  image.src = `/api/marker/${markerId}.png?t=${Date.now()}`;
  image.alt = `Printable ArUco test marker, ID ${markerId}`;
  message.textContent = `Marker ${markerId} · 4×4 dictionary`;
});

videoFeed.addEventListener("load", () => {
  videoPlaceholder.hidden = true;
});

videoFeed.addEventListener("error", () => {
  videoPlaceholder.hidden = false;
});

refreshStatus();
window.setInterval(refreshStatus, 500);
