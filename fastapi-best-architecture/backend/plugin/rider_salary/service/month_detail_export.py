"""自然月单文件明细导出。

半月结的同一个月只生成一个工作簿。逐单公式、按日公式、手工科目，以及还没有
逐单明细的订单，都写在「当月明细」这一张表里，用周期列区分所属结算周期。

行来自 P0-08 有效单读层：作废、反冲、已被反冲的薪资单不进入导出。数据行按
数据库窗口逐行写入 write_only 工作簿，不先收成列表。
"""

from calendar import monthrange
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.settle_period import SITE_LEVEL_RIDER_ID
from backend.plugin.rider_salary.enums import CalcStage, DetailSource, PeriodStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.order import order_status_label
from backend.plugin.rider_salary.service.audit_service import audit_service
from backend.plugin.rider_salary.service.payroll_view import effective_payroll_ids
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.excel import (
    StreamingWorkbook,
    append_streamed_rows,
    assert_export_row_limit,
    stream_rows,
    stream_scalars,
)
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

MONTH_DETAIL_SHEET = '当月明细'
MONTH_DETAIL_HEADERS = [
    '日期',
    '工号',
    '姓名',
    '站点',
    '订单号',
    '距离(公里)',
    '重量(斤)',
    '下单时间',
    '送达时间',
    '订单状态',
    '方案短名',
    '版本号',
    '科目',
    '金额',
    '来源',
    '是否进应发',
    '周期',
    '周期状态',
]
_FORMULA_STAGES = (CalcStage.per_order.value, CalcStage.daily.value)


def parse_export_month(month: str) -> tuple[str, date, date]:
    """
    解析自然月

    :param month: ``YYYY-MM``
    :return: 规范化月份、月初、月末
    """
    text = (month or '').strip()
    parts = text.split('-')
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise errors.RequestError(msg='月份格式应为 YYYY-MM')
    try:
        year = int(parts[0])
        mon = int(parts[1])
        start = date(year, mon, 1)
    except ValueError as exc:
        raise errors.RequestError(msg='月份格式应为 YYYY-MM') from exc
    if mon < 1 or mon > 12:
        raise errors.RequestError(msg='月份格式应为 YYYY-MM')
    end = date(year, mon, monthrange(year, mon)[1])
    return f'{year:04d}-{mon:02d}', start, end


def month_detail_included(*, source: str, stage: str) -> bool:
    """
    这一行是否属于「订单行 + 当日公式 + 手工科目」

    逐单公式是订单行，按日公式是当日公式，手工来源是手工科目。
    周期公式、预支抵扣和反冲明细不进这张表。

    :param source: 明细来源
    :param stage: 计算阶段
    :return:
    """
    if source == DetailSource.manual.value:
        return True
    return source == DetailSource.formula.value and stage in _FORMULA_STAGES


def payroll_ids_for_month_export(payrolls: Sequence[Any]) -> list[int]:
    """
    有效单 id，升序

    :param payrolls: 与自然月相交的周期上的薪资单
    :return: 有效单 id；作废、反冲、已被反冲的单不在其中
    """
    return sorted(effective_payroll_ids(payrolls))


def period_column_text(start: date, end: date) -> str:
    """
    周期列文本

    :param start: 周期开始
    :param end: 周期结束
    :return:
    """
    return f'{start.isoformat()}~{end.isoformat()}'


def pick_period_for_day(periods: Sequence[Any], rider_id: int, day: date) -> Any | None:
    """
    为还没有薪资明细的订单挑所属周期

    骑手级周期优先于站点级。同一级别里取开始日最晚、编号较小的一条。
    只读已有周期，不创建。

    :param periods: 与该月相交的周期
    :param rider_id: 骑手 ID
    :param day: 业务日期
    :return:
    """
    covering = [
        row
        for row in periods
        if row.start_date <= day <= row.end_date and int(row.rider_id) in (SITE_LEVEL_RIDER_ID, rider_id)
    ]
    rider_level = [row for row in covering if int(row.rider_id) == rider_id and rider_id != SITE_LEVEL_RIDER_ID]
    pool = rider_level or [row for row in covering if int(row.rider_id) == SITE_LEVEL_RIDER_ID]
    if not pool:
        return None
    pool.sort(key=lambda row: (row.start_date, -int(row.id)))
    return pool[-1]


def build_month_detail_row(
    *,
    biz_date: date | None,
    job_no: str,
    rider_name: str,
    site_name: str,
    order_no: str = '',
    distance_km: object = None,
    weight_jin: object = None,
    order_time: datetime | None = None,
    deliver_time: datetime | None = None,
    order_status: str = '',
    plan_short_name: str = '',
    version_no: int | None = None,
    subject_name: str = '',
    amount: object = None,
    source: str = '',
    include_in_gross: bool | None = None,
    period_text: str = '',
    period_status: str = '',
) -> list[object]:
    """
    组装一行当月明细，列顺序与表头一致

    :param biz_date: 业务日期
    :param job_no: 工号
    :param rider_name: 姓名
    :param site_name: 站点
    :param order_no: 订单号
    :param distance_km: 距离
    :param weight_jin: 重量
    :param order_time: 下单时间
    :param deliver_time: 送达时间
    :param order_status: 订单状态枚举值
    :param plan_short_name: 方案短名
    :param version_no: 版本号
    :param subject_name: 科目
    :param amount: 金额
    :param source: 明细来源枚举值，订单行可空
    :param include_in_gross: 是否进应发，订单行可空
    :param period_text: 周期区间
    :param period_status: 周期状态中文
    :return:
    """
    return [
        biz_date.isoformat() if biz_date else '',
        job_no or '',
        rider_name or '',
        site_name,
        order_no or '',
        '' if distance_km is None else str(distance_km),
        '' if weight_jin is None else str(weight_jin),
        timezone.to_str(order_time) if order_time else '',
        timezone.to_str(deliver_time) if deliver_time else '',
        order_status_label(order_status) if order_status else '',
        plan_short_name or '',
        '' if version_no is None else f'v{int(version_no)}',
        subject_name or '',
        '' if amount is None else float(q2(amount)),
        _source_label(source),
        _yes_no(flag=include_in_gross),
        period_text,
        period_status,
    ]


def _source_label(source: str) -> str:
    if not source:
        return ''
    try:
        return DetailSource(source).label
    except ValueError:
        return source


def _yes_no(*, flag: bool | None) -> str:
    if flag is None:
        return ''
    return '是' if flag else '否'


def _period_status_label(status: str) -> str:
    try:
        return PeriodStatus(status).label
    except ValueError:
        return status or ''


def _period_cells(period: Any | None) -> tuple[str, str]:
    if period is None:
        return '', ''
    return period_column_text(period.start_date, period.end_date), _period_status_label(period.status)


def _detail_filters(
    effective_ids: Sequence[int],
    start: date,
    end: date,
    rider_id: int | None,
) -> list[Any]:
    filters: list[Any] = [
        RiderSalaryPayrollDetail.deleted == 0,
        RiderSalaryPayrollDetail.biz_date >= start,
        RiderSalaryPayrollDetail.biz_date <= end,
        RiderSalaryPayrollDetail.payroll_id.in_(list(effective_ids)),
        or_(
            RiderSalaryPayrollDetail.source == DetailSource.manual.value,
            and_(
                RiderSalaryPayrollDetail.source == DetailSource.formula.value,
                RiderSalaryPayrollDetail.stage.in_(_FORMULA_STAGES),
            ),
        ),
    ]
    if rider_id is not None:
        filters.append(RiderSalaryPayrollDetail.rider_id == rider_id)
    return filters


def _covered_order_exists(effective_ids: Sequence[int], start: date, end: date) -> Any:
    """已经作为逐单公式写进有效单的订单，不再单独占一行。"""
    ids = list(effective_ids) if effective_ids else [-1]
    return (
        select(RiderSalaryPayrollDetail.id)
        .where(
            RiderSalaryPayrollDetail.order_id == RiderSalaryOrder.id,
            RiderSalaryPayrollDetail.deleted == 0,
            RiderSalaryPayrollDetail.order_id.is_not(None),
            RiderSalaryPayrollDetail.biz_date >= start,
            RiderSalaryPayrollDetail.biz_date <= end,
            RiderSalaryPayrollDetail.source == DetailSource.formula.value,
            RiderSalaryPayrollDetail.stage == CalcStage.per_order.value,
            RiderSalaryPayrollDetail.payroll_id.in_(ids),
        )
        .exists()
    )


def _bare_order_filters(
    *,
    site_id: int,
    rider_id: int | None,
    start: date,
    end: date,
    effective_ids: Sequence[int],
) -> list[Any]:
    filters: list[Any] = [
        RiderSalaryOrder.site_id == site_id,
        RiderSalaryOrder.deleted == 0,
        RiderSalaryOrder.biz_date >= start,
        RiderSalaryOrder.biz_date <= end,
        ~_covered_order_exists(effective_ids, start, end),
    ]
    if rider_id is not None:
        filters.append(RiderSalaryOrder.rider_id == rider_id)
    return filters


def _detail_stmt(effective_ids: Sequence[int], start: date, end: date, rider_id: int | None) -> Any:
    return (
        select(
            RiderSalaryPayrollDetail.biz_date,
            RiderSalaryRider.job_no,
            RiderSalaryRider.name,
            RiderSalaryOrder.order_no,
            RiderSalaryOrder.distance_km,
            RiderSalaryOrder.weight_jin,
            RiderSalaryOrder.order_time,
            RiderSalaryOrder.deliver_time,
            RiderSalaryOrder.status,
            RiderSalaryPlan.short_name,
            RiderSalaryPlanVersion.version_no,
            RiderSalarySubject.name,
            RiderSalaryPayrollDetail.amount,
            RiderSalaryPayrollDetail.source,
            RiderSalaryPayrollDetail.include_in_gross,
            RiderSalaryPayroll.period_id,
        )
        .select_from(RiderSalaryPayrollDetail)
        .outerjoin(RiderSalaryRider, RiderSalaryRider.id == RiderSalaryPayrollDetail.rider_id)
        .outerjoin(RiderSalaryOrder, RiderSalaryOrder.id == RiderSalaryPayrollDetail.order_id)
        .outerjoin(RiderSalarySubject, RiderSalarySubject.id == RiderSalaryPayrollDetail.subject_id)
        .outerjoin(
            RiderSalaryPlanVersion,
            RiderSalaryPlanVersion.id == RiderSalaryPayrollDetail.plan_version_id,
        )
        .outerjoin(RiderSalaryPlan, RiderSalaryPlan.id == RiderSalaryPlanVersion.plan_id)
        .join(RiderSalaryPayroll, RiderSalaryPayroll.id == RiderSalaryPayrollDetail.payroll_id)
        .where(*_detail_filters(effective_ids, start, end, rider_id))
        .order_by(
            RiderSalaryPayrollDetail.biz_date.asc(),
            RiderSalaryPayrollDetail.rider_id.asc(),
            RiderSalaryPayrollDetail.id.asc(),
        )
    )


def _bare_order_stmt(
    *,
    site_id: int,
    rider_id: int | None,
    start: date,
    end: date,
    effective_ids: Sequence[int],
) -> Any:
    return (
        select(
            RiderSalaryOrder.biz_date,
            RiderSalaryOrder.rider_id,
            RiderSalaryRider.job_no,
            RiderSalaryRider.name,
            RiderSalaryOrder.order_no,
            RiderSalaryOrder.distance_km,
            RiderSalaryOrder.weight_jin,
            RiderSalaryOrder.order_time,
            RiderSalaryOrder.deliver_time,
            RiderSalaryOrder.status,
        )
        .select_from(RiderSalaryOrder)
        .outerjoin(RiderSalaryRider, RiderSalaryRider.id == RiderSalaryOrder.rider_id)
        .where(
            *_bare_order_filters(
                site_id=site_id,
                rider_id=rider_id,
                start=start,
                end=end,
                effective_ids=effective_ids,
            )
        )
        .order_by(RiderSalaryOrder.biz_date.asc(), RiderSalaryOrder.id.asc())
    )


def _row_from_detail(packed: Any, site_name: str, period_by_id: dict[int, Any]) -> list[object]:
    period_id = packed[15]
    period_text, period_status = _period_cells(period_by_id.get(int(period_id)) if period_id else None)
    return build_month_detail_row(
        biz_date=packed[0],
        job_no=packed[1] or '',
        rider_name=packed[2] or '',
        site_name=site_name,
        order_no=packed[3] or '',
        distance_km=packed[4],
        weight_jin=packed[5],
        order_time=packed[6],
        deliver_time=packed[7],
        order_status=packed[8] or '',
        plan_short_name=packed[9] or '',
        version_no=None if packed[10] is None else int(packed[10]),
        subject_name=packed[11] or '',
        amount=packed[12],
        source=packed[13] or '',
        include_in_gross=bool(packed[14]) if packed[14] is not None else None,
        period_text=period_text,
        period_status=period_status,
    )


def _row_from_order(packed: Any, site_name: str, periods: Sequence[Any]) -> list[object]:
    day = packed[0]
    rider_id = int(packed[1] or 0)
    period_text, period_status = _period_cells(pick_period_for_day(periods, rider_id, day) if day else None)
    return build_month_detail_row(
        biz_date=day,
        job_no=packed[2] or '',
        rider_name=packed[3] or '',
        site_name=site_name,
        order_no=packed[4] or '',
        distance_km=packed[5],
        weight_jin=packed[6],
        order_time=packed[7],
        deliver_time=packed[8],
        order_status=packed[9] or '',
        period_text=period_text,
        period_status=period_status,
    )


async def _count(db: AsyncSession, stmt: Any) -> int:
    total = await db.scalar(stmt)
    return int(total or 0)


async def _load_periods(
    db: AsyncSession,
    site_id: int,
    rider_id: int | None,
    start: date,
    end: date,
) -> list[RiderSalarySettlePeriod]:
    """读出与自然月相交的周期。不生成、不改写。"""
    stmt = select(RiderSalarySettlePeriod).where(
        RiderSalarySettlePeriod.site_id == site_id,
        RiderSalarySettlePeriod.deleted == 0,
        RiderSalarySettlePeriod.start_date <= end,
        RiderSalarySettlePeriod.end_date >= start,
    )
    if rider_id is not None:
        stmt = stmt.where(RiderSalarySettlePeriod.rider_id.in_([SITE_LEVEL_RIDER_ID, rider_id]))
    stmt = stmt.order_by(RiderSalarySettlePeriod.start_date.asc(), RiderSalarySettlePeriod.id.asc())
    return list((await db.scalars(stmt)).all())


async def _load_payrolls(
    db: AsyncSession,
    period_ids: Sequence[int],
    rider_id: int | None,
) -> list[RiderSalaryPayroll]:
    """只流式取出薪资单头，供有效单读层挑单。明细不在这里装进列表。"""
    if not period_ids:
        return []
    stmt = select(RiderSalaryPayroll).where(
        RiderSalaryPayroll.period_id.in_(list(period_ids)),
        RiderSalaryPayroll.deleted == 0,
    )
    if rider_id is not None:
        stmt = stmt.where(RiderSalaryPayroll.rider_id == rider_id)
    stmt = stmt.order_by(RiderSalaryPayroll.id.asc())
    found: list[RiderSalaryPayroll] = []
    async for row in stream_scalars(db, stmt):
        found.append(row)
        db.expunge(row)
    return found


async def _iter_month_detail_rows(
    db: AsyncSession,
    *,
    site_name: str,
    periods: Sequence[Any],
    effective_ids: Sequence[int],
    site_id: int,
    rider_id: int | None,
    start: date,
    end: date,
) -> AsyncIterator[list[object]]:
    """逐行产出当月明细。迭代器前进一步只消费数据库里的一行。"""
    period_by_id = {int(row.id): row for row in periods}
    if effective_ids:
        async for packed in stream_rows(db, _detail_stmt(effective_ids, start, end, rider_id)):
            yield _row_from_detail(packed, site_name, period_by_id)
    async for packed in stream_rows(
        db,
        _bare_order_stmt(site_id=site_id, rider_id=rider_id, start=start, end=end, effective_ids=effective_ids),
    ):
        yield _row_from_order(packed, site_name, periods)


def _filename(site_name: str, rider_name: str | None, month_text: str) -> str:
    who = f'_{rider_name}' if rider_name else ''
    return f'当月明细_{site_name}{who}_{month_text}.xlsx'


async def _get_site(db: AsyncSession, site_id: int) -> RiderSalarySite:
    site = await db.scalar(select(RiderSalarySite).where(RiderSalarySite.id == site_id, RiderSalarySite.deleted == 0))
    if site is None:
        raise errors.NotFoundError(msg='站点不存在')
    return site


async def _get_rider(db: AsyncSession, rider_id: int) -> RiderSalaryRider:
    rider = await db.scalar(
        select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
    )
    if rider is None:
        raise errors.NotFoundError(msg='骑手不存在')
    return rider


class MonthDetailExportService:
    """按自然月导出一张明细表"""

    async def export(
        self,
        *,
        db: AsyncSession,
        request: Request,
        site_id: int,
        month: str,
        rider_id: int | None,
    ) -> tuple[bytes, str]:
        """
        导出一个自然月的明细 xlsx

        半月结会命中两段周期，仍然只返回一个文件，周期列写出各自的区间。

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param month: 自然月 ``YYYY-MM``
        :param rider_id: 骑手 ID，空则导出该站全部骑手
        :return: 文件字节, 文件名
        """
        month_text, start, end = parse_export_month(month)
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, site_id)
        site = await _get_site(db, site_id)
        rider = await _get_rider(db, rider_id) if rider_id is not None else None
        periods = await _load_periods(db, site_id, rider_id, start, end)
        payrolls = await _load_payrolls(db, [int(row.id) for row in periods], rider_id)
        effective_ids = payroll_ids_for_month_export(payrolls)
        detail_count = 0
        if effective_ids:
            detail_count = await _count(
                db,
                select(func.count())
                .select_from(RiderSalaryPayrollDetail)
                .where(*_detail_filters(effective_ids, start, end, rider_id)),
            )
        order_count = await _count(
            db,
            select(func.count())
            .select_from(RiderSalaryOrder)
            .where(
                *_bare_order_filters(
                    site_id=site_id,
                    rider_id=rider_id,
                    start=start,
                    end=end,
                    effective_ids=effective_ids,
                )
            ),
        )
        assert_export_row_limit(detail_count + order_count)
        book = StreamingWorkbook()
        sheet = book.add_sheet(MONTH_DETAIL_SHEET, MONTH_DETAIL_HEADERS)
        await append_streamed_rows(
            book,
            sheet,
            _iter_month_detail_rows(
                db,
                site_name=site.name,
                periods=periods,
                effective_ids=effective_ids,
                site_id=site_id,
                rider_id=rider_id,
                start=start,
                end=end,
            ),
        )
        content = book.to_bytes()
        rider_name = rider.name if rider is not None else None
        filename = _filename(site.name, rider_name, month_text)
        await audit_service.record(
            db,
            request,
            module='薪资日历',
            action='导出当月明细',
            target_type='site',
            target_id=site_id,
            target_label=f'{site.name} {month_text}',
            site_id=site_id,
        )
        return content, filename


month_detail_export_service = MonthDetailExportService()
