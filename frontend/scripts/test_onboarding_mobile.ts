// Onboarding on phones: one way to start a class, two ways to add a photo,
// no password change for students, and the phone layout rules.

import { readFileSync } from "node:fs";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
  console.log(`  ✓ ${message}`);
}

const read = (path: string) => readFileSync(new URL(`../${path}`, import.meta.url), "utf-8");

async function run(): Promise<void> {
  console.log("Onboarding and phone checks");
  const flow = read("src/pages/TeacherAttendanceFlow.tsx");
  expect(flow.includes("{step === 1 && <TodayTimetable onOpenSession={handleOpenSlotSession} />}"), "Take Attendance starts classes from today's timetable");
  expect(!flow.includes("api.createSession(") && !flow.includes("START ATTENDANCE"), "no instant ad-hoc attendance");
  expect(!flow.includes("Start New Attendance") && !flow.includes("Active Session: None"), "no old Start New Attendance card");
  expect(!flow.includes("New Attendance"), "the completion page has no New Attendance");

  const wizard = read("src/components/student/SetupWizard.tsx");
  expect(wizard.includes("Take a photo") && wizard.includes("Choose from gallery"), "two ways to add a photo");
  expect(wizard.includes("<SelfieCamera") && !wizard.includes('capture: "user"'), "Take a photo opens the camera in the page, not the gallery");
  const camera = read("src/components/student/SelfieCamera.tsx");
  expect(camera.includes('facingMode: "user"') && camera.includes("Retake") && camera.includes('capture="user"'), "front camera with Retake, and the camera app when it cannot open");

  const app = read("src/App.tsx");
  const studentRoute = app.slice(app.indexOf("// Students do not change their own password"), app.indexOf("<StudentDashboard"));
  expect(studentRoute.length > 0 && !studentRoute.includes("onChangePassword"), "students have no Password button");
  expect(app.includes("mustChangePassword"), "the forced change after an admin reset stays");

  const layout = read("src/components/layout/layout.css");
  expect(layout.includes("@media (max-width: 600px)") && layout.includes("flex: 1 1 0;"), "the menu is a tab bar that fits on a phone");
  expect(layout.includes("font-size: 16px;"), "fields do not zoom the page on phones");
  expect(read("src/components/auth/auth.css").includes(".auth-password-pair"), "sign-up password fields stack on a phone");
}

run().catch((err) => {
  console.error("\n❌ Onboarding and phone checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
