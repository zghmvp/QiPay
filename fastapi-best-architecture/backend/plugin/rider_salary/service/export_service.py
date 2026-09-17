from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.enums import CalcStage, DetailSource, OrderStatus, PayrollKind, PayrollStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.service.audit_service import audit_service
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.utils.audit import resolve_operator_name
from backend.plugin.rider_salary.utils.excel import write_workbook
from backend.plugin.rider_salary.utils.export_adjustment import (
    AdjustmentSheetStats,
    attention_rider_day_keys,
    classify_adjustments,
    list_period_window_adjustments,
    manual_detail_keys,
    sheet_stats,
)
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.order_attention import (
    attention_confession,
    attention_duration_minutes,
    attention_reason,
    keep_export_detail_row,
    list_period_attention_orders,
)
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
    '入账状态',
    '需关注同日同骑手',
    '奖惩说明',
]
NET_HEADERS = ['工号', '姓名', '原单', '反冲', '补发', '净差']

SHEET_SUMMARY = '薪资汇总'
SHEET_DETAIL = '薪资明细'
SHEET_ADJUSTMENT = '奖惩记录'
SHEET_NET = '净额对照'
SHEET_ATTENTION = '需关注说明'
ATTENTION_HEADERS = ['工号', '姓名', '订单号', '状态', '时长(分钟)', '需关注原因', '说明']

ZERO = Decimal('0.00')


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


@dataclass(frozen=True, slots=True)
class ExportPeriodFile:
    """周期导出文件（汇总金额不因排除改变）。"""

    content: bytes
    filename: str
    attention_count: int
    exclude_attention: bool
    booked_adjustment_count: int
    unbooked_adjustment_count: int
    attention_adjustment_count: int
    excluded_adjustment_count: int
    exclude_attention_adjustments: bool


class ExportService:
    """薪资导出服务"""

    async def export_period(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        exclude_attention: bool = False,
        exclude_attention_adjustments: bool = False,
    ) -> ExportPeriodFile:
        """
        导出周期薪资 xlsx

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 周期 ID
        :param exclude_attention: 是否从文件行排除需关注订单（不改 gross/net）
        :param exclude_attention_adjustments: 奖惩是否同步去掉需关注同日同骑手（默认关）
        :return: 导出文件与对账计数
        """
        period, site, _rider = await period_service._load_visible(db, request, pk)
        payrolls = list(await payroll_dao.select_models_order(db, 'id', 'asc', period_id=period.id, deleted=0))
        riders = await period_service._rider_map(db, [row.rider_id for row in payrolls])
        site_name = site.name if site is not None else str(period.site_id)
        period_text = f'{period.start_date}~{period.end_date}'
        details = await self._list_details(db, [row.id for row in payrolls])
        attention_orders = await list_period_attention_orders(db, period)
        attention_ids = {int(row.id) for row in attention_orders}
        attention_count = len(attention_orders)
        riders.update(await period_service._rider_map(db, [row.rider_id for row in attention_orders]))
        plan_names, subject_names, order_nos = await self._lookup_maps(db, details)
        details_by_payroll: dict[int, list[RiderSalaryPayrollDetail]] = {}
        for detail in details:
            details_by_payroll.setdefault(detail.payroll_id, []).append(detail)
        summary_rows: list[list] = []
        detail_rows: list[list] = []
        net_acc: dict[int, dict[str, Any]] = {}
        ordered_rider_ids: list[int] = []
        for payroll in payrolls:
            rider = riders.get(payroll.rider_id)
            job_no = rider.job_no if rider is not None else str(payroll.rider_id)
            name = rider.name if rider is not None else ''
            summary_rows.append([
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
            ])
            if payroll.rider_id not in net_acc:
                ordered_rider_ids.append(payroll.rider_id)
                net_acc[payroll.rider_id] = {
                    'job_no': job_no,
                    'name': name,
                    'normal': ZERO,
                    'reversal': ZERO,
                    'supplement': ZERO,
                }
            if payroll.kind in net_acc[payroll.rider_id]:
                net_acc[payroll.rider_id][payroll.kind] = q2(net_acc[payroll.rider_id][payroll.kind] + q2(payroll.net))
            detail_rows.extend(
                [
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
                for detail in details_by_payroll.get(payroll.id, [])
                if keep_export_detail_row(
                    exclude_attention=exclude_attention,
                    order_id=detail.order_id,
                    attention_ids=attention_ids,
                )
            )
        adj_rows, adj_stats = await self._adjustment_rows(
            db,
            period,
            riders,
            details=details,
            attention_orders=attention_orders,
            exclude_attention_adjustments=exclude_attention_adjustments,
        )
        net_rows = self._net_rows(net_acc, riders, ordered_rider_ids)
        sheets: list[tuple[str, list[str], list[list]]] = [
            (SHEET_SUMMARY, SUMMARY_HEADERS, summary_rows),
            (SHEET_DETAIL, DETAIL_HEADERS, detail_rows),
            (SHEET_ADJUSTMENT, ADJUSTMENT_HEADERS, adj_rows),
            (SHEET_NET, NET_HEADERS, net_rows),
        ]
        notice_rows = self._attention_notice_rows(
            orders=attention_orders,
            riders=riders,
            excluded=exclude_attention,
        )
        if notice_rows:
            sheets.append((SHEET_ATTENTION, ATTENTION_HEADERS, notice_rows))
        content = write_workbook(sheets)
        filename = f'薪资导出_{site_name}_{period.start_date}_{period.end_date}.xlsx'
        confession = attention_confession(count=attention_count, excluded=exclude_attention)
        audit_extra = f'，{confession}' if confession else ''
        if exclude_attention_adjustments and adj_stats.excluded_count:
            audit_extra += f'，奖惩同步去掉 {adj_stats.excluded_count} 条'
        await audit_service.record(
            db,
            request,
            module='结算周期',
            action='导出',
            target_type='period',
            target_id=period.id,
            target_label=f'{site_name} {period_text}',
            description=(
                f'{resolve_operator_name(request)} 于 {timezone.to_str(timezone.now())} '
                f'对 周期{site_name} {period_text} 执行了导出{audit_extra}'
            ),
        )
        return ExportPeriodFile(
            content=content,
            filename=filename,
            attention_count=attention_count,
            exclude_attention=exclude_attention,
            booked_adjustment_count=adj_stats.booked_count,
            unbooked_adjustment_count=adj_stats.unbooked_count,
            attention_adjustment_count=adj_stats.attention_count,
            excluded_adjustment_count=adj_stats.excluded_count,
            exclude_attention_adjustments=exclude_attention_adjustments,
        )

    @staticmethod
    def _attention_notice_rows(
        *,
        orders: list[RiderSalaryOrder],
        riders: dict[int, RiderSalaryRider],
        excluded: bool,
    ) -> list[list]:
        count = len(orders)
        confession = attention_confession(count=count, excluded=excluded)
        if not confession:
            return []
        if excluded:
            return [['', '', '', '', '', '', confession]]
        rows: list[list] = []
        for order in orders:
            rider = riders.get(order.rider_id)
            reason = attention_reason(
                status=order.status,
                order_time=order.order_time,
                deliver_time=order.deliver_time,
            )
            rows.append([
                rider.job_no if rider is not None else str(order.rider_id),
                rider.name if rider is not None else '',
                order.order_no,
                _label(OrderStatus, order.status),
                attention_duration_minutes(order),
                reason or '',
                confession,
            ])
        return rows

    @staticmethod
    async def _list_details(db: AsyncSession, payroll_ids: list[int]) -> list[RiderSalaryPayrollDetail]:
        if not payroll_ids:
            return []
        rows = await db.scalars(
            select(RiderSalaryPayrollDetail)
            .where(
                RiderSalaryPayrollDetail.payroll_id.in_(payroll_ids),
                RiderSalaryPayrollDetail.deleted == 0,
            )
            .order_by(RiderSalaryPayrollDetail.id.asc())
        )
        return list(rows.all())

    async def _lookup_maps(
        self,
        db: AsyncSession,
        details: list[RiderSalaryPayrollDetail],
    ) -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
        version_ids = {row.plan_version_id for row in details if row.plan_version_id}
        subject_ids = {row.subject_id for row in details if row.subject_id}
        order_ids = {row.order_id for row in details if row.order_id}
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
        order_nos: dict[int, str] = {}
        if order_ids:
            rows = await db.scalars(select(RiderSalaryOrder).where(RiderSalaryOrder.id.in_(list(order_ids))))
            order_nos = {row.id: row.order_no for row in rows.all()}
        return plan_names, subject_names, order_nos

    async def _adjustment_rows(
        self,
        db: AsyncSession,
        period: RiderSalarySettlePeriod,
        payroll_riders: dict[int, RiderSalaryRider],
        *,
        details: list[RiderSalaryPayrollDetail],
        attention_orders: list[RiderSalaryOrder],
        exclude_attention_adjustments: bool,
    ) -> tuple[list[list], AdjustmentSheetStats]:
        adjustments = await list_period_window_adjustments(db, period)
        rider_ids = list({row.rider_id for row in adjustments} | set(payroll_riders))
        riders = dict(payroll_riders)
        riders.update(await period_service._rider_map(db, rider_ids))
        subject_ids = {row.subject_id for row in adjustments}
        subjects: dict[int, RiderSalarySubject] = {}
        if subject_ids:
            rows = await db.scalars(select(RiderSalarySubject).where(RiderSalarySubject.id.in_(list(subject_ids))))
            subjects = {row.id: row for row in rows.all()}
        classified = classify_adjustments(
            adjustments,
            period_id=int(period.id),
            manual_keys=manual_detail_keys(details),
            attention_keys=attention_rider_day_keys(attention_orders),
            exclude_attention_adjustments=exclude_attention_adjustments,
        )
        stats = sheet_stats(classified)
        rows_out: list[list] = []
        for item in classified:
            if item.dropped:
                continue
            adj = item.adjustment
            rider = riders.get(adj.rider_id)
            subject = subjects.get(adj.subject_id)
            rows_out.append([
                rider.job_no if rider is not None else str(adj.rider_id),
                rider.name if rider is not None else '',
                adj.biz_date.isoformat() if adj.biz_date else '',
                subject.name if subject is not None else str(adj.subject_id),
                _excel_number(adj.amount),
                _excel_number(adj.signed_amount if adj.signed_amount is not None else adj.amount),
                adj.remark or '',
                _yes_no(flag=bool(adj.is_locked)),
                item.booked_label,
                _yes_no(flag=item.attention_same_day),
                item.attention_note,
            ])
        return rows_out, stats

    @staticmethod
    def _net_rows(
        net_acc: dict[int, dict[str, Any]],
        riders: dict[int, RiderSalaryRider],
        ordered_ids: list[int],
    ) -> list[list]:
        rows: list[list] = []
        for rider_id in ordered_ids:
            bucket = net_acc.get(rider_id)
            if bucket is None:
                continue
            rider = riders.get(rider_id)
            original = q2(bucket.get('normal') or ZERO)
            reversal = q2(bucket.get('reversal') or ZERO)
            supplement = q2(bucket.get('supplement') or ZERO)
            rows.append([
                rider.job_no if rider is not None else bucket.get('job_no'),
                rider.name if rider is not None else bucket.get('name'),
                _excel_number(original),
                _excel_number(reversal),
                _excel_number(supplement),
                _excel_number(q2(original + reversal + supplement)),
            ])
        return rows


export_service = ExportService()
