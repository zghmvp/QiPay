"""Q-14：全局审计对站点角色不可见；副手同样隔离；全站角色看到原始手机号。"""

import json
import uuid

from factories import bind_site_manager, create_rider_with_phone, create_site, expect_ok
from runtime import ApiClient, RoleAccount


def test_global_audit_hidden_from_site_roles_admin_sees_raw_phone(
    client: ApiClient,
    admin_token: dict[str, str],
    salary_admin_token: dict[str, str],
    site_deputy_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """科目审计没有站点，负责人和副手都看不到；薪资管理员能看到明文手机号。"""
    own_site = create_site(client, admin_token, name='审计副手本站')
    other_site = create_site(client, admin_token, name='审计副手他站')
    bind_site_manager(
        client,
        admin_token,
        site_id=own_site['id'],
        user_id=role_accounts['site_deputy'].user_id,
        role='deputy',
    )
    phone = '13711112222'
    own_rider = create_rider_with_phone(
        client,
        admin_token,
        site_id=own_site['id'],
        phone=phone,
        name='副手本站骑手',
    )
    other_rider = create_rider_with_phone(
        client,
        admin_token,
        site_id=other_site['id'],
        phone='13600003333',
        name='副手他站骑手',
    )
    subject_name = f'全局科目{uuid.uuid4().hex[:6]}'
    expect_ok(
        client.post(
            '/rider-salary/subjects',
            headers=admin_token,
            json={'code': f'Q14{uuid.uuid4().hex[:8].upper()}', 'name': subject_name, 'direction': 'bonus'},
        )
    )

    deputy_logs = _all_audit_logs(client, site_deputy_token)
    deputy_text = json.dumps(deputy_logs, ensure_ascii=False, default=str)
    assert other_rider['job_no'] not in deputy_text
    assert phone not in deputy_text
    assert '137****2222' in deputy_text
    assert own_rider['job_no'] in deputy_text
    assert subject_name not in deputy_text
    assert {item.get('site_id') for item in deputy_logs} <= {own_site['id']}

    admin_logs = _all_audit_logs(client, salary_admin_token)
    admin_text = json.dumps(admin_logs, ensure_ascii=False, default=str)
    assert phone in admin_text
    assert subject_name in admin_text
    matched = [
        item
        for item in admin_logs
        if item.get('target_type') == 'rider' and str(item.get('target_id')) == str(own_rider['id'])
    ]
    assert matched
    assert matched[-1]['site_id'] == own_site['id']
    assert matched[-1]['after']['phone'] == phone


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
