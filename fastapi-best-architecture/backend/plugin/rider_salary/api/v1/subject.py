from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.subject import CreateSubjectParam, GetSubjectDetail, UpdateSubjectParam
from backend.plugin.rider_salary.service.subject_service import subject_service

router = APIRouter()


@router.get(
    '/all',
    summary='获取科目下拉列表',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def get_all_subjects(db: CurrentSession) -> ResponseSchemaModel[list[GetSubjectDetail]]:
    data = await subject_service.get_all(db=db)
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取科目详情',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def get_subject(
    db: CurrentSession,
    pk: Annotated[int, Path(description='科目 ID')],
) -> ResponseSchemaModel[GetSubjectDetail]:
    data = await subject_service.get(db=db, pk=pk)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取科目',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        DependsRBAC,
    ],
)
async def get_subjects_paginated(
    db: CurrentSession,
    name: Annotated[str | None, Query(description='科目名称')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
    direction: Annotated[str | None, Query(description='方向')] = None,
) -> ResponseSchemaModel[PageData[GetSubjectDetail]]:
    page_data = await subject_service.get_list(db=db, name=name, status=status, direction=direction)
    return response_base.success(data=page_data)


@router.post(
    '',
    summary='创建科目',
    dependencies=[
        Depends(RequestPermission('rs:subject:add')),
        DependsRBAC,
    ],
)
async def create_subject(db: CurrentSessionTransaction, request: Request, obj: CreateSubjectParam) -> ResponseModel:
    await subject_service.create(db=db, request=request, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新科目',
    dependencies=[
        Depends(RequestPermission('rs:subject:edit')),
        DependsRBAC,
    ],
)
async def update_subject(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='科目 ID')],
    obj: UpdateSubjectParam,
) -> ResponseModel:
    count = await subject_service.update(db=db, request=request, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除科目',
    dependencies=[
        Depends(RequestPermission('rs:subject:del')),
        DependsRBAC,
    ],
)
async def delete_subject(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='科目 ID')],
) -> ResponseModel:
    count = await subject_service.delete(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()
