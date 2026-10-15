"""B1/B2：用工历史、离职、骑手主数据与日标记的锁账校验和重算标记。"""

from datetime import date

import pytest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import EmployType, PayrollStatus
from backend.plugin.rider_salary.model.day_flag import RiderSalaryDayFlag
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.rider_employ_history import RiderSalaryRiderEmployHistory
from backend.plugin.rider_salary.schema.day_flag import DayFlagItem, UpsertDayFlagParam
from backend.plugin.rider_salary.schema.rider import (
    CreateEmployHistoryParam,
    RiderLeaveParam,
    UpdateEmployHistoryParam,
    UpdateRiderParam,
)
from backend.plugin.rider_salary.service.day_flag_service import day_flag_service
from backend.plugin.rider_salary.service.rider_service import rider_service
from backend.plugin.rider_salary.tests.integration.harness import Seed, admin_request, run_db

SEP1, SEP30 = date(2026, 9, 1), date(2026, 9, 30)
OCT1, OCT31 = date(2026, 10, 1), date(2026, 10, 31)
LOCK_MSG = '该日期所属结算周期已锁账，禁止修改，请走反冲补发流程'


async def _history(
    seed: Seed,
    rider_id: int,
    start: date,
    end: date | None = None,
    employ_type: str = EmployType.part_time.value,
) -> RiderSalaryRiderEmployHistory:
    return await seed.add(
        RiderSalaryRiderEmployHistory(
            rider_id=rider_id,
            start_date=start,
            end_date=end,
            employ_type=employ_type,
        )
    )


async def _draft(seed: Seed, period_id: int, rider_id: int) -> RiderSalaryPayroll:
    return await seed.add(RiderSalaryPayroll(period_id=period_id, rider_id=rider_id, status=PayrollStatus.draft.value))


async def _assert_marked(db: AsyncSession, payroll: RiderSalaryPayroll) -> None:
    await db.refresh(payroll)
    assert payroll.stale is True
    payroll.stale = False
    await db.flush()


def test_locked_employ_history_writes_rejected() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        await seed.period(site, SEP1, SEP30, status='locked')
        creator = await seed.rider(site)
        editor = await seed.rider(site)
        opener = await seed.rider(site)
        inside = await _history(seed, editor.id, SEP1, SEP30)
        opened = await _history(seed, opener.id, date(2026, 1, 1))

        with pytest.raises(errors.ForbiddenError) as create_exc:
            await rider_service.create_employ_history(
                db=db,
                request=req,
                pk=creator.id,
                obj=CreateEmployHistoryParam(
                    employ_type=EmployType.full_time,
                    start_date=date(2026, 9, 10),
                    end_date=date(2026, 9, 20),
                ),
            )
        assert LOCK_MSG in create_exc.value.msg

        with pytest.raises(errors.ForbiddenError) as update_exc:
            await rider_service.update_employ_history(
                db=db,
                request=req,
                pk=editor.id,
                history_id=inside.id,
                obj=UpdateEmployHistoryParam(employ_type=EmployType.full_time),
            )
        assert LOCK_MSG in update_exc.value.msg

        with pytest.raises(errors.ForbiddenError) as shorten_exc:
            await rider_service.update_employ_history(
                db=db,
                request=req,
                pk=opener.id,
                history_id=opened.id,
                obj=UpdateEmployHistoryParam(end_date=date(2026, 8, 31)),
            )
        assert LOCK_MSG in shorten_exc.value.msg

        with pytest.raises(errors.ForbiddenError) as delete_exc:
            await rider_service.delete_employ_history(db=db, request=req, pk=editor.id, history_id=inside.id)
        assert LOCK_MSG in delete_exc.value.msg

        await db.refresh(opened)
        assert opened.end_date is None
        await db.refresh(inside)
        assert inside.employ_type == EmployType.part_time.value
        assert inside.deleted == 0

    run_db(_case)


def test_employ_history_only_checks_dates_that_change() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        await seed.period(site, SEP1, SEP30, status='paid')
        opened = await _history(seed, rider.id, date(2026, 1, 1))

        # 新段从锁账期内开始：收尾上一段会改变 9 月的用工类型，拒绝
        with pytest.raises(errors.ForbiddenError) as exc:
            await rider_service.create_employ_history(
                db=db,
                request=req,
                pk=rider.id,
                obj=CreateEmployHistoryParam(
                    employ_type=EmployType.full_time, start_date=date(2026, 9, 15), end_date=None
                ),
            )
        assert LOCK_MSG in exc.value.msg
        await db.refresh(opened)
        assert opened.end_date is None

        # 新段从锁账期之后开始：9 月不受影响，放行并收尾上一段
        await rider_service.create_employ_history(
            db=db,
            request=req,
            pk=rider.id,
            obj=CreateEmployHistoryParam(employ_type=EmployType.full_time, start_date=OCT1, end_date=None),
        )
        await db.refresh(opened)
        assert opened.end_date == SEP30

        # 只挪动锁账期之后的结束日期：放行
        other = await seed.rider(site)
        segment = await _history(seed, other.id, date(2026, 1, 1), date(2026, 12, 31))
        await rider_service.update_employ_history(
            db=db,
            request=req,
            pk=other.id,
            history_id=segment.id,
            obj=UpdateEmployHistoryParam(end_date=date(2026, 11, 30)),
        )
        await db.refresh(segment)
        assert segment.end_date == date(2026, 11, 30)

    run_db(_case)


def test_leave_inside_locked_period_rejected() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        rider = await seed.rider(site)
        moved = await seed.rider(site)
        await seed.period(site, SEP1, SEP30, status='locked')
        await _history(seed, rider.id, date(2026, 1, 1))

        with pytest.raises(errors.ForbiddenError) as leave_exc:
            await rider_service.leave(
                db=db,
                request=req,
                pk=rider.id,
                obj=RiderLeaveParam(leave_date=date(2026, 9, 15), reason='离职'),
            )
        assert LOCK_MSG in leave_exc.value.msg
        await db.refresh(rider)
        assert rider.leave_date is None
        assert rider.status == 'on_job'

        with pytest.raises(errors.ForbiddenError) as update_exc:
            await rider_service.update(
                db=db,
                request=req,
                pk=moved.id,
                obj=UpdateRiderParam(leave_date=date(2026, 9, 15)),
            )
        assert LOCK_MSG in update_exc.value.msg
        await db.refresh(moved)
        assert moved.leave_date is None

    run_db(_case)


def test_day_flag_rejected_when_rider_period_locked() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        for index in range(1, 12):
            rider = await seed.rider(site)
            rider.job_no = f'J{index:02d}'
            await seed.period(site, SEP1, SEP30, rider_id=rider.id, status='locked')
        await db.flush()

        with pytest.raises(errors.ForbiddenError) as exc:
            await day_flag_service.upsert(
                db=db,
                request=req,
                obj=UpsertDayFlagParam(
                    site_id=site.id,
                    days=[DayFlagItem(biz_date=date(2026, 9, 10), bad_weather=True)],
                ),
            )
        assert '、'.join(f'J{index:02d}' for index in range(1, 11)) in exc.value.msg
        assert '等11人' in exc.value.msg
        assert 'J11' not in exc.value.msg
        saved = await db.scalar(
            select(RiderSalaryDayFlag.id).where(
                RiderSalaryDayFlag.site_id == site.id,
                RiderSalaryDayFlag.biz_date == date(2026, 9, 10),
                RiderSalaryDayFlag.deleted == 0,
            )
        )
        assert saved is None

    run_db(_case)


def test_unlocked_master_writes_mark_draft_stale() -> None:
    async def _case(db: AsyncSession) -> None:
        seed = Seed(db)
        req = admin_request()
        site = await seed.site()
        period = await seed.period(site, OCT1, OCT31)

        history_rider = await seed.rider(site)
        opened = await _history(seed, history_rider.id, date(2026, 1, 1))
        history_payroll = await _draft(seed, period.id, history_rider.id)
        await rider_service.create_employ_history(
            db=db,
            request=req,
            pk=history_rider.id,
            obj=CreateEmployHistoryParam(employ_type=EmployType.full_time, start_date=OCT1, end_date=None),
        )
        await db.refresh(opened)
        assert opened.end_date == date(2026, 9, 30)
        await _assert_marked(db, history_payroll)
        created = await db.scalar(
            select(RiderSalaryRiderEmployHistory).where(
                RiderSalaryRiderEmployHistory.rider_id == history_rider.id,
                RiderSalaryRiderEmployHistory.start_date == OCT1,
                RiderSalaryRiderEmployHistory.deleted == 0,
            )
        )
        assert created is not None
        await rider_service.update_employ_history(
            db=db,
            request=req,
            pk=history_rider.id,
            history_id=created.id,
            obj=UpdateEmployHistoryParam(end_date=date(2026, 10, 20)),
        )
        await _assert_marked(db, history_payroll)
        await rider_service.delete_employ_history(db=db, request=req, pk=history_rider.id, history_id=created.id)
        await _assert_marked(db, history_payroll)

        leave_rider = await seed.rider(site)
        leave_payroll = await _draft(seed, period.id, leave_rider.id)
        await rider_service.leave(
            db=db,
            request=req,
            pk=leave_rider.id,
            obj=RiderLeaveParam(leave_date=date(2026, 10, 15), reason='离职'),
        )
        await db.refresh(leave_rider)
        assert leave_rider.status == 'resigned'
        assert leave_rider.leave_date == date(2026, 10, 15)
        await _assert_marked(db, leave_payroll)

        master_rider = await seed.rider(site, hire_date=date(2026, 1, 1))
        master_payroll = await _draft(seed, period.id, master_rider.id)
        await rider_service.update(
            db=db,
            request=req,
            pk=master_rider.id,
            obj=UpdateRiderParam(hire_date=date(2026, 2, 1)),
        )
        await db.refresh(master_rider)
        assert master_rider.hire_date == date(2026, 2, 1)
        await _assert_marked(db, master_payroll)
        await rider_service.update(
            db=db,
            request=req,
            pk=master_rider.id,
            obj=UpdateRiderParam(leave_date=date(2026, 10, 20)),
        )
        await db.refresh(master_rider)
        assert master_rider.leave_date == date(2026, 10, 20)
        await _assert_marked(db, master_payroll)

        flag_rider = await seed.rider(site)
        flag_payroll = await _draft(seed, period.id, flag_rider.id)
        await day_flag_service.upsert(
            db=db,
            request=req,
            obj=UpsertDayFlagParam(
                site_id=site.id,
                days=[DayFlagItem(biz_date=date(2026, 10, 5), high_temp=True)],
            ),
        )
        await _assert_marked(db, flag_payroll)
        await _assert_marked(db, history_payroll)
        await db.refresh(master_payroll)
        master_payroll.stale = False
        await db.flush()

        await seed.period(site, SEP1, SEP30, status='locked')
        await rider_service.update(
            db=db,
            request=req,
            pk=master_rider.id,
            obj=UpdateRiderParam(employ_type=EmployType.full_time),
        )
        await db.refresh(master_rider)
        assert master_rider.employ_type == EmployType.full_time.value
        await _assert_marked(db, master_payroll)

    run_db(_case)
