"""
ORM models -- mirrors the relational schema from Step 1:

employees        (employee_id PK, full_name, department, position, ...)
skills           (skill_id PK, skill_name, skill_category, ...)
assessments      (id PK, employee_id FK, skill_id FK, proficiency_level, ...)
                 UNIQUE(employee_id, skill_id) -- one current level per pair
assessment_history(id PK, employee_id FK, skill_id FK, proficiency_level,
                    assessed_by, assessed_at) -- append-only audit trail
"""
import enum
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, Date, UniqueConstraint,
    CheckConstraint, Index
)
from sqlalchemy.orm import relationship
from database import Base


class ProficiencyLevel(int, enum.Enum):
    L0_NONE = 0          # No exposure / not trained
    L1_AWARENESS = 1     # Aware, needs supervision
    L2_BASIC = 2          # Can perform with occasional support
    L3_PROFICIENT = 3    # Fully independent
    L4_EXPERT = 4         # Can train / audit others


class Employee(Base):
    __tablename__ = "employees"

    employee_id = Column(String(20), primary_key=True)          # e.g. "EMP-0001" -- shown as "ID Code"
    full_name = Column(String(120), nullable=False)
    department = Column(String(80), nullable=False, index=True)
    line = Column(String(80), nullable=True, index=True)          # separate production line, if different from department
    position = Column(String(80), nullable=False)                 # shown as "Title"
    employee_type = Column(String(10), nullable=True)             # "FTE" or "LO" -- shown as "Type"
    join_date = Column(Date, nullable=True)
    is_active = Column(Integer, nullable=False, default=1)        # soft delete flag
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assessments = relationship(
        "Assessment", back_populates="employee", cascade="all, delete-orphan"
    )


class Skill(Base):
    __tablename__ = "skills"

    skill_id = Column(String(20), primary_key=True)               # e.g. "SK-001"
    skill_name = Column(String(120), nullable=False, unique=True)
    skill_category = Column(String(60), nullable=False, index=True)  # Operation/Maintenance/Quality/Safety
    description = Column(String(500), nullable=True)
    is_critical = Column(Integer, nullable=False, default=0)      # flags "critical skill" for bottleneck detection
    created_at = Column(DateTime, default=datetime.utcnow)

    assessments = relationship(
        "Assessment", back_populates="skill", cascade="all, delete-orphan"
    )


class Assessment(Base):
    """Current proficiency of one employee on one skill (one row per pair)."""
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), ForeignKey("employees.employee_id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(String(20), ForeignKey("skills.skill_id", ondelete="CASCADE"), nullable=False)
    proficiency_level = Column(Integer, nullable=False, default=0)
    assessed_by = Column(String(120), nullable=True)
    assessed_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = relationship("Employee", back_populates="assessments")
    skill = relationship("Skill", back_populates="assessments")

    __table_args__ = (
        UniqueConstraint("employee_id", "skill_id", name="uq_employee_skill"),
        CheckConstraint("proficiency_level >= 0 AND proficiency_level <= 4", name="ck_level_range"),
        Index("ix_assessment_employee_skill", "employee_id", "skill_id"),
    )


class AssessmentHistory(Base):
    """Append-only audit log -- every change to a proficiency level is recorded here."""
    __tablename__ = "assessment_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), ForeignKey("employees.employee_id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(String(20), ForeignKey("skills.skill_id", ondelete="CASCADE"), nullable=False)
    proficiency_level = Column(Integer, nullable=False)
    assessed_by = Column(String(120), nullable=True)
    assessed_at = Column(DateTime, default=datetime.utcnow)
