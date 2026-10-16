# VisionLogix AI — Milestone and Evaluation Evidence

Updated: 2026-10-16

No percentage-complete claims are used because formal milestone rubrics were
not supplied. Status below describes what source code and automated checks
verify, not what has been demonstrated with physical hardware.

## Feature status

| Area | Status | Evidence and remaining validation |
| --- | --- | --- |
| ArUco marker generation and ID validation | Implemented; software-tested | Tests generate supported and unsupported 4×4 markers. Printed-marker tests under varied real lighting, distances, and angles are still required. |
| Camera-to-warehouse assignment | Implemented; software-tested | Generated JPEG frames are submitted to Flask and IDs in each zone range are asserted against the resulting robot assignment. Physical webcam end-to-end evaluation remains unverified here. |
| A* obstacle-aware routing | Implemented; software-tested | Paths are checked for shelf intersections, endpoint correctness, and four-direction adjacency. |
| Delivery lifecycle and queue | Implemented; software-tested | Deterministic simulation tests cover movement, arrival, queued dispatch, duplicate IDs, and blocked-route states. |
| 3D robot rendering | Implemented; browser integration not yet verified | Renderer follows backend route index/progress along adjacent path segments. Visual timing and occlusion should still be reviewed with the target browser and a real camera session. |
| Dynamic rerouting | Implemented; controlled scenario tested | Temporary grid obstacles are submitted via API. Only an accepted replacement route is counted; a no-path result blocks the robot and does not increment the reroute metric. |
| Session performance KPIs | Implemented; deterministic fixtures tested | Throughput, mis-sort rate, accepted reroutes, and completed-delivery duration have explicit empty-session handling. Values are simulation-only. |
| Marker delivery database | Implemented; SQLite persistence and API tested | Each assigned marker is saved once per dashboard run with image center, destination, status, and timestamps. Local SQLite survives app restarts; Neon Postgres support is implemented for Vercel but requires a configured `DATABASE_URL` and has not been connected here. |
| Independent destination validation | Not verified | The mis-sort KPI compares the assignment with the configured marker-to-zone mapping. It does not establish that an independent operator or sensor confirmed the expected destination. |
| New-user usability | Not verified | A warehouse operator/supervisor who did not develop the app must complete the workflow and provide feedback. |
| Portfolio evidence | Incomplete | Genuine hardware/build photos, team-work photos (if applicable), and a demo video showing physical marker detection through completed delivery have not been supplied or generated. |

## Recorded software verification

On 2026-10-16, the repository test command completed with **57 tests passing**.
A local browser smoke test used generated ArUco marker images (not a physical
webcam) and the Flask browser-frame endpoint:

- ID 70 was sent repeatedly and created only one delivery; ID 40 created the
  second delivery. The assignments were Zone C and Zone B respectively.
- Both simulated deliveries reached their configured destinations.
- A temporary obstruction placed on ID 40's route was avoided by an accepted
  replacement path; the reroute counter became 1.
- The sample session reported 2 attempts, 2 completions, 1.46 simulated
  packages/minute, 0/2 configured-map mis-sorts, a 0.0% configured-map
  mis-sort rate, 1 accepted reroute, 4.3 seconds average simulated delivery
  time, and 0 blocked deliveries.
- The renderer canvas loaded and the browser reported no JavaScript console
  errors during this smoke test.
- The marker database page was opened in a local browser; records rendered,
  and the 375-pixel mobile viewport had no horizontal page overflow.

These measurements describe a generated-image test session, not physical
camera conditions, field throughput, or independently verified sorting
accuracy. The mis-sort result only confirms agreement with the configured ID
map.

## Automated performance fixtures

The following are deterministic software fixtures, not warehouse benchmarks or
real-world operating results:

| Fixture | Attempts | Completed | Throughput | Incorrect assignments | Mis-sort rate | Reroutes | Average delivery time | Blocked |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Metric calculation: 1 completed assignment over a fixed 60-second observation window; deliberately assign marker 7 to the wrong zone | 1 | 1 | 1.0/min | 1 | 100% | 0 | 3.5 s | 0 |
| Controlled successful reroute: add a temporary obstruction on the active route and accept an alternate A* path | 1 | 0 at checkpoint | 0/min | 0 | 0% | 1 | — | 0 |
| Controlled failed reroute: block all exits from the current cell | 1 | 0 | 0/min | 0 | 0% | 0 | — | 1 |

The first row deliberately injects a wrong assignment to verify the error
counter. It is not a quality score for the normal marker-to-zone mapping.
Throughput and time values are test inputs used to verify formulas, not
measured physical-world performance. The full run's test counts and result
should be recorded from the actual test command during evaluation.

## Product workflow

1. Generate/print an ArUco 4×4 marker with a delivery ID from 1 to 96.
2. Connect a local webcam (or grant browser-camera access on the hosted
   deployment) and show the marker clearly in its field of view.
3. Confirm the detected ID and image-space center coordinates in the detection
   panel. These pixels are not warehouse localization.
4. Confirm the ID's configured destination: 1–32 is Zone A, 33–64 is Zone B,
   and 65–96 is Zone C.
5. Observe the simulated route and delivery status in Fleet Activity and the
   3D warehouse.
6. Open **Database** to review marker IDs, image-space positions, assignments,
    delivery statuses, and timestamps retained across app runs.
7. Review session-only performance metrics. Use the controlled obstacle API
   scenario only for testing rerouting.

## Performance definitions

- Observation starts at the first supported delivery-marker assignment in the
  current app session. Packages/minute is completed deliveries divided by
  elapsed observation minutes. If elapsed time is zero, throughput is
  undefined and shown as `—`.
- A mis-sort is counted once per unique marker assignment when its actual zone
  differs from the expected zone derived from the configured marker-ID map.
  The rate is incorrect assignments / evaluated assignments × 100. This is
  not independent validation.
- A reroute is counted only after a new route is generated and accepted.
  Successful records retain the previous remaining route, replacement route,
  timestamp, and reason. Failed replans are not counted.
- Average delivery time is calculated from the recorded start/completion
  timestamps for completed deliveries only. Incomplete deliveries are
  excluded.
- These KPIs are generated by a virtual simulation and are not real package
  throughput, measured labor productivity, or physical robot telemetry.
- Marker history is independent of the current delivery session. Local runs use
  SQLite; persistent Vercel history requires Neon configuration through the
  `DATABASE_URL` environment variable and is not yet validated against a live
  cloud database.

## Run and test

On Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py
```

Open <http://127.0.0.1:5000>, generate and print a marker, connect the camera,
then verify the detection panel and robot's destination. For cloud testing,
allow camera access on the HTTPS deployment. The hosted deployment is not
automatically updated by local source edits.

## Submission materials

- GitHub repository: <https://github.com/vinodkumarvadrapalya7551-alt/VisionLogix-AI>
- Hosted demo: <https://visionlogix-ai.vercel.app> (last published deployment;
  verify separately that it contains the current local changes).
- Build/hardware and webcam photographs: not supplied.
- Team-work photographs: not supplied.
- Detection-panel and 3D-warehouse screenshots captured for final submission:
  not supplied.
- Demo video of a printed marker triggering a completed delivery: not supplied.
- Independent warehouse-user test and feedback: not yet performed.
