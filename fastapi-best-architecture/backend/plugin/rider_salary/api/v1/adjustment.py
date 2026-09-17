from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_code import CustomResponse
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.adjustment import (
    BatchCreateAdjustmentParam,
    BatchCreateAdjustmentResult,
    CreateAdjustmentParam,
    DeleteAdjustmentParam,
    GetAdjustmentDetail,
    UpdateAdjustmentParam,
)
from backend.plugin.rider_salary.service.adjustment_service import adjustment_service

router = APIRouter()


@router.get(
    '',
    summary='分页获取奖惩记录',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        Depends(RequestPermission('rs:adjustment:add')),
        DependsRBAC,
    ],
)
async def get_adjustments_paginated(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    rider_id: Annotated[int | None, Query(description='骑手 ID')] = None,
    subject_id: Annotated[int | None, Query(description='科目 ID')] = None,
    date_from: Annotated[date | None, Query(description='开始日期')] = None,
    date_to: Annotated[date | None, Query(description='结束日期')] = None,
    direction: Annotated[str | None, Query(description='方向')] = None,
) -> ResponseSchemaModel[PageData[GetAdjustmentDetail]]:
    page_data = await adjustment_service.get_list(
        db=db,
        request=request,
        site_id=site_id,
        rider_id=rider_id,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
        direction=direction,
    )
    return response_base.success(data=page_data)


@router.post(
    '/batch',
    summary='批量录入奖惩',
    dependencies=[
        Depends(RequestPermission('rs:adjustment:add')),
        DependsRBAC,
    ],
)
async def create_adjustments_batch(
    db: CurrentSessionTransaction,
    request: Request,
    obj: BatchCreateAdjustmentParam,
) -> ResponseSchemaModel[BatchCreateAdjustmentResult]:
    data = await adjustment_service.create_batch(db=db, request=request, items=obj.items)
    return response_base.success(res=CustomResponse(code=200, msg=data.message), data=data)


@router.get(
    '/{pk}',
    summary='获取奖惩记录详情',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:adjustment:add')),
        DependsRBAC,
    ],
)
async def get_adjustment(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='奖惩记录 ID')],
) -> ResponseSchemaModel[GetAdjustmentDetail]:
    data = await adjustment_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '',
    summary='录入奖惩',
    dependencies=[
        Depends(RequestPermission('rs:adjustment:add')),
        DependsRBAC,
    ],
)
async def create_adjustment(
    db: CurrentSessionTransaction,
    request: Request,
    obj: CreateAdjustmentParam,
) -> ResponseSchemaModel[GetAdjustmentDetail]:
    data = await adjustment_service.create(db=db, request=request, obj=obj)
    return response_base.success(data=data)


@router.put(
    '/{pk}',
    summary='修改奖惩',
    dependencies=[
        Depends(RequestPermission('rs:adjustment:edit')),
        DependsRBAC,
    ],
)
async def update_adjustment(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='奖惩记录 ID')],
    obj: UpdateAdjustmentParam,
) -> ResponseModel:
    count = await adjustment_service.update(db=db, request=request, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除奖惩',
    dependencies=[
        Depends(RequestPermission('rs:adjustment:del')),
        DependsRBAC,
    ],
)
async def delete_adjustment(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='奖惩记录 ID')],
    obj: DeleteAdjustmentParam,
) -> ResponseModel:
    count = await adjustment_service.delete(db=db, request=request, pk=pk, reason=obj.reason)
    if count > 0:
        return response_base.success()
    return response_base.fail()
