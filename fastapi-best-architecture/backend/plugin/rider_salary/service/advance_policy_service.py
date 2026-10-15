from dataclasses import asdict
from decimal import Decimal

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.advance import advance_dao
from backend.plugin.rider_salary.crud.advance_policy import advance_policy_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.enums import AdvanceStatus, PayrollStatus, RiderStatus
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.advance_policy import GLOBAL_POLICY_SITE_ID, RiderSalaryAdvancePolicy
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.schema.advance import GetAdvancePolicy, SaveAdvancePolicyParam
from backend.plugin.rider_salary.service.advance_quote import AdvanceQuote, AdvanceRule, builtin_rule, quote_advance
from backend.plugin.rider_salary.service.audit_service import audit_service, is_global_operator
from backend.plugin.rider_salary.service.calc_service import calculate_rider_period
from backend.plugin.rider_salary.service.calendar_service import (
    period_range_text,
    pick_effective_payroll,
    resolve_period,
)
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

_STORED = {PayrollStatus.draft.value, PayrollStatus.finalized.value, PayrollStatus.paid.value}
_POLICY_FIELDS = (
    'amount_mode',
    'percent',
    'fixed_amount',
    'max_amount',
    'monthly_max_count',
    'min_tenure_days',
    'min_completed_orders',
    'min_amount',
)


def rule_from_row(row: RiderSalaryAdvancePolicy) -> AdvanceRule:
    """把已保存规则转成试算对象。"""
    return AdvanceRule(
        amount_mode=row.amount_mode,
        percent=q2(row.percent),
        fixed_amount=q2(row.fixed_amount),
        max_amount=q2(row.max_amount) if row.max_amount is not None else None,
        monthly_max_count=row.monthly_max_count,
        min_tenure_days=row.min_tenure_days,
        min_completed_orders=row.min_completed_orders,
        min_amount=q2(row.min_amount),
    )


def _policy_snapshot(row: RiderSalaryAdvancePolicy) -> dict[str, str | int | bool | None]:
    data: dict[str, str | int | bool | None] = {'site_id': row.site_id}
    for name in _POLICY_FIELDS:
        value = getattr(row, name)
        data[name] = str(value) if isinstance(value, Decimal) else value
    return data


class AdvancePolicyService:
    """预支规则的读取、保存和额度试算。"""

    async def resolve_rule(self, db: AsyncSession, site_id: int) -> tuple[AdvanceRule, str, int]:
        """站点规则优先，否则全局，否则系统默认。返回规则、来源、来源站点。"""
        if site_id == GLOBAL_POLICY_SITE_ID:
            global_row = await advance_policy_dao.get_by_site(db, GLOBAL_POLICY_SITE_ID)
            if global_row is not None:
                return rule_from_row(global_row), 'global', GLOBAL_POLICY_SITE_ID
            return builtin_rule(), 'builtin', GLOBAL_POLICY_SITE_ID
        site_row = await advance_policy_dao.get_by_site(db, site_id)
        if site_row is not None:
            return rule_from_row(site_row), 'site', site_id
        global_row = await advance_policy_dao.get_by_site(db, GLOBAL_POLICY_SITE_ID)
        if global_row is not None:
            return rule_from_row(global_row), 'global', GLOBAL_POLICY_SITE_ID
        return builtin_rule(), 'builtin', GLOBAL_POLICY_SITE_ID

    async def get(self, *, db: AsyncSession, request: Request, site_id: int) -> GetAdvancePolicy:
        """读取某站点或全局的生效规则。"""
        await self._assert_scope(db, request, site_id)
        rule, source, _owner = await self.resolve_rule(db, site_id)
        site_name = '全局默认'
        if site_id != GLOBAL_POLICY_SITE_ID:
            site = await site_dao.get(db, site_id)
            if site is None:
                raise errors.NotFoundError(msg='站点不存在')
            site_name = site.name
        return GetAdvancePolicy(
            site_id=site_id,
            amount_mode=rule.amount_mode if rule.amount_mode in {'percent', 'fixed'} else 'percent',
            percent=rule.percent,
            fixed_amount=rule.fixed_amount,
            max_amount=rule.max_amount,
            monthly_max_count=rule.monthly_max_count,
            min_tenure_days=rule.min_tenure_days,
            min_completed_orders=rule.min_completed_orders,
            min_amount=rule.min_amount,
            source=source,  # type: ignore[arg-type]
            site_name=site_name,
        )

    async def save(
        self,
        *,
        db: AsyncSession,
        request: Request,
        obj: SaveAdvancePolicyParam,
    ) -> GetAdvancePolicy:
        """保存站点或全局预支规则。"""
        await self._assert_scope(db, request, obj.site_id)
        if obj.site_id != GLOBAL_POLICY_SITE_ID:
            site = await site_dao.get(db, obj.site_id)
            if site is None:
                raise errors.NotFoundError(msg='站点不存在')
        row = await advance_policy_dao.get_by_site(db, obj.site_id)
        before = _policy_snapshot(row) if row is not None else None
        if row is None:
            row = RiderSalaryAdvancePolicy(site_id=obj.site_id)
            db.add(row)
        row.amount_mode = obj.amount_mode
        row.percent = q2(obj.percent)
        row.fixed_amount = q2(obj.fixed_amount)
        row.max_amount = q2(obj.max_amount) if obj.max_amount is not None else None
        row.monthly_max_count = obj.monthly_max_count
        row.min_tenure_days = obj.min_tenure_days
        row.min_completed_orders = obj.min_completed_orders
        row.min_amount = q2(obj.min_amount)
        await db.flush()
        label = '全局默认' if obj.site_id == GLOBAL_POLICY_SITE_ID else f'站点 {obj.site_id}'
        await audit_service.record(
            db,
            request,
            module='advance',
            action='保存预支规则',
            target_type='advance_policy',
            target_id=row.id,
            target_label=label,
            before=before,
            after=_policy_snapshot(row),
            description=f'保存{label}预支规则',
        )
        return await self.get(db=db, request=request, site_id=obj.site_id)

    async def evaluate(self, db: AsyncSession, rider: object) -> AdvanceQuote:
        """按骑手当前周期预估实发和规则计算可预支额度。"""
        site_id = int(rider.site_id)
        rule, _source, _owner = await self.resolve_rule(db, site_id)
        today = timezone.now().date()
        period = await resolve_period(db, site_id, int(rider.id), today)
        estimate_net, order_count = await self._estimate(db, rider, period)
        undeducted = await self._undeducted(db, int(rider.id))
        site = await site_dao.get(db, site_id)
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        in_flight = await advance_dao.list_in_flight(db, int(rider.id))
        used = q2(sum((row.amount for row in in_flight), Decimal(0)))
        monthly_count = await advance_dao.count_submitted_since(db, int(rider.id), month_start)
        return quote_advance(
            rule=rule,
            estimate_net=estimate_net,
            order_count=order_count,
            period_status=period.status,
            period_range=period_range_text(period.start_date, period.end_date),
            hire_date=getattr(rider, 'hire_date', None),
            today=today,
            on_job=getattr(rider, 'status', None) == RiderStatus.on_job,
            rider_limit=getattr(rider, 'advance_limit', None),
            site_limit=getattr(site, 'advance_limit', None) if site else None,
            in_flight_amount=used,
            in_flight_count=len(in_flight),
            monthly_count=monthly_count,
            undeducted_amount=undeducted,
        )

    @staticmethod
    async def _undeducted(db: AsyncSession, rider_id: int) -> Decimal:
        """已发放、尚未被定稿薪资扣回的预支：余额 + 草稿里暂扣的部分"""
        remaining = await db.scalar(
            select(func.coalesce(func.sum(RiderSalaryAdvance.remaining_amount), 0)).where(
                RiderSalaryAdvance.rider_id == rider_id,
                RiderSalaryAdvance.status == AdvanceStatus.paid.value,
                RiderSalaryAdvance.deleted == 0,
            )
        )
        held = await db.scalar(
            select(func.coalesce(func.sum(RiderSalaryPayroll.advance_deduction), 0)).where(
                RiderSalaryPayroll.rider_id == rider_id,
                RiderSalaryPayroll.status == PayrollStatus.draft.value,
                RiderSalaryPayroll.deleted == 0,
            )
        )
        return q2(Decimal(remaining or 0) + Decimal(held or 0))

    async def _estimate(self, db: AsyncSession, rider: object, period: object) -> tuple[Decimal, int]:
        rider_id = int(rider.id)
        stored = None
        period_id = getattr(period, 'id', None)
        if period_id:
            rows = list(
                (
                    await db.scalars(
                        select(RiderSalaryPayroll).where(
                            RiderSalaryPayroll.period_id == period_id,
                            RiderSalaryPayroll.rider_id == rider_id,
                            RiderSalaryPayroll.deleted == 0,
                        )
                    )
                ).all()
            )
            stored = pick_effective_payroll(rows)
            stale_draft = any(row.status == PayrollStatus.draft.value and row.stale for row in rows)
            if stale_draft or (stored is not None and stored.status not in _STORED):
                stored = None
        # 额度按扣预支前的实发计算；已占用的预支另行从额度中扣除
        if stored is not None:
            return q2(stored.net + stored.advance_deduction), int(stored.order_count)
        result = await calculate_rider_period(db, rider_id=rider_id, period=period, persist=False)
        return q2(result.net), int(result.order_count)

    async def _assert_scope(self, db: AsyncSession, request: Request, site_id: int) -> None:
        if site_id == GLOBAL_POLICY_SITE_ID:
            if not is_global_operator(request):
                raise errors.ForbiddenError(msg='只有薪资管理员可以修改全局预支规则')
            return
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, site_id)


advance_policy_service: AdvancePolicyService = AdvancePolicyService()


def quote_payload(quote: AdvanceQuote) -> dict[str, object]:
    """试算结果转成接口字段。"""
    data = asdict(quote)
    data['reasons'] = list(quote.reasons)
    return data
