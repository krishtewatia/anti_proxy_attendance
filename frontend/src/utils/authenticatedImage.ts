// Loading images that need the user's token.
//
// A plain <img src> cannot send an Authorization header, so protected images
// (student profile photos) are fetched with the token, turned into a Blob and
// shown through an object URL. Every object URL created here is revoked when
// it is replaced or when the owner goes away, so the image data is released.

export interface ImageLoaderDeps {
  getToken: () => string | null;
  fetchImpl: (input: string, init?: RequestInit) => Promise<Response>;
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  baseUrl: string;
}

export type ImageLoadState =
  | { status: "idle"; objectUrl: null }
  | { status: "loading"; objectUrl: null }
  | { status: "loaded"; objectUrl: string }
  | { status: "error"; objectUrl: null };

export const IDLE_STATE: ImageLoadState = { status: "idle", objectUrl: null };

// A path such as "/api/v1/students/X/photo" is relative to the API, not to the page.
export function resolveImageUrl(url: string, baseUrl: string): string {
  if (/^https?:\/\//i.test(url)) {
    return url;
  }
  const base = baseUrl.replace(/\/+$/, "");
  return `${base}${url.startsWith("/") ? "" : "/"}${url}`;
}

// Fetch one protected image and return an object URL for it.
// Throws when there is no token or the server does not return the image.
export async function fetchImageAsObjectUrl(
  url: string,
  deps: ImageLoaderDeps,
  signal?: AbortSignal,
): Promise<string> {
  const token = deps.getToken();
  if (!token) {
    throw new Error("Not signed in");
  }
  const response = await deps.fetchImpl(resolveImageUrl(url, deps.baseUrl), {
    headers: { Authorization: `Bearer ${token}` },
    // The token travels in the header only; no cookies, and nothing kept in the HTTP cache.
    credentials: "omit",
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Image request failed with status ${response.status}`);
  }
  return deps.createObjectURL(await response.blob());
}

// Owns at most one object URL at a time for one image slot on the page.
export class AuthenticatedImageController {
  private currentObjectUrl: string | null = null;
  private requestId = 0;
  private abort: AbortController | null = null;
  private disposed = false;
  private readonly deps: ImageLoaderDeps;
  private readonly onChange: (state: ImageLoadState) => void;

  constructor(deps: ImageLoaderDeps, onChange: (state: ImageLoadState) => void) {
    this.deps = deps;
    this.onChange = onChange;
  }

  // Show the image at `url`, or nothing when it is empty.
  async load(url: string | null | undefined): Promise<void> {
    if (this.disposed) {
      return;
    }
    const id = ++this.requestId;
    this.abort?.abort();
    this.abort = null;
    this.release();

    if (!url) {
      this.onChange(IDLE_STATE);
      return;
    }

    const controller = new AbortController();
    this.abort = controller;
    this.onChange({ status: "loading", objectUrl: null });

    let objectUrl: string;
    try {
      objectUrl = await fetchImageAsObjectUrl(url, this.deps, controller.signal);
    } catch {
      if (!this.disposed && id === this.requestId) {
        this.onChange({ status: "error", objectUrl: null });
      }
      return;
    }

    // The component went away, or a newer image was requested, while this one
    // was loading: the URL was never shown, so release it straight away.
    if (this.disposed || id !== this.requestId) {
      this.deps.revokeObjectURL(objectUrl);
      return;
    }

    this.currentObjectUrl = objectUrl;
    this.onChange({ status: "loaded", objectUrl });
  }

  // Call when the owner unmounts. Safe to call more than once.
  dispose(): void {
    this.disposed = true;
    this.requestId++;
    this.abort?.abort();
    this.abort = null;
    this.release();
  }

  private release(): void {
    if (this.currentObjectUrl) {
      this.deps.revokeObjectURL(this.currentObjectUrl);
      this.currentObjectUrl = null;
    }
  }
}
