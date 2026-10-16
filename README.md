# VisionLogix — Vision and Warehouse Simulation

VisionLogix detects ArUco 4×4 markers from a local webcam and uses IDs 1–96 to
trigger virtual robot deliveries in an interactive 3D warehouse. A* pathfinding
routes each robot around shelf obstacles to its assigned destination zone.
It is a marker-based item identification and delivery-status tool for a small
warehouse operator or supervisor, not a general-purpose object-recognition
system.

## Requirements

- Python 3.10 or newer
- A webcam connected to the computer running the app
- Camera access enabled in the operating system
- A browser with WebGL support for the 3D warehouse view

## Run on Windows

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Open <http://127.0.0.1:5000>. Select **Connect camera** to start the local
camera feed. The app binds only to `127.0.0.1`; it does not expose camera video
to the local network.

The latest non-empty camera detection snapshot and warehouse delivery state are
saved locally in `instance/visionlogix.sqlite3` while the app is running, so
they can be restored after a server restart. Loading or refreshing the home
page starts a fresh run: it stops the camera and clears the saved detections
and current warehouse deliveries. The separate marker-history table is not
cleared; open **Database** in the navigation to view saved deliveries from
current and earlier runs.
Each dashboard load starts a new run ID. Within a run, a marker is stored once
even if the camera sends many repeated frames; showing the same marker in a
later run creates a separate history record.

Three.js and its orbit controls are bundled under `static/vendor`, so the
dashboard does not need internet access at runtime. `package.json` and
`package-lock.json` pin the library version used for those bundled files.

No independently measured physical-warehouse baseline or operator usability
study is available yet. Do not use the simulation KPIs to claim labor savings,
real package throughput, or sorting accuracy.

If the default camera is not the one you want, set its OpenCV index before
starting the app:

```powershell
$env:CAMERA_INDEX = "0"
.\.venv\Scripts\python.exe main.py
```

On the VisionLogix workstation, camera index `1` is the HP Wide Vision HD
physical webcam; index `0` is the Smart Connect virtual camera. The app defaults
to the HP webcam so its feed is not taken from Smart Connect.

## Marker-to-delivery mapping

The **Test marker** control generates printable ArUco 4×4 markers using the
4×4/100 dictionary, with supported IDs 0–96. These are ArUco fiducials, not QR
codes. IDs 1–96 identify virtual robots and trigger one delivery per ID for
each app run:

| Marker IDs | Destination |
| --- | --- |
| 1–32 | Zone A |
| 33–64 | Zone B |
| 65–96 | Zone C |

ID 0 remains available for visual detection, but does not trigger a delivery.
The 3D warehouse retains its six 4×4 shelf blocks; each scanned marker is
routed to the destination zone mapped to its ID range.
When a delivery is triggered, its robot receives an A* route from an entry lane
to the destination. The simulation reserves the shared aisle for one moving
robot at a time to prevent robot-to-robot route collisions. Other robots are
queued and shown in the delivery dashboard. A virtual package rides with each
robot and is removed from the robot when it reaches its destination. Drag the
3D view to orbit and use the mouse wheel to zoom.

If the browser or device cannot create a WebGL context, the warehouse panel
automatically switches to a top-down 2D canvas view with shelves, zones,
routes, and robot positions. The detection, delivery, and status workflows
continue to work in this fallback mode.

This is a virtual warehouse simulation; it does not issue commands to physical
robots or track real packages. Camera coordinates are image pixels and are not
warehouse coordinates. Reconnecting the same marker during a single app run
does not create a duplicate delivery. One virtual robot moves at a time; queued
robots wait off the aisle, and blocked robots reserve their current grid cell.

The browser-camera view draws marker outlines over the preview using returned
corner coordinates. The local camera preview is annotated by OpenCV. In both
modes, IDs and center coordinates refer to the camera image, not calibrated
warehouse localization.

## Performance metrics

The dashboard reports simulation-only session measurements:

- **Packages/minute:** completed deliveries divided by elapsed time since the
  first valid marker assignment in this app session.
- **Mis-sorts:** assigned destinations that disagree with the configured
  marker-ID-to-zone mapping. The displayed rate is mis-sorts divided by
  evaluated assignments. This is an internal consistency check, not
  independent validation of marker accuracy.
- **Reroutes:** accepted replacement routes only. A failed replan is not
  counted as a reroute and leaves the delivery blocked.
- **Average delivery time:** mean start-to-completion time for completed
  deliveries only. Incomplete and blocked deliveries are excluded.

An empty/zero-duration session has no defined throughput or mis-sort rate and
is displayed as `—`. These values describe the virtual simulation and must not
be interpreted as real-world warehouse throughput or productivity.

## API

- `GET /api/status` — local camera status and current/saved detections.
- `GET /api/detections` — local camera detections.
- `GET /api/warehouse` — delivery state, routes, dynamic/static obstacles,
  movement progress, and session metrics.
- `GET /api/metrics` — current performance metrics as JSON.
- `GET /api/marker-records?limit=100` — saved marker delivery history, newest
  first. The limit must be between 1 and 500. Each record includes marker ID,
  assigned zone, camera-image center, delivery status, and timestamps.
- `GET /database` — browser view of saved marker records; it refreshes every
  five seconds and can also be refreshed manually.
- `POST /api/camera/start` and `POST /api/camera/stop` — control the local
  webcam.
- `POST /api/camera/frame` — Vercel browser-camera JPEG detection endpoint;
  accepts JPEG bytes with `X-Run-ID` set to the UUID supplied with the dashboard
  page, then returns detected marker data and the resulting warehouse snapshot.
- `POST /api/warehouse/reset` — clear the current in-memory delivery session.
- `POST /api/warehouse/obstacles` — replace temporary blocked grid cells and
  attempt to replan an affected moving robot. Example:

  ```json
  {
    "blocked_cells": [[4, 3]],
    "reason": "Temporary aisle obstruction"
  }
  ```

  Use an empty `blocked_cells` array to clear temporary obstacles. The response
  contains `rerouted` and the current warehouse state. Coordinates must be
  integer grid cells inside the 24×16 warehouse.

## Validation and limitations

Run the automated tests with the command below. They use generated ArUco
images, deterministic timestamps, and controlled obstacle scenarios; they do
not establish physical-camera detection performance across lighting,
distance, or angle conditions. The frontend smooths each robot along one
adjacent A* route segment at a time, using backend route index and progress.
Only one robot is dispatched at a time; this is the simulation's aisle
reservation policy, not a multi-robot traffic-control system.

See [MILESTONE.md](./MILESTONE.md) for evidence-based feature status, test
fixtures, known limitations, and portfolio materials that are still needed.

For reliable detection, keep the whole marker visible, use bright even lighting,
avoid glare, and make the marker at least 40 pixels wide in the camera image.
The reported position is the marker's center in camera-frame pixels; it is not
a calibrated real-world measurement.

## Deploy to Vercel

Import this repository in Vercel with the project root set to the repository
root. The included `vercel.json` routes the Flask app through Vercel's Python
function. No separate frontend build command is required. Marker history uses
a pure-Python PostgreSQL driver for compatibility with Vercel's managed
runtime.

The hosted version uses your browser's camera permission and securely uploads
downscaled JPEG frames to the Flask function for ArUco detection. Uploaded
frames are processed in memory and not written as image files. Use HTTPS and
allow camera access when prompted. A camera-detected marker ID from 1–32
routes to Zone A, 33–64 to Zone B, and 65–96 to Zone C. Cloud function storage
is temporary and cannot be used for durable SQLite data. To persist marker
history in the deployed app, create a Neon Postgres database and configure its
connection string as the `DATABASE_URL` environment variable in the Vercel
project settings for every deployment environment you use. The application
requires this variable for persistent marker history on Vercel. If it is
missing or cannot connect, marker detection and delivery simulation continue,
the dashboard reports that the marker history was not saved, and `/database`
shows the database configuration error. Local development uses SQLite unless
`DATABASE_URL` is set. Never commit the connection string. After configuring
the variable, redeploy the project.

The database view and records API currently have no authentication layer.
Anyone who can access the deployed app can view its marker IDs, image-space
positions, destinations, statuses, and timestamps; do not store sensitive
information in these records.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
