from __future__ import annotations

import os
import threading
from uuid import UUID, uuid4
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from pathfinding import DEFAULT_OBSTACLES
from visionlogix.camera import CameraService
from visionlogix.detector import create_marker_png
from visionlogix.marker_history import MarkerHistoryStore, MarkerHistoryUnavailable
from visionlogix.state_store import AppStateStore
from warehouse import WarehouseService


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["CAMERA_ENABLED"] = os.environ.get("VERCEL") != "1"
app.config["BROWSER_CAMERA_ENABLED"] = os.environ.get("VERCEL") == "1"
camera = CameraService(camera_index=int(os.environ.get("CAMERA_INDEX", "1")))
detector_lock = threading.Lock()
warehouse = WarehouseService()
current_run_id = uuid4().hex
state_path = (
    Path("/tmp/visionlogix.sqlite3")
    if os.environ.get("VERCEL") == "1"
    else Path(app.instance_path) / "visionlogix.sqlite3"
)
state_store = AppStateStore(state_path)
marker_history = MarkerHistoryStore(
    state_path,
    database_url=os.environ.get("DATABASE_URL"),
    require_database_url=os.environ.get("VERCEL") == "1",
)
saved_warehouse = state_store.load("warehouse")
if saved_warehouse is not None:
    warehouse.restore(saved_warehouse)


def request_run_id() -> str | None:
    raw_run_id = request.headers.get("X-Run-ID", current_run_id)
    try:
        return UUID(raw_run_id).hex
    except (AttributeError, ValueError):
        return None


@app.get("/")
def index() -> str:
    global current_run_id
    camera.stop()
    warehouse.reset()
    state_store.clear("detections")
    state_store.clear("warehouse")
    current_run_id = uuid4().hex
    return render_template(
        "index.html",
        camera_enabled=app.config["CAMERA_ENABLED"],
        browser_camera=app.config["BROWSER_CAMERA_ENABLED"],
        run_id=current_run_id,
        camera_available=(
            app.config["CAMERA_ENABLED"] or app.config["BROWSER_CAMERA_ENABLED"]
        ),
    )


@app.get("/database")
def marker_database() -> str:
    return render_template("database.html")


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")


@app.get("/api/status")
def status():
    current_status = camera.status()
    if not app.config["CAMERA_ENABLED"]:
        current_status.update(
            running=False,
            starting=False,
            detections=[],
            message="Live camera detection is unavailable in the Vercel demo.",
        )
        current_status["last_detections"] = []
        return jsonify(current_status)
    if current_status["detections"]:
        state_store.save("detections", current_status["detections"])
    current_status["last_detections"] = (
        state_store.load("detections") or []
    )
    return jsonify(current_status)


@app.get("/api/detections")
def detections():
    if not app.config["CAMERA_ENABLED"]:
        return jsonify([])
    current_detections = camera.detections()
    if current_detections:
        state_store.save("detections", current_detections)
        return jsonify(current_detections)
    return jsonify(state_store.load("detections") or [])


@app.get("/api/warehouse")
def warehouse_status():
    current_detections = camera.detections()
    warehouse.observe_detections(current_detections)
    state = warehouse.snapshot()
    state_store.save("warehouse", state)
    try:
        marker_history.sync_scanned_markers(current_detections, current_run_id)
        marker_history.sync_warehouse(state, current_detections, current_run_id)
    except MarkerHistoryUnavailable as exc:
        state["marker_history_saved"] = False
        state["marker_history_warning"] = str(exc)
    else:
        state["marker_history_saved"] = True
    return jsonify(state)


@app.get("/api/marker-records")
def marker_records():
    raw_limit = request.args.get("limit", "100")
    try:
        limit = int(raw_limit)
    except ValueError:
        return jsonify({"error": "limit must be an integer."}), 400
    if limit < 1 or limit > 500:
        return jsonify({"error": "limit must be between 1 and 500."}), 400

    try:
        result = marker_history.list_records(limit)
        result["persistence"] = (
            "persistent" if marker_history.database_url else "local"
        )
        return jsonify(result)
    except MarkerHistoryUnavailable as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/marker-ids.txt")
def marker_id_document():
    try:
        document = marker_history.marker_id_document()
        response = Response(document, mimetype="text/plain; charset=utf-8")
        response.headers["Content-Disposition"] = (
            'attachment; filename="visionlogix-marker-ids.txt"'
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except MarkerHistoryUnavailable as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/metrics")
def performance_metrics():
    run_id = request_run_id()
    if run_id is None:
        return jsonify({"error": "X-Run-ID must be a valid UUID."}), 400
    return jsonify(warehouse.metrics_snapshot())


@app.post("/api/warehouse/reset")
def reset_warehouse():
    warehouse.reset()
    state = warehouse.snapshot()
    state_store.save("warehouse", state)
    return jsonify(state)


@app.post("/api/warehouse/obstacles")
def update_warehouse_obstacles():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object."}), 400

    raw_cells = payload.get("blocked_cells")
    if not isinstance(raw_cells, list):
        return jsonify({"error": "blocked_cells must be a list of [x, y] cells."}), 400

    blocked_cells: set[tuple[int, int]] = set()
    for cell in raw_cells:
        if (
            not isinstance(cell, list)
            or len(cell) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in cell)
        ):
            return jsonify({"error": "Each blocked cell must contain integer x and y coordinates."}), 400
        x, y = cell
        if not 0 <= x < 24 or not 0 <= y < 16:
            return jsonify({"error": "Blocked cells must be inside the warehouse grid."}), 400
        if (x, y) in DEFAULT_OBSTACLES:
            return jsonify({"error": "Permanent shelf cells cannot be redefined as temporary obstacles."}), 400
        blocked_cells.add((x, y))

    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 200:
        return jsonify({"error": "reason must contain 1–200 characters."}), 400

    rerouted = warehouse.set_dynamic_obstacles(blocked_cells, reason.strip())
    state = warehouse.snapshot()
    state_store.save("warehouse", state)
    return jsonify({"rerouted": rerouted, "warehouse": state})


@app.post("/api/camera/start")
def start_camera():
    if not app.config["CAMERA_ENABLED"]:
        return jsonify({
            "running": False,
            "message": "Live camera detection is unavailable in the Vercel demo.",
        }), 503
    started, message = camera.start()
    return jsonify({"running": started, "message": message}), 200 if started else 503


@app.post("/api/camera/stop")
def stop_camera():
    if not app.config["CAMERA_ENABLED"]:
        return jsonify({
            "running": False,
            "message": "Live camera detection is unavailable in the Vercel demo.",
        })
    camera.stop()
    return jsonify({"running": False, "message": "Camera stopped."})


@app.post("/api/camera/frame")
def process_camera_frame():
    if not app.config["BROWSER_CAMERA_ENABLED"]:
        return jsonify({"error": "Browser camera uploads are not enabled."}), 404
    if request.mimetype != "image/jpeg":
        return jsonify({"error": "Camera frames must be sent as JPEG images."}), 415
    run_id = request_run_id()
    if run_id is None:
        return jsonify({"error": "X-Run-ID must be a valid UUID."}), 400

    image_bytes = request.get_data(cache=False)
    if not image_bytes:
        return jsonify({"error": "The uploaded camera frame is empty."}), 400

    frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"error": "The uploaded camera frame is not a valid image."}), 400

    with detector_lock:
        detections, _ = camera.detector.detect(frame)
    detection_data = [detection.as_dict() for detection in detections]
    warehouse.observe_detections(detection_data)
    state = warehouse.snapshot()
    state_store.save("warehouse", state)
    try:
        marker_history.sync_scanned_markers(detection_data, run_id)
        marker_history.sync_warehouse(state, detection_data, run_id)
    except MarkerHistoryUnavailable as exc:
        history_saved = False
        history_warning = str(exc)
    else:
        history_saved = True
    return jsonify({
        "detections": detection_data,
        "frame_width": int(frame.shape[1]),
        "frame_height": int(frame.shape[0]),
        "warehouse": state,
        "marker_history_saved": history_saved,
        "marker_history_warning": history_warning if not history_saved else None,
    })


@app.get("/api/marker/<int:marker_id>.png")
def marker_image(marker_id: int):
    try:
        image = create_marker_png(marker_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return Response(image, mimetype="image/png")


@app.get("/video_feed")
def video_feed():
    if not app.config["CAMERA_ENABLED"]:
        return jsonify({
            "error": "Live camera detection is unavailable in the Vercel demo."
        }), 503
    frame_id, first_jpeg, running = camera.wait_for_frame(after_frame_id=0, timeout=0)
    if not running or first_jpeg is None:
        return jsonify({"error": "Camera is not ready to stream frames."}), 503

    def frames():
        current_id = frame_id
        jpeg = first_jpeg
        while jpeg is not None:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            current_id, jpeg, running = camera.wait_for_frame(current_id)
            if not running:
                return

    return Response(
        frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
