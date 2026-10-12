"""预支台账与站点月份成本。

台账只统计已发放、未删除的预支。发放取金额，抵扣取 ``deducted_amount``，
结转取 ``remaining_amount``（空值按 0）。三者对平的充要条件是
发放 − 抵扣 − 结转 = 0，与 ``ADVANCE_LEDGER_CONSISTENCY_SQL`` 同一口径。

成本按自然月和站点汇总。跨月结算周期只按与该月重叠的天数拆开展示，
不改薪资单金额。应发、实发、预支抵扣只加总
``payroll_view.build_rider_views`` 挑出的有效单，不另写一套取有效单的逻辑。
"""

from calendar import monthrange
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.report import (
    AdvanceLedgerLine,
    GetAdvanceLedger,
    GetCostSummary,
    SiteMonthCostRow,
)
from backend.plugin.rider_salary.service.payroll_view import build_rider_views
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2

ZERO = Decimal('0.00')
COST_DISPLAY_ALLOCATION_NOTE = '按与自然月重叠的天数展示分摊，不是改工资。薪资单金额仍按结算周期。'

# 已发放且未删除的预支：发放、抵扣、结转与差额。
# remaining_amount 为空时 SUM 会跳过，与内存里按 0 计入一致。
# 差额 = 发放 − 抵扣 − 结转，0 表示对平。方言为 PostgreSQL（运行库），语句本身也可在 SQLite 执行。
ADVANCE_LEDGER_CONSISTENCY_SQL = """
SELECT
    COALESCE(SUM(amount), 0) AS issued,
    COALESCE(SUM(deducted_amount), 0) AS deducted,
    COALESCE(SUM(remaining_amount), 0) AS carried,
    COALESCE(SUM(amount), 0)
        - COALESCE(SUM(deducted_amount), 0)
        - COALESCE(SUM(remaining_amount), 0) AS gap
FROM rs_advance
WHERE deleted = 0
  AND status = 'paid'
"""


@dataclass(frozen=True)
class AdvanceLedgerTotals:
    """预支台账合计。"""

    issued: Decimal
    deducted: Decimal
    carried: Decimal
    gap: Decimal
    balanced: bool


def _deleted(row: Any) -> bool:
    return int(getattr(row, 'deleted', 0) or 0) != 0


def _money(row: Any, name: str) -> Decimal:
    return q2(getattr(row, name, ZERO) or ZERO)


def is_ledger_advance(row: Any) -> bool:
    """已发放且未删除，才进入台账。"""
    if _deleted(row):
        return False
    return getattr(row, 'status', None) == AdvanceStatus.paid.value


def summarize_advance_ledger(advances: Sequence[Any]) -> tuple[AdvanceLedgerTotals, list[AdvanceLedgerLine]]:
    """
    按台账口径汇总发放、抵扣、结转

    与 ``ADVANCE_LEDGER_CONSISTENCY_SQL`` 同一筛选：只计已发放、未删除的预支。
    单行结转为空时按 0，合计差额为 0 即对平。

    :param advances: 预支单，可含未发放和已删除
    :return: 合计，以及按预支单 ID 升序的明细
    """
    issued = ZERO
    deducted = ZERO
    carried = ZERO
    lines: list[AdvanceLedgerLine] = []
    for row in advances:
        if not is_ledger_advance(row):
            continue
        row_issued = _money(row, 'amount')
        row_deducted = _money(row, 'deducted_amount')
        row_carried = _money(row, 'remaining_amount')
        issued += row_issued
        deducted += row_deducted
        carried += row_carried
        lines.append(
            AdvanceLedgerLine(
                advance_id=int(getattr(row, 'id', 0) or 0),
                rider_id=int(getattr(row, 'rider_id', 0) or 0),
                site_id=int(getattr(row, 'site_id', 0) or 0),
                issued=row_issued,
                deducted=row_deducted,
                carried=row_carried,
            )
        )
    issued = q2(issued)
    deducted = q2(deducted)
    carried = q2(carried)
    gap = q2(issued - deducted - carried)
    lines.sort(key=lambda item: item.advance_id)
    totals = AdvanceLedgerTotals(
        issued=issued,
        deducted=deducted,
        carried=carried,
        gap=gap,
        balanced=gap == ZERO,
    )
    return totals, lines


@dataclass(frozen=True)
class SiteMonthCost:
    """一个站点在某个月的有效薪资成本。"""

    site_id: int
    month: str
    slip_count: int
    gross: Decimal
    net: Decimal
    advance_deduction: Decimal


def _period_span(period: Any) -> tuple[date, date] | None:
    """结算周期的闭区间。没有结束日时视为只落在开始日，避免把整笔算进错误的月。"""
    start = getattr(period, 'start_date', None)
    if not isinstance(start, date):
        return None
    end = getattr(period, 'end_date', None)
    if not isinstance(end, date) or end < start:
        end = start
    return start, end


def month_slices(start: date, end: date) -> list[tuple[str, int, int]]:
    """自然月与结算周期的重叠天数。返回月份、重叠天数、周期天数。"""
    period_days = (end - start).days + 1
    slices: list[tuple[str, int, int]] = []
    year, month = start.year, start.month
    while True:
        month_start = date(year, month, 1)
        month_end = date(year, month, monthrange(year, month)[1])
        overlap_start = max(start, month_start)
        overlap_end = min(end, month_end)
        if overlap_start <= overlap_end:
            days = (overlap_end - overlap_start).days + 1
            slices.append((f'{year:04d}-{month:02d}', days, period_days))
        if month_end >= end:
            break
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return slices


def _share(amount: Decimal, overlap_days: int, period_days: int) -> Decimal:
    """按重叠天数分摊一笔展示金额。周期天数无效时保持原额。"""
    if period_days <= 0:
        return q2(amount)
    return q2(amount * Decimal(overlap_days) / Decimal(period_days))


def summarize_site_month_cost(periods: Sequence[Any], payrolls: Sequence[Any]) -> list[SiteMonthCost]:
    """
    按站点、自然月汇总有效薪资单的展示成本

    薪资单金额仍按结算周期，这里只按与自然月重叠的天数拆开展示。
    同一站点同一月份的多个周期合并。有效单由 ``build_rider_views`` 决定：
    作废、反冲、已被反冲的单不计入；反冲后尚未补发的组没有成本。
    没有结束日的周期整笔计入开始日所在月。

    :param periods: 结算周期
    :param payrolls: 这些周期上的薪资单，可含作废和反冲
    :return: 先按月份倒序，再按站点 ID 升序
    """
    period_by_id: dict[int, Any] = {}
    for period in periods:
        if _deleted(period):
            continue
        period_by_id[int(getattr(period, 'id', 0) or 0)] = period
    buckets: dict[tuple[int, str], list[Decimal | int]] = defaultdict(
        lambda: [0, ZERO, ZERO, ZERO],
    )
    for view in build_rider_views(payrolls):
        payroll = view.effective
        if payroll is None:
            continue
        period = period_by_id.get(view.period_id)
        if period is None:
            continue
        span = _period_span(period)
        if span is None:
            continue
        start, end = span
        site_id = int(getattr(period, 'site_id', 0) or 0)
        gross = q2(getattr(payroll, 'gross', ZERO) or ZERO)
        net = q2(view.final_net)
        advance = q2(getattr(payroll, 'advance_deduction', ZERO) or ZERO)
        for month, overlap_days, period_days in month_slices(start, end):
            slot = buckets[site_id, month]
            slot[0] = int(slot[0]) + 1
            slot[1] = q2(Decimal(slot[1]) + _share(gross, overlap_days, period_days))
            slot[2] = q2(Decimal(slot[2]) + _share(net, overlap_days, period_days))
            slot[3] = q2(Decimal(slot[3]) + _share(advance, overlap_days, period_days))
    rows = [
        SiteMonthCost(
            site_id=site_id,
            month=month,
            slip_count=int(slot[0]),
            gross=q2(slot[1]),
            net=q2(slot[2]),
            advance_deduction=q2(slot[3]),
        )
        for (site_id, month), slot in buckets.items()
    ]
    rows.sort(key=lambda item: item.site_id)
    rows.sort(key=lambda item: item.month, reverse=True)
    return rows


def parse_report_month(month: str | None) -> tuple[str | None, date | None, date | None]:
    """
    解析 ``YYYY-MM``。空值表示不按月份过滤。

    :param month: 月份
    :return: 规范化月份、月初、月末
    """
    if month is None or not str(month).strip():
        return None, None, None
    try:
        year_s, mon_s = str(month).strip().split('-')
        year, mon = int(year_s), int(mon_s)
        start = date(year, mon, 1)
    except (TypeError, ValueError):
        raise errors.RequestError(msg='月份格式须为 YYYY-MM')
    end = date(year, mon, monthrange(year, mon)[1])
    return f'{year:04d}-{mon:02d}', start, end


def _site_clause(column: Any, site_ids: set[int] | None) -> Any:
    if site_ids is None:
        return true()
    return column.in_(list(site_ids) or [-1])


class ReportService:
    """对账与报表"""

    @staticmethod
    async def advance_ledger(
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
    ) -> GetAdvanceLedger:
        """
        预支台账

        全站可见看全部已发放预支；其余用户只看可见站点。合计与明细使用同一口径。

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID，空表示当前可见范围
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
            site_ids: set[int] | None = {site_id}
        else:
            site_ids = visible
        rows = list(
            (
                await db.scalars(
                    select(RiderSalaryAdvance).where(
                        RiderSalaryAdvance.deleted == 0,
                        RiderSalaryAdvance.status == AdvanceStatus.paid.value,
                        _site_clause(RiderSalaryAdvance.site_id, site_ids),
                    )
                )
            ).all()
        )
        totals, lines = summarize_advance_ledger(rows)
        return GetAdvanceLedger(
            issued=totals.issued,
            deducted=totals.deducted,
            carried=totals.carried,
            gap=totals.gap,
            balanced=totals.balanced,
            lines=lines,
        )

    @staticmethod
    async def cost_summary(
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        month: str | None,
    ) -> GetCostSummary:
        """
        按站点和自然月汇总有效薪资成本的展示分摊

        薪资单金额不改。跨月周期在每个重叠的自然月各出一行，金额按重叠天数占比。

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID，空表示当前可见范围
        :param month: 月份 ``YYYY-MM``，空表示全部月份
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
            site_ids: set[int] | None = {site_id}
        else:
            site_ids = visible
        month_key, start, end = parse_report_month(month)
        period_stmt = select(RiderSalarySettlePeriod).where(
            RiderSalarySettlePeriod.deleted == 0,
            _site_clause(RiderSalarySettlePeriod.site_id, site_ids),
        )
        if start is not None and end is not None:
            period_stmt = period_stmt.where(
                RiderSalarySettlePeriod.start_date <= end,
                RiderSalarySettlePeriod.end_date >= start,
            )
        periods = list((await db.scalars(period_stmt)).all())
        if not periods:
            return _empty_cost(month_key)
        period_ids = [int(row.id) for row in periods]
        payrolls = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.period_id.in_(period_ids),
                        RiderSalaryPayroll.deleted == 0,
                    )
                )
            ).all()
        )
        costs = summarize_site_month_cost(periods, payrolls)
        if month_key is not None:
            costs = [item for item in costs if item.month == month_key]
        names = await _site_labels(db, {item.site_id for item in costs})
        rows = [
            SiteMonthCostRow(
                site_id=item.site_id,
                site_code=names.get(item.site_id, ('', ''))[0],
                site_name=names.get(item.site_id, ('', ''))[1],
                month=item.month,
                slip_count=item.slip_count,
                gross=item.gross,
                net=item.net,
                advance_deduction=item.advance_deduction,
            )
            for item in costs
        ]
        return GetCostSummary(
            month=month_key,
            allocation_note=COST_DISPLAY_ALLOCATION_NOTE,
            rows=rows,
            slip_count=sum(item.slip_count for item in rows),
            gross=q2(sum((item.gross for item in rows), ZERO)),
            net=q2(sum((item.net for item in rows), ZERO)),
            advance_deduction=q2(sum((item.advance_deduction for item in rows), ZERO)),
        )


def _empty_cost(month: str | None) -> GetCostSummary:
    return GetCostSummary(
        month=month,
        allocation_note=COST_DISPLAY_ALLOCATION_NOTE,
        rows=[],
        slip_count=0,
        gross=ZERO,
        net=ZERO,
        advance_deduction=ZERO,
    )


async def _site_labels(db: AsyncSession, site_ids: set[int]) -> dict[int, tuple[str, str]]:
    if not site_ids:
        return {}
    sites = list((await db.scalars(select(RiderSalarySite).where(RiderSalarySite.id.in_(list(site_ids))))).all())
    return {int(site.id): (site.code or '', site.name or '') for site in sites}


report_service: ReportService = ReportService()
