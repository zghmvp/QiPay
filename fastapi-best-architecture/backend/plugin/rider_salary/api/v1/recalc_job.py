from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.recalc_job import (
    GetRecalcJobDetail,
)
from backend.plugin.rider_salary.service.recalc_job_service import recalc_job_service

router = APIRouter()


@router.get(
    '/{pk}',
    summary='获取重算任务状态',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:period:calculate')),
        DependsRBAC,
    ],
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
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:period:calculate')),
        DependsRBAC,
    ],
)
async def retry_recalc_job(
    db: CurrentSessionTransaction,
    request: Request,
    background_tasks: BackgroundTasks,
    pk: Annotated[int, Path(description='任务 ID')],
) -> ResponseSchemaModel[GetRecalcJobDetail]:
    data = await recalc_job_service.retry(db=db, request=request, pk=pk, background_tasks=background_tasks)
    return response_base.success(data=data)
