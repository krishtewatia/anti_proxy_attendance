export interface SessionFormData {
  courseName: string;
  classroomId: string;
  startTime: string;
  endTime: string;
  requiredPresence: number;
}

export interface ValidationErrors {
  courseName?: string;
  classroomId?: string;
  startTime?: string;
  endTime?: string;
  requiredPresence?: string;
}

export function validateSessionForm(data: SessionFormData): {
  isValid: boolean;
  errors: ValidationErrors;
} {
  const errors: ValidationErrors = {};

  if (!data.courseName.trim()) {
    errors.courseName = "Course name is required";
  }

  if (!data.classroomId.trim()) {
    errors.classroomId = "Classroom is required";
  }

  if (!data.startTime) {
    errors.startTime = "Start time is required";
  }

  if (!data.endTime) {
    errors.endTime = "End time is required";
  }

  if (data.startTime && data.endTime) {
    const startDate = new Date(data.startTime);
    const endDate = new Date(data.endTime);

    if (isNaN(startDate.getTime())) {
      errors.startTime = "Invalid start time format";
    }
    if (isNaN(endDate.getTime())) {
      errors.endTime = "Invalid end time format";
    }

    if (!isNaN(startDate.getTime()) && !isNaN(endDate.getTime())) {
      if (endDate.getTime() <= startDate.getTime()) {
        errors.endTime = "End time must be after start time";
      }
    }
  }

  if (
    isNaN(data.requiredPresence) ||
    data.requiredPresence < 0 ||
    data.requiredPresence > 100
  ) {
    errors.requiredPresence = "Required presence must be between 0 and 100";
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  };
}
