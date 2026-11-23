# Attend.

A local, operator-confirmed attendance system. One camera, a face-only YOLO detector, three browser pages, and a persistent SQLite event log. No recognition or personal identity database.

## Start on this laptop

After completing the installation below, run this command in PowerShell from the repository root:

```powershell
.\.venv\Scripts\python.exe app.py
```

Or double-click **Start Attend.cmd**. Open **http://127.0.0.1:5000/setup**. On the first real launch, the terminal prints a randomly generated eight-digit operator PIN. Click **Unlock controls** in the app and enter that PIN. The PIN is stored as a salted password hash, not plaintext. The default database starts empty; verification used disposable databases.

If the PIN is lost, stop the server, run the following command, enter a new PIN twice, and restart. Existing browser sessions will be invalidated.

```powershell
.\.venv\Scripts\python.exe app.py --set-pin
```

The server uses Waitress, with debugging and the Flask reloader disabled. By default it listens on **0.0.0.0:5000**, with local HTTPS on **0.0.0.0:5443**, so trusted local devices can connect. Use `--no-lan` to listen only on `127.0.0.1`. Run **one server process** for this project. Use Ctrl+C in its terminal to stop it.

## Fresh Windows installation

Use 64-bit Python **3.11 or 3.12**. The commands below use the tested version, Python 3.12. Clone the repository first, or start in the root of your existing checkout.

```powershell
git clone https://github.com/Vansh-Choyal/smart-attendance.git
Set-Location smart-attendance
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe scripts\download_model.py
.\.venv\Scripts\python.exe app.py
```

Keep the server running and open **http://127.0.0.1:5000/setup** in your browser.

No activation or PowerShell execution-policy change is necessary. `requirements.txt` pins direct dependencies; `requirements.lock.txt` records the complete working Windows/Python 3.12 installation. If installing on a different supported platform and the lock has no matching wheel, install `requirements.txt` instead and rerun the checks. The first dependency/model download needs internet. Normal operation and all fonts/icons work offline.

## The three pages

* **/setup** — select a local webcam, directly stream this device's browser camera, or optionally connect an IP stream. Preview and save the source. Only one source runs at a time. Direct browser capture needs no camera app download.
* **/dashboard** — database-backed daily count, camera/detection status, latest entry, paginated event history, date selection and a real seven-day chart. Refreshes automatically every two seconds. Reset today is authenticated, CSRF-protected and requires an explicit dialog confirmation.
* **/camera** — full-viewport monitoring, correctly mapped detection zone and face boxes, large attendance button, live count, keyboard shortcuts and a browser-fullscreen control. The feed uses `object-fit: cover` to fill the screen with a centered crop; overlays use the same scale and crop with a ResizeObserver. Phone browser capture requests portrait (9:16) video.

Only operators can view the video, configure the camera, or mark/reset attendance. The dashboard remains available as a read-only local display. Unlock each browser separately. Operator sessions expire after eight hours. The lock action removes access from the current browser.

## Laptop webcam

1. Unlock controls on Setup, choose **Built-in camera**, and click **Scan devices**. The bounded scan checks indices 0–3 by default. An already selected webcam is listed without reopening and disrupting it.
2. Select a discovered device, or enter its OpenCV index manually (usually 0).
3. Click **Test connection**. Confirm that **Connected** and a real live preview appear. A successful configuration response alone does not prove that a frame arrived.
4. Click **Save & Continue**, then **Open camera** on the dashboard.

If no webcam responds, close other apps using it, check its physical connection, and check Windows **Settings → Privacy & security → Camera → Let desktop apps access your camera** yourself. No camera is selected automatically and no synthetic feed is substituted.

## Phone camera directly in the browser — no app download

1. Connect the phone and laptop to the same Wi-Fi.
2. Start Attend with `.\.venv\Scripts\python.exe app.py --lan`. This starts HTTP on **5000** and a local HTTPS listener on **5443**, sharing one camera/model/database.
3. Open the **HTTPS phone address printed in the terminal** in Chrome or Safari. Use the newly printed address after changing networks.
4. The local certificate is generated on the laptop. The phone may display a certificate warning; inspect that it is your laptop's local address and handle the browser's trust prompt yourself. No certificate, camera app or browser extension is automatically installed. Some browsers require additional certificate trust before they enable camera APIs; browser security restrictions cannot be overridden by this application. No insecure-browser flags or public tunnels are configured.
5. Unlock operator controls with your existing PIN, choose **Phone camera**, select back/front camera, and tap **Use this phone's camera**. Allow camera access when your browser asks.
6. The local preview appears and current JPEG frames are uploaded over HTTPS. Wait for **Connected**. You can leave this phone on Setup and open Camera/Dashboard on the laptop, or tap **Save & Continue** to monitor and mark on the phone itself. Capture resumes across Attend's three pages in the same tab.
7. Keep the phone awake and Attend in the foreground. Backgrounding or locking a phone can suspend its camera; uploads pause in hidden tabs and server eligibility expires automatically. Returning requests a fresh capture ticket. Use **Stop camera** to release the phone camera.

The existing HTTP Setup page also contains the button; on a phone it first opens HTTPS. `http://192.168.x.x:5000` cannot directly request camera access because browsers require a secure context. HTTP localhost on the laptop is a permitted development exception. The server sends `Permissions-Policy: camera=(self), microphone=(), geolocation=()` and does not request audio.

Browser uploads allow exactly one active publisher. Each JPEG requires operator authentication, CSRF, a current publisher token, an ordered sequence number and a one-use server-issued capture ticket. Tickets expire after the detection freshness limit; capture timestamps are conservatively anchored to ticket issuance, so delayed buffered uploads cannot become fresh detections. Uploads have a 2MiB limit, JPEG-only decoding and dimension/pixel bounds. Frames use the same latest-frame slot, YOLO worker, zone checks, session lockout and SQLite insertion as a native camera. No browser video or uploaded image is written to disk. Only the source choice is saved; camera access always requires browser permission.

## Optional existing IP-camera stream

An existing camera URL is still available under **Phone camera → Use an IP camera URL instead**. It is optional; the browser method above needs no other app.

1. Connect the laptop and phone to the same trusted Wi-Fi or laptop/phone hotspot. Guest-network client isolation can prevent them from communicating.
2. Open an IP-camera app on the phone, start its camera server, keep the phone awake, and find the **direct video stream** URL. A camera app's HTML control-page URL is usually not a stream URL.
3. On the laptop's Setup page, choose **IP camera** and enter the URL, for example `http://192.168.1.100:8080/video`. MJPEG/HTTP and RTSP sources are opened through OpenCV/FFmpeg. JPEG snapshot-only endpoints are not continuous camera streams.
4. Test the connection, wait for the real preview, and save. The phone remains the source; the laptop performs inference.
5. If the phone disconnects, eligibility is immediately invalidated when capture fails, or after the 1.5-second frame freshness limit. Reconnection delays grow from 1 to 2, 4, 8 and at most 16 seconds. A supervisor also restarts a native camera worker that stalls for 12 seconds. Lockout survives a connection failure: a disconnect never counts as a clear zone.

For an RTSP source that requires TCP, set the standard OpenCV FFmpeg option before launch:

```powershell
$env:OPENCV_FFMPEG_CAPTURE_OPTIONS = 'rtsp_transport;tcp'
.\.venv\Scripts\python.exe app.py
```

Camera URLs must resolve to local/private network addresses. Credentials and query tokens in URLs are never returned by the API, written into attendance events, or displayed back to a viewer. The whole saved source is encrypted with **Windows current-user DPAPI** in `data/camera.enc`; the same Windows account must run the app after restart. Non-Windows installations use Fernet with a local key and restrictive file modes. Back up/deploy these files according to that platform's protections; a key stored beside ciphertext is not protection from someone with full account access. Entered URLs live only in the form/request and the active capture configuration in memory. Native camera stderr is suppressed because FFmpeg may print credential-bearing URLs.

## Opening the interface on another local device

A phone **streaming to the laptop does not require LAN mode**: the server can use `--no-lan` while connecting out to that phone.

LAN mode is enabled by default, including local HTTPS for direct phone cameras. To operate the web interface from a second device:

```powershell
.\.venv\Scripts\python.exe app.py --lan --port 5000
ipconfig
```

Use the laptop's active Wi-Fi **IPv4 address**, for example `https://192.168.1.20:5443/setup` for browser-camera use or `http://192.168.1.20:5000/dashboard` for an existing display. If Windows asks about network access, allow it only for your trusted private network. No firewall changes are made by this project. LAN mode binds to `0.0.0.0` but still rejects public client addresses and unrecognized/public Host headers; it does not trust forwarded client-IP headers. Do not forward either port through a router or expose it on public Wi-Fi/internet. Prefer HTTPS for operator access. Administrative requests require the operator session and a same-origin CSRF token in both modes. `--https-port` changes 5443; `--no-https` disables the TLS listener when it is not needed. TLS keys/certificates are generated under `data/tls/`, reused, and regenerated on expiry or local address changes at startup. Existing PINs and attendance records are preserved.

## Face model: source, license and installation

The download script installs **yolov8n-face.pt** from [akanametov/yolo-face](https://github.com/akanametov/yolo-face), release **1.0.0**. It is a face-trained detector, not the standard COCO person detector. The loaded class list is checked at runtime and must contain only `face`; a general-purpose model is rejected.

* [Direct weight download](https://github.com/akanametov/yolo-face/releases/download/1.0.0/yolov8n-face.pt)
* Required default path: **models/yolov8n-face.pt**
* Verified file size: **6,389,512 bytes**
* Pinned SHA-256: `d545bf1add5aa736a4febac4f4f9245a6d596cd0fe70d5d57989fe0cb9e626ca`
* Model source repository declares [GPL-3.0](https://github.com/akanametov/yolo-face/blob/dev/LICENSE). The installed Ultralytics package is under [AGPL-3.0, with an enterprise licensing option](https://www.ultralytics.com/license). Review those upstream terms when redistributing or changing deployment scope. This project does not relicense upstream weights or dependencies.

`scripts/download_model.py` downloads only that source, verifies the pinned checksum and installs atomically. A changed/unexpected weight file is rejected by the downloader. The application never automatically falls back to a person detector, Haar cascade or fake detections. If weights are missing, invalid, or cannot initialize, the UI shows a model error and attendance stays disabled. Restart after fixing the model.

## What a check-in means

A check-in is an **operator-confirmed entry event**, not verified personal identity, student attendance by name, or a unique-person count. Someone returning after the zone clears can be counted again. The model can also detect a face displayed in a photo/screen: there is no liveness verification. Supervise the demonstration accordingly.

The pipeline is:

```text
Camera capture → latest frame → face-only YOLO → zone + stability
              → operator confirmation → atomic SQLite insertion
```

An eligible face must have confidence ≥0.60, its bounding-box **center** inside the configured zone, and stable geometric overlap for 400ms. Faces outside the zone do not enable recording. Two or more faces with centers inside the zone disable recording and reset stability. Bounding-box overlap is only an ephemeral continuity check, not identity tracking.

The explicit states are `IDLE → FACE_DETECTED → READY → RECORDED → WAITING_FOR_CLEAR → IDLE`, with `CAMERA_DISCONNECTED` overriding eligibility when the camera or detector cannot supply fresh data. After recording, **both** a continuously clear zone for one second **and** a minimum two-second cooldown are required. Occupancy keeps the system locked indefinitely. A camera switch or network failure cannot bypass that lock. Restarting the server resets all ephemeral detection state, so have the zone clear before resuming a demonstration.

`POST /api/attendance/mark` verifies connection, current frame/detection generation and age, one eligible face, READY state, and the server-issued session token. A shared lock serializes inference commits, marking and source changes. A transaction inserts the event; a UNIQUE index on `detection_session_id` provides a second duplicate-request safeguard. The client submits no count. SQLite is the only source of attendance totals.

## Data and privacy

`data/attendance.sqlite3` contains only:

```text
attendance_events(id, timestamp, camera_source, detection_session_id, status)
```

The session identifier is a random occupancy-session token, unrelated to the person's face. Camera source is a safe display label, never a stream URL. Timestamps are UTC ISO 8601; `Asia/Kolkata` is the default display/grouping timezone. Day boundaries are computed in that timezone, including DST when another configured timezone requires it. Schema initialization is automatic, with `PRAGMA user_version=1`, WAL mode, a timestamp index and busy timeout. Restarting does not clear events. IDs remain globally increasing after a daily reset.

Camera frames, encoded JPEGs and normalized face boxes exist **in memory only** and expire with the current state. No images, raw footage, crops, face embeddings, landmarks, biometric identifiers or recognition libraries are stored. Ultralytics prediction uses `save=False`, `save_txt=False`, `save_crop=False` and `show=False`. The application makes no cloud inference requests. Browser/API responses for live data use `Cache-Control: no-store`. Fonts and Lucide icons are bundled locally with their upstream license notices.

Back up the SQLite database while the server is stopped, or use SQLite's backup API. Treat `data/` as private runtime state and exclude it from source sharing. Do not delete it as a way to restart the application.

## Configuration

Set environment variables in the same PowerShell terminal before starting. Defaults are in `config.py`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ATTEND_TIMEZONE` | `Asia/Kolkata` | IANA timezone for dates and grouping |
| `ATTEND_MODEL_PATH` | `models/yolov8n-face.pt` | Absolute/local trusted face model path |
| `ATTEND_DATA_DIR` | `data/` | Persistent database, auth and encrypted camera config |
| `ATTEND_CONFIDENCE` | `0.6` | Minimum detection confidence |
| `ATTEND_INFERENCE_SIZE` | `640` | YOLO image size |
| `ATTEND_INFERENCE_FPS` | `8` | Maximum inference attempts per second |
| `ATTEND_DEVICE` | `cpu` | Ultralytics inference device |
| `ATTEND_STABLE_SECONDS` | `0.4` | Continuous single-face stability |
| `ATTEND_CLEAR_SECONDS` | `1.0` | Continuous clear-zone rearm duration |
| `ATTEND_COOLDOWN_SECONDS` | `2.0` | Minimum interval after a check-in |
| `ATTEND_DETECTION_MAX_AGE` | `1.0` | Maximum age of the inference source frame |
| `ATTEND_CAMERA_MAX_AGE` | `1.5` | Maximum age of the latest captured frame |
| `ATTEND_ZONE` | `0.24,0.20,0.76,0.80` | Normalized left,top,right,bottom target boundary |
| `ATTEND_CAMERA_WIDTH` / `ATTEND_CAMERA_HEIGHT` | `1280` / `720` | Requested webcam resolution; actual device size is respected |
| `ATTEND_PREVIEW_FPS` | `20` | JPEG encoding/streaming cap, independent of inference |
| `ATTEND_CAMERA_SCAN_LIMIT` | `4` | Number of webcam indices to probe |
| `ATTEND_BROWSER_UPLOAD_FPS` | `12` | Maximum direct browser frame uploads per second; one request in flight |

For example:

```powershell
$env:ATTEND_INFERENCE_FPS = '6'
$env:ATTEND_TIMEZONE = 'Asia/Kolkata'
.\.venv\Scripts\python.exe app.py
```

The latest-frame slot is bounded to one frame. Capture runs in a supervised child process; a reader publishes one shared in-memory preview, and one inference thread runs one model. Slow inference never accumulates a video queue. Clients poll shared status (350ms on Camera, one second elsewhere); dashboard data polls every two seconds. The stream reopens periodically to revalidate the operator session. Waitress has 24 threads; this is intended for a small local demonstration, not dozens of simultaneous MJPEG viewers. No unmeasured FPS/latency claims are made.

## API

JSON uses `{"ok":true,"data":...}` or `{"ok":false,"error":{"code":"...","message":"..."}}`. All browser mutations need a session CSRF token in `X-CSRF-Token`; all camera/attendance mutations also need operator authentication. GET `/api/auth/status` supplies a token. POST `/api/auth/login` accepts `{"pin":"..."}` and returns a rotated token; `/api/auth/logout` locks the browser.

| Endpoint | Behavior |
| --- | --- |
| GET `/api/cameras` | Authenticated, bounded OpenCV camera scan |
| POST `/api/camera/test` | Activate `{"type":"webcam","index":0}` or `{"type":"ip","url":"..."}` without persisting |
| POST `/api/camera/select` | Activate and encrypt/persist the source; `{"use_saved":true}` reuses saved config |
| POST `/api/camera/browser/start` | Claim this operator browser as the publisher; saves browser source and issues an ephemeral publisher token/ticket |
| POST `/api/camera/browser/frame` | Authenticated raw JPEG upload; `X-Camera-Session`, `X-Capture-Ticket`, `X-Frame-Sequence` headers plus CSRF required |
| POST `/api/camera/browser/renew` | Issue a fresh capture ticket after a pause or lost connection; JSON publisher token required |
| POST `/api/camera/browser/stop` | Release the matching publisher and invalidate detection immediately |
| GET `/api/camera/status` | Safe source label, connection state, actual dimensions and reconnection status |
| GET `/api/camera/feed` | Authenticated, shared MJPEG stream; 503 without a fresh frame |
| GET `/api/detection/status` | State, eligibility, normalized zone; boxes/session token restricted to operators |
| POST `/api/attendance/mark` | Atomically consume READY `{"session_id":"server-issued-token"}`; 201 success, 409 ineligible |
| GET `/api/attendance/stats` | Daily count and latest entry; optional `?date=YYYY-MM-DD` |
| GET `/api/attendance/events` | Daily newest-first events; `date`, `limit` (1–100), `before` event ID |
| GET `/api/attendance/weekly` | Seven database-backed days ending at optional `date` |
| POST `/api/attendance/reset` | Delete today only, requires `{"confirm_date":"YYYY-MM-DD"}` |

## Verification

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py config.py database routes services scripts tests
.\.venv\Scripts\python.exe -m pytest -q
Get-ChildItem static\js\*.js | ForEach-Object { node --check $_.FullName }
node --test tests\browser_camera.test.cjs
```

The tests use camera/detection doubles and disposable databases; they never fabricate events in the real database. See **QA_REPORT.md** for what ran and what remains hardware/browser-dependent. Optional isolated preview fixtures are in `tests/preview_server.py` (PIN `86420864`, ports 5055/5056). `--mock` is explicitly synthetic; it is never loaded by the production entry point. Stop it with Ctrl+C after testing.

An additional opt-in check exercises the actual YOLO model, a controllable local MJPEG stream, real HTTP APIs, concurrent marking, clear/cooldown rearming and automatic reconnection. It fetches an OpenCV reference image into memory and uses disposable data; it needs internet for that reference image only:

```powershell
.\.venv\Scripts\python.exe tests\integration_stream.py
.\.venv\Scripts\python.exe tests\integration_browser.py
```

Before the school demonstration, run this physical acceptance sequence:

1. Choose/test/save the actual camera. Confirm the preview updates when the scene moves.
2. Open Camera and wait for the detector to finish loading. Stand outside the zone: marking must remain disabled.
3. Put one face in the zone for at least 400ms. Mark once, click repeatedly, and verify only one database event/count increment.
4. Keep the face in the zone past two seconds: marking must stay locked. Clear the zone for at least one second, then verify a new subject can be marked.
5. Place two faces in the zone: recording must be disabled. Move one out and wait for stability again.
6. Unplug the webcam or stop the phone stream. Marking must stop; reconnect and verify the preview and detection recover.
7. Refresh Dashboard and restart the server. Counts and events must persist. Start with the detection zone clear after a restart.
8. Check Setup, Dashboard and Camera at a laptop size and a phone width, portrait/landscape, and browser fullscreen. Verify the target brackets follow the actual video when letterboxed. Test Space, Enter and Escape; form typing must not trigger marking.
9. Test reset only with disposable demonstration data after reviewing its confirmation dialog. Check that older dates remain untouched.

## Project layout

```text
app.py                 Flask factory, CLI, operator session, Waitress entry point
config.py              Defaults and environment configuration
database/db.py         SQLite schema, UTC storage, local-day queries
services/
  camera_service.py    Supervised capture, latest frame, shared JPEG, reconnection
  detection_service.py Face-only YOLO and inference worker
  attendance_service.py State machine and atomic operator confirmation
  auth.py              Hashed PIN, rate limiting, CSRF, local network guard
  secure_store.py      DPAPI/Fernet configuration encryption
routes/                Camera and attendance APIs
templates/             Exactly three primary application pages
static/                Responsive CSS, vanilla JS, bundled Inter and Lucide
models/                Model provenance, upstream license and downloaded weights
scripts/download_model.py Checksum-pinned model installer
tests/                 State, API, concurrency, persistence, security checks
```
