import hashlib
import json

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.plan_item import plan_item_dao
from backend.plugin.rider_salary.crud.plan_version import plan_version_dao
from backend.plugin.rider_salary.engine.compiler import validate_item
from backend.plugin.rider_salary.engine.fields import STAGE_ORDER
from backend.plugin.rider_salary.enums import CalcStage, PlanVersionStatus, TrialMode
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.schema.plan import (
    CreatePlanParam,
    CreatePlanVersionParam,
    DisablePlanVersionParam,
    GetActivePlanVersion,
    GetPlanBrief,
    UpdatePlanParam,
    UpdatePlanVersionParam,
)
from backend.plugin.rider_salary.schema.plan_item import GetPlanItemDetail, GetPlanVersionDetail, PlanItemParam
from backend.plugin.rider_salary.schema.trial import (
    TrialDailyRow,
    TrialPerOrderItem,
    TrialPerOrderRow,
    TrialPeriodItem,
    TrialResult,
    TrialSegmentOrderCount,
    TrialSummary,
)
from backend.plugin.rider_salary.service.calc_service import CalcResult, trial_rider_range
from backend.plugin.rider_salary.utils.audit import audit_service
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.plan_activate import (
    assert_activate_trial_is_binding_aware,
    clear_activation_trial_stamp,
    partial_segment_fixed_amount_warning,
    stamp_trial_for_activate,
)
from backend.plugin.rider_salary.utils.plan_guarantee import assert_accrued_guarantee_is_last_period_item
from backend.plugin.rider_salary.utils.plan_manual import assert_period_formula_not_manual_addend
from backend.plugin.rider_salary.utils.plan_threshold import assert_threshold_price_period_items_xor
from backend.utils.timezone import timezone

IMMUTABLE_MSG = '该方案版本已被使用，禁止编辑或删除，请停用后复制为新版本'
ZERO = Decimal('0.00')


def assert_version_editable(version: RiderSalaryPlanVersion) -> None:
    """is_used 禁止改删；非 draft 禁止当草稿编辑"""
    if version.is_used:
        raise errors.ForbiddenError(msg=IMMUTABLE_MSG)
    if version.status != PlanVersionStatus.draft.value:
        raise errors.ForbiddenError(msg='仅草稿版本可以编辑')


def canonical_items_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """纲要 §10#7 规范化 items"""

    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        return (STAGE_ORDER.get(str(item.get('stage')), 9), int(item.get('sort_order') or 0))

    payload: list[dict[str, Any]] = [
        {
            'condition_json': item.get('condition_json'),
            'enabled': bool(item.get('enabled', True)),
            'formula_json': item.get('formula_json'),
            'name': item.get('name'),
            'sort_order': int(item.get('sort_order') or 0),
            'stage': item.get('stage'),
            'subject_id': item.get('subject_id'),
        }
        for item in sorted(items, key=sort_key)
    ]
    return payload


def items_hash_of(items: list[dict[str, Any]]) -> str:
    """sha256(规范化 JSON)"""
    text = json.dumps(canonical_items_payload(items), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def orm_items_as_dicts(items: list[RiderSalaryPlanItem]) -> list[dict[str, Any]]:
    """ORM 方案项转哈希字典"""
    return [
        {
            'subject_id': item.subject_id,
            'name': item.name,
            'stage': item.stage,
            'sort_order': item.sort_order,
            'condition_json': item.condition_json,
            'formula_json': item.formula_json,
            'enabled': item.enabled,
        }
        for item in items
    ]


def _to_version_detail(
    version: RiderSalaryPlanVersion,
    items: list[RiderSalaryPlanItem],
    plan: RiderSalaryPlan | None,
) -> GetPlanVersionDetail:
    return GetPlanVersionDetail(
        id=version.id,
        plan_id=version.plan_id,
        version_no=version.version_no,
        status=version.status,
        mode_tag=version.mode_tag,
        is_used=version.is_used,
        items_hash=version.items_hash,
        trial_hash=version.trial_hash,
        trial_passed=version.trial_passed,
        trial_snapshot=version.trial_snapshot,
        copied_from_id=version.copied_from_id,
        activated_time=version.activated_time,
        disabled_time=version.disabled_time,
        voided_time=version.voided_time,
        remark=version.remark,
        created_time=version.created_time,
        updated_time=version.updated_time,
        items=[GetPlanItemDetail.model_validate(item) for item in items],
        plan=GetPlanBrief.model_validate(plan) if plan is not None else None,
    )


def build_trial_result(
    calc: CalcResult,
    trial_hash: str | None,
    *,
    mode: TrialMode | str = TrialMode.full_version,
) -> TrialResult:
    """将 CalcResult 转为试算接口结构"""
    if isinstance(mode, str):
        mode = TrialMode(mode)
    per_order_map: dict[tuple[Any, ...], TrialPerOrderRow] = {}
    period_items: list[TrialPeriodItem] = []
    daily_items: dict[date, list[TrialPerOrderItem]] = {}
    for detail in calc.details:
        item = TrialPerOrderItem(name=detail.name, amount=detail.amount, calc_trace=detail.calc_trace)
        if detail.stage == CalcStage.per_order.value:
            key = (detail.order_id, detail.order_no, detail.biz_date)
            row = per_order_map.get(key)
            if row is None:
                row = TrialPerOrderRow(
                    order_no=detail.order_no, order_id=detail.order_id, biz_date=detail.biz_date, items=[]
                )
                per_order_map[key] = row
            row.items.append(item)
        elif detail.stage == CalcStage.daily.value and detail.source == 'formula':
            if detail.biz_date is not None:
                daily_items.setdefault(detail.biz_date, []).append(item)
        elif detail.stage == CalcStage.period.value and detail.source == 'formula':
            period_items.append(
                TrialPeriodItem(
                    name=detail.name,
                    amount=detail.amount,
                    calc_trace=detail.calc_trace,
                    plan_version_id=detail.plan_version_id,
                )
            )
    daily_rows: list[TrialDailyRow] = [
        TrialDailyRow(
            biz_date=daily.biz_date,
            order_count=daily.order_count,
            amount=daily.formula_amount,
            day_status=daily.day_status,
            items=daily_items.get(daily.biz_date, []),
        )
        for daily in calc.dailies
    ]
    summary = TrialSummary(
        order_count=calc.order_count,
        valid_order_count=calc.valid_order_count,
        plan_order_count=calc.plan_order_count,
        segment_order_counts=[
            TrialSegmentOrderCount(
                plan_version_id=row.plan_version_id,
                start_date=row.start_date,
                end_date=row.end_date,
                plan_order_count=row.plan_order_count,
            )
            for row in (calc.segment_order_counts or [])
        ],
        gross=calc.gross,
        deduction_total=calc.deduction_total,
        net=calc.net,
        per_order_total=calc.per_order_total,
        daily_total=calc.daily_total,
        period_total=calc.period_total,
        manual_bonus=calc.bonus_total,
        manual_penalty=calc.penalty_total,
        bonus_total=calc.bonus_total,
        penalty_total=calc.penalty_total,
        advance_deduction=q2(ZERO),
        advance_deductible=calc.advance_deductible,
        warnings=list(calc.warnings),
    )
    return TrialResult(
        passed=True,
        trial_hash=trial_hash,
        mode=mode.value,
        mode_label=mode.label,
        matches_official_calculate=mode == TrialMode.binding_segments,
        summary=summary,
        per_order=list(per_order_map.values()),
        daily=daily_rows,
        period_items=period_items,
        warnings=list(calc.warnings),
        adjustments=[],
    )


class PlanService:
    """方案与版本服务"""

    @staticmethod
    async def get_plan(db: AsyncSession, pk: int) -> RiderSalaryPlan:
        """获取方案"""
        plan = await plan_dao.get(db, pk)
        if plan is None:
            raise errors.NotFoundError(msg='方案不存在')
        return plan

    @staticmethod
    async def get_plan_list(db: AsyncSession, name: str | None, status: str | None) -> dict[str, Any]:
        """分页方案"""
        stmt = await plan_dao.get_select(name, status)
        return await paging_data(db, stmt)

    @staticmethod
    async def create_plan(db: AsyncSession, obj: CreatePlanParam, request: Request) -> RiderSalaryPlan:
        """创建方案"""
        exists = await plan_dao.get_by_code(db, obj.code)
        if exists is not None:
            raise errors.ConflictError(msg='方案编码已存在')
        plan = await plan_dao.create(db, obj)
        await db.flush()
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='创建方案',
            target_type='plan',
            target_id=plan.id,
            target_label=f'方案{plan.code}/{plan.name}',
        )
        return plan

    @staticmethod
    async def update_plan(db: AsyncSession, pk: int, obj: UpdatePlanParam, request: Request) -> int:
        """更新方案"""
        plan = await PlanService.get_plan(db, pk)
        if obj.code and obj.code != plan.code:
            exists = await plan_dao.get_by_code(db, obj.code)
            if exists is not None:
                raise errors.ConflictError(msg='方案编码已存在')
        count = await plan_dao.update(db, pk, obj)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='修改方案',
            target_type='plan',
            target_id=pk,
            target_label=f'方案{plan.code}',
        )
        return count

    @staticmethod
    async def delete_plan(db: AsyncSession, pk: int, request: Request) -> int:
        """删除方案：无版本或全部为未使用草稿"""
        plan = await PlanService.get_plan(db, pk)
        versions = await plan_version_dao.list_by_plan(db, pk)
        for version in versions:
            if version.status != PlanVersionStatus.draft.value or version.is_used:
                raise errors.RequestError(msg='方案存在已启用或已使用的版本，禁止删除')
        for version in versions:
            await plan_item_dao.logical_delete_by_version(db, version.id)
            await plan_version_dao.delete(db, version.id)
        count = await plan_dao.delete(db, pk)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='删除方案',
            target_type='plan',
            target_id=pk,
            target_label=f'方案{plan.code}/{plan.name}',
        )
        return count

    @staticmethod
    async def get_version(db: AsyncSession, pk: int) -> GetPlanVersionDetail:
        """版本详情（含 items 与 plan）"""
        version = await plan_version_dao.get(db, pk)
        if version is None:
            raise errors.NotFoundError(msg='方案版本不存在')
        items = await plan_item_dao.list_by_version(db, pk)
        plan = await plan_dao.get(db, version.plan_id)
        return _to_version_detail(version, items, plan)

    @staticmethod
    async def get_version_model(db: AsyncSession, pk: int) -> RiderSalaryPlanVersion:
        """获取版本模型"""
        version = await plan_version_dao.get(db, pk)
        if version is None:
            raise errors.NotFoundError(msg='方案版本不存在')
        return version

    @staticmethod
    async def get_version_list(db: AsyncSession, plan_id: int | None, status: str | None) -> dict[str, Any]:
        """分页版本"""
        stmt = await plan_version_dao.get_select(plan_id, status)
        return await paging_data(db, stmt)

    @staticmethod
    async def get_active_dropdown(db: AsyncSession) -> list[GetActivePlanVersion]:
        """启用版本下拉"""
        versions = await plan_version_dao.get_active_list(db)
        result: list[GetActivePlanVersion] = []
        for version in versions:
            plan = await plan_dao.get(db, version.plan_id)
            if plan is None:
                continue
            result.append(
                GetActivePlanVersion(
                    id=version.id,
                    plan_name=plan.name,
                    short_name=plan.short_name,
                    color=plan.color,
                    version_no=version.version_no,
                )
            )
        return result

    @staticmethod
    async def create_version(db: AsyncSession, obj: CreatePlanVersionParam, request: Request) -> RiderSalaryPlanVersion:
        """创建草稿版本，version_no 自增"""
        plan = await PlanService.get_plan(db, obj.plan_id)
        version_no = await plan_version_dao.next_version_no(db, obj.plan_id)
        version = await plan_version_dao.create(db, obj, version_no)
        await db.flush()
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='创建方案版本',
            target_type='plan_version',
            target_id=version.id,
            target_label=f'方案{plan.name} v{version_no}',
        )
        return version

    @staticmethod
    async def update_version(db: AsyncSession, pk: int, obj: UpdatePlanVersionParam, request: Request) -> int:
        """更新版本基本信息"""
        version = await PlanService.get_version_model(db, pk)
        assert_version_editable(version)
        count = await plan_version_dao.update(db, pk, obj)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='修改方案版本',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案版本{pk}',
        )
        return count

    @staticmethod
    async def delete_version(db: AsyncSession, pk: int, request: Request) -> int:
        """删除未使用草稿版本"""
        version = await PlanService.get_version_model(db, pk)
        assert_version_editable(version)
        await plan_item_dao.logical_delete_by_version(db, pk)
        count = await plan_version_dao.delete(db, pk)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='删除方案版本',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案版本{pk}',
        )
        return count

    @staticmethod
    async def replace_items(
        db: AsyncSession, pk: int, items: list[PlanItemParam], request: Request
    ) -> GetPlanVersionDetail:
        """全量覆盖方案项"""
        version = await PlanService.get_version_model(db, pk)
        assert_version_editable(version)
        compiled: list[tuple[PlanItemParam, str, str]] = []
        item_errors: list[str] = []
        for index, item in enumerate(items):
            result = validate_item(item.stage, item.condition_json, item.formula_json)
            if not result.ok:
                label = item.name or f'第 {index + 1} 项'
                item_errors.extend([f'方案项「{label}」{msg}' for msg in result.errors])
            compiled.append((item, result.condition_expr, result.formula_expr))
        if item_errors:
            raise errors.RequestError(msg='；'.join(item_errors))
        assert_accrued_guarantee_is_last_period_item(items)
        assert_threshold_price_period_items_xor(items)
        assert_period_formula_not_manual_addend(items)
        await plan_item_dao.logical_delete_by_version(db, pk)
        for item, condition_expr, formula_expr in compiled:
            await plan_item_dao.create(
                db,
                pk,
                item,
                condition_expr=condition_expr,
                formula_expr=formula_expr,
            )
        new_hash = items_hash_of([item.model_dump() for item, _c, _f in compiled])
        if version.items_hash != new_hash:
            clear_activation_trial_stamp(version)
        version.items_hash = new_hash
        await db.flush()
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='更新方案项',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案版本{pk}',
        )
        return await PlanService.get_version(db, pk)

    @staticmethod
    async def trial(
        db: AsyncSession,
        pk: int,
        rider_id: int,
        start_date: date,
        end_date: date,
        request: Request,
        mode: TrialMode = TrialMode.full_version,
    ) -> TrialResult:
        """试算；整版是 what-if，绑定感知才写入启用闸门认的模式。"""
        if isinstance(mode, str):
            mode = TrialMode(mode)
        version = await PlanService.get_version_model(db, pk)
        items = await plan_item_dao.list_by_version(db, pk)
        if not items:
            raise errors.RequestError(msg='请先配置方案项再试算')
        forced = version if mode == TrialMode.full_version else None
        calc = await trial_rider_range(
            db,
            rider_id=rider_id,
            start=start_date,
            end=end_date,
            forced_plan_version=forced,
        )
        current_hash = items_hash_of(orm_items_as_dicts(items))
        result = build_trial_result(calc, current_hash, mode=mode)
        if mode == TrialMode.binding_segments:
            warn = partial_segment_fixed_amount_warning(
                items,
                start_date,
                end_date,
                calc.segment_order_counts,
            )
            if warn:
                if warn not in result.warnings:
                    result.warnings.append(warn)
                if warn not in result.summary.warnings:
                    result.summary.warnings.append(warn)
        stamp_trial_for_activate(
            version,
            mode=mode,
            current_hash=current_hash,
            summary=result.summary.model_dump(mode='json'),
        )
        await db.flush()
        action = '试算方案' if mode == TrialMode.full_version else '按绑定分段试算'
        plan = await plan_dao.get(db, version.plan_id)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action=action,
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案{plan.name if plan else pk} v{version.version_no}',
        )
        return result

    @staticmethod
    async def activate(db: AsyncSession, pk: int, request: Request) -> None:
        """启用版本"""
        version = await PlanService.get_version_model(db, pk)
        if version.status == PlanVersionStatus.voided.value:
            raise errors.RequestError(msg='已作废版本不能启用')
        items = await plan_item_dao.list_by_version(db, pk)
        if len(items) < 1:
            raise errors.RequestError(msg='启用前至少需要 1 条方案项')
        activate_errors: list[str] = []
        for item in items:
            result = validate_item(item.stage, item.condition_json, item.formula_json)
            if not result.ok:
                activate_errors.extend([f'方案项「{item.name}」{msg}' for msg in result.errors])
        if activate_errors:
            raise errors.RequestError(msg='；'.join(activate_errors))
        assert_accrued_guarantee_is_last_period_item(items)
        assert_threshold_price_period_items_xor(items)
        assert_period_formula_not_manual_addend(items)
        current_hash = items_hash_of(orm_items_as_dicts(items))
        version.items_hash = current_hash
        assert_activate_trial_is_binding_aware(version, current_hash)
        version.status = PlanVersionStatus.active.value
        version.activated_time = timezone.now()
        await db.flush()
        plan = await plan_dao.get(db, version.plan_id)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='启用方案',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案{plan.name if plan else pk} v{version.version_no}',
        )

    @staticmethod
    async def disable(db: AsyncSession, pk: int, obj: DisablePlanVersionParam, request: Request) -> None:
        """停用版本"""
        version = await PlanService.get_version_model(db, pk)
        if version.status != PlanVersionStatus.active.value:
            raise errors.RequestError(msg='仅启用中的版本可以停用')
        version.status = PlanVersionStatus.disabled.value
        version.disabled_time = timezone.now()
        await db.flush()
        plan = await plan_dao.get(db, version.plan_id)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='方案停用',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案{plan.name if plan else pk} v{version.version_no}',
            reason=obj.reason,
        )

    @staticmethod
    async def copy(db: AsyncSession, pk: int, request: Request) -> RiderSalaryPlanVersion:
        """复制为新草稿"""
        version = await PlanService.get_version_model(db, pk)
        items = await plan_item_dao.list_by_version(db, pk)
        plan = await PlanService.get_plan(db, version.plan_id)
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
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='复制方案版本',
            target_type='plan_version',
            target_id=copied.id,
            target_label=f'方案{plan.name} v{version.version_no} → v{version_no}',
        )
        return copied


plan_service = PlanService()
