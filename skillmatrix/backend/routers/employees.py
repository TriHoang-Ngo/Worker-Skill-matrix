import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd

from database import get_db, require_admin
from models import Employee
import schemas

router = APIRouter(prefix="/api/employees", tags=["Employees"])


@router.get("", response_model=List[schemas.EmployeeOut])
def list_employees(
    department: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    q = db.query(Employee)
    if active_only:
        q = q.filter(Employee.is_active == 1)
    if department:
        q = q.filter(Employee.department == department)
    if search:
        like = f"%{search}%"
        q = q.filter(Employee.full_name.ilike(like) if hasattr(Employee.full_name, "ilike") else Employee.full_name.like(like))
    return q.order_by(Employee.full_name).all()


@router.get("/{employee_id}", response_model=schemas.EmployeeOut)
def get_employee(employee_id: str, db: Session = Depends(get_db)):
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, f"Employee {employee_id} not found")
    return emp


@router.post("", response_model=schemas.EmployeeOut, status_code=201)
def create_employee(payload: schemas.EmployeeCreate, db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    if db.get(Employee, payload.employee_id):
        raise HTTPException(409, f"Employee {payload.employee_id} already exists")
    emp = Employee(**payload.model_dump())
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@router.put("/{employee_id}", response_model=schemas.EmployeeOut)
def update_employee(employee_id: str, payload: schemas.EmployeeUpdate, db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, f"Employee {employee_id} not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(emp, k, v)
    db.commit()
    db.refresh(emp)
    return emp


@router.delete("/{employee_id}", status_code=204)
def delete_employee(employee_id: str, hard: bool = False, db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    """Soft-delete by default (is_active=0), preserving assessment history. hard=True removes the row."""
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, f"Employee {employee_id} not found")
    if hard:
        db.delete(emp)
    else:
        emp.is_active = 0
    db.commit()
    return None


# ---------------- Excel / CSV import & export ----------------

REQUIRED_IMPORT_COLUMNS = {"employee_id", "full_name", "department", "position"}

# Accept the plant's own header names (e.g. "ID Code", "Title", "Type") as
# aliases for our internal field names, so imports don't need exact matches.
IMPORT_COLUMN_ALIASES = {
    "id_code": "employee_id",
    "id": "employee_id",
    "title": "position",
    "type": "employee_type",
}


def _clean(val):
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


@router.post("/import")
async def import_employees(file: UploadFile = File(...), db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    """Bulk-upsert employees from an uploaded .csv or .xlsx file. Accepts the
    optional columns Type (FTE/LO), Join date, and Line alongside the
    required ID Code/Employee ID, Full Name, Department, and Title/Position."""
    content = await file.read()
    try:
        if file.filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns=IMPORT_COLUMN_ALIASES)
    missing = REQUIRED_IMPORT_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(400, f"Missing required columns: {sorted(missing)}")

    created, updated, errors = 0, 0, []
    for i, row in df.iterrows():
        try:
            eid = str(row["employee_id"]).strip()
            emp_type = _clean(row["employee_type"]) if "employee_type" in df.columns else None
            if emp_type and emp_type.upper() not in ("FTE", "LO"):
                errors.append(f"Row {i + 2}: Type must be FTE or LO, got '{emp_type}' — left blank")
                emp_type = None
            elif emp_type:
                emp_type = emp_type.upper()
            join_date = None
            if "join_date" in df.columns:
                raw = _clean(row["join_date"])
                if raw:
                    try:
                        join_date = pd.to_datetime(raw).date()
                    except Exception:
                        errors.append(f"Row {i + 2}: could not parse join date '{raw}' — left blank")
            line = _clean(row["line"]) if "line" in df.columns else None

            existing = db.get(Employee, eid)
            if existing:
                existing.full_name = str(row["full_name"]).strip()
                existing.department = str(row["department"]).strip()
                existing.position = str(row["position"]).strip()
                if emp_type: existing.employee_type = emp_type
                if join_date: existing.join_date = join_date
                if line: existing.line = line
                updated += 1
            else:
                db.add(Employee(
                    employee_id=eid,
                    full_name=str(row["full_name"]).strip(),
                    department=str(row["department"]).strip(),
                    position=str(row["position"]).strip(),
                    employee_type=emp_type,
                    join_date=join_date,
                    line=line,
                ))
                created += 1
        except Exception as e:
            errors.append(f"Row {i + 2}: {e}")

    db.commit()
    return {"created": created, "updated": updated, "errors": errors}


@router.get("/export/{fmt}")
def export_employees(fmt: str, db: Session = Depends(get_db)):
    """fmt = 'csv' or 'xlsx'."""
    rows = db.query(Employee).filter(Employee.is_active == 1).all()
    df = pd.DataFrame([{
        "ID Code": r.employee_id,
        "Full Name": r.full_name,
        "Type": r.employee_type or "",
        "Join date": r.join_date.isoformat() if r.join_date else "",
        "Department": r.department,
        "Title": r.position,
        "Line": r.line or "",
    } for r in rows])

    buf = io.BytesIO()
    if fmt == "csv":
        df.to_csv(buf, index=False)
        media = "text/csv"
        fname = "employees.csv"
    elif fmt == "xlsx":
        df.to_excel(buf, index=False, engine="openpyxl")
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        fname = "employees.xlsx"
    else:
        raise HTTPException(400, "fmt must be 'csv' or 'xlsx'")
    buf.seek(0)
    return StreamingResponse(buf, media_type=media, headers={
        "Content-Disposition": f"attachment; filename={fname}"
    })
