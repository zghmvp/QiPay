from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.dashboard import GetDashboardSummary
from backend.plugin.rider_salary.schema.recalc_job import (
    BatchRecalcStaleParam,
    BatchRecalcStalePreview,
    BatchRecalcStaleResult,
)
from backend.plugin.rider_salary.service.dashboard_service import dashboard_service
from backend.plugin.rider_salary.service.recalc_job_service import recalc_job_service

router = APIRouter()


@router.get(
    '/summary',
    summary='获取工作台汇总',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:dashboard:view')),
        DependsRBAC,
    ],
)
async def get_dashboard_summary(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int | None, Query(description='站点 ID，空表示全部可见站点')] = None,
    month: Annotated[str | None, Query(description='月份，格式 YYYY-MM')] = None,
) -> ResponseSchemaModel[GetDashboardSummary]:
    data = await dashboard_service.summary(db=db, request=request, site_id=site_id, month=month)
    return response_base.success(data=data)


@router.post(
    '/stale-batch/preview',
    summary='预览本站本月 stale 批量重算',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:period:calculate')),
        DependsRBAC,
    ],
)
async def preview_stale_batch_recalc(
    db: CurrentSession,
    request: Request,
    obj: BatchRecalcStaleParam,
) -> ResponseSchemaModel[BatchRecalcStalePreview]:
    data = await recalc_job_service.preview_stale_batch(db=db, request=request, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/stale-batch',
    summary='本站本月 stale 批量重算',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:period:calculate')),
        DependsRBAC,
    ],
)
async def submit_stale_batch_recalc(
    db: CurrentSessionTransaction,
    request: Request,
    background_tasks: BackgroundTasks,
    obj: BatchRecalcStaleParam,
) -> ResponseSchemaModel[BatchRecalcStaleResult]:
    data = await recalc_job_service.submit_stale_batch(
        db=db, request=request, obj=obj, background_tasks=background_tasks
    )
    return response_base.success(data=data)
