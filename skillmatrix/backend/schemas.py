from datetime import datetime, date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict


# ---------- Employee ----------
class EmployeeBase(BaseModel):
    full_name: str = Field(..., max_length=120)
    department: str = Field(..., max_length=80)
    line: Optional[str] = Field(None, max_length=80)
    position: str = Field(..., max_length=80)          # "Title"
    employee_type: Optional[Literal["FTE", "LO"]] = None  # "Type"
    join_date: Optional[date] = None


class EmployeeCreate(EmployeeBase):
    employee_id: str = Field(..., max_length=20)        # "ID Code"


class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    line: Optional[str] = None
    position: Optional[str] = None
    employee_type: Optional[Literal["FTE", "LO"]] = None
    join_date: Optional[date] = None
    is_active: Optional[bool] = None


class EmployeeOut(EmployeeBase):
    model_config = ConfigDict(from_attributes=True)
    employee_id: str
    is_active: bool
    updated_at: datetime


# ---------- Skill ----------
class SkillBase(BaseModel):
    skill_name: str = Field(..., max_length=120)
    skill_category: str = Field(..., max_length=60)
    description: Optional[str] = None
    is_critical: bool = False


class SkillCreate(SkillBase):
    skill_id: str = Field(..., max_length=20)


class SkillUpdate(BaseModel):
    skill_name: Optional[str] = None
    skill_category: Optional[str] = None
    description: Optional[str] = None
    is_critical: Optional[bool] = None


class SkillOut(SkillBase):
    model_config = ConfigDict(from_attributes=True)
    skill_id: str


# ---------- Assessment ----------
class AssessmentUpsert(BaseModel):
    employee_id: str
    skill_id: str
    proficiency_level: int = Field(..., ge=0, le=4)
    assessed_by: Optional[str] = None


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    employee_id: str
    skill_id: str
    proficiency_level: int
    assessed_by: Optional[str]
    assessed_at: datetime


# ---------- Matrix (aggregated grid for frontend) ----------
class MatrixCell(BaseModel):
    skill_id: str
    proficiency_level: int


class MatrixRow(BaseModel):
    employee_id: str
    full_name: str
    department: str
    position: str
    cells: List[MatrixCell]


class MatrixResponse(BaseModel):
    skills: List[SkillOut]
    rows: List[MatrixRow]


# ---------- Search ----------
class SkillSearchResult(BaseModel):
    employee_id: str
    full_name: str
    department: str
    position: str
    proficiency_level: int


# ---------- Analytics ----------
class LineCoverage(BaseModel):
    department: str
    total_possible: int
    total_achieved_weighted: int
    coverage_pct: float
    headcount: int


class BottleneckAlert(BaseModel):
    skill_id: str
    skill_name: str
    skill_category: str
    department: Optional[str]
    qualified_worker_count: int   # workers at Level 3+
    threshold: int
    severity: str                 # "critical" | "warning"
