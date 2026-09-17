from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.payroll_daily import payroll_daily_dao
from backend.plugin.rider_salary.crud.payroll_detail import payroll_detail_dao
from backend.plugin.rider_salary.enums import (
    AdvanceStatus,
    CalcStage,
    DeductStatus,
    DetailSource,
    PayrollKind,
    PayrollStatus,
)
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.payroll import (
    AdvanceLineItem,
    GetPayrollDailyDetail,
    GetPayrollDetailItem,
    GetPayrollGroupedDetail,
    GetPayrollSummary,
    PlanVersionLabel,
    SubjectBreakdownItem,
)
from backend.plugin.rider_salary.utils.audit import audit_service
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

ADVANCE_SUBJECT_ID = 0
ZERO = Decimal('0.00')


def extract_advance_id(trace: dict[str, Any] | None) -> int | None:
    """从 calc_trace 提升预支单 ID"""
    if not isinstance(trace, dict):
        return None
    raw = trace.get('advance_id')
    if raw is None and isinstance(trace.get('变量'), dict):
        raw = trace['变量'].get('预支单ID')
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def extract_adjustment_id(trace: dict[str, Any] | None) -> int | None:
    """从 calc_trace 提升奖惩单 ID（若有）"""
    if not isinstance(trace, dict):
        return None
    raw = trace.get('adjustment_id')
    if raw is None and isinstance(trace.get('变量'), dict):
        raw = trace['变量'].get('奖惩单ID') or trace['变量'].get('adjustment_id')
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def build_subject_breakdown(
    items: list[GetPayrollDetailItem],
) -> list[SubjectBreakdownItem]:
    """按科目聚合明细；勾稽用进应发行之和对齐 gross"""
    buckets: dict[tuple[int | None, bool | None], dict[str, Any]] = {}
    for item in items:
        sid = item.subject_id if item.subject_id is not None else ADVANCE_SUBJECT_ID
        if item.source == DetailSource.advance.value:
            sid = ADVANCE_SUBJECT_ID
        key = (sid, item.include_in_gross)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                'subject_id': sid,
                'subject_code': item.subject_code,
                'subject_name': item.subject_name
                or ('预支抵扣' if item.source == DetailSource.advance.value else item.name),
                'direction': None,
                'include_in_gross': item.include_in_gross,
                'line_count': 0,
                'amount_sum': ZERO,
                'sources': set(),
            }
            buckets[key] = bucket
        bucket['line_count'] += 1
        bucket['amount_sum'] = q2(bucket['amount_sum'] + (item.amount or ZERO))
        if item.source:
            bucket['sources'].add(item.source)
        if item.subject_code and not bucket['subject_code']:
            bucket['subject_code'] = item.subject_code
        if item.subject_name and not bucket['subject_name']:
            bucket['subject_name'] = item.subject_name
    result: list[SubjectBreakdownItem] = [
        SubjectBreakdownItem(
            subject_id=bucket['subject_id'],
            subject_code=bucket['subject_code'],
            subject_name=bucket['subject_name'],
            direction=bucket['direction'],
            include_in_gross=bucket['include_in_gross'],
            line_count=bucket['line_count'],
            amount_sum=q2(bucket['amount_sum']),
            sources=sorted(bucket['sources']),
        )
        for bucket in buckets.values()
    ]
    result.sort(key=lambda row: (row.subject_id or 0, row.subject_name or ''))
    return result


def build_advance_lines(items: list[GetPayrollDetailItem]) -> list[AdvanceLineItem]:
    """从明细提取预支抵扣行"""
    lines: list[AdvanceLineItem] = []
    for item in items:
        if item.source != DetailSource.advance.value:
            continue
        advance_id = item.advance_id or extract_advance_id(item.calc_trace) or 0
        remaining = None
        deduct_status = None
        trace = item.calc_trace or {}
        if isinstance(trace.get('变量'), dict):
            rem = trace['变量'].get('剩余') or trace['变量'].get('remaining_after')
            if rem is not None:
                try:
                    remaining = q2(Decimal(str(rem)))
                except Exception:
                    remaining = None
        if 'deduct_status' in trace:
            deduct_status = str(trace.get('deduct_status'))
        lines.append(
            AdvanceLineItem(
                advance_id=int(advance_id),
                amount=q2(abs(item.amount or ZERO)),
                remaining_after=remaining,
                deduct_status=deduct_status,
                calc_trace=item.calc_trace,
            )
        )
    return lines


def gross_from_breakdown(breakdown: list[SubjectBreakdownItem]) -> Decimal:
    """进应发科目合计（用于勾稽）"""
    total = ZERO
    for row in breakdown:
        if row.include_in_gross and row.subject_id != ADVANCE_SUBJECT_ID:
            if DetailSource.advance.value in (row.sources or []):
                continue
            total = q2(total + (row.amount_sum or ZERO))
    return total


@dataclass
class AdvanceLine:
    """预支抵扣行"""

    advance_id: int
    amount: Decimal
    remaining_after: Decimal
    deducted_after: Decimal
    deduct_status: str
    calc_trace: dict[str, Any] = field(default_factory=dict)


def _deduct_status(remaining: Decimal, amount: Decimal) -> str:
    if remaining <= 0:
        return DeductStatus.done.value
    if remaining < amount:
        return DeductStatus.partial.value
    return DeductStatus.none.value


def apply_advance_restore(advance: Any, restored: Decimal) -> None:
    """把一笔预支抵扣加回 remaining，并回退 deduct_status（draft 重算 / 反冲共用）"""
    restored_amt = q2(abs(restored))
    remaining = q2((getattr(advance, 'remaining_amount', ZERO) or ZERO) + restored_amt)
    deducted = q2(max((getattr(advance, 'deducted_amount', ZERO) or ZERO) - restored_amt, ZERO))
    total = q2(getattr(advance, 'amount', ZERO) or ZERO)
    if remaining > total:
        remaining = total
    advance.remaining_amount = remaining
    advance.deducted_amount = deducted
    advance.deduct_status = _deduct_status(remaining, total)


def compute_advance_deduction(
    advances: list[Any],
    cap: Decimal,
    *,
    persist: bool,
) -> tuple[Decimal, list[AdvanceLine]]:
    """
    按 paid_time 先后抵扣。persist=False 时不修改 remaining，只返回可抵扣参考额（调用方决定是否写入明细）。
    """
    budget = q2(max(cap, ZERO))
    if budget <= 0:
        return ZERO, []
    ordered = sorted(
        [item for item in advances if q2(getattr(item, 'remaining_amount', ZERO) or ZERO) > 0],
        key=lambda item: getattr(item, 'paid_time', None) or datetime.min.replace(tzinfo=timezone.tz_info),
    )
    total = ZERO
    lines: list[AdvanceLine] = []
    remaining_budget = budget
    for item in ordered:
        if remaining_budget <= 0:
            break
        remaining = q2(getattr(item, 'remaining_amount', ZERO) or ZERO)
        if remaining <= 0:
            continue
        deduct = q2(min(remaining, remaining_budget))
        if deduct <= 0:
            continue
        total += deduct
        remaining_budget -= deduct
        new_remaining = q2(remaining - deduct)
        new_deducted = q2((getattr(item, 'deducted_amount', ZERO) or ZERO) + deduct)
        status = _deduct_status(new_remaining, q2(getattr(item, 'amount', ZERO) or ZERO))
        if persist:
            item.remaining_amount = new_remaining
            item.deducted_amount = new_deducted
            item.deduct_status = status
        lines.append(
            AdvanceLine(
                advance_id=int(getattr(item, 'id', 0) or 0),
                amount=deduct,
                remaining_after=new_remaining,
                deducted_after=new_deducted,
                deduct_status=status,
                calc_trace={
                    '条件': 'True',
                    '条件结果': True,
                    '公式': '预支抵扣',
                    '变量': {'预支单ID': getattr(item, 'id', 0), '抵扣': float(deduct)},
                    '结果': float(deduct),
                    'advance_id': getattr(item, 'id', 0),
                },
            )
        )
    return q2(total), lines


class PayrollService:
    """薪资单领域服务：预支抵扣、反冲"""

    @staticmethod
    async def load_paid_advances(db: AsyncSession, rider_id: int) -> list[RiderSalaryAdvance]:
        """已发放且仍有待抵扣的预支单"""
        rows = await db.scalars(
            select(RiderSalaryAdvance)
            .where(
                RiderSalaryAdvance.rider_id == rider_id,
                RiderSalaryAdvance.status == AdvanceStatus.paid.value,
                RiderSalaryAdvance.deleted == 0,
            )
            .order_by(RiderSalaryAdvance.paid_time.asc(), RiderSalaryAdvance.id.asc())
        )
        return [row for row in rows.all() if q2(row.remaining_amount or ZERO) > 0]

    async def apply_advance_deduction(
        self,
        db: AsyncSession,
        *,
        rider_id: int,
        cap: Decimal,
        persist: bool,
    ) -> tuple[Decimal, list[AdvanceLine]]:
        """
        按 paid 且 remaining>0 的预支单抵扣。persist=False 只计算参考值。
        """
        advances = await self.load_paid_advances(db, rider_id)
        return compute_advance_deduction(advances, cap, persist=persist)

    async def create_reversal(
        self,
        db: AsyncSession,
        payroll: RiderSalaryPayroll,
        operator: Request | None,
        reason: str,
    ) -> RiderSalaryPayroll:
        """
        生成反冲单：明细取负、kind=reversal、status=finalized；回滚预支抵扣。
        rs_payroll_daily 不变。
        """
        if payroll.kind == PayrollKind.reversal.value:
            raise errors.RequestError(msg='反冲单不能再次反冲')
        if payroll.reversed:
            raise errors.RequestError(msg='该薪资单已被反冲')
        if payroll.status not in {PayrollStatus.finalized.value, PayrollStatus.paid.value}:
            raise errors.RequestError(msg='仅已定稿或已发薪的薪资单可反冲')

        details = await payroll_detail_dao.list_by_payroll(db, payroll.id)
        reversal = RiderSalaryPayroll(
            period_id=payroll.period_id,
            rider_id=payroll.rider_id,
            kind=PayrollKind.reversal.value,
            status=PayrollStatus.finalized.value,
            calc_version=payroll.calc_version,
            stale=False,
            reversed=False,
            warnings=list(payroll.warnings or []),
            order_count=payroll.order_count,
            valid_order_count=payroll.valid_order_count,
            per_order_total=q2(-payroll.per_order_total),
            daily_total=q2(-payroll.daily_total),
            period_total=q2(-payroll.period_total),
            bonus_total=q2(-payroll.bonus_total),
            penalty_total=q2(-payroll.penalty_total),
            gross=q2(-payroll.gross),
            deduction_total=q2(-payroll.deduction_total),
            advance_deduction=q2(-payroll.advance_deduction),
            net=q2(-payroll.net),
            plan_version_ids=list(payroll.plan_version_ids or []),
            reversed_of_id=payroll.id,
            calc_time=timezone.now(),
            calc_by=int(getattr(getattr(operator, 'user', None), 'id', 0) or 0) if operator else None,
        )
        db.add(reversal)
        await db.flush()

        for detail in details:
            db.add(
                RiderSalaryPayrollDetail(
                    payroll_id=reversal.id,
                    rider_id=detail.rider_id,
                    subject_id=detail.subject_id,
                    amount=q2(-detail.amount),
                    stage=detail.stage,
                    include_in_gross=detail.include_in_gross,
                    source=DetailSource.reversal.value,
                    biz_date=detail.biz_date,
                    plan_version_id=detail.plan_version_id,
                    plan_item_id=detail.plan_item_id,
                    order_id=detail.order_id,
                    calc_trace=detail.calc_trace,
                )
            )
            if detail.source == DetailSource.advance.value:
                await self._restore_advance(db, detail)

        payroll.reversed = True
        await db.flush()
        if operator is not None:
            await audit_service.record(
                db,
                operator,
                module='薪资结果',
                action='反冲补发',
                target_type='payroll',
                target_id=payroll.id,
                target_label=f'薪资单{payroll.id}',
                reason=reason,
            )
        return reversal

    @staticmethod
    async def _restore_advance(db: AsyncSession, detail: RiderSalaryPayrollDetail) -> None:
        """反冲预支抵扣：remaining 加回，deduct_status 回退"""
        trace = detail.calc_trace or {}
        advance_id = trace.get('advance_id')
        if not advance_id:
            return
        advance = await db.scalar(
            select(RiderSalaryAdvance).where(
                RiderSalaryAdvance.id == int(advance_id),
                RiderSalaryAdvance.deleted == 0,
            )
        )
        if advance is None:
            return
        apply_advance_restore(advance, q2(abs(detail.amount)))

    async def restore_advances_from_payroll(self, db: AsyncSession, payroll: RiderSalaryPayroll) -> None:
        """draft 重算前：按旧预支明细把 remaining 加回，供本次重新抵扣"""
        details = await payroll_detail_dao.list_by_payroll(db, payroll.id)
        for detail in details:
            if detail.source == DetailSource.advance.value:
                await self._restore_advance(db, detail)

    @staticmethod
    async def get(db: AsyncSession, pk: int) -> RiderSalaryPayroll:
        """获取薪资单"""
        payroll = await payroll_dao.get(db, pk)
        if payroll is None:
            raise errors.NotFoundError(msg='薪资单不存在')
        return payroll

    async def assert_visible(self, db: AsyncSession, request: Request, payroll: RiderSalaryPayroll) -> None:
        """校验可见站点"""
        period = await db.scalar(
            select(RiderSalarySettlePeriod).where(
                RiderSalarySettlePeriod.id == payroll.period_id,
                RiderSalarySettlePeriod.deleted == 0,
            )
        )
        if period is None:
            return
        site_ids = await get_visible_site_ids(request, db)
        assert_site_visible(site_ids, period.site_id)

    async def get_list(
        self,
        db: AsyncSession,
        request: Request,
        *,
        period_id: int | None,
        rider_id: int | None,
        site_id: int | None,
        kind: str | None,
        status: str | None,
        stale: bool | None,
    ) -> dict[str, Any]:
        """分页薪资单（含站点/周期/骑手摘要）"""
        visible = await get_visible_site_ids(request, db)
        stmt = await payroll_dao.get_select(
            period_id,
            rider_id,
            site_id,
            kind,
            status,
            stale=stale,
            site_ids=visible,
        )
        page = await paging_data(db, stmt)
        items = page.get('items') or []
        if not items:
            return page
        payroll_ids = [int(getattr(item, 'id', item.get('id') if isinstance(item, dict) else 0) or 0) for item in items]
        payroll_ids = [pk for pk in payroll_ids if pk]
        rows = await db.scalars(
            select(RiderSalaryPayroll).where(RiderSalaryPayroll.id.in_(payroll_ids), RiderSalaryPayroll.deleted == 0)
        )
        payroll_map = {row.id: row for row in rows.all()}
        ordered = [payroll_map[pk] for pk in payroll_ids if pk in payroll_map]
        ctx = await self._context_maps(db, ordered)
        page['items'] = [self._to_summary(row, ctx) for row in ordered]
        return page

    async def get_grouped(self, db: AsyncSession, request: Request, pk: int) -> GetPayrollGroupedDetail:
        """汇总 + 明细按阶段分组 + 日汇总 + 科目拆解"""
        payroll = await self.get(db, pk)
        await self.assert_visible(db, request, payroll)
        details = await payroll_detail_dao.list_by_payroll(db, pk)
        lookups = await self._detail_lookups(db, details)
        detail_items = [self._to_detail_item(row, lookups) for row in details]
        grouped: dict[str, list[GetPayrollDetailItem]] = {
            CalcStage.per_order.value: [],
            CalcStage.daily.value: [],
            CalcStage.period.value: [],
        }
        for item in detail_items:
            grouped.setdefault(item.stage, []).append(item)
        ctx = await self._context_maps(db, [payroll])
        period = ctx['periods'].get(payroll.period_id)
        dailies: list[GetPayrollDailyDetail] = []
        if period is not None:
            rows = await payroll_daily_dao.list_by_rider_range(
                db,
                payroll.rider_id,
                period.start_date,
                period.end_date,
            )
            dailies = [GetPayrollDailyDetail.model_validate(row) for row in rows]
        summary = self._to_summary(payroll, ctx)
        data = GetPayrollGroupedDetail.model_validate(summary.model_dump())
        data.details = grouped
        data.dailies = dailies
        data.subject_breakdown = build_subject_breakdown(detail_items)
        data.advance_lines = build_advance_lines(detail_items)
        data.plan_version_labels = self._plan_version_labels(payroll.plan_version_ids or [], lookups)
        # 回填科目方向（来自科目表）
        for row in data.subject_breakdown:
            subject = lookups['subjects'].get(row.subject_id or 0)
            if subject is not None:
                row.direction = subject.direction
                if not row.subject_code:
                    row.subject_code = subject.code
                if not row.subject_name:
                    row.subject_name = subject.name
                if row.include_in_gross is None:
                    row.include_in_gross = subject.include_in_gross
        return data

    async def get_details_page(
        self,
        db: AsyncSession,
        request: Request,
        pk: int,
        *,
        biz_date: str | None,
        stage: str | None,
        subject_id: int | None,
        order_id: int | None,
    ) -> dict[str, Any]:
        """分页明细"""
        payroll = await self.get(db, pk)
        await self.assert_visible(db, request, payroll)
        stmt = await payroll_detail_dao.get_select(pk, biz_date, stage, subject_id, order_id)
        page = await paging_data(db, stmt)
        items = page.get('items') or []
        if not items:
            return page
        detail_ids = [int(getattr(item, 'id', item.get('id') if isinstance(item, dict) else 0) or 0) for item in items]
        detail_ids = [did for did in detail_ids if did]
        rows = await db.scalars(
            select(RiderSalaryPayrollDetail).where(
                RiderSalaryPayrollDetail.id.in_(detail_ids),
                RiderSalaryPayrollDetail.deleted == 0,
            )
        )
        detail_map = {row.id: row for row in rows.all()}
        ordered = [detail_map[did] for did in detail_ids if did in detail_map]
        lookups = await self._detail_lookups(db, ordered)
        page['items'] = [self._to_detail_item(row, lookups) for row in ordered]
        return page

    @staticmethod
    def _to_summary(payroll: RiderSalaryPayroll, ctx: dict[str, Any]) -> GetPayrollSummary:
        data = GetPayrollSummary.model_validate(payroll)
        period = ctx['periods'].get(payroll.period_id)
        rider = ctx['riders'].get(payroll.rider_id)
        site = None
        if period is not None:
            site = ctx['sites'].get(period.site_id)
            data.site_id = period.site_id
            data.period_start = period.start_date
            data.period_end = period.end_date
            data.cycle_type = period.cycle_type
            data.period_status = period.status
        if site is not None:
            data.site_name = site.name
        if rider is not None:
            data.rider_job_no = rider.job_no
            data.job_no = rider.job_no
            data.rider_name = rider.name
        return data

    @staticmethod
    def _to_detail_item(row: RiderSalaryPayrollDetail, lookups: dict[str, Any]) -> GetPayrollDetailItem:
        item = GetPayrollDetailItem.model_validate(row)
        subject = lookups['subjects'].get(row.subject_id)
        if subject is not None:
            item.subject_name = subject.name
            item.subject_code = subject.code
        plan_item = lookups['plan_items'].get(row.plan_item_id) if row.plan_item_id else None
        if plan_item is not None:
            item.name = plan_item.name
            item.plan_item_name = plan_item.name
        elif item.name:
            item.plan_item_name = item.name
        if row.order_id:
            item.order_no = lookups['order_nos'].get(row.order_id)
        if row.plan_version_id:
            item.plan_version_name = lookups['plan_names'].get(row.plan_version_id)
        item.advance_id = extract_advance_id(row.calc_trace)
        item.adjustment_id = extract_adjustment_id(row.calc_trace)
        if item.source == DetailSource.advance.value and not item.subject_name:
            item.subject_name = '预支抵扣'
            item.subject_code = item.subject_code or 'ADVANCE'
        return item

    @staticmethod
    def _plan_version_labels(version_ids: list[int], lookups: dict[str, Any]) -> list[PlanVersionLabel]:
        labels: list[PlanVersionLabel] = [
            PlanVersionLabel(
                id=vid,
                name=lookups['plan_names'].get(vid),
                code=lookups['plan_codes'].get(vid),
            )
            for vid in version_ids
        ]
        return labels

    async def _context_maps(self, db: AsyncSession, payrolls: list[RiderSalaryPayroll]) -> dict[str, Any]:
        period_ids = {row.period_id for row in payrolls if row.period_id}
        rider_ids = {row.rider_id for row in payrolls if row.rider_id}
        periods: dict[int, RiderSalarySettlePeriod] = {}
        if period_ids:
            rows = await db.scalars(
                select(RiderSalarySettlePeriod).where(
                    RiderSalarySettlePeriod.id.in_(list(period_ids)),
                    RiderSalarySettlePeriod.deleted == 0,
                )
            )
            periods = {row.id: row for row in rows.all()}
        riders: dict[int, RiderSalaryRider] = {}
        if rider_ids:
            rows = await db.scalars(
                select(RiderSalaryRider).where(
                    RiderSalaryRider.id.in_(list(rider_ids)),
                    RiderSalaryRider.deleted == 0,
                )
            )
            riders = {row.id: row for row in rows.all()}
        site_ids = {row.site_id for row in periods.values()}
        sites: dict[int, RiderSalarySite] = {}
        if site_ids:
            rows = await db.scalars(
                select(RiderSalarySite).where(
                    RiderSalarySite.id.in_(list(site_ids)),
                    RiderSalarySite.deleted == 0,
                )
            )
            sites = {row.id: row for row in rows.all()}
        return {'periods': periods, 'riders': riders, 'sites': sites}

    async def _detail_lookups(self, db: AsyncSession, details: list[RiderSalaryPayrollDetail]) -> dict[str, Any]:
        subject_ids = {row.subject_id for row in details if row.subject_id}
        order_ids = {row.order_id for row in details if row.order_id}
        plan_item_ids = {row.plan_item_id for row in details if row.plan_item_id}
        version_ids = {row.plan_version_id for row in details if row.plan_version_id}
        subjects: dict[int, RiderSalarySubject] = {}
        if subject_ids:
            rows = await db.scalars(select(RiderSalarySubject).where(RiderSalarySubject.id.in_(list(subject_ids))))
            subjects = {row.id: row for row in rows.all()}
        order_nos: dict[int, str] = {}
        if order_ids:
            rows = await db.scalars(select(RiderSalaryOrder).where(RiderSalaryOrder.id.in_(list(order_ids))))
            order_nos = {row.id: row.order_no for row in rows.all()}
        plan_items: dict[int, RiderSalaryPlanItem] = {}
        if plan_item_ids:
            rows = await db.scalars(select(RiderSalaryPlanItem).where(RiderSalaryPlanItem.id.in_(list(plan_item_ids))))
            plan_items = {row.id: row for row in rows.all()}
        plan_names: dict[int, str] = {}
        plan_codes: dict[int, str | None] = {}
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
                plan_codes[version.id] = plan.code if plan is not None else None
        return {
            'subjects': subjects,
            'order_nos': order_nos,
            'plan_items': plan_items,
            'plan_names': plan_names,
            'plan_codes': plan_codes,
        }


payroll_service = PayrollService()
