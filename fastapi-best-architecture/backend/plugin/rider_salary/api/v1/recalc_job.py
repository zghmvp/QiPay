from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.recalc_job import (
    GetLatestRecalcJobResult,
    GetRecalcJobDetail,
)
from backend.plugin.rider_salary.service.recalc_job_service import recalc_job_service

router = APIRouter()

_JOB_DEPS = [
    DependsJwtAuth,
    Depends(RequestPermission('rs:period:calculate')),
    DependsRBAC,
]


@router.get(
    '/latest',
    summary='获取本站最近一条重算任务',
    dependencies=_JOB_DEPS,
)
async def get_latest_recalc_job(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int, Query(description='站点 ID')],
    source: Annotated[str | None, Query(description='来源：import_batch / stale_batch，缺省为全部')] = None,
) -> ResponseSchemaModel[GetLatestRecalcJobResult]:
    data = await recalc_job_service.get_latest(db=db, request=request, site_id=site_id, source=source)
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取重算任务状态',
    dependencies=_JOB_DEPS,
)
async def get_recalc_job(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='任务 ID')],
) -> ResponseSchemaModel[GetRecalcJobDetail]:
    data = await recalc_job_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/retry',
    summary='重试失败的重算任务',
    dependencies=_JOB_DEPS,
)
async def retry_recalc_job(
    db: CurrentSessionTransaction,
    request: Request,
    background_tasks: BackgroundTasks,
    pk: Annotated[int, Path(description='任务 ID')],
) -> ResponseSchemaModel[GetRecalcJobDetail]:
    data = await recalc_job_service.retry(db=db, request=request, pk=pk, background_tasks=background_tasks)
    return response_base.success(data=data)
