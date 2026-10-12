"""P2-06：试算校验骑手所属站点；启用中和已使用版本不回写 trial_hash。"""

import uuid

from typing import Any

from factories import (
    activate_plan,
    bind_plan,
    bind_site_manager,
    create_c01_plan,
    create_rider,
    create_site,
    expect_error,
    expect_ok,
    import_completed_orders,
    login_username,
    money,
    month_bounds,
    order_row,
)
from runtime import ApiClient, RoleAccount


def _menu_id(client: ApiClient, headers: dict[str, str], name: str) -> int:
    """按菜单 name 取 ID。

    :param client: 基座客户端
    :param headers: 超管 token
    :param name: 菜单 name
    :return: 菜单 ID
    """
    tree = expect_ok(client.get('/sys/menus', headers=headers))

    def walk(nodes: list[dict[str, Any]]) -> int | None:
        for node in nodes:
            if node.get('name') == name:
                return int(node['id'])
            found = walk(node.get('children') or [])
            if found is not None:
                return found
        return None

    found = walk(tree)
    assert found is not None, name
    return found


def _role_named(client: ApiClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    """按名称取唯一角色。

    :param client: 基座客户端
    :param headers: 超管 token
    :param name: 角色名称
    :return: 角色
    """
    roles = expect_ok(client.get('/sys/roles/all', headers=headers))
    matched = [role for role in roles if role.get('name') == name]
    assert len(matched) == 1, (name, [role.get('name') for role in roles])
    return matched[0]


def _trial(
    client: ApiClient,
    headers: dict[str, str],
    version_id: int,
    rider_id: int,
    start: str,
    end: str,
) -> Any:
    """调用试算接口。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param version_id: 方案版本 ID
    :param rider_id: 骑手 ID
    :param start: 开始日期
    :param end: 结束日期
    :return: httpx 响应
    """
    return client.post(
        f'/rider-salary/plan-versions/{version_id}/trial',
        headers=headers,
        json={'rider_id': rider_id, 'start_date': start, 'end_date': end},
    )


def _site_owner_with_trial(
    client: ApiClient,
    admin_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
    *,
    site_id: int,
) -> dict[str, str]:
    """建一个只绑定指定站点、并持有试算权限的负责人。

    种子里的站点负责人角色没有 ``rs:plan:trial``，直接调用会在权限层返回 403，到不了站点校验。

    :param client: 基座客户端
    :param admin_token: 超管 token
    :param role_accounts: 预置角色账号
    :param site_id: 该负责人可见的站点
    :return: 负责人请求头
    """
    suffix = uuid.uuid4().hex[:8]
    role_name = f'试算负责人{suffix}'
    expect_ok(
        client.post(
            '/sys/roles',
            headers=admin_token,
            json={
                'name': role_name,
                'status': 1,
                'is_filter_scopes': False,
                'remark': '仅用于试算站点可见性',
            },
        )
    )
    role = _role_named(client, admin_token, role_name)
    expect_ok(
        client.put(
            f'/sys/roles/{role["id"]}/menus',
            headers=admin_token,
            json={'menus': [_menu_id(client, admin_token, 'RiderSalaryPlanTrial')]},
        )
    )
    admin_user = expect_ok(client.get(f'/sys/users/{role_accounts["admin"].user_id}', headers=admin_token))
    username = f'it_trial_{suffix}'
    created = expect_ok(
        client.post(
            '/sys/users',
            headers=admin_token,
            json={
                'username': username,
                'password': '123456',
                'nickname': '试算站点负责人',
                'dept_id': admin_user['dept_id'],
                'roles': [role['id']],
            },
        )
    )
    expect_ok(
        client.put(
            f'/sys/users/{created["id"]}/permissions',
            headers=admin_token,
            params={'type': 'staff'},
        )
    )
    bind_site_manager(client, admin_token, site_id=site_id, user_id=int(created['id']), role='owner')
    return login_username(client, username, '123456')


def test_site_owner_cannot_trial_other_site_rider(
    client: ApiClient,
    admin_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """负责人试算其他站点的骑手返回 403，且不回写试算状态；本站骑手可以试算。"""
    own_site = create_site(client, admin_token, name='试算本站')
    other_site = create_site(client, admin_token, name='试算他站')
    own_rider = create_rider(client, admin_token, site_id=own_site['id'], name='本站试算骑手', hire_date='2026-01-01')
    other_rider = create_rider(
        client, admin_token, site_id=other_site['id'], name='他站试算骑手', hire_date='2026-01-01'
    )
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-03')
    marker = uuid.uuid4().hex[:10].upper()
    for site, rider, day in (
        (own_site, own_rider, '2026-03-02'),
        (other_site, other_rider, '2026-03-03'),
    ):
        imported = import_completed_orders(
            client,
            admin_token,
            site_id=site['id'],
            site_code=site['code'],
            job_no=rider['job_no'],
            rows=[order_row(f'PV{marker}{day[-2:]}', day, '20.00')],
        )
        assert imported['success_rows'] == 1
    owner_token = _site_owner_with_trial(
        client,
        admin_token,
        role_accounts,
        site_id=own_site['id'],
    )
    denied = _trial(client, owner_token, plan['version_id'], other_rider['id'], start, end)
    assert '无权访问该站点数据' in expect_error(denied, 403)
    untouched = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert untouched['trial_hash'] is None
    assert untouched['trial_passed'] is False
    allowed = expect_ok(_trial(client, owner_token, plan['version_id'], own_rider['id'], start, end))
    assert allowed['passed'] is True
    written = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert written['trial_passed'] is True
    assert written['trial_hash']


def test_active_and_used_trial_does_not_persist_hash(
    client: ApiClient,
    admin_token: dict[str, str],
) -> None:
    """对启用中和已使用版本再试算，trial_hash 与快照保持不变，结果只在响应里返回。"""
    site = create_site(client, admin_token, name='试算不落库站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='不落库骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-04')
    marker = uuid.uuid4().hex[:10].upper()
    first = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row(f'PH{marker}02', '2026-04-02', '20.00')],
    )
    assert first['success_rows'] == 1
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    before = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert before['status'] == 'active'
    assert before['is_used'] is False
    assert before['trial_hash']
    snapshot = before['trial_snapshot']
    assert money(snapshot['per_order_total']) == money('5.00')
    second = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row(f'PH{marker}03', '2026-04-03', '20.00')],
    )
    assert second['success_rows'] == 1
    active_again = expect_ok(_trial(client, admin_token, plan['version_id'], rider['id'], start, end))
    assert active_again['passed'] is True
    assert money(active_again['summary']['per_order_total']) == money('10.00')
    after_active = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert after_active['trial_hash'] == before['trial_hash']
    assert after_active['trial_snapshot'] == snapshot
    assert after_active['trial_passed'] is True
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=plan['version_id'], start_date=start)
    used = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert used['is_used'] is True
    used_again = expect_ok(_trial(client, admin_token, plan['version_id'], rider['id'], start, end))
    assert money(used_again['summary']['per_order_total']) == money('10.00')
    after_used = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert after_used['trial_hash'] == before['trial_hash']
    assert after_used['trial_snapshot'] == snapshot
    assert after_used['is_used'] is True
