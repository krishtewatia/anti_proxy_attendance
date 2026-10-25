import React, { useState, useEffect } from "react";
import { api } from "../../services";
import { classLabel, type PublicClass } from "../../utils/catalog.ts";
import { emailPlaceholder, registrationProblem, type RegistrationRules } from "../../utils/registration.ts";
import { ConsentNotice } from "./ConsentNotice";

interface RegisterFormProps {
  onSuccess: (registeredEmail: string) => void;
  onSwitchToLogin: () => void;
}

export const RegisterForm: React.FC<RegisterFormProps> = ({
  onSuccess,
  onSwitchToLogin,
}) => {
  const [role, setRole] = useState<"STUDENT" | "TEACHER">("STUDENT");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Student-specific fields. Students are known by roll number; the internal
  // student ID is made up by the server.
  const [rollNumber, setRollNumber] = useState("");
  const [consentAccepted, setConsentAccepted] = useState(false);
  const [classCode, setClassCode] = useState("");
  const [photoBase64, setPhotoBase64] = useState<string | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);

  // Teacher-specific fields (no teacher ID: teachers are known by email)
  const [department, setDepartment] = useState("CSE-DS");

  // The college email domain and the photo notice (from the server).
  const [rules, setRules] = useState<RegistrationRules | null>(null);

  // The classes that exist and are open for registration (from the server).
  const [classes, setClasses] = useState<PublicClass[]>([]);
  const [classesLoaded, setClassesLoaded] = useState(false);

  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getPublicClasses()
      .then((list) => {
        if (cancelled) return;
        setClasses(list);
        setClassCode((current) => current || (list[0]?.class_code ?? ""));
      })
      .catch(() => {
        // The form then says the class list could not be loaded.
      })
      .finally(() => {
        if (!cancelled) setClassesLoaded(true);
      });
    api
      .getRegistrationRules()
      .then((loaded) => {
        if (!cancelled) setRules(loaded);
      })
      .catch(() => {
        // Without the rules the server still checks the email and the notice.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const domain = rules?.college_email_domain ?? null;

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

    const problem = registrationProblem(
      {
        role,
        name,
        email,
        password,
        confirmPassword,
        rollNumber,
        hasPhoto: Boolean(photoBase64),
        consentAccepted,
      },
      domain,
    );
    if (problem) {
      setErrorMessage(problem);
      return;
    }

    setLoading(true);

    try {
      if (role === "STUDENT") {
        if (!classCode) {
          setErrorMessage("Please choose your class.");
          setLoading(false);
          return;
        }

        await api.registerStudent({
          name: trimmedName,
          email: trimmedEmail,
          password,
          roll_number: rollNumber.trim(),
          class_code: classCode,
          photo_base64: photoBase64 || undefined,
          consent_version: photoBase64 && rules ? rules.consent_notice.version : undefined,
        });
      } else {
        await api.registerTeacher({
          name: trimmedName,
          email: trimmedEmail,
          password,
          department,
          // Classes and subjects are assigned by an administrator at approval.
          assigned_classes: [],
          assigned_subjects: [],
        });
      }

      onSuccess(trimmedEmail);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("409") || message.toLowerCase().includes("already exists")) {
        setErrorMessage("An account with this email or roll number already exists.");
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
            <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Attendance sessions</div>
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
          placeholder={role === "STUDENT" ? "e.g. Alex Example" : "e.g. Dr. A. Example"}
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
          placeholder={emailPlaceholder(domain, role)}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
        />
        {domain && (
          <small style={{ color: "#64748b", fontSize: "0.75rem" }}>Use your college email address (@{domain}).</small>
        )}
      </div>

      {/* Role-Specific: Student Fields */}
      {role === "STUDENT" && (
        <>
          <div className="form-group" style={{ marginBottom: "0.85rem" }}>
            <label className="form-label" htmlFor="register-roll-no">Roll No</label>
            <input
              id="register-roll-no"
              type="text"
              className="auth-input"
              placeholder="e.g. 2401331540142" inputMode="numeric"
              value={rollNumber}
              onChange={(e) => setRollNumber(e.target.value)}
              required
              disabled={loading}
            />
          </div>

          <div className="form-group" style={{ marginBottom: "0.85rem" }}>
            <label className="form-label" htmlFor="register-class">Class</label>
            <select
              id="register-class"
              className="auth-input"
              value={classCode}
              onChange={(e) => setClassCode(e.target.value)}
              disabled={loading || classes.length === 0}
              style={{ background: "#ffffff", color: "#0f172a" }}
            >
              {classes.length === 0 && (
                <option value="">
                  {classesLoaded ? "No classes are available" : "Loading classes..."}
                </option>
              )}
              {classes.map((item) => (
                <option key={item.class_code} value={item.class_code}>{classLabel(item)}</option>
              ))}
            </select>
            {classesLoaded && classes.length === 0 && (
              <small style={{ color: "#b45309", fontSize: "0.75rem" }}>
                The class list could not be loaded. Try again in a moment, or ask an administrator.
              </small>
            )}
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

          {photoBase64 && rules && (
            <div style={{ marginBottom: "1rem" }}>
              <ConsentNotice notice={rules.consent_notice} accepted={consentAccepted} onChange={setConsentAccepted} disabled={loading} />
            </div>
          )}
        </>
      )}

      {/* Role-Specific: Teacher Fields */}
      {role === "TEACHER" && (
        <div style={{ marginBottom: "0.85rem" }}>
          <div className="form-group">
            <label className="form-label" htmlFor="register-dept">Department</label>
            <input
              id="register-dept"
              type="text"
              className="auth-input"
              placeholder="e.g. CSE-DS"
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
