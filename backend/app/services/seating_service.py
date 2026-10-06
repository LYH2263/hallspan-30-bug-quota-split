"""排座提交与名额台账的原子联动服务。

不变量：
1. 名额数字只在「提交排座」的瞬间由当前 front_rows 现算，不读任何上次缓存。
2. 座位图 / 名额已耗 / 统计前排占用 同源于一次内存计算，交叉校验通过才落库。
3. 台账（quota_ledgers）与最新方案（seat_plans）在同一事务同成功或同失败；
   失败一律 rollback，绝不留下半张方案或半本台账。
4. 历史方案的名额数字钉死在其 result_json 中，任何后续改动都不回刷。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, QuotaLedger, SeatPlan
from app.services.seat_engine import (
    QuotaShortage,
    find_violations,
    place_candidates,
    plan_to_dict,
    verify_consistency,
)


class SeatingRejected(Exception):
    """业务拒绝（名额不足、参数非法）；调用方映射为 HTTP 400。"""

    def __init__(self, message: str, code: str = "rejected"):
        super().__init__(message)
        self.code = code


def _load_candidates(db: Session, hall_id: int) -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no,
         "paper_id": c.paper_id, "special": bool(c.special)}
        for c in db.scalars(
            select(Candidate).where(Candidate.hall_id == hall_id).order_by(Candidate.id)
        ).all()
    ]


def generate_plan(hall: Hall, candidates: list[dict]) -> dict:
    """纯内存：现算名额 -> 排座 -> 校验 -> 组装结果。不触碰数据库。

    任何失败都抛出异常，调用方负责 rollback；此处不存在半成品状态。
    """
    # 名额在提交瞬间重算：front_rows 直接来自当前考室行，绝不沿用缓存名额。
    front_rows = hall.front_rows or 0
    try:
        assigns, unplaced, quota = place_candidates(
            hall.rows, hall.cols, hall.min_manhattan, candidates, front_rows
        )
    except QuotaShortage as exc:
        raise SeatingRejected(str(exc), code="quota_shortage") from exc

    # 图 / 台账 / 统计 三处对不齐则整场失败，不产生方案。
    verify_consistency(assigns, quota)

    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols, quota)
    result["hall"] = {"id": hall.id, "name": hall.name,
                      "min_manhattan": hall.min_manhattan, "front_rows": front_rows}
    return result


def _commit_plan(db: Session, hall_id: int, result: dict) -> SeatPlan:
    """同一事务内写方案 + 更新台账。调用方不得在此之前 commit。"""
    q = result["quota"]
    special_count = q["special_seated_front"] if q["enabled"] else sum(
        1 for a in result["assignments"] if a.get("special")
    )
    plan = SeatPlan(
        hall_id=hall_id,
        created_at=datetime.utcnow(),
        result_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(plan)
    db.flush()  # 取 plan.id；仍在事务内，失败可整体回滚

    ledger = db.scalars(
        select(QuotaLedger).where(QuotaLedger.hall_id == hall_id)
    ).first()
    if ledger is None:
        ledger = QuotaLedger(hall_id=hall_id)
        db.add(ledger)
    ledger.updated_at = datetime.utcnow()
    ledger.front_rows = q["front_rows"]
    ledger.quota_total = q["quota_total"]
    ledger.quota_used = q["quota_used"]
    ledger.special_count = special_count
    ledger.plan_id = plan.id
    db.commit()
    db.refresh(plan)
    return plan


def run_seating(db: Session, hall_id: int) -> tuple[SeatPlan, dict]:
    hall = db.get(Hall, hall_id)
    if not hall:
        raise SeatingRejected("考室不存在", code="not_found")
    candidates = _load_candidates(db, hall_id)
    try:
        result = generate_plan(hall, candidates)
        plan = _commit_plan(db, hall_id, result)
    except Exception:
        db.rollback()
        raise
    return plan, result


def validate_front_rows(front_rows: int, hall_rows: int) -> None:
    """负数或超过考室行数直接拒绝保存；调用方必须在任何改动之前调用。"""
    if front_rows < 0:
        raise SeatingRejected("前排行数不能为负", code="invalid_front_rows")
    if front_rows > hall_rows:
        raise SeatingRejected(
            f"前排行数 {front_rows} 超过考室行数 {hall_rows}", code="invalid_front_rows"
        )


def update_front_rows(db: Session, hall_id: int, front_rows: int) -> tuple[SeatPlan, dict]:
    """改前排行数：先校验，再在同一事务改配置、重算名额、重建方案与台账。

    失败时配置、台账、方案三处全部停在拒绝前（rollback）。
    """
    hall = db.get(Hall, hall_id)
    if not hall:
        raise SeatingRejected("考室不存在", code="not_found")
    validate_front_rows(front_rows, hall.rows)  # 三处停在拒绝前：未做任何改动

    hall.front_rows = front_rows
    candidates = _load_candidates(db, hall_id)
    try:
        result = generate_plan(hall, candidates)
        plan = _commit_plan(db, hall_id, result)
    except Exception:
        db.rollback()  # front_rows、台账、方案全部回到旧值/旧行
        raise
    return plan, result


def set_candidate_special(db: Session, candidate_id: int, special: bool) -> tuple[int, tuple[SeatPlan, dict] | None]:
    """改特殊标记：同一事务改标记、重算名额、重建方案与台账。

    名额不足时 rollback：标记不改、方案条数不增、台账不动。
    返回 (hall_id, (plan, result))；名额账关闭时仍重排以保持联动一致。
    """
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise SeatingRejected("考生不存在", code="not_found")
    if bool(cand.special) == bool(special):
        return cand.hall_id, None  # 无变化，不增方案

    cand.special = bool(special)
    hall = db.get(Hall, cand.hall_id)
    candidates = _load_candidates(db, cand.hall_id)
    try:
        result = generate_plan(hall, candidates)
        plan = _commit_plan(db, cand.hall_id, result)
    except Exception:
        db.rollback()  # “保住名额账”优先：标记、台账、方案皆不变
        raise
    return cand.hall_id, (plan, result)
