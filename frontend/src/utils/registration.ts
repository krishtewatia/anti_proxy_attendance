// Sign-up rules for the pilot: the college email domain, the roll number, and
// the notice a student accepts before sending a photo of their face. There is
// no "forgot password": an administrator resets passwords.
// Pure helpers only, so they can be tested without a browser.

export interface ConsentNotice {
  version: string;
  title: string;
  points: string[];
}

export interface RegistrationRules {
  // null until the academic structure exists: any address is accepted then.
  college_email_domain: string | null;
  consent_notice: ConsentNotice;
}

export interface ConsentStatus {
  accepted: boolean;
  accepted_at: string | null;
  notice: ConsentNotice;
}

// What the sign-in page says after a sign-up. A student can sign in at once;
// approval of their setup puts them on the attendance list. A teacher waits.
export function registeredMessage(role: "STUDENT" | "TEACHER"): string {
  return role === "STUDENT"
    ? "Account created. Sign in now, then choose your section and add your photos under My Setup. You join the attendance list once an administrator approves your setup."
    : "Account created. Sign in now; you can take attendance once an administrator approves you and assigns your classes.";
}

// The server's answer to a teacher who is signed in but not approved yet.
export const TEACHER_PENDING_TEXT = "Waiting for an administrator to approve you and assign your classes.";

export function isTeacherPendingError(err: unknown): boolean {
  return err instanceof Error && err.message.includes("Waiting for an administrator to approve you");
}

export const FORGOT_PASSWORD_HINT = "Forgot your password? Ask an administrator to reset it.";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Digits only, of varying length (e.g. 2401331540142); not derived from the email.
const ROLL_REGEX = /^[0-9]{8,20}$/;

// A student's college email is their ERP ID at the college domain.
export function emailPlaceholder(domain: string | null, role: "STUDENT" | "TEACHER"): string {
  if (!domain) return "your.email@college.edu";
  return role === "STUDENT" ? `STUDENT_ERP@${domain}` : `name@${domain}`;
}

export function emailHint(domain: string, role: "STUDENT" | "TEACHER"): string {
  return role === "STUDENT"
    ? `Use your college email (your ERP ID @${domain}).`
    : `Use your college email address (@${domain}).`;
}

// What the form says when the email or roll number is already registered: the
// server names which one; the person is pointed to an administrator.
export function duplicateRegistrationMessage(serverMessage: string): string {
  const text = serverMessage.toLowerCase();
  const which = text.includes("roll number")
    ? "This roll number is already registered."
    : text.includes("email")
      ? "An account with this email already exists."
      : "An account with this email or roll number already exists.";
  return `${which} Try signing in instead. ${FORGOT_PASSWORD_HINT}`;
}

export function emailAllowed(email: string, domain: string | null): boolean {
  const address = email.trim().toLowerCase();
  if (!EMAIL_REGEX.test(address)) return false;
  return !domain || address.endsWith(`@${domain.toLowerCase()}`);
}

export interface RegistrationFields {
  role: "STUDENT" | "TEACHER";
  name: string;
  email: string;
  password: string;
  confirmPassword: string;
  rollNumber: string;
  hasPhoto: boolean;
  consentAccepted: boolean;
}

// The first problem with the form, in the words shown to the person, or null.
export function registrationProblem(fields: RegistrationFields, domain: string | null): string | null {
  if (!fields.name.trim()) return "Please enter your full name.";
  if (!EMAIL_REGEX.test(fields.email.trim())) return "Please enter a valid email address.";
  if (!emailAllowed(fields.email, domain)) return `Use your college email address (ending in @${domain}).`;
  if (fields.password.length < 6) return "Password must be at least 6 characters long.";
  if (fields.password !== fields.confirmPassword) return "Passwords do not match.";
  if (fields.role === "STUDENT") {
    const roll = fields.rollNumber.trim();
    if (!roll) return "Please enter your roll number.";
    if (!ROLL_REGEX.test(roll)) return "Your roll number is digits only, 8 to 20 of them (e.g. 2401331540142).";
    if (fields.hasPhoto && !fields.consentAccepted) return "Read the notice about your photo and tick that you accept it.";
  }
  return null;
}
