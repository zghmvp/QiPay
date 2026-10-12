from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.settle_period import SITE_LEVEL_RIDER_ID
from backend.plugin.rider_salary.enums import CalcStage, DetailSource, PayrollKind, PayrollStatus
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.service.audit_service import audit_service
from backend.plugin.rider_salary.service.payroll_view import (
    RiderPayrollView,
    build_rider_views,
    live_payrolls_of_kind,
)
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.utils.audit import operator_display_name
from backend.plugin.rider_salary.utils.excel import (
    StreamingWorkbook,
    append_streamed_rows,
    assert_export_row_limit,
    stream_rows,
    stream_scalars,
)
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

SUMMARY_HEADERS = [
    '工号',
    '姓名',
    '站点',
    '周期',
    '单据类型',
    '状态',
    '单量',
    '有效单量',
    '逐单合计',
    '按日合计',
    '周期项合计',
    '手工奖',
    '手工惩',
    '应发',
    '代扣',
    '预支抵扣',
    '实发',
    '计算时间',
]
DETAIL_HEADERS = [
    '工号',
    '姓名',
    '日期',
    '阶段',
    '方案',
    '科目',
    '订单号',
    '金额',
    '是否进应发',
    '来源',
    '计算过程',
]
ADJUSTMENT_HEADERS = [
    '工号',
    '姓名',
    '日期',
    '科目',
    '金额',
    '带符号金额',
    '备注',
    '是否锁账',
]
NET_HEADERS = ['工号', '姓名', '原单', '反冲', '补发', '净差', '最终实发']
HISTORY_HEADERS = [*SUMMARY_HEADERS, '已被反冲', '反冲对象']

SHEET_SUMMARY = '薪资汇总'
SHEET_DETAIL = '薪资明细'
SHEET_ADJUSTMENT = '奖惩记录'
SHEET_NET = '净额对照'
SHEET_ORIGINAL = '原单'
SHEET_REVERSAL = '反冲'
SHEET_SUPPLEMENT = '补发'


def summarize_trace(trace: dict[str, Any] | None) -> str:
    """
    将 calc_trace 摘要成一行中文

    :param trace: 计算过程
    :return:
    """
    if not trace:
        return ''
    parts: list[str] = []
    condition = trace.get('条件')
    if condition not in (None, ''):
        flag = '真' if trace.get('条件结果') else '假'
        parts.append(f'条件：{condition}（{flag}）')
    formula = trace.get('公式')
    if formula not in (None, ''):
        parts.append(f'公式：{formula}')
    variables = trace.get('变量')
    if isinstance(variables, dict) and variables:
        joined = '，'.join(f'{key}={value}' for key, value in variables.items())
        parts.append(joined)
    if '结果' in trace:
        parts.append(f'结果={trace["结果"]}')
    return '；'.join(parts)


def content_disposition(filename: str) -> str:
    """RFC 5987 Content-Disposition"""
    ascii_name = 'payroll.xlsx'
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def _label(enum_cls: type, value: Any) -> str:
    try:
        return enum_cls(value).label
    except ValueError:
        return str(value or '')


def _excel_number(value: Any) -> float | None:
    if value is None:
        return None
    return float(q2(value))


def _excel_time(value: datetime | None) -> str:
    if value is None:
        return ''
    return timezone.to_str(value)


def _yes_no(*, flag: bool) -> str:
    return '是' if flag else '否'


def _rider_cells(riders: dict[int, Any], rider_id: int) -> tuple[str, str]:
    rider = riders.get(rider_id)
    if rider is None:
        return str(rider_id), ''
    return getattr(rider, 'job_no', None) or str(rider_id), getattr(rider, 'name', None) or ''


def _summary_row(
    payroll: Any,
    riders: dict[int, Any],
    *,
    site_name: str,
    period_text: str,
) -> list:
    job_no, name = _rider_cells(riders, int(payroll.rider_id))
    return [
        job_no,
        name,
        site_name,
        period_text,
        _label(PayrollKind, payroll.kind),
        _label(PayrollStatus, payroll.status),
        payroll.order_count,
        payroll.valid_order_count,
        _excel_number(payroll.per_order_total),
        _excel_number(payroll.daily_total),
        _excel_number(payroll.period_total),
        _excel_number(payroll.bonus_total),
        _excel_number(payroll.penalty_total),
        _excel_number(payroll.gross),
        _excel_number(payroll.deduction_total),
        _excel_number(payroll.advance_deduction),
        _excel_number(payroll.net),
        _excel_time(payroll.calc_time),
    ]


def _history_row(
    payroll: Any,
    riders: dict[int, Any],
    *,
    site_name: str,
    period_text: str,
) -> list:
    row = _summary_row(payroll, riders, site_name=site_name, period_text=period_text)
    target = getattr(payroll, 'reversed_of_id', None)
    row.append(_yes_no(flag=bool(getattr(payroll, 'reversed', False))))
    row.append('' if target is None else int(target))
    return row


def _detail_row(
    detail: Any,
    riders: dict[int, Any],
    rider_id: int,
    *,
    plan_names: dict[int, str],
    subject_names: dict[int, str],
    order_nos: dict[int, str],
) -> list:
    job_no, name = _rider_cells(riders, rider_id)
    return [
        job_no,
        name,
        detail.biz_date.isoformat() if detail.biz_date else '',
        _label(CalcStage, detail.stage),
        plan_names.get(detail.plan_version_id or 0, ''),
        subject_names.get(detail.subject_id, str(detail.subject_id)),
        order_nos.get(detail.order_id or 0, '') if detail.order_id else '',
        _excel_number(detail.amount),
        _yes_no(flag=bool(detail.include_in_gross)),
        _label(DetailSource, detail.source),
        summarize_trace(detail.calc_trace),
    ]


def _net_row(view: RiderPayrollView, riders: dict[int, Any]) -> list:
    job_no, name = _rider_cells(riders, view.rider_id)
    return [
        job_no,
        name,
        _excel_number(view.original_net),
        _excel_number(view.reversal_net),
        _excel_number(view.supplement_net),
        _excel_number(view.net_diff),
        _excel_number(view.final_net),
    ]


def period_export_upper_bound(payroll_count: int, detail_count: int, adjustment_count: int) -> int:
    """汇总、净额和历史分表各最多一行薪资单，再加上明细和奖惩。"""
    return detail_count + adjustment_count + payroll_count * 3


def _adjustment_filters(period: RiderSalarySettlePeriod) -> list[Any]:
    clauses: list[Any] = [
        RiderSalaryAdjustment.site_id == period.site_id,
        RiderSalaryAdjustment.biz_date >= period.start_date,
        RiderSalaryAdjustment.biz_date <= period.end_date,
        RiderSalaryAdjustment.deleted == 0,
    ]
    if period.rider_id and period.rider_id != SITE_LEVEL_RIDER_ID:
        clauses.append(RiderSalaryAdjustment.rider_id == period.rider_id)
    return clauses


def build_payroll_export_sheets(
    payrolls: list[Any],
    details: list[Any],
    riders: dict[int, Any],
    *,
    site_name: str,
    period_text: str,
    plan_names: dict[int, str],
    subject_names: dict[int, str],
    order_nos: dict[int, str],
) -> list[tuple[str, list[str], list[list]]]:
    """
    组装薪资汇总、明细、净额对照，以及原单 / 反冲 / 补发历史分表

    汇总和明细只含有效单。作废单不进入任何表。历史分表保留已被反冲的在册单据。
    净差 = 当前有效补发 − 原单；最终实发是有效单实发。

    :param payrolls: 本周期薪资单
    :param details: 明细
    :param riders: 骑手
    :param site_name: 站点名称
    :param period_text: 周期起止
    :param plan_names: 方案版本显示名
    :param subject_names: 科目名称
    :param order_nos: 订单号
    :return: (表名, 表头, 数据行)
    """
    views = build_rider_views(payrolls, details)
    effective = [view.effective for view in views if view.effective is not None]
    effective.sort(key=lambda row: int(getattr(row, 'id', 0) or 0))
    summary_rows = [_summary_row(row, riders, site_name=site_name, period_text=period_text) for row in effective]
    detail_rows: list[list] = []
    for view in views:
        payroll = view.effective
        if payroll is None:
            continue
        detail_rows.extend(
            _detail_row(
                detail,
                riders,
                int(payroll.rider_id),
                plan_names=plan_names,
                subject_names=subject_names,
                order_nos=order_nos,
            )
            for detail in view.details
        )
    net_rows = [_net_row(view, riders) for view in views if view.has_live]
    context = {'site_name': site_name, 'period_text': period_text}
    return [
        (SHEET_SUMMARY, SUMMARY_HEADERS, summary_rows),
        (SHEET_DETAIL, DETAIL_HEADERS, detail_rows),
        (SHEET_NET, NET_HEADERS, net_rows),
        (
            SHEET_ORIGINAL,
            HISTORY_HEADERS,
            [_history_row(row, riders, **context) for row in live_payrolls_of_kind(payrolls, PayrollKind.normal.value)],
        ),
        (
            SHEET_REVERSAL,
            HISTORY_HEADERS,
            [
                _history_row(row, riders, **context)
                for row in live_payrolls_of_kind(payrolls, PayrollKind.reversal.value)
            ],
        ),
        (
            SHEET_SUPPLEMENT,
            HISTORY_HEADERS,
            [
                _history_row(row, riders, **context)
                for row in live_payrolls_of_kind(payrolls, PayrollKind.supplement.value)
            ],
        ),
    ]


class ExportService:
    """薪资导出服务"""

    async def export_period(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
    ) -> tuple[bytes, str]:
        """
        导出周期薪资 xlsx

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :return: 文件字节, 文件名
        """
        period, site, _rider = await period_service.load_visible(db, request, pk)
        payroll_count, detail_count, adjustment_count = await self._period_export_counts(db, period)
        assert_export_row_limit(period_export_upper_bound(payroll_count, detail_count, adjustment_count))
        payrolls = list(await payroll_dao.select_models_order(db, 'id', 'asc', period_id=period.id, deleted=0))
        riders = await period_service.rider_map(db, [row.rider_id for row in payrolls])
        site_name = site.name if site is not None else str(period.site_id)
        period_text = f'{period.start_date}~{period.end_date}'
        views = build_rider_views(payrolls)
        effective = [view.effective for view in views if view.effective is not None]
        effective.sort(key=lambda row: int(getattr(row, 'id', 0) or 0))
        effective_ids = [int(row.id) for row in effective]
        plan_names, subject_names = await self._dimension_names(db, effective_ids)
        riders, subjects = await self._adjustment_dimensions(db, period, riders)
        book = StreamingWorkbook()
        summary_sheet = book.add_sheet(SHEET_SUMMARY, SUMMARY_HEADERS)
        for payroll in effective:
            book.append(summary_sheet, _summary_row(payroll, riders, site_name=site_name, period_text=period_text))
        detail_sheet = book.add_sheet(SHEET_DETAIL, DETAIL_HEADERS)
        await append_streamed_rows(
            book,
            detail_sheet,
            self._iter_detail_rows(
                db,
                effective_ids,
                riders,
                plan_names=plan_names,
                subject_names=subject_names,
            ),
        )
        adjustment_sheet = book.add_sheet(SHEET_ADJUSTMENT, ADJUSTMENT_HEADERS)
        await append_streamed_rows(book, adjustment_sheet, self._iter_adjustment_rows(db, period, riders, subjects))
        net_sheet = book.add_sheet(SHEET_NET, NET_HEADERS)
        for view in views:
            if view.has_live:
                book.append(net_sheet, _net_row(view, riders))
        history = (
            (SHEET_ORIGINAL, PayrollKind.normal.value),
            (SHEET_REVERSAL, PayrollKind.reversal.value),
            (SHEET_SUPPLEMENT, PayrollKind.supplement.value),
        )
        context = {'site_name': site_name, 'period_text': period_text}
        for title, kind in history:
            sheet = book.add_sheet(title, HISTORY_HEADERS)
            for payroll in live_payrolls_of_kind(payrolls, kind):
                book.append(sheet, _history_row(payroll, riders, **context))
        content = book.to_bytes()
        filename = f'薪资导出_{site_name}_{period.start_date}_{period.end_date}.xlsx'
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='导出',
            target_type='period',
            target_id=period.id,
            target_label=f'{site_name} {period_text}',
            description=(
                f'{operator_display_name(request)} 于 {timezone.to_str(timezone.now())} '
                f'对 周期{site_name} {period_text} 执行了导出'
            ),
        )
        return content, filename

    async def _period_export_counts(
        self,
        db: AsyncSession,
        period: RiderSalarySettlePeriod,
    ) -> tuple[int, int, int]:
        """计数薪资单、明细和奖惩，不把行装进内存。"""
        payroll_ids = select(RiderSalaryPayroll.id).where(
            RiderSalaryPayroll.period_id == period.id,
            RiderSalaryPayroll.deleted == 0,
        )
        payroll_count = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryPayroll)
                .where(
                    RiderSalaryPayroll.period_id == period.id,
                    RiderSalaryPayroll.deleted == 0,
                )
            )
            or 0
        )
        detail_count = int(
            await db.scalar(
                select(func.count())
                .select_from(RiderSalaryPayrollDetail)
                .where(
                    RiderSalaryPayrollDetail.payroll_id.in_(payroll_ids),
                    RiderSalaryPayrollDetail.deleted == 0,
                )
            )
            or 0
        )
        adjustment_count = int(
            await db.scalar(select(func.count()).select_from(RiderSalaryAdjustment).where(*_adjustment_filters(period)))
            or 0
        )
        return payroll_count, detail_count, adjustment_count

    async def _dimension_names(
        self,
        db: AsyncSession,
        payroll_ids: list[int],
    ) -> tuple[dict[int, str], dict[int, str]]:
        """只取明细里出现过的方案和科目名称。"""
        if not payroll_ids:
            return {}, {}
        version_ids = {
            int(item)
            for item in (
                await db.scalars(
                    select(RiderSalaryPayrollDetail.plan_version_id)
                    .where(
                        RiderSalaryPayrollDetail.payroll_id.in_(payroll_ids),
                        RiderSalaryPayrollDetail.deleted == 0,
                        RiderSalaryPayrollDetail.plan_version_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
            if item
        }
        subject_ids = {
            int(item)
            for item in (
                await db.scalars(
                    select(RiderSalaryPayrollDetail.subject_id)
                    .where(
                        RiderSalaryPayrollDetail.payroll_id.in_(payroll_ids),
                        RiderSalaryPayrollDetail.deleted == 0,
                        RiderSalaryPayrollDetail.subject_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
            if item
        }
        plan_names: dict[int, str] = {}
        if version_ids:
            versions = list(
                (
                    await db.scalars(
                        select(RiderSalaryPlanVersion).where(RiderSalaryPlanVersion.id.in_(list(version_ids)))
                    )
                ).all()
            )
            plan_ids = {row.plan_id for row in versions}
            plans: dict[int, RiderSalaryPlan] = {}
            if plan_ids:
                plan_rows = await db.scalars(select(RiderSalaryPlan).where(RiderSalaryPlan.id.in_(list(plan_ids))))
                plans = {row.id: row for row in plan_rows.all()}
            for version in versions:
                plan = plans.get(version.plan_id)
                plan_names[version.id] = plan.short_name if plan is not None else f'v{version.version_no}'
        subject_names: dict[int, str] = {}
        if subject_ids:
            rows = await db.scalars(select(RiderSalarySubject).where(RiderSalarySubject.id.in_(list(subject_ids))))
            subject_names = {row.id: row.name for row in rows.all()}
        return plan_names, subject_names

    async def _iter_detail_rows(
        self,
        db: AsyncSession,
        payroll_ids: list[int],
        riders: dict[int, Any],
        *,
        plan_names: dict[int, str],
        subject_names: dict[int, str],
    ) -> AsyncIterator[list[object]]:
        """逐行产出薪资明细。订单号随明细一起取出，不先攒全部明细。"""
        if not payroll_ids:
            return
        stmt = (
            select(RiderSalaryPayrollDetail, RiderSalaryOrder.order_no)
            .outerjoin(RiderSalaryOrder, RiderSalaryOrder.id == RiderSalaryPayrollDetail.order_id)
            .where(
                RiderSalaryPayrollDetail.payroll_id.in_(payroll_ids),
                RiderSalaryPayrollDetail.deleted == 0,
            )
            .order_by(RiderSalaryPayrollDetail.payroll_id.asc(), RiderSalaryPayrollDetail.id.asc())
        )
        async for packed in stream_rows(db, stmt):
            detail = packed[0]
            order_no = packed[1]
            order_nos = {int(detail.order_id): order_no} if detail.order_id and order_no else {}
            values = _detail_row(
                detail,
                riders,
                int(detail.rider_id),
                plan_names=plan_names,
                subject_names=subject_names,
                order_nos=order_nos,
            )
            db.expunge(detail)
            yield values

    async def _adjustment_dimensions(
        self,
        db: AsyncSession,
        period: RiderSalarySettlePeriod,
        payroll_riders: dict[int, RiderSalaryRider],
    ) -> tuple[dict[int, RiderSalaryRider], dict[int, RiderSalarySubject]]:
        """奖惩导出前只取骑手和科目，不取出奖惩行。"""
        filters = _adjustment_filters(period)
        rider_ids = [
            int(item)
            for item in (await db.scalars(select(RiderSalaryAdjustment.rider_id).where(*filters).distinct())).all()
        ]
        subject_ids = [
            int(item)
            for item in (await db.scalars(select(RiderSalaryAdjustment.subject_id).where(*filters).distinct())).all()
        ]
        riders = dict(payroll_riders)
        riders.update(await period_service.rider_map(db, rider_ids))
        subjects: dict[int, RiderSalarySubject] = {}
        if subject_ids:
            rows = await db.scalars(select(RiderSalarySubject).where(RiderSalarySubject.id.in_(subject_ids)))
            subjects = {row.id: row for row in rows.all()}
        return riders, subjects

    async def _iter_adjustment_rows(
        self,
        db: AsyncSession,
        period: RiderSalarySettlePeriod,
        riders: dict[int, RiderSalaryRider],
        subjects: dict[int, RiderSalarySubject],
    ) -> AsyncIterator[list[object]]:
        """逐行产出奖惩。迭代器前进一步只消费一条奖惩。"""
        stmt = (
            select(RiderSalaryAdjustment)
            .where(*_adjustment_filters(period))
            .order_by(RiderSalaryAdjustment.biz_date.asc(), RiderSalaryAdjustment.id.asc())
        )
        async for item in stream_scalars(db, stmt):
            rider = riders.get(item.rider_id)
            subject = subjects.get(item.subject_id)
            values = [
                rider.job_no if rider is not None else str(item.rider_id),
                rider.name if rider is not None else '',
                item.biz_date.isoformat() if item.biz_date else '',
                subject.name if subject is not None else str(item.subject_id),
                _excel_number(item.amount),
                _excel_number(item.signed_amount if item.signed_amount is not None else item.amount),
                item.remark or '',
                _yes_no(flag=bool(item.is_locked)),
            ]
            db.expunge(item)
            yield values


export_service = ExportService()
