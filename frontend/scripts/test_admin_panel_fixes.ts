// Regression checks for five admin-panel bugs:
//   b. finished sessions did not show as completed (frontend looked for a status the backend never writes)
//   c. the sidebar moved with the page length and long lists pushed everything down
//   d. the logo and title were not a link
//   e. a made-up institution name was shown; the name now comes from one setting
// (a. "admin cannot open a session" is covered by backend/tests/test_admin_session_access.py)

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import {
  SESSION_STATUS_FILTERS,
  isSessionCompleted,
  matchesStatusFilter,
  paginate,
  sessionStatusBadgeClass,
  sessionStatusLabel,
} from "../src/utils/sessions.ts";
import { APP_NAME } from "../src/config/app.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, found);
    } else if (/\.(tsx?|css|html)$/.test(name)) {
      found.push(path);
    }
  }
  return found;
}

// The body of the first rule whose selector is exactly `selector` (the base rule
// comes before any @media override in these files).
function cssRule(css: string, selector: string): string {
  const top = css;
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = top.match(new RegExp(`(^|\\n)${escaped} \\{([^}]*)\\}`));
  if (!match) {
    throw new Error(`no CSS rule for ${selector}`);
  }
  return match[2];
}

async function run() {
  console.log("==================================================");
  console.log("   Admin Panel Fixes: Regression Checks           ");
  console.log("==================================================");

  console.log("\n[1/6] The statuses the backend writes are shown in words (bug b)...");
  expect(sessionStatusLabel("FINALIZED") === "Completed", "a finalized session must read Completed");
  expect(sessionStatusLabel("COMPLETED") === "Completed", "COMPLETED is accepted as the same thing");
  expect(sessionStatusLabel("ACTIVE") === "In Progress", "an active session must read In Progress");
  expect(sessionStatusLabel("SCHEDULED") === "Scheduled", "a scheduled session must read Scheduled");
  expect(sessionStatusLabel("finalized") === "Completed", "case must not matter");
  expect(isSessionCompleted("FINALIZED") && !isSessionCompleted("ACTIVE") && !isSessionCompleted("SCHEDULED"), "only finished sessions are completed");
  expect(sessionStatusBadgeClass("ACTIVE") !== sessionStatusBadgeClass("FINALIZED"), "active and completed must look different");
  expect(sessionStatusBadgeClass("SCHEDULED") !== sessionStatusBadgeClass("FINALIZED"), "scheduled and completed must look different");

  console.log("[2/6] The Completed filter finds finalized sessions (bug b)...");
  const statuses = ["FINALIZED", "FINALIZED", "SCHEDULED", "ACTIVE"];
  const count = (filter: Parameters<typeof matchesStatusFilter>[1]) =>
    statuses.filter((status) => matchesStatusFilter(status, filter)).length;
  expect(count("COMPLETED") === 2, "the Completed filter must match FINALIZED sessions");
  expect(count("ACTIVE") === 1 && count("SCHEDULED") === 1 && count("ALL") === 4, "each filter must match its own status");
  expect(SESSION_STATUS_FILTERS.map((f) => f.value).join(",") === "ALL,SCHEDULED,ACTIVE,COMPLETED", "every backend status must have a filter");
  for (const file of sourceFiles("src")) {
    const text = readFileSync(file, "utf-8");
    if (file.replace(/\\/g, "/").endsWith("utils/sessions.ts")) continue;
    expect(!/status === ["']COMPLETED["']/.test(text) || file.includes("SessionsTab"), `${file} compares a session status with COMPLETED, which the backend never sends`);
  }

  console.log("[3/6] Long lists are shown a page at a time (bug c)...");
  const sessions = Array.from({ length: 45 }, (_, index) => index + 1);
  const first = paginate(sessions, 1, 15);
  expect(first.items.length === 15 && first.pageCount === 3 && first.from === 1 && first.to === 15, "page 1 of 45 by 15");
  const last = paginate(sessions, 3, 15);
  expect(last.items[0] === 31 && last.items.length === 15 && last.to === 45, "page 3 of 45 by 15");
  expect(paginate(sessions, 99, 15).page === 3 && paginate(sessions, -4, 15).page === 1, "a page outside the range is brought back inside");
  const empty = paginate([], 1, 15);
  expect(empty.items.length === 0 && empty.pageCount === 1 && empty.from === 0 && empty.to === 0, "an empty list is one empty page");
  expect(paginate(sessions.slice(0, 16), 2, 15).items.length === 1, "a last page can be short");

  console.log("[4/6] The sidebar is fixed and only the content scrolls (bug c)...");
  const layout = readFileSync("src/components/layout/layout.css", "utf-8");
  const shell = cssRule(layout, ".erp-app-shell");
  expect(/height:\s*100d?vh/.test(shell) && /overflow:\s*hidden/.test(shell), "the shell must be exactly as tall as the window");
  const sidebar = cssRule(layout, ".erp-sidebar");
  expect(!sidebar.includes("space-between"), "the sidebar must not spread its menu over the page height");
  expect(/overflow-y:\s*auto/.test(sidebar), "the sidebar must scroll on its own when the window is short");
  const body = cssRule(layout, ".erp-body");
  expect(!/min-height:\s*calc/.test(body) && /min-height:\s*0/.test(body), "the body row must not grow with the content");
  expect(/overflow-y:\s*auto/.test(cssRule(layout, ".erp-content-pane")), "the content pane is what scrolls");
  expect(/overflow-x:\s*auto/.test(cssRule(readFileSync("src/index.css", "utf-8"), ".erp-table-container")), "a wide table must scroll inside its own box");

  console.log("[5/6] The logo and title link to the right home page (bug d)...");
  const appLayout = readFileSync("src/components/layout/AppLayout.tsx", "utf-8");
  expect(/<a\s[^>]*className="erp-header-left erp-home-link"[^>]*href=\{getDashboardPath\(user\.role\)\}/s.test(appLayout), "the signed-in header must link to the role's dashboard");
  const authLayout = readFileSync("src/components/auth/AuthLayout.tsx", "utf-8");
  expect(/<a className="erp-auth-home-link" href="\/"/.test(authLayout), "the sign-in page header must link to the public home page");
  const app = readFileSync("src/App.tsx", "utf-8");
  expect((app.match(/onGoHome=\{goHome\}/g) || []).length === (app.match(/<AppLayout\r?\n/g) || []).length, "every signed-in layout must be given the home action");

  console.log("[6/6] The product name comes from one setting; no made-up institution (bug e)...");
  expect(APP_NAME === "Anti-Proxy Attendance System", `unexpected default name: ${APP_NAME}`);
  const renamed = spawnSync(
    "node",
    ["--experimental-strip-types", "-e", 'import("./src/config/app.ts").then((m) => console.log(m.APP_NAME))'],
    { env: { ...process.env, VITE_APP_NAME: "Renamed Product" }, encoding: "utf-8" },
  );
  expect(renamed.stdout.trim() === "Renamed Product", `VITE_APP_NAME must rename the product (got "${renamed.stdout.trim()}")`);
  const banned = [/Apex Institute/i, /Institute of Technology/i, /COLLEGE ERP/i, /Office of Academic Affairs/i, /Student Information System/i];
  for (const file of [...sourceFiles("src"), "index.html"]) {
    const text = readFileSync(file, "utf-8");
    for (const pattern of banned) {
      expect(!pattern.test(text), `${file} still contains ${pattern}`);
    }
  }
  expect(readFileSync("index.html", "utf-8").includes("<title>Anti-Proxy Attendance System</title>"), "the page title must be the product name");
  expect(readFileSync("src/main.tsx", "utf-8").includes("document.title = APP_NAME"), "the browser tab must show the configured name");
  for (const file of ["src/components/layout/AppLayout.tsx", "src/components/auth/AuthLayout.tsx"]) {
    expect(readFileSync(file, "utf-8").includes("{APP_NAME}"), `${file} must show the configured name`);
  }

  console.log("\n✅ All admin panel regression checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Admin panel regression checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
