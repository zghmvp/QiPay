from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.rider_salary.model.rider import RiderSalaryRider as Rider
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam, GetAdvanceDetail
from backend.plugin.rider_salary.schema.calendar import GetCalendarDayDetail, GetCalendarMonth
from backend.plugin.rider_salary.schema.me import (
    ChangeMePasswordParam,
    GetMeAdjustmentItem,
    GetMeAdvanceLimit,
    GetMePayrollEstimate,
    GetMePayslipDetail,
    GetMePayslipItem,
    GetMePlan,
    GetMeProfile,
)
from backend.plugin.rider_salary.schema.notice import GetNoticeDetail
from backend.plugin.rider_salary.service.me_service import me_service
from backend.plugin.rider_salary.utils.deps import DependsCurrentRider, DependsWritableRider

router = APIRouter()


@router.get(
    '/profile',
    summary='获取骑手资料',
    dependencies=[DependsJwtAuth],
)
async def get_me_profile(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
) -> ResponseSchemaModel[GetMeProfile]:
    data = await me_service.profile(db=db, rider=rider)
    return response_base.success(data=data)


@router.get(
    '/calendar',
    summary='获取本人月历',
    dependencies=[DependsJwtAuth],
)
async def get_me_calendar(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
    month: Annotated[str | None, Query(description='月份，格式 YYYY-MM')] = None,
) -> ResponseSchemaModel[GetCalendarMonth]:
    data = await me_service.calendar(db=db, rider=rider, month=month)
    return response_base.success(data=data)


@router.get(
    '/days/{biz_date}',
    summary='获取本人某日详情',
    dependencies=[DependsJwtAuth],
)
async def get_me_day(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
    biz_date: date,
) -> ResponseSchemaModel[GetCalendarDayDetail]:
    data = await me_service.day(db=db, rider=rider, biz_date=biz_date)
    return response_base.success(data=data)


@router.get(
    '/payroll-estimate',
    summary='获取当前周期预计工资',
    dependencies=[DependsJwtAuth],
)
async def get_me_payroll_estimate(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
) -> ResponseSchemaModel[GetMePayrollEstimate]:
    data = await me_service.payroll_estimate(db=db, rider=rider)
    return response_base.success(data=data)


@router.get(
    '/payslips',
    summary='获取本人往期工资条',
    description='按周期列出已定稿或已发薪的有效薪资单。草稿、作废和已被反冲的单不返回。',
    dependencies=[DependsJwtAuth],
)
async def get_me_payslips(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
) -> ResponseSchemaModel[list[GetMePayslipItem]]:
    data = await me_service.payslips(db=db, rider=rider)
    return response_base.success(data=data)


@router.get(
    '/payslips/{pk}',
    summary='获取本人工资条明细',
    description='只返回该骑手当前有效且已定稿或已发薪的工资条，明细不含计算过程。',
    dependencies=[DependsJwtAuth],
)
async def get_me_payslip(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
    pk: int,
) -> ResponseSchemaModel[GetMePayslipDetail]:
    data = await me_service.payslip(db=db, rider=rider, pk=pk)
    return response_base.success(data=data)


@router.get(
    '/adjustments',
    summary='获取本人奖惩',
    dependencies=[DependsJwtAuth],
)
async def get_me_adjustments(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
    month: Annotated[str | None, Query(description='月份，格式 YYYY-MM')] = None,
) -> ResponseSchemaModel[list[GetMeAdjustmentItem]]:
    data = await me_service.adjustments(db=db, rider=rider, month=month)
    return response_base.success(data=data)


@router.get(
    '/plan',
    summary='获取本人当前与未来方案',
    dependencies=[DependsJwtAuth],
)
async def get_me_plan(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
) -> ResponseSchemaModel[GetMePlan]:
    data = await me_service.plan(db=db, rider=rider)
    return response_base.success(data=data)


@router.get(
    '/notices',
    summary='获取站点公告',
    dependencies=[DependsJwtAuth],
)
async def get_me_notices(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
) -> ResponseSchemaModel[list[GetNoticeDetail]]:
    data = await me_service.notices(db=db, rider=rider)
    return response_base.success(data=data)


@router.get(
    '/advance-limit',
    summary='获取预支额度',
    description='可用额度 = 上限 − 在途 − 已发放未抵扣',
    dependencies=[DependsJwtAuth],
)
async def get_me_advance_limit(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
) -> ResponseSchemaModel[GetMeAdvanceLimit]:
    data = await me_service.advance_limit(db=db, rider=rider)
    return response_base.success(data=data)


@router.get(
    '/advances',
    summary='获取本人预支记录',
    dependencies=[DependsJwtAuth],
)
async def get_me_advances(
    db: CurrentSession,
    rider: Annotated[Rider, DependsCurrentRider],
) -> ResponseSchemaModel[list[GetAdvanceDetail]]:
    data = await me_service.advances(db=db, rider=rider)
    return response_base.success(data=data)


@router.post(
    '/advances',
    summary='提交预支申请',
    dependencies=[DependsJwtAuth],
)
async def create_me_advance(
    db: CurrentSessionTransaction,
    request: Request,
    rider: Annotated[Rider, DependsWritableRider],
    obj: CreateMeAdvanceParam,
) -> ResponseSchemaModel[GetAdvanceDetail]:
    data = await me_service.create_advance(db=db, request=request, rider=rider, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/advances/{pk}/cancel',
    summary='撤回预支申请',
    description='仅待审核的预支可撤回；待发放需由管理员取消',
    dependencies=[DependsJwtAuth],
)
async def cancel_me_advance(
    db: CurrentSessionTransaction,
    request: Request,
    rider: Annotated[Rider, DependsWritableRider],
    pk: int,
) -> ResponseModel:
    await me_service.cancel_advance(db=db, request=request, rider=rider, pk=pk)
    return response_base.success()


@router.put(
    '/password',
    summary='修改本人密码',
    description='须改密时仅此接口可调用。成功后清除必须改密标记，并保持当前登录。',
    dependencies=[DependsJwtAuth],
)
async def update_me_password(
    db: CurrentSessionTransaction,
    rider: Annotated[Rider, DependsCurrentRider],
    obj: ChangeMePasswordParam,
) -> ResponseModel:
    await me_service.change_password(db=db, rider=rider, obj=obj)
    return response_base.success()
