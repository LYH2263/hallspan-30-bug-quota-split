"""API 层原子联动测试（sqlite 内存库）。

覆盖验收口径：
- 名额不足时拒绝，方案条数不增、标记不改、台账不动；
- 非法前排行数（负 / 超行）拒绝保存，三处停在拒绝前；
- 排座图、名额已耗、统计前排占用同一套数；
- 历史方案钉死生成当时的名额数字，不回刷；
- 失败不留半张方案或半本台账。
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def ctx(monkeypatch):
    # 在导入 app 之前指掉数据库相关环境，避免触达 postgres
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SEED_ON_EMPTY", "false")

    import app.database as dbmod
    from app.database import Base, get_db
    from app.models import models as M  # noqa: F401 注册表

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", TestSession)
    Base.metadata.create_all(bind=engine)

    from app.main import app

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)

    def make_world(special_indexes=(0, 1), front_rows=1, rows=5, cols=6, min_dist=2):
        s = TestSession()
        hall = M.Hall(code="H101", name="一号考室", rows=rows, cols=cols,
                      min_manhattan=min_dist, front_rows=front_rows)
        s.add(hall); s.flush()
        papers = []
        for code in ("P-A", "P-B", "P-C"):
            p = M.PaperSet(code=code, title=code)
            s.add(p); s.flush(); papers.append(p)
        names = ["陈一", "李二", "张三", "赵四", "钱五", "孙六",
                 "周七", "吴八", "郑九", "王十", "冯十一", "陈十二"]
        for i, name in enumerate(names):
            s.add(M.Candidate(hall_id=hall.id, name=name, ticket_no=f"T{2026001+i}",
                              paper_id=papers[i % 3].id, special=i in special_indexes))
        s.commit()
        hall_id = hall.id
        s.close()
        return hall_id

    def session():
        return TestSession()

    return client, make_world, session, M


def _plan_count(s, M):
    return s.scalar(select(func.count()).select_from(M.SeatPlan))


def _ledger(s, M):
    return s.scalars(select(M.QuotaLedger).where(M.QuotaLedger.hall_id == 1)).first()


# ---------- 种子场景 ----------

def test_seed_two_specials_both_row0_and_quota_matches(ctx):
    client, make_world, session, M = ctx
    make_world(special_indexes=(0, 1), front_rows=1)
    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 200, r.text
    d = r.json()
    specials = [a for a in d["assignments"] if a["special"]]
    assert len(specials) == 2
    assert {a["row"] for a in specials} == {0}
    # 图 / 名额已耗 / 统计前排占用同一套数
    front_in_map = sum(1 for a in d["assignments"] if a["row"] < d["quota"]["front_rows"])
    assert d["quota"]["quota_used"] == front_in_map == 2
    assert d["stats"]["quota_used"] == d["stats"]["front_occupied"] == 2
    assert d["quota"]["quota_total"] == 6
    # 台账与方案同生
    s = session()
    led = _ledger(s, M)
    assert led.quota_used == 2 and led.quota_total == 6 and led.plan_id == d["id"]


def test_ordinary_not_in_quota_zone(ctx):
    client, make_world, session, M = ctx
    make_world(special_indexes=(0,), front_rows=1)
    d = client.post("/api/seating/run?hall_id=1").json()
    front = [a for a in d["assignments"] if a["row"] == 0]
    assert all(a["special"] for a in front)
    assert len(front) == 1  # 前排不得被普通人凑满


# ---------- 名额不足：三处不动、条数不增 ----------

def test_quota_shortage_marking_special_rejected_atomically(ctx):
    client, make_world, session, M = ctx
    # 6 名特殊恰好等于 1 行 x 6 列的名额格（min_dist=1 排除几何干扰）
    make_world(special_indexes=tuple(range(6)), front_rows=1, min_dist=1)
    run = client.post("/api/seating/run?hall_id=1")
    assert run.status_code == 200, run.text
    assert run.json()["quota"]["quota_used"] == 6
    s = session()
    plans_before = _plan_count(s, M)
    used_before = _ledger(s, M).quota_used
    s.close()

    # 再标 1 人特殊 => 7 名特殊 > 6 个名额格，必须拒绝
    r = client.patch("/api/candidates/7/special", json={"special": True})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "quota_shortage"

    s = session()
    # 方案条数不增
    assert _plan_count(s, M) == plans_before
    # 台账没动（仍是 6）
    led = _ledger(s, M)
    assert led.quota_used == used_before == 6
    # 标记没改成：“保住名额账”优先于改标记
    assert s.get(M.Candidate, 7).special is False
    flagged = {c.id for c in s.scalars(
        select(M.Candidate).where(M.Candidate.special == True)).all()}
    assert flagged == {1, 2, 3, 4, 5, 6}
    # 最新方案仍是旧的那一条，名额数字钉死
    latest = client.get("/api/seating/latest?hall_id=1").json()
    assert latest["id"] == run.json()["id"]
    assert latest["quota"]["quota_used"] == 6
    s.close()


def test_quota_shortage_run_rejected_no_new_plan(ctx):
    client, make_world, session, M = ctx
    make_world(special_indexes=tuple(range(7)), front_rows=1)
    s = session()
    assert _plan_count(s, M) == 0
    s.close()
    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "quota_shortage"
    s = session()
    assert _plan_count(s, M) == 0  # 失败不留半张方案
    assert _ledger(s, M) is None   # 也不留半本台账
    s.close()


# ---------- 非法前排行数：三处停在拒绝前 ----------

@pytest.mark.parametrize("bad", [-1, 6, 99])
def test_invalid_front_rows_rejected(ctx, bad):
    client, make_world, session, M = ctx
    make_world(front_rows=1)
    client.post("/api/seating/run?hall_id=1")
    s = session()
    plans_before = _plan_count(s, M)
    s.close()

    r = client.put("/api/halls/1/front-rows", json={"front_rows": bad})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_front_rows"

    s = session()
    hall = s.get(M.Hall, 1)
    assert hall.front_rows == 1            # 行数没改
    assert _plan_count(s, M) == plans_before  # 方案不增
    assert _ledger(s, M).front_rows == 1   # 台账没动
    s.close()


def test_front_rows_zero_disables_and_reenables(ctx):
    client, make_world, session, M = ctx
    make_world(front_rows=1)
    d1 = client.post("/api/seating/run?hall_id=1").json()
    assert d1["quota"]["enabled"] is True

    r = client.put("/api/halls/1/front-rows", json={"front_rows": 0})
    assert r.status_code == 200, r.text
    assert r.json()["quota"]["enabled"] is False
    s = session()
    assert s.get(M.Hall, 1).front_rows == 0
    assert _ledger(s, M).quota_total == 0
    s.close()
    stats = client.get("/api/seating/stats?hall_id=1").json()
    assert stats["quota_enabled"] is False

    # 0 -> 1 重新开启：名额按当轮格子现算，绝不沿用上一轮台账或继续拦人。
    r = client.put("/api/halls/1/front-rows", json={"front_rows": 1})
    assert r.status_code == 200, r.text
    q = r.json()["quota"]
    assert q["enabled"] is True and q["front_rows"] == 1
    assert q["quota_total"] == 6 and q["quota_used"] == 2
    s = session()
    led = _ledger(s, M)
    assert led.front_rows == 1 and led.quota_total == 6 and led.quota_used == 2
    s.close()


def test_ordinary_unplaced_does_not_count_against_quota(ctx):
    """名额区外几何放不下的普通人进未排（合法），名额已耗仍只等于前排特殊人数。"""
    client, make_world, session, M = ctx
    # 3 行 x 4 列、间距 3：两名特殊考生可在第 0 行（0,0)/(0,3) 落位，
    # 但普通人只剩 1~2 行里极少数格，10 名普通人必有未排。
    make_world(special_indexes=(0, 1), front_rows=1, rows=3, cols=4, min_dist=3)
    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 200, r.text
    d = r.json()
    front = [a for a in d["assignments"] if a["row"] == 0]
    assert len(front) == 2 and all(a["special"] for a in front)
    assert d["quota"]["quota_used"] == 2
    assert len(d["unplaced"]) > 0  # 普通人未排，不算整场失败
    st = client.get("/api/seating/stats?hall_id=1").json()
    assert st["unplaced"] == len(d["unplaced"])
    assert st["front_occupied"] == st["quota_used"] == 2


# ---------- 历史方案钉死 ----------

def test_history_plan_pinned_not_refreshed(ctx):
    client, make_world, session, M = ctx
    make_world(front_rows=1)
    d_fr1 = client.post("/api/seating/run?hall_id=1").json()
    # 改成前排行数 2，生成新方案
    r = client.put("/api/halls/1/front-rows", json={"front_rows": 2})
    assert r.status_code == 200
    d_fr2 = client.get("/api/seating/latest?hall_id=1").json()
    assert d_fr2["quota"]["front_rows"] == 2
    assert d_fr2["quota"]["quota_total"] == 12
    assert d_fr2["id"] != d_fr1["id"]

    # 旧方案的 result_json 仍钉死生成当时的名额数字
    s = session()
    old = s.get(M.SeatPlan, d_fr1["id"])
    pinned = json.loads(old.result_json)["quota"]
    assert pinned["front_rows"] == 1
    assert pinned["quota_total"] == 6
    assert pinned["quota_used"] == 2
    s.close()


# ---------- 标记切换成功路径 ----------

def test_mark_special_success_extends_plan_and_ledger(ctx):
    client, make_world, session, M = ctx
    make_world(special_indexes=(0, 1), front_rows=1)
    client.post("/api/seating/run?hall_id=1")
    r = client.patch("/api/candidates/3/special", json={"special": True})
    assert r.status_code == 200, r.text
    assert r.json()["quota"]["quota_used"] == 3
    s = session()
    assert s.get(M.Candidate, 3).special is True
    assert _ledger(s, M).quota_used == 3
    s.close()
    # 无变化的切换不增方案
    s = session(); before = _plan_count(s, M); s.close()
    r = client.patch("/api/candidates/3/special", json={"special": True})
    assert r.status_code == 200
    s = session(); assert _plan_count(s, M) == before; s.close()


def test_stats_same_numbers_as_map(ctx):
    client, make_world, session, M = ctx
    make_world(front_rows=1)
    d = client.post("/api/seating/run?hall_id=1").json()
    st = client.get("/api/seating/stats?hall_id=1").json()
    assert st["front_occupied"] == d["quota"]["quota_used"] == st["quota_used"]
