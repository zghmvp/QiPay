from types import SimpleNamespace

from backend.plugin.rider_salary.service.order_service import (
    ORDER_CREATE_SUCCESS_MSG,
    ORDER_FIX_SUCCESS_MSG,
    ORDER_WRITE_STALE_HINT,
    pick_covering_calc_period,
)


def test_pick_covering_calc_period_only_open_or_reopened() -> None:
    assert pick_covering_calc_period(SimpleNamespace(id=1, status='open')).id == 1
    assert pick_covering_calc_period(SimpleNamespace(id=2, status='reopened')).id == 2
    assert pick_covering_calc_period(SimpleNamespace(id=3, status='locked')) is None
    assert pick_covering_calc_period(SimpleNamespace(id=4, status='paid')) is None
    assert pick_covering_calc_period(None) is None


def test_order_write_messages_name_stale_not_paid() -> None:
    assert '需重算' in ORDER_WRITE_STALE_HINT
    assert '尚未出账' in ORDER_WRITE_STALE_HINT
    assert '需重算' in ORDER_CREATE_SUCCESS_MSG
    assert '尚未出账' in ORDER_CREATE_SUCCESS_MSG
    assert '需重算' in ORDER_FIX_SUCCESS_MSG
    assert '尚未出账' in ORDER_FIX_SUCCESS_MSG
    assert '已出账' not in ORDER_FIX_SUCCESS_MSG
    assert '薪资已更新' not in ORDER_FIX_SUCCESS_MSG


def test_order_write_does_not_auto_calculate() -> None:
    import inspect

    from backend.plugin.rider_salary.service import order_service as mod

    source = inspect.getsource(mod.OrderService) + inspect.getsource(mod._to_write_detail)
    assert 'calculate_period' not in source
    assert 'calculate_rider_period' not in source
    assert 'persist=True' not in source
    assert 'assert_not_locked' in inspect.getsource(mod.OrderService.create)
    assert 'mark_stale' in inspect.getsource(mod.OrderService.create)
    assert 'audit_service.record' in inspect.getsource(mod.OrderService.create)
    assert 'assert_not_locked' in inspect.getsource(mod.OrderService.update)
    assert 'mark_stale' in inspect.getsource(mod.OrderService.update)
    assert 'audit_service.record' in inspect.getsource(mod.OrderService.update)
