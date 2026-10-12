import hashlib
import json

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.plan import plan_dao
from backend.plugin.rider_salary.crud.plan_item import plan_item_dao
from backend.plugin.rider_salary.crud.plan_version import plan_version_dao
from backend.plugin.rider_salary.crud.rider import rider_dao
from backend.plugin.rider_salary.engine.compiler import references_accrued_amount, validate_item
from backend.plugin.rider_salary.engine.context import iter_dates
from backend.plugin.rider_salary.engine.fields import STAGE_ORDER
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, EnableStatus, PlanVersionStatus, SubjectDirection
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.day_flag import RiderSalaryDayFlag
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_employ_history import RiderSalaryRiderEmployHistory
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.plugin.rider_salary.schema.plan import (
    CreatePlanParam,
    CreatePlanVersionParam,
    DisablePlanVersionParam,
    GetActivePlanVersion,
    GetPlanBrief,
    UpdatePlanParam,
    UpdatePlanVersionParam,
)
from backend.plugin.rider_salary.schema.plan_item import (
    GetPlanItemDetail,
    GetPlanVersionDetail,
    PlanItemParam,
    TrialUnsavedPlanParam,
)
from backend.plugin.rider_salary.schema.trial import (
    TrialDailyRow,
    TrialPerOrderItem,
    TrialPerOrderRow,
    TrialPeriodItem,
    TrialResult,
    TrialSummary,
)
from backend.plugin.rider_salary.service.audit_service import snapshot
from backend.plugin.rider_salary.service.calc_service import (
    CalcInput,
    CalcResult,
    is_eval_failure_warning,
    run_calc_pipeline,
    trial_max_orders,
    trial_rider_range,
)
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.utils.audit import audit_service
from backend.plugin.rider_salary.utils.db_errors import client_error_from_integrity
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.lifecycle import assert_plan_can_activate, plan_accepts_new_binding
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

IMMUTABLE_MSG = '该方案版本已被使用，禁止编辑或删除，请停用后复制为新版本'
ACCRUED_SORT_MSG = '保底项「{name}」引用「本期已计金额」，必须排在周期阶段最后，否则补差会偏大'
ZERO = Decimal('0.00')
UNSAVED_PLAN_VERSION_ID = 0
_PLAN_FIELDS = ('id', 'code', 'name', 'short_name', 'color', 'description', 'status')
_VERSION_FIELDS = (
    'id',
    'plan_id',
    'version_no',
    'status',
    'mode_tag',
    'is_used',
    'items_hash',
    'trial_hash',
    'trial_passed',
    'copied_from_id',
    'activated_time',
    'disabled_time',
    'voided_time',
    'remark',
)
_ITEM_FIELDS = (
    'id',
    'plan_version_id',
    'subject_id',
    'name',
    'stage',
    'sort_order',
    'condition_json',
    'formula_json',
    'condition_expr',
    'formula_expr',
    'enabled',
    'remark',
)


def _deleted_after(before: dict[str, Any], pk: int) -> dict[str, Any]:
    """逻辑删除后的快照。"""
    after = dict(before)
    after['id'] = pk
    after['deleted'] = True
    return after


def _patched_snapshot(before: dict[str, Any], obj: object, fields: tuple[str, ...]) -> dict[str, Any]:
    """用本次提交的字段覆盖更新前快照。"""
    after = dict(before)
    if not hasattr(obj, 'model_dump'):
        return after
    data = obj.model_dump(exclude_unset=True)
    for name in fields:
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, date):
            after[name] = value.isoformat()
        elif isinstance(value, Decimal):
            after[name] = str(value)
        else:
            after[name] = value
    return after


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def assert_accrued_items_last(items: list[Any]) -> None:
    """已启用的周期项若引用「本期已计金额」，执行顺序必须是该阶段最大值。

    已启用的历史版本不走这里：版本不可变，只在保存草稿和启用时调用。
    停用项不参与累计，因此不要求它们排在最后。

    :param items: 方案项，字典或模型均可
    :return:
    """
    period = [
        item
        for item in items
        if _item_value(item, 'stage') == CalcStage.period.value and bool(_item_value(item, 'enabled', True))
    ]
    if not period:
        return
    max_sort = max(int(_item_value(item, 'sort_order') or 0) for item in period)
    messages: list[str] = []
    for item in period:
        if not references_accrued_amount(
            condition_json=_item_value(item, 'condition_json'),
            formula_json=_item_value(item, 'formula_json'),
            condition_expr=_item_value(item, 'condition_expr'),
            formula_expr=_item_value(item, 'formula_expr'),
        ):
            continue
        sort_order = int(_item_value(item, 'sort_order') or 0)
        blocked = any(
            other is not item
            and int(_item_value(other, 'sort_order') or 0) >= sort_order
            and not references_accrued_amount(
                condition_json=_item_value(other, 'condition_json'),
                formula_json=_item_value(other, 'formula_json'),
                condition_expr=_item_value(other, 'condition_expr'),
                formula_expr=_item_value(other, 'formula_expr'),
            )
            for other in period
        )
        if sort_order != max_sort or blocked:
            name = _item_value(item, 'name') or '未命名'
            messages.append(ACCRUED_SORT_MSG.format(name=name))
    if messages:
        raise errors.RequestError(msg='；'.join(messages))


def assert_version_editable(version: RiderSalaryPlanVersion) -> None:
    """is_used 禁止改删；非 draft 禁止当草稿编辑"""
    if version.is_used:
        raise errors.ForbiddenError(msg=IMMUTABLE_MSG)
    if version.status != PlanVersionStatus.draft.value:
        raise errors.ForbiddenError(msg='仅草稿版本可以编辑')


def plan_item_subject_error(subject: Any | None, *, index: int, name: str) -> str | None:
    """方案项科目不合格时返回中文原因。

    方案没有站点或用工类型，算薪会把方案项套到所有绑定骑手。
    因此科目必须存在、处于启用，且适用范围为空（空表示全站、全部用工类型）。

    :param subject: 科目；缺失时为空
    :param index: 方案项序号，从 1 开始
    :param name: 方案项名称
    :return: 不合格原因；合格时为空
    """
    label = name or '未命名'
    if subject is None:
        return f'第 {index} 项「{label}」科目不存在'
    if str(getattr(subject, 'status', '')) != EnableStatus.enable.value:
        return f'第 {index} 项「{label}」引用的科目已停用'
    if getattr(subject, 'scope_sites', None) or getattr(subject, 'scope_employ_types', None):
        return f'第 {index} 项「{label}」引用的科目限定了适用范围，不能用于方案项'
    return None


async def assert_plan_item_subjects(db: AsyncSession, items: list[Any]) -> None:
    """保存和启用前校验科目存在、启用，且适用范围为全站。

    :param db: 数据库会话
    :param items: 待写入或已保存的方案项
    :return:
    """
    if not items:
        return
    subject_ids = {int(_item_value(item, 'subject_id')) for item in items}
    subjects = await load_trial_subjects(db, subject_ids)
    messages: list[str] = []
    for index, item in enumerate(items, start=1):
        subject = subjects.get(int(_item_value(item, 'subject_id')))
        message = plan_item_subject_error(subject, index=index, name=str(_item_value(item, 'name') or ''))
        if message:
            messages.append(message)
    if messages:
        raise errors.RequestError(msg='；'.join(messages))


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


def compile_unsaved_items(items: list[PlanItemParam]) -> list[tuple[PlanItemParam, str, str]]:
    """编译未保存方案项。编译失败直接拒绝，避免把空公式当成 0 元。"""
    if not items:
        raise errors.RequestError(msg='请先配置方案项再试算')
    compiled: list[tuple[PlanItemParam, str, str]] = []
    item_errors: list[str] = []
    for index, item in enumerate(items):
        result = validate_item(item.stage, item.condition_json, item.formula_json)
        if not result.ok:
            item_errors.extend([f'第 {index + 1} 项 {msg}' for msg in result.errors])
            continue
        compiled.append((item, result.condition_expr, result.formula_expr))
    if item_errors:
        raise errors.RequestError(msg='；'.join(item_errors))
    assert_accrued_items_last([
        {
            'name': item.name,
            'stage': item.stage,
            'sort_order': item.sort_order,
            'enabled': item.enabled,
            'condition_json': item.condition_json,
            'formula_json': item.formula_json,
            'condition_expr': condition_expr,
            'formula_expr': formula_expr,
        }
        for item, condition_expr, formula_expr in compiled
    ])
    return compiled


async def load_trial_subjects(db: AsyncSession, subject_ids: set[int]) -> dict[int, RiderSalarySubject]:
    """按 ID 读取未删除科目。"""
    if not subject_ids:
        return {}
    rows = await db.scalars(
        select(RiderSalarySubject).where(
            RiderSalarySubject.id.in_(subject_ids),
            RiderSalarySubject.deleted == 0,
        )
    )
    return {row.id: row for row in rows.all()}


def unsaved_item_views(
    compiled: list[tuple[PlanItemParam, str, str]],
    subjects: dict[int, RiderSalarySubject],
) -> list[PlanItemView]:
    """把编译结果收成内存方案项。缺科目时拒绝，不用默认方向冒充 0 元。"""
    views: list[PlanItemView] = []
    for index, (item, condition_expr, formula_expr) in enumerate(compiled):
        subject = subjects.get(item.subject_id)
        if subject is None:
            raise errors.RequestError(msg=f'第 {index + 1} 项科目不存在')
        views.append(
            PlanItemView(
                id=None,
                subject_id=item.subject_id,
                name=item.name,
                stage=str(item.stage),
                sort_order=item.sort_order,
                condition_json=item.condition_json,
                formula_json=item.formula_json,
                condition_expr=condition_expr,
                formula_expr=formula_expr,
                enabled=item.enabled,
                direction=subject.direction,
                include_in_gross=bool(subject.include_in_gross),
            )
        )
    return views


async def count_trial_orders(db: AsyncSession, rider: RiderSalaryRider, start: date, end: date) -> int:
    """统计试算区间内的订单数，用于上限校验。"""
    counted = await db.scalar(
        select(func.count())
        .select_from(RiderSalaryOrder)
        .where(
            RiderSalaryOrder.rider_id == rider.id,
            RiderSalaryOrder.site_id == rider.site_id,
            RiderSalaryOrder.biz_date >= start,
            RiderSalaryOrder.biz_date <= end,
            RiderSalaryOrder.deleted == 0,
        )
    )
    return int(counted or 0)


async def load_unsaved_trial_input(
    db: AsyncSession,
    *,
    rider: RiderSalaryRider,
    start: date,
    end: date,
    items: list[PlanItemView],
) -> CalcInput:
    """组装试算入参。方案段来自请求体，订单和奖惩只读。"""
    segment = Segment(
        plan_version_id=UNSAVED_PLAN_VERSION_ID,
        start_date=start,
        end_date=end,
        items=items,
    )
    orders = list(
        (
            await db.scalars(
                select(RiderSalaryOrder).where(
                    RiderSalaryOrder.rider_id == rider.id,
                    RiderSalaryOrder.site_id == rider.site_id,
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                )
            )
        ).all()
    )
    flags = list(
        (
            await db.scalars(
                select(RiderSalaryDayFlag).where(
                    RiderSalaryDayFlag.site_id == rider.site_id,
                    RiderSalaryDayFlag.biz_date >= start,
                    RiderSalaryDayFlag.biz_date <= end,
                    RiderSalaryDayFlag.deleted == 0,
                )
            )
        ).all()
    )
    history = list(
        (
            await db.scalars(
                select(RiderSalaryRiderEmployHistory).where(
                    RiderSalaryRiderEmployHistory.rider_id == rider.id,
                    RiderSalaryRiderEmployHistory.deleted == 0,
                )
            )
        ).all()
    )
    adjustments = list(
        (
            await db.scalars(
                select(RiderSalaryAdjustment).where(
                    RiderSalaryAdjustment.rider_id == rider.id,
                    RiderSalaryAdjustment.site_id == rider.site_id,
                    RiderSalaryAdjustment.biz_date >= start,
                    RiderSalaryAdjustment.biz_date <= end,
                    RiderSalaryAdjustment.deleted == 0,
                )
            )
        ).all()
    )
    await _attach_adjustment_subjects(db, adjustments)
    covered, site_dates = await _trial_coverage(db, rider.site_id, start, end)
    advances = await payroll_service.load_paid_advances(db, rider.id, for_update=False)
    return CalcInput(
        rider_id=rider.id,
        site_id=rider.site_id,
        period_start=start,
        period_end=end,
        hire_date=rider.hire_date,
        leave_date=rider.leave_date,
        employ_type=rider.employ_type,
        segments=[segment],
        orders=orders,
        day_flags={row.biz_date: row for row in flags},
        employ_history=history,
        adjustments=adjustments,
        advances=advances,
        covered_dates=covered,
        site_order_dates=site_dates,
        persist_advance=False,
        period_id=None,
        rider_job_no=rider.job_no or '',
        rider_name=rider.name or '',
    )


async def _attach_adjustment_subjects(db: AsyncSession, adjustments: list[RiderSalaryAdjustment]) -> None:
    """给奖惩挂上科目方向。带符号金额只改内存，不回写列。"""
    subject_ids = {row.subject_id for row in adjustments}
    subjects = await load_trial_subjects(db, subject_ids)
    for adj in adjustments:
        subject = subjects.get(adj.subject_id)
        adj.subject = subject
        if subject is None:
            continue
        adj.direction = subject.direction
        adj.include_in_gross = subject.include_in_gross
        if adj.signed_amount is None:
            amount = q2(adj.amount)
            derived = amount if subject.direction == SubjectDirection.bonus.value else q2(-amount)
            set_committed_value(adj, 'signed_amount', derived)


async def _trial_coverage(db: AsyncSession, site_id: int, start: date, end: date) -> tuple[set[date], set[date]]:
    """导入批次覆盖日，以及站点在区间内有订单的日期。"""
    batches = list(
        (
            await db.scalars(
                select(RiderSalaryImportBatch).where(
                    RiderSalaryImportBatch.site_id == site_id,
                    RiderSalaryImportBatch.deleted == 0,
                )
            )
        ).all()
    )
    covered: set[date] = set()
    for batch in batches:
        if batch.date_from is None or batch.date_to is None:
            continue
        covered.update(iter_dates(max(batch.date_from, start), min(batch.date_to, end)))
    site_dates = set(
        (
            await db.scalars(
                select(RiderSalaryOrder.biz_date).where(
                    RiderSalaryOrder.site_id == site_id,
                    RiderSalaryOrder.biz_date >= start,
                    RiderSalaryOrder.biz_date <= end,
                    RiderSalaryOrder.deleted == 0,
                )
            )
        ).all()
    )
    return covered, site_dates


def build_trial_result(calc: CalcResult, trial_hash: str | None, *, passed: bool = True) -> TrialResult:
    """将 CalcResult 转为试算接口结构"""
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
        passed=passed,
        trial_hash=trial_hash,
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
        try:
            plan = await plan_dao.create(db, obj)
            await db.flush()
        except IntegrityError as exc:
            raise client_error_from_integrity(exc) from exc
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='创建方案',
            target_type='plan',
            target_id=plan.id,
            target_label=f'方案{plan.code}/{plan.name}',
            before=None,
            after=snapshot(plan, _PLAN_FIELDS),
        )
        return plan

    @staticmethod
    async def update_plan(db: AsyncSession, pk: int, obj: UpdatePlanParam, request: Request) -> int:
        """更新方案"""
        plan = await PlanService.get_plan(db, pk)
        before = snapshot(plan, _PLAN_FIELDS)
        if obj.code and obj.code != plan.code:
            exists = await plan_dao.get_by_code(db, obj.code)
            if exists is not None:
                raise errors.ConflictError(msg='方案编码已存在')
        try:
            count = await plan_dao.update(db, pk, obj)
            await db.flush()
        except IntegrityError as exc:
            raise client_error_from_integrity(exc) from exc
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='修改方案',
            target_type='plan',
            target_id=pk,
            target_label=f'方案{plan.code}',
            before=before,
            after=_patched_snapshot(before, obj, _PLAN_FIELDS),
        )
        return count

    @staticmethod
    async def delete_plan(db: AsyncSession, pk: int, request: Request) -> int:
        """删除方案：无版本或全部为未使用草稿"""
        plan = await PlanService.get_plan(db, pk)
        before = snapshot(plan, _PLAN_FIELDS)
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
            before=before,
            after=_deleted_after(before, pk),
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
        """启用版本下拉。方案按 ID 一次取出，不再逐个查询。"""
        versions = await plan_version_dao.get_active_list(db)
        plan_ids = list(dict.fromkeys(version.plan_id for version in versions))
        plan_map: dict[int, RiderSalaryPlan] = {}
        if plan_ids:
            plans = (
                await db.scalars(
                    select(RiderSalaryPlan).where(
                        RiderSalaryPlan.id.in_(plan_ids),
                        RiderSalaryPlan.deleted == 0,
                    )
                )
            ).all()
            plan_map = {item.id: item for item in plans}
        result: list[GetActivePlanVersion] = []
        for version in versions:
            plan = plan_map.get(version.plan_id)
            if plan is None or not plan_accepts_new_binding(plan):
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
        try:
            version = await plan_version_dao.create(db, obj, version_no)
            await db.flush()
        except IntegrityError as exc:
            raise client_error_from_integrity(exc) from exc
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='创建方案版本',
            target_type='plan_version',
            target_id=version.id,
            target_label=f'方案{plan.name} v{version_no}',
            before=None,
            after=snapshot(version, _VERSION_FIELDS),
        )
        return version

    @staticmethod
    async def update_version(db: AsyncSession, pk: int, obj: UpdatePlanVersionParam, request: Request) -> int:
        """更新版本基本信息"""
        version = await PlanService.get_version_model(db, pk)
        assert_version_editable(version)
        before = snapshot(version, _VERSION_FIELDS)
        count = await plan_version_dao.update(db, pk, obj)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='修改方案版本',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案版本{pk}',
            before=before,
            after=_patched_snapshot(before, obj, _VERSION_FIELDS),
        )
        return count

    @staticmethod
    async def delete_version(db: AsyncSession, pk: int, request: Request) -> int:
        """删除未使用草稿版本"""
        version = await PlanService.get_version_model(db, pk)
        assert_version_editable(version)
        before = snapshot(version, _VERSION_FIELDS)
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
            before=before,
            after=_deleted_after(before, pk),
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
                item_errors.extend([f'第 {index + 1} 项 {msg}' for msg in result.errors])
            compiled.append((item, result.condition_expr, result.formula_expr))
        if item_errors:
            raise errors.RequestError(msg='；'.join(item_errors))
        assert_accrued_items_last([
            {
                'name': item.name,
                'stage': item.stage,
                'sort_order': item.sort_order,
                'enabled': item.enabled,
                'condition_json': item.condition_json,
                'formula_json': item.formula_json,
                'condition_expr': condition_expr,
                'formula_expr': formula_expr,
            }
            for item, condition_expr, formula_expr in compiled
        ])
        await assert_plan_item_subjects(db, items)
        old_items = await plan_item_dao.list_by_version(db, pk)
        before = {
            'items_hash': version.items_hash,
            'count': len(old_items),
            'items': [snapshot(item, _ITEM_FIELDS) for item in old_items],
        }
        await plan_item_dao.logical_delete_by_version(db, pk)
        created_rows = []
        for item, condition_expr, formula_expr in compiled:
            created_rows.append(
                await plan_item_dao.create(
                    db,
                    pk,
                    item,
                    condition_expr=condition_expr,
                    formula_expr=formula_expr,
                )
            )
        new_hash = items_hash_of([item.model_dump() for item, _c, _f in compiled])
        if version.items_hash != new_hash:
            version.trial_passed = False
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
            before=before,
            after={
                'items_hash': new_hash,
                'count': len(created_rows),
                'items': [snapshot(row, _ITEM_FIELDS) for row in created_rows],
            },
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
    ) -> TrialResult:
        """试算。先校验骑手所属站点可见；仅未使用的草稿回写试算哈希和快照。"""
        version = await PlanService.get_version_model(db, pk)
        rider = await rider_dao.get(db, rider_id)
        if rider is None:
            raise errors.NotFoundError(msg='骑手不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, rider.site_id)
        items = await plan_item_dao.list_by_version(db, pk)
        if not items:
            raise errors.RequestError(msg='请先配置方案项再试算')
        calc = await trial_rider_range(
            db, rider_id=rider_id, start=start_date, end=end_date, forced_plan_version=version
        )
        if int(calc.valid_order_count or 0) < 1:
            raise errors.RequestError(msg='试算至少需要 1 笔已完成订单')
        current_hash = items_hash_of(orm_items_as_dicts(items))
        failures = [item for item in calc.warnings if is_eval_failure_warning(item)]
        passed = not failures
        result = build_trial_result(calc, current_hash if passed else version.trial_hash, passed=passed)
        before = snapshot(version, _VERSION_FIELDS)
        if version.status == PlanVersionStatus.draft.value and not version.is_used:
            version.items_hash = current_hash
            if passed:
                version.trial_hash = current_hash
                version.trial_passed = True
                version.trial_snapshot = result.summary.model_dump(mode='json')
            else:
                version.trial_passed = False
            await db.flush()
        plan = await plan_dao.get(db, version.plan_id)
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='试算方案',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案{plan.name if plan else pk} v{version.version_no}',
            before=before,
            after=snapshot(version, _VERSION_FIELDS),
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
        if version.status != PlanVersionStatus.active.value:
            assert_accrued_items_last(items)
            await assert_plan_item_subjects(db, items)
        current_hash = items_hash_of(orm_items_as_dicts(items))
        version.items_hash = current_hash
        if not version.trial_passed:
            raise errors.RequestError(msg='请先完成试算再启用')
        if version.trial_hash != current_hash:
            raise errors.RequestError(msg='方案内容已变更，请重新试算')
        plan = await plan_dao.get(db, version.plan_id)
        if plan is None:
            raise errors.NotFoundError(msg='方案不存在')
        assert_plan_can_activate(plan)
        before = snapshot(version, _VERSION_FIELDS)
        version.status = PlanVersionStatus.active.value
        version.activated_time = timezone.now()
        await db.flush()
        await audit_service.record(
            db,
            request,
            module='薪资方案',
            action='启用方案',
            target_type='plan_version',
            target_id=pk,
            target_label=f'方案{plan.name if plan else pk} v{version.version_no}',
            before=before,
            after=snapshot(version, _VERSION_FIELDS),
        )

    @staticmethod
    async def disable(db: AsyncSession, pk: int, obj: DisablePlanVersionParam, request: Request) -> None:
        """停用版本"""
        version = await PlanService.get_version_model(db, pk)
        if version.status != PlanVersionStatus.active.value:
            raise errors.RequestError(msg='仅启用中的版本可以停用')
        before = snapshot(version, _VERSION_FIELDS)
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
            before=before,
            after=snapshot(version, _VERSION_FIELDS),
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
            before=None,
            after=snapshot(copied, _VERSION_FIELDS),
        )
        return copied

    @staticmethod
    async def trial_unsaved(db: AsyncSession, obj: TrialUnsavedPlanParam, request: Request) -> TrialResult:
        """试算未保存草稿。在内存中构造方案段并计算，不写试算哈希、试算快照和方案版本。"""
        if obj.start_date > obj.end_date:
            raise errors.RequestError(msg='结束日期不能早于开始日期')
        rider = await rider_dao.get(db, obj.rider_id)
        if rider is None:
            raise errors.NotFoundError(msg='骑手不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, rider.site_id)
        compiled = compile_unsaved_items(obj.items)
        subjects = await load_trial_subjects(db, {item.subject_id for item, _cond, _formula in compiled})
        views = unsaved_item_views(compiled, subjects)
        order_count = await count_trial_orders(db, rider, obj.start_date, obj.end_date)
        if order_count > trial_max_orders():
            raise errors.RequestError(msg=f'试算订单数超过上限 {trial_max_orders()}')
        data = await load_unsaved_trial_input(
            db,
            rider=rider,
            start=obj.start_date,
            end=obj.end_date,
            items=views,
        )
        calc = run_calc_pipeline(data)
        if int(calc.valid_order_count or 0) < 1:
            raise errors.RequestError(msg='试算至少需要 1 笔已完成订单')
        failures = [item for item in calc.warnings if is_eval_failure_warning(item)]
        passed = not failures
        current_hash = items_hash_of([item.model_dump() for item, _cond, _formula in compiled])
        return build_trial_result(calc, current_hash if passed else None, passed=passed)


plan_service = PlanService()
