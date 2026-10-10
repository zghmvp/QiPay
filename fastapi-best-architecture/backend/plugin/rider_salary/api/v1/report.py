from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession
from backend.plugin.rider_salary.schema.report import GetCostSummary
from backend.plugin.rider_salary.service.report_service import report_service

router = APIRouter()


@router.get(
    '/costs',
    summary='按站点和月份汇总成本',
    description='只加总有效薪资单。月份取结算周期开始日，作废、反冲和已被反冲的单不计入。',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:report:view')),
        DependsRBAC,
    ],
)
async def get_cost_summary(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int | None, Query(description='站点 ID，空表示全部可见站点')] = None,
    month: Annotated[str | None, Query(description='月份，格式 YYYY-MM，空表示全部月份')] = None,
) -> ResponseSchemaModel[GetCostSummary]:
    data = await report_service.cost_summary(db=db, request=request, site_id=site_id, month=month)
    return response_base.success(data=data)
