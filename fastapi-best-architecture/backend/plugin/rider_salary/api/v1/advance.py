from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import StreamingResponse

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.advance import (
    AdvanceActionParam,
    AdvanceReasonParam,
    GetAdvanceDetail,
    GetAdvanceMonthlyQuota,
)
from backend.plugin.rider_salary.service.advance_service import advance_service

router = APIRouter()


@router.get(
    '/export',
    summary='导出预支明细',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:advance:export')),
        DependsRBAC,
    ],
)
async def export_advances(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
    date_from: Annotated[date | None, Query(description='申请日起')] = None,
    date_to: Annotated[date | None, Query(description='申请日止')] = None,
) -> StreamingResponse:
    content = await advance_service.export(
        db=db,
        request=request,
        site_id=site_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    filename = '预支明细.xlsx'
    return StreamingResponse(
        iter([content]),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get(
    '/quota',
    summary='获取骑手本月预支次数',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:advance:approve')),
        DependsRBAC,
    ],
)
async def get_advance_quota(
    db: CurrentSession,
    request: Request,
    rider_id: Annotated[int, Query(description='骑手 ID')],
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
) -> ResponseSchemaModel[GetAdvanceMonthlyQuota]:
    data = await advance_service.quota_for_admin(db=db, request=request, rider_id=rider_id, site_id=site_id)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取预支单',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        Depends(RequestPermission('rs:advance:approve')),
        DependsRBAC,
    ],
)
async def get_advances_paginated(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    rider_id: Annotated[int | None, Query(description='骑手 ID')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
    date_from: Annotated[date | None, Query(description='申请日起')] = None,
    date_to: Annotated[date | None, Query(description='申请日止')] = None,
    id: Annotated[int | None, Query(description='预支单 ID')] = None,
) -> ResponseSchemaModel[PageData[GetAdvanceDetail]]:
    page_data = await advance_service.get_list(
        db=db,
        request=request,
        site_id=site_id,
        rider_id=rider_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        pk=id,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取预支单详情',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:advance:approve')),
        DependsRBAC,
    ],
)
async def get_advance(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='预支单 ID')],
) -> ResponseSchemaModel[GetAdvanceDetail]:
    data = await advance_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/approve',
    summary='审核通过预支',
    dependencies=[
        Depends(RequestPermission('rs:advance:approve')),
        DependsRBAC,
    ],
)
async def approve_advance(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='预支单 ID')],
    obj: AdvanceActionParam,
) -> ResponseModel:
    await advance_service.approve(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.post(
    '/{pk}/reject',
    summary='驳回预支',
    dependencies=[
        Depends(RequestPermission('rs:advance:reject')),
        DependsRBAC,
    ],
)
async def reject_advance(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='预支单 ID')],
    obj: AdvanceReasonParam,
) -> ResponseModel:
    await advance_service.reject(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.post(
    '/{pk}/mark-paid',
    summary='标记预支已发放',
    dependencies=[
        Depends(RequestPermission('rs:advance:mark-paid')),
        DependsRBAC,
    ],
)
async def mark_paid_advance(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='预支单 ID')],
    obj: AdvanceActionParam,
) -> ResponseModel:
    await advance_service.mark_paid(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.post(
    '/{pk}/cancel',
    summary='取消待发放预支',
    dependencies=[
        Depends(RequestPermission('rs:advance:cancel')),
        DependsRBAC,
    ],
)
async def cancel_advance(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='预支单 ID')],
    obj: AdvanceReasonParam,
) -> ResponseModel:
    await advance_service.cancel(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()
