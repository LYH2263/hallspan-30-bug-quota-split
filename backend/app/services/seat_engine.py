"""Exam seating: min Manhattan distance; same paper_id cannot be 4-neighbor adjacent.

前排名额（front_rows > 0 时启用）：
- 名额只在排座提交的瞬间由 ``front_rows * cols`` 现算，绝不读取任何上次缓存。
- 特殊考生先排，且只能消耗名额格（前 ``front_rows`` 行）。
- 普通人禁止占用名额格；名额区只留给特殊考生，绝不用普通人凑满前排。
- 任一特殊考生无法在名额格内落位 -> 抛 :class:`QuotaShortage`，整批作废，
  不返回半成品方案。
- ``front_rows == 0`` 关闭名额账，退回现网行为（所有人按行序抢全场格）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class SeatAssign:
    candidate_id: int
    name: str
    ticket_no: str
    paper_id: int
    row: int
    col: int
    special: bool = False


@dataclass
class Violation:
    kind: str
    a_id: int
    b_id: int
    detail: str


class QuotaShortage(Exception):
    """前排名额不足以容纳全部特殊考生；整场排座失败，不产生方案。"""

    def __init__(self, special_count: int, quota_total: int, front_rows: int,
                 geometric: bool = False):
        self.special_count = special_count
        self.quota_total = quota_total
        self.front_rows = front_rows
        self.geometric = geometric
        if geometric:
            msg = (f"前排几何放不下全部特殊考生：{special_count} 人无法在前 {front_rows} 行"
                   f"（{quota_total} 格）内满足间距/同卷约束")
        else:
            msg = (f"前排名额不足：特殊考生 {special_count} 人，名额格仅 {quota_total} 个"
                   f"（前排行数 {front_rows}）")
        super().__init__(msg)


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def neighbors4(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int]]:
    out = []
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc))
    return out


def _seat_ok(r: int, c: int, cand: dict, occupied: dict[tuple[int, int], SeatAssign],
             min_dist: int, rows: int, cols: int) -> bool:
    for pos, other in occupied.items():
        if manhattan((r, c), pos) < min_dist:
            return False
        if other.paper_id == cand["paper_id"] and (r, c) in neighbors4(pos[0], pos[1], rows, cols):
            return False
    for nr, nc in neighbors4(r, c, rows, cols):
        if (nr, nc) in occupied and occupied[(nr, nc)].paper_id == cand["paper_id"]:
            return False
    return True


def quota_snapshot(assigns: list[SeatAssign], rows: int, cols: int, front_rows: int) -> dict:
    """从最终座位图现算名额账——图是唯一事实源，不另记一份会走样的数。"""
    enabled = front_rows > 0
    quota_total = front_rows * cols
    quota_used = sum(1 for a in assigns if a.row < front_rows) if enabled else 0
    special_seated_front = sum(
        1 for a in assigns if a.special and a.row < front_rows
    ) if enabled else 0
    return {
        "enabled": enabled,
        "front_rows": front_rows,
        "quota_total": quota_total,
        "quota_used": quota_used,
        "quota_remaining": quota_total - quota_used,
        # 统计页的“前排占用”取同一套数
        "front_occupied": quota_used,
        "special_seated_front": special_seated_front,
        "hall_rows": rows,
        "hall_cols": cols,
    }


def place_candidates(
    rows: int,
    cols: int,
    min_dist: int,
    candidates: list[dict],
    front_rows: int = 0,
) -> tuple[list[SeatAssign], list[dict], dict]:
    """Greedy 排座，返回 (assignments, unplaced, quota)。

    名额启用时：特殊考生先排且只进名额格；普通人只进非名额格。
    名额不足以容纳特殊考生则抛 :class:`QuotaShortage`，不留半成品。
    """
    # 名额在提交瞬间现算，调用方传入的 front_rows 即当前考室配置，无任何缓存。
    specials = [c for c in candidates if c.get("special")]
    quota_total = front_rows * cols

    # 名额数这一关先过：绝不先把普通人排满再把特殊考生丢进未排。
    if front_rows > 0 and len(specials) > quota_total:
        raise QuotaShortage(len(specials), quota_total, front_rows)

    occupied: dict[tuple[int, int], SeatAssign] = {}
    unplaced: list[dict] = []

    def try_place(cand: dict, row_range: range, *, is_special: bool) -> bool:
        for r in row_range:
            for c in range(cols):
                if (r, c) in occupied:
                    continue
                if not _seat_ok(r, c, cand, occupied, min_dist, rows, cols):
                    continue
                occupied[(r, c)] = SeatAssign(
                    cand["id"], cand["name"], cand["ticket_no"], cand["paper_id"],
                    r, c, is_special,
                )
                return True
        return False

    if front_rows <= 0:
        # 名额账关闭：退回现网，按名册原序抢全场格，不做任何前排约束。
        for cand in candidates:
            if not try_place(cand, range(0, rows), is_special=bool(cand.get("special"))):
                unplaced.append(cand)
    else:
        # 第一阶段：特殊考生先排，只消耗名额格，绝不落到非名额区。
        # 名额数虽够但前排几何（间距/同卷相邻）放不下任一人，同样整场失败。
        for cand in specials:
            if not try_place(cand, range(0, front_rows), is_special=True):
                raise QuotaShortage(len(specials), quota_total, front_rows, geometric=True)
        # 第二阶段：普通人只准进非名额格；名额格宁可空着，也不用普通人凑前排。
        for cand in [c for c in candidates if not c.get("special")]:
            if not try_place(cand, range(front_rows, rows), is_special=False):
                unplaced.append(cand)

    assigns = list(occupied.values())
    return assigns, unplaced, quota_snapshot(assigns, rows, cols, front_rows)


def find_violations(rows: int, cols: int, min_dist: int, assigns: list[SeatAssign]) -> list[Violation]:
    viols: list[Violation] = []
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            d = manhattan((a.row, a.col), (b.row, b.col))
            if d < min_dist:
                viols.append(Violation("distance", a.candidate_id, b.candidate_id,
                                       f"曼哈顿距离 {d} < 最小要求 {min_dist}"))
            if a.paper_id == b.paper_id and (b.row, b.col) in neighbors4(a.row, a.col, rows, cols):
                viols.append(Violation("same_paper_adjacent", a.candidate_id, b.candidate_id,
                                       f"同试卷套 {a.paper_id} 四邻相邻"))
    return viols


def verify_consistency(assigns: list[SeatAssign], quota: dict) -> None:
    """图 / 名额已耗 / 统计前排占用 三处对不齐就抛错，禁止落库。"""
    if not quota.get("enabled"):
        return
    front_rows = quota["front_rows"]
    in_front = [a for a in assigns if a.row < front_rows]
    # 名额格内只允许特殊考生；普通人占名额格即账图不符。
    if any(not a.special for a in in_front):
        raise ValueError("名额台账与座位图不一致：名额格被普通考生占用")
    used = len(in_front)
    if used != quota["quota_used"]:
        raise ValueError("名额台账与座位图不一致：名额已耗对不上前排格数")
    if used != quota["front_occupied"]:
        raise ValueError("名额台账与统计不一致：前排占用对不上名额已耗")
    if used > quota["quota_total"]:
        raise ValueError("名额台账超支：已耗超过名额总额")
    specials_in_front = sum(1 for a in assigns if a.special and a.row < front_rows)
    specials_total = sum(1 for a in assigns if a.special)
    if specials_in_front != specials_total:
        raise ValueError("名额台账与座位图不一致：存在未落在名额格的特殊考生")


def plan_to_dict(assigns: list[SeatAssign], unplaced: list[dict], viols: list[Violation],
                 rows: int, cols: int, quota: dict | None = None) -> dict:
    quota = quota or quota_snapshot(assigns, rows, cols, 0)
    return {
        "rows": rows,
        "cols": cols,
        "assignments": [asdict(a) for a in assigns],
        "unplaced": unplaced,
        "violations": [asdict(v) for v in viols],
        "quota": quota,
        "stats": {
            "seated": len(assigns),
            "unplaced": len(unplaced),
            "violations": len(viols),
            "capacity": rows * cols,
            # 前排占用与名额已耗同源
            "front_occupied": quota["front_occupied"],
            "quota_total": quota["quota_total"],
            "quota_used": quota["quota_used"],
            "quota_enabled": quota["enabled"],
        },
    }
