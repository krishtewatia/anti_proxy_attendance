export interface AcademicClass {
  class_id: string;
  class_code: string;
  branch: string;
  section: string;
  semester?: number;
}

export interface Subject {
  subject_id: string;
  name: string;
  code?: string;
  branch?: string;
}

export interface BranchHierarchy {
  name: string;
  sections: string[];
}

export interface AcademicStructureResponse {
  branches: BranchHierarchy[];
  classes: AcademicClass[];
  subjects: Subject[];
}
