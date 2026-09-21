from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, require_admin
from models import Employee, Skill, Assessment, AssessmentHistory
import schemas

router = APIRouter(prefix="/api", tags=["Assessments"])


@router.put("/assessments", response_model=schemas.AssessmentOut)
def upsert_assessment(payload: schemas.AssessmentUpsert, db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    """Create or update a single worker's proficiency level for a skill.
    Used by the grid's click-to-edit cell editor. Every change is also
    written to assessment_history for audit / trend purposes."""
    if not db.get(Employee, payload.employee_id):
        raise HTTPException(404, f"Employee {payload.employee_id} not found")
    if not db.get(Skill, payload.skill_id):
        raise HTTPException(404, f"Skill {payload.skill_id} not found")

    row = (
        db.query(Assessment)
        .filter_by(employee_id=payload.employee_id, skill_id=payload.skill_id)
        .one_or_none()
    )
    if row:
        row.proficiency_level = payload.proficiency_level
        row.assessed_by = payload.assessed_by
        row.assessed_at = datetime.utcnow()
    else:
        row = Assessment(**payload.model_dump())
        db.add(row)

    db.add(AssessmentHistory(
        employee_id=payload.employee_id,
        skill_id=payload.skill_id,
        proficiency_level=payload.proficiency_level,
        assessed_by=payload.assessed_by,
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/matrix", response_model=schemas.MatrixResponse)
def get_matrix(department: Optional[str] = None, db: Session = Depends(get_db)):
    """Aggregated grid: every active employee x every skill, with the current
    proficiency level (0 if never assessed). Shaped for direct binding to the
    frontend grid component (rows/columns)."""
    emp_q = db.query(Employee).filter(Employee.is_active == 1)
    if department:
        emp_q = emp_q.filter(Employee.department == department)
    employees = emp_q.order_by(Employee.full_name).all()
    skills = db.query(Skill).order_by(Skill.skill_category, Skill.skill_name).all()

    # Build a lookup of existing assessments for just these employees, in one query.
    emp_ids = [e.employee_id for e in employees]
    existing = (
        db.query(Assessment)
        .filter(Assessment.employee_id.in_(emp_ids))
        .all()
        if emp_ids else []
    )
    level_lookup = {(a.employee_id, a.skill_id): a.proficiency_level for a in existing}

    rows = []
    for e in employees:
        cells = [
            schemas.MatrixCell(
                skill_id=s.skill_id,
                proficiency_level=level_lookup.get((e.employee_id, s.skill_id), 0),
            )
            for s in skills
        ]
        rows.append(schemas.MatrixRow(
            employee_id=e.employee_id,
            full_name=e.full_name,
            department=e.department,
            position=e.position,
            cells=cells,
        ))

    return schemas.MatrixResponse(skills=skills, rows=rows)


@router.get("/search-by-skill", response_model=List[schemas.SkillSearchResult])
def search_by_skill(skill_id: str, min_level: int = 3, db: Session = Depends(get_db)):
    """Find every active worker who meets or exceeds a minimum proficiency
    level for a given skill -- e.g. 'who can run the CNC mill at L3+'."""
    if not db.get(Skill, skill_id):
        raise HTTPException(404, f"Skill {skill_id} not found")

    results = (
        db.query(Employee, Assessment.proficiency_level)
        .join(Assessment, Assessment.employee_id == Employee.employee_id)
        .filter(
            Assessment.skill_id == skill_id,
            Assessment.proficiency_level >= min_level,
            Employee.is_active == 1,
        )
        .order_by(Assessment.proficiency_level.desc(), Employee.full_name)
        .all()
    )
    return [
        schemas.SkillSearchResult(
            employee_id=emp.employee_id,
            full_name=emp.full_name,
            department=emp.department,
            position=emp.position,
            proficiency_level=level,
        )
        for emp, level in results
    ]
