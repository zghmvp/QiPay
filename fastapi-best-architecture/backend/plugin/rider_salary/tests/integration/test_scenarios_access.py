"""E9、E14：骑手不能调用管理端读接口，站点负责人不能看到其他站点的审计。"""

import json

from factories import bind_site_manager, create_rider_with_phone, create_site, expect_error, expect_ok
from runtime import ApiClient, RoleAccount


def test_e9_rider_token_cannot_call_admin_reads(
    client: ApiClient,
    rider_token: dict[str, str],
) -> None:
    """E9 / P3-04：骑手 token 访问骑手列表、订单列表和公式校验都返回 403。"""
    riders = client.get('/rider-salary/riders', headers=rider_token, params={'page': 1, 'size': 20})
    orders = client.get('/rider-salary/orders', headers=rider_token, params={'page': 1, 'size': 20})
    engine = client.post(
        '/rider-salary/engine/validate',
        headers=rider_token,
        json={'stage': 'per_order'},
    )
    for response in (riders, orders, engine):
        message = expect_error(response, 403)
        assert message is not None


def test_e14_owner_cannot_read_other_site_audit(
    client: ApiClient,
    admin_token: dict[str, str],
    site_owner_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """E14 / P3-01：负责人看不到其他站点的审计快照；跨站读骑手详情返回 403。Q-14 采用不可见且打码。"""
    own_site = create_site(client, admin_token, name='审计本站')
    other_site = create_site(client, admin_token, name='审计他站')
    bind_site_manager(
        client,
        admin_token,
        site_id=own_site['id'],
        user_id=role_accounts['site_owner'].user_id,
    )
    own_phone = '13812348000'
    other_phone = '13900002222'
    own_rider = create_rider_with_phone(
        client,
        admin_token,
        site_id=own_site['id'],
        phone=own_phone,
        name='本站骑手',
        hire_date='2026-09-01',
    )
    other_rider = create_rider_with_phone(
        client,
        admin_token,
        site_id=other_site['id'],
        phone=other_phone,
        name='他站骑手',
        hire_date='2026-09-01',
    )
    cross = client.get(f'/rider-salary/riders/{other_rider["id"]}', headers=site_owner_token)
    expect_error(cross, 403)
    own = expect_ok(client.get(f'/rider-salary/riders/{own_rider["id"]}', headers=site_owner_token))
    assert own['job_no'] == own_rider['job_no']

    logs = _all_audit_logs(client, site_owner_token)
    text = json.dumps(logs, ensure_ascii=False, default=str)
    assert other_rider['job_no'] not in text
    assert other_phone not in text
    assert own_rider['job_no'] in text
    assert own_phone not in text
    assert '138****8000' in text


def _all_audit_logs(client: ApiClient, headers: dict[str, str]) -> list[dict]:
    items: list[dict] = []
    page = 1
    while page <= 20:
        data = expect_ok(client.get('/rider-salary/audit-logs', headers=headers, params={'page': page, 'size': 100}))
        batch = list(data['items'])
        items.extend(batch)
        total = int(data.get('total') or 0)
        if not batch or len(items) >= total:
            break
        page += 1
    return items
