"""P0-06 方案回退：作废草稿前归还预支，修正预览计数。

验收用例目前写成服务层单测。P1-03 集成基座就绪后，迁到
``backend/plugin/rider_salary/tests/integration/``，改成走 API 的 E8 场景
（回退后预支 remaining 恢复为 3000、deduct_status 恢复为可抵扣），
并直接执行 ``ADVANCE_DEDUCTION_CONSISTENCY_SQL`` 断言 0 行差异。
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from backend.plugin.rider_salary.enums import DeductStatus, DetailSource, PayrollKind, PayrollStatus
from backend.plugin.rider_salary.schema.rollback import RollbackParam
from backend.plugin.rider_salary.service.payroll_service import (
    ADVANCE_DEDUCTION_CONSISTENCY_SQL,
    PayrollService,
    advance_deduction_diffs,
    apply_advance_restore,
    find_advance_deduction_mismatches,
    payroll_service,
)
from backend.plugin.rider_salary.service.rollback_service import (
    classify_rollback_payrolls,
    is_reversal_target,
    rollback_service,
)

D = Decimal
VERSION_ID = 10


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin', nickname='管理员', is_superuser=True))


def _version() -> SimpleNamespace:
    return SimpleNamespace(
        id=VERSION_ID,
        plan_id=1,
        version_no=3,
        status='active',
        is_used=True,
        mode_tag='custom',
        remark='',
        items_hash='hash',
        voided_time=None,
    )


def _plan() -> SimpleNamespace:
    return SimpleNamespace(id=1, name='十月方案', short_name='十月')


def _payroll(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 1,
        'period_id': 8,
        'rider_id': 2,
        'status': PayrollStatus.draft.value,
        'kind': PayrollKind.normal.value,
        'reversed': False,
        'plan_version_ids': [VERSION_ID],
        'deleted': 0,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _rollback_read_rows(stmt: object, payrolls: list[SimpleNamespace]) -> list[object]:
    """模拟明细反查：版本 ID 来自明细，同周期反冲目标另查。"""
    sql = ' '.join(str(stmt).lower().split())
    where = sql.split(' where ', 1)[-1] if ' where ' in sql else ''
    if 'rs_rider_plan_binding' in sql:
        return []
    if 'rs_payroll_detail' in sql:
        return [int(row.id) for row in payrolls if VERSION_ID in list(getattr(row, 'plan_version_ids', None) or [])]
    if 'period_id in' in where:
        return [row for row in payrolls if is_reversal_target(row)]
    return [
        row
        for row in payrolls
        if VERSION_ID in list(getattr(row, 'plan_version_ids', None) or [])
        and getattr(row, 'status', None) != PayrollStatus.voided.value
    ]


def _bind_rollback_reads(db: AsyncMock, payrolls: list[SimpleNamespace]) -> None:
    """明细反查返回引用该版本的薪资单 ID，薪资单查询返回传入列表。"""

    async def _scalars(stmt: object) -> MagicMock:  # ruff: ignore[unused-async]
        return _rows(_rollback_read_rows(stmt, payrolls))

    db.scalars = _scalars


def _rows(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = items
    return result


def _advance_e8() -> SimpleNamespace:
    """E8：3000 已全部抵扣，承载它的草稿即将作废。"""
    return SimpleNamespace(
        id=5,
        amount=D('3000.00'),
        remaining_amount=D('0.00'),
        deducted_amount=D('3000.00'),
        deduct_status=DeductStatus.done.value,
        deleted=0,
    )


def _advance_detail(payroll_id: int, advance_id: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        payroll_id=payroll_id,
        source=DetailSource.advance.value,
        amount=D('-3000.00'),
        calc_trace={'advance_id': advance_id},
        deleted=0,
    )


def test_classify_skips_reversal_slips_and_already_reversed() -> None:
    drafts, finalized, paid = classify_rollback_payrolls([
        _payroll(id=1, status=PayrollStatus.draft.value),
        _payroll(id=2, status=PayrollStatus.finalized.value),
        _payroll(id=3, status=PayrollStatus.paid.value),
        _payroll(id=4, status=PayrollStatus.finalized.value, reversed=True),
        _payroll(id=5, status=PayrollStatus.finalized.value, kind=PayrollKind.reversal.value),
        _payroll(id=6, status=PayrollStatus.paid.value, reversed=True),
    ])
    assert [row.id for row in drafts] == [1]
    assert [row.id for row in finalized] == [2]
    assert [row.id for row in paid] == [3]
    assert len(finalized) + len(paid) == 2


def test_preview_counts_match_reversal_targets() -> None:
    """反冲单和已被反冲的单不再计入已定稿/已发薪，计数等于实际将反冲的单数。"""
    payrolls = [
        _payroll(id=1, status=PayrollStatus.draft.value, period_id=8),
        _payroll(id=2, status=PayrollStatus.finalized.value, period_id=8),
        _payroll(id=3, status=PayrollStatus.paid.value, period_id=9),
        _payroll(id=4, status=PayrollStatus.finalized.value, reversed=True, period_id=8),
        _payroll(id=5, status=PayrollStatus.finalized.value, kind=PayrollKind.reversal.value, period_id=8),
        _payroll(id=6, status=PayrollStatus.draft.value, plan_version_ids=[99]),
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
        assert result.payrolls_finalized == 1
        assert result.payrolls_paid == 1
        assert result.reversal_count == result.payrolls_finalized + result.payrolls_paid
        assert result.periods_reopened == 2
        assert result.has_paid is True
        assert [row.id for row in result.payrolls] == [1, 2, 3]
        assert any('下次算薪将新建草稿' in line for line in result.consequences)
        assert all('标记需重算' not in line for line in result.consequences)
        assert result.consequences[0] == '该方案已执行发薪操作，回退将产生财务影响'

    anyio.run(_case)


def test_preview_without_reversal_target_has_zero_counts() -> None:
    payrolls = [
        _payroll(id=4, status=PayrollStatus.finalized.value, reversed=True),
        _payroll(id=5, status=PayrollStatus.paid.value, reversed=True),
        _payroll(id=6, status=PayrollStatus.finalized.value, kind=PayrollKind.reversal.value),
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
        assert result.payrolls_draft == 0
        assert result.payrolls_finalized == 0
        assert result.payrolls_paid == 0
        assert result.reversal_count == 0
        assert result.has_paid is False
        assert result.payrolls == []

    anyio.run(_case)


def test_e8_rollback_restores_advance_before_void_and_skips_mark_stale() -> None:
    """作废草稿前归还 3000；反冲单与已反冲单不重复处理；不再 mark_stale。"""
    import backend.plugin.rider_salary.service.rollback_service as rollback_mod

    advance = _advance_e8()
    draft = _payroll(id=3, status=PayrollStatus.draft.value, period_id=8)
    finalized = _payroll(id=4, status=PayrollStatus.finalized.value, period_id=8)
    already = _payroll(id=5, status=PayrollStatus.finalized.value, reversed=True, period_id=8)
    reversal = _payroll(id=6, status=PayrollStatus.finalized.value, kind=PayrollKind.reversal.value, period_id=8)
    payrolls = [draft, finalized, already, reversal]
    detail = _advance_detail(draft.id)
    period = SimpleNamespace(id=8, status='locked', reopened_time=None, reopened_by=None)
    db = AsyncMock()
    _bind_rollback_reads(db, payrolls)
    db.scalar = AsyncMock(side_effect=[advance, period])
    statuses: list[str] = []

    async def spy_restore(session: AsyncMock, payroll: SimpleNamespace) -> None:
        statuses.append(payroll.status)
        await PayrollService.restore_advances_from_payroll(payroll_service, session, payroll)

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
            patch(
                'backend.plugin.rider_salary.service.payroll_service.payroll_detail_dao.list_by_payroll',
                new=AsyncMock(return_value=[detail]),
            ),
            patch.object(rollback_mod.payroll_service, 'restore_advances_from_payroll', spy_restore),
            patch.object(rollback_mod.payroll_service, 'create_reversal', new=AsyncMock()) as reversal_mock,
            patch.object(rollback_mod.period_service, 'set_locked_flags', new=AsyncMock()) as flags,
            patch.object(
                rollback_mod.RollbackService,
                '_copy_draft',
                new=AsyncMock(return_value=SimpleNamespace(id=99)),
            ),
            patch.object(rollback_mod.audit_service, 'record', new=AsyncMock()) as audit,
        ):
            copied = await rollback_service.rollback(
                db,
                VERSION_ID,
                RollbackParam(reason='方案配错', confirm_text=''),
                _request(),
            )
        assert copied.id == 99
        reversal_mock.assert_awaited_once()
        assert reversal_mock.await_args.args[1].id == finalized.id
        flags.assert_awaited_once()
        assert flags.await_args.kwargs['locked'] is False
        description = audit.await_args.kwargs['description']
        assert '下次算薪将新建草稿' in description
        assert '作废草稿薪资1条' in description
        assert '生成反冲单1条' in description
        assert '标记需重算' not in description

    anyio.run(_case)
    assert statuses == [PayrollStatus.draft.value]
    assert draft.status == PayrollStatus.voided.value
    assert advance.remaining_amount == D('3000.00')
    assert advance.deducted_amount == D('0.00')
    assert advance.deduct_status == DeductStatus.none.value
    assert already.reversed is True
    assert reversal.status == PayrollStatus.finalized.value
    assert not hasattr(rollback_mod, 'mark_stale')
    assert period.status == 'reopened'


def test_e8_consistency_is_empty_after_restore() -> None:
    """作废单上的抵扣明细不计入；归还后 deducted 与有效明细合计没有差异。"""
    advance = _advance_e8()
    voided = _payroll(id=3, status=PayrollStatus.voided.value)
    detail = _advance_detail(voided.id)
    before = advance_deduction_diffs([advance], [voided], [detail])
    assert before == [(5, D('3000.00'), D('0.00'))]

    apply_advance_restore(advance, D('3000.00'))
    assert advance.remaining_amount == D('3000.00')
    assert advance.deduct_status == DeductStatus.none.value
    assert advance_deduction_diffs([advance], [voided], [detail]) == []

    held = _payroll(id=7, status=PayrollStatus.draft.value)
    held_advance = _advance_e8()
    assert advance_deduction_diffs([held_advance], [held], [_advance_detail(held.id)]) == []

    restored = SimpleNamespace(
        id=5,
        amount=D('3000.00'),
        remaining_amount=D('3000.00'),
        deducted_amount=D('0.00'),
        deduct_status=DeductStatus.none.value,
        deleted=0,
    )
    original = _payroll(id=8, status=PayrollStatus.finalized.value, reversed=True)
    reversal = _payroll(id=9, status=PayrollStatus.finalized.value, kind=PayrollKind.reversal.value)
    assert advance_deduction_diffs([restored], [original, reversal], [_advance_detail(original.id)]) == []


def test_consistency_sql_excludes_voided_reversed_and_reversal() -> None:
    sql = ADVANCE_DEDUCTION_CONSISTENCY_SQL
    assert "d.source = 'advance'" in sql
    assert "p.status <> 'voided'" in sql
    assert 'p.reversed = false' in sql
    assert "p.kind <> 'reversal'" in sql
    assert 'a.deducted_amount' in sql
    assert 'd.deleted = 0' in sql
    assert 'p.deleted = 0' in sql


def test_find_advance_deduction_mismatches_returns_sql_rows() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    async def _case() -> None:
        rows = await find_advance_deduction_mismatches(db)
        assert rows == []
        statement = db.execute.await_args.args[0]
        assert "p.status <> 'voided'" in str(statement)

    anyio.run(_case)


def test_restore_advances_from_payroll_returns_remaining() -> None:
    advance = _advance_e8()
    payroll = _payroll(id=3)
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=advance)

    async def _case() -> None:
        with patch(
            'backend.plugin.rider_salary.service.payroll_service.payroll_detail_dao.list_by_payroll',
            new=AsyncMock(return_value=[_advance_detail(payroll.id)]),
        ):
            await payroll_service.restore_advances_from_payroll(db, payroll)

    anyio.run(_case)
    assert advance.remaining_amount == D('3000.00')
    assert advance.deducted_amount == D('0.00')
    assert advance.deduct_status == DeductStatus.none.value


def test_non_superuser_preview_forbidden() -> None:
    from backend.common.exception import errors

    request = SimpleNamespace(user=SimpleNamespace(is_superuser=False))

    async def _case() -> None:
        with pytest.raises(errors.ForbiddenError, match='仅超级管理员可执行方案回退'):
            await rollback_service.preview(AsyncMock(), VERSION_ID, request)

    anyio.run(_case)
