# VisionLogix — Vision and Warehouse Simulation

VisionLogix detects ArUco 4×4 markers from a local webcam and uses IDs 1–96 to
trigger virtual robot deliveries in an interactive 3D warehouse. A* pathfinding
routes each robot around shelf obstacles to its assigned destination zone.

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
and warehouse deliveries.

Three.js and its orbit controls are bundled under `static/vendor`, so the
dashboard does not need internet access at runtime. `package.json` and
`package-lock.json` pin the library version used for those bundled files.

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

This is a virtual warehouse simulation; it does not issue commands to physical
robots or track real packages. The camera detects marker identity and image
coordinates only. It does not infer a robot's calibrated position in the
warehouse. Reconnecting the same marker during a single app run does not create
a duplicate delivery.

For reliable detection, keep the whole marker visible, use bright even lighting,
avoid glare, and make the marker at least 40 pixels wide in the camera image.
The reported position is the marker's center in camera-frame pixels; it is not
a calibrated real-world measurement.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
