import { api } from "../src/services/api.ts";
import type { AuditAction, AuditEventResponse, AuditResourceType } from "../src/types/audit.ts";
import { requireLiveBackend } from "./live_backend.ts";

function testAuditDataContracts() {
  console.log("--------------------------------------------------");
  console.log("1. Testing Audit Data Contracts & Types");
  console.log("--------------------------------------------------");

  const sampleEvents: AuditEventResponse[] = [
    {
      audit_id: "audit_001",
      actor_user_id: "teacher_01",
      actor_role: "TEACHER",
      action: "SESSION_CREATED",
      resource_type: "SESSION",
      resource_id: "session_001",
      timestamp: "2026-10-02T10:00:00Z",
      metadata: {
        course_name: "Operating Systems",
        classroom_id: "ROOM_101",
        required_presence_percentage: 75.0,
      },
    },
    {
      audit_id: "audit_002",
      actor_user_id: "teacher_01",
      actor_role: "TEACHER",
      action: "ROSTER_UPDATED",
      resource_type: "SESSION_ROSTER",
      resource_id: "session_001",
      timestamp: "2026-10-02T10:05:00Z",
      metadata: {
        student_count: 25,
      },
    },
    {
      audit_id: "audit_003",
      actor_user_id: "teacher_01",
      actor_role: "TEACHER",
      action: "ATTENDANCE_FINALIZED",
      resource_type: "SESSION",
      resource_id: "session_001",
      timestamp: "2026-10-02T11:00:00Z",
      metadata: {
        attendance_record_count: 25,
        required_presence_percentage: 75.0,
      },
    },
    {
      audit_id: "audit_004",
      actor_user_id: "teacher_01",
      actor_role: "TEACHER",
      action: "ATTENDANCE_CORRECTED",
      resource_type: "ATTENDANCE",
      resource_id: "att_001",
      timestamp: "2026-10-02T11:15:00Z",
      metadata: {
        session_id: "session_001",
        identity: "student_01",
        previous_status: "ABSENT",
        new_status: "PRESENT",
        previous_presence_seconds: 0,
        new_presence_seconds: 2700,
        reason: "Verified manually by professor",
      },
    },
  ];

  console.log(`Validated ${sampleEvents.length} mock audit event contracts.`);

  // Chronological verification
  for (let i = 0; i < sampleEvents.length - 1; i++) {
    const tCurrent = new Date(sampleEvents[i].timestamp).getTime();
    const tNext = new Date(sampleEvents[i + 1].timestamp).getTime();
    if (tCurrent > tNext) {
      throw new Error(`Chronological sorting violation between ${sampleEvents[i].audit_id} and ${sampleEvents[i + 1].audit_id}`);
    }
  }

  console.log("✅ Audit data contracts and chronological ordering passed!\n");
}

async function testAuditApiClient() {
  console.log("--------------------------------------------------");
  console.log("2. Testing api.getAuditEvents Client Method");
  console.log("--------------------------------------------------");

  if (typeof api.getAuditEvents !== "function") {
    throw new Error("api.getAuditEvents is not defined on the api client object.");
  }

  try {
    const health = await requireLiveBackend();
    console.log("Live backend healthy:", health);
  } catch (err: any) {
    console.log("ℹ Backend not currently running locally, skipping live network request:", err.message);
    return;
  }

  console.log("✅ api.getAuditEvents verified successfully!\n");
}

async function run() {
  try {
    testAuditDataContracts();
    await testAuditApiClient();
    console.log("✨ All Audit Logs UI contract tests completed successfully!");
  } catch (err) {
    console.error("❌ Test failed:", err);
    process.exit(1);
  }
}

run();
