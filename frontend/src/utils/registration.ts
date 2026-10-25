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

export const FORGOT_PASSWORD_HINT = "Forgot your password? Ask an administrator to reset it.";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Digits only, of varying length (e.g. 2401331540142); not derived from the email.
const ROLL_REGEX = /^[0-9]{8,20}$/;

export function emailPlaceholder(domain: string | null, role: "STUDENT" | "TEACHER"): string {
  if (!domain) return "your.email@college.edu";
  return role === "STUDENT" ? `rollno@${domain}` : `name@${domain}`;
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
