"""P5-05：回退预览按明细反查薪资单，1 万张无关薪资单时仍小于 1 秒。"""

import time

from typing import Any

import runtime

from factories import create_plan, expect_ok
from runtime import ApiClient
from sqlalchemy import event, text

_NOISE = 10_000
_PER_ORDER = {'类型': '固定金额', '金额': 20}


def _execute(statement: str, params: dict[str, Any] | None = None) -> None:
    active = runtime.ACTIVE
    assert active is not None and active._conn is not None and active.client is not None

    async def _run() -> None:
        await active._conn.execute(text(statement), params or {})

    active.client.loop.run_until_complete(_run())


def _rows(statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    active = runtime.ACTIVE
    assert active is not None and active._conn is not None and active.client is not None

    async def _run() -> list[dict[str, Any]]:
        result = await active._conn.execute(text(statement), params or {})
        return [dict(row) for row in result.mappings().all()]

    return active.client.loop.run_until_complete(_run())


def _insert_payroll(
    *,
    period_id: int,
    rider_id: int,
    status: str,
    version_ids: str,
) -> int:
    rows = _rows(
        """
        insert into rs_payroll (
            period_id, rider_id, kind, status, calc_version, stale, reversed,
            order_count, valid_order_count,
            per_order_total, daily_total, period_total, bonus_total, penalty_total,
            gross, deduction_total, advance_deduction, net,
            plan_version_ids, created_time
        ) values (
            :period_id, :rider_id, 'normal', :status, 1, false, false,
            1, 1,
            20, 0, 0, 0, 0,
            20, 0, 0, 20,
            cast(:version_ids as json), now()
        )
        returning id
        """,
        {
            'period_id': period_id,
            'rider_id': rider_id,
            'status': status,
            'version_ids': version_ids,
        },
    )
    return int(rows[0]['id'])


def test_preview_skips_unrelated_payrolls(client: ApiClient, admin_token: dict[str, str]) -> None:
    """1 万张无关薪资单不进入预览；同周期未引用该版本的已定稿单仍计入反冲。"""
    plan = create_plan(
        client,
        admin_token,
        name='回退反查',
        short_name='反查',
        items=[
            {
                'subject_code': 'BASE_UNIT_PRICE',
                'name': '基础单价',
                'stage': 'per_order',
                'sort_order': 0,
                'formula_json': _PER_ORDER,
            }
        ],
    )
    version_id = int(plan['version_id'])
    _execute(
        """
        insert into rs_payroll (
            period_id, rider_id, kind, status, calc_version, stale, reversed,
            order_count, valid_order_count,
            per_order_total, daily_total, period_total, bonus_total, penalty_total,
            gross, deduction_total, advance_deduction, net,
            plan_version_ids, created_time
        )
        select
            700000 + g, 1, 'normal', 'finalized', 1, false, false,
            0, 0,
            0, 0, 0, 0, 0,
            0, 0, 0, 0,
            '[0]'::json, now()
        from generate_series(1, :noise) as g
        """,
        {'noise': _NOISE},
    )
    period_id = 820000
    draft_id = _insert_payroll(period_id=period_id, rider_id=11, status='draft', version_ids=f'[{version_id}]')
    seeded_id = _insert_payroll(period_id=period_id, rider_id=12, status='finalized', version_ids=f'[{version_id}]')
    sibling_id = _insert_payroll(period_id=period_id, rider_id=13, status='finalized', version_ids='[0]')
    _insert_payroll(period_id=period_id + 1, rider_id=14, status='finalized', version_ids='[0]')
    for payroll_id, rider_id in ((draft_id, 11), (seeded_id, 12)):
        _execute(
            """
            insert into rs_payroll_detail (
                payroll_id, rider_id, subject_id, amount, stage, include_in_gross, source,
                plan_version_id, created_time
            ) values (
                :payroll_id, :rider_id, 1, 20, 'per_order', true, 'formula',
                :version_id, now()
            )
            """,
            {'payroll_id': payroll_id, 'rider_id': rider_id, 'version_id': version_id},
        )
    total = _rows('select count(*) as total from rs_payroll where deleted = 0')[0]['total']
    assert int(total) >= _NOISE

    active = runtime.ACTIVE
    assert active is not None and active._engine is not None
    statements: list[str] = []

    def _capture(
        _conn: object, _cursor: object, statement: str, _parameters: object, _context: object, _many: object
    ) -> None:
        statements.append(statement)

    event.listen(active._engine.sync_engine, 'before_cursor_execute', _capture)
    started = time.perf_counter()
    try:
        preview = expect_ok(
            client.get(
                f'/rider-salary/plan-versions/{version_id}/rollback-preview',
                headers=admin_token,
            )
        )
    finally:
        event.remove(active._engine.sync_engine, 'before_cursor_execute', _capture)
    elapsed = time.perf_counter() - started

    assert preview['payrolls_draft'] == 1
    assert preview['payrolls_finalized'] == 2
    assert preview['payrolls_paid'] == 0
    assert {row['id'] for row in preview['payrolls']} == {draft_id, seeded_id, sibling_id}
    assert elapsed < 1, f'预览耗时 {elapsed:.3f} 秒'
    detail_sql = [item.lower() for item in statements if 'rs_payroll_detail' in item.lower()]
    assert any('plan_version_id' in item and 'distinct' in item for item in detail_sql), detail_sql
    payroll_sql = [
        item.lower()
        for item in statements
        if 'from rs_payroll' in item.lower() and 'rs_payroll_detail' not in item.lower()
    ]
    assert payroll_sql, statements
    assert all(' in (' in item or ' = any' in item for item in payroll_sql), payroll_sql
