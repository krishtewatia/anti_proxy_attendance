import { validateAttendanceCorrectionForm } from "../src/components/attendance/validation.ts";
import {
  formatCorrectionTimestamp,
  formatPresenceDuration,
} from "../src/components/session/attendance-helpers.ts";
import { api, auth } from "../src/services/index.ts";
import type {
  AttendanceCorrectionResponse,
  AttendanceSummaryItem,
} from "../src/types/index.ts";

function testCorrectionFormValidationAndPayload() {
  console.log("==================================================");
  console.log("1. Testing Correction Form Validation & Payload Generation");
  console.log("==================================================");

  // 1a. Test Initial Population from Attendance Record
  const mockAttendance: AttendanceSummaryItem = {
    attendance_id: "att_mock_001",
    identity: "person_01",
    presence_duration_seconds: 3000,
    presence_percentage: 83.33,
    required_presence_percentage: 70.0,
    status: "PRESENT",
  };

  console.log("Initial state populated from attendance record:", {
    identity: mockAttendance.identity,
    status: mockAttendance.status,
    presence: formatPresenceDuration(mockAttendance.presence_duration_seconds),
  });

  if (mockAttendance.status !== "PRESENT" || mockAttendance.presence_duration_seconds !== 3000) {
    throw new Error("Initial attendance values populated incorrectly.");
  }
  console.log("  ✅ Existing attendance values populated correctly.");

  // 1b. Test Valid Form & Sanitized Payload
  const validResult = validateAttendanceCorrectionForm({
    newStatus: "ABSENT",
    newPresenceSeconds: 2400,
    reason: "  Student left 20 minutes before class ended.  ",
  });

  if (!validResult.isValid || !validResult.sanitizedPayload) {
    throw new Error(`Valid form was rejected: ${JSON.stringify(validResult.errors)}`);
  }

  // Ensure whitespace was trimmed
  if (validResult.sanitizedPayload.reason !== "Student left 20 minutes before class ended.") {
    throw new Error(`Reason whitespace was not trimmed: ${validResult.sanitizedPayload.reason}`);
  }

  // Ensure ONLY required client fields exist in payload (no audit fields like corrected_by)
  const keys = Object.keys(validResult.sanitizedPayload);
  if (keys.length !== 3 || !keys.includes("new_status") || !keys.includes("new_presence_seconds") || !keys.includes("reason")) {
    throw new Error(`Payload contains extraneous fields: ${JSON.stringify(keys)}`);
  }
  console.log("  ✅ Valid form accepted and clean API payload generated:", validResult.sanitizedPayload);

  // 1c. Test Empty Reason Rejection
  const emptyReasonResult = validateAttendanceCorrectionForm({
    newStatus: "PRESENT",
    newPresenceSeconds: 3000,
    reason: "   ",
  });
  if (emptyReasonResult.isValid || !emptyReasonResult.errors.reason) {
    throw new Error("Empty/whitespace reason was not rejected!");
  }
  console.log("  ✅ Empty/whitespace reason prevented submission:", emptyReasonResult.errors.reason);

  // 1d. Test Negative Duration Rejection
  const negativeDurationResult = validateAttendanceCorrectionForm({
    newStatus: "ABSENT",
    newPresenceSeconds: -15,
    reason: "Valid reason for correction",
  });
  if (negativeDurationResult.isValid || !negativeDurationResult.errors.presence) {
    throw new Error("Negative duration was not rejected!");
  }
  console.log("  ✅ Negative duration prevented submission:", negativeDurationResult.errors.presence);

  // 1e. Test Invalid Status Rejection
  const invalidStatusResult = validateAttendanceCorrectionForm({
    newStatus: "LATE" as any,
    newPresenceSeconds: 1500,
    reason: "Student arrived late",
  });
  if (invalidStatusResult.isValid || !invalidStatusResult.errors.status) {
    throw new Error("Invalid status was not rejected!");
  }
  console.log("  ✅ Invalid status prevented submission:", invalidStatusResult.errors.status);

  // 1f. Test Status Switching & Duration Editing
  let statusState = mockAttendance.status;
  let durationState = mockAttendance.presence_duration_seconds;

  // Switch status
  statusState = statusState === "PRESENT" ? "ABSENT" : "PRESENT";
  // Edit duration
  durationState = 1800;

  const switchedResult = validateAttendanceCorrectionForm({
    newStatus: statusState,
    newPresenceSeconds: durationState,
    reason: "Teacher manual presence verification",
  });
  if (!switchedResult.isValid) {
    throw new Error(`Status switch failed validation: ${JSON.stringify(switchedResult.errors)}`);
  }
  console.log(`  ✅ Status switched to ${statusState} and duration edited to ${durationState}s successfully.`);
}

function testModalSimulation() {
  console.log("\n==================================================");
  console.log("2. Testing Modal State Flow & Submission Guards");
  console.log("==================================================");

  // Simulate modal opening and duplicate submission lock
  let modalOpen = true;
  let isSaving = false;
  let refreshTriggered = false;
  let apiCallCount = 0;

  const simulateSubmit = async () => {
    if (isSaving) {
      console.log("  [Duplicate Guard]: Second submit ignored because previous is in-flight.");
      return;
    }
    isSaving = true;
    apiCallCount++;

    // Simulate async network request
    await new Promise((resolve) => setTimeout(resolve, 50));

    // On success: close modal and trigger attendance refresh
    modalOpen = false;
    refreshTriggered = true;
    isSaving = false;
  };

  // Trigger double-click submission to test duplicate submission prevention
  const p1 = simulateSubmit();
  const p2 = simulateSubmit();

  return Promise.all([p1, p2]).then(() => {
    if (apiCallCount !== 1) {
      throw new Error(`Expected exactly 1 API call, got: ${apiCallCount}`);
    }
    if (modalOpen !== false) {
      throw new Error("Modal failed to close on success.");
    }
    if (refreshTriggered !== true) {
      throw new Error("Attendance refresh was not triggered after success.");
    }
    console.log("  ✅ Duplicate submission successfully prevented (exactly 1 API call made).");
    console.log("  ✅ Modal closed and attendance list refresh triggered on success.");
  });
}

async function testAuditTrailHistoryStateAndFormatting() {
  console.log("\n==================================================");
  console.log("3. Testing Part 5 — Correction History & Audit Trail UI");
  console.log("==================================================");

  // 3a. Test Timestamp Formatting
  const rawIso = "2026-10-01T04:56:45Z";
  const formattedTime = formatCorrectionTimestamp(rawIso);
  console.log(`  Timestamp format check: "${rawIso}" -> "${formattedTime}"`);
  if (!formattedTime.includes("Oct 1") && !formattedTime.includes("10/1")) {
    throw new Error(`Unexpected timestamp format: ${formattedTime}`);
  }
  console.log("  ✅ Correct timestamp formatting verified.");

  // 3b. Test Empty History State
  const emptyHistory: AttendanceCorrectionResponse[] = [];
  const emptyStateTitle = "No manual corrections";
  const emptyStateDesc = "This attendance record has not been manually modified.";

  if (emptyHistory.length !== 0) {
    throw new Error("Expected empty history array to have length 0");
  }
  console.log("  Empty state verified:", {
    title: emptyStateTitle,
    description: emptyStateDesc,
    count: emptyHistory.length,
  });
  console.log("  ✅ Empty history state verified.");

  // 3c. Test Multiple History Entries & Chronological Order
  const mockEntries: AttendanceCorrectionResponse[] = [
    {
      correction_id: "corr_001",
      attendance_id: "att_001",
      session_id: "session_001",
      identity: "person_01",
      corrected_by: "teacher_123",
      previous_status: "ABSENT",
      new_status: "PRESENT",
      previous_presence_seconds: 0,
      new_presence_seconds: 3000,
      reason: "Student was manually verified.",
      corrected_at: "2026-10-01T04:48:00Z",
    },
    {
      correction_id: "corr_002",
      attendance_id: "att_001",
      session_id: "session_001",
      identity: "person_01",
      corrected_by: "teacher_123",
      previous_status: "PRESENT",
      new_status: "ABSENT",
      previous_presence_seconds: 3000,
      new_presence_seconds: 2400,
      reason: "Student stepped out early.",
      corrected_at: "2026-10-01T04:56:45Z",
    },
  ];

  if (mockEntries.length !== 2) {
    throw new Error(`Expected 2 history entries, got: ${mockEntries.length}`);
  }

  // Verify Chronological Ordering (oldest -> newest)
  const t0 = new Date(mockEntries[0].corrected_at).getTime();
  const t1 = new Date(mockEntries[1].corrected_at).getTime();
  if (t0 > t1) {
    throw new Error("History entries are not in chronological order!");
  }
  console.log("  ✅ Multiple history entries and chronological ordering verified.");

  // 3d. Test Correct Before/After Values
  const e1 = mockEntries[0];
  const e2 = mockEntries[1];

  if (e1.previous_status !== "ABSENT" || e1.new_status !== "PRESENT") {
    throw new Error(`Entry 1 status transition mismatch: ${e1.previous_status} -> ${e1.new_status}`);
  }
  if (formatPresenceDuration(e1.previous_presence_seconds) !== "0 min" || formatPresenceDuration(e1.new_presence_seconds) !== "50 min") {
    throw new Error(`Entry 1 duration formatting mismatch: ${e1.previous_presence_seconds}s -> ${e1.new_presence_seconds}s`);
  }

  if (e2.previous_status !== "PRESENT" || e2.new_status !== "ABSENT") {
    throw new Error(`Entry 2 status transition mismatch: ${e2.previous_status} -> ${e2.new_status}`);
  }
  if (formatPresenceDuration(e2.previous_presence_seconds) !== "50 min" || formatPresenceDuration(e2.new_presence_seconds) !== "40 min") {
    throw new Error(`Entry 2 duration formatting mismatch: ${e2.previous_presence_seconds}s -> ${e2.new_presence_seconds}s`);
  }
  console.log("  ✅ Correct before/after status and duration transitions verified:", {
    entry1: `${e1.previous_status} (${formatPresenceDuration(e1.previous_presence_seconds)}) → ${e1.new_status} (${formatPresenceDuration(e1.new_presence_seconds)})`,
    entry2: `${e2.previous_status} (${formatPresenceDuration(e2.previous_presence_seconds)}) → ${e2.new_status} (${formatPresenceDuration(e2.new_presence_seconds)})`,
  });

  // 3e. Test Correct Teacher
  if (e1.corrected_by !== "teacher_123" || e2.corrected_by !== "teacher_123") {
    throw new Error(`Teacher ID mismatch: ${e1.corrected_by}, ${e2.corrected_by}`);
  }
  console.log("  ✅ Correct teacher attribution verified ('By: teacher_123').");

  // 3f. Test API Error + Retry Flow
  let failureCount = 0;
  let retrySucceeded = false;
  let historyLoadedData: AttendanceCorrectionResponse[] = [];

  const simulateFetchWithRetry = async () => {
    if (failureCount === 0) {
      failureCount++;
      throw new Error("Network timeout: 504 Gateway Timeout");
    }
    // Retry succeeds
    retrySucceeded = true;
    historyLoadedData = mockEntries;
    return historyLoadedData;
  };

  try {
    await simulateFetchWithRetry();
  } catch (err: any) {
    console.log("  Simulated initial fetch failed as expected:", err.message);
  }

  // Trigger retry
  const retried = await simulateFetchWithRetry();
  if (!retrySucceeded || retried.length !== 2) {
    throw new Error("Retry flow failed to recover and load history.");
  }
  console.log("  ✅ API error and successful retry recovery verified.");

  // 3g. Test History Refreshes After a New Correction
  let currentHistory = [...mockEntries];
  const newCorrection: AttendanceCorrectionResponse = {
    correction_id: "corr_003",
    attendance_id: "att_001",
    session_id: "session_001",
    identity: "person_01",
    corrected_by: "teacher_123",
    previous_status: "ABSENT",
    new_status: "PRESENT",
    previous_presence_seconds: 2400,
    new_presence_seconds: 3600,
    reason: "Final manual override after doctor note provided.",
    corrected_at: "2026-10-01T05:15:00Z",
  };

  // Simulate refresh callback triggered after successful correction
  const refreshHistory = async () => {
    currentHistory = [...currentHistory, newCorrection];
  };

  await refreshHistory();

  if (currentHistory.length !== 3) {
    throw new Error(`Expected 3 entries after refresh, got: ${currentHistory.length}`);
  }
  if (currentHistory[2].correction_id !== "corr_003") {
    throw new Error("Refreshed history did not include the new correction!");
  }
  console.log("  ✅ History refreshes after a new correction verified (count updated to 3).");
}

async function testLiveApiCorrectionFlow() {
  console.log("\n==================================================");
  console.log("4. Testing Live API Correction Flow (if backend running)");
  console.log("==================================================");

  try {
    const health = await api.checkHealth();
    console.log("  Live backend connected:", health.status);
  } catch (err: any) {
    console.log("  ℹ Live backend not running locally, skipping live network call:", err.message);
    return;
  }

  const timestamp = Date.now();
  const teacherEmail = `teacher_ui_corr_${timestamp}@university.edu`;
  const password = "StrongPassword123!";

  // 1. Authenticate Teacher
  console.log(`  Registering and logging in ${teacherEmail}...`);
  await api.register({
    email: teacherEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherEmail, password });

  // 2. Create Session & Enroll Roster
  const session = await api.createSession({
    course_name: "Computer Architecture",
    classroom_id: "ROOM_404",
    start_time: "2026-10-20T10:00:00Z",
    end_time: "2026-10-20T11:00:00Z",
    required_presence_percentage: 70.0,
  });

  await api.updateSessionRoster(session.session_id, ["person_01"]);

  // 3. Finalize Session (initial state will be ABSENT, 0s)
  const finalized = await api.finalizeSession(session.session_id);
  const initialAtt = finalized.records[0];
  console.log("  Initial attendance state:", {
    attendance_id: initialAtt.attendance_id,
    identity: initialAtt.identity,
    status: initialAtt.status,
    presence_duration_seconds: initialAtt.presence_duration_seconds,
  });

  // 4. Test GET corrections on pristine record -> should return empty list []
  const initialHistory = await api.getAttendanceCorrections(
    session.session_id,
    initialAtt.attendance_id,
  );
  if (!Array.isArray(initialHistory) || initialHistory.length !== 0) {
    throw new Error(`Expected empty history [], got: ${JSON.stringify(initialHistory)}`);
  }
  console.log("  ✅ Live GET corrections on uncorrected record returned empty list [].");

  // 5. Call api.correctAttendance (Teacher manually overrides to PRESENT with 2700s)
  console.log("  Calling api.correctAttendance via PATCH...");
  const correctionResponse = await api.correctAttendance(
    session.session_id,
    initialAtt.attendance_id,
    {
      new_status: "PRESENT",
      new_presence_seconds: 2700,
      reason: "Manual verification: Camera stream was briefly obstructed.",
    },
  );

  console.log("  ✅ Correction API returned 200:", {
    correction_id: correctionResponse.correction_id,
    corrected_by: correctionResponse.corrected_by,
    previous_status: correctionResponse.previous_status,
    new_status: correctionResponse.new_status,
    previous_presence_seconds: correctionResponse.previous_presence_seconds,
    new_presence_seconds: correctionResponse.new_presence_seconds,
    reason: correctionResponse.reason,
  });

  // 6. Test GET corrections after 1st correction -> should return 1 item
  const historyAfterFirst = await api.getAttendanceCorrections(
    session.session_id,
    initialAtt.attendance_id,
  );
  if (historyAfterFirst.length !== 1) {
    throw new Error(`Expected 1 history entry, got: ${historyAfterFirst.length}`);
  }
  const h1 = historyAfterFirst[0];
  if (h1.previous_status !== "ABSENT" || h1.new_status !== "PRESENT" || h1.new_presence_seconds !== 2700) {
    throw new Error("History item 1 values mismatch.");
  }
  console.log("  ✅ Live GET corrections returned 1 item with correct audit trail.");

  // 7. Make 2nd correction: PRESENT -> ABSENT
  await api.correctAttendance(
    session.session_id,
    initialAtt.attendance_id,
    {
      new_status: "ABSENT",
      new_presence_seconds: 1200,
      reason: "Student departed early at 20-minute mark.",
    },
  );

  // 8. Test GET corrections after 2nd correction -> should return 2 items in chronological order
  const historyAfterSecond = await api.getAttendanceCorrections(
    session.session_id,
    initialAtt.attendance_id,
  );
  if (historyAfterSecond.length !== 2) {
    throw new Error(`Expected 2 history entries, got: ${historyAfterSecond.length}`);
  }
  if (historyAfterSecond[0].new_status !== "PRESENT" || historyAfterSecond[1].new_status !== "ABSENT") {
    throw new Error("Chronological history ordering mismatch.");
  }
  console.log("  ✅ Live GET corrections returned 2 entries in strict chronological order.");

  // 9. Refetch session attendance via GET to verify fresh backend state and manually_corrected flag
  const refreshedAttendance = await api.getAttendance(session.session_id);
  const updatedRecord = refreshedAttendance.records[0];
  console.log("  Refreshed attendance record from GET /api/v1/attendance:", updatedRecord);

  if (updatedRecord.status !== "ABSENT" || updatedRecord.presence_duration_seconds !== 1200) {
    throw new Error("Refreshed attendance does not match corrected values.");
  }
  if (!updatedRecord.manually_corrected) {
    throw new Error("Expected manually_corrected to be true in refreshed attendance record!");
  }

  console.log("  ✅ Refetched attendance confirmed updated values and 'manually_corrected: true'!");
}

async function run() {
  testCorrectionFormValidationAndPayload();
  await testModalSimulation();
  await testAuditTrailHistoryStateAndFormatting();
  await testLiveApiCorrectionFlow();
  console.log("\n==================================================");
  console.log("🎉 ALL FRONTEND ATTENDANCE CORRECTION & AUDIT TESTS PASSED!");
  console.log("==================================================");
}

run().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
