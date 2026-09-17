from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession
from backend.plugin.rider_salary.schema.audit import GetAuditLogDetail
from backend.plugin.rider_salary.service.audit_service import audit_service

router = APIRouter()


@router.get(
    '',
    summary='分页获取操作日志',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        Depends(RequestPermission('rs:audit:view')),
        DependsRBAC,
    ],
)
async def get_audit_logs_paginated(
    db: CurrentSession,
    request: Request,
    module: Annotated[str | None, Query(description='模块')] = None,
    action: Annotated[str | None, Query(description='动作')] = None,
    operator: Annotated[str | None, Query(description='操作人')] = None,
    date_from: Annotated[str | None, Query(description='开始时间')] = None,
    date_to: Annotated[str | None, Query(description='结束时间')] = None,
    target_type: Annotated[str | None, Query(description='对象类型')] = None,
    keyword: Annotated[str | None, Query(description='关键字')] = None,
) -> ResponseSchemaModel[PageData[GetAuditLogDetail]]:
    page_data = await audit_service.get_list(
        db=db,
        request=request,
        module=module,
        action=action,
        operator=operator,
        date_from=date_from,
        date_to=date_to,
        target_type=target_type,
        keyword=keyword,
    )
    return response_base.success(data=page_data)
