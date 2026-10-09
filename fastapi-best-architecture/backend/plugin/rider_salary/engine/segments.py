from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.subject import RiderSalarySubject


@dataclass
class PlanItemView:
    """方案项视图（含科目方向）"""

    id: int | None
    subject_id: int
    name: str
    stage: str
    sort_order: int
    condition_json: dict | None
    formula_json: dict | None
    condition_expr: str
    formula_expr: str
    enabled: bool
    direction: str
    include_in_gross: bool


@dataclass
class Segment:
    """连续同版本生效段（仅有方案日；无方案段不进入算薪）"""

    plan_version_id: int
    start_date: date
    end_date: date
    plan_version: Any | None = None
    items: list[PlanItemView] = field(default_factory=list)


def _employ_code(value: Any, default: str) -> str:
    """用工类型收成字符串。空值回退到默认快照。"""
    raw = getattr(value, 'value', value)
    if not raw:
        return default
    return str(raw)


def employ_type_on(history: list[Any], default: str, day: date) -> str:
    """某日的用工类型。

    取覆盖该日的用工历史；多段重叠时用开始日最晚的一段。
    没有任何一段覆盖时，回退到 default（骑手当前快照）。

    :param history: 用工历史，需有 start_date、end_date、employ_type
    :param default: 没有覆盖记录时的回退值
    :param day: 业务日
    :return: 用工类型编码
    """
    matched = [
        row
        for row in history
        if getattr(row, 'start_date', day) <= day and (getattr(row, 'end_date', None) is None or day <= row.end_date)
    ]
    if not matched:
        return default
    matched.sort(key=lambda row: getattr(row, 'start_date', day), reverse=True)
    return _employ_code(getattr(matched[0], 'employ_type', None), default)


def _employ_runs(
    start: date,
    end: date,
    history: list[Any],
    default: str,
) -> list[tuple[date, date, str]]:
    """闭区间内按连续相同用工类型切成若干段。"""
    runs: list[tuple[date, date, str]] = []
    current = start
    kind = employ_type_on(history, default, current)
    run_start = current
    while current < end:
        nxt = current + timedelta(days=1)
        nxt_kind = employ_type_on(history, default, nxt)
        if nxt_kind != kind:
            runs.append((run_start, current, kind))
            run_start = nxt
            kind = nxt_kind
        current = nxt
    runs.append((run_start, current, kind))
    return runs


def split_segments_by_employ(
    segments: list[Segment],
    history: list[Any],
    default: str,
) -> list[Segment]:
    """用工类型在段内变化时，按连续相同类型切开。

    类型整天不变的段原样返回。切出的子段共用原方案项，方案版本不变。
    只按日历上的解析结果切，不按在职区间裁剪；在职裁剪仍由算薪流水线负责。

    :param segments: 方案版本段
    :param history: 用工历史
    :param default: 历史未覆盖某日时回退的用工类型
    :return: 切段后的方案段
    """
    result: list[Segment] = []
    for segment in segments:
        if segment.end_date < segment.start_date:
            result.append(segment)
            continue
        runs = _employ_runs(segment.start_date, segment.end_date, history, default)
        if len(runs) <= 1:
            result.append(segment)
            continue
        for start, end, _kind in runs:
            result.append(
                Segment(
                    plan_version_id=segment.plan_version_id,
                    start_date=start,
                    end_date=end,
                    plan_version=segment.plan_version,
                    items=list(segment.items),
                )
            )
    return result


def segments_from_d2(d2_segments: list[Any]) -> list[Segment]:
    """
    将 D2 `Segment(plan_version_id, start, end)` 转为算薪 Segment。
    无方案段（plan_version_id is None）跳过，由流水线按日标 no_plan。
    """
    result: list[Segment] = []
    for row in d2_segments:
        version_id = getattr(row, 'plan_version_id', None)
        if version_id is None:
            continue
        result.append(
            Segment(
                plan_version_id=int(version_id),
                start_date=row.start,
                end_date=row.end,
            )
        )
    return result


async def load_plan_item_views(db: AsyncSession, plan_version_id: int) -> list[PlanItemView]:
    """加载版本下方案项及科目方向"""
    items = list(
        (
            await db.scalars(
                select(RiderSalaryPlanItem)
                .where(
                    RiderSalaryPlanItem.plan_version_id == plan_version_id,
                    RiderSalaryPlanItem.deleted == 0,
                )
                .order_by(RiderSalaryPlanItem.sort_order.asc(), RiderSalaryPlanItem.id.asc())
            )
        ).all()
    )
    subject_ids = {item.subject_id for item in items}
    subjects: dict[int, RiderSalarySubject] = {}
    if subject_ids:
        subject_rows = await db.scalars(
            select(RiderSalarySubject).where(
                RiderSalarySubject.id.in_(subject_ids),
                RiderSalarySubject.deleted == 0,
            )
        )
        subjects = {row.id: row for row in subject_rows.all()}
    views: list[PlanItemView] = []
    for item in items:
        subject = subjects.get(item.subject_id)
        if subject is None:
            raise errors.RequestError(msg=f'方案项「{item.name}」引用的科目不存在')
        views.append(
            PlanItemView(
                id=item.id,
                subject_id=item.subject_id,
                name=item.name,
                stage=item.stage,
                sort_order=item.sort_order,
                condition_json=item.condition_json,
                formula_json=item.formula_json,
                condition_expr=item.condition_expr or 'True',
                formula_expr=item.formula_expr or '0',
                enabled=bool(item.enabled),
                direction=subject.direction,
                include_in_gross=bool(subject.include_in_gross),
            )
        )
    return views


async def resolve_segments(
    db: AsyncSession,
    rider_id: int,
    start: date,
    end: date,
    forced: RiderSalaryPlanVersion | None = None,
) -> list[Segment]:
    """
    解析骑手在区间内的方案段。forced 时整个区间一个段。
    未 forced 时以 D2 `resolve_effective_plans` 为唯一真源。
    """
    if forced is not None:
        items = await load_plan_item_views(db, forced.id)
        return [
            Segment(
                plan_version_id=forced.id,
                start_date=start,
                end_date=end,
                plan_version=forced,
                items=items,
            )
        ]
    from backend.plugin.rider_salary.service.rider_service import resolve_effective_plans

    mapped = segments_from_d2(await resolve_effective_plans(db, rider_id, start, end))
    version_ids = {item.plan_version_id for item in mapped}
    versions: dict[int, RiderSalaryPlanVersion] = {}
    if version_ids:
        rows = await db.scalars(
            select(RiderSalaryPlanVersion).where(
                RiderSalaryPlanVersion.id.in_(version_ids),
                RiderSalaryPlanVersion.deleted == 0,
            )
        )
        versions = {row.id: row for row in rows.all()}
    result: list[Segment] = []
    for segment in mapped:
        items = await load_plan_item_views(db, segment.plan_version_id)
        result.append(
            Segment(
                plan_version_id=segment.plan_version_id,
                start_date=segment.start_date,
                end_date=segment.end_date,
                plan_version=versions.get(segment.plan_version_id),
                items=items,
            )
        )
    return result
