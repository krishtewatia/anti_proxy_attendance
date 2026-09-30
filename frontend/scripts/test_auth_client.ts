import { auth } from "../src/services/index.ts";
import type { UserResponse } from "../src/types/index.ts";

async function runAuthClientTests() {
  console.log("==================================================");
  console.log("       STEP 2C.1: Frontend Auth Client Unit Test  ");
  console.log("==================================================");

  // 1. Initial State
  console.log("\n[1/5] Testing initial storage state...");
  auth.logout();
  if (auth.isAuthenticated()) {
    throw new Error("Expected isAuthenticated to be false initially");
  }
  if (auth.getStoredToken() !== null) {
    throw new Error("Expected getStoredToken to be null initially");
  }
  if (auth.getStoredUser() !== null) {
    throw new Error("Expected getStoredUser to be null initially");
  }
  console.log("✅ Initial unauthenticated state verified.");

  // 2. Setting Stored Auth
  console.log("\n[2/5] Testing setting stored credentials...");
  const dummyUser: UserResponse = {
    user_id: "user_test_teacher_1",
    email: "teacher.test@example.com",
    role: "TEACHER",
    is_active: true,
  };
  const dummyToken = "mock.jwt.token";

  auth.setStoredAuth(dummyToken, dummyUser);
  console.log("✅ Credentials saved to storage.");

  // 3. Verifying Stored Auth State
  console.log("\n[3/5] Testing credentials retrieval and state...");
  if (!auth.isAuthenticated()) {
    throw new Error("Expected isAuthenticated to be true after setStoredAuth");
  }
  if (auth.getStoredToken() !== dummyToken) {
    throw new Error(`Token mismatch: expected ${dummyToken}, got ${auth.getStoredToken()}`);
  }
  const retrievedUser = auth.getStoredUser();
  if (!retrievedUser || retrievedUser.user_id !== dummyUser.user_id || retrievedUser.email !== dummyUser.email) {
    throw new Error("Stored user mismatch");
  }
  console.log("✅ Stored credentials correctly retrieved:", retrievedUser);

  // 4. Logout / Clearing Storage
  console.log("\n[4/5] Testing auth.logout()...");
  auth.logout();
  if (auth.isAuthenticated()) {
    throw new Error("Expected isAuthenticated to be false after logout");
  }
  if (auth.getStoredToken() !== null) {
    throw new Error("Expected getStoredToken to be null after logout");
  }
  if (auth.getStoredUser() !== null) {
    throw new Error("Expected getStoredUser to be null after logout");
  }
  console.log("✅ Storage cleared after logout.");

  // 5. Corrupt Data Handling
  console.log("\n[5/5] Testing corrupt user data recovery...");
  auth.setStoredAuth("dummy_token", dummyUser);
  // Intentionally corrupt storage
  const memoryOrLocalStorage = (globalThis as any).localStorage;
  if (memoryOrLocalStorage) {
    memoryOrLocalStorage.setItem("anti_proxy_user", "invalid json {{{");
    const safeUser = auth.getStoredUser();
    if (safeUser !== null) {
      throw new Error("Expected corrupt user JSON to safely return null");
    }
  }
  console.log("✅ Corrupt data safely handled.");

  console.log("\n==================================================");
  console.log("✅ ALL STEP 2C.1 AUTH CLIENT TESTS PASSED!");
  console.log("==================================================");
}

runAuthClientTests().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
