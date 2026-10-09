"""P6-02：离职 90 天内只读，往期工资条走有效单读层。"""

import inspect

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, get_args, get_origin
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Delete, Insert, Update

from backend.common.exception import errors
from backend.plugin.rider_salary.api.v1.me import cancel_me_advance, create_me_advance, update_me_password
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam
from backend.plugin.rider_salary.service.me_service import aggregate_slip_lines, me_service
from backend.plugin.rider_salary.utils.deps import (
    DependsCurrentRider,
    DependsWritableRider,
    get_current_rider,
    get_writable_rider,
)
from backend.plugin.rider_salary.utils.password_gate import MUST_CHANGE_PASSWORD_CODE
from backend.plugin.rider_salary.utils.read_grace import (
    NOT_RIDER_MSG,
    RESIGNED_EXPIRED_MSG,
    RESIGNED_READ_GRACE_DAYS,
    resigned_read_until,
    rider_can_read,
)


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _Db:
    def __init__(self, rider: object | None) -> None:
        self.rider = rider
        self.statements: list[object] = []

    async def scalar(self, stmt: object) -> object | None:
        self.statements.append(stmt)
        return self.rider


class _QueueSession:
    def __init__(self, *, scalars: list[list[object]], scalar: list[object] | None = None) -> None:
        self._scalars = list(scalars)
        self._scalar = list(scalar or [])
        self.statements: list[object] = []

    async def scalars(self, stmt: object) -> _Rows:
        self.statements.append(stmt)
        return _Rows(self._scalars.pop(0))

    async def scalar(self, stmt: object) -> object:
        self.statements.append(stmt)
        return self._scalar.pop(0)


def _request(path: str, method: str) -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=9), url=SimpleNamespace(path=path), method=method)


def _rider(**kwargs: object) -> SimpleNamespace:
    base: dict[str, object] = {
        'id': 7,
        'user_id': 9,
        'status': 'on_job',
        'leave_date': None,
        'must_change_password': False,
        'deleted': 0,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _payroll(**kwargs: object) -> SimpleNamespace:
    base: dict[str, object] = {
        'deleted': 0,
        'status': 'finalized',
        'kind': 'normal',
        'reversed': False,
        'calc_version': 1,
        'id': 1,
        'period_id': 1,
        'rider_id': 7,
        'gross': Decimal('100.00'),
        'net': Decimal('80.00'),
        'deduction_total': Decimal('10.00'),
        'advance_deduction': Decimal('10.00'),
        'order_count': 3,
        'calc_time': None,
        'stale': False,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _detail(**kwargs: object) -> SimpleNamespace:
    base: dict[str, object] = {
        'id': 1,
        'payroll_id': 1,
        'deleted': 0,
        'stage': 'per_order',
        'source': 'formula',
        'subject_id': 11,
        'amount': Decimal('40.00'),
        'calc_trace': {'公式': '秘密公式'},
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _sql(stmt: object) -> str:
    compiled = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    return ' '.join(compiled.split())


def test_grace_is_ninety_days_inclusive() -> None:
    """Q-05 推荐 90 天，含截止日当天，超过一天才拒绝。"""
    assert RESIGNED_READ_GRACE_DAYS == 90
    leave = date(2026, 7, 11)
    rider = _rider(status='resigned', leave_date=leave)
    assert resigned_read_until(leave) == date(2026, 10, 9)
    assert rider_can_read(rider, date(2026, 10, 9)) is True
    assert rider_can_read(rider, date(2026, 10, 10)) is False
    assert rider_can_read(_rider(status='resigned', leave_date=None), date(2026, 10, 9)) is False
    assert rider_can_read(_rider(status='on_job', leave_date=date(2020, 1, 1)), date(2026, 10, 9)) is True


def test_current_rider_grace_password_and_admin() -> None:
    async def _run() -> None:
        clock = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
        within = _rider(status='resigned', leave_date=date(2026, 7, 11), must_change_password=True)
        expired = _rider(status='resigned', leave_date=date(2026, 7, 10), must_change_password=True)
        on_job = _rider(must_change_password=True)
        profile = '/api/v1/rider-salary/me/profile'
        password = '/api/v1/rider-salary/me/password'
        with patch('backend.plugin.rider_salary.utils.read_grace.timezone') as tz:
            tz.now.return_value = clock
            allowed = await get_current_rider(_request(password, 'PUT'), _Db(within))
            assert allowed is within
            with pytest.raises(errors.RequestError) as must_change:
                await get_current_rider(_request(profile, 'GET'), _Db(within))
            assert must_change.value.code == MUST_CHANGE_PASSWORD_CODE
            with pytest.raises(errors.RequestError) as on_job_change:
                await get_current_rider(_request(profile, 'GET'), _Db(on_job))
            assert on_job_change.value.code == MUST_CHANGE_PASSWORD_CODE
            with pytest.raises(errors.ForbiddenError) as denied:
                await get_current_rider(_request(profile, 'GET'), _Db(expired))
            assert denied.value.msg == RESIGNED_EXPIRED_MSG
            assert '查阅期限' in str(denied.value.msg)
            db = _Db(None)
            with pytest.raises(errors.ForbiddenError) as admin:
                await get_current_rider(_request(profile, 'GET'), db)
            assert admin.value.msg == NOT_RIDER_MSG
            assert '查阅期限' not in str(admin.value.msg)
            assert 'rs_rider' in _sql(db.statements[0])
            assert 'user_id' in _sql(db.statements[0])
            assert 'deleted' in _sql(db.statements[0])

    anyio.run(_run)


def test_writable_rider_rejects_resigned_advance_writes() -> None:
    async def _run() -> None:
        rider = _rider(status='resigned', leave_date=date(2026, 9, 1))
        request = _request('/api/v1/rider-salary/me/profile', 'GET')
        with patch('backend.plugin.rider_salary.utils.read_grace.timezone') as tz:
            tz.now.return_value = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
            assert await get_current_rider(request, _Db(rider)) is rider
        with pytest.raises(errors.RequestError, match='不能申请预支'):
            get_writable_rider(_request('/api/v1/rider-salary/me/advances', 'POST'), rider)
        with pytest.raises(errors.RequestError, match='不能撤回预支'):
            get_writable_rider(_request('/api/v1/rider-salary/me/advances/8/cancel', 'POST'), rider)
        on_job = _rider()
        assert get_writable_rider(_request('/api/v1/rider-salary/me/advances', 'POST'), on_job) is on_job

    anyio.run(_run)


def test_password_route_stays_readable_and_advance_routes_are_writable() -> None:
    """改密继续走只读依赖，预支申请和撤回走写依赖。"""

    def _depends(func: object) -> tuple[object, ...]:
        annotation = func.__annotations__['rider']
        assert get_origin(annotation) is Annotated
        return get_args(annotation)

    assert DependsWritableRider in _depends(create_me_advance)
    assert DependsWritableRider in _depends(cancel_me_advance)
    assert DependsCurrentRider in _depends(update_me_password)
    assert DependsWritableRider not in _depends(update_me_password)


def test_resigned_service_refuses_advance_before_writing() -> None:
    async def _run() -> None:
        rider = _rider(status='resigned', leave_date=date(2026, 9, 1))
        obj = CreateMeAdvanceParam(amount=Decimal('10.00'), reason='周转')
        with pytest.raises(errors.RequestError, match='不能申请预支'):
            await me_service.create_advance(db=None, request=None, rider=rider, obj=obj)  # type: ignore[arg-type]
        with pytest.raises(errors.RequestError, match='不能撤回预支'):
            await me_service.cancel_advance(db=None, request=None, rider=rider, pk=3)  # type: ignore[arg-type]

    anyio.run(_run)


def test_profile_marks_resigned_rider_read_only() -> None:
    async def _run() -> None:
        rider = SimpleNamespace(
            id=7,
            site_id=2,
            job_no='D7',
            name='甲',
            employ_type='part_time',
            hire_date=date(2026, 1, 1),
            advance_limit=None,
            status='resigned',
            leave_date=date(2026, 8, 1),
        )
        site = SimpleNamespace(name='一号站', advance_limit=None)
        with (
            patch('backend.plugin.rider_salary.service.me_service.site_dao.get', AsyncMock(return_value=site)),
            patch(
                'backend.plugin.rider_salary.service.me_service.resolve_effective_plans',
                AsyncMock(return_value=[]),
            ),
            patch(
                'backend.plugin.rider_salary.service.me_service.advance_dao.list_in_flight',
                AsyncMock(return_value=[]),
            ),
        ):
            data = await me_service.profile(db=AsyncMock(), rider=rider)  # type: ignore[arg-type]
        assert data.read_only is True
        assert data.status == 'resigned'
        assert data.status_label == '离职'
        assert data.read_until == date(2026, 10, 30)
        assert data.leave_date == date(2026, 8, 1)

    anyio.run(_run)


def test_payslips_use_effective_settled_slips_without_writing() -> None:
    """补发压过已反冲原单；草稿、作废、反冲后未补发都不出现。不预估、不写库。"""
    payrolls = [
        _payroll(id=1, period_id=1, kind='normal', reversed=True, calc_version=1, net=Decimal('10.00')),
        _payroll(id=2, period_id=1, kind='supplement', calc_version=2, net=Decimal('90.00'), gross=Decimal('90.00')),
        _payroll(id=3, period_id=2, status='draft'),
        _payroll(id=4, period_id=3, reversed=True),
        _payroll(id=5, period_id=4, status='paid', net=Decimal('50.00')),
        _payroll(id=6, period_id=5, status='voided'),
    ]
    periods = [
        SimpleNamespace(id=1, start_date=date(2026, 9, 1), end_date=date(2026, 9, 15), status='paid', deleted=0),
        SimpleNamespace(id=4, start_date=date(2026, 10, 1), end_date=date(2026, 10, 15), status='locked', deleted=0),
    ]
    db = _QueueSession(scalars=[payrolls, periods])

    async def _run() -> None:
        with (
            patch('backend.plugin.rider_salary.service.me_service.calculate_rider_period', AsyncMock()) as calc,
            patch('backend.plugin.rider_salary.service.me_service.set_cached_text', AsyncMock()) as store,
            patch('backend.plugin.rider_salary.service.me_service.get_cached_text', AsyncMock()) as read_cache,
        ):
            rows = await me_service.payslips(db=db, rider=_rider())  # type: ignore[arg-type]
            calc.assert_not_called()
            store.assert_not_called()
            read_cache.assert_not_called()
        assert [row.id for row in rows] == [5, 2]
        assert rows[0].period_range == '10-01~10-15'
        assert rows[0].net == Decimal('50.00')
        assert rows[1].kind_label == '补发'
        assert rows[1].net == Decimal('90.00')
        assert all(not isinstance(stmt, (Insert, Update, Delete)) for stmt in db.statements)
        assert 'rs_payroll' in _sql(db.statements[0])
        assert 'rs_settle_period' in _sql(db.statements[1])

    anyio.run(_run)


def test_payslip_detail_hides_trace_and_uses_effective_lines() -> None:
    supplement = _payroll(id=2, period_id=1, kind='supplement', calc_version=2, net=Decimal('90.00'))
    original = _payroll(id=1, period_id=1, kind='normal', reversed=True, calc_version=1, net=Decimal('10.00'))
    details = [
        _detail(id=10, payroll_id=1, amount=Decimal('999.00'), calc_trace={'公式': '原单秘密'}),
        _detail(id=11, payroll_id=2, subject_id=11, amount=Decimal('30.00'), calc_trace={'公式': '秘密公式'}),
        _detail(id=12, payroll_id=2, subject_id=11, amount=Decimal('10.00')),
        _detail(id=13, payroll_id=2, subject_id=12, source='advance', amount=Decimal('-5.00'), stage='period'),
    ]
    period = SimpleNamespace(
        id=1,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
        status='paid',
        deleted=0,
    )
    subjects = [
        SimpleNamespace(id=11, name='配送提成', deleted=0),
        SimpleNamespace(id=12, name='预支抵扣', deleted=0),
    ]
    db = _QueueSession(
        scalar=[supplement, period],
        scalars=[[original, supplement], details, subjects],
    )

    async def _run() -> None:
        data = await me_service.payslip(db=db, rider=_rider(), pk=2)  # type: ignore[arg-type]
        dumped = data.model_dump_json()
        assert 'calc_trace' not in dumped
        assert '秘密公式' not in dumped
        assert '原单秘密' not in dumped
        assert '999' not in dumped
        assert data.net == Decimal('90.00')
        assert [(line.subject_name, line.amount, line.line_count) for line in data.lines] == [
            ('配送提成', Decimal('40.00'), 2),
            ('预支抵扣', Decimal('-5.00'), 1),
        ]
        assert data.lines[0].stage_label == '逐单'
        assert data.lines[1].source_label == '预支抵扣'
        missing = _QueueSession(scalar=[original], scalars=[[original, supplement], details])
        with pytest.raises(errors.NotFoundError, match='已失效'):
            await me_service.payslip(db=missing, rider=_rider(), pk=1)  # type: ignore[arg-type]
        absent = _QueueSession(scalar=[None], scalars=[])
        with pytest.raises(errors.NotFoundError, match='工资条不存在'):
            await me_service.payslip(db=absent, rider=_rider(), pk=99)  # type: ignore[arg-type]

    anyio.run(_run)


def test_aggregate_slip_lines_does_not_keep_trace() -> None:
    lines = aggregate_slip_lines([
        _detail(amount=Decimal('1.50')),
        _detail(id=2, amount=Decimal('2.50')),
    ])
    assert len(lines) == 1
    assert lines[0].amount == Decimal('4.00')
    assert lines[0].line_count == 2
    assert not hasattr(lines[0], 'calc_trace')


def test_estimate_still_uses_cache_and_does_not_persist() -> None:
    source = inspect.getsource(me_service.payroll_estimate)
    assert 'persist=False' in source
    assert '_cached_estimate' in source
    assert '_store_estimate' in source
