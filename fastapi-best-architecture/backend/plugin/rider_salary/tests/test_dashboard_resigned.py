from types import SimpleNamespace

from backend.plugin.rider_salary.service.dashboard_service import (
    RESIGNED_WITH_ORDERS_ITEM_KEYS,
    resigned_with_orders_item,
)


def test_resigned_item_keeps_rider_id_and_no_new_fields() -> None:
    item = resigned_with_orders_item(SimpleNamespace(id=9, job_no='D5A001', name='张三'), 4)
    assert item['rider_id'] == 9
    assert item['job_no'] == 'D5A001'
    assert item['name'] == '张三'
    assert item['order_count'] == 4
    assert set(item) == RESIGNED_WITH_ORDERS_ITEM_KEYS
