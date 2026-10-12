"""P3-06：全站范围按权限码判定，开户骑手角色按种子锚点判定，都不看中文角色名。"""

from typing import Any

from factories import create_rider, create_site, expect_ok, login_username, open_rider_account
from runtime import ApiClient, RoleAccount

_RENAMED_ADMIN = '薪酬主管'
_DECOY_RIDER = '骑手'
_RENAMED_RIDER = '配送员'


def _drop_user_cache(*user_ids: int) -> None:
    """清掉这些用户的登录缓存，避免改名后的快照留到下一条用例。"""
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


def _role_named(client: ApiClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    roles = expect_ok(client.get('/sys/roles/all', headers=headers))
    matched = [role for role in roles if role.get('name') == name]
    assert len(matched) == 1, (name, [role.get('name') for role in roles])
    return matched[0]


def _rename_role(client: ApiClient, headers: dict[str, str], role: dict[str, Any], name: str) -> None:
    expect_ok(
        client.put(
            f'/sys/roles/{role["id"]}',
            headers=headers,
            json={
                'name': name,
                'status': role['status'],
                'is_filter_scopes': role['is_filter_scopes'],
                'remark': role.get('remark'),
            },
        )
    )


def _menu_id(client: ApiClient, headers: dict[str, str], name: str) -> int:
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


def _site_codes(client: ApiClient, headers: dict[str, str]) -> set[str]:
    rows = expect_ok(client.get('/rider-salary/sites/all', headers=headers))
    return {row['code'] for row in rows}


def _create_role(client: ApiClient, headers: dict[str, str], name: str, menu_id: int | None) -> dict[str, Any]:
    expect_ok(
        client.post(
            '/sys/roles',
            headers=headers,
            json={
                'name': name,
                'status': 1,
                'is_filter_scopes': False,
                'remark': '同名角色，不授予范围权限码',
            },
        )
    )
    created = _role_named(client, headers, name)
    if menu_id is not None:
        expect_ok(
            client.put(
                f'/sys/roles/{created["id"]}/menus',
                headers=headers,
                json={'menus': [menu_id]},
            )
        )
    return created


def test_renamed_salary_admin_still_sees_all_sites(
    client: ApiClient,
    admin_token: dict[str, str],
    salary_admin_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """薪资管理员改名后仍可见全站；新建的同名角色没有 rs:scope:all，看不到全站。"""
    cache_ids = [role_accounts['salary_admin'].user_id]
    try:
        site = create_site(client, admin_token, name='范围站点')
        before = _site_codes(client, salary_admin_token)
        assert site['code'] in before
        assert 'FXBASE' in before

        original = _role_named(client, admin_token, '薪资管理员')
        plain_menu_id = _menu_id(client, admin_token, 'RiderSalarySite')
        _rename_role(client, admin_token, original, _RENAMED_ADMIN)

        profile = expect_ok(client.get('/sys/users/me', headers=salary_admin_token))
        assert _RENAMED_ADMIN in profile['roles']
        assert '薪资管理员' not in profile['roles']
        after = _site_codes(client, salary_admin_token)
        assert site['code'] in after
        assert 'FXBASE' in after

        decoy = _create_role(client, admin_token, '薪资管理员', plain_menu_id)
        assert decoy['id'] != original['id']
        admin_user = expect_ok(client.get(f'/sys/users/{role_accounts["admin"].user_id}', headers=admin_token))
        created = expect_ok(
            client.post(
                '/sys/users',
                headers=admin_token,
                json={
                    'username': 'scope_alias_admin',
                    'password': '123456',
                    'nickname': '同名薪资管理员',
                    'dept_id': admin_user['dept_id'],
                    'roles': [decoy['id']],
                },
            )
        )
        cache_ids.append(int(created['id']))
        alias_headers = login_username(client, 'scope_alias_admin', '123456')
        alias_profile = expect_ok(client.get('/sys/users/me', headers=alias_headers))
        assert '薪资管理员' in alias_profile['roles']
        alias_codes = _site_codes(client, alias_headers)
        assert site['code'] not in alias_codes
        assert 'FXBASE' not in alias_codes
    finally:
        _drop_user_cache(*cache_ids)


def test_open_account_uses_rider_anchor_not_role_name(
    client: ApiClient,
    admin_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """骑手角色改名后开户仍分配该角色；后建的同名角色没有种子锚点，不会被选中。"""
    cache_ids = [role_accounts['rider'].user_id]
    try:
        original = _role_named(client, admin_token, '骑手')
        _rename_role(client, admin_token, original, _RENAMED_RIDER)
        decoy = _create_role(client, admin_token, _DECOY_RIDER, None)
        assert decoy['id'] != original['id']

        site = create_site(client, admin_token, name='开户站点')
        rider = create_rider(client, admin_token, site_id=site['id'], name='锚点骑手')
        open_rider_account(client, admin_token, rider_id=rider['id'], job_no=rider['job_no'])
        page = expect_ok(
            client.get(
                '/sys/users',
                headers=admin_token,
                params={'username': rider['job_no'], 'page': 1, 'size': 20},
            )
        )
        matched = [item for item in page['items'] if item['username'] == rider['job_no']]
        assert len(matched) == 1, page
        cache_ids.append(int(matched[0]['id']))
        roles = expect_ok(client.get(f'/sys/users/{matched[0]["id"]}/roles', headers=admin_token))
        assert [role['name'] for role in roles] == [_RENAMED_RIDER]
        assert roles[0]['id'] == original['id']
    finally:
        _drop_user_cache(*cache_ids)
