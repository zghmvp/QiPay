"""E6、E7：已锁账周期内不能改用工历史，也不能把绑定移出该周期。"""

from factories import calculate_period, expect_error, expect_ok, lock_period, order_row, provision_c01_month
from runtime import ApiClient


def test_e6_locked_month_rejects_employ_history(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E6 / P0-09：已锁账的 9 月内新增用工历史，返回 403 且不落库。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-09',
        orders=[order_row('E6-0901', '2026-09-03')],
        hire_date='2026-09-01',
        rider_name='用工历史骑手',
        site_name='用工历史站点',
    )
    calculate_period(client, admin_token, ready['period']['id'])
    lock_period(client, admin_token, ready['period']['id'], '用工历史锁账')
    rider_id = ready['rider']['id']
    before = expect_ok(client.get(f'/rider-salary/riders/{rider_id}/employ-history', headers=admin_token))
    response = client.post(
        f'/rider-salary/riders/{rider_id}/employ-history',
        headers=admin_token,
        json={'employ_type': 'full_time', 'start_date': '2026-09-10', 'remark': '锁账后改类型'},
    )
    message = expect_error(response, status=403)
    assert '已锁账' in message
    after = expect_ok(client.get(f'/rider-salary/riders/{rider_id}/employ-history', headers=admin_token))
    assert after == before
    assert not any(
        row['employ_type'] == 'full_time' and str(row['start_date']).startswith('2026-09-10') for row in after
    )


def test_e7_locked_month_rejects_binding_move(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E7 / P0-10：把绑定起始日改到 10 月 1 日，使已锁账的 9 月失去方案，返回 403 且不落库。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-09',
        orders=[order_row('E7-0901', '2026-09-04')],
        hire_date='2026-09-01',
        rider_name='绑定骑手',
        site_name='绑定站点',
    )
    calculate_period(client, admin_token, ready['period']['id'])
    lock_period(client, admin_token, ready['period']['id'], '绑定锁账')
    rider_id = ready['rider']['id']
    bindings = expect_ok(client.get(f'/rider-salary/riders/{rider_id}/bindings', headers=admin_token))
    assert len(bindings) == 1
    binding = bindings[0]
    assert str(binding['start_date']).startswith('2026-09-01')
    response = client.put(
        f'/rider-salary/riders/{rider_id}/bindings/{binding["id"]}',
        headers=admin_token,
        json={'start_date': '2026-10-01'},
    )
    message = expect_error(response, status=403)
    assert '已锁账' in message
    after = expect_ok(client.get(f'/rider-salary/riders/{rider_id}/bindings', headers=admin_token))
    assert len(after) == 1
    assert str(after[0]['start_date']).startswith('2026-09-01')
