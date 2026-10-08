import React, { useEffect, useRef, useState } from "react";
import { getApiBaseUrl } from "../../services/api.ts";
import { getStoredToken } from "../../services/auth.ts";
import {
  AuthenticatedImageController,
  IDLE_STATE,
  type ImageLoadState,
} from "../../utils/authenticatedImage.ts";

interface AuthenticatedImageProps {
  // API path or URL of a protected image, e.g. a student's photo_url.
  src?: string | null;
  alt: string;
  style?: React.CSSProperties;
  className?: string;
  // Shown while loading, when there is no image, and when it cannot be loaded.
  fallback?: React.ReactNode;
}

// An <img> for images that need the user's token. The image is fetched with
// the Authorization header and shown through an object URL, which is revoked
// when the source changes and when the component unmounts.
export const AuthenticatedImage: React.FC<AuthenticatedImageProps> = ({
  src,
  alt,
  style,
  className,
  fallback = null,
}) => {
  const [state, setState] = useState<ImageLoadState>(IDLE_STATE);
  const controllerRef = useRef<AuthenticatedImageController | null>(null);

  // One controller per mounted component; disposing it revokes the object URL.
  useEffect(() => {
    const controller = new AuthenticatedImageController(
      {
        getToken: getStoredToken,
        fetchImpl: (input, init) => fetch(input, init),
        createObjectURL: (blob) => URL.createObjectURL(blob),
        revokeObjectURL: (url) => URL.revokeObjectURL(url),
        baseUrl: getApiBaseUrl(),
      },
      setState,
    );
    controllerRef.current = controller;
    return () => {
      controller.dispose();
      controllerRef.current = null;
    };
  }, []);

  useEffect(() => {
    void controllerRef.current?.load(src);
  }, [src]);

  if (state.status !== "loaded") {
    return <>{fallback}</>;
  }
  return <img src={state.objectUrl} alt={alt} style={style} className={className} />;
};
