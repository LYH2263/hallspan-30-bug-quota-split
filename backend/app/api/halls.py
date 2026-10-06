from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Hall
from app.services.seating_service import SeatingRejected, update_front_rows

router = APIRouter(prefix="/halls", tags=["halls"])


class FrontRowsIn(BaseModel):
    front_rows: int


def _hall_dict(r: Hall) -> dict:
    return {"id": r.id, "code": r.code, "name": r.name, "rows": r.rows,
            "cols": r.cols, "min_manhattan": r.min_manhattan,
            "front_rows": r.front_rows or 0}


@router.get("")
def list_halls(db: Session = Depends(get_db)):
    return [_hall_dict(r) for r in db.scalars(select(Hall).order_by(Hall.id)).all()]


@router.put("/{hall_id}/front-rows")
def set_front_rows(hall_id: int, body: FrontRowsIn, db: Session = Depends(get_db)):
    """改前排行数并原子重排。负数/超行拒绝保存；名额不足整单回滚。

    被拒绝时本端点不做任何写：行数、台账、最新方案全部停在拒绝前。
    """
    try:
        _plan, result = update_front_rows(db, hall_id, body.front_rows)
    except SeatingRejected as exc:
        # 服务层已 rollback；此处绝不能再把被拒的 front_rows 写回考室行。
        status = 404 if exc.code == "not_found" else 400
        raise HTTPException(status, {"code": exc.code, "detail": str(exc)})
    hall = db.get(Hall, hall_id)
    return {"hall": _hall_dict(hall), "plan_id": _plan.id, "quota": result["quota"]}
