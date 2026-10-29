import React, { useEffect, useRef, useState } from "react";

interface SelfieCameraProps {
  onCapture: (file: File) => void;
  onClose: () => void;
}

// "Take a photo" in the page itself: the front camera, a preview, Capture and
// Retake. Many Android browsers ignore <input capture> and open the gallery,
// so the camera is opened here. When the camera cannot be used (permission
// refused, no camera), the phone's own picker is offered instead.
export const SelfieCamera: React.FC<SelfieCameraProps> = ({ onCapture, onClose }) => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [shot, setShot] = useState<{ url: string; file: File } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const open = async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setFailed("This browser cannot open the camera here.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        setReady(true);
      } catch (err: unknown) {
        const name = err instanceof Error ? err.name : "";
        setFailed(
          name === "NotAllowedError" || name === "PermissionDeniedError"
            ? "Camera access was not allowed."
            : "The camera could not be opened.",
        );
      }
    };
    void open();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  useEffect(() => () => {
    if (shot) URL.revokeObjectURL(shot.url);
  }, [shot]);

  const capture = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const file = new File([blob], "camera.jpg", { type: "image/jpeg" });
        setShot({ url: URL.createObjectURL(blob), file });
      },
      "image/jpeg",
      0.92,
    );
  };

  const use = () => {
    if (!shot) return;
    onCapture(shot.file);
    onClose();
  };

  return (
    <div className="erp-card" style={{ padding: "0.75rem", display: "grid", gap: "0.6rem", maxWidth: "26rem" }}>
      {failed ? (
        <>
          <div className="alert-banner warning" role="status">
            <span>{failed} Allow camera access for this site in the browser settings, or use the phone's camera app below.</span>
          </div>
          <div className="erp-photo-buttons">
            <label className="erp-btn erp-btn-primary" style={{ cursor: "pointer" }}>
              Open the camera app
              <input
                type="file"
                accept="image/*"
                capture="user"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) {
                    onCapture(file);
                    onClose();
                  }
                }}
              />
            </label>
            <button type="button" className="erp-btn erp-btn-secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <div style={{ position: "relative", width: "100%", aspectRatio: "3 / 4", background: "#0f172a", borderRadius: "8px", overflow: "hidden" }}>
            {/* Mirrored like a mirror while framing; the photo itself is not mirrored. */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              aria-label="Camera preview"
              style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)", display: shot ? "none" : "block" }}
            />
            {shot && <img src={shot.url} alt="Captured photo" style={{ width: "100%", height: "100%", objectFit: "cover" }} />}
            {!ready && !shot && (
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#f8fafc", fontSize: "0.9rem" }}>
                Opening the camera...
              </div>
            )}
          </div>
          <div className="erp-photo-buttons">
            {shot ? (
              <>
                <button type="button" className="erp-btn erp-btn-primary" onClick={use}>
                  Use this photo
                </button>
                <button type="button" className="erp-btn erp-btn-secondary" onClick={() => setShot(null)}>
                  Retake
                </button>
              </>
            ) : (
              <>
                <button type="button" className="erp-btn erp-btn-primary" onClick={capture} disabled={!ready}>
                  Capture
                </button>
                <button type="button" className="erp-btn erp-btn-secondary" onClick={onClose}>
                  Cancel
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
};
