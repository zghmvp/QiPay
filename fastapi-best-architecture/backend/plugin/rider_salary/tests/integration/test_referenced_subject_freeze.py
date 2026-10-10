"""P2-02：被引用科目不能改方向和是否进应发；方案项拒绝停用或限定范围的科目。

Q-10 采用推荐方案 A。未保存试算和已保存草稿的试算回写不在这里改。
"""

import uuid

from factories import (
    create_rider,
    create_site,
    ensure_completed_order_for_trial,
    expect_error,
    expect_ok,
    month_bounds,
)
from runtime import ApiClient

_MISSING_SUBJECT = 9_007_199_254_740_991


def _create_subject(client: ApiClient, headers: dict[str, str], **extra: object) -> dict:
    """创建自定义科目并按编码查回。"""
    code = str(extra.pop('code', f'P202{uuid.uuid4().hex[:8].upper()}'))
    payload: dict[str, object] = {
        'code': code,
        'name': extra.pop('name', '冻结科目'),
        'direction': 'bonus',
        'include_in_gross': True,
        'status': 'enable',
    }
    payload.update(extra)
    expect_ok(client.post('/rider-salary/subjects', headers=headers, json=payload))
    rows = expect_ok(client.get('/rider-salary/subjects/all', headers=headers))
    for row in rows:
        if row['code'] == code:
            return row
    raise AssertionError(f'未找到科目 {code}')


def _draft_version(client: ApiClient, headers: dict[str, str]) -> int:
    """新建一份空草稿版本。"""
    plan = expect_ok(
        client.post(
            '/rider-salary/plans',
            headers=headers,
            json={
                'code': f'P202{uuid.uuid4().hex[:6].upper()}',
                'name': '科目校验方案',
                'short_name': '科目',
                'color': '#1677ff',
                'status': 'enable',
            },
        )
    )
    version = expect_ok(
        client.post(
            '/rider-salary/plan-versions',
            headers=headers,
            json={'plan_id': plan['id'], 'mode_tag': 'per_order'},
        )
    )
    return int(version['id'])


def _item(subject_id: int, name: str = '基础') -> dict[str, object]:
    return {
        'subject_id': subject_id,
        'name': name,
        'stage': 'per_order',
        'sort_order': 0,
        'formula_json': {'类型': '固定金额', '金额': 5},
        'enabled': True,
    }


def test_referenced_by_plan_item_direction_returns_400(client: ApiClient, admin_token: dict[str, str]) -> None:
    """未被引用时可以改方向；写入方案项后改方向返回 400，原方向保留。"""
    subject = _create_subject(client, admin_token, name='方案项冻结')
    expect_ok(
        client.put(
            f'/rider-salary/subjects/{subject["id"]}',
            headers=admin_token,
            json={'direction': 'penalty'},
        )
    )
    version_id = _draft_version(client, admin_token)
    expect_ok(
        client.put(
            f'/rider-salary/plan-versions/{version_id}/items',
            headers=admin_token,
            json=[_item(subject['id'], '扣款项')],
        )
    )
    changed = client.put(
        f'/rider-salary/subjects/{subject["id"]}',
        headers=admin_token,
        json={'direction': 'bonus'},
    )
    assert '不能修改方向或是否进应发' in expect_error(changed)
    detail = expect_ok(client.get(f'/rider-salary/subjects/{subject["id"]}', headers=admin_token))
    assert detail['direction'] == 'penalty'
    expect_ok(
        client.put(
            f'/rider-salary/subjects/{subject["id"]}',
            headers=admin_token,
            json={'name': '方案项冻结改名', 'direction': 'penalty'},
        )
    )


def test_referenced_by_adjustment_include_in_gross_returns_400(client: ApiClient, admin_token: dict[str, str]) -> None:
    """奖惩引用后不能把科目改成不进应发。"""
    subject = _create_subject(
        client,
        admin_token,
        name='奖惩冻结',
        direction='penalty',
        include_in_gross=True,
    )
    site = create_site(client, admin_token, name='科目冻结站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='科目冻结骑手', hire_date='2026-09-01')
    expect_ok(
        client.post(
            '/rider-salary/adjustments',
            headers=admin_token,
            json={
                'rider_id': rider['id'],
                'biz_date': '2026-10-08',
                'subject_id': subject['id'],
                'amount': '12.00',
                'remark': '引用后冻结是否进应发',
            },
        )
    )
    changed = client.put(
        f'/rider-salary/subjects/{subject["id"]}',
        headers=admin_token,
        json={'include_in_gross': False},
    )
    assert '不能修改方向或是否进应发' in expect_error(changed)
    detail = expect_ok(client.get(f'/rider-salary/subjects/{subject["id"]}', headers=admin_token))
    assert detail['include_in_gross'] is True


def test_disabled_subject_save_fails(client: ApiClient, admin_token: dict[str, str]) -> None:
    """方案项引用已停用科目时保存失败，版本上不留下方案项。重新启用后可以保存。"""
    subject = _create_subject(client, admin_token, name='已停用科目', status='disable')
    version_id = _draft_version(client, admin_token)
    saved = client.put(
        f'/rider-salary/plan-versions/{version_id}/items',
        headers=admin_token,
        json=[_item(subject['id'], '停用项')],
    )
    assert '已停用' in expect_error(saved)
    empty = expect_ok(client.get(f'/rider-salary/plan-versions/{version_id}', headers=admin_token))
    assert empty['items'] == []

    expect_ok(
        client.put(
            f'/rider-salary/subjects/{subject["id"]}',
            headers=admin_token,
            json={'status': 'enable'},
        )
    )
    expect_ok(
        client.put(
            f'/rider-salary/plan-versions/{version_id}/items',
            headers=admin_token,
            json=[_item(subject['id'], '停用项')],
        )
    )


def test_missing_or_scoped_subject_save_fails(client: ApiClient, admin_token: dict[str, str]) -> None:
    """科目不存在，或限定了站点、用工类型时，保存方案项失败。"""
    version_id = _draft_version(client, admin_token)
    missing = client.put(
        f'/rider-salary/plan-versions/{version_id}/items',
        headers=admin_token,
        json=[_item(_MISSING_SUBJECT, '缺失科目')],
    )
    assert '科目不存在' in expect_error(missing)

    site = create_site(client, admin_token, name='范围站点')
    scoped = _create_subject(client, admin_token, name='限站点', scope_sites=[site['id']])
    rejected = client.put(
        f'/rider-salary/plan-versions/{version_id}/items',
        headers=admin_token,
        json=[_item(scoped['id'], '限站点项')],
    )
    assert '适用范围' in expect_error(rejected)

    employ = _create_subject(client, admin_token, name='限全职', scope_employ_types=['full_time'])
    rejected_employ = client.put(
        f'/rider-salary/plan-versions/{version_id}/items',
        headers=admin_token,
        json=[_item(employ['id'], '限全职项')],
    )
    assert '适用范围' in expect_error(rejected_employ)
    detail = expect_ok(client.get(f'/rider-salary/plan-versions/{version_id}', headers=admin_token))
    assert detail['items'] == []


def test_activate_rejects_subject_disabled_after_trial(client: ApiClient, admin_token: dict[str, str]) -> None:
    """试算仍只给未使用草稿回写哈希；之后停用科目，启用被拒绝且哈希不变。"""
    subject = _create_subject(client, admin_token, name='启用前停用')
    version_id = _draft_version(client, admin_token)
    expect_ok(
        client.put(
            f'/rider-salary/plan-versions/{version_id}/items',
            headers=admin_token,
            json=[_item(subject['id'])],
        )
    )
    site = create_site(client, admin_token, name='启用校验站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='启用校验骑手', hire_date='2026-09-01')
    start, end = month_bounds('2026-10')
    ensure_completed_order_for_trial(
        client,
        admin_token,
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    expect_ok(
        client.post(
            f'/rider-salary/plan-versions/{version_id}/trial',
            headers=admin_token,
            json={'rider_id': rider['id'], 'start_date': start, 'end_date': end},
        )
    )
    before = expect_ok(client.get(f'/rider-salary/plan-versions/{version_id}', headers=admin_token))
    assert before['trial_passed'] is True
    assert before['trial_hash']
    expect_ok(
        client.put(
            f'/rider-salary/subjects/{subject["id"]}',
            headers=admin_token,
            json={'status': 'disable'},
        )
    )
    activated = client.post(f'/rider-salary/plan-versions/{version_id}/activate', headers=admin_token)
    assert '已停用' in expect_error(activated)
    after = expect_ok(client.get(f'/rider-salary/plan-versions/{version_id}', headers=admin_token))
    assert after['status'] == 'draft'
    assert after['trial_hash'] == before['trial_hash']
    assert after['trial_passed'] is True
