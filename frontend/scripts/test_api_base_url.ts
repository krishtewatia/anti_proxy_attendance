// Where the browser sends API requests.
// The Docker image is built with VITE_API_BASE_URL=same-origin, so the page
// calls the API on the address it was loaded from (the reverse proxy), never
// on a separate backend port that a deployment does not publish.

import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function baseUrlWith(value: string | undefined): string {
  const env = { ...process.env };
  delete env.VITE_API_BASE_URL;
  if (value !== undefined) env.VITE_API_BASE_URL = value;
  const result = spawnSync(
    "node",
    ["--experimental-strip-types", "-e", 'import("./src/services/api.ts").then((m) => console.log(JSON.stringify(m.getApiBaseUrl())))'],
    { env, encoding: "utf-8" },
  );
  return JSON.parse(result.stdout.trim().split("\n").pop() || '"<no output>"');
}

async function run() {
  console.log("==================================================");
  console.log("   API Address: Same Origin Behind The Proxy      ");
  console.log("==================================================");

  console.log("\n[1/3] \"same-origin\" means relative requests...");
  expect(baseUrlWith("same-origin") === "", `same-origin must give an empty base (got "${baseUrlWith("same-origin")}")`);

  console.log("[2/3] An explicit address is still used as given...");
  expect(baseUrlWith("http://127.0.0.1:9000") === "http://127.0.0.1:9000", "an explicit address must be kept");
  expect(baseUrlWith(undefined) === "http://localhost:8000", "outside a browser with nothing set, the local backend is the default");

  console.log("[3/3] The image is built for same-origin and nginx accepts frames and photos...");
  const dockerfile = readFileSync("Dockerfile", "utf-8");
  expect(/ARG VITE_API_BASE_URL="same-origin"/.test(dockerfile), "the image must default to same-origin API calls");
  expect(/ENV VITE_API_BASE_URL=\$\{VITE_API_BASE_URL\}/.test(dockerfile), "the build must see VITE_API_BASE_URL");
  const nginx = readFileSync("nginx.conf", "utf-8");
  const api = nginx.slice(nginx.indexOf("location ^~ /api/"), nginx.indexOf("location ^~ /uploads/"));
  expect(/client_max_body_size\s+1[0-9]m;/.test(api), "the API proxy must accept camera frames and enrollment photos");
  const source = readFileSync("src/services/api.ts", "utf-8");
  expect(source.includes('VITE_API_BASE_URL === SAME_ORIGIN'), "api.ts must recognise the same-origin setting");

  console.log("\n✅ All API address checks passed.");
}

run().catch((err) => {
  console.error("\n❌ API address checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
