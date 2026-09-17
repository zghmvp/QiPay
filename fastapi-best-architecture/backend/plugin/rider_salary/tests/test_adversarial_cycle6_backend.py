"""对抗循环 Cycle 6 后端：周期列表消费 stale=1+site_id+month；不改 #9 stale 谓词。"""

from __future__ import annotations

import inspect

from datetime import date

import anyio

from backend.plugin.rider_salary.api.v1.period import get_periods_paginated
from backend.plugin.rider_salary.crud.settle_period import CRUDSettlePeriod, settle_period_dao
from backend.plugin.rider_salary.service.dashboard_service import (
    DashboardService,
    stale_periods_view_all_link,
)
from backend.plugin.rider_salary.service.period_service import PeriodService
from backend.plugin.rider_salary.tests.test_adversarial_cycle2_backend import (
    test_fix_c03_gross_8200,
    test_fix_c04_gross_7800,
    test_fix_c05a_gross_3500,
)

START = date(2026, 9, 1)
END = date(2026, 9, 30)


def test_gold_8200_7800_3500_unchanged() -> None:
    test_fix_c03_gross_8200()
    test_fix_c04_gross_7800()
    test_fix_c05a_gross_3500()


def test_period_list_api_exposes_stale_site_month() -> None:
    params = inspect.signature(get_periods_paginated).parameters
    assert 'stale' in params
    assert 'site_id' in params
    assert 'month' in params


def test_period_get_list_forwards_stale_site_month() -> None:
    src = inspect.getsource(PeriodService.get_list)
    assert 'stale=stale' in src
    assert 'site_id=site_id' in src
    assert 'month_start=month_start' in src
    assert 'month_end=month_end' in src
    assert 'parse_year_month(month)' in src


def test_hash9_stale_predicate_not_rewritten() -> None:
    src = inspect.getsource(CRUDSettlePeriod.get_select)
    assert 'if stale:' in src
    assert 'exists(' in src
    assert 'RiderSalaryPayroll.period_id == RiderSalarySettlePeriod.id' in src
    assert 'RiderSalaryPayroll.stale.is_(True)' in src
    assert 'RiderSalaryPayroll.deleted == 0' in src
    assert src.count('RiderSalaryPayroll.stale.is_(True)') == 1


def test_period_select_consumes_stale_site_and_month() -> None:
    async def _run() -> str:
        stmt = await settle_period_dao.get_select(
            site_id=4,
            rider_id=None,
            status=None,
            month_start=START,
            month_end=END,
            site_ids={4},
            stale=True,
            lock_due=None,
        )
        return str(stmt.compile(compile_kwargs={'literal_binds': True}))

    sql = anyio.run(_run).lower()
    assert 'stale' in sql
    assert 'true' in sql
    assert '2026-09-01' in sql
    assert '2026-09-30' in sql
    assert 'site_id' in sql
    assert '4' in sql
    assert '99' not in sql
    assert 'exists' in sql


def test_stale_view_all_carries_site_and_month() -> None:
    assert stale_periods_view_all_link(site_id=4, month='2026-09') == (
        '/rider-salary/period?stale=1&site_id=4&month=2026-09'
    )
    assert stale_periods_view_all_link(site_id=None, month='2026-09') == ('/rider-salary/period?stale=1&month=2026-09')
    src = inspect.getsource(DashboardService._stale_periods)
    assert 'stale_periods_view_all_link' in src
    assert "link='/rider-salary/period?stale=1'" not in src
    assert 'status=open' not in src
    assert 'period?id={period.id}' in src
    assert 'RiderSalaryPayroll.stale.is_(True)' in src
