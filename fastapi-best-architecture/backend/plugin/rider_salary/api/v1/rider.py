from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.period import LeaveSettlementResult
from backend.plugin.rider_salary.schema.rider import (
    BatchBindingResult,
    BatchIssuedPasswordResult,
    BatchOpenAccountParam,
    BatchPlanBindingParam,
    BatchResetPasswordParam,
    CreateEmployHistoryParam,
    CreatePlanBindingParam,
    CreateRiderParam,
    DisableRiderAccountParam,
    EnableRiderAccountParam,
    GetEffectivePlanSegment,
    GetEmployHistoryDetail,
    GetPlanBindingDetail,
    GetRiderDetail,
    IssuedRiderPassword,
    OpenRiderAccountParam,
    ResetRiderPasswordParam,
    RiderLeaveParam,
    RiderLeaveResult,
    UpdateEmployHistoryParam,
    UpdatePlanBindingParam,
    UpdateRiderParam,
)
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.service.rider_service import rider_service
from backend.plugin.rider_salary.utils.permission import RequestAnyPermission

router = APIRouter()


@router.get(
    '',
    summary='分页获取骑手',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        Depends(RequestAnyPermission('rs:rider:view', 'rs:rider:add')),
        DependsRBAC,
    ],
)
async def get_riders_paginated(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
    employ_type: Annotated[str | None, Query(description='用工类型')] = None,
    keyword: Annotated[str | None, Query(description='工号或姓名')] = None,
) -> ResponseSchemaModel[PageData[GetRiderDetail]]:
    page_data = await rider_service.get_list(
        db=db,
        request=request,
        site_id=site_id,
        status=status,
        employ_type=employ_type,
        keyword=keyword,
    )
    return response_base.success(data=page_data)


@router.post(
    '',
    summary='创建骑手',
    dependencies=[
        Depends(RequestPermission('rs:rider:add')),
        DependsRBAC,
    ],
)
async def create_rider(db: CurrentSessionTransaction, request: Request, obj: CreateRiderParam) -> ResponseModel:
    await rider_service.create(db=db, request=request, obj=obj)
    return response_base.success()


@router.post(
    '/batch/bindings',
    summary='批量绑定方案',
    description='一次为多名骑手绑定同一方案。每人单独校验锁账、标记重算并写审计；任一失败则整单回滚。',
    dependencies=[
        Depends(RequestPermission('rs:rider:binding')),
        DependsRBAC,
    ],
)
async def create_bindings_batch(
    db: CurrentSessionTransaction,
    request: Request,
    obj: BatchPlanBindingParam,
) -> ResponseSchemaModel[BatchBindingResult]:
    data = await rider_service.create_bindings_batch(db=db, request=request, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/batch/open-account',
    summary='批量开通骑手账号',
    description='每人生成独立随机密码，仅本次返回，并要求首次登录修改。不接受统一密码。任一失败则整单回滚。',
    dependencies=[
        Depends(RequestPermission('rs:rider:account')),
        DependsRBAC,
    ],
)
async def open_rider_accounts_batch(
    db: CurrentSessionTransaction,
    request: Request,
    obj: BatchOpenAccountParam,
) -> ResponseSchemaModel[BatchIssuedPasswordResult]:
    data = await rider_service.open_accounts_batch(db=db, request=request, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/batch/reset-password',
    summary='批量重置骑手密码',
    description='每人生成独立随机密码，仅本次返回，并重新要求首次登录修改。不接受统一密码。任一失败则整单回滚。',
    dependencies=[
        Depends(RequestPermission('rs:rider:account')),
        DependsRBAC,
    ],
)
async def reset_rider_passwords_batch(
    db: CurrentSessionTransaction,
    request: Request,
    obj: BatchResetPasswordParam,
) -> ResponseSchemaModel[BatchIssuedPasswordResult]:
    data = await rider_service.reset_passwords_batch(db=db, request=request, obj=obj)
    return response_base.success(data=data)


@router.get(
    '/{pk}/employ-history',
    summary='获取用工类型历史',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestAnyPermission('rs:rider:view', 'rs:rider:employ')),
        DependsRBAC,
    ],
)
async def get_employ_history(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
) -> ResponseSchemaModel[list[GetEmployHistoryDetail]]:
    data = await rider_service.list_employ_history(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/employ-history',
    summary='新增用工类型历史',
    dependencies=[
        Depends(RequestPermission('rs:rider:employ')),
        DependsRBAC,
    ],
)
async def create_employ_history(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: CreateEmployHistoryParam,
) -> ResponseModel:
    await rider_service.create_employ_history(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}/employ-history/{history_id}',
    summary='修改用工类型历史',
    dependencies=[
        Depends(RequestPermission('rs:rider:employ')),
        DependsRBAC,
    ],
)
async def update_employ_history(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    history_id: Annotated[int, Path(description='用工历史 ID')],
    obj: UpdateEmployHistoryParam,
) -> ResponseModel:
    count = await rider_service.update_employ_history(db=db, request=request, pk=pk, history_id=history_id, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}/employ-history/{history_id}',
    summary='删除用工类型历史',
    dependencies=[
        Depends(RequestPermission('rs:rider:employ')),
        DependsRBAC,
    ],
)
async def delete_employ_history(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    history_id: Annotated[int, Path(description='用工历史 ID')],
) -> ResponseModel:
    count = await rider_service.delete_employ_history(db=db, request=request, pk=pk, history_id=history_id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.get(
    '/{pk}/bindings',
    summary='获取方案绑定',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestAnyPermission('rs:rider:view', 'rs:rider:binding')),
        DependsRBAC,
    ],
)
async def get_bindings(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
) -> ResponseSchemaModel[list[GetPlanBindingDetail]]:
    data = await rider_service.list_bindings(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/bindings',
    summary='新增方案绑定',
    dependencies=[
        Depends(RequestPermission('rs:rider:binding')),
        DependsRBAC,
    ],
)
async def create_binding(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: CreatePlanBindingParam,
) -> ResponseModel:
    await rider_service.create_binding(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}/bindings/{binding_id}',
    summary='修改方案绑定',
    dependencies=[
        Depends(RequestPermission('rs:rider:binding')),
        DependsRBAC,
    ],
)
async def update_binding(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    binding_id: Annotated[int, Path(description='绑定 ID')],
    obj: UpdatePlanBindingParam,
) -> ResponseModel:
    count = await rider_service.update_binding(db=db, request=request, pk=pk, binding_id=binding_id, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}/bindings/{binding_id}',
    summary='删除方案绑定',
    dependencies=[
        Depends(RequestPermission('rs:rider:binding')),
        DependsRBAC,
    ],
)
async def delete_binding(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    binding_id: Annotated[int, Path(description='绑定 ID')],
) -> ResponseModel:
    count = await rider_service.delete_binding(db=db, request=request, pk=pk, binding_id=binding_id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.get(
    '/{pk}/effective-plans',
    summary='获取生效方案区间',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestAnyPermission('rs:rider:view', 'rs:rider:binding')),
        DependsRBAC,
    ],
)
async def get_effective_plans(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    start: Annotated[date, Query(description='开始日期')],
    end: Annotated[date, Query(description='结束日期')],
) -> ResponseSchemaModel[list[GetEffectivePlanSegment]]:
    data = await rider_service.get_effective_plans(db=db, request=request, pk=pk, start=start, end=end)
    return response_base.success(data=data)


@router.put(
    '/{pk}/leave',
    summary='骑手离职',
    description='待审核预支自动驳回；待发放预支不自动取消，并在返回提示中说明。离职日所在周期已锁账时拒绝。',
    dependencies=[
        Depends(RequestPermission('rs:rider:edit')),
        DependsRBAC,
    ],
)
async def leave_rider(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: RiderLeaveParam,
) -> ResponseSchemaModel[RiderLeaveResult]:
    data = await rider_service.leave(db=db, request=request, pk=pk, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/{pk}/leave-settlement',
    summary='生成离职结算周期',
    description='为已离职骑手生成骑手级结算周期，可单独算薪、锁账和标记发薪。碰到站点级周期时整段覆盖，结束日可能晚于离职日。重复调用返回已有周期。',
    dependencies=[
        Depends(RequestPermission('rs:period:generate')),
        DependsRBAC,
    ],
)
async def create_leave_settlement(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
) -> ResponseSchemaModel[LeaveSettlementResult]:
    data = await period_service.create_leave_settlement(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/open-account',
    summary='开通骑手账号',
    dependencies=[
        Depends(RequestPermission('rs:rider:account')),
        DependsRBAC,
    ],
)
async def open_rider_account(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: OpenRiderAccountParam,
) -> ResponseSchemaModel[IssuedRiderPassword]:
    data = await rider_service.open_account(db=db, request=request, pk=pk, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/{pk}/reset-password',
    summary='重置骑手密码',
    dependencies=[
        Depends(RequestPermission('rs:rider:account')),
        DependsRBAC,
    ],
)
async def reset_rider_password(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: ResetRiderPasswordParam,
) -> ResponseSchemaModel[IssuedRiderPassword]:
    data = await rider_service.reset_password(db=db, request=request, pk=pk, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/{pk}/disable-account',
    summary='停用骑手账号',
    dependencies=[
        Depends(RequestPermission('rs:rider:account')),
        DependsRBAC,
    ],
)
async def disable_rider_account(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: DisableRiderAccountParam,
) -> ResponseModel:
    await rider_service.disable_account(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.post(
    '/{pk}/enable-account',
    summary='启用骑手账号',
    dependencies=[
        Depends(RequestPermission('rs:rider:account')),
        DependsRBAC,
    ],
)
async def enable_rider_account(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: EnableRiderAccountParam,
) -> ResponseModel:
    await rider_service.enable_account(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.get(
    '/{pk}',
    summary='获取骑手详情',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestAnyPermission('rs:rider:view', 'rs:rider:add')),
        DependsRBAC,
    ],
)
async def get_rider(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
) -> ResponseSchemaModel[GetRiderDetail]:
    data = await rider_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.put(
    '/{pk}',
    summary='更新骑手',
    dependencies=[
        Depends(RequestPermission('rs:rider:edit')),
        DependsRBAC,
    ],
)
async def update_rider(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
    obj: UpdateRiderParam,
) -> ResponseModel:
    count = await rider_service.update(db=db, request=request, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除骑手',
    dependencies=[
        Depends(RequestPermission('rs:rider:del')),
        DependsRBAC,
    ],
)
async def delete_rider(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='骑手 ID')],
) -> ResponseModel:
    count = await rider_service.delete(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()
