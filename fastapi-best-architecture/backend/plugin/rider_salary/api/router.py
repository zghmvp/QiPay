from fastapi import APIRouter

from backend.core.conf import settings
from backend.plugin.rider_salary.api.v1.adjustment import router as adjustment_router
from backend.plugin.rider_salary.api.v1.advance import router as advance_router
from backend.plugin.rider_salary.api.v1.audit import router as audit_router
from backend.plugin.rider_salary.api.v1.calendar import router as calendar_router
from backend.plugin.rider_salary.api.v1.dashboard import router as dashboard_router
from backend.plugin.rider_salary.api.v1.day_flag import router as day_flag_router
from backend.plugin.rider_salary.api.v1.engine import router as engine_router
from backend.plugin.rider_salary.api.v1.me import router as me_router
from backend.plugin.rider_salary.api.v1.notice import router as notice_router
from backend.plugin.rider_salary.api.v1.order import batch_router as import_batch_router
from backend.plugin.rider_salary.api.v1.order import router as order_router
from backend.plugin.rider_salary.api.v1.payroll import router as payroll_router
from backend.plugin.rider_salary.api.v1.period import router as period_router
from backend.plugin.rider_salary.api.v1.plan import router as plan_router
from backend.plugin.rider_salary.api.v1.plan import version_router as plan_version_router
from backend.plugin.rider_salary.api.v1.recalc_job import router as recalc_job_router
from backend.plugin.rider_salary.api.v1.rider import router as rider_router
from backend.plugin.rider_salary.api.v1.site import router as site_router
from backend.plugin.rider_salary.api.v1.subject import router as subject_router

v1 = APIRouter(prefix=f'{settings.FASTAPI_API_V1_PATH}/rider-salary')

v1.include_router(site_router, prefix='/sites', tags=['站点管理'])
v1.include_router(rider_router, prefix='/riders', tags=['骑手管理'])
v1.include_router(subject_router, prefix='/subjects', tags=['科目管理'])
v1.include_router(plan_router, prefix='/plans', tags=['薪资方案'])
v1.include_router(plan_version_router, prefix='/plan-versions', tags=['薪资方案'])
v1.include_router(engine_router, prefix='/engine', tags=['公式引擎元数据'])
v1.include_router(order_router, prefix='/orders', tags=['订单明细'])
v1.include_router(import_batch_router, prefix='/import-batches', tags=['订单明细'])
v1.include_router(day_flag_router, prefix='/day-flags', tags=['日标记'])
v1.include_router(adjustment_router, prefix='/adjustments', tags=['奖惩录入'])
v1.include_router(period_router, prefix='/periods', tags=['结算周期'])
v1.include_router(payroll_router, prefix='/payrolls', tags=['薪资结果'])
v1.include_router(calendar_router, prefix='/calendar', tags=['薪资日历'])
v1.include_router(dashboard_router, prefix='/dashboard', tags=['工作台'])
v1.include_router(recalc_job_router, prefix='/recalc-jobs', tags=['重算任务'])
v1.include_router(advance_router, prefix='/advances', tags=['预支审核'])
v1.include_router(notice_router, prefix='/notices', tags=['站点公告'])
v1.include_router(audit_router, prefix='/audit-logs', tags=['操作日志'])
v1.include_router(me_router, prefix='/me', tags=['骑手端'])
