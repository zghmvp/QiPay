"""E13：两轮反冲后，日详情每个订单只保留有效薪资单上的一行。"""

from factories import (
    calculate_period,
    expect_ok,
    lock_period,
    money,
    open_rider_account,
    order_row,
    provision_c01_month,
    reverse_period,
)
from runtime import ApiClient


def test_e13_day_detail_keeps_one_line_per_order(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E13 / P0-08：两轮反冲后，8 月 1 日的同一订单在管理端和 H5 都只显示一行明细。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-08',
        orders=[order_row('E13-0801', '2026-08-01')],
        hire_date='2026-08-01',
        rider_name='日详情骑手',
        site_name='日详情站点',
    )
    period_id = ready['period']['id']
    rider = ready['rider']
    rider_headers = open_rider_account(client, admin_token, rider_id=rider['id'], job_no=rider['job_no'])
    calculate_period(client, admin_token, period_id)
    lock_period(client, admin_token, period_id, '第一轮锁账')
    reverse_period(client, admin_token, period_id, '第一轮反冲')
    calculate_period(client, admin_token, period_id)
    lock_period(client, admin_token, period_id, '补发锁账')
    reverse_period(client, admin_token, period_id, '第二轮反冲')
    calculate_period(client, admin_token, period_id)

    admin_day = expect_ok(client.get(f'/rider-salary/calendar/{rider["id"]}/days/2026-08-01', headers=admin_token))
    h5_day = expect_ok(client.get('/rider-salary/me/days/2026-08-01', headers=rider_headers))
    for day in (admin_day, h5_day):
        matched = [order for order in day['orders'] if order['order_no'] == 'E13-0801']
        assert len(matched) == 1
        details = matched[0]['details']
        assert len(details) == 1
        assert money(details[0]['amount']) == money('5.00')
        assert money(day['totals']['formula_amount']) == money('5.00')
