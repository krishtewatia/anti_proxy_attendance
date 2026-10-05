"""Academic Schemas for Branches, Sections, Classes, and Subjects."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class AcademicClass(BaseModel):
    """Represents a student cohort identified by branch and section (e.g. DS-B)."""

    model_config = ConfigDict(extra="ignore")

    class_id: Optional[str] = Field(default=None)
    class_code: str = Field(description="Formatted class tag like DS-B, CS-A, AIML-B")
    branch: str = Field(description="Branch name e.g. Data Science, Computer Science")
    section: str = Field(description="Section letter e.g. A, B, C")
    semester: Optional[int] = Field(default=None, description="Optional semester 1..8")

    def model_post_init(self, __context) -> None:
        if not self.class_id:
            self.class_id = self.class_code


class Subject(BaseModel):
    """Subject/Course offered in the curriculum."""

    model_config = ConfigDict(extra="ignore")

    subject_id: Optional[str] = Field(default=None)
    name: str = Field(description="Course name e.g. Machine Learning, DBMS, DevOps")
    code: Optional[str] = Field(default=None, description="Course code e.g. CS-301")
    branch: Optional[str] = Field(default=None, description="Target branch if specific")

    def model_post_init(self, __context) -> None:
        if not self.subject_id:
            self.subject_id = self.code or self.name


class BranchHierarchy(BaseModel):
    """Represents an academic branch and its sections."""

    model_config = ConfigDict(extra="ignore")

    name: str
    sections: list[str]


class AcademicStructureResponse(BaseModel):
    """Full academic hierarchy returned for registration and selection dropdowns."""

    model_config = ConfigDict(extra="ignore")

    branches: list[BranchHierarchy]
    classes: list[AcademicClass]
    subjects: list[Subject]
