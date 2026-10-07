# ADR-010: Drop Phone WebRTC Ingest in Favour of a USB Webcam Through the Browser Camera Selector

## Status
Accepted (2026-10). Supersedes the WebRTC ingest option of ADR-001.

## Context
The system originally let a phone act as a classroom camera over WebRTC. The phone opened a page served by the vision service on port 8088, negotiated a WebRTC connection (`/offer`), and streamed video that the vision service consumed with `aiortc` and `av`.

Three things changed:

1. **The attendance flow moved to a browser-owned camera.** The teacher's browser captures frames with `getUserMedia()` and the teacher picks the device from a camera dropdown. Any camera the operating system exposes works, including a phone connected by USB in webcam mode.
2. **The marking path was secured.** Frames go from the browser to the backend with the teacher's JWT. The backend checks session ownership and that the session is active, calls the vision service over the internal network with a service key, and marks attendance only from a signed recognition result. The vision service has no published port.
3. **The WebRTC path could not meet that model.** It required the vision service to be reachable from phones on the LAN, to serve a web page and accept unauthenticated signalling, and to hold a long-lived media session that was not tied to a teacher, a session or a roster.

Keeping WebRTC would have meant either re-exposing the vision service or building a second, separately secured ingest path, with its own authentication, session binding and tests.

## Decision
- Remove phone WebRTC ingest: the receiver module, the phone camera page, the signalling and preview routes, the WebRTC runner, the phone-camera links and previews in the web portal, the WebRTC tests, and the `aiortc` and `av` dependencies.
- A phone is used as a camera by connecting it over USB in webcam mode and selecting it in the browser's camera dropdown. No code is specific to that case.
- The vision service is a small internal HTTP API (`camera/vision_api.py`, started by `run_vision_service.py`): frame recognition, embedding extraction and gallery sync, all behind the service key.
- The doorway pipeline modules are kept: SCRFD detection, ByteTrack tracking, boundary-crossing direction logic and the presence engine. They are exercised by recorded-video tests only. **Doorway mode is offline-tested and has no live ingest.**

## Consequences
**Positive**
- One ingest path, with one authentication and authorization model.
- The vision service is not reachable from outside the backend network, and serves no browser-facing content.
- Two heavy native dependencies (`aiortc`, `av`) and their version constraints are gone; the Dependabot ignore rule for `av` is removed.
- Less code to secure and maintain.

**Negative**
- A phone can no longer be used wirelessly as a camera. It needs a USB connection and webcam mode on the phone.
- There is no live doorway (entry/exit) mode. Running the doorway pipeline against a live camera again would need a new ingest path designed to the same security model as the frame route.
- The frame rate is whatever the browser sends (about 2 to 3 frames per second), which suits one-time recognition but not continuous tracking.

## Alternatives Considered
- **Keep WebRTC behind authentication.** Rejected: it still requires exposing the vision service to client devices and a second secured path.
- **Proxy WebRTC signalling through the backend.** Rejected: media would still flow to the vision service directly, and the complexity is high for a feature the current flow does not need.
- **RTSP cameras for doorway mode.** Not rejected, but out of scope here. The RTSP source and camera registry remain in the codebase; a live doorway mode would start from them.
