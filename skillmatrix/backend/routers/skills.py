from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, require_admin
from models import Skill
import schemas

router = APIRouter(prefix="/api/skills", tags=["Skills"])


@router.get("", response_model=List[schemas.SkillOut])
def list_skills(category: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Skill)
    if category:
        q = q.filter(Skill.skill_category == category)
    return q.order_by(Skill.skill_category, Skill.skill_name).all()


@router.get("/{skill_id}", response_model=schemas.SkillOut)
def get_skill(skill_id: str, db: Session = Depends(get_db)):
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return skill


@router.post("", response_model=schemas.SkillOut, status_code=201)
def create_skill(payload: schemas.SkillCreate, db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    if db.get(Skill, payload.skill_id):
        raise HTTPException(409, f"Skill {payload.skill_id} already exists")
    skill = Skill(**payload.model_dump())
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.put("/{skill_id}", response_model=schemas.SkillOut)
def update_skill(skill_id: str, payload: schemas.SkillUpdate, db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(skill, k, v)
    db.commit()
    db.refresh(skill)
    return skill


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str, db: Session = Depends(get_db), _admin: bool = Depends(require_admin)):
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    db.delete(skill)
    db.commit()
    return None
