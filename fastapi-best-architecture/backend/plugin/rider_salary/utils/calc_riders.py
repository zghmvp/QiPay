"""算薪骑手多选：未选=全量；搜索/分页可选第 201+ 人。"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

UNSELECTED_MEANS_ALL = '未选 = 计算本周期全部骑手'
TRUNCATED_HINT = '仅列出前 {n} 人，其余请搜索'
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 200


def normalize_calc_rider_ids(rider_ids: list[int] | None) -> list[int] | None:
    """未选（None 或空列表）= 周期内全部；非空只算选中的人。"""
    if not rider_ids:
        return None
    seen: set[int] = set()
    ordered: list[int] = []
    for raw in rider_ids:
        try:
            rider_id = int(raw)
        except (TypeError, ValueError):
            continue
        if rider_id <= 0 or rider_id in seen:
            continue
        seen.add(rider_id)
        ordered.append(rider_id)
    return ordered or None


def rider_matches_keyword(rider: Any, keyword: str | None) -> bool:
    text = (keyword or '').strip()
    if not text:
        return True
    needle = text.casefold()
    job_no = str(getattr(rider, 'job_no', '') or '')
    name = str(getattr(rider, 'name', '') or '')
    return needle in job_no.casefold() or needle in name.casefold()


@dataclass(frozen=True, slots=True)
class CalcRiderPage:
    """算薪骑手分页。"""

    items: list[Any]
    total: int
    page: int
    size: int
    listed_count: int
    truncated: bool
    truncated_hint: str | None
    unselected_means_all: str


def paginate_calc_riders(
    riders: list[Any],
    *,
    keyword: str | None = None,
    page: int = 1,
    size: int = DEFAULT_PAGE_SIZE,
) -> CalcRiderPage:
    """内存分页：可见不是全集时给出「仅列出前 N 人，其余请搜索」。"""
    page_no = max(int(page or 1), 1)
    page_size = int(size or DEFAULT_PAGE_SIZE)
    if page_size < 1:
        page_size = DEFAULT_PAGE_SIZE
    page_size = min(page_size, MAX_PAGE_SIZE)
    matched = [row for row in riders if rider_matches_keyword(row, keyword)]
    total = len(matched)
    start = (page_no - 1) * page_size
    items = matched[start : start + page_size]
    truncated = total > len(items)
    hint = TRUNCATED_HINT.format(n=page_size) if truncated else None
    return CalcRiderPage(
        items=items,
        total=total,
        page=page_no,
        size=page_size,
        listed_count=len(items),
        truncated=truncated,
        truncated_hint=hint,
        unselected_means_all=UNSELECTED_MEANS_ALL,
    )


def calc_rider_total_pages(total: int, size: int) -> int:
    if size <= 0:
        return 1
    return max(1, ceil(total / size)) if total else 1
