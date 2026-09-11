from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession
from backend.plugin.rider_salary.schema.payroll import GetPayrollDetailItem, GetPayrollGroupedDetail, GetPayrollSummary
from backend.plugin.rider_salary.service.payroll_service import payroll_service

router = APIRouter()


@router.get(
    '',
    summary='分页获取薪资结果',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        Depends(RequestPermission('rs:payroll:view')),
        DependsRBAC,
    ],
)
async def get_payrolls_paginated(
    db: CurrentSession,
    request: Request,
    period_id: Annotated[int | None, Query(description='周期 ID')] = None,
    rider_id: Annotated[int | None, Query(description='骑手 ID')] = None,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    kind: Annotated[str | None, Query(description='类型')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
    stale: Annotated[bool | None, Query(description='需重算')] = None,
) -> ResponseSchemaModel[PageData[GetPayrollSummary]]:
    data = await payroll_service.get_list(
        db,
        request,
        period_id=period_id,
        rider_id=rider_id,
        site_id=site_id,
        kind=kind,
        status=status,
        stale=stale,
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}/details',
    summary='分页获取薪资明细',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        Depends(RequestPermission('rs:payroll:view')),
        DependsRBAC,
    ],
)
async def get_payroll_details(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='薪资单 ID')],
    biz_date: Annotated[str | None, Query(description='业务日期')] = None,
    stage: Annotated[str | None, Query(description='计算阶段')] = None,
    subject_id: Annotated[int | None, Query(description='科目 ID')] = None,
    order_id: Annotated[int | None, Query(description='订单 ID')] = None,
) -> ResponseSchemaModel[PageData[GetPayrollDetailItem]]:
    data = await payroll_service.get_details_page(
        db,
        request,
        pk,
        biz_date=biz_date,
        stage=stage,
        subject_id=subject_id,
        order_id=order_id,
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取薪资单详情',
    description='汇总 + 明细按阶段分组 + 日汇总',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:payroll:view')),
        DependsRBAC,
    ],
)
async def get_payroll(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='薪资单 ID')],
) -> ResponseSchemaModel[GetPayrollGroupedDetail]:
    data = await payroll_service.get_grouped(db, request, pk)
    return response_base.success(data=data)
