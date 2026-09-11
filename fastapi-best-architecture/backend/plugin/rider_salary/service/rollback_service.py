from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.plan_item import plan_item_dao
from backend.plugin.rider_salary.crud.plan_version import plan_version_dao
from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus, PeriodStatus, PlanVersionStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_plan_binding import RiderSalaryRiderPlanBinding
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.schema.rollback import (
    RollbackParam,
    RollbackPreviewPayroll,
    RollbackPreviewResult,
    RollbackPreviewRider,
)
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.service.plan_service import PlanService
from backend.plugin.rider_salary.utils.audit import audit_service, require_reason
from backend.plugin.rider_salary.utils.recalc import mark_stale
from backend.utils.timezone import timezone

CONFIRM_TEXT = '确认回退'


def assert_rollback_confirm(*, has_paid: bool, confirm_text: str | None) -> None:
    """存在已发薪结果时必须输入「确认回退」；纯草稿回退只需 reason"""
    if not has_paid:
        return
    if (confirm_text or '').strip() != CONFIRM_TEXT:
        raise errors.RequestError(msg='请输入确认文字「确认回退」')


def _assert_superuser(request: Request) -> None:
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_superuser', False):
        raise errors.ForbiddenError(msg='仅超级管理员可执行方案回退')


def _version_referenced(payroll: RiderSalaryPayroll, version_id: int) -> bool:
    ids = payroll.plan_version_ids or []
    return version_id in ids


class RollbackService:
    """受控回退"""

    async def preview(self, db: AsyncSession, pk: int, request: Request) -> RollbackPreviewResult:
        """回退预览"""
        _assert_superuser(request)
        version = await PlanService.get_version_model(db, pk)
        plan = await plan_dao.get(db, version.plan_id)
        bindings = list(
            (
                await db.scalars(
                    select(RiderSalaryRiderPlanBinding).where(
                        RiderSalaryRiderPlanBinding.plan_version_id == pk,
                        RiderSalaryRiderPlanBinding.deleted == 0,
                    )
                )
            ).all()
        )
        rider_rows: list[RollbackPreviewRider] = []
        for binding in bindings:
            rider = await db.scalar(
                select(RiderSalaryRider).where(
                    RiderSalaryRider.id == binding.rider_id,
                    RiderSalaryRider.deleted == 0,
                )
            )
            rider_rows.append(
                RollbackPreviewRider(
                    rider_id=binding.rider_id,
                    job_no=rider.job_no if rider else None,
                    name=rider.name if rider else None,
                    start_date=binding.start_date,
                    end_date=binding.end_date,
                )
            )
        payrolls = await self._affected_payrolls(db, pk)
        drafts = [row for row in payrolls if row.status == PayrollStatus.draft.value]
        finalized = [row for row in payrolls if row.status == PayrollStatus.finalized.value]
        paid = [row for row in payrolls if row.status == PayrollStatus.paid.value]
        reversal_targets = [
            row
            for row in payrolls
            if row.status in {PayrollStatus.finalized.value, PayrollStatus.paid.value}
            and not row.reversed
            and row.kind != PayrollKind.reversal.value
        ]
        period_ids = {row.period_id for row in reversal_targets}
        label = f'{plan.short_name if plan else "方案"} / v{version.version_no}'
        has_paid = bool(paid)
        consequences = [
            f'方案版本「{label}」将作废',
            f'将解除 {len(bindings)} 条骑手绑定',
            f'将作废 {len(drafts)} 条草稿薪资结果，并标记需重算',
            f'将生成 {len(reversal_targets)} 条反冲单，{len(period_ids)} 个周期进入补发中',
            '系统将自动复制一份新草稿版本供修改后重新试算启用',
        ]
        if has_paid:
            consequences.insert(0, '该方案已执行发薪操作，回退将产生财务影响')
        return RollbackPreviewResult(
            version_label=label,
            version_id=version.id,
            binding_count=len(bindings),
            riders=rider_rows,
            payrolls_draft=len(drafts),
            payrolls_finalized=len(finalized),
            payrolls_paid=len(paid),
            reversal_count=len(reversal_targets),
            periods_reopened=len(period_ids),
            has_paid=has_paid,
            consequences=consequences,
            payrolls=[
                RollbackPreviewPayroll(
                    id=row.id,
                    period_id=row.period_id,
                    rider_id=row.rider_id,
                    status=row.status,
                    kind=row.kind,
                )
                for row in payrolls
            ],
        )

    async def rollback(
        self,
        db: AsyncSession,
        pk: int,
        obj: RollbackParam,
        request: Request,
    ) -> RiderSalaryPlanVersion:
        """执行回退（单事务由 API CurrentSessionTransaction 提交）"""
        _assert_superuser(request)
        require_reason('方案回退', obj.reason)
        version = await PlanService.get_version_model(db, pk)
        if version.status == PlanVersionStatus.draft.value and not version.is_used:
            raise errors.RequestError(msg='该版本尚未启用，请直接删除，无需回退')
        if version.status == PlanVersionStatus.voided.value:
            raise errors.RequestError(msg='该版本已作废')
        preview = await self.preview(db, pk, request)
        assert_rollback_confirm(has_paid=preview.has_paid, confirm_text=obj.confirm_text)

        version.status = PlanVersionStatus.voided.value
        version.voided_time = timezone.now()

        bindings = list(
            (
                await db.scalars(
                    select(RiderSalaryRiderPlanBinding).where(
                        RiderSalaryRiderPlanBinding.plan_version_id == pk,
                        RiderSalaryRiderPlanBinding.deleted == 0,
                    )
                )
            ).all()
        )
        for binding in bindings:
            rider = await db.scalar(
                select(RiderSalaryRider).where(RiderSalaryRider.id == binding.rider_id, RiderSalaryRider.deleted == 0)
            )
            binding.deleted = binding.id
            binding.deleted_time = timezone.now()
            await audit_service.record(
                db,
                request,
                module='薪资方案',
                action='解除绑定',
                target_type='binding',
                target_id=binding.id,
                target_label=f'骑手{rider.job_no if rider else binding.rider_id}',
                reason=obj.reason,
            )

        payrolls = await self._affected_payrolls(db, pk)
        for payroll in payrolls:
            if payroll.status == PayrollStatus.draft.value:
                payroll.status = PayrollStatus.voided.value
                period = await db.scalar(
                    select(RiderSalarySettlePeriod).where(
                        RiderSalarySettlePeriod.id == payroll.period_id,
                        RiderSalarySettlePeriod.deleted == 0,
                    )
                )
                if period is not None:
                    await mark_stale(
                        db,
                        rider_ids=[payroll.rider_id],
                        date_from=period.start_date,
                        date_to=period.end_date,
                    )
            elif (
                payroll.status in {PayrollStatus.finalized.value, PayrollStatus.paid.value}
                and not payroll.reversed
                and payroll.kind != PayrollKind.reversal.value
            ):
                await payroll_service.create_reversal(db, payroll, request, obj.reason)
                period = await db.scalar(
                    select(RiderSalarySettlePeriod).where(
                        RiderSalarySettlePeriod.id == payroll.period_id,
                        RiderSalarySettlePeriod.deleted == 0,
                    )
                )
                if period is not None:
                    period.status = PeriodStatus.reopened.value
                    period.reopened_time = timezone.now()
                    user = getattr(request, 'user', None)
                    period.reopened_by = int(getattr(user, 'id', 0) or 0)
                    await period_service._set_locked_flags(db, period, locked=False)

        copied = await self._copy_draft(db, version)
        plan = await plan_dao.get(db, version.plan_id)
        summary = (
            f'解除绑定{preview.binding_count}条，作废草稿薪资{preview.payrolls_draft}条，'
            f'生成反冲单{preview.reversal_count}条，周期进入补发中{preview.periods_reopened}个'
        )
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='方案回退',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案{plan.name if plan else pk} v{version.version_no}',
            reason=obj.reason,
            description=(
                f'{getattr(request.user, "nickname", None) or getattr(request.user, "username", "未知")} 于 '
                f'{timezone.to_str(timezone.now())} 对 方案{plan.name if plan else ""} v{version.version_no} '
                f'执行了回退，原因：{obj.reason}；后果：{summary}'
            ),
        )
        return copied

    @staticmethod
    async def _affected_payrolls(db: AsyncSession, version_id: int) -> list[RiderSalaryPayroll]:
        rows = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.deleted == 0,
                        RiderSalaryPayroll.status != PayrollStatus.voided.value,
                    )
                )
            ).all()
        )
        return [row for row in rows if _version_referenced(row, version_id)]

    @staticmethod
    async def _copy_draft(db: AsyncSession, version: RiderSalaryPlanVersion) -> RiderSalaryPlanVersion:
        version_no = await plan_version_dao.next_version_no(db, version.plan_id)
        copied = RiderSalaryPlanVersion(
            plan_id=version.plan_id,
            version_no=version_no,
            status=PlanVersionStatus.draft.value,
            mode_tag=version.mode_tag,
            copied_from_id=version.id,
            remark=version.remark,
            items_hash=version.items_hash,
            trial_passed=False,
        )
        db.add(copied)
        await db.flush()
        items = await plan_item_dao.list_by_version(db, version.id)
        for item in items:
            db.add(
                RiderSalaryPlanItem(
                    plan_version_id=copied.id,
                    subject_id=item.subject_id,
                    name=item.name,
                    stage=item.stage,
                    sort_order=item.sort_order,
                    condition_json=item.condition_json,
                    formula_json=item.formula_json,
                    condition_expr=item.condition_expr,
                    formula_expr=item.formula_expr,
                    enabled=item.enabled,
                    remark=item.remark,
                )
            )
        await db.flush()
        return copied


rollback_service = RollbackService()
