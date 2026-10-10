"""P0-02 补发中的周期必须有补发单才能再锁账。

P1-03 集成基座（``tests/integration/``）尚未就绪，验收写成服务层单测：
E3 不补算锁账返回 400 并列出工号；补发草稿齐了才能锁，周期净额等于补发单合计；
沿用原单生成金额相同的补发草稿并写审计，周期净额等于原单。
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import DeductStatus, PayrollKind, PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.service.payroll_service import advance_deduction_diffs
from backend.plugin.rider_salary.service.period_service import (
    CARRY_FORWARD_NOTE,
    CARRY_FORWARD_REASON,
    active_supplement_net_total,
    apply_supplement_from_original,
    missing_supplement_lock_message,
    missing_supplement_rider_ids,
    period_net_total,
    period_service,
    reapply_advance_amount,
)


def _period(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 9,
        'site_id': 1,
        'rider_id': 0,
        'cycle_type': 'month',
        'start_date': date(2026, 9, 1),
        'end_date': date(2026, 9, 30),
        'status': PeriodStatus.reopened.value,
        'remark': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _site() -> SimpleNamespace:
    return SimpleNamespace(id=1, name='测试站', code='S1')


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin', nickname='管理员'))


def _rider(rider_id: int, job_no: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=rider_id, job_no=job_no, name=name)


def _money(value: str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value)


def _slip(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 1,
        'rider_id': 2,
        'kind': PayrollKind.normal.value,
        'status': PayrollStatus.finalized.value,
        'deleted': 0,
        'reversed': False,
        'stale': False,
        'net': Decimal('0.00'),
        'gross': Decimal('0.00'),
        'advance_deduction': Decimal('0.00'),
        'deduction_total': Decimal('0.00'),
        'per_order_total': Decimal('0.00'),
        'daily_total': Decimal('0.00'),
        'period_total': Decimal('0.00'),
        'bonus_total': Decimal('0.00'),
        'penalty_total': Decimal('0.00'),
        'order_count': 3,
        'valid_order_count': 3,
        'plan_version_ids': [4],
        'warnings': None,
        'calc_version': 1,
    }
    data.update(kwargs)
    for key in (
        'net',
        'gross',
        'advance_deduction',
        'deduction_total',
        'per_order_total',
        'daily_total',
        'period_total',
        'bonus_total',
        'penalty_total',
    ):
        data[key] = _money(data[key])  # type: ignore[arg-type]
    return SimpleNamespace(**data)


def _detail(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'rider_id': 2,
        'subject_id': 31,
        'amount': Decimal('100.00'),
        'stage': 'period',
        'include_in_gross': True,
        'source': 'formula',
        'biz_date': date(2026, 9, 1),
        'plan_version_id': 4,
        'plan_item_id': 8,
        'order_id': None,
        'calc_trace': {'结果': '100.00'},
    }
    data.update(kwargs)
    data['amount'] = _money(data['amount'])  # type: ignore[arg-type]
    return SimpleNamespace(**data)


def _scalars_then_empty(results: list[MagicMock]) -> AsyncMock:
    """预置批次用完后补空结果。锁账还会再查求值失败草稿，假会话不能在这里停住。"""
    pending = list(results)

    def _next(*_args: object, **_kwargs: object) -> MagicMock:
        if pending:
            return pending.pop(0)
        empty = MagicMock()
        empty.all.return_value = []
        return empty

    return AsyncMock(side_effect=_next)


def _scalar_db(*batches: list[SimpleNamespace]) -> AsyncMock:
    results: list[MagicMock] = []
    for batch in batches:
        item = MagicMock()
        item.all.return_value = batch
        results.append(item)
    db = AsyncMock()
    db.scalars = _scalars_then_empty(results)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()

    def _flush() -> None:
        for call in db.add.call_args_list:
            obj = call.args[0]
            if getattr(obj, 'id', None) is None and getattr(obj, 'period_id', None) is not None:
                obj.id = 501

    db.flush = AsyncMock(side_effect=_flush)
    return db


def test_missing_supplement_message_lists_job_nos() -> None:
    assert missing_supplement_lock_message(['R002']) == '存在缺补发单的骑手：工号 R002，请先补算或沿用原单'
    assert missing_supplement_lock_message(['R003', 'R002']) == (
        '存在缺补发单的骑手：工号 R003、R002，请先补算或沿用原单'
    )


def test_missing_supplement_ignores_reversal_voided_and_fresh_draft() -> None:
    payrolls = [
        _slip(id=1, rider_id=2, reversed=True, net='100.00'),
        _slip(id=2, rider_id=2, kind=PayrollKind.reversal.value, reversed=False, net='-100.00'),
        _slip(id=3, rider_id=3, reversed=True, status=PayrollStatus.voided.value, net='50.00'),
        _slip(id=4, rider_id=4, kind=PayrollKind.reversal.value, reversed=True, net='-20.00'),
    ]
    fresh = [_slip(id=5, rider_id=2, kind=PayrollKind.supplement.value, status=PayrollStatus.draft.value)]
    assert missing_supplement_rider_ids(payrolls, fresh) == []
    stale = [_slip(id=6, rider_id=2, kind=PayrollKind.supplement.value, status=PayrollStatus.draft.value, stale=True)]
    assert missing_supplement_rider_ids(payrolls, stale) == [2]


def test_e3_net_is_zero_until_supplement_exists() -> None:
    """原单与反冲单抵消后净额为 0；补上补发单后净额等于补发单，沿用原单后净额等于原单。"""
    original = _slip(id=1, net='100.00', gross='120.00', reversed=True)
    reversal = _slip(id=2, kind=PayrollKind.reversal.value, net='-100.00', gross='-120.00')
    assert period_net_total([original, reversal]) == Decimal('0.00')

    supplement = _slip(id=3, kind=PayrollKind.supplement.value, status=PayrollStatus.draft.value, net='80.00')
    chain = [original, reversal, supplement]
    assert period_net_total(chain) == Decimal('80.00')
    assert active_supplement_net_total(chain) == Decimal('80.00')

    carried = _slip(id=4, kind=PayrollKind.supplement.value, status=PayrollStatus.draft.value, net='100.00')
    carried_chain = [original, reversal, carried]
    assert period_net_total(carried_chain) == Decimal('100.00')
    assert period_net_total(carried_chain) == _money(original.net)


def test_reapply_advance_restores_the_reversed_deduction() -> None:
    advance = SimpleNamespace(
        remaining_amount=Decimal('30.00'),
        deducted_amount=Decimal('0.00'),
        amount=Decimal('30.00'),
        deduct_status=DeductStatus.none.value,
    )
    applied = reapply_advance_amount(advance, Decimal('-30.00'))
    assert applied == Decimal('30.00')
    assert advance.remaining_amount == Decimal('0.00')
    assert advance.deducted_amount == Decimal('30.00')
    assert advance.deduct_status == DeductStatus.done.value


def test_reapply_advance_stops_at_remaining() -> None:
    advance = SimpleNamespace(
        remaining_amount=Decimal('10.00'),
        deducted_amount=Decimal('20.00'),
        amount=Decimal('30.00'),
        deduct_status=DeductStatus.partial.value,
    )
    applied = reapply_advance_amount(advance, Decimal('-30.00'))
    assert applied == Decimal('10.00')
    assert advance.remaining_amount == Decimal('0.00')
    assert advance.deducted_amount == Decimal('30.00')


def test_apply_supplement_copies_original_amounts() -> None:
    original = _slip(net='100.00', gross='120.00', advance_deduction='20.00', calc_version=2, plan_version_ids=[9])
    payroll = SimpleNamespace()
    apply_supplement_from_original(payroll, original)
    assert payroll.kind == PayrollKind.supplement.value
    assert payroll.status == PayrollStatus.draft.value
    assert payroll.stale is False
    assert payroll.net == Decimal('100.00')
    assert payroll.gross == Decimal('120.00')
    assert payroll.advance_deduction == Decimal('20.00')
    assert payroll.plan_version_ids == [9]
    assert payroll.plan_version_ids is not original.plan_version_ids
    assert payroll.calc_version == 3
    assert CARRY_FORWARD_NOTE in payroll.warnings


def test_e3_lock_rejects_and_lists_missing_supplement_job_no() -> None:
    """有已反冲原单、没有补发草稿时锁账 400，工号出现在缺补发单文案里。"""
    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='100.00')
    reversal = _slip(id=12, rider_id=2, kind=PayrollKind.reversal.value, net='-100.00')
    db = _scalar_db([], [original, reversal], [_rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[2]),
            ),
            patch.object(period_service, 'set_locked_flags', AsyncMock()) as flags,
        ):
            with pytest.raises(errors.RequestError, match='存在缺补发单的骑手：工号 R002') as caught:
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
            assert '未算薪' not in (caught.value.msg or '')
            flags.assert_not_awaited()
        assert period.status == PeriodStatus.reopened.value
        assert period_net_total([original, reversal]) == Decimal('0.00')

    anyio.run(_case)


def test_reversed_rider_outside_expected_set_still_blocks_lock() -> None:
    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='40.00')
    db = _scalar_db([], [original], [_rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[]),
            ),
        ):
            with pytest.raises(errors.RequestError, match='工号 R002'):
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
        assert period.status == PeriodStatus.reopened.value

    anyio.run(_case)


def test_lock_lists_missing_supplements_in_original_id_order() -> None:
    period = _period()
    first = _slip(id=1, rider_id=3, reversed=True, net='10.00')
    second = _slip(id=2, rider_id=2, reversed=True, net='20.00')
    db = _scalar_db(
        [],
        [second, first],
        [_rider(3, 'R003', '丙'), _rider(2, 'R002', '乙')],
    )

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[]),
            ),
        ):
            with pytest.raises(errors.RequestError, match='工号 R003、R002'):
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')

    anyio.run(_case)


def test_lock_succeeds_after_supplement_and_net_equals_supplement_total() -> None:
    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='100.00')
    reversal = _slip(id=12, rider_id=2, kind=PayrollKind.reversal.value, net='-100.00')
    supplement = _slip(
        id=13,
        rider_id=2,
        kind=PayrollKind.supplement.value,
        status=PayrollStatus.draft.value,
        net='80.00',
        gross='80.00',
    )
    chain = [original, reversal, supplement]
    db = _scalar_db([supplement], [original, reversal, supplement], [])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[2]),
            ),
            patch.object(period_service, 'set_locked_flags', AsyncMock()) as flags,
            patch.object(period_service, '_mark_plan_versions_used', AsyncMock()),
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ),
        ):
            await period_service.lock(db=db, request=_request(), pk=9, reason='补算后锁账')
            flags.assert_awaited_once()
        assert period.status == PeriodStatus.locked.value
        assert period_net_total(chain) == active_supplement_net_total(chain) == Decimal('80.00')

    anyio.run(_case)


def test_stale_supplement_still_blocks_lock() -> None:
    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='100.00')
    stale = _slip(
        id=13,
        rider_id=2,
        kind=PayrollKind.supplement.value,
        status=PayrollStatus.draft.value,
        stale=True,
        net='80.00',
    )
    db = _scalar_db([stale], [original, stale], [_rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[2]),
            ),
        ):
            with pytest.raises(errors.RequestError, match='存在缺补发单的骑手：工号 R002'):
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')

    anyio.run(_case)


def test_lock_check_lists_missing_supplement() -> None:
    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='100.00')
    db = _scalar_db([], [original], [_rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[]),
            ),
        ):
            result = await period_service.lock_check(db=db, request=_request(), pk=9)
        assert result.can_lock is False
        assert result.empty is False
        assert [(item.job_no, item.rider_name) for item in result.missing_supplement] == [('R002', '乙')]
        assert result.uncalculated == []
        assert result.message == '存在缺补发单的骑手：工号 R002，请先补算或沿用原单'

    anyio.run(_case)


def test_carry_forward_copies_original_net_and_writes_audit() -> None:
    period = _period()
    original = _slip(
        id=11,
        rider_id=2,
        reversed=True,
        net='100.00',
        gross='120.00',
        advance_deduction='20.00',
        calc_version=2,
    )
    reversal = _slip(id=12, rider_id=2, kind=PayrollKind.reversal.value, net='-100.00', gross='-120.00')
    detail = _detail(amount='120.00')
    db = _scalar_db([original, reversal], [], [_rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.payroll_detail_dao.list_by_payroll',
                AsyncMock(return_value=[detail]),
            ) as list_details,
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ) as audit,
        ):
            result = await period_service.carry_forward(
                db=db,
                request=_request(),
                pk=9,
                rider_ids=None,
                reason=None,
            )
        assert result.created_count == 1
        assert result.rider_ids == [2]
        assert result.net_total == Decimal('100.00')
        created = next(call.args[0] for call in db.add.call_args_list if getattr(call.args[0], 'period_id', None))
        assert created.kind == PayrollKind.supplement.value
        assert created.status == PayrollStatus.draft.value
        assert created.stale is False
        assert created.net == Decimal('100.00')
        assert created.gross == Decimal('120.00')
        assert created.advance_deduction == Decimal('20.00')
        assert created.calc_version == 3
        assert CARRY_FORWARD_NOTE in created.warnings
        copied = next(call.args[0] for call in db.add.call_args_list if getattr(call.args[0], 'payroll_id', None))
        assert copied.amount == Decimal('120.00')
        assert copied.payroll_id == created.id
        list_details.assert_awaited_once()
        assert audit.await_args.kwargs['action'] == '沿用原单'
        assert audit.await_args.kwargs['reason'] == CARRY_FORWARD_REASON
        assert audit.await_args.kwargs['before']['source_payroll_id'] == 11
        assert audit.await_args.kwargs['before']['net'] == '100.00'
        assert audit.await_args.kwargs['after']['kind'] == PayrollKind.supplement.value
        assert audit.await_args.kwargs['after']['net'] == '100.00'
        assert 'before' in audit.await_args.kwargs
        assert 'after' in audit.await_args.kwargs
        assert period_net_total([original, reversal, created]) == Decimal('100.00')
        assert period.status == PeriodStatus.reopened.value

    anyio.run(_case)


def test_carry_forward_reapplies_advance_and_warns_when_short() -> None:
    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='70.00', gross='100.00', advance_deduction='30.00')
    detail = _detail(
        amount='-30.00',
        source='advance',
        include_in_gross=False,
        subject_id=0,
        calc_trace={'advance_id': 7},
    )
    advance = SimpleNamespace(
        id=7,
        remaining_amount=Decimal('10.00'),
        deducted_amount=Decimal('0.00'),
        amount=Decimal('30.00'),
        deduct_status=DeductStatus.none.value,
        deleted=0,
    )
    db = _scalar_db([original], [], [_rider(2, 'R002', '乙')])
    db.scalar = AsyncMock(return_value=advance)

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.payroll_detail_dao.list_by_payroll',
                AsyncMock(return_value=[detail]),
            ),
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ),
        ):
            result = await period_service.carry_forward(
                db=db,
                request=_request(),
                pk=9,
                rider_ids=[2],
                reason='金额未变',
            )
        created = next(call.args[0] for call in db.add.call_args_list if getattr(call.args[0], 'period_id', None))
        copied = next(
            call.args[0] for call in db.add.call_args_list if getattr(call.args[0], 'source', None) == 'advance'
        )
        assert result.net_total == Decimal('90.00')
        assert created.net == Decimal('90.00')
        assert created.advance_deduction == Decimal('10.00')
        assert copied.amount == Decimal('-10.00')
        assert advance.remaining_amount == Decimal('0.00')
        assert advance.deducted_amount == Decimal('10.00')
        assert any('余额不足' in item for item in created.warnings)
        assert advance_deduction_diffs([advance], [original, created], [copied]) == []

    anyio.run(_case)


def test_carry_forward_refreshes_stale_supplement_instead_of_adding_another() -> None:
    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='100.00', gross='100.00')
    stale = _slip(
        id=20,
        rider_id=2,
        kind=PayrollKind.supplement.value,
        status=PayrollStatus.draft.value,
        stale=True,
        net='1.00',
    )
    db = _scalar_db([original], [stale], [_rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.payroll_detail_dao.list_by_payroll',
                AsyncMock(return_value=[]),
            ),
            patch(
                'backend.plugin.rider_salary.service.period_service.payroll_detail_dao.logical_delete_by_payroll',
                AsyncMock(),
            ) as wipe,
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ) as audit,
        ):
            result = await period_service.carry_forward(
                db=db,
                request=_request(),
                pk=9,
                rider_ids=None,
                reason='沿用',
            )
        assert result.created_count == 1
        assert result.net_total == Decimal('100.00')
        assert stale.net == Decimal('100.00')
        assert stale.stale is False
        assert stale.kind == PayrollKind.supplement.value
        wipe.assert_awaited_once()
        assert audit.await_args.kwargs['target_id'] == 20
        assert not any(getattr(call.args[0], 'period_id', None) for call in db.add.call_args_list)

    anyio.run(_case)


def test_carry_forward_rejects_open_period_and_unknown_rider() -> None:
    open_period = _period(status=PeriodStatus.open.value)
    db = _scalar_db()

    async def _open_case() -> None:
        with patch.object(period_service, '_load_visible', AsyncMock(return_value=(open_period, _site(), None))):
            with pytest.raises(errors.RequestError, match='不允许沿用原单'):
                await period_service.carry_forward(
                    db=db,
                    request=_request(),
                    pk=9,
                    rider_ids=None,
                    reason=None,
                )
        db.scalars.assert_not_called()

    anyio.run(_open_case)

    period = _period()
    original = _slip(id=11, rider_id=2, reversed=True, net='100.00')
    unknown_db = _scalar_db([original], [], [])

    async def _unknown_case() -> None:
        with patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))):
            with pytest.raises(errors.RequestError, match='以下骑手无需沿用原单：工号 99'):
                await period_service.carry_forward(
                    db=unknown_db,
                    request=_request(),
                    pk=9,
                    rider_ids=[99],
                    reason=None,
                )

    anyio.run(_unknown_case)
