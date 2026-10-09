import {
  classChoices,
  classEditChanges,
  classEditFields,
  classLabel,
  deleteBlockedReason,
  normalizeClassCode,
  subjectEditChanges,
  usageSummary,
  validateClassCode,
  type AdminClassRow,
  type AdminSubjectRow,
} from "../src/utils/catalog.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function classRow(overrides: Partial<AdminClassRow> = {}): AdminClassRow {
  return {
    class_id: "cls_ds_b",
    class_code: "DS-B",
    branch: "Data Science",
    section: "B",
    semester: 6,
    status: "ACTIVE",
    usage: { students: 0, teachers: 0, sessions: 0 },
    in_use: false,
    ...overrides,
  };
}

function subjectRow(overrides: Partial<AdminSubjectRow> = {}): AdminSubjectRow {
  return {
    subject_id: "sub_ml",
    name: "Machine Learning",
    code: "DS-301",
    branch: "Data Science",
    status: "ACTIVE",
    usage: { teachers: 0, sessions: 0 },
    in_use: false,
    ...overrides,
  };
}

async function runCatalogTests() {
  console.log("==================================================");
  console.log("   Classes and Subjects: Screen Rules             ");
  console.log("==================================================");

  console.log("\n[1/6] Class codes are normalized and checked...");
  expect(normalizeClassCode(" ds-b ") === "DS-B", "a code must be trimmed and upper-cased");
  expect(validateClassCode("ds-b") === null && validateClassCode("AI&ML-A") === null, "ordinary codes must be accepted");
  expect(validateClassCode("A") !== null, "a one-letter code must be refused");
  expect(validateClassCode("has space") !== null && validateClassCode("../x") !== null, "spaces and slashes must be refused");
  expect(classLabel({ class_code: "DS-B", branch: "Data Science", section: "B" }) === "DS-B · Data Science, Section B", "unexpected class label");

  console.log("[2/6] Usage is summarized in words...");
  expect(usageSummary({ students: 0, teachers: 0, sessions: 0 }) === "Not in use", "nothing must read 'Not in use'");
  expect(usageSummary({ students: 2, teachers: 1, sessions: 0 }) === "2 students, 1 teacher", "counts must be singular or plural");

  console.log("[3/6] Something in use cannot be deleted, only archived...");
  expect(deleteBlockedReason(classRow()) === null, "an unused class can be deleted");
  const used = classRow({ in_use: true, usage: { students: 3, teachers: 0, sessions: 1 } });
  expect((deleteBlockedReason(used) || "").includes("3 students, 1 session"), "the reason must say what uses it");
  expect((deleteBlockedReason(used) || "").includes("Archive"), "the reason must point to archiving");

  console.log("[4/6] Only changed class fields are sent, and never the fixed ones of a class in use...");
  const unused = classRow();
  expect(Object.keys(classEditChanges(unused, classEditFields(unused))).length === 0, "nothing changed must send nothing");
  const renamed = classEditChanges(unused, { class_code: " ds-x ", branch: "Data Science", section: "b", semester: "6" });
  expect(JSON.stringify(renamed) === JSON.stringify({ class_code: "DS-X" }), "a code change must send only the code");
  const locked = classEditChanges(used, { class_code: "DS-X", branch: "Design", section: "Z", semester: "7" });
  expect(JSON.stringify(locked) === JSON.stringify({ semester: 7 }), "a class in use must send only the semester");
  const cleared = classEditChanges(unused, { ...classEditFields(unused), semester: " " });
  expect(JSON.stringify(cleared) === JSON.stringify({ clear_semester: true }), "an emptied semester must be cleared, not sent as zero");

  console.log("[5/6] A subject in use keeps its name...");
  const subject = subjectRow();
  expect(Object.keys(subjectEditChanges(subject, { name: "Machine Learning", code: "DS-301", branch: "Data Science" })).length === 0, "nothing changed must send nothing");
  expect(subjectEditChanges(subject, { name: "ML Basics", code: "DS-301", branch: "Data Science" }).name === "ML Basics", "an unused subject can be renamed");
  const usedSubject = subjectRow({ in_use: true, usage: { teachers: 1, sessions: 0 } });
  const subjectChanges = subjectEditChanges(usedSubject, { name: "ML Basics", code: "DS-999", branch: "" });
  expect(subjectChanges.name === undefined, "a subject in use must not send a new name");
  expect(subjectChanges.code === "DS-999" && subjectChanges.branch === "", "its code and branch can still change");

  console.log("[6/6] A form offers the active classes, plus the one already chosen...");
  const active = [
    { class_code: "DS-B", branch: "Data Science", section: "B" },
    { class_code: "CS-A", branch: "Computer Science", section: "A" },
  ];
  expect(classChoices(active).length === 2, "a new record is offered only active classes");
  expect(classChoices(active, "DS-B").length === 2, "an active current class is not listed twice");
  const withArchived = classChoices(active, "DS-OLD");
  expect(withArchived.length === 3 && withArchived[2].class_code === "DS-OLD", "an archived current class must stay selectable");

  console.log("\n✅ All classes and subjects checks passed.");
}

runCatalogTests().catch((err) => {
  console.error("\n❌ Classes and subjects checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
