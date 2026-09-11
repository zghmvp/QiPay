from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession
from backend.plugin.rider_salary.schema.dashboard import GetDashboardSummary
from backend.plugin.rider_salary.service.dashboard_service import dashboard_service

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
