from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.notice import CreateNoticeParam, GetNoticeDetail, UpdateNoticeParam
from backend.plugin.rider_salary.service.notice_service import notice_service

router = APIRouter()


@router.get(
    '/{pk}',
    summary='获取公告详情',
    dependencies=[
        DependsJwtAuth,
        Depends(RequestPermission('rs:notice:add')),
        DependsRBAC,
    ],
)
async def get_notice(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='公告 ID')],
) -> ResponseSchemaModel[GetNoticeDetail]:
    data = await notice_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取公告',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        Depends(RequestPermission('rs:notice:add')),
        DependsRBAC,
    ],
)
async def get_notices_paginated(
    db: CurrentSession,
    request: Request,
    title: Annotated[str | None, Query(description='标题')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
) -> ResponseSchemaModel[PageData[GetNoticeDetail]]:
    page_data = await notice_service.get_list(db=db, request=request, title=title, status=status, site_id=site_id)
    return response_base.success(data=page_data)


@router.post(
    '',
    summary='创建公告',
    dependencies=[
        Depends(RequestPermission('rs:notice:add')),
        DependsRBAC,
    ],
)
async def create_notice(db: CurrentSessionTransaction, request: Request, obj: CreateNoticeParam) -> ResponseModel:
    await notice_service.create(db=db, request=request, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新公告',
    dependencies=[
        Depends(RequestPermission('rs:notice:edit')),
        DependsRBAC,
    ],
)
async def update_notice(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='公告 ID')],
    obj: UpdateNoticeParam,
) -> ResponseModel:
    count = await notice_service.update(db=db, request=request, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/{pk}/publish',
    summary='发布公告',
    dependencies=[
        Depends(RequestPermission('rs:notice:edit')),
        DependsRBAC,
    ],
)
async def publish_notice(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='公告 ID')],
) -> ResponseModel:
    count = await notice_service.publish(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/{pk}/offline',
    summary='下线公告',
    dependencies=[
        Depends(RequestPermission('rs:notice:edit')),
        DependsRBAC,
    ],
)
async def offline_notice(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='公告 ID')],
) -> ResponseModel:
    count = await notice_service.offline(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除公告',
    dependencies=[
        Depends(RequestPermission('rs:notice:del')),
        DependsRBAC,
    ],
)
async def delete_notice(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='公告 ID')],
) -> ResponseModel:
    count = await notice_service.delete(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()
