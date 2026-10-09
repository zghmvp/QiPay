"""P2-09：生命周期非法组合统一返回 400。

停用站点不能新建或换入骑手；离职骑手不能开户或重新启用账号；
停用方案的启用版本不能新绑定，也不能再启用版本。已有绑定只改日期仍放行。
"""

from factories import (
    activate_plan,
    bind_plan,
    create_c01_plan,
    create_rider,
    create_site,
    ensure_completed_order_for_trial,
    expect_error,
    expect_ok,
    month_bounds,
)
from runtime import ApiClient

_SITE_DISABLED = '所属站点已停用，不能分配新骑手'
_RESIGNED_OPEN = '离职骑手不能开通账号'
_RESIGNED_ENABLE = '离职骑手不能启用账号'
_PLAN_BIND = '停用方案不能用于新绑定'
_PLAN_ACTIVATE = '方案已停用，不能启用版本'


def _active_version_ids(client: ApiClient, headers: dict[str, str]) -> set[int]:
    rows = expect_ok(client.get('/rider-salary/plan-versions/active', headers=headers))
    return {int(item['id']) for item in rows}


def test_disabled_site_rejects_new_rider_and_transfer(client: ApiClient, admin_token: dict[str, str]) -> None:
    """停用站点不能建骑手，也不能把在职骑手换进来；重新启用后两条都恢复。"""
    home = create_site(client, admin_token, name='在用站点')
    closed = create_site(client, admin_token, name='停用站点')
    rider = create_rider(client, admin_token, site_id=home['id'], name='待调站骑手', hire_date='2026-01-01')
    expect_ok(
        client.put(
            f'/rider-salary/sites/{closed["id"]}',
            headers=admin_token,
            json={'status': 'disable'},
        )
    )

    created = client.post(
        '/rider-salary/riders',
        headers=admin_token,
        json={
            'job_no': 'ITDISABLED1',
            'name': '不该建成',
            'site_id': closed['id'],
            'employ_type': 'part_time',
            'hire_date': '2026-01-01',
            'status': 'on_job',
        },
    )
    assert expect_error(created) == _SITE_DISABLED

    transferred = client.put(
        f'/rider-salary/riders/{rider["id"]}',
        headers=admin_token,
        json={'site_id': closed['id'], 'reason': '调到停用站'},
    )
    assert expect_error(transferred) == _SITE_DISABLED
    detail = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}', headers=admin_token))
    assert detail['site_id'] == home['id']

    expect_ok(
        client.put(
            f'/rider-salary/sites/{closed["id"]}',
            headers=admin_token,
            json={'status': 'enable'},
        )
    )
    created_after = create_rider(client, admin_token, site_id=closed['id'], name='恢复后新建')
    assert created_after['site_id'] == closed['id']


def test_resigned_rider_cannot_open_or_enable_account(client: ApiClient, admin_token: dict[str, str]) -> None:
    """离职后不能开户，已有账号也不能重新启用；在职开户和离职后停用账号仍可用。"""
    site = create_site(client, admin_token, name='离职账号站点')
    left = create_rider(client, admin_token, site_id=site['id'], name='先离职', hire_date='2026-01-01')
    expect_ok(
        client.put(
            f'/rider-salary/riders/{left["id"]}/leave',
            headers=admin_token,
            json={'leave_date': '2026-09-10', 'reason': '个人原因'},
        )
    )
    opened = client.post(
        f'/rider-salary/riders/{left["id"]}/open-account',
        headers=admin_token,
        json={'password': 'Rider@123456', 'reason': '离职后开户'},
    )
    assert expect_error(opened) == _RESIGNED_OPEN

    employed = create_rider(client, admin_token, site_id=site['id'], name='在职开户', hire_date='2026-01-01')
    expect_ok(
        client.post(
            f'/rider-salary/riders/{employed["id"]}/open-account',
            headers=admin_token,
            json={'password': 'Rider@123456', 'reason': '在职开户'},
        )
    )
    expect_ok(
        client.post(
            f'/rider-salary/riders/{employed["id"]}/enable-account',
            headers=admin_token,
            json={'reason': '在职启用'},
        )
    )
    expect_ok(
        client.put(
            f'/rider-salary/riders/{employed["id"]}/leave',
            headers=admin_token,
            json={'leave_date': '2026-09-10', 'reason': '个人原因'},
        )
    )
    enabled = client.post(
        f'/rider-salary/riders/{employed["id"]}/enable-account',
        headers=admin_token,
        json={'reason': '离职后启用'},
    )
    assert expect_error(enabled) == _RESIGNED_ENABLE
    expect_ok(
        client.post(
            f'/rider-salary/riders/{employed["id"]}/disable-account',
            headers=admin_token,
            json={'reason': '离职后停用账号'},
        )
    )


def test_disabled_plan_active_version_cannot_be_newly_bound(client: ApiClient, admin_token: dict[str, str]) -> None:
    """方案停用后，启用中的版本不能新绑定或改绑过去；只改结束日、改到仍启用的方案都可以。"""
    site = create_site(client, admin_token, name='停用方案站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='已绑定骑手', hire_date='2026-01-01')
    another = create_rider(client, admin_token, site_id=site['id'], name='待绑定骑手', hire_date='2026-01-01')
    closed_plan = create_c01_plan(client, admin_token)
    open_plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-09')
    activate_plan(
        client,
        admin_token,
        version_id=closed_plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    activate_plan(
        client,
        admin_token,
        version_id=open_plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(
        client,
        admin_token,
        rider_id=rider['id'],
        version_id=closed_plan['version_id'],
        start_date='2026-01-01',
    )
    expect_ok(
        client.put(
            f'/rider-salary/plans/{closed_plan["plan_id"]}',
            headers=admin_token,
            json={'status': 'disable'},
        )
    )
    version = expect_ok(client.get(f'/rider-salary/plan-versions/{closed_plan["version_id"]}', headers=admin_token))
    assert version['status'] == 'active'
    active_ids = _active_version_ids(client, admin_token)
    assert closed_plan['version_id'] not in active_ids
    assert open_plan['version_id'] in active_ids

    rejected = client.post(
        f'/rider-salary/riders/{another["id"]}/bindings',
        headers=admin_token,
        json={
            'plan_version_id': closed_plan['version_id'],
            'binding_type': 'default',
            'start_date': '2026-01-01',
        },
    )
    assert expect_error(rejected) == _PLAN_BIND

    bindings = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}/bindings', headers=admin_token))
    assert len(bindings) == 1
    binding_id = bindings[0]['id']
    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}/bindings/{binding_id}',
            headers=admin_token,
            json={'end_date': '2026-12-31'},
        )
    )
    kept = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}/bindings', headers=admin_token))
    assert kept[0]['end_date'] == '2026-12-31'
    assert kept[0]['plan_version_id'] == closed_plan['version_id']

    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}/bindings/{binding_id}',
            headers=admin_token,
            json={'plan_version_id': open_plan['version_id']},
        )
    )
    switched_back = client.put(
        f'/rider-salary/riders/{rider["id"]}/bindings/{binding_id}',
        headers=admin_token,
        json={'plan_version_id': closed_plan['version_id']},
    )
    assert expect_error(switched_back) == _PLAN_BIND

    expect_ok(
        client.put(
            f'/rider-salary/plans/{closed_plan["plan_id"]}',
            headers=admin_token,
            json={'status': 'enable'},
        )
    )
    assert closed_plan['version_id'] in _active_version_ids(client, admin_token)
    bind_plan(
        client,
        admin_token,
        rider_id=another['id'],
        version_id=closed_plan['version_id'],
        start_date='2026-01-01',
    )


def test_disabled_plan_cannot_activate_version(client: ApiClient, admin_token: dict[str, str]) -> None:
    """方案停用后仍可建草稿和复制，但不能启用；重新启用方案后再启用版本。"""
    site = create_site(client, admin_token, name='启用拦截站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='试算骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    expect_ok(
        client.put(
            f'/rider-salary/plans/{plan["plan_id"]}',
            headers=admin_token,
            json={'status': 'disable'},
        )
    )
    draft = expect_ok(
        client.post(
            '/rider-salary/plan-versions',
            headers=admin_token,
            json={'plan_id': plan['plan_id'], 'mode_tag': 'per_order', 'remark': '停用后草稿'},
        )
    )
    assert draft['status'] == 'draft'
    copied = expect_ok(client.post(f'/rider-salary/plan-versions/{plan["version_id"]}/copy', headers=admin_token))
    assert copied['status'] == 'draft'

    start, end = month_bounds('2026-09')
    ensure_completed_order_for_trial(
        client,
        admin_token,
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    expect_ok(
        client.post(
            f'/rider-salary/plan-versions/{plan["version_id"]}/trial',
            headers=admin_token,
            json={'rider_id': rider['id'], 'start_date': start, 'end_date': end},
        )
    )
    activated = client.post(f'/rider-salary/plan-versions/{plan["version_id"]}/activate', headers=admin_token)
    assert expect_error(activated) == _PLAN_ACTIVATE

    expect_ok(
        client.put(
            f'/rider-salary/plans/{plan["plan_id"]}',
            headers=admin_token,
            json={'status': 'enable'},
        )
    )
    expect_ok(client.post(f'/rider-salary/plan-versions/{plan["version_id"]}/activate', headers=admin_token))
    detail = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert detail['status'] == 'active'
