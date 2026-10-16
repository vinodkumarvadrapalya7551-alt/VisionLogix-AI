const cameraState = document.querySelector("#connection-state");
const connectionLabel = document.querySelector("#connection-label");
const cameraMessage = document.querySelector("#camera-message");
const startButton = document.querySelector("#start-button");
const stopButton = document.querySelector("#stop-button");
const videoFeed = document.querySelector("#video-feed");
const browserVideo = document.querySelector("#browser-camera");
const browserOverlay = document.querySelector("#browser-overlay");
const videoPlaceholder = document.querySelector("#video-placeholder");
const placeholderTitle = document.querySelector("#camera-placeholder-title");
const placeholderMessage = document.querySelector("#camera-placeholder-message");
const detectionList = document.querySelector("#detection-list");
const markerCount = document.querySelector("#marker-count");
const detectionHeading = document.querySelector("#detection-heading");
let startPending = false;
const browserCameraEnabled = startButton.dataset.cameraMode === "browser";
let browserCameraStream = null;
const frameCanvas = document.createElement("canvas");
const runId = document.body.dataset.runId;

function setCameraState(running, message, starting = false) {
  const wasRunning = cameraState.dataset.state === "on";
  cameraState.dataset.state = running ? "on" : starting ? "starting" : "off";
  connectionLabel.textContent = running
    ? "Camera connected"
    : starting
      ? "Connecting camera"
      : !browserCameraEnabled
        ? "Camera offline"
        : "Camera offline";
  cameraState.setAttribute("aria-label", connectionLabel.textContent);
  cameraMessage.textContent = message;
  startButton.disabled = running || startPending;
  stopButton.disabled = !running && !starting;

  if (starting) {
    videoFeed.removeAttribute("src");
    videoFeed.hidden = true;
    browserVideo.hidden = true;
    browserOverlay.hidden = true;
    videoPlaceholder.hidden = false;
    videoPlaceholder.classList.add("is-starting");
    placeholderTitle.textContent = "Opening camera…";
    placeholderMessage.textContent = browserCameraEnabled
      ? "Waiting for camera permission and the first video frame."
      : "Connecting to the camera and waiting for the first frame.";
    document.querySelector("#frame-size").textContent = "CONNECTING CAMERA";
    return;
  }

  if (running && !wasRunning) {
    videoPlaceholder.classList.add("is-starting");
    videoPlaceholder.hidden = false;
    placeholderTitle.textContent = "Camera connected";
    placeholderMessage.textContent = "Waiting for the first live video frame.";
    if (browserCameraEnabled) {
      videoFeed.hidden = true;
      browserVideo.hidden = false;
      browserOverlay.hidden = false;
    } else {
      videoFeed.src = `/video_feed?t=${Date.now()}`;
      videoFeed.hidden = false;
    }
  } else if (!running) {
    videoFeed.removeAttribute("src");
    videoFeed.hidden = true;
    browserVideo.hidden = true;
    browserOverlay.hidden = true;
    videoPlaceholder.hidden = false;
    videoPlaceholder.classList.remove("is-starting");
    placeholderTitle.textContent = "Camera feed is paused";
    placeholderMessage.textContent = "Connect a camera to begin marker detection.";
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

function drawBrowserDetections(detections, width, height) {
  browserOverlay.width = width;
  browserOverlay.height = height;
  const context = browserOverlay.getContext("2d");
  context.clearRect(0, 0, width, height);
  context.lineWidth = Math.max(2, width / 400);
  context.font = `bold ${Math.max(16, width / 32)}px Segoe UI, sans-serif`;
  context.textBaseline = "bottom";
  context.strokeStyle = "#c5f477";
  context.fillStyle = "#c5f477";

  for (const detection of detections) {
    if (!Array.isArray(detection.corners) || detection.corners.length !== 4) continue;
    context.beginPath();
    detection.corners.forEach(([x, y], index) => {
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.closePath();
    context.stroke();
    const [labelX, labelY] = detection.corners[0];
    context.fillText(`ID ${detection.marker_id}`, labelX, Math.max(20, labelY - 6));
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
      label:
        robot.status === "blocked"
          ? "Route planning failed"
          : "Aisle-safe route planned",
      state: robot.status === "blocked" ? "blocked" : "complete",
    },
  ];

  if (robot.status === "blocked") {
    steps.push(
      { label: "No clear route to destination", state: "blocked" },
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
  if (browserCameraEnabled) return;
  try {
    const response = await fetch("/api/warehouse", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not read warehouse status.");
    const state = await response.json();
    renderWarehouseState(state);
  } catch (error) {
    document.querySelector("#warehouse-message").textContent =
      "WAREHOUSE SERVICE UNAVAILABLE";
    document.querySelector("#robot-list").textContent = error.message;
  }
}

function renderWarehouseState(state) {
  document.querySelector("#warehouse-message").textContent =
    window.warehouseRendererFallback
      ? `ISOMETRIC 3D VIEW · ${state.message.toUpperCase()}`
      : state.message.toUpperCase();
  document.querySelector("#warehouse-total").textContent = String(state.summary.total);
  document.querySelector("#warehouse-moving").textContent = String(state.summary.moving);
  document.querySelector("#warehouse-queued").textContent = String(state.summary.queued);
  document.querySelector("#warehouse-delivered").textContent =
    String(state.summary.delivered);
  renderRobotList(state.robots);
  if (state.metrics) renderPerformanceMetrics(state.metrics);
  window.updateWarehouseScene?.(state);
}

function renderPerformanceMetrics(metrics) {
  const formatMetric = (value, fractionDigits, suffix) => {
    const number = Number(value);
    return value === null || value === undefined || !Number.isFinite(number)
      ? "—"
      : `${number.toFixed(fractionDigits)}${suffix}`;
  };
  const formatCount = (value) => {
    const number = Number(value);
    return value === null || value === undefined || !Number.isFinite(number)
      ? "—"
      : String(number);
  };
  document.querySelector("#metric-throughput").textContent =
    formatMetric(metrics.packages_per_minute, 2, " / min");
  document.querySelector("#metric-completed").textContent =
    formatCount(metrics.completed_deliveries);
  document.querySelector("#metric-attempts").textContent =
    formatCount(metrics.delivery_attempts ?? metrics.evaluated_assignments);
  document.querySelector("#metric-mis-sorts").textContent =
    formatCount(metrics.mis_sorts);
  document.querySelector("#metric-mis-sort-rate").textContent =
    formatMetric(metrics.mis_sort_rate_percent, 1, "%");
  document.querySelector("#metric-evaluated").textContent =
    formatCount(metrics.evaluated_assignments);
  document.querySelector("#metric-reroutes").textContent =
    formatCount(metrics.reroutes);
  document.querySelector("#metric-failed").textContent =
    formatCount(metrics.failed_deliveries ?? metrics.blocked_routes);
  document.querySelector("#metric-average-time").textContent =
    formatMetric(metrics.average_delivery_seconds, 1, " s");
  const observationSeconds = Number(metrics.observation_seconds);
  document.querySelector("#metrics-window").textContent = Number.isFinite(observationSeconds)
    ? metrics.session_started_at
      ? `OBSERVING · ${(observationSeconds / 60).toFixed(1)} MIN`
      : "WAITING FOR FIRST MARKER"
    : "METRICS UNAVAILABLE";
}

async function refreshPerformanceMetrics() {
  try {
    const response = await fetch("/api/metrics", {
      cache: "no-store",
      headers: { "X-Run-ID": runId },
    });
    if (!response.ok) throw new Error("Performance metrics are unavailable.");
    renderPerformanceMetrics(await response.json());
  } catch {
    document.querySelector("#metrics-window").textContent = "METRICS UNAVAILABLE";
    for (const id of [
      "metric-throughput",
      "metric-completed",
      "metric-attempts",
      "metric-mis-sorts",
      "metric-mis-sort-rate",
      "metric-evaluated",
      "metric-reroutes",
      "metric-failed",
      "metric-average-time",
    ]) {
      document.querySelector(`#${id}`).textContent = "—";
    }
  }
}

async function refreshStatus() {
  if (browserCameraEnabled) return;
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
  if (browserCameraEnabled) {
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("This browser does not support secure camera access.");
      }
      browserCameraStream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 30, max: 30 },
        },
      });
      browserVideo.srcObject = browserCameraStream;
      await browserVideo.play();
      startPending = false;
      setCameraState(true, "Camera connected. Scanning for ArUco markers.");
      void processBrowserCameraFrames(browserCameraStream);
    } catch (error) {
      browserCameraStream?.getTracks().forEach((track) => track.stop());
      browserCameraStream = null;
      startPending = false;
      const message =
        error.name === "NotAllowedError"
          ? "Camera permission was denied. Allow camera access in your browser, then try again."
          : error.name === "NotFoundError"
            ? "No camera was found on this device."
            : error.message || "Could not connect to the camera.";
      setCameraState(false, message);
    }
    return;
  }

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
  if (browserCameraEnabled) {
    browserCameraStream?.getTracks().forEach((track) => track.stop());
    browserCameraStream = null;
    browserVideo.pause();
    browserVideo.srcObject = null;
    setCameraState(false, "Camera stopped.");
    return;
  }
  try {
    const response = await fetch("/api/camera/stop", { method: "POST" });
    const result = await response.json();
    setCameraState(result.running, result.message);
  } catch {
    cameraMessage.textContent = "Could not stop the camera service.";
  }
});

async function processBrowserCameraFrames(stream) {
  let previousFrameAt = performance.now();
  while (browserCameraStream === stream && stream.active) {
    try {
      if (
        browserVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
        browserVideo.videoWidth > 0 &&
        browserVideo.videoHeight > 0
      ) {
        const scale = Math.min(1, 960 / browserVideo.videoWidth);
        frameCanvas.width = Math.round(browserVideo.videoWidth * scale);
        frameCanvas.height = Math.round(browserVideo.videoHeight * scale);
        const context = frameCanvas.getContext("2d");
        context.drawImage(browserVideo, 0, 0, frameCanvas.width, frameCanvas.height);

        const blob = await new Promise((resolve, reject) => {
          frameCanvas.toBlob(
            (image) => image ? resolve(image) : reject(new Error("Could not encode camera frame.")),
            "image/jpeg",
            0.72,
          );
        });
        const response = await fetch("/api/camera/frame", {
          method: "POST",
          headers: {
            "Content-Type": "image/jpeg",
            "X-Run-ID": runId,
          },
          body: blob,
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Camera frame processing failed.");

        renderDetections(result.detections);
        drawBrowserDetections(
          result.detections,
          result.frame_width,
          result.frame_height,
        );
        renderWarehouseState(result.warehouse);
        cameraMessage.textContent = result.marker_history_warning
          ? `Marker detected and delivery assigned, but history was not saved: ${result.marker_history_warning}`
          : "Camera connected. Scanning for ArUco markers.";
        document.querySelector("#frame-size").textContent =
          `${result.frame_width} × ${result.frame_height}`;
        const now = performance.now();
        document.querySelector("#fps-value").textContent =
          `${(1000 / Math.max(1, now - previousFrameAt)).toFixed(1)} FPS`;
        previousFrameAt = now;
      }
    } catch (error) {
      cameraMessage.textContent = error.message;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 120));
  }
}

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
  videoPlaceholder.classList.remove("is-starting");
});

browserVideo.addEventListener("loadeddata", () => {
  videoPlaceholder.hidden = true;
  videoPlaceholder.classList.remove("is-starting");
});

videoFeed.addEventListener("error", () => {
  videoPlaceholder.hidden = false;
});

if (browserCameraEnabled) {
  cameraMessage.textContent =
    "Allow camera access when prompted. Camera frames are sent securely for marker detection.";
} else {
  refreshStatus();
  window.setInterval(refreshStatus, 500);
}
refreshPerformanceMetrics();
window.setInterval(refreshPerformanceMetrics, 3000);
