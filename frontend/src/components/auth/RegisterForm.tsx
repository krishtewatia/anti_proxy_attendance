import React, { useState, useEffect } from "react";
import { api } from "../../services";

interface RegisterFormProps {
  onSuccess: (registeredEmail: string) => void;
  onSwitchToLogin: () => void;
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const RegisterForm: React.FC<RegisterFormProps> = ({
  onSuccess,
  onSwitchToLogin,
}) => {
  const [role, setRole] = useState<"STUDENT" | "TEACHER">("STUDENT");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Student-specific fields
  const [studentId, setStudentId] = useState("");
  const [rollNumber, setRollNumber] = useState("");
  const [branch, setBranch] = useState("Data Science");
  const [section, setSection] = useState("B");
  const [photoBase64, setPhotoBase64] = useState<string | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);

  // Teacher-specific fields
  const [teacherId, setTeacherId] = useState("");
  const [department, setDepartment] = useState("Data Science");

  // Dynamic academic branches & sections
  const [branches, setBranches] = useState<string[]>(["Data Science", "Computer Science", "AI & ML"]);
  const [sections, setSections] = useState<string[]>(["A", "B", "C"]);

  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    // Attempt to load live academic structure for dropdowns
    api.getAcademicStructure()
      .then((struct) => {
        if (struct.branches && struct.branches.length > 0) {
          setBranches(struct.branches.map((b) => b.name));
          const currentB = struct.branches.find((b) => b.name === "Data Science") || struct.branches[0];
          if (currentB && currentB.sections) {
            setSections(currentB.sections);
          }
        }
      })
      .catch(() => {
        // Fallback to default lists
      });
  }, []);

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith("image/")) {
      setErrorMessage("Please upload a valid image file (JPG or PNG).");
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const b64 = reader.result as string;
      setPhotoBase64(b64);
      setPhotoPreview(b64);
    };
    reader.readAsDataURL(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    const trimmedEmail = email.trim();
    const trimmedName = name.trim();

    if (!trimmedName) {
      setErrorMessage("Please enter your full name.");
      return;
    }

    if (!trimmedEmail || !EMAIL_REGEX.test(trimmedEmail)) {
      setErrorMessage("Please enter a valid email address.");
      return;
    }

    if (password.length < 6) {
      setErrorMessage("Password must be at least 6 characters long.");
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage("Passwords do not match.");
      return;
    }

    setLoading(true);

    try {
      if (role === "STUDENT") {
        if (!studentId.trim()) {
          setErrorMessage("Please enter your Student ID (e.g. DS20260125).");
          setLoading(false);
          return;
        }
        if (!rollNumber.trim()) {
          setErrorMessage("Please enter your ERP / Roll Number.");
          setLoading(false);
          return;
        }

        await api.registerStudent({
          name: trimmedName,
          email: trimmedEmail,
          password,
          student_id: studentId.trim(),
          roll_number: rollNumber.trim(),
          branch,
          section,
          photo_base64: photoBase64 || undefined,
        });
      } else {
        if (!teacherId.trim()) {
          setErrorMessage("Please enter your Teacher ID (e.g. T001).");
          setLoading(false);
          return;
        }

        await api.registerTeacher({
          name: trimmedName,
          email: trimmedEmail,
          password,
          teacher_id: teacherId.trim(),
          department,
          assigned_classes: [`${branch === "Data Science" ? "DS" : "CS"}-${section}`],
          assigned_subjects: ["Machine Learning"],
        });
      }

      onSuccess(trimmedEmail);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("409") || message.toLowerCase().includes("already exists")) {
        setErrorMessage("An account with this email or ID already exists.");
      } else {
        setErrorMessage(message || "Unable to complete registration. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate>
      {errorMessage && (
        <div className="alert-banner error" role="alert" style={{ marginBottom: "1rem" }}>
          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" width="20" height="20">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 7.5h.008v.008H12v-.008z" />
          </svg>
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Account Type Selector */}
      <div className="form-group" style={{ marginBottom: "1.25rem" }}>
        <label className="role-group-label" style={{ fontWeight: 600, display: "block", marginBottom: "0.5rem" }}>
          Select Role
        </label>
        <div className="role-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <div
            className={`role-card ${role === "STUDENT" ? "selected" : ""}`}
            onClick={() => setRole("STUDENT")}
            role="radio"
            aria-checked={role === "STUDENT"}
            style={{
              padding: "0.85rem",
              borderRadius: "8px",
              cursor: "pointer",
              border: role === "STUDENT" ? "2px solid #1d4ed8" : "1px solid #e2e8f0",
              background: role === "STUDENT" ? "#eff6ff" : "#ffffff",
              textAlign: "center",
            }}
          >
            <div style={{ fontWeight: 600, fontSize: "0.95rem", color: role === "STUDENT" ? "#1d4ed8" : "#0f172a" }}>Student</div>
            <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Self-registration & Photo</div>
          </div>

          <div
            className={`role-card ${role === "TEACHER" ? "selected" : ""}`}
            onClick={() => setRole("TEACHER")}
            role="radio"
            aria-checked={role === "TEACHER"}
            style={{
              padding: "0.85rem",
              borderRadius: "8px",
              cursor: "pointer",
              border: role === "TEACHER" ? "2px solid #1d4ed8" : "1px solid #e2e8f0",
              background: role === "TEACHER" ? "#eff6ff" : "#ffffff",
              textAlign: "center",
            }}
          >
            <div style={{ fontWeight: 600, fontSize: "0.95rem", color: role === "TEACHER" ? "#1d4ed8" : "#0f172a" }}>Teacher</div>
            <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Classroom Sessions</div>
          </div>
        </div>
      </div>

      {/* Common: Full Name */}
      <div className="form-group" style={{ marginBottom: "0.85rem" }}>
        <label className="form-label" htmlFor="register-name">Full Name</label>
        <input
          id="register-name"
          type="text"
          className="auth-input"
          placeholder={role === "STUDENT" ? "e.g. Rahul Sharma" : "e.g. Dr. A. Sharma"}
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          disabled={loading}
        />
      </div>

      {/* Common: Email Address */}
      <div className="form-group" style={{ marginBottom: "0.85rem" }}>
        <label className="form-label" htmlFor="register-email">Email Address</label>
        <input
          id="register-email"
          type="email"
          className="auth-input"
          placeholder="your.email@campus.edu"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
        />
      </div>

      {/* Role-Specific: Student Fields */}
      {role === "STUDENT" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "0.85rem" }}>
            <div className="form-group">
              <label className="form-label" htmlFor="register-student-id">Student ID</label>
              <input
                id="register-student-id"
                type="text"
                className="auth-input"
                placeholder="e.g. DS202601"
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="register-roll-no">ERP / Roll No</label>
              <input
                id="register-roll-no"
                type="text"
                className="auth-input"
                placeholder="e.g. 20261234"
                value={rollNumber}
                onChange={(e) => setRollNumber(e.target.value)}
                required
                disabled={loading}
              />
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0.75rem", marginBottom: "0.85rem" }}>
            <div className="form-group">
              <label className="form-label" htmlFor="register-branch">Branch</label>
              <select
                id="register-branch"
                className="auth-input"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                disabled={loading}
                style={{ background: "#ffffff", color: "#0f172a" }}
              >
                {branches.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="register-section">Section</label>
              <select
                id="register-section"
                className="auth-input"
                value={section}
                onChange={(e) => setSection(e.target.value)}
                disabled={loading}
                style={{ background: "#ffffff", color: "#0f172a" }}
              >
                {sections.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Biometric Photo Upload */}
          <div className="form-group" style={{ marginBottom: "1rem" }}>
            <label className="form-label" style={{ display: "flex", justifyContent: "space-between" }}>
              <span>Profile Photograph / Face Scan</span>
              <span style={{ fontSize: "0.75rem", color: "#1d4ed8" }}>Required for Attendance</span>
            </label>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginTop: "0.35rem" }}>
              {photoPreview ? (
                <img
                  src={photoPreview}
                  alt="Student face preview"
                  style={{ width: "54px", height: "54px", borderRadius: "50%", objectFit: "cover", border: "2px solid #1d4ed8" }}
                />
              ) : (
                <div style={{ width: "54px", height: "54px", borderRadius: "50%", background: "#f1f5f9", border: "1px solid #cbd5e1", display: "flex", alignItems: "center", justifyContent: "center", color: "#64748b", fontSize: "1.25rem" }}>
                  👤
                </div>
              )}
              <input
                type="file"
                accept="image/*"
                onChange={handlePhotoChange}
                disabled={loading}
                style={{ fontSize: "0.85rem", color: "#475569" }}
              />
            </div>
          </div>
        </>
      )}

      {/* Role-Specific: Teacher Fields */}
      {role === "TEACHER" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "0.85rem" }}>
          <div className="form-group">
            <label className="form-label" htmlFor="register-teacher-id">Teacher ID</label>
            <input
              id="register-teacher-id"
              type="text"
              className="auth-input"
              placeholder="e.g. T001"
              value={teacherId}
              onChange={(e) => setTeacherId(e.target.value)}
              required
              disabled={loading}
            />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="register-dept">Department</label>
            <input
              id="register-dept"
              type="text"
              className="auth-input"
              placeholder="e.g. Data Science"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              required
              disabled={loading}
            />
          </div>
        </div>
      )}

      {/* Password & Confirm */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "1.25rem" }}>
        <div className="form-group">
          <label className="form-label" htmlFor="register-password">Password</label>
          <input
            id="register-password"
            type="password"
            className="auth-input"
            placeholder="Min. 6 chars"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            disabled={loading}
          />
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="register-confirm">Confirm Password</label>
          <input
            id="register-confirm"
            type="password"
            className="auth-input"
            placeholder="Re-enter"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            disabled={loading}
          />
        </div>
      </div>

      <button
        type="submit"
        className="btn-submit"
        disabled={loading}
      >
        {loading ? "Registering & Processing..." : `Register as ${role === "STUDENT" ? "Student" : "Teacher"}`}
      </button>

      <div className="auth-footer">
        <span>Already have an account? </span>
        <button
          type="button"
          onClick={onSwitchToLogin}
          disabled={loading}
          className="auth-footer-btn"
        >
          Sign In
        </button>
      </div>
    </form>
  );
};
