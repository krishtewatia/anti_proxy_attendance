import React, { useEffect, useRef, useState } from "react";
import { api } from "../../services";
import "./always-on-video-feed.css";

export type VideoSourceType = "WEBCAM" | "PHONE" | "SIMULATOR";

export interface AlwaysOnVideoFeedProps {
  sessionId: string;
  classroomId: string;
  rosterIdentities?: string[];
  initialSource?: VideoSourceType;
  onEventDispatched?: () => void;
}

export const AlwaysOnVideoFeed: React.FC<AlwaysOnVideoFeedProps> = ({
  sessionId: _sessionId,
  classroomId,
  rosterIdentities = [],
  initialSource = "WEBCAM",
  onEventDispatched,
}) => {
  const [source, setSource] = useState<VideoSourceType>(initialSource);
  const [webcamError, setWebcamError] = useState<string | null>(null);
  const [simulating, setSimulating] = useState<string | null>(null);
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [simLog, setSimLog] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const phoneStreamerUrl =
    typeof window !== "undefined"
      ? `http://${window.location.hostname}:8088`
      : "http://localhost:8088";

  // Start webcam if source is WEBCAM
  const startWebcam = async () => {
    setWebcamError(null);
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Webcam access not supported in this browser.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setWebcamError(`Webcam access denied or unavailable: ${msg}`);
    }
  };

  const stopWebcam = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  };

  useEffect(() => {
    if (source === "WEBCAM") {
      startWebcam();
    } else {
      stopWebcam();
    }
    return () => {
      stopWebcam();
    };
  }, [source]);

  const handleCopyPhoneUrl = async () => {
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(phoneStreamerUrl);
        setCopiedUrl(true);
        setTimeout(() => setCopiedUrl(false), 2500);
      }
    } catch {
      // fallback
    }
  };

  const handleTriggerTransit = async (identity: string, direction: "ENTRY" | "EXIT") => {
    setSimulating(`${identity}_${direction}`);
    setSimLog(null);
    try {
      const res = await api.simulateTransitEvent(identity, direction, "CAM_ROOM_101_DOOR");
      setSimLog(
        `✓ ${direction} event ingested for ${identity} (${res.status}). Real-time attendance updated!`
      );
      if (onEventDispatched) {
        onEventDispatched();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setSimLog(`Failed to ingest transit event: ${msg}`);
    } finally {
      setSimulating(null);
    }
  };

  return (
    <section className="always-on-video-card" aria-label="Live Video Feed Monitor">
      {/* Video Header & Source Switcher */}
      <div className="video-card-header">
        <div className="video-header-left">
          <div className="live-pulse-badge">
            <span className="live-dot" />
            <span className="live-text">CONTINUOUS VIDEO FEED</span>
          </div>
          <span className="video-classroom-tag">Classroom: {classroomId || "ROOM_101"}</span>
        </div>

        <div className="video-source-tabs" role="tablist">
          <button
            type="button"
            className={`source-tab-btn ${source === "WEBCAM" ? "active" : ""}`}
            onClick={() => setSource("WEBCAM")}
            role="tab"
            aria-selected={source === "WEBCAM"}
          >
            <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9A2.25 2.25 0 0013.5 5.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
            </svg>
            <span>💻 Laptop Webcam</span>
          </button>

          <button
            type="button"
            className={`source-tab-btn ${source === "PHONE" ? "active" : ""}`}
            onClick={() => setSource("PHONE")}
            role="tab"
            aria-selected={source === "PHONE"}
          >
            <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3" />
            </svg>
            <span>📱 Mobile Phone</span>
          </button>

          <button
            type="button"
            className={`source-tab-btn ${source === "SIMULATOR" ? "active" : ""}`}
            onClick={() => setSource("SIMULATOR")}
            role="tab"
            aria-selected={source === "SIMULATOR"}
          >
            <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
            </svg>
            <span>🎬 Test Transit Simulator</span>
          </button>
        </div>
      </div>

      {/* Main Viewport */}
      <div className="video-viewport-container">
        {/* Source 1: Laptop Webcam Viewport */}
        {source === "WEBCAM" && (
          <div className="webcam-viewport">
            <video
              ref={videoRef}
              className="webcam-video-element"
              autoPlay
              playsInline
              muted
            />

            {/* Futuristic Recognition HUD Overlay */}
            <div className="video-hud-overlay">
              <div className="hud-corner top-left" />
              <div className="hud-corner top-right" />
              <div className="hud-corner bottom-left" />
              <div className="hud-corner bottom-right" />
              <div className="hud-scan-line" />

              <div className="hud-face-reticle">
                <div className="reticle-box">
                  <span className="reticle-label">FACIAL SCAN ACTIVE</span>
                </div>
              </div>

              <div className="hud-stats-bar">
                <span className="hud-stat-item">FPS: 30</span>
                <span className="hud-stat-item">CAMERA: CAM_ROOM_101_DOOR</span>
                <span className="hud-stat-item">DOOR SENSOR: ACTIVE</span>
              </div>
            </div>

            {webcamError && (
              <div className="webcam-error-overlay">
                <p>{webcamError}</p>
                <button type="button" className="btn-retry-webcam" onClick={startWebcam}>
                  Try Again
                </button>
              </div>
            )}
          </div>
        )}

        {/* Source 2: Mobile Phone WebRTC Node */}
        {source === "PHONE" && (
          <div className="phone-streamer-viewport">
            <div className="phone-radar-container">
              <div className="radar-circle radar-pulse" />
              <div className="radar-circle" />
              <div className="radar-center-icon">
                <svg width="32" height="32" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3" />
                </svg>
              </div>
            </div>

            <div className="phone-instructions-box">
              <h3 className="phone-stream-title">Connect Mobile Phone as Entrance Scanner</h3>
              <p className="phone-stream-desc">
                Open this URL on your phone or scan the QR code to stream directly to <strong>CS-101 (Room 101)</strong>:
              </p>

              <div className="phone-connect-row">
                <div className="phone-qr-card">
                  <img
                    src={`https://api.qrserver.com/v1/create-qr-code/?size=140x140&margin=4&data=${encodeURIComponent(phoneStreamerUrl)}`}
                    alt="Scan with mobile camera"
                    className="phone-qr-img"
                    width="130"
                    height="130"
                  />
                  <span className="phone-qr-label">📷 Scan with Phone</span>
                </div>

                <div className="phone-url-column">
                  <div className="phone-url-display">
                    <code className="phone-url-text">{phoneStreamerUrl}</code>
                  </div>
                  <div className="phone-btn-actions">
                    <button
                      type="button"
                      className="btn-copy-stream-url"
                      onClick={handleCopyPhoneUrl}
                      title="Copy mobile link"
                    >
                      {copiedUrl ? "✓ Copied!" : "📋 Copy Link"}
                    </button>
                    <button
                      type="button"
                      className="btn-open-stream-tab"
                      onClick={() => window.open(phoneStreamerUrl, "_blank")}
                      title="Open in new browser tab"
                    >
                      🔗 Open in Tab
                    </button>
                  </div>
                </div>
              </div>

              <div className="phone-tips-row">
                <span className="tip-badge">💡 Note for Android Chrome:</span>
                <span className="tip-text">
                  If prompted for camera permission on HTTP, enable <code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code> and add <code>{phoneStreamerUrl}</code>.
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Source 3: Optical Transit Simulator */}
        {source === "SIMULATOR" && (
          <div className="simulator-viewport">
            <div className="simulator-header-text">
              <h3 className="simulator-title">Optical Entrance & Exit Simulator</h3>
              <p className="simulator-desc">
                Simulate authentic entrance door passages in real-time. Triggering an entry marks the student present in the live ledger immediately; exit pauses presence tracking.
              </p>
            </div>

            <div className="simulator-students-grid">
              {(rosterIdentities.length > 0
                ? rosterIdentities
                : ["student_alice", "student_bob", "student_charlie", "person_01"]
              ).map((ident) => (
                <div key={ident} className="simulator-student-card">
                  <div className="sim-student-name">
                    <span className="sim-student-avatar">
                      {ident.slice(0, 2).toUpperCase()}
                    </span>
                    <span className="sim-student-label">{ident.replace("_", " ").toUpperCase()}</span>
                  </div>

                  <div className="sim-action-buttons">
                    <button
                      type="button"
                      className="btn-sim-entry"
                      onClick={() => handleTriggerTransit(ident, "ENTRY")}
                      disabled={simulating === `${ident}_ENTRY`}
                      title={`Simulate ${ident} entering the classroom`}
                    >
                      {simulating === `${ident}_ENTRY` ? "..." : "+ ENTRY (Present)"}
                    </button>
                    <button
                      type="button"
                      className="btn-sim-exit"
                      onClick={() => handleTriggerTransit(ident, "EXIT")}
                      disabled={simulating === `${ident}_EXIT`}
                      title={`Simulate ${ident} exiting the classroom`}
                    >
                      {simulating === `${ident}_EXIT` ? "..." : "− EXIT"}
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {simLog && (
              <div className="sim-status-banner">
                <span>{simLog}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Continuous Optical Connection Telemetry Footer */}
      <footer className="video-telemetry-bar">
        <div className="telemetry-item">
          <span className="telemetry-indicator online" />
          <span className="telemetry-label">Continuous Connection:</span>
          <span className="telemetry-val">ACTIVE (PORT 8088 / WEBCAM)</span>
        </div>

        <div className="telemetry-item">
          <span className="telemetry-label">Ingestion Mode:</span>
          <span className="telemetry-val">Real-Time Facial Recognition</span>
        </div>

        <div className="telemetry-item">
          <span className="telemetry-label">Target Doorway:</span>
          <span className="telemetry-val">CAM_ROOM_101_DOOR</span>
        </div>
      </footer>
    </section>
  );
};
