import io
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from database import get_db
from models import Employee, Skill, Assessment
import schemas

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

TARGET_LEVEL = 3  # "proficient" threshold used for coverage %


def _coverage_by_department(db: Session) -> List[schemas.LineCoverage]:
    """Coverage % = achieved proficiency points / possible points (target=L3) per line.
    e.g. 10 workers x 5 skills x target L3 = 150 possible points; if the line
    has scored 90 points total, coverage = 60%."""
    employees = db.query(Employee).filter(Employee.is_active == 1).all()
    skills = db.query(Skill).all()
    n_skills = len(skills)
    assessments = db.query(Assessment).all()
    level_lookup = {(a.employee_id, a.skill_id): a.proficiency_level for a in assessments}

    by_dept: dict[str, list[Employee]] = {}
    for e in employees:
        by_dept.setdefault(e.department, []).append(e)

    results = []
    for dept, emps in sorted(by_dept.items()):
        possible = len(emps) * n_skills * TARGET_LEVEL
        achieved = 0
        for e in emps:
            for s in skills:
                lvl = level_lookup.get((e.employee_id, s.skill_id), 0)
                achieved += min(lvl, TARGET_LEVEL)  # cap contribution at target
        pct = round((achieved / possible) * 100, 1) if possible else 0.0
        results.append(schemas.LineCoverage(
            department=dept,
            total_possible=possible,
            total_achieved_weighted=achieved,
            coverage_pct=pct,
            headcount=len(emps),
        ))
    return results


@router.get("/coverage", response_model=List[schemas.LineCoverage])
def skill_coverage_by_line(db: Session = Depends(get_db)):
    """Dashboard #1: skill coverage % per production line."""
    return _coverage_by_department(db)


def _detect_bottlenecks(db: Session, threshold: int, level_floor: int, by_department: bool) -> List[schemas.BottleneckAlert]:
    """Flags a skill (optionally per-department) where the count of workers
    at >= level_floor is at or below `threshold`. Critical skills (is_critical)
    are flagged as 'critical' severity; others as 'warning'."""
    skills = db.query(Skill).all()
    employees = {e.employee_id: e for e in db.query(Employee).filter(Employee.is_active == 1).all()}
    assessments = (
        db.query(Assessment)
        .filter(Assessment.proficiency_level >= level_floor, Assessment.employee_id.in_(employees.keys()))
        .all()
    )

    alerts = []
    if by_department:
        # count qualified workers per (skill, department)
        counts: dict[tuple[str, str], int] = {}
        for a in assessments:
            emp = employees.get(a.employee_id)
            if not emp:
                continue
            key = (a.skill_id, emp.department)
            counts[key] = counts.get(key, 0) + 1

        depts = sorted({e.department for e in employees.values()})
        for s in skills:
            for dept in depts:
                cnt = counts.get((s.skill_id, dept), 0)
                if cnt <= threshold:
                    alerts.append(schemas.BottleneckAlert(
                        skill_id=s.skill_id,
                        skill_name=s.skill_name,
                        skill_category=s.skill_category,
                        department=dept,
                        qualified_worker_count=cnt,
                        threshold=threshold,
                        severity="critical" if s.is_critical else "warning",
                    ))
    else:
        counts: dict[str, int] = {}
        for a in assessments:
            counts[a.skill_id] = counts.get(a.skill_id, 0) + 1
        for s in skills:
            cnt = counts.get(s.skill_id, 0)
            if cnt <= threshold:
                alerts.append(schemas.BottleneckAlert(
                    skill_id=s.skill_id,
                    skill_name=s.skill_name,
                    skill_category=s.skill_category,
                    department=None,
                    qualified_worker_count=cnt,
                    threshold=threshold,
                    severity="critical" if s.is_critical else "warning",
                ))

    # Critical-severity, lowest headcount first
    alerts.sort(key=lambda a: (a.severity != "critical", a.qualified_worker_count))
    return alerts


@router.get("/bottlenecks", response_model=List[schemas.BottleneckAlert])
def bottleneck_alerts(
    threshold: int = Query(1, ge=0, description="Alert if qualified worker count <= threshold"),
    level_floor: int = Query(3, ge=0, le=4, description="Minimum level counted as 'qualified'"),
    by_department: bool = Query(True, description="Evaluate per production line vs. plant-wide"),
    db: Session = Depends(get_db),
):
    """Dashboard #2: bottleneck detection -- e.g. 'alert if a critical skill
    has only 1 worker at Level 3+' is threshold=1, level_floor=3."""
    return _detect_bottlenecks(db, threshold, level_floor, by_department)


# ---------------- Report export (PDF / Excel) ----------------

@router.get("/report/excel")
def export_excel_report(db: Session = Depends(get_db)):
    coverage = _coverage_by_department(db)
    bottlenecks = _detect_bottlenecks(db, threshold=1, level_floor=3, by_department=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame([c.model_dump() for c in coverage]).to_excel(writer, sheet_name="Coverage by Line", index=False)
        pd.DataFrame([b.model_dump() for b in bottlenecks]).to_excel(writer, sheet_name="Bottleneck Alerts", index=False)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=skill_matrix_report.xlsx"},
    )


@router.get("/report/pdf")
def export_pdf_report(db: Session = Depends(get_db)):
    coverage = _coverage_by_department(db)
    bottlenecks = _detect_bottlenecks(db, threshold=1, level_floor=3, by_department=True)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Worker Skill Matrix -- Summary Report", styles["Title"]),
        Paragraph(f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]),
        Spacer(1, 0.5 * cm),
        Paragraph("Skill Coverage by Production Line", styles["Heading2"]),
    ]

    cov_data = [["Department", "Headcount", "Coverage %"]] + [
        [c.department, str(c.headcount), f"{c.coverage_pct}%"] for c in coverage
    ]
    cov_table = Table(cov_data, hAlign="LEFT")
    cov_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story += [cov_table, Spacer(1, 1 * cm), Paragraph("Bottleneck Alerts (Level 3+ headcount)", styles["Heading2"])]

    bn_data = [["Skill", "Category", "Line", "Qualified", "Severity"]] + [
        [b.skill_name, b.skill_category, b.department or "Plant-wide", str(b.qualified_worker_count), b.severity]
        for b in bottlenecks[:40]  # cap rows on a single report page-set
    ]
    bn_table = Table(bn_data, hAlign="LEFT")
    bn_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8C1B1B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(bn_table)

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=skill_matrix_report.pdf"},
    )
