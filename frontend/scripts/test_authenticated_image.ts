import {
  AuthenticatedImageController,
  fetchImageAsObjectUrl,
  resolveImageUrl,
  type ImageLoadState,
  type ImageLoaderDeps,
} from "../src/utils/authenticatedImage.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

interface Harness {
  deps: ImageLoaderDeps;
  requests: Array<{ url: string; init?: RequestInit }>;
  created: string[];
  revoked: string[];
  states: ImageLoadState[];
  token: { value: string | null };
  respond: { status: number };
  // When set, the next fetch waits until release() is called.
  gate: { promise: Promise<void> | null; release: () => void };
}

function makeHarness(): Harness {
  const requests: Harness["requests"] = [];
  const created: string[] = [];
  const revoked: string[] = [];
  const states: ImageLoadState[] = [];
  const token = { value: "token-abc" as string | null };
  const respond = { status: 200 };
  const gate: Harness["gate"] = { promise: null, release: () => {} };

  const deps: ImageLoaderDeps = {
    getToken: () => token.value,
    fetchImpl: async (url, init) => {
      requests.push({ url, init });
      if (gate.promise) {
        await gate.promise;
      }
      if (init?.signal?.aborted) {
        throw new Error("aborted");
      }
      return new Response(new Blob(["image-bytes"], { type: "image/jpeg" }), { status: respond.status });
    },
    createObjectURL: () => {
      const url = `blob:test-${created.length + 1}`;
      created.push(url);
      return url;
    },
    revokeObjectURL: (url) => {
      revoked.push(url);
    },
    baseUrl: "http://api.test:8000/",
  };
  return { deps, requests, created, revoked, states, token, respond, gate };
}

function hold(h: Harness): void {
  h.gate.promise = new Promise<void>((resolve) => {
    h.gate.release = () => {
      h.gate.promise = null;
      resolve();
    };
  });
}

async function runAuthenticatedImageTests() {
  console.log("==================================================");
  console.log("   Protected Images: Token, Object URLs, Cleanup   ");
  console.log("==================================================");

  console.log("\n[1/9] Photo paths are resolved against the API, absolute URLs are kept...");
  expect(
    resolveImageUrl("/api/v1/students/S1/photo", "http://api.test:8000/") === "http://api.test:8000/api/v1/students/S1/photo",
    "relative path not resolved against the API base",
  );
  expect(resolveImageUrl("api/x", "http://api.test:8000") === "http://api.test:8000/api/x", "missing slash not handled");
  expect(resolveImageUrl("https://cdn.test/a.jpg", "http://api.test:8000") === "https://cdn.test/a.jpg", "absolute URL changed");

  console.log("[2/9] The request carries the Authorization header and no cookies...");
  {
    const h = makeHarness();
    const objectUrl = await fetchImageAsObjectUrl("/api/v1/students/S1/photo", h.deps);
    expect(objectUrl === "blob:test-1", `unexpected object URL ${objectUrl}`);
    expect(h.requests.length === 1, "expected exactly one request");
    expect(h.requests[0].url === "http://api.test:8000/api/v1/students/S1/photo", `unexpected URL ${h.requests[0].url}`);
    const headers = new Headers(h.requests[0].init?.headers);
    expect(headers.get("Authorization") === "Bearer token-abc", "Authorization header missing or wrong");
    expect(h.requests[0].init?.credentials === "omit", "cookies must not be sent");
    expect(h.requests[0].init?.cache === "no-store", "the photo must not be kept in the HTTP cache");
  }

  console.log("[3/9] Without a token nothing is requested...");
  {
    const h = makeHarness();
    h.token.value = null;
    let threw = false;
    try {
      await fetchImageAsObjectUrl("/api/v1/students/S1/photo", h.deps);
    } catch {
      threw = true;
    }
    expect(threw, "expected an error without a token");
    expect(h.requests.length === 0, "no request may be sent without a token");
    expect(h.created.length === 0, "no object URL may be created without a token");
  }

  console.log("[4/9] A 401, 403 or 404 creates no object URL and ends in the error state...");
  for (const status of [401, 403, 404, 500]) {
    const h = makeHarness();
    h.respond.status = status;
    const controller = new AuthenticatedImageController(h.deps, (s) => h.states.push(s));
    await controller.load("/api/v1/students/S1/photo");
    expect(h.created.length === 0, `object URL created for status ${status}`);
    expect(h.states[h.states.length - 1].status === "error", `expected error state for ${status}`);
    expect(h.states[h.states.length - 1].objectUrl === null, "error state must not carry a URL");
  }

  console.log("[5/9] A loaded image goes loading -> loaded with its object URL...");
  {
    const h = makeHarness();
    const controller = new AuthenticatedImageController(h.deps, (s) => h.states.push(s));
    await controller.load("/api/v1/students/S1/photo");
    expect(h.states.map((s) => s.status).join(",") === "loading,loaded", `unexpected states ${h.states.map((s) => s.status)}`);
    expect(h.states[1].objectUrl === "blob:test-1", "loaded state has the wrong URL");
    expect(h.revoked.length === 0, "nothing should be revoked while the image is shown");

    console.log("[6/9] Unmounting revokes the object URL, exactly once...");
    controller.dispose();
    expect(h.revoked.join(",") === "blob:test-1", `expected blob:test-1 revoked, got ${h.revoked}`);
    controller.dispose();
    expect(h.revoked.length === 1, "dispose must not revoke twice");
    await controller.load("/api/v1/students/S2/photo");
    expect(h.requests.length === 1, "a disposed controller must not load again");
  }

  console.log("[7/9] Changing the source revokes the previous object URL...");
  {
    const h = makeHarness();
    const controller = new AuthenticatedImageController(h.deps, (s) => h.states.push(s));
    await controller.load("/api/v1/students/S1/photo");
    await controller.load("/api/v1/students/S2/photo");
    expect(h.created.join(",") === "blob:test-1,blob:test-2", `unexpected created ${h.created}`);
    expect(h.revoked.join(",") === "blob:test-1", `expected the first URL revoked, got ${h.revoked}`);
    await controller.load(null);
    expect(h.revoked.join(",") === "blob:test-1,blob:test-2", "clearing the source must revoke the current URL");
    expect(h.states[h.states.length - 1].status === "idle", "expected idle after clearing the source");
    controller.dispose();
    expect(h.revoked.length === 2, "nothing left to revoke");
  }

  console.log("[8/9] An image that finishes loading after unmount is never shown and is released...");
  {
    const h = makeHarness();
    const controller = new AuthenticatedImageController(h.deps, (s) => h.states.push(s));
    hold(h);
    const pending = controller.load("/api/v1/students/S1/photo");
    controller.dispose();
    h.gate.release();
    await pending;
    expect(!h.states.some((s) => s.status === "loaded"), "state was updated after unmount");
    expect(h.created.length === h.revoked.length, `created ${h.created.length} but revoked ${h.revoked.length}`);
  }

  console.log("[9/9] A slow earlier image never replaces a newer one, and every URL is released...");
  {
    const h = makeHarness();
    const controller = new AuthenticatedImageController(h.deps, (s) => h.states.push(s));
    // Let the first request get past the abort check so it really produces a URL late.
    const slowDeps: ImageLoaderDeps = {
      ...h.deps,
      fetchImpl: async (url, init) => {
        h.requests.push({ url, init });
        if (url.endsWith("/S1/photo")) {
          await new Promise((resolve) => setTimeout(resolve, 30));
        }
        return new Response(new Blob(["image-bytes"]), { status: 200 });
      },
    };
    const racing = new AuthenticatedImageController(slowDeps, (s) => h.states.push(s));
    const first = racing.load("/api/v1/students/S1/photo");
    const second = racing.load("/api/v1/students/S2/photo");
    await Promise.all([first, second]);
    const loaded = h.states.filter((s) => s.status === "loaded");
    expect(loaded.length === 1, `expected one loaded state, got ${loaded.length}`);
    racing.dispose();
    controller.dispose();
    expect(h.created.length === 2, `expected two object URLs, got ${h.created.length}`);
    expect(h.revoked.length === 2, `every object URL must be revoked; created ${h.created}, revoked ${h.revoked}`);
  }

  console.log("\nAll protected image tests passed.");
}

runAuthenticatedImageTests().catch((error) => {
  console.error("Protected image tests failed:", error);
  process.exit(1);
});
