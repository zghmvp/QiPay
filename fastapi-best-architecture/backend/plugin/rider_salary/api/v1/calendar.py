from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession
from backend.plugin.rider_salary.schema.calendar import GetCalendarDayDetail, GetCalendarMonth
from backend.plugin.rider_salary.service.calendar_service import calendar_service

router = APIRouter()


@router.get(
    '/{rider_id}/days/{biz_date}',
    summary='获取骑手某日薪资详情',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:calendar:view')),
        DependsRBAC,
    ],
)
async def get_calendar_day(
    db: CurrentSession,
    request: Request,
    rider_id: Annotated[int, Path(description='骑手 ID')],
    biz_date: Annotated[date, Path(description='日期')],
) -> ResponseSchemaModel[GetCalendarDayDetail]:
    data = await calendar_service.build_day(db, rider_id, biz_date, request=request)
    return response_base.success(data=data)


@router.get(
    '/{rider_id}',
    summary='获取骑手月历',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:calendar:view')),
        DependsRBAC,
    ],
)
async def get_calendar_month(
    db: CurrentSession,
    request: Request,
    rider_id: Annotated[int, Path(description='骑手 ID')],
    month: Annotated[str | None, Query(description='月份，格式 YYYY-MM')] = None,
) -> ResponseSchemaModel[GetCalendarMonth]:
    data = await calendar_service.build_month(db, rider_id, month, request=request)
    return response_base.success(data=data)
