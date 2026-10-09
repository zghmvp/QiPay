from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.plan_item import plan_item_dao
from backend.plugin.rider_salary.crud.plan_version import plan_version_dao
from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus, PeriodStatus, PlanVersionStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
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
from backend.plugin.rider_salary.service.audit_service import snapshot
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.service.plan_service import PlanService
from backend.plugin.rider_salary.utils.audit import audit_service, operator_display_name, require_reason
from backend.utils.timezone import timezone

CONFIRM_TEXT = '确认回退'
_VERSION_FIELDS = ('id', 'plan_id', 'version_no', 'status', 'is_used', 'items_hash', 'voided_time')
_BINDING_FIELDS = ('id', 'rider_id', 'plan_version_id', 'binding_type', 'start_date', 'end_date', 'remark')


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


def is_reversal_target(payroll: RiderSalaryPayroll) -> bool:
    """将被反冲：已定稿或已发薪、尚未反冲、且本身不是反冲单。"""
    if payroll.status not in {PayrollStatus.finalized.value, PayrollStatus.paid.value}:
        return False
    if payroll.reversed:
        return False
    return payroll.kind != PayrollKind.reversal.value


def classify_rollback_payrolls(
    payrolls: list[RiderSalaryPayroll],
) -> tuple[list[RiderSalaryPayroll], list[RiderSalaryPayroll], list[RiderSalaryPayroll]]:
    """拆成将作废的草稿、将反冲的已定稿、将反冲的已发薪。

    反冲单和已被反冲的原单不计入预览，避免把它们算成「已定稿」。
    """
    drafts = [row for row in payrolls if row.status == PayrollStatus.draft.value]
    finalized = [row for row in payrolls if is_reversal_target(row) and row.status == PayrollStatus.finalized.value]
    paid = [row for row in payrolls if is_reversal_target(row) and row.status == PayrollStatus.paid.value]
    return drafts, finalized, paid


def scope_rollback_payrolls(
    payrolls: list[RiderSalaryPayroll],
    version_id: int,
    *,
    referenced_ids: set[int] | None = None,
) -> tuple[list[RiderSalaryPayroll], list[RiderSalaryPayroll], list[RiderSalaryPayroll]]:
    """按 Q-04 方案 A 划定回退范围。

    草稿仍只作废引用该版本的。一旦某周期里有引用该版本、且尚未反冲的已定稿或已发薪单，
    该周期内其余未反冲的已定稿、已发薪单一并反冲，与周期级反冲口径一致。
    没有这种种子单的周期不动，避免把无关周期重开。
    ``referenced_ids`` 来自明细 ``plan_version_id`` 反查；不传时仍按薪资单上的版本 JSON 判断。
    """
    if referenced_ids is None:
        referenced = [row for row in payrolls if _version_referenced(row, version_id)]
    else:
        referenced = [row for row in payrolls if int(row.id) in referenced_ids]
    drafts = [row for row in referenced if row.status == PayrollStatus.draft.value]
    period_ids = {row.period_id for row in referenced if is_reversal_target(row)}
    targets = [row for row in payrolls if row.period_id in period_ids and is_reversal_target(row)]
    drafts.sort(key=lambda row: int(row.id))
    targets.sort(key=lambda row: int(row.id))
    finalized = [row for row in targets if row.status == PayrollStatus.finalized.value]
    paid = [row for row in targets if row.status == PayrollStatus.paid.value]
    return drafts, finalized, paid


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
        referenced_ids, payrolls = await self._payrolls_for_rollback(db, pk)
        drafts, finalized, paid = scope_rollback_payrolls(payrolls, pk, referenced_ids=referenced_ids)
        reversal_targets = [*finalized, *paid]
        period_ids = {row.period_id for row in reversal_targets}
        label = f'{plan.short_name if plan else "方案"} / v{version.version_no}'
        has_paid = bool(paid)
        if reversal_targets:
            reversal_text = (
                f'将生成 {len(reversal_targets)} 条反冲单'
                f'（含受影响周期内未引用该版本的已定稿、已发薪单），'
                f'{len(period_ids)} 个周期进入补发中'
            )
        else:
            reversal_text = f'将生成 0 条反冲单，{len(period_ids)} 个周期进入补发中'
        consequences = [
            f'方案版本「{label}」将作废',
            f'将解除 {len(bindings)} 条骑手绑定',
            f'将作废 {len(drafts)} 条草稿薪资结果，下次算薪将新建草稿',
            reversal_text,
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
                for row in [*drafts, *reversal_targets]
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

        before_version = snapshot(version, _VERSION_FIELDS)
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
        removed_binding_ids: list[int] = []
        for binding in bindings:
            rider = await db.scalar(
                select(RiderSalaryRider).where(RiderSalaryRider.id == binding.rider_id, RiderSalaryRider.deleted == 0)
            )
            before_binding = snapshot(binding, _BINDING_FIELDS)
            binding.deleted = binding.id
            binding.deleted_time = timezone.now()
            after_binding = snapshot(binding, _BINDING_FIELDS)
            after_binding['deleted'] = binding.deleted
            after_binding['deleted_time'] = timezone.to_str(binding.deleted_time)
            removed_binding_ids.append(binding.id)
            await audit_service.record(
                db,
                request,
                module='薪资方案',
                action='解除绑定',
                target_type='binding',
                target_id=binding.id,
                target_label=f'骑手{rider.job_no if rider else binding.rider_id}',
                reason=obj.reason,
                before=before_binding,
                after=after_binding,
            )

        referenced_ids, payrolls = await self._payrolls_for_rollback(db, pk)
        drafts, finalized, paid = scope_rollback_payrolls(payrolls, pk, referenced_ids=referenced_ids)
        for payroll in drafts:
            await payroll_service.restore_advances_from_payroll(db, payroll)
            payroll.status = PayrollStatus.voided.value
        for payroll in [*finalized, *paid]:
            await payroll_service.create_reversal(db, payroll, request, obj.reason)
        reopened_ids: set[int] = set()
        user = getattr(request, 'user', None)
        operator_id = int(getattr(user, 'id', 0) or 0)
        for payroll in [*finalized, *paid]:
            if payroll.period_id in reopened_ids:
                continue
            reopened_ids.add(payroll.period_id)
            period = await db.scalar(
                select(RiderSalarySettlePeriod).where(
                    RiderSalarySettlePeriod.id == payroll.period_id,
                    RiderSalarySettlePeriod.deleted == 0,
                )
            )
            if period is None:
                continue
            period.status = PeriodStatus.reopened.value
            period.reopened_time = timezone.now()
            period.reopened_by = operator_id
            await period_service.set_locked_flags(db, period, locked=False)

        copied = await self._copy_draft(db, version)
        plan = await plan_dao.get(db, version.plan_id)
        summary = (
            f'解除绑定{preview.binding_count}条，作废草稿薪资{preview.payrolls_draft}条，'
            f'下次算薪将新建草稿，生成反冲单{preview.reversal_count}条，'
            f'周期进入补发中{preview.periods_reopened}个'
        )
        after_version = snapshot(version, _VERSION_FIELDS)
        after_version['removed_binding_ids'] = removed_binding_ids
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='方案回退',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案{plan.name if plan else pk} v{version.version_no}',
            reason=obj.reason,
            before=before_version,
            after=after_version,
            description=(
                f'{operator_display_name(request)} 于 '
                f'{timezone.to_str(timezone.now())} 对 方案{plan.name if plan else ""} v{version.version_no} '
                f'执行了回退，原因：{obj.reason}；后果：{summary}'
            ),
        )
        return copied

    @staticmethod
    async def _payrolls_for_rollback(
        db: AsyncSession,
        version_id: int,
    ) -> tuple[set[int], list[RiderSalaryPayroll]]:
        """用明细上的方案版本反查薪资单，再补上同周期需要整期反冲的单。

        不再把未作废薪资单全表载入内存。引用关系以 ``rs_payroll_detail.plan_version_id``
        的 ``distinct payroll_id`` 为准；种子单所在周期里其余未反冲的已定稿、已发薪单另查一次。
        """
        referenced_ids = {
            int(item)
            for item in (
                await db.scalars(
                    select(RiderSalaryPayrollDetail.payroll_id)
                    .where(
                        RiderSalaryPayrollDetail.plan_version_id == version_id,
                        RiderSalaryPayrollDetail.deleted == 0,
                    )
                    .distinct()
                )
            ).all()
        }
        if not referenced_ids:
            return set(), []
        referenced = list(
            (
                await db.scalars(
                    select(RiderSalaryPayroll).where(
                        RiderSalaryPayroll.id.in_(referenced_ids),
                        RiderSalaryPayroll.deleted == 0,
                        RiderSalaryPayroll.status != PayrollStatus.voided.value,
                    )
                )
            ).all()
        )
        referenced_ids = {int(row.id) for row in referenced}
        period_ids = {row.period_id for row in referenced if is_reversal_target(row)}
        extras: list[RiderSalaryPayroll] = []
        if period_ids:
            extras = list(
                (
                    await db.scalars(
                        select(RiderSalaryPayroll).where(
                            RiderSalaryPayroll.period_id.in_(period_ids),
                            RiderSalaryPayroll.deleted == 0,
                            RiderSalaryPayroll.status.in_([
                                PayrollStatus.finalized.value,
                                PayrollStatus.paid.value,
                            ]),
                            RiderSalaryPayroll.reversed.is_(False),
                            RiderSalaryPayroll.kind != PayrollKind.reversal.value,
                        )
                    )
                ).all()
            )
        by_id = {int(row.id): row for row in referenced}
        for row in extras:
            by_id.setdefault(int(row.id), row)
        return referenced_ids, list(by_id.values())

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
