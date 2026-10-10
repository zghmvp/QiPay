from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import Request
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

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
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.schema.payroll import (
    GetPayrollDailyDetail,
    GetPayrollDetailItem,
    GetPayrollGroupedDetail,
)
from backend.plugin.rider_salary.service.audit_service import snapshot
from backend.plugin.rider_salary.utils.audit import audit_service
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

ADVANCE_SUBJECT_ID = 0
ZERO = Decimal('0.00')
_PAYROLL_FIELDS = (
    'id',
    'period_id',
    'rider_id',
    'kind',
    'status',
    'reversed',
    'reversed_of_id',
    'gross',
    'net',
    'advance_deduction',
    'deduction_total',
    'order_count',
    'valid_order_count',
)

# 预支 deducted_amount 应等于有效薪资单上的预支抵扣明细合计。
# 有效单：未删除、非作废、未被反冲、且不是反冲单。抵扣明细金额为负，合计取相反数。
# 只返回有差异的预支；0 行表示一致。方言为 PostgreSQL（运行库）。
ADVANCE_DEDUCTION_CONSISTENCY_SQL = """
SELECT
    a.id AS advance_id,
    a.deducted_amount,
    COALESCE(s.detail_total, 0) AS detail_total
FROM rs_advance a
LEFT JOIN (
    SELECT
        (d.calc_trace ->> 'advance_id')::bigint AS advance_id,
        SUM(-d.amount) AS detail_total
    FROM rs_payroll_detail d
    INNER JOIN rs_payroll p ON p.id = d.payroll_id AND p.deleted = 0
    WHERE d.deleted = 0
      AND d.source = 'advance'
      AND p.status <> 'voided'
      AND p.reversed = false
      AND p.kind <> 'reversal'
      AND d.calc_trace ->> 'advance_id' IS NOT NULL
    GROUP BY 1
) s ON s.advance_id = a.id
WHERE a.deleted = 0
  AND a.deducted_amount IS DISTINCT FROM COALESCE(s.detail_total, 0)
"""


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


def advance_deduction_diffs(
    advances: list[Any],
    payrolls: list[Any],
    details: list[Any],
) -> list[tuple[int, Decimal, Decimal]]:
    """
    与 ADVANCE_DEDUCTION_CONSISTENCY_SQL 同一口径的内存对照。

    返回 (预支 ID, deducted_amount, 有效明细合计)。空列表表示没有差异。
    作废单、已被反冲的原单、反冲单上的明细不计入。
    """
    effective_ids = {
        int(payroll.id)
        for payroll in payrolls
        if int(getattr(payroll, 'deleted', 0) or 0) == 0
        and getattr(payroll, 'status', None) != PayrollStatus.voided.value
        and not getattr(payroll, 'reversed', False)
        and getattr(payroll, 'kind', None) != PayrollKind.reversal.value
    }
    totals: dict[int, Decimal] = {}
    for detail in details:
        if int(getattr(detail, 'deleted', 0) or 0) != 0:
            continue
        if getattr(detail, 'source', None) != DetailSource.advance.value:
            continue
        if int(getattr(detail, 'payroll_id', 0) or 0) not in effective_ids:
            continue
        advance_id = (getattr(detail, 'calc_trace', None) or {}).get('advance_id')
        if not advance_id:
            continue
        key = int(advance_id)
        totals[key] = q2(totals.get(key, ZERO) + q2(-getattr(detail, 'amount', ZERO)))
    diffs: list[tuple[int, Decimal, Decimal]] = []
    for advance in advances:
        if int(getattr(advance, 'deleted', 0) or 0) != 0:
            continue
        deducted = q2(getattr(advance, 'deducted_amount', ZERO) or ZERO)
        detail_total = q2(totals.get(int(advance.id), ZERO))
        if deducted != detail_total:
            diffs.append((int(advance.id), deducted, detail_total))
    return diffs


async def find_advance_deduction_mismatches(db: AsyncSession) -> list[Any]:
    """执行预支抵扣一致性 SQL。空列表表示 deducted_amount 与有效明细合计一致。"""
    result = await db.execute(text(ADVANCE_DEDUCTION_CONSISTENCY_SQL))
    return list(result.all())


def apply_advance_restore(advance: Any, restored: Decimal) -> None:
    """把一笔预支抵扣加回 remaining，并回退 deduct_status（draft 重算 / 作废 / 反冲共用）"""
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
        key=lambda item: (
            getattr(item, 'paid_time', None) or datetime.min.replace(tzinfo=timezone.tz_info),
            int(getattr(item, 'id', 0) or 0),
        ),
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


def _advance_id_of(detail: Any) -> int | None:
    trace = getattr(detail, 'calc_trace', None) or {}
    raw = trace.get('advance_id')
    if raw in (None, ''):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _copy_advance(advance: Any) -> SimpleNamespace:
    """预支的只读副本。后续加回和抵扣只改副本，避免会话把 remaining 刷回库。"""
    return SimpleNamespace(
        id=int(getattr(advance, 'id', 0) or 0),
        amount=q2(getattr(advance, 'amount', ZERO) or ZERO),
        remaining_amount=q2(getattr(advance, 'remaining_amount', ZERO) or ZERO),
        deducted_amount=q2(getattr(advance, 'deducted_amount', ZERO) or ZERO),
        paid_time=getattr(advance, 'paid_time', None),
    )


def preview_advance_deduction(
    advances: list[Any],
    occupied_details: list[Any],
    cap: Decimal,
) -> Decimal | None:
    """草稿需重算时的只读预估抵扣。

    按纲要 §10 第 30 条，先把本草稿 ``source=advance`` 明细加回待抵扣余额，再按当前可抵扣额
    调用 ``compute_advance_deduction``。加回和抵扣都发生在副本上，入参对象的
    ``remaining_amount`` 保持不变。没有可加回的明细时返回空，调用方沿用算薪给出的参考额。
    """
    copies = [_copy_advance(item) for item in advances]
    by_id = {item.id: item for item in copies if item.id}
    restored = False
    for detail in occupied_details:
        if int(getattr(detail, 'deleted', 0) or 0) != 0:
            continue
        if getattr(detail, 'source', None) != DetailSource.advance.value:
            continue
        advance_id = _advance_id_of(detail)
        if advance_id is None:
            continue
        target = by_id.get(advance_id)
        if target is None:
            continue
        apply_advance_restore(target, q2(getattr(detail, 'amount', ZERO) or ZERO))
        restored = True
    if not restored:
        return None
    total, _lines = compute_advance_deduction(copies, cap, persist=False)
    return total


class PayrollService:
    """薪资单领域服务：预支抵扣、反冲"""

    @staticmethod
    async def load_paid_advances(
        db: AsyncSession,
        rider_id: int,
        *,
        for_update: bool = False,
    ) -> list[RiderSalaryAdvance]:
        """已发放且仍有待抵扣的预支单。

        ``for_update`` 时按 ``paid_time``、``id`` 加行锁，避免两个周期同时扣同一笔余额。
        只读预估不要加锁。
        """
        stmt = (
            select(RiderSalaryAdvance)
            .where(
                RiderSalaryAdvance.rider_id == rider_id,
                RiderSalaryAdvance.status == AdvanceStatus.paid.value,
                RiderSalaryAdvance.deleted == 0,
            )
            .order_by(RiderSalaryAdvance.paid_time.asc(), RiderSalaryAdvance.id.asc())
        )
        if for_update:
            stmt = stmt.with_for_update()
        rows = await db.scalars(stmt)
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
        advances = await self.load_paid_advances(db, rider_id, for_update=persist)
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

        before = snapshot(payroll, _PAYROLL_FIELDS)
        claimed = await db.execute(
            update(RiderSalaryPayroll)
            .where(
                RiderSalaryPayroll.id == payroll.id,
                RiderSalaryPayroll.reversed.is_(False),
                RiderSalaryPayroll.deleted == 0,
                RiderSalaryPayroll.kind != PayrollKind.reversal.value,
                RiderSalaryPayroll.status.in_([PayrollStatus.finalized.value, PayrollStatus.paid.value]),
            )
            .values(reversed=True)
            .execution_options(synchronize_session=False)
        )
        rowcount = getattr(claimed, 'rowcount', None)
        if rowcount is None or int(rowcount or 0) != 1:
            raise errors.RequestError(msg='该薪资单已被反冲')
        if hasattr(payroll, '_sa_instance_state'):
            set_committed_value(payroll, 'reversed', True)
        else:
            payroll.reversed = True

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

        await db.flush()
        after_original = snapshot(payroll, _PAYROLL_FIELDS)
        after_original['reversed'] = True
        await audit_service.record(
            db,
            operator,
            module='薪资结果',
            action='反冲补发',
            target_type='payroll',
            target_id=payroll.id,
            target_label=f'薪资单{payroll.id}',
            reason=reason,
            before=before,
            after={'payroll': after_original, 'reversal': snapshot(reversal, _PAYROLL_FIELDS)},
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
            select(RiderSalaryAdvance)
            .where(
                RiderSalaryAdvance.id == int(advance_id),
                RiderSalaryAdvance.deleted == 0,
            )
            .with_for_update()
        )
        if advance is None:
            return
        apply_advance_restore(advance, q2(abs(detail.amount)))

    async def restore_advances_from_payroll(self, db: AsyncSession, payroll: RiderSalaryPayroll) -> None:
        """按薪资单上的预支抵扣明细把 remaining 加回。

        草稿重算前调用，供本次重新抵扣。方案回退作废草稿前也必须调用，
        否则已抵扣金额会随作废凭空消失，预支无法再次抵扣。
        """
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
        """分页薪资单"""
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
        return await paging_data(db, stmt)

    async def get_grouped(self, db: AsyncSession, request: Request, pk: int) -> GetPayrollGroupedDetail:
        """汇总 + 明细按阶段分组 + 日汇总"""
        payroll = await self.get(db, pk)
        await self.assert_visible(db, request, payroll)
        details = await payroll_detail_dao.list_by_payroll(db, pk)
        grouped: dict[str, list[GetPayrollDetailItem]] = {
            CalcStage.per_order.value: [],
            CalcStage.daily.value: [],
            CalcStage.period.value: [],
        }
        for row in details:
            grouped.setdefault(row.stage, []).append(GetPayrollDetailItem.model_validate(row))
        period = await db.scalar(
            select(RiderSalarySettlePeriod).where(
                RiderSalarySettlePeriod.id == payroll.period_id,
                RiderSalarySettlePeriod.deleted == 0,
            )
        )
        dailies: list[GetPayrollDailyDetail] = []
        if period is not None:
            rows = await payroll_daily_dao.list_by_rider_range(
                db,
                payroll.rider_id,
                period.start_date,
                period.end_date,
            )
            dailies = [GetPayrollDailyDetail.model_validate(row) for row in rows]
        data = GetPayrollGroupedDetail.model_validate(payroll)
        data.details = grouped
        data.dailies = dailies
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
        return await paging_data(db, stmt)


payroll_service = PayrollService()
