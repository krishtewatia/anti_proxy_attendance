import type { AttendanceCorrectionCreate, AttendanceStatus } from "../../types";

export interface AttendanceCorrectionFormData {
  newStatus: AttendanceStatus;
  newPresenceSeconds: number;
  reason: string;
}

export interface AttendanceCorrectionValidationErrors {
  status?: string;
  presence?: string;
  reason?: string;
}

export interface AttendanceCorrectionValidationResult {
  isValid: boolean;
  errors: AttendanceCorrectionValidationErrors;
  sanitizedPayload?: AttendanceCorrectionCreate;
}

/**
 * Validates manual attendance correction form input before submitting to the backend.
 */
export function validateAttendanceCorrectionForm(
  data: AttendanceCorrectionFormData,
): AttendanceCorrectionValidationResult {
  const errors: AttendanceCorrectionValidationErrors = {};

  if (data.newStatus !== "PRESENT" && data.newStatus !== "ABSENT") {
    errors.status = "Please select either PRESENT or ABSENT.";
  }

  if (
    isNaN(data.newPresenceSeconds) ||
    data.newPresenceSeconds === null ||
    data.newPresenceSeconds === undefined ||
    data.newPresenceSeconds < 0
  ) {
    errors.presence = "Presence duration must be 0 or greater.";
  }

  const trimmedReason = typeof data.reason === "string" ? data.reason.trim() : "";
  if (!trimmedReason) {
    errors.reason = "A reason is mandatory for manual attendance review.";
  } else if (trimmedReason.length > 1000) {
    errors.reason = "Reason cannot exceed 1000 characters.";
  }

  const isValid = Object.keys(errors).length === 0;

  return {
    isValid,
    errors,
    sanitizedPayload: isValid
      ? {
          new_status: data.newStatus,
          new_presence_seconds: Number(data.newPresenceSeconds),
          reason: trimmedReason,
        }
      : undefined,
  };
}
