from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Hall(Base):
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    min_manhattan: Mapped[int] = mapped_column(Integer, default=2)
    # 前排行数：0 = 关闭名额账、退回现网；只在点排座提交瞬间据此现算名额格。
    front_rows: Mapped[int] = mapped_column(Integer, default=0)

class PaperSet(Base):
    __tablename__ = "paper_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(128))

class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    name: Mapped[str] = mapped_column(String(64))
    ticket_no: Mapped[str] = mapped_column(String(32))
    paper_id: Mapped[int] = mapped_column(ForeignKey("paper_sets.id"))
    # 特殊考生：名额账开启时只能消耗前排格，普通人不得占用这些格。
    special: Mapped[bool] = mapped_column(Boolean, default=False)

class QuotaLedger(Base):
    """前排名额台账：每个考室一行（最新），与最新方案同生共死。"""
    __tablename__ = "quota_ledgers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"), unique=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    front_rows: Mapped[int] = mapped_column(Integer)
    quota_total: Mapped[int] = mapped_column(Integer)
    quota_used: Mapped[int] = mapped_column(Integer)
    special_count: Mapped[int] = mapped_column(Integer, default=0)
    # 指向本次台账对应的方案；失败时二者都不写。
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("seat_plans.id"), nullable=True)

class SeatPlan(Base):
    __tablename__ = "seat_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # result_json 内钉死生成当时的 front_rows / quota_total / quota_used，永不回刷。
    result_json: Mapped[str] = mapped_column(Text, default="{}")
