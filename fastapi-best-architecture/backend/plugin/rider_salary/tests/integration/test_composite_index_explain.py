"""P5-08：站点加日期的订单查询能走复合索引。"""

import psycopg
import pytest

from backend.core.conf import settings

pytestmark = pytest.mark.integration


def test_order_site_date_explain_uses_composite_index() -> None:
    """关掉顺序扫描后，站点加业务日的查询计划应出现复合索引。"""
    try:
        conn = psycopg.connect(
            host='127.0.0.1',
            port=5432,
            user='root',
            password='postgres',
            dbname=settings.DATABASE_SCHEMA,
            connect_timeout=5,
        )
    except psycopg.Error as exc:
        pytest.fail(f'无法连接数据库：{exc}')
    with conn:
        conn.execute('drop index if exists ix_rs_order_biz_date')
        conn.execute('drop index if exists ix_rs_order_site_id')
        conn.execute('set enable_seqscan = off')
        rows = conn.execute(
            """
            explain
            select id
            from rs_order
            where site_id = 1
              and biz_date >= date '2026-01-01'
              and biz_date <= date '2026-01-31'
              and deleted = 0
            """
        ).fetchall()
        conn.rollback()
    plan = '\n'.join(str(row[0]) for row in rows)
    assert 'ix_rs_order_site_biz_date' in plan, plan
