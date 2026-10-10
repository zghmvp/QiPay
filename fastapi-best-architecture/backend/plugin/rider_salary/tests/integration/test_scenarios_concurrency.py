"""E5：同一周期并发两次反冲，只应留下一轮反冲单。"""

import asyncio

from factories import calculate_period, live_net, lock_period, money, order_row, period_payrolls, provision_c01_month
from runtime import ApiClient


def test_e5_concurrent_reverse_creates_one_reversal(client: ApiClient, admin_token: dict[str, str]) -> None:
    """E5：并发两次反冲，一次成功一次拒绝，每名骑手只有一张反冲单。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-08',
        orders=[order_row('E5-0801', '2026-08-06')],
        hire_date='2026-08-01',
        rider_name='并发反冲骑手',
        site_name='并发反冲站点',
    )
    period_id = ready['period']['id']
    calculate_period(client, admin_token, period_id)
    lock_period(client, admin_token, period_id, '并发反冲前锁账')

    async def _both() -> list[object]:
        return list(
            await asyncio.gather(
                client.raw.post(
                    f'/rider-salary/periods/{period_id}/reverse',
                    headers=admin_token,
                    json={'reason': '并发甲'},
                ),
                client.raw.post(
                    f'/rider-salary/periods/{period_id}/reverse',
                    headers=admin_token,
                    json={'reason': '并发乙'},
                ),
                return_exceptions=True,
            )
        )

    results = client.loop.run_until_complete(_both())
    failures = [item for item in results if isinstance(item, Exception)]
    assert not failures, failures
    statuses = [item.status_code for item in results]
    assert sorted(statuses) == [200, 400], [item.text for item in results]

    payrolls = period_payrolls(client, admin_token, period_id)
    reversals = [row for row in payrolls if row['rider_id'] == ready['rider']['id'] and row['kind'] == 'reversal']
    assert len(reversals) == 1
    assert live_net(payrolls, ready['rider']['id']) == money('0.00')
