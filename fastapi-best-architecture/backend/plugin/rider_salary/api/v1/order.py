from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Path, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_code import CustomResponse
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.enums import ImportBatchStatus
from backend.plugin.rider_salary.schema.import_batch import GetImportBatchDetail, GetImportBatchListItem
from backend.plugin.rider_salary.schema.order import CreateOrderParam, GetOrderDetail, ImportResult, UpdateOrderParam
from backend.plugin.rider_salary.service.import_service import build_import_template, import_service
from backend.plugin.rider_salary.service.order_service import order_service

router = APIRouter()
batch_router = APIRouter()


@router.get(
    '',
    summary='分页获取订单明细',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
    ],
)
async def get_orders_paginated(
    db: CurrentSession,
    request: Request,
    *,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    rider_id: Annotated[int | None, Query(description='骑手 ID')] = None,
    date_from: Annotated[date | None, Query(description='业务日期起')] = None,
    date_to: Annotated[date | None, Query(description='业务日期止')] = None,
    status: Annotated[str | None, Query(description='订单状态')] = None,
    order_no: Annotated[str | None, Query(description='订单号')] = None,
    import_batch_id: Annotated[int | None, Query(description='导入批次 ID')] = None,
    is_locked: Annotated[bool | None, Query(description='是否已锁账')] = None,
    attention: Annotated[
        bool | None,
        Query(description='需关注：配送异常∪已退款∪已完成且时长>60分钟（与工作台同源）'),
    ] = None,
    missing_delivery: Annotated[
        bool | None,
        Query(description='已完成且送达时间为空'),
    ] = None,
) -> ResponseSchemaModel[PageData[GetOrderDetail]]:
    page_data = await order_service.get_list(
        db=db,
        request=request,
        site_id=site_id,
        rider_id=rider_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        order_no=order_no,
        import_batch_id=import_batch_id,
        is_locked=is_locked,
        attention=attention,
        missing_delivery=missing_delivery,
    )
    return response_base.success(data=page_data)


@router.get(
    '/import-template',
    summary='下载订单导入模板',
    dependencies=[
        Depends(RequestPermission('rs:order:import')),
        DependsRBAC,
    ],
)
async def download_import_template() -> StreamingResponse:
    content = build_import_template()
    filename = '订单导入模板.xlsx'
    return StreamingResponse(
        iter([content]),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get(
    '/export',
    summary='导出订单明细',
    dependencies=[
        Depends(RequestPermission('rs:order:export')),
        DependsRBAC,
    ],
)
async def export_orders(
    db: CurrentSessionTransaction,
    request: Request,
    site_id: Annotated[int, Query(description='站点 ID')],
    date_from: Annotated[date | None, Query(description='业务日期起')] = None,
    date_to: Annotated[date | None, Query(description='业务日期止')] = None,
    rider_id: Annotated[int | None, Query(description='骑手 ID')] = None,
) -> StreamingResponse:
    content, filename = await order_service.export(
        db=db,
        request=request,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        rider_id=rider_id,
    )
    return StreamingResponse(
        iter([content]),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post(
    '/import',
    summary='导入订单明细',
    dependencies=[
        Depends(RequestPermission('rs:order:import')),
        DependsRBAC,
    ],
)
async def import_orders(
    db: CurrentSessionTransaction,
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description='导入文件')],
    *,
    site_id: Annotated[int | None, Form(description='站点 ID')] = None,
    skip_errors: Annotated[bool, Form(description='跳过错误行')] = False,
    auto_recalc: Annotated[bool, Form(description='导入后自动重算')] = False,
) -> ResponseSchemaModel[ImportResult]:
    result = await import_service.import_orders(
        db=db,
        request=request,
        file=file,
        site_id=site_id,
        skip_errors=skip_errors,
        auto_recalc=auto_recalc,
        background_tasks=background_tasks,
    )
    if result.status == ImportBatchStatus.failed:
        res = CustomResponse(code=200, msg='导入失败，未写入任何订单，请下载错误报告')
    elif result.status == ImportBatchStatus.partial_failed:
        res = CustomResponse(
            code=200,
            msg=f'导入完成：成功 {result.success_rows} 行，失败 {result.failed_rows} 行，请下载错误报告',
        )
    else:
        res = CustomResponse(code=200, msg='导入完成')
    return response_base.success(res=res, data=result)


@router.get('/{pk}', summary='获取订单详情', dependencies=[DependsJwtAuth])
async def get_order(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='订单 ID')],
) -> ResponseSchemaModel[GetOrderDetail]:
    data = await order_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '',
    summary='补录订单',
    dependencies=[
        Depends(RequestPermission('rs:order:add')),
        DependsRBAC,
    ],
)
async def create_order(
    db: CurrentSessionTransaction,
    request: Request,
    obj: CreateOrderParam,
) -> ResponseSchemaModel[GetOrderDetail]:
    data = await order_service.create(db=db, request=request, obj=obj)
    return response_base.success(data=data)


@router.put(
    '/{pk}',
    summary='纠错订单',
    dependencies=[
        Depends(RequestPermission('rs:order:edit')),
        DependsRBAC,
    ],
)
async def update_order(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='订单 ID')],
    obj: UpdateOrderParam,
) -> ResponseSchemaModel[GetOrderDetail]:
    data = await order_service.update(db=db, request=request, pk=pk, obj=obj)
    return response_base.success(data=data)


@router.delete(
    '/{pk}',
    summary='删除订单',
    dependencies=[
        Depends(RequestPermission('rs:order:del')),
        DependsRBAC,
    ],
)
async def delete_order(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='订单 ID')],
    reason: Annotated[str, Query(description='删除原因')],
) -> ResponseModel:
    await order_service.delete(db=db, request=request, pk=pk, reason=reason)
    return response_base.success()


@batch_router.get(
    '',
    summary='分页获取导入批次',
    dependencies=[
        DependsJwtAuth,
        DependsPagination,
    ],
)
async def get_import_batches_paginated(
    db: CurrentSession,
    request: Request,
    *,
    site_id: Annotated[int | None, Query(description='站点 ID')] = None,
    status: Annotated[str | None, Query(description='批次状态')] = None,
) -> ResponseSchemaModel[PageData[GetImportBatchListItem]]:
    page_data = await import_service.get_batch_list(db=db, request=request, site_id=site_id, status=status)
    return response_base.success(data=page_data)


@batch_router.get(
    '/{pk}/error-report',
    summary='下载导入错误报告',
    dependencies=[
        Depends(RequestPermission('rs:order:import')),
        DependsRBAC,
    ],
)
async def download_error_report(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='批次 ID')],
) -> StreamingResponse:
    content = await import_service.get_error_report(db=db, request=request, pk=pk)
    filename = f'导入错误报告-{pk}.xlsx'
    return StreamingResponse(
        iter([content]),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@batch_router.get('/{pk}', summary='获取导入批次详情', dependencies=[DependsJwtAuth])
async def get_import_batch(
    db: CurrentSession,
    request: Request,
    pk: Annotated[int, Path(description='批次 ID')],
) -> ResponseSchemaModel[GetImportBatchDetail]:
    data = await import_service.get_batch(db=db, request=request, pk=pk)
    return response_base.success(data=data)
