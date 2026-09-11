from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.site import (
    CreateSiteParam,
    GetSiteDetail,
    GetSiteManagerDetail,
    SiteManagerItem,
    UpdateSiteParam,
)
from backend.plugin.rider_salary.service.site_service import site_service

router = APIRouter()


@router.get(
    '/all',
    summary='获取可见站点下拉列表',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def get_all_sites(db: CurrentSession, request: Request) -> ResponseSchemaModel[list[GetSiteDetail]]:
    data = await site_service.get_all(db=db, request=request)
    return response_base.success(data=data)


@router.get(
    '/{pk}/managers',
    summary='获取站点负责人',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def get_site_managers(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='站点 ID')],
) -> ResponseSchemaModel[list[GetSiteManagerDetail]]:
    data = await site_service.get_managers(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.put(
    '/{pk}/managers',
    summary='覆盖站点负责人',
    dependencies=[
        Depends(RequestPermission('rs:site:manager')),
        DependsRBAC,
    ],
)
async def update_site_managers(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='站点 ID')],
    managers: list[SiteManagerItem],
) -> ResponseModel:
    await site_service.update_managers(db=db, request=request, pk=pk, managers=managers)
    return response_base.success()


@router.get(
    '/{pk}',
    summary='获取站点详情',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def get_site(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='站点 ID')],
) -> ResponseSchemaModel[GetSiteDetail]:
    data = await site_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取站点',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        DependsRBAC,
    ],
)
async def get_sites_paginated(
    db: CurrentSession,
    request: Request,
    name: Annotated[str | None, Query(description='站点名称')] = None,
    code: Annotated[str | None, Query(description='站点编码')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
) -> ResponseSchemaModel[PageData[GetSiteDetail]]:
    page_data = await site_service.get_list(db=db, request=request, name=name, code=code, status=status)
    return response_base.success(data=page_data)


@router.post(
    '',
    summary='创建站点',
    dependencies=[
        Depends(RequestPermission('rs:site:add')),
        DependsRBAC,
    ],
)
async def create_site(db: CurrentSessionTransaction, request: Request, obj: CreateSiteParam) -> ResponseModel:
    await site_service.create(db=db, request=request, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新站点',
    dependencies=[
        Depends(RequestPermission('rs:site:edit')),
        DependsRBAC,
    ],
)
async def update_site(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='站点 ID')],
    obj: UpdateSiteParam,
) -> ResponseModel:
    count = await site_service.update(db=db, request=request, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除站点',
    dependencies=[
        Depends(RequestPermission('rs:site:del')),
        DependsRBAC,
    ],
)
async def delete_site(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='站点 ID')],
) -> ResponseModel:
    count = await site_service.delete(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()
