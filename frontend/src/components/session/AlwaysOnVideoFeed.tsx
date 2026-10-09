import React, { useEffect, useRef, useState } from "react";
import "./always-on-video-feed.css";

export interface AlwaysOnVideoFeedProps {
  sessionId: string;
  classroomId: string;
}

export const AlwaysOnVideoFeed: React.FC<AlwaysOnVideoFeedProps> = ({
  sessionId: _sessionId,
  classroomId,
}) => {
  const [webcamError, setWebcamError] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

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
    startWebcam();
    return () => {
      stopWebcam();
    };
  }, []);

  return (
    <section className="always-on-video-card" aria-label="Live Video Feed Monitor">
      {/* Video Header & Source Switcher */}
      <div className="video-card-header">
        <div className="video-header-left">
          <div className="live-pulse-badge">
            <span className="live-dot" />
            <span className="live-text">CONTINUOUS VIDEO FEED</span>
          </div>
          <span className="video-classroom-tag">Classroom: {classroomId || "—"}</span>
        </div>

      </div>

      {/* Main Viewport */}
      <div className="video-viewport-container">
        {(
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

      </div>

    </section>
  );
};
