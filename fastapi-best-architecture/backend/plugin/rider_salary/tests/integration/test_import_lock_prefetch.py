"""P5-07：导入按骑手预取锁账日期，查询次数不超过骑手数 + 1。"""

import csv
import io

from typing import Any

import runtime

from factories import create_rider, create_site, expect_ok
from runtime import ApiClient
from sqlalchemy import event, text


def _execute(statement: str, params: dict[str, Any]) -> None:
    active = runtime.ACTIVE
    assert active is not None and active._conn is not None and active.client is not None

    async def _run() -> None:
        await active._conn.execute(text(statement), params)

    active.client.loop.run_until_complete(_run())


def test_import_lock_queries_follow_rider_count(client: ApiClient, admin_token: dict[str, str]) -> None:
    """三名骑手、每人 40 行都落在已锁账月份，锁账 SELECT 不超过 4 次，且行仍被拒绝。"""
    site = create_site(client, admin_token, name='锁账预取站点')
    riders = [
        create_rider(client, admin_token, site_id=site['id'], name=f'预取骑手{index}', hire_date='2026-09-01')
        for index in range(3)
    ]
    _execute(
        """
        insert into rs_settle_period (
            site_id, cycle_type, start_date, end_date, rider_id, status, created_time
        ) values (
            :site_id, 'month', '2026-10-01', '2026-10-31', 0, 'locked', now()
        )
        """,
        {'site_id': site['id']},
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        '站点编码',
        '骑手工号',
        '订单号',
        '配送距离(公里)',
        '商品重量(斤)',
        '下单时间',
        '送达时间',
        '订单状态',
        '订单金额',
        '备注',
    ])
    rows_per_rider = 40
    for rider in riders:
        for offset in range(rows_per_rider):
            day = 2 + (offset % 20)
            stamp = f'2026-10-{day:02d} 12:00:00'
            writer.writerow([
                site['code'],
                rider['job_no'],
                f'LK{rider["id"]}-{offset}',
                '3.50',
                '5.00',
                stamp,
                f'2026-10-{day:02d} 12:20:00',
                '已完成',
                '20.00',
                '',
            ])
    content = buffer.getvalue().encode('utf-8')
    active = runtime.ACTIVE
    assert active is not None and active._engine is not None
    statements: list[str] = []

    def _capture(
        _conn: object, _cursor: object, statement: str, _parameters: object, _context: object, _many: object
    ) -> None:
        statements.append(statement)

    event.listen(active._engine.sync_engine, 'before_cursor_execute', _capture)
    try:
        result = expect_ok(
            client.post(
                '/rider-salary/orders/import',
                headers=admin_token,
                data={'site_id': str(site['id']), 'skip_errors': 'false', 'auto_recalc': 'false'},
                files={'file': ('orders.csv', content, 'text/csv')},
            )
        )
    finally:
        event.remove(active._engine.sync_engine, 'before_cursor_execute', _capture)

    rider_count = len(riders)
    row_count = rider_count * rows_per_rider
    lock_selects = [
        item for item in statements if 'rs_settle_period' in item.lower() and item.lstrip().lower().startswith('select')
    ]
    assert result['failed_rows'] == row_count
    assert result['success_rows'] == 0
    assert any('锁账' in item['reason'] for item in result['errors'])
    assert len(lock_selects) <= rider_count + 1, (len(lock_selects), lock_selects)
    assert len(lock_selects) < row_count
