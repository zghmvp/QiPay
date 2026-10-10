from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import StreamingResponse

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_code import CustomResponse
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.calc_job import GetCalcJobDetail
from backend.plugin.rider_salary.schema.period import (
    CalculatePeriodParam,
    CalculatePeriodResult,
    CarryForwardParam,
    CarryForwardResult,
    GeneratePeriodParam,
    GeneratePeriodResult,
    GetLockCheckResult,
    GetPeriodForDateResult,
    GetPeriodListItem,
    GetPeriodWithPayrolls,
    LockPeriodParam,
    MarkPaidPeriodParam,
    MarkPaidPeriodResult,
    ReversePeriodParam,
    ReversePeriodResult,
)
from backend.plugin.rider_salary.service.calc_job_service import get_visible_calc_job
from backend.plugin.rider_salary.service.export_service import content_disposition, export_service
from backend.plugin.rider_salary.service.period_service import period_service

router = APIRouter()


@router.get(
    '',
    summary='分页获取结算周期',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
        DependsRBAC,
    ],
)
async def get_periods_paginated(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    rider_id: Annotated[int | None, Query(description='骑手 ID，0 表示站点级')] = None,
    status: Annotated[str | None, Query(description='状态，多个用英文逗号分隔')] = None,
    month: Annotated[str | None, Query(description='年月 YYYY-MM')] = None,
    stale: Annotated[bool | None, Query(description='是否存在需重算草稿')] = None,
) -> ResponseSchemaModel[PageData[GetPeriodListItem]]:
    data = await period_service.get_list(
        db=db,
        request=request,
        site_id=site_id,
        rider_id=rider_id,
        status=status,
        month=month,
        stale=stale,
    )
    return response_base.success(data=data)


@router.get(
    '/for-date',
    summary='按日期查询覆盖周期',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def get_period_for_date(
    db: CurrentSession,
    request: Request,
    site_id: Annotated[int, Query(description='站点 ID')],
    date_: Annotated[date, Query(alias='date', description='业务日期')],
    rider_id: Annotated[int | None, Query(description='骑手 ID')] = None,
) -> ResponseSchemaModel[GetPeriodForDateResult]:
    data = await period_service.get_for_date(
        db=db,
        request=request,
        site_id=site_id,
        rider_id=rider_id,
        biz_date=date_,
    )
    return response_base.success(data=data)


@router.post(
    '/generate',
    summary='生成结算周期',
    dependencies=[
        Depends(RequestPermission('rs:period:generate')),
        DependsRBAC,
    ],
)
async def generate_periods(
    db: CurrentSessionTransaction,
    request: Request,
    obj: GeneratePeriodParam,
) -> ResponseSchemaModel[GeneratePeriodResult]:
    data = await period_service.generate(db=db, request=request, obj=obj)
    return response_base.success(data=data)


@router.get(
    '/{pk}/export',
    summary='导出周期薪资',
    dependencies=[
        Depends(RequestPermission('rs:period:export')),
        DependsRBAC,
    ],
)
async def export_period(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
) -> StreamingResponse:
    content, filename = await export_service.export_period(db=db, request=request, pk=pk)
    return StreamingResponse(
        iter([content]),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': content_disposition(filename)},
    )


@router.get(
    '/calc-jobs/{job_id}',
    summary='获取算薪作业',
    description='返回进度、失败骑手和原因。作业已落库，进程重启后仍可查询',
    dependencies=[
        Depends(RequestPermission('rs:period:calculate')),
        DependsRBAC,
    ],
)
async def get_calc_job(
    db: CurrentSession,
    request: Request,
    job_id: Annotated[int, Path(description='作业 ID')],
) -> ResponseSchemaModel[GetCalcJobDetail]:
    data = await get_visible_calc_job(db=db, request=request, job_id=job_id)
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取结算周期详情',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def get_period(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
) -> ResponseSchemaModel[GetPeriodWithPayrolls]:
    data = await period_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/calculate',
    summary='计算周期薪资',
    dependencies=[
        Depends(RequestPermission('rs:period:calculate')),
        DependsRBAC,
    ],
)
async def calculate_period(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
    obj: CalculatePeriodParam | None = None,
) -> ResponseSchemaModel[CalculatePeriodResult]:
    data = await period_service.calculate(
        db=db,
        request=request,
        pk=pk,
        obj=obj or CalculatePeriodParam(),
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}/lock-check',
    summary='锁账预检',
    description='返回未算薪、需重算和缺补发单骑手，不修改数据',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def lock_check_period(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
) -> ResponseSchemaModel[GetLockCheckResult]:
    data = await period_service.lock_check(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/carry-forward',
    summary='沿用原单',
    description='为已反冲且金额无需变化的骑手生成与原单金额相同的补发草稿，并写入审计',
    dependencies=[
        Depends(RequestPermission('rs:period:lock')),
        DependsRBAC,
    ],
)
async def carry_forward_period(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
    obj: CarryForwardParam | None = None,
) -> ResponseSchemaModel[CarryForwardResult]:
    payload = obj or CarryForwardParam()
    data = await period_service.carry_forward(
        db=db,
        request=request,
        pk=pk,
        rider_ids=payload.rider_ids,
        reason=payload.reason,
    )
    return response_base.success(data=data)


@router.post(
    '/{pk}/lock',
    summary='锁账',
    description='重复锁账，或期望状态与当前状态不一致时返回 409，不重复写审计',
    dependencies=[
        Depends(RequestPermission('rs:period:lock')),
        DependsRBAC,
    ],
)
async def lock_period(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
    obj: LockPeriodParam,
) -> ResponseModel:
    await period_service.lock(
        db=db,
        request=request,
        pk=pk,
        reason=obj.reason,
        expected_status=obj.expected_status,
    )
    return response_base.success()


@router.post(
    '/{pk}/mark-paid',
    summary='标记发薪',
    description='仅标记，不涉及实际打款。重复标记或期望状态不一致时返回 409，不重复写审计',
    dependencies=[
        Depends(RequestPermission('rs:period:mark-paid')),
        DependsRBAC,
    ],
)
async def mark_paid_period(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
    obj: MarkPaidPeriodParam | None = None,
) -> ResponseSchemaModel[MarkPaidPeriodResult]:
    data = await period_service.mark_paid(
        db=db,
        request=request,
        pk=pk,
        reason=None if obj is None else obj.reason,
        expected_status=None if obj is None else obj.expected_status,
    )
    if data.warning:
        return response_base.success(res=CustomResponse(code=200, msg=data.warning), data=data)
    return response_base.success(data=data)


@router.post(
    '/{pk}/reverse',
    summary='反冲补发',
    description='期望状态与当前状态不一致时返回 409。周期已在补发中时沿用原错误，不会生成第二张反冲单',
    dependencies=[
        Depends(RequestPermission('rs:period:reverse')),
        DependsRBAC,
    ],
)
async def reverse_period(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
    obj: ReversePeriodParam,
) -> ResponseSchemaModel[ReversePeriodResult]:
    data = await period_service.reverse(
        db=db,
        request=request,
        pk=pk,
        reason=obj.reason,
        expected_status=obj.expected_status,
    )
    return response_base.success(data=data)


@router.delete(
    '/{pk}',
    summary='删除结算周期',
    description='仅允许删除开放且没有任何薪资结果的周期',
    dependencies=[
        Depends(RequestPermission('rs:period:delete')),
        DependsRBAC,
    ],
)
async def delete_period(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
) -> ResponseModel:
    await period_service.delete(db=db, request=request, pk=pk)
    return response_base.success()
