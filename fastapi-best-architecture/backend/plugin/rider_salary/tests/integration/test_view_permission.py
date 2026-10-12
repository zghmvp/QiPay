"""只读角色能拉列表，不能写。旧写码在过渡期仍能读。"""

from typing import Any

from factories import bind_site_manager, create_rider, create_site, expect_ok, login_username
from runtime import ApiClient

_VIEW_MENUS = (
    'RiderSalary',
    'RiderSalaryRider',
    'RiderSalaryRiderDetail',
    'RiderSalaryAdjustment',
    'RiderSalaryAdvance',
    'RiderSalaryNotice',
    'RiderSalaryDayFlag',
    'RiderSalaryRiderView',
    'RiderSalaryAdjustmentView',
    'RiderSalaryDayFlagView',
    'RiderSalaryAdvanceView',
    'RiderSalaryNoticeView',
)
_VIEW_CODES = (
    'rs:rider:view',
    'rs:adjustment:view',
    'rs:dayflag:view',
    'rs:advance:view',
    'rs:notice:view',
)
_WRITE_CODES = (
    'rs:rider:add',
    'rs:rider:edit',
    'rs:rider:del',
    'rs:rider:binding',
    'rs:rider:employ',
    'rs:rider:account',
    'rs:adjustment:add',
    'rs:adjustment:edit',
    'rs:adjustment:del',
    'rs:advance:approve',
    'rs:advance:reject',
    'rs:advance:mark-paid',
    'rs:advance:cancel',
    'rs:advance:export',
    'rs:notice:add',
    'rs:notice:edit',
    'rs:notice:del',
    'rs:dayflag:edit',
)
_STAFF_DENIED = '用户已被禁止后台管理操作，请联系系统管理员'


def _drop_user_cache(*user_ids: int) -> None:
    """清掉这些用户的登录缓存。"""
    import redis

    from backend.core.conf import settings

    if not user_ids:
        return
    client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        db=settings.REDIS_DATABASE,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.delete(*[f'{settings.JWT_USER_REDIS_PREFIX}:{user_id}' for user_id in user_ids])
    finally:
        client.close()


def _menu_ids(client: ApiClient, headers: dict[str, str], names: tuple[str, ...]) -> list[int]:
    tree = expect_ok(client.get('/sys/menus', headers=headers))
    found: dict[str, int] = {}

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            name = node.get('name')
            if isinstance(name, str) and name in names and name not in found:
                found[name] = int(node['id'])
            children = node.get('children') or []
            if children:
                walk(children)

    walk(tree)
    missing = [name for name in names if name not in found]
    assert not missing, missing
    return [found[name] for name in names]


def _create_staff(
    client: ApiClient,
    headers: dict[str, str],
    *,
    role_name: str,
    username: str,
    menu_names: tuple[str, ...],
    dept_id: int,
) -> tuple[int, dict[str, str]]:
    expect_ok(
        client.post(
            '/sys/roles',
            headers=headers,
            json={'name': role_name, 'status': 1, 'is_filter_scopes': False, 'remark': 'P3-05 只读验收'},
        )
    )
    roles = expect_ok(client.get('/sys/roles/all', headers=headers))
    matched = [role for role in roles if role.get('name') == role_name]
    assert len(matched) == 1, role_name
    role_id = int(matched[0]['id'])
    expect_ok(
        client.put(
            f'/sys/roles/{role_id}/menus',
            headers=headers,
            json={'menus': _menu_ids(client, headers, menu_names)},
        )
    )
    created = expect_ok(
        client.post(
            '/sys/users',
            headers=headers,
            json={
                'username': username,
                'password': '123456',
                'nickname': role_name,
                'dept_id': dept_id,
                'roles': [role_id],
            },
        )
    )
    user_id = int(created['id'])
    expect_ok(client.put(f'/sys/users/{user_id}/permissions', headers=headers, params={'type': 'staff'}))
    return user_id, login_username(client, username, '123456')


def _paths(nodes: list[dict[str, Any]] | None) -> set[str]:
    found: set[str] = set()
    for node in nodes or []:
        path = node.get('path')
        if isinstance(path, str) and path:
            found.add(path)
        found.update(_paths(node.get('children')))
    return found


def _assert_read(response: Any) -> None:
    body = response.json()
    assert response.status_code == 200, body
    assert body['code'] == 200, body


def _assert_forbidden(response: Any) -> None:
    body = response.json()
    assert response.status_code == 403, body
    assert body['code'] == 403, body
    assert body.get('msg') != _STAFF_DENIED, body


def test_view_only_role_reads_lists_and_hides_writes(
    client: ApiClient,
    admin_token: dict[str, str],
    salary_admin_token: dict[str, str],
) -> None:
    """只有 view 码的角色能打开五个列表，写接口 403；只有旧写码时列表仍可读。"""
    cache_ids: list[int] = []
    try:
        admin = expect_ok(client.get('/sys/users/me', headers=admin_token))
        dept_id = int(admin['dept_id'])
        viewer_id, viewer = _create_staff(
            client,
            admin_token,
            role_name='只读观察员',
            username='view_only_p305',
            menu_names=_VIEW_MENUS,
            dept_id=dept_id,
        )
        cache_ids.append(viewer_id)
        codes = set(expect_ok(client.get('/auth/codes', headers=viewer)))
        assert set(_VIEW_CODES) <= codes
        assert codes.isdisjoint(_WRITE_CODES)
        sidebar = _paths(expect_ok(client.get('/sys/menus/sidebar', headers=viewer)))
        for path in (
            '/rider-salary/rider',
            '/rider-salary/adjustment',
            '/rider-salary/advance',
            '/rider-salary/notice',
            '/rider-salary/day-flag',
        ):
            assert path in sidebar, sorted(sidebar)

        site = create_site(client, admin_token, name='只读站点')
        bind_site_manager(client, admin_token, site_id=site['id'], user_id=viewer_id)
        rider = create_rider(client, admin_token, site_id=site['id'], name='只读骑手')

        for path in (
            '/rider-salary/riders',
            '/rider-salary/adjustments',
            '/rider-salary/advances',
            '/rider-salary/notices',
        ):
            _assert_read(client.get(path, headers=viewer))
        _assert_read(
            client.get(
                '/rider-salary/day-flags',
                headers=viewer,
                params={'site_id': site['id'], 'month': '2026-10'},
            )
        )
        _assert_read(client.get(f'/rider-salary/riders/{rider["id"]}', headers=viewer))
        _assert_read(client.get(f'/rider-salary/riders/{rider["id"]}/employ-history', headers=viewer))
        _assert_read(client.get(f'/rider-salary/riders/{rider["id"]}/bindings', headers=viewer))

        _assert_forbidden(
            client.post(
                '/rider-salary/riders',
                headers=viewer,
                json={
                    'job_no': 'VIEWBLOCK',
                    'name': '不应创建',
                    'site_id': site['id'],
                    'employ_type': 'part_time',
                    'hire_date': '2026-10-01',
                },
            )
        )
        _assert_forbidden(
            client.post(
                '/rider-salary/adjustments',
                headers=viewer,
                json={
                    'rider_id': rider['id'],
                    'biz_date': '2026-10-01',
                    'subject_id': 94001,
                    'amount': '1.00',
                    'remark': '只读不应写入',
                },
            )
        )
        _assert_forbidden(
            client.post(
                '/rider-salary/notices',
                headers=viewer,
                json={'title': '只读公告', 'content': '不应成功', 'site_id': site['id']},
            )
        )
        _assert_forbidden(
            client.put(
                '/rider-salary/day-flags',
                headers=viewer,
                json={'site_id': site['id'], 'days': []},
            )
        )
        _assert_forbidden(
            client.post(
                '/rider-salary/advances/1/approve',
                headers=viewer,
                json={'remark': '不应通过'},
            )
        )

        legacy_id, legacy = _create_staff(
            client,
            admin_token,
            role_name='旧码兼容员',
            username='legacy_add_p305',
            menu_names=('RiderSalary', 'RiderSalaryRider', 'RiderSalaryRiderAdd'),
            dept_id=dept_id,
        )
        cache_ids.append(legacy_id)
        legacy_codes = set(expect_ok(client.get('/auth/codes', headers=legacy)))
        assert 'rs:rider:add' in legacy_codes
        assert 'rs:rider:view' not in legacy_codes
        _assert_read(client.get('/rider-salary/riders', headers=legacy))
        _assert_forbidden(client.get('/rider-salary/adjustments', headers=legacy))

        stranger_id, stranger = _create_staff(
            client,
            admin_token,
            role_name='无关菜单员',
            username='no_view_p305',
            menu_names=('RiderSalary', 'RiderSalaryDashboard', 'RiderSalaryDashboardView'),
            dept_id=dept_id,
        )
        cache_ids.append(stranger_id)
        _assert_forbidden(client.get('/rider-salary/riders', headers=stranger))
        _assert_forbidden(client.get('/rider-salary/notices', headers=stranger))
        _assert_forbidden(
            client.get(
                '/rider-salary/day-flags',
                headers=stranger,
                params={'site_id': site['id'], 'month': '2026-10'},
            )
        )

        for path in (
            '/rider-salary/riders',
            '/rider-salary/adjustments',
            '/rider-salary/advances',
            '/rider-salary/notices',
        ):
            _assert_read(client.get(path, headers=salary_admin_token))
    finally:
        _drop_user_cache(*cache_ids)
