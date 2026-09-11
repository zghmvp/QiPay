from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.day_flag import GetDayFlagDetail, UpsertDayFlagParam
from backend.plugin.rider_salary.service.day_flag_service import day_flag_service

router = APIRouter()


@router.get(
    '',
    summary='获取站点当月日标记',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:dayflag:edit')),
        DependsRBAC,
    ],
)
async def get_day_flags(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int, Query(description='站点 ID')],
    month: Annotated[str, Query(description='月份 YYYY-MM')],
) -> ResponseSchemaModel[list[GetDayFlagDetail]]:
    data = await day_flag_service.get_month(db=db, request=request, site_id=site_id, month=month)
    return response_base.success(data=data)


@router.put(
    '',
    summary='批量更新日标记',
    dependencies=[
        Depends(RequestPermission('rs:dayflag:edit')),
        DependsRBAC,
    ],
)
async def upsert_day_flags(
    db: CurrentSessionTransaction,
    request: Request,
    obj: UpsertDayFlagParam,
) -> ResponseModel:
    await day_flag_service.upsert(db=db, request=request, obj=obj)
    return response_base.success()
