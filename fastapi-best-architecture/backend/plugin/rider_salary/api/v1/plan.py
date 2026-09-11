from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.plan import (
    CreatePlanParam,
    CreatePlanVersionParam,
    DisablePlanVersionParam,
    GetActivePlanVersion,
    GetPlanDetail,
    UpdatePlanParam,
    UpdatePlanVersionParam,
)
from backend.plugin.rider_salary.schema.plan_item import GetPlanVersionDetail, PlanItemParam, TrialPlanVersionParam
from backend.plugin.rider_salary.schema.rollback import RollbackParam, RollbackPreviewResult
from backend.plugin.rider_salary.schema.trial import TrialResult
from backend.plugin.rider_salary.service.plan_service import plan_service
from backend.plugin.rider_salary.service.rollback_service import rollback_service

router = APIRouter()
version_router = APIRouter()


@router.get(
    '',
    summary='分页获取薪资方案',
    dependencies=[DependsJwtAuth, DependsRBAC, DependsPagination],
)
async def get_plans_paginated(
    db: CurrentSession,
    name: Annotated[str | None, Query(description='方案名称')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
) -> ResponseSchemaModel[PageData[GetPlanDetail]]:
    data = await plan_service.get_plan_list(db, name, status)
    return response_base.success(data=data)


@router.get('/{pk}', summary='获取方案详情', dependencies=[DependsJwtAuth, DependsRBAC])
async def get_plan(
    db: CurrentSession,
    pk: Annotated[int, Path(description='方案 ID')],
) -> ResponseSchemaModel[GetPlanDetail]:
    plan = await plan_service.get_plan(db, pk)
    return response_base.success(data=plan)


@router.post(
    '',
    summary='创建方案',
    dependencies=[Depends(RequestPermission('rs:plan:add')), DependsRBAC],
)
async def create_plan(
    db: CurrentSessionTransaction, request: Request, obj: CreatePlanParam
) -> ResponseSchemaModel[GetPlanDetail]:
    plan = await plan_service.create_plan(db, obj, request)
    return response_base.success(data=GetPlanDetail.model_validate(plan))


@router.put(
    '/{pk}',
    summary='更新方案',
    dependencies=[Depends(RequestPermission('rs:plan:edit')), DependsRBAC],
)
async def update_plan(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='方案 ID')],
    obj: UpdatePlanParam,
) -> ResponseModel:
    count = await plan_service.update_plan(db, pk, obj, request)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除方案',
    dependencies=[Depends(RequestPermission('rs:plan:del')), DependsRBAC],
)
async def delete_plan(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='方案 ID')],
) -> ResponseModel:
    count = await plan_service.delete_plan(db, pk, request)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@version_router.get('/active', summary='启用方案版本下拉', dependencies=[DependsJwtAuth, DependsRBAC])
async def get_active_plan_versions(db: CurrentSession) -> ResponseSchemaModel[list[GetActivePlanVersion]]:
    data = await plan_service.get_active_dropdown(db)
    return response_base.success(data=data)


@version_router.get(
    '',
    summary='分页获取方案版本',
    dependencies=[DependsJwtAuth, DependsRBAC, DependsPagination],
)
async def get_plan_versions_paginated(
    db: CurrentSession,
    plan_id: Annotated[int | None, Query(description='方案 ID')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
) -> ResponseSchemaModel[PageData[GetPlanVersionDetail]]:
    data = await plan_service.get_version_list(db, plan_id, status)
    return response_base.success(data=data)


@version_router.post(
    '',
    summary='创建方案版本草稿',
    dependencies=[Depends(RequestPermission('rs:plan:add')), DependsRBAC],
)
async def create_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    obj: CreatePlanVersionParam,
) -> ResponseSchemaModel[GetPlanVersionDetail]:
    version = await plan_service.create_version(db, obj, request)
    data = await plan_service.get_version(db, version.id)
    return response_base.success(data=data)


@version_router.get('/{pk}', summary='获取方案版本详情', dependencies=[DependsJwtAuth, DependsRBAC])
async def get_plan_version(
    db: CurrentSession,
    pk: Annotated[int, Path(description='版本 ID')],
) -> ResponseSchemaModel[GetPlanVersionDetail]:
    data = await plan_service.get_version(db, pk)
    return response_base.success(data=data)


@version_router.put(
    '/{pk}',
    summary='更新方案版本基本信息',
    dependencies=[Depends(RequestPermission('rs:plan:edit')), DependsRBAC],
)
async def update_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
    obj: UpdatePlanVersionParam,
) -> ResponseModel:
    count = await plan_service.update_version(db, pk, obj, request)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@version_router.delete(
    '/{pk}',
    summary='删除方案版本',
    dependencies=[Depends(RequestPermission('rs:plan:del')), DependsRBAC],
)
async def delete_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
) -> ResponseModel:
    count = await plan_service.delete_version(db, pk, request)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@version_router.put(
    '/{pk}/items',
    summary='全量覆盖方案项',
    dependencies=[Depends(RequestPermission('rs:plan:edit')), DependsRBAC],
)
async def put_plan_version_items(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
    items: list[PlanItemParam],
) -> ResponseSchemaModel[GetPlanVersionDetail]:
    data = await plan_service.replace_items(db, pk, items, request)
    return response_base.success(data=data)


@version_router.post(
    '/{pk}/trial',
    summary='试算方案版本',
    dependencies=[Depends(RequestPermission('rs:plan:trial')), DependsRBAC],
)
async def trial_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
    obj: TrialPlanVersionParam,
) -> ResponseSchemaModel[TrialResult]:
    data = await plan_service.trial(db, pk, obj.rider_id, obj.start_date, obj.end_date, request)
    return response_base.success(data=data)


@version_router.post(
    '/{pk}/activate',
    summary='启用方案版本',
    dependencies=[Depends(RequestPermission('rs:plan:activate')), DependsRBAC],
)
async def activate_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
) -> ResponseModel:
    await plan_service.activate(db, pk, request)
    return response_base.success()


@version_router.post(
    '/{pk}/disable',
    summary='停用方案版本',
    dependencies=[Depends(RequestPermission('rs:plan:disable')), DependsRBAC],
)
async def disable_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
    obj: DisablePlanVersionParam,
) -> ResponseModel:
    await plan_service.disable(db, pk, obj, request)
    return response_base.success()


@version_router.post(
    '/{pk}/copy',
    summary='复制为新草稿版本',
    dependencies=[Depends(RequestPermission('rs:plan:copy')), DependsRBAC],
)
async def copy_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
) -> ResponseSchemaModel[GetPlanVersionDetail]:
    copied = await plan_service.copy(db, pk, request)
    data = await plan_service.get_version(db, copied.id)
    return response_base.success(data=data)


@version_router.get(
    '/{pk}/rollback-preview',
    summary='方案回退预览',
    dependencies=[Depends(RequestPermission('rs:plan:rollback')), DependsRBAC],
)
async def rollback_preview(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
) -> ResponseSchemaModel[RollbackPreviewResult]:
    data = await rollback_service.preview(db, pk, request)
    return response_base.success(data=data)


@version_router.post(
    '/{pk}/rollback',
    summary='执行方案回退',
    dependencies=[Depends(RequestPermission('rs:plan:rollback')), DependsRBAC],
)
async def rollback_plan_version(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='版本 ID')],
    obj: RollbackParam,
) -> ResponseSchemaModel[GetPlanVersionDetail]:
    copied = await rollback_service.rollback(db, pk, obj, request)
    data = await plan_service.get_version(db, copied.id)
    return response_base.success(data=data)
