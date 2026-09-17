from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request
from fastapi.responses import StreamingResponse

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.schema.period import (
    CalcPrecheckResult,
    CalcRiderPageResult,
    CalculatePeriodParam,
    CalculatePeriodResult,
    GeneratePeriodParam,
    GeneratePeriodResult,
    GetPeriodForDateResult,
    GetPeriodListItem,
    GetPeriodWithPayrolls,
    LockPeriodParam,
    LockPreflightResult,
    MarkPaidPeriodParam,
    ReversePeriodParam,
    ReversePeriodResult,
)
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
    status: Annotated[str | None, Query(description='状态')] = None,
    month: Annotated[str | None, Query(description='年月 YYYY-MM')] = None,
    stale: Annotated[bool | None, Query(description='仅需重算周期')] = None,
    lock_due: Annotated[
        bool | None,
        Query(description='锁账倒计时：open|reopened 且 end_date≤今天+3（含已过期未锁）'),
    ] = None,
) -> ResponseSchemaModel[PageData[GetPeriodListItem]]:
    data = await period_service.get_list(
        db=db,
        request=request,
        site_id=site_id,
        rider_id=rider_id,
        status=status,
        month=month,
        stale=stale,
        lock_due=lock_due,
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
    exclude_attention: Annotated[
        bool | None,
        Query(description='排除需关注订单行（不改应发/实发），默认不排除'),
    ] = None,
    exclude_attention_adjustments: Annotated[
        bool | None,
        Query(description='奖惩同步去掉需关注同日同骑手，默认关闭；关闭时仍导出并标注'),
    ] = None,
) -> StreamingResponse:
    excluded = bool(exclude_attention)
    drop_adj = bool(exclude_attention_adjustments)
    exported = await export_service.export_period(
        db=db,
        request=request,
        pk=pk,
        exclude_attention=excluded,
        exclude_attention_adjustments=drop_adj,
    )
    headers = {'Content-Disposition': content_disposition(exported.filename)}
    headers['X-QiPay-Attention-Count'] = str(exported.attention_count)
    headers['X-QiPay-Attention-Excluded'] = '1' if exported.exclude_attention else '0'
    headers['X-QiPay-Adjustment-Booked'] = str(exported.booked_adjustment_count)
    headers['X-QiPay-Adjustment-Unbooked'] = str(exported.unbooked_adjustment_count)
    headers['X-QiPay-Adjustment-Attention'] = str(exported.attention_adjustment_count)
    headers['X-QiPay-Adjustment-Excluded'] = str(exported.excluded_adjustment_count)
    return StreamingResponse(
        iter([exported.content]),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=headers,
    )


@router.get(
    '/{pk}/calc-riders',
    summary='算薪骑手搜索分页',
    description='未选=计算本周期全部骑手。可见列表不是全集时返回 truncated_hint，请搜索第 201+ 人。',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def list_period_calc_riders(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
    keyword: Annotated[str | None, Query(description='工号或姓名')] = None,
    page: Annotated[int, Query(ge=1, description='页码')] = 1,
    size: Annotated[int, Query(gt=0, le=200, description='每页数量，最大 200')] = 200,
) -> ResponseSchemaModel[CalcRiderPageResult]:
    data = await period_service.list_calc_riders(
        db=db,
        request=request,
        pk=pk,
        keyword=keyword,
        page=page,
        size=size,
    )
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


@router.get(
    '/{pk}/calc-precheck',
    summary='算薪预检',
    description='只读聚合硬风险与警告，不写薪资结果；不要求算薪权限',
    dependencies=[
        DependsJwtAuth,
        DependsRBAC,
    ],
)
async def calc_precheck_period(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
) -> ResponseSchemaModel[CalcPrecheckResult]:
    data = await period_service.calc_precheck(db=db, request=request, pk=pk)
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
    background_tasks: BackgroundTasks,
    pk: Annotated[int, Path(description='周期 ID')],
    obj: CalculatePeriodParam | None = None,
) -> ResponseSchemaModel[CalculatePeriodResult]:
    data = await period_service.calculate(
        db=db,
        request=request,
        pk=pk,
        obj=obj or CalculatePeriodParam(),
        background_tasks=background_tasks,
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}/lock-preflight',
    summary='锁账预检',
    description='返回本锁将冻结的订单/奖惩/薪资单数、将锁骑手数，以及决策29跳过的骑手级覆盖人数',
    dependencies=[
        Depends(RequestPermission('rs:period:lock')),
        DependsRBAC,
    ],
)
async def lock_period_preflight(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='周期 ID')],
) -> ResponseSchemaModel[LockPreflightResult]:
    data = await period_service.lock_preflight(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/lock',
    summary='锁账',
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
    await period_service.lock(db=db, request=request, pk=pk, reason=obj.reason)
    return response_base.success()


@router.post(
    '/{pk}/mark-paid',
    summary='标记发薪',
    description='仅标记，不涉及实际打款',
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
) -> ResponseModel:
    await period_service.mark_paid(db=db, request=request, pk=pk, reason=None if obj is None else obj.reason)
    return response_base.success()


@router.post(
    '/{pk}/reverse',
    summary='反冲补发',
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
    data = await period_service.reverse(db=db, request=request, pk=pk, reason=obj.reason)
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
