# Verification report

## Direct browser camera update — 20 November 2026

The current version adds **Phone camera → Use this phone's camera** without another phone app. Local HTTPS runs on **5443** alongside HTTP **5000**, sharing the same Flask application, detector, camera source and database. Existing PIN, session key and count were checked before/after the running-server update and preserved.

* **58 Python tests passed** (`58 passed in 45.83s`). This includes the original 46 checks plus browser upload, lease ownership, freshness tickets, ordering/replay rejection, source handover, invalid JPEG/dimension/body-size rejection, authentication/CSRF/HTTPS enforcement, no persisted media, and local certificate generation/reuse.
* **Six JavaScript component tests passed** using Node's built-in test runner and isolated mocks. These cover insecure contexts, certificate-trust error feedback, denied camera permission, double clicks/one in-flight upload, hidden-tab upload suspension/fresh tickets, camera-track shutdown, late-response cancellation and preservation of binary JPEG content type with CSRF. These are component tests, not browser or phone tests.
* Actual **HTTPS + uploaded JPEG + real YOLO + attendance API + SQLite** integration passed using `tests/integration_browser.py` with a temporary database and an in-memory OpenCV reference image. The client verified TLS using the generated certificate as its explicit trust anchor; certificate verification was not disabled. Sixteen concurrent HTTPS requests created exactly one event; blank frames plus cooldown rearmed the system; the next session created event two; stopping uploads expired camera eligibility and rejected marking. HTTP and HTTPS both reported the same count. No uploaded media was persisted.
* The running app returned HTTP 200 for `/setup` from both LAN listeners, HTTP on port 5000 and HTTPS on port 5443. Both pages contained the new button/script and the `camera=(self)` permissions policy. Both listeners were owned by one application process.
* Python compilation, all five application JavaScript syntax checks, dependency consistency checks and checksum verification remain available in the README. Dependencies include the installed/pinned Cheroot TLS server; phone-side downloads are not required.

**Not verified on a physical phone:** getUserMedia permission prompts, rear/front camera selection, browser acceptance of the self-signed local certificate, navigation resume, display layout and sustained upload performance. Browser inventory access was unavailable; the native Chrome window was minimized and no browser visual QA was completed. Some mobile browsers require certificate trust beyond an HTTPS URL. The app reports this limitation instead of claiming a camera is connected. No OS/browser trust settings were changed automatically, no certificate was installed on a phone, and no public tunnel was created.

The following sections record the earlier baseline verification.

Verified on **20 November 2026**, Windows, Python **3.12.13**, CPU inference. This report separates automated/backend and hardware evidence from unverified visual/physical acceptance.

## Successful checks

* **46 automated tests passed**, final run: `46 passed in 43.01s`.
* Python compilation passed for the application, configuration, services, database, routes, scripts and tests.
* All runtime imports succeeded: Flask, OpenCV, Ultralytics, sqlite3, Waitress, NumPy and cryptography.
* All four application JavaScript files passed `node --check`.
* `python -m pip check`: **No broken requirements found**.
* Real YOLO weights loaded successfully, class names were **`{0: 'face'}`**; the pinned SHA-256 matched. A blank frame returned zero detections. A public OpenCV reference image returned exactly one face at confidence threshold 0.60. The image was decoded and processed in memory, never saved.
* The real stack started under Waitress with temporary runtime data. All three pages and all local CSS/JavaScript/font/icon assets returned HTTP 200. No production database was populated and no real operator PIN was pre-created.
* Physical camera enumeration returned indices **0 and 1**. Camera **0** connected successfully at an actual **1280×720**. The real inference pipeline reached `IDLE / Waiting for face`, and `/api/camera/feed` delivered a live JPEG inside the MJPEG stream. No attendance event was created from the physical camera during verification.
* An unavailable HTTP stream entered `disconnected`, with retry count 1 and backoff 1 second. Marking returned 409, the feed returned 503, and the database count stayed zero.

## Full real-model integration

`tests/integration_stream.py` ran successfully against a temporary database and a controllable **loopback MJPEG fixture**, using the actual YOLO model and normal application/API code. The fixture used an OpenCV reference image and blank frames in memory; this was not a physical phone or a fabricated production feed.

1. Actual face inference through the MJPEG camera path reached stable READY.
2. **16 concurrent HTTP marking requests** produced **one 201 and fifteen 409 responses**, with exactly one saved event.
3. A blank zone and completed cooldown rearmed the service. The next stable face session created event two.
4. Disconnecting the fixture invalidated the camera and rejected marking.
5. Restoring the fixture recovered capture automatically. A fresh clear zone rearmed the detector.
6. Stats, event list and weekly total all reported exactly **two**, and no image/video/array files existed in the temporary data directory.
7. All temporary server and capture resources were stopped after checking. Fixture data was separate from the real application's future `data/` directory.

## Required QA coverage

| Requested check | Evidence / result |
| --- | --- |
| Python syntax | Passed compilation |
| Imports | Passed actual installed runtime imports |
| Application startup | Passed actual Waitress/YOLO startup and HTTP requests |
| Database initialization | Passed schema, version and empty count tests |
| Event insertion | Passed actual real-model integration plus unit/API tests |
| Duplicate protection | Passed 32 parallel service calls, 16 parallel Flask HTTP calls, and 16 real network requests |
| Invalid detection | Passed missing, low-confidence, outside-zone, multiple-face, stale-frame, old-source-generation and old-session rejection |
| Camera disconnected | Passed unavailable real HTTP source and real MJPEG outage/reconnection; stale capture cannot serve a frame |
| Empty state | All three templates rendered successfully and actual HTTP routes/assets passed; visual appearance not inspected |
| All three routes | `/setup`, `/dashboard`, `/camera`: HTTP 200 |
| Restart persistence | A second independent Flask application/Database instance using the same on-disk SQLite file retained its count; its stats endpoint returned the saved count |
| No persisted face/video data | Schema is limited to the five specified event fields; tests/integration found no saved media/arrays; inference saving flags disabled |
| Responsive layout | Responsive CSS and ResizeObserver mapping implemented; actual desktop/phone rendering is **not visually verified** |

Additional tests passed for continuous clear duration plus cooldown, lockout retained across camera failure, queued pre-disconnection frame rejection, model-missing error, PIN rate limiting, operator authorization, CSRF, foreign Origin rejection, public network/Host rejection, date validation, reset confirmation, Windows DPAPI encryption/round-trip, redacted camera URLs, and India-time midnight grouping.

## Remaining acceptance checks

The computer-use tool could not establish Chrome's current URL with enough confidence to enforce its policy, and stopped browser control. Browser screenshots, responsive visual inspection, actual button/keyboard interactions, focus behavior and fullscreen behavior were therefore **not verified**. HTML responses and JavaScript syntax checks do not establish visual/UI correctness.

No physical phone, school Wi-Fi, live group of subjects, physical USB unplug/replug cycle, or projector was available for acceptance. The laptop webcam's capture/stream and actual inference were exercised, but physical subject positioning and the operator's complete browser interaction still need to be checked. The README contains a short acceptance sequence for these steps.

No sustained performance benchmark was performed. Configured preview/inference caps are not measured achieved FPS. The source includes bounded buffers and a native-camera stall watchdog; a deliberately hung native device driver was not induced during verification.
