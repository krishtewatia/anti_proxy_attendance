import { api } from "../src/services/index.ts";
import type {
  SessionCreate,
  SessionRosterUpdate,
  VisionEventCreate,
} from "../src/types/index.ts";

async function runIntegrationTest() {
  console.log("==================================================");
  console.log("   STEP 2A.3: Frontend <-> FastAPI Integration    ");
  console.log("==================================================");

  // 1. Health check
  console.log("\n[1/7] Testing api.checkHealth()...");
  const health = await api.checkHealth();
  console.log("✅ Health response:", health);
  if (health.status !== "healthy") {
    throw new Error(`Expected status 'healthy', got '${health.status}'`);
  }

  // 2. Create session
  const sessionData: SessionCreate = {
    course_name: "CS101 - Distributed Systems",
    classroom_id: "LH-101",
    start_time: "2026-09-29T10:00:00Z",
    end_time: "2026-09-29T11:00:00Z",
    required_presence_percentage: 75.0,
  };

  console.log("\n[2/7] Testing api.createSession()...");
  const session = await api.createSession(sessionData);
  console.log("✅ Created session:", session);
  if (!session.session_id) {
    throw new Error("Missing session_id in created session");
  }
  const sessionId = session.session_id;

  // 3. Update roster
  console.log(`\n[3/7] Testing api.updateRoster() for session ${sessionId}...`);
  const rosterData: SessionRosterUpdate = {
    identities: ["student_alice", "student_bob", "student_charlie"],
  };
  const roster = await api.updateRoster(sessionId, rosterData);
  console.log("✅ Updated roster:", roster);
  if (roster.identities.length !== 3) {
    throw new Error("Roster count mismatch");
  }

  // 4. Get roster
  console.log(`\n[4/7] Testing api.getRoster() for session ${sessionId}...`);
  const fetchedRoster = await api.getRoster(sessionId);
  console.log("✅ Retrieved roster:", fetchedRoster);
  if (!fetchedRoster.identities.includes("student_alice")) {
    throw new Error("Fetched roster missing student_alice");
  }

  // 5. Ingest vision events for student_alice
  // Alice enters at 10:05 and exits at 10:55 (50 mins = 83.3% > 75%)
  console.log("\n[5/7] Testing api.ingestVisionEvent()...");
  const entryEvent: VisionEventCreate = {
    event_id: `evt_entry_${Date.now()}`,
    camera_id: "cam_door_in",
    track_id: 101,
    identity: "student_alice",
    direction: "ENTRY",
    timestamp: "2026-09-29T10:05:00Z",
    evidence: {
      peak_similarity: 0.94,
      mean_similarity: 0.91,
      supporting_frames: 42,
      total_frames: 45,
      consistency_pct: 93.3,
    },
  };
  const entryRes = await api.ingestVisionEvent(entryEvent);
  console.log("✅ Ingested ENTRY event:", entryRes);

  const exitEvent: VisionEventCreate = {
    event_id: `evt_exit_${Date.now()}`,
    camera_id: "cam_door_out",
    track_id: 102,
    identity: "student_alice",
    direction: "EXIT",
    timestamp: "2026-09-29T10:55:00Z",
    evidence: {
      peak_similarity: 0.95,
      mean_similarity: 0.92,
      supporting_frames: 40,
      total_frames: 44,
      consistency_pct: 90.9,
    },
  };
  const exitRes = await api.ingestVisionEvent(exitEvent);
  console.log("✅ Ingested EXIT event:", exitRes);

  // 6. Finalize session
  console.log(`\n[6/7] Testing api.finalizeSession() for session ${sessionId}...`);
  const finalization = await api.finalizeSession(sessionId);
  console.log("✅ Finalization response:", finalization);
  if (finalization.records.length !== 3) {
    throw new Error(`Expected 3 finalization records, got ${finalization.records.length}`);
  }

  // 7. Get attendance summary
  console.log(`\n[7/7] Testing api.getAttendance() for session ${sessionId}...`);
  const attendance = await api.getAttendance(sessionId);
  console.log("✅ Attendance summary:", JSON.stringify(attendance, null, 2));

  const alice = attendance.records.find((r) => r.identity === "student_alice");
  const bob = attendance.records.find((r) => r.identity === "student_bob");
  const charlie = attendance.records.find((r) => r.identity === "student_charlie");

  if (!alice || alice.status !== "PRESENT") {
    throw new Error(`Expected student_alice to be PRESENT, got: ${alice?.status}`);
  }
  if (!bob || bob.status !== "ABSENT") {
    throw new Error(`Expected student_bob to be ABSENT, got: ${bob?.status}`);
  }
  if (!charlie || charlie.status !== "ABSENT") {
    throw new Error(`Expected student_charlie to be ABSENT, got: ${charlie?.status}`);
  }

  console.log("\n==================================================");
  console.log("🎉 ALL INTEGRATION CHECKS PASSED!");
  console.log("   - Frontend Typed API Client <-> FastAPI: 100% OK");
  console.log("   - End-to-end Session, Roster, Events, Attendance verified");
  console.log("==================================================");
}

runIntegrationTest().catch((err) => {
  console.error("\n❌ Integration test failed:", err);
  process.exit(1);
});
