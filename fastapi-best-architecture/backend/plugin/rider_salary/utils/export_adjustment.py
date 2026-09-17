"""导出奖惩 sheet：已入账 / 未入账可分，排除需关注默认仍导出并标注。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend.plugin.rider_salary.crud.settle_period import SITE_LEVEL_RIDER_ID
from backend.plugin.rider_salary.enums import DetailSource
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

BOOKED_LABEL = '已入账'
UNBOOKED_LABEL = '未入账'
ATTENTION_ADJ_NOTE = '该骑手该日存在需关注订单'
SYNC_DROP_NOTE = '奖惩同步去掉同日同骑手'


def attention_rider_day_keys(orders: list[Any]) -> set[tuple[int, date]]:
    """需关注订单的 (骑手, 业务日)。"""
    keys: set[tuple[int, date]] = set()
    for order in orders:
        biz_date = getattr(order, 'biz_date', None)
        rider_id = getattr(order, 'rider_id', None)
        if biz_date is None or rider_id is None:
            continue
        keys.add((int(rider_id), biz_date))
    return keys


def manual_detail_keys(details: list[Any]) -> set[tuple[int, date | None, int]]:
    """本周期 payroll 手工明细键 (rider_id, biz_date, subject_id)。"""
    keys: set[tuple[int, date | None, int]] = set()
    for detail in details:
        source = getattr(detail, 'source', None)
        if source != DetailSource.manual.value:
            continue
        rider_id = getattr(detail, 'rider_id', None)
        subject_id = getattr(detail, 'subject_id', None)
        if rider_id is None or subject_id is None:
            continue
        keys.add((int(rider_id), getattr(detail, 'biz_date', None), int(subject_id)))
    return keys


def is_booked_adjustment(
    adj: Any,
    *,
    period_id: int,
    manual_keys: set[tuple[int, date | None, int]],
) -> bool:
    """已入本周期 payroll：period_id 回写或存在对应手工明细。"""
    adj_period = getattr(adj, 'period_id', None)
    if adj_period is not None and int(adj_period) == int(period_id):
        return True
    key = (
        int(getattr(adj, 'rider_id', 0) or 0),
        getattr(adj, 'biz_date', None),
        int(getattr(adj, 'subject_id', 0) or 0),
    )
    return key in manual_keys


def is_attention_same_day(adj: Any, attention_keys: set[tuple[int, date]]) -> bool:
    biz_date = getattr(adj, 'biz_date', None)
    rider_id = getattr(adj, 'rider_id', None)
    if biz_date is None or rider_id is None:
        return False
    return (int(rider_id), biz_date) in attention_keys


@dataclass(frozen=True, slots=True)
class ClassifiedAdjustment:
    """奖惩导出行分类。"""

    adjustment: Any
    booked: bool
    attention_same_day: bool
    dropped: bool

    @property
    def booked_label(self) -> str:
        return BOOKED_LABEL if self.booked else UNBOOKED_LABEL

    @property
    def attention_note(self) -> str:
        if self.dropped:
            return ''
        return ATTENTION_ADJ_NOTE if self.attention_same_day else ''


def classify_adjustments(
    adjustments: list[Any],
    *,
    period_id: int,
    manual_keys: set[tuple[int, date | None, int]],
    attention_keys: set[tuple[int, date]],
    exclude_attention_adjustments: bool = False,
) -> list[ClassifiedAdjustment]:
    """
    分类窗口内奖惩。exclude_attention_adjustments 默认 False：需关注同日同骑手仍导出并标注。
    打开后这些行 dropped=True，调用方不得写入 sheet。
    """
    rows: list[ClassifiedAdjustment] = []
    for adj in adjustments:
        booked = is_booked_adjustment(adj, period_id=period_id, manual_keys=manual_keys)
        attention = is_attention_same_day(adj, attention_keys)
        dropped = bool(exclude_attention_adjustments and attention)
        rows.append(
            ClassifiedAdjustment(
                adjustment=adj,
                booked=booked,
                attention_same_day=attention,
                dropped=dropped,
            )
        )
    rows.sort(key=lambda row: (0 if row.booked else 1, getattr(row.adjustment, 'id', 0) or 0))
    return rows


@dataclass(frozen=True, slots=True)
class AdjustmentSheetStats:
    """奖惩 sheet 对账计数（不改 gross/net）。"""

    booked_count: int
    unbooked_count: int
    attention_count: int
    excluded_count: int


def sheet_stats(rows: list[ClassifiedAdjustment]) -> AdjustmentSheetStats:
    kept = [row for row in rows if not row.dropped]
    return AdjustmentSheetStats(
        booked_count=sum(1 for row in kept if row.booked),
        unbooked_count=sum(1 for row in kept if not row.booked),
        attention_count=sum(1 for row in kept if row.attention_same_day),
        excluded_count=sum(1 for row in rows if row.dropped),
    )


async def list_period_window_adjustments(db: AsyncSession, period: Any) -> list[RiderSalaryAdjustment]:
    """站点日期窗内奖惩（骑手级周期只计该骑手）。"""
    stmt = select(RiderSalaryAdjustment).where(
        RiderSalaryAdjustment.site_id == period.site_id,
        RiderSalaryAdjustment.biz_date >= period.start_date,
        RiderSalaryAdjustment.biz_date <= period.end_date,
        RiderSalaryAdjustment.deleted == 0,
    )
    rider_id = int(getattr(period, 'rider_id', 0) or 0)
    if rider_id and rider_id != SITE_LEVEL_RIDER_ID:
        stmt = stmt.where(RiderSalaryAdjustment.rider_id == rider_id)
    rows = await db.scalars(stmt.order_by(RiderSalaryAdjustment.biz_date.asc(), RiderSalaryAdjustment.id.asc()))
    return list(rows.all())


async def list_payroll_manual_details(db: AsyncSession, payroll_ids: list[int]) -> list[RiderSalaryPayrollDetail]:
    if not payroll_ids:
        return []
    rows = await db.scalars(
        select(RiderSalaryPayrollDetail).where(
            RiderSalaryPayrollDetail.payroll_id.in_(payroll_ids),
            RiderSalaryPayrollDetail.deleted == 0,
            RiderSalaryPayrollDetail.source == DetailSource.manual.value,
        )
    )
    return list(rows.all())
