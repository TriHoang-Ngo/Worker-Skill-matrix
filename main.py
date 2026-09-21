from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base, SessionLocal
from models import Employee, Skill, Assessment
from routers import employees, skills, assessments, analytics

app = FastAPI(
    title="Worker Skill Matrix API",
    description="Backend for manufacturing plant skill-matrix tracking, gap analysis and reporting.",
    version="1.0.0",
)
@app.get("/")
def read_root():
    return {"message": "Skill Matrix API is running!"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to the plant intranet origin(s) in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(employees.router)
app.include_router(skills.router)
app.include_router(assessments.router)
app.include_router(analytics.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _seed_demo_data_if_empty()


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _seed_demo_data_if_empty():
    """Populates a small demo dataset on first run so the frontend has
    something to render immediately. Safe to delete in a real deployment --
    guarded so it only runs against an empty database."""
    db = SessionLocal()
    try:
        if db.query(Employee).count() > 0:
            return

        employees_seed = [
            ("EMP-0001", "Nguyen Van An", "Line 1 - Assembly", "Line Operator"),
            ("EMP-0002", "Tran Thi Binh", "Line 1 - Assembly", "Line Operator"),
            ("EMP-0003", "Le Van Cuong", "Line 1 - Assembly", "Shift Lead"),
            ("EMP-0004", "Pham Thi Dung", "Line 2 - Packaging", "Line Operator"),
            ("EMP-0005", "Hoang Van Em", "Line 2 - Packaging", "Maintenance Tech"),
            ("EMP-0006", "Do Thi Phuong", "Line 3 - Machining", "CNC Operator"),
            ("EMP-0007", "Vu Van Giang", "Line 3 - Machining", "Quality Inspector"),
        ]
        for eid, name, dept, pos in employees_seed:
            db.add(Employee(employee_id=eid, full_name=name, department=dept, position=pos))

        skills_seed = [
            ("SK-001", "CNC Machine Operation", "Operation", 1),
            ("SK-002", "Conveyor Line Changeover", "Operation", 0),
            ("SK-003", "Preventive Maintenance - Mechanical", "Maintenance", 1),
            ("SK-004", "PLC Fault Diagnosis", "Maintenance", 1),
            ("SK-005", "In-line Quality Inspection", "Quality", 0),
            ("SK-006", "Statistical Process Control (SPC)", "Quality", 0),
            ("SK-007", "Lockout-Tagout (LOTO)", "Safety", 1),
            ("SK-008", "Forklift Operation", "Safety", 0),
        ]
        for sid, name, cat, crit in skills_seed:
            db.add(Skill(skill_id=sid, skill_name=name, skill_category=cat, is_critical=bool(crit)))

        db.commit()

        import random
        random.seed(42)
        emp_ids = [e[0] for e in employees_seed]
        skill_ids = [s[0] for s in skills_seed]
        for eid in emp_ids:
            for sid in skill_ids:
                if random.random() < 0.75:  # not every worker assessed on every skill
                    db.add(Assessment(
                        employee_id=eid, skill_id=sid,
                        proficiency_level=random.choices([0, 1, 2, 3, 4], weights=[10, 25, 30, 25, 10])[0],
                        assessed_by="seed-data",
                    ))
        db.commit()
    finally:
        db.close()
