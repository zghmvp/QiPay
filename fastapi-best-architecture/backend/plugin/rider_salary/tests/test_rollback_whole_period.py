"""P0-05 方案回退：反冲范围与周期重开范围一致，消除双发。

Q-04 未拍板，按推荐方案 A：引用该版本的已定稿单所在周期，全部未反冲的
已定稿、已发薪单一并反冲。``_persist_result`` 另加兜底，原单未反冲时不得新建补发单。

P1-03 集成基座（``tests/integration/``、``tests/golden/``）尚未就绪，验收写成服务层单测。
基座就绪后迁入集成用例，走 API 复现 E12：R005 原单 20 元，回退并重算全员后有效净额仍为 20，
不会变成 40；R004 为重算后的值；导出净额对照的最终实发与有效单一致。
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.payroll_daily import payroll_daily_dao
from backend.plugin.rider_salary.crud.payroll_detail import payroll_detail_dao
from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.schema.rollback import RollbackParam
from backend.plugin.rider_salary.service.calc_service import CalcDetail, CalcResult, _persist_result
from backend.plugin.rider_salary.service.export_service import (
    NET_HEADERS,
    SHEET_NET,
    SHEET_SUMMARY,
    SUMMARY_HEADERS,
    build_payroll_export_sheets,
)
from backend.plugin.rider_salary.service.payroll_view import build_rider_views
from backend.plugin.rider_salary.service.period_service import period_net_total
from backend.plugin.rider_salary.service.rollback_service import (
    is_reversal_target,
    rollback_service,
    scope_rollback_payrolls,
)

VERSION_ID = 10
OTHER_VERSION = 99
PERIOD_ID = 8
R004 = 4
R005 = 5
ORIGINAL_NET = Decimal('20.00')
RECALC_NET = Decimal('28.00')


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin', nickname='管理员', is_superuser=True))


def _version() -> SimpleNamespace:
    return SimpleNamespace(
        id=VERSION_ID,
        plan_id=1,
        version_no=2,
        status='active',
        is_used=True,
        mode_tag='custom',
        remark='',
        items_hash='hash',
        voided_time=None,
    )


def _plan() -> SimpleNamespace:
    return SimpleNamespace(id=1, name='十月方案', short_name='十月')


def _rollback_read_rows(stmt: object, payrolls: list[object]) -> list[object]:
    """模拟明细反查：版本 ID 来自明细，同周期反冲目标另查。"""
    sql = ' '.join(str(stmt).lower().split())
    where = sql.split(' where ', 1)[-1] if ' where ' in sql else ''
    if 'rs_rider_plan_binding' in sql:
        return []
    if 'rs_payroll_detail' in sql:
        return [
            int(row.id)
            for row in payrolls
            if VERSION_ID in list(getattr(row, 'plan_version_ids', None) or [])
            and int(getattr(row, 'deleted', 0) or 0) == 0
        ]
    if 'period_id in' in where:
        return [row for row in payrolls if is_reversal_target(row)]
    return [
        row
        for row in payrolls
        if VERSION_ID in list(getattr(row, 'plan_version_ids', None) or [])
        and int(getattr(row, 'deleted', 0) or 0) == 0
        and getattr(row, 'status', None) != PayrollStatus.voided.value
    ]


def _bind_rollback_reads(db: AsyncMock, payrolls: list[object]) -> None:
    """按语句把明细反查、薪资单读取和绑定查询分开，避免预览再扫全表。"""

    async def _scalars(stmt: object) -> MagicMock:  # ruff: ignore[unused-async]
        return _rows(_rollback_read_rows(stmt, payrolls))

    db.scalars = _scalars


def _rows(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = items
    return result


def _payroll(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 1,
        'period_id': PERIOD_ID,
        'rider_id': R004,
        'status': PayrollStatus.finalized.value,
        'kind': PayrollKind.normal.value,
        'reversed': False,
        'plan_version_ids': [VERSION_ID],
        'deleted': 0,
        'net': ORIGINAL_NET,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _slip(
    *,
    payroll_id: int,
    rider_id: int,
    kind: str = PayrollKind.normal.value,
    status: str = PayrollStatus.finalized.value,
    net: Decimal = ORIGINAL_NET,
    reversed_flag: bool = False,
    reversed_of_id: int | None = None,
    plan_version_ids: list[int] | None = None,
) -> RiderSalaryPayroll:
    row = RiderSalaryPayroll(
        period_id=PERIOD_ID,
        rider_id=rider_id,
        kind=kind,
        status=status,
        calc_version=1,
        reversed=reversed_flag,
        net=net,
        gross=net,
        per_order_total=net,
        plan_version_ids=plan_version_ids if plan_version_ids is not None else [VERSION_ID],
        reversed_of_id=reversed_of_id,
    )
    row.id = payroll_id
    return row


def _result(rider_id: int, net: str) -> CalcResult:
    amount = Decimal(net)
    return CalcResult(
        rider_id=rider_id,
        period_id=PERIOD_ID,
        payroll_id=None,
        order_count=1,
        valid_order_count=1,
        per_order_total=amount,
        daily_total=Decimal('0.00'),
        period_total=Decimal('0.00'),
        bonus_total=Decimal('0.00'),
        penalty_total=Decimal('0.00'),
        gross=amount,
        deduction_total=Decimal('0.00'),
        advance_deduction=Decimal('0.00'),
        advance_deductible=Decimal('0.00'),
        net=amount,
        plan_version_ids=[],
        warnings=[],
        details=[
            CalcDetail(
                rider_id=rider_id,
                subject_id=1,
                amount=amount,
                stage='per_order',
                include_in_gross=True,
                source='formula',
            )
        ],
        dailies=[],
    )


class _Ledger:
    """内存账本，同时充当回退和落库用的会话。"""

    def __init__(self, payrolls: list[RiderSalaryPayroll], period: SimpleNamespace) -> None:
        self.payrolls = payrolls
        self.period = period
        self.pending: list[object] = []
        self.next_id = max(int(row.id) for row in payrolls) + 1

    def add(self, obj: object) -> None:
        self.pending.append(obj)

    def add_all(self, objs: list[object]) -> None:
        self.pending.extend(objs)

    async def flush(self) -> None:
        for obj in self.pending:
            if not isinstance(obj, RiderSalaryPayroll):
                continue
            if getattr(obj, 'id', None) is None:
                obj.id = self.next_id
                self.next_id += 1
            if obj not in self.payrolls:
                self.payrolls.append(obj)
        self.pending.clear()

    async def scalars(self, stmt: object) -> MagicMock:
        sql = str(stmt).lower()
        if 'rs_rider_plan_binding' in sql:
            return _rows([])
        return _rows(_rollback_read_rows(stmt, self.payrolls))

    async def scalar(self, _stmt: object) -> SimpleNamespace:
        return self.period

    async def execute(self, _stmt: object) -> SimpleNamespace:
        return SimpleNamespace(rowcount=1)


def test_scope_reverses_whole_period_but_not_other_periods() -> None:
    """同周期未引用该版本的已定稿单纳入反冲；别的周期、已反冲单和反冲单不纳入。"""
    affected = _payroll(id=1, rider_id=R004, plan_version_ids=[VERSION_ID])
    untouched = _payroll(id=2, rider_id=R005, plan_version_ids=[OTHER_VERSION])
    other_period = _payroll(id=3, rider_id=6, period_id=9, plan_version_ids=[OTHER_VERSION])
    draft = _payroll(id=4, rider_id=R004, status=PayrollStatus.draft.value, plan_version_ids=[VERSION_ID])
    already = _payroll(id=5, rider_id=7, reversed=True, plan_version_ids=[OTHER_VERSION])
    reversal = _payroll(id=6, rider_id=R004, kind=PayrollKind.reversal.value, plan_version_ids=[VERSION_ID])
    paid = _payroll(id=7, rider_id=8, status=PayrollStatus.paid.value, plan_version_ids=[OTHER_VERSION])
    drafts, finalized, paid_rows = scope_rollback_payrolls(
        [affected, untouched, other_period, draft, already, reversal, paid],
        VERSION_ID,
    )
    assert [row.id for row in drafts] == [4]
    assert [row.id for row in finalized] == [1, 2]
    assert [row.id for row in paid_rows] == [7]


def test_preview_counts_unreferenced_finalized_in_same_period() -> None:
    """预览反冲数包含同周期未引用该版本的 R005，不含其他周期。"""
    payrolls = [
        _payroll(id=1, rider_id=R004, plan_version_ids=[VERSION_ID]),
        _payroll(id=2, rider_id=R005, plan_version_ids=[OTHER_VERSION]),
        _payroll(id=3, rider_id=6, period_id=9, plan_version_ids=[OTHER_VERSION]),
        _payroll(id=4, rider_id=R004, status=PayrollStatus.draft.value),
    ]
    db = AsyncMock()
    _bind_rollback_reads(db, payrolls)

    async def _case() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.rollback_service.PlanService.get_version_model',
                new=AsyncMock(return_value=_version()),
            ),
            patch(
                'backend.plugin.rider_salary.service.rollback_service.plan_dao.get',
                new=AsyncMock(return_value=_plan()),
            ),
        ):
            result = await rollback_service.preview(db, VERSION_ID, _request())
        assert result.payrolls_draft == 1
        assert result.payrolls_finalized == 2
        assert result.payrolls_paid == 0
        assert result.reversal_count == 2
        assert result.periods_reopened == 1
        assert {row.rider_id for row in result.payrolls if row.status == PayrollStatus.finalized.value} == {R004, R005}
        assert any('未引用该版本' in line for line in result.consequences)

    anyio.run(_case)


def test_e12_unaffected_rider_stays_20_after_rollback_and_recalc() -> None:
    """E12：R005 原单 20，整期反冲后重算仍为 20，不会变成 40；R004 为重算值。"""
    period = SimpleNamespace(id=PERIOD_ID, status=PeriodStatus.locked.value, reopened_time=None, reopened_by=None)
    originals = [
        _slip(payroll_id=1, rider_id=R004, plan_version_ids=[VERSION_ID]),
        _slip(payroll_id=2, rider_id=R005, plan_version_ids=[OTHER_VERSION]),
    ]
    ledger = _Ledger(originals, period)
    riders = {
        R004: SimpleNamespace(id=R004, job_no='R004', name='丁'),
        R005: SimpleNamespace(id=R005, job_no='R005', name='戊'),
    }

    def _alive(row: RiderSalaryPayroll) -> bool:
        return int(getattr(row, 'deleted', 0) or 0) == 0 and row.status != PayrollStatus.voided.value

    def _get_draft(_db: object, period_id: int, rider_id: int, kind: str) -> RiderSalaryPayroll | None:
        rows = [
            row
            for row in ledger.payrolls
            if _alive(row)
            and row.period_id == period_id
            and row.rider_id == rider_id
            and row.kind == kind
            and row.status == PayrollStatus.draft.value
        ]
        return max(rows, key=lambda row: int(row.id)) if rows else None

    def _get_current(_db: object, period_id: int, rider_id: int, kind: str) -> RiderSalaryPayroll | None:
        rows = [
            row
            for row in ledger.payrolls
            if _alive(row) and row.period_id == period_id and row.rider_id == rider_id and row.kind == kind
        ]
        return max(rows, key=lambda row: int(row.id)) if rows else None

    def _select_models(_db: object, *, period_id: int, deleted: int = 0) -> list[RiderSalaryPayroll]:
        return [
            row
            for row in ledger.payrolls
            if row.period_id == period_id and int(getattr(row, 'deleted', 0) or 0) == deleted
        ]

    async def _case() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.rollback_service.PlanService.get_version_model',
                new=AsyncMock(return_value=_version()),
            ),
            patch(
                'backend.plugin.rider_salary.service.rollback_service.plan_dao.get',
                new=AsyncMock(return_value=_plan()),
            ),
            patch.object(payroll_detail_dao, 'list_by_payroll', AsyncMock(return_value=[])),
            patch.object(payroll_detail_dao, 'logical_delete_by_payroll', AsyncMock()),
            patch.object(payroll_daily_dao, 'get_one', AsyncMock(return_value=None)),
            patch(
                'backend.plugin.rider_salary.service.rollback_service.audit_service.record',
                AsyncMock(),
            ),
            patch(
                'backend.plugin.rider_salary.service.payroll_service.audit_service.record',
                AsyncMock(),
            ),
            patch(
                'backend.plugin.rider_salary.service.calc_service.audit_service.record',
                AsyncMock(),
            ),
            patch.object(
                rollback_service,
                '_copy_draft',
                new=AsyncMock(return_value=SimpleNamespace(id=99)),
            ),
            patch(
                'backend.plugin.rider_salary.service.rollback_service.period_service.set_locked_flags',
                new=AsyncMock(),
            ) as flags,
            patch.object(payroll_dao, 'get_draft', AsyncMock(side_effect=_get_draft)),
            patch.object(payroll_dao, 'get_current', AsyncMock(side_effect=_get_current)),
            patch.object(payroll_dao, 'select_models', AsyncMock(side_effect=_select_models)),
        ):
            await rollback_service.rollback(
                ledger,
                VERSION_ID,
                RollbackParam(reason='方案配错', confirm_text=''),
                _request(),
            )
            assert period.status == PeriodStatus.reopened.value
            flags.assert_awaited_once()
            assert originals[0].reversed is True
            assert originals[1].reversed is True
            assert period_net_total(ledger.payrolls) == Decimal('0.00')

            await _persist_result(
                ledger,
                rider=riders[R004],
                period=period,
                result=_result(R004, '28.00'),
                operator=None,
            )
            await _persist_result(
                ledger,
                rider=riders[R005],
                period=period,
                result=_result(R005, '20.00'),
                operator=None,
            )

        views = {view.rider_id: view for view in build_rider_views(ledger.payrolls)}
        assert views[R005].final_net == ORIGINAL_NET
        assert views[R005].effective.kind == PayrollKind.supplement.value
        assert views[R004].final_net == RECALC_NET
        assert period_net_total([row for row in ledger.payrolls if row.rider_id == R005]) == ORIGINAL_NET
        assert period_net_total([row for row in ledger.payrolls if row.rider_id == R004]) == RECALC_NET
        assert views[R005].final_net != Decimal('40.00')

        sheets = build_payroll_export_sheets(
            ledger.payrolls,
            [],
            riders,
            site_name='测试站',
            period_text='2026-10-01~2026-10-31',
            plan_names={},
            subject_names={},
            order_nos={},
        )
        by_name = {name: (headers, rows) for name, headers, rows in sheets}
        net_headers, net_rows = by_name[SHEET_NET]
        summary_headers, summary_rows = by_name[SHEET_SUMMARY]
        assert net_headers == NET_HEADERS
        assert summary_headers == SUMMARY_HEADERS
        net_by_job = {row[0]: row for row in net_rows}
        final_idx = NET_HEADERS.index('最终实发')

        def cell(value: float) -> Decimal:
            return Decimal(str(value))

        assert cell(net_by_job['R005'][final_idx]) == views[R005].final_net
        assert cell(net_by_job['R004'][final_idx]) == views[R004].final_net
        assert cell(net_by_job['R005'][NET_HEADERS.index('原单')]) == ORIGINAL_NET
        assert cell(net_by_job['R005'][NET_HEADERS.index('反冲')]) == -ORIGINAL_NET
        assert cell(net_by_job['R005'][NET_HEADERS.index('补发')]) == ORIGINAL_NET
        assert cell(net_by_job['R005'][NET_HEADERS.index('净差')]) == Decimal('0.00')
        assert cell(net_by_job['R004'][NET_HEADERS.index('补发')]) == RECALC_NET
        summary_net = SUMMARY_HEADERS.index('实发')
        summary_by_job = {row[0]: cell(row[summary_net]) for row in summary_rows}
        assert summary_by_job == {'R004': RECALC_NET, 'R005': ORIGINAL_NET}
        assert sum(summary_by_job.values(), Decimal('0.00')) == ORIGINAL_NET + RECALC_NET

    anyio.run(_case)


def test_persist_refuses_supplement_when_original_not_reversed() -> None:
    """兜底：未反冲的 20 元原单不能再叠一张补发，有效净额保持 20 而不是 40。"""
    period = SimpleNamespace(
        id=PERIOD_ID,
        status=PeriodStatus.reopened.value,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
    )
    original = _slip(payroll_id=2, rider_id=R005, plan_version_ids=[OTHER_VERSION])
    ledger = _Ledger([original], period)
    rider = SimpleNamespace(id=R005, job_no='R005', name='戊')

    def _select_models(_db: object, *, period_id: int, deleted: int = 0) -> list[RiderSalaryPayroll]:
        return [
            row
            for row in ledger.payrolls
            if row.period_id == period_id and int(getattr(row, 'deleted', 0) or 0) == deleted
        ]

    async def _case() -> None:
        with (
            patch.object(payroll_dao, 'get_draft', AsyncMock(return_value=None)),
            patch.object(payroll_dao, 'get_current', AsyncMock(return_value=None)),
            patch.object(payroll_dao, 'select_models', AsyncMock(side_effect=_select_models)),
        ):
            with pytest.raises(errors.RequestError, match='该骑手原单尚未反冲，不能生成补发单'):
                await _persist_result(
                    ledger,
                    rider=rider,
                    period=period,
                    result=_result(R005, '20.00'),
                    operator=None,
                )
        assert ledger.payrolls == [original]
        assert period_net_total(ledger.payrolls) == ORIGINAL_NET
        views = build_rider_views(ledger.payrolls)
        assert views[0].final_net == ORIGINAL_NET
        assert views[0].final_net != Decimal('40.00')

    anyio.run(_case)
