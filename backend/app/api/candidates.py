from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate
from app.services.seating_service import SeatingRejected, set_candidate_special

router = APIRouter(prefix="/candidates", tags=["candidates"])


class SpecialIn(BaseModel):
    special: bool


def _cand_dict(r: Candidate) -> dict:
    return {"id": r.id, "hall_id": r.hall_id, "name": r.name,
            "ticket_no": r.ticket_no, "paper_id": r.paper_id,
            "special": bool(r.special)}


@router.get("")
def list_candidates(db: Session = Depends(get_db)):
    return [_cand_dict(r)
            for r in db.scalars(select(Candidate).order_by(Candidate.id)).all()]


@router.patch("/{candidate_id}/special")
def set_special(candidate_id: int, body: SpecialIn, db: Session = Depends(get_db)):
    """改特殊标记并原子重排；名额不足时标记、台账、方案全部不变（400）。"""
    try:
        hall_id, outcome = set_candidate_special(db, candidate_id, body.special)
    except SeatingRejected as exc:
        status = 404 if exc.code == "not_found" else 400
        raise HTTPException(status, {"code": exc.code, "detail": str(exc)})
    cand = db.get(Candidate, candidate_id)
    resp = {"candidate": _cand_dict(cand)}
    if outcome is not None:
        plan, result = outcome
        resp["plan_id"] = plan.id
        resp["quota"] = result["quota"]
    return resp
