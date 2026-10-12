"""结算周期：同范围不相交；骑手级不能与站点级重叠。离职结算整段覆盖另见离职用例。"""

import uuid

from typing import Any

from factories import (
    calculate_period,
    create_rider,
    create_site,
    expect_error,
    expect_ok,
    generate_month,
    order_row,
    provision_c01_month,
)
from runtime import ApiClient


def _ranges(items: list[dict], rider_id: int) -> list[tuple[str, str]]:
    return sorted((item['start_date'], item['end_date']) for item in items if item['rider_id'] == rider_id)


def _generate(client: ApiClient, headers: dict[str, str], site_id: int, month: str) -> Any:
    return client.post(
        '/rider-salary/periods/generate',
        headers=headers,
        json={'site_id': site_id, 'month': month},
    )


def _set_override(client: ApiClient, headers: dict[str, str], rider_id: int, cycle: str) -> None:
    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider_id}',
            headers=headers,
            json={'settle_cycle_override': cycle},
        )
    )


def test_two_riders_can_share_the_same_half_month(
    client: ApiClient,
    admin_token: dict[str, str],
) -> None:
    """两个骑手的覆盖与站点周期起止相同时，只生成站点级周期，不另建骑手级。"""
    site = create_site(client, admin_token, name='双骑手半月站点', settle_cycle='half_month')
    first = create_rider(client, admin_token, site_id=site['id'], name='半月甲', hire_date='2026-10-01')
    second = create_rider(client, admin_token, site_id=site['id'], name='半月乙', hire_date='2026-10-01')
    _set_override(client, admin_token, first['id'], 'half_month')
    _set_override(client, admin_token, second['id'], 'half_month')

    created = expect_ok(_generate(client, admin_token, site['id'], '2026-10'))
    halves = [('2026-10-01', '2026-10-15'), ('2026-10-16', '2026-10-31')]
    assert _ranges(created['items'], 0) == halves
    assert _ranges(created['items'], first['id']) == []
    assert _ranges(created['items'], second['id']) == []
    assert created['created_count'] == 2


def test_month_period_rejects_rider_half_month(client: ApiClient, admin_token: dict[str, str]) -> None:
    """月结周期与骑手半月结相交时生成返回 400，并且不写入骑手级周期。"""
    site = create_site(client, admin_token, name='月结拒绝半月', settle_cycle='month')
    rider = create_rider(client, admin_token, site_id=site['id'], name='半月覆盖骑手', hire_date='2026-10-01')
    _set_override(client, admin_token, rider['id'], 'half_month')

    message = expect_error(_generate(client, admin_token, site['id'], '2026-10'), 400)
    assert '相交' in message
    assert '下一个完整周期' in message

    listed = expect_ok(
        client.get(
            '/rider-salary/periods',
            headers=admin_token,
            params={'site_id': site['id'], 'month': '2026-10', 'page': 1, 'size': 20},
        )
    )
    assert _ranges(listed['items'], 0) == []
    assert _ranges(listed['items'], rider['id']) == []


def test_site_halves_reject_rider_month(client: ApiClient, admin_token: dict[str, str]) -> None:
    """站点半月结与骑手月结相交时生成返回 400。"""
    site = create_site(client, admin_token, name='半月拒绝月结', settle_cycle='half_month')
    rider = create_rider(client, admin_token, site_id=site['id'], name='月结覆盖骑手', hire_date='2026-10-01')
    _set_override(client, admin_token, rider['id'], 'month')

    message = expect_error(_generate(client, admin_token, site['id'], '2026-10'), 400)
    assert '相交' in message


def test_partial_cover_rejected(client: ApiClient, admin_token: dict[str, str]) -> None:
    """骑手半月结盖不住跨月的站点级周期时返回 400，并且不会写入骑手级周期。"""
    site = create_site(client, admin_token, name='部分覆盖站点', settle_cycle='month')
    expect_ok(
        client.put(
            f'/rider-salary/sites/{site["id"]}',
            headers=admin_token,
            json={'settle_cycle': 'custom', 'cycle_config': {'anchor_day': 20}},
        )
    )
    first = expect_ok(_generate(client, admin_token, site['id'], '2026-10'))
    assert _ranges(first['items'], 0) == [
        ('2026-09-20', '2026-10-19'),
        ('2026-10-20', '2026-11-19'),
    ]
    rider = create_rider(client, admin_token, site_id=site['id'], name='部分覆盖骑手', hire_date='2026-09-01')
    message = expect_error(
        client.put(
            f'/rider-salary/riders/{rider["id"]}',
            headers=admin_token,
            json={'settle_cycle_override': 'half_month'},
        ),
        400,
    )
    assert '相交' in message
    assert '不能与站点级周期重叠' in message

    listed = expect_ok(
        client.get(
            '/rider-salary/periods',
            headers=admin_token,
            params={'site_id': site['id'], 'month': '2026-10', 'page': 1, 'size': 20},
        )
    )
    assert _ranges(listed['items'], rider['id']) == []
    assert len(_ranges(listed['items'], 0)) == 2


def test_payroll_blocks_later_rider_cover(client: ApiClient, admin_token: dict[str, str]) -> None:
    """站点级周期里已有该骑手薪资单时，保存相交的周期覆盖即返回 400。"""
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-04',
        orders=[order_row(f'P019-{uuid.uuid4().hex[:8]}', '2026-04-08')],
        hire_date='2026-04-01',
        rider_name='已有薪资单骑手',
        site_name='已有薪资单站点',
    )
    period_id = ready['period']['id']
    rider_id = ready['rider']['id']
    site_id = ready['site']['id']
    calculate_period(client, admin_token, period_id)
    message = expect_error(
        client.put(
            f'/rider-salary/riders/{rider_id}',
            headers=admin_token,
            json={'settle_cycle_override': 'half_month'},
        ),
        400,
    )
    assert '薪资单' in message
    assert '下一个完整周期' in message

    again = expect_ok(_generate(client, admin_token, site_id, '2026-04'))
    assert again['created_count'] == 0

    listed = expect_ok(
        client.get(
            '/rider-salary/periods',
            headers=admin_token,
            params={'site_id': site_id, 'month': '2026-04', 'page': 1, 'size': 20},
        )
    )
    assert _ranges(listed['items'], 0) == [('2026-04-01', '2026-04-30')]
    assert _ranges(listed['items'], rider_id) == []


def test_site_cycle_change_rejects_same_scope_overlap(client: ApiClient, admin_token: dict[str, str]) -> None:
    """月结改半月结后，同一站点级范围重叠返回 400。下一个月可以生成。"""
    site = create_site(client, admin_token, name='站点级重叠站点', settle_cycle='month')
    first = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    assert first['start_date'] == '2026-09-01'
    assert first['end_date'] == '2026-09-30'

    again = expect_ok(_generate(client, admin_token, site['id'], '2026-09'))
    assert again['created_count'] == 0
    assert again['skipped_count'] == 1

    expect_ok(
        client.put(
            f'/rider-salary/sites/{site["id"]}',
            headers=admin_token,
            json={'settle_cycle': 'half_month'},
        )
    )
    message = expect_error(_generate(client, admin_token, site['id'], '2026-09'), 400)
    assert '相交' in message
    assert '删除' in message

    listed = expect_ok(
        client.get(
            '/rider-salary/periods',
            headers=admin_token,
            params={'site_id': site['id'], 'month': '2026-09', 'page': 1, 'size': 20},
        )
    )
    assert _ranges(listed['items'], 0) == [('2026-09-01', '2026-09-30')]

    october = expect_ok(_generate(client, admin_token, site['id'], '2026-10'))
    assert _ranges(october['items'], 0) == [('2026-10-01', '2026-10-15'), ('2026-10-16', '2026-10-31')]
    assert october['created_count'] == 2
