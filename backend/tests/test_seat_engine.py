import pytest

from app.services.seat_engine import (
    QuotaShortage,
    find_violations,
    manhattan,
    place_candidates,
    plan_to_dict,
    quota_snapshot,
    verify_consistency,
    SeatAssign,
)

def _cands(n, specials=()):
    return [
        {"id": i + 1, "name": f"C{i}", "ticket_no": f"T{i}",
         "paper_id": 1 + (i % 2), "special": i in specials}
        for i in range(n)
    ]

def test_manhattan():
    assert manhattan((0, 0), (2, 1)) == 3

def test_min_distance_placement():
    cands = _cands(4)
    assigns, unplaced, quota = place_candidates(4, 4, 2, cands)
    assert len(assigns) + len(unplaced) == 4
    assert quota["enabled"] is False
    for i, a in enumerate(assigns):
        for b in assigns[i+1:]:
            assert manhattan((a.row, a.col), (b.row, b.col)) >= 2

def test_same_paper_not_adjacent_in_result():
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T1", "paper_id": 1, "special": False},
        {"id": 2, "name": "B", "ticket_no": "T2", "paper_id": 1, "special": False},
        {"id": 3, "name": "C", "ticket_no": "T3", "paper_id": 2, "special": False},
    ]
    assigns, _, _ = place_candidates(3, 3, 1, cands)
    viols = find_violations(3, 3, 1, assigns)
    assert not any(v.kind == "same_paper_adjacent" for v in viols)

def test_violation_detection():
    assigns = [
        SeatAssign(1, "A", "T1", 1, 0, 0, False),
        SeatAssign(2, "B", "T2", 1, 0, 1, False),
    ]
    viols = find_violations(2, 2, 2, assigns)
    kinds = {v.kind for v in viols}
    assert "distance" in kinds
    assert "same_paper_adjacent" in kinds


# ---------- 前排名额 ----------

def test_seed_scenario_two_specials_both_row0():
    """种子场景：前排行数 1，两名特殊考生都必须落在第 0 行，账图一致。"""
    cands = _cands(12, specials=(0, 1))
    assigns, unplaced, quota = place_candidates(5, 6, 2, cands, front_rows=1)
    specials = [a for a in assigns if a.special]
    assert len(specials) == 2
    assert {a.row for a in specials} == {0}
    # 名额格内只有特殊考生，普通人不占名额
    in_front = [a for a in assigns if a.row < 1]
    assert all(a.special for a in in_front)
    # 名额已耗与图一致
    assert quota["quota_total"] == 6
    assert quota["quota_used"] == len(in_front) == 2
    assert quota["front_occupied"] == quota["quota_used"]
    verify_consistency(assigns, quota)

def test_quota_computed_at_submit_not_cached():
    """同批考生、不同 front_rows：名额数当场重算，不沿用旧值。"""
    cands = _cands(8, specials=(0, 1))
    _, _, q1 = place_candidates(5, 6, 2, cands, front_rows=1)
    _, _, q2 = place_candidates(5, 6, 2, cands, front_rows=2)
    assert q1["quota_total"] == 6 and q1["quota_used"] == 2
    assert q2["quota_total"] == 12 and q2["quota_used"] == 2

def test_ordinary_never_occupies_quota_cells():
    """名额格宁可空着也不许普通人占用凑满前排。"""
    cands = _cands(10, specials=(0,))
    assigns, _, quota = place_candidates(3, 4, 1, cands, front_rows=1)
    front = [a for a in assigns if a.row < 1]
    assert all(a.special for a in front)
    assert len(front) == 1  # 只有那 1 名特殊考生，前排不得被普通人填满
    assert quota["quota_used"] == 1
    verify_consistency(assigns, quota)

def test_quota_shortage_raises_no_half_plan():
    """名额数不够：直接失败，不返回半张方案。"""
    cands = _cands(8, specials=tuple(range(7)))  # 1x6 只有 6 个名额格
    with pytest.raises(QuotaShortage):
        place_candidates(3, 6, 1, cands, front_rows=1)

def test_geometry_shortage_also_fails_whole_run():
    """名额数够但前排几何放不下（间距约束）：同样整场失败，不先排普通人。"""
    cands = _cands(4, specials=(0, 1))  # 1x2 前排，min_dist=3 时两人无法同排
    with pytest.raises(QuotaShortage):
        place_candidates(3, 2, 3, cands, front_rows=1)

def test_front_rows_zero_disables_quota_current_behavior():
    """front_rows=0：关闭名额账，特殊考生也不被强制到前排，退回现网。"""
    cands = _cands(6, specials=(4,))
    assigns, unplaced, quota = place_candidates(3, 3, 2, cands, front_rows=0)
    assert quota["enabled"] is False
    assert quota["quota_total"] == 0 and quota["quota_used"] == 0
    assert len(assigns) + len(unplaced) == 6
    verify_consistency(assigns, quota)  # disabled 时不做前排约束

def test_verify_consistency_detects_ordinary_in_quota():
    assigns = [
        SeatAssign(1, "A", "T1", 1, 0, 0, True),
        SeatAssign(2, "B", "T2", 1, 0, 1, False),  # 普通人混进名额格
    ]
    quota = quota_snapshot(assigns, 2, 2, 1)
    with pytest.raises(ValueError):
        verify_consistency(assigns, quota)

def test_plan_dict_carries_pinned_quota_snapshot():
    cands = _cands(4, specials=(0, 1))
    assigns, unplaced, quota = place_candidates(2, 4, 2, cands, front_rows=1)
    viols = find_violations(2, 4, 2, assigns)
    d = plan_to_dict(assigns, unplaced, viols, 2, 4, quota)
    # 统计的前排占用必须与名额已耗同一套数
    assert d["stats"]["front_occupied"] == d["stats"]["quota_used"] == quota["quota_used"]
    assert d["quota"]["front_rows"] == 1
