import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import SeatPlan
from app.services.seating_service import SeatingRejected, run_seating

router = APIRouter(prefix="/seating", tags=["seating"])


def _rejected(exc: SeatingRejected) -> HTTPException:
    status = 404 if exc.code == "not_found" else 400
    return HTTPException(status, {"code": exc.code, "detail": str(exc)})


@router.post("/run")
def run(hall_id: int = 1, db: Session = Depends(get_db)):
    try:
        plan, result = run_seating(db, hall_id)
    except SeatingRejected as exc:
        raise _rejected(exc)
    return {"id": plan.id, **result}


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    plan = db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()
    if not plan:
        # 尚无方案时按当前配置生成一份；失败则返回拒绝，不伪造空方案。
        try:
            plan, result = run_seating(db, hall_id)
        except SeatingRejected as exc:
            raise _rejected(exc)
        return {"id": plan.id, **result}
    # 历史方案：名额数字钉死在生成当时，不回刷为当前台账。
    data = json.loads(plan.result_json)
    return {"id": plan.id, **data}


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "violations": data.get("violations", []),
            "unplaced": data.get("unplaced", [])}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    # 统计页所有人数/名额数原样取方案快照：图、已耗名额、前排占用同源同一套数，
    # 不做任何页侧累加或摊派。
    snapshot = dict(data.get("stats", {}))
    snapshot["quota"] = data.get("quota", {})
    return {"hall_id": hall_id, **snapshot}
