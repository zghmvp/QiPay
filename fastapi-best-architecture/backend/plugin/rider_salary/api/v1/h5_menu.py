from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.h5_menu import GetH5Menu, SaveH5MenuParam
from backend.plugin.rider_salary.service.h5_menu_service import h5_menu_service

router = APIRouter()


@router.get(
    '',
    summary='获取骑手端菜单开关',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:h5:menu')),
        DependsRBAC,
    ],
)
async def get_h5_menu(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int, Query(description='站点 ID，0 表示全局默认')] = 0,
) -> ResponseSchemaModel[GetH5Menu]:
    data = await h5_menu_service.get(db=db, request=request, site_id=site_id)
    return response_base.success(data=data)


@router.put(
    '',
    summary='保存骑手端菜单开关',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:h5:menu')),
        DependsRBAC,
    ],
)
async def save_h5_menu(
    db: CurrentSessionTransaction,
    request: Request,
    obj: SaveH5MenuParam,
) -> ResponseSchemaModel[GetH5Menu]:
    data = await h5_menu_service.save(db=db, request=request, obj=obj)
    return response_base.success(data=data)
