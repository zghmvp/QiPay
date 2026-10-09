"""P6-11：未保存草稿试算不落库，求值失败显式返回。"""

import uuid

from typing import Any

from factories import (
    C01_FORMULA,
    create_c01_plan,
    create_rider,
    create_site,
    expect_error,
    expect_ok,
    import_completed_orders,
    money,
    month_bounds,
    order_row,
    subject_id,
)
from runtime import ApiClient
from test_plan_trial_visibility import _site_owner_with_trial

DIV_ZERO = {'类型': '表达式', '表达式': '1 / (订单金额 - 订单金额)'}


def _page_total(client: ApiClient, headers: dict[str, str], path: str) -> int:
    """读取分页接口的总条数。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param path: 接口路径
    :return: total
    """
    page = expect_ok(client.get(path, headers=headers, params={'page': 1, 'size': 1}))
    return int(page['total'])


def _item(client: ApiClient, headers: dict[str, str], *, name: str, formula: dict[str, Any]) -> dict[str, Any]:
    """一条逐单方案项。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param name: 项名称
    :param formula: 公式 JSON
    :return: 请求体中的方案项
    """
    return {
        'subject_id': subject_id(client, headers, 'BASE_UNIT_PRICE'),
        'name': name,
        'stage': 'per_order',
        'sort_order': 0,
        'formula_json': formula,
        'enabled': True,
    }


def _trial(
    client: ApiClient,
    headers: dict[str, str],
    *,
    rider_id: int,
    start: str,
    end: str,
    items: list[dict[str, Any]],
) -> Any:
    """调用未保存草稿试算。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param rider_id: 骑手 ID
    :param start: 开始日期
    :param end: 结束日期
    :param items: 方案项
    :return: httpx 响应
    """
    return client.post(
        '/rider-salary/plan-versions/trial',
        headers=headers,
        json={'rider_id': rider_id, 'start_date': start, 'end_date': end, 'items': items},
    )


def test_unsaved_trial_calculates_without_creating_version(client: ApiClient, admin_token: dict[str, str]) -> None:
    """新建方案不保存就能试算，库里不新增方案或方案版本。"""
    site = create_site(client, admin_token, name='未保存试算站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='未保存试算骑手', hire_date='2026-01-01')
    start, end = month_bounds('2026-02')
    marker = uuid.uuid4().hex[:10].upper()
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row(f'UT{marker}02', '2026-02-02', '20.00')],
    )
    assert imported['success_rows'] == 1
    before_plans = _page_total(client, admin_token, '/rider-salary/plans')
    before_versions = _page_total(client, admin_token, '/rider-salary/plan-versions')
    body = expect_ok(
        _trial(
            client,
            admin_token,
            rider_id=rider['id'],
            start=start,
            end=end,
            items=[_item(client, admin_token, name='基础单价', formula=C01_FORMULA)],
        )
    )
    assert body['passed'] is True
    assert money(body['summary']['per_order_total']) == money('5.00')
    assert body['trial_hash']
    assert _page_total(client, admin_token, '/rider-salary/plans') == before_plans
    assert _page_total(client, admin_token, '/rider-salary/plan-versions') == before_versions


def test_unsaved_trial_does_not_rewrite_saved_draft(client: ApiClient, admin_token: dict[str, str]) -> None:
    """未保存试算不回写已有草稿的试算哈希和快照。"""
    site = create_site(client, admin_token, name='未保存不回写站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='不回写骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-04')
    marker = uuid.uuid4().hex[:10].upper()
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row(f'UW{marker}03', '2026-04-03', '20.00')],
    )
    assert imported['success_rows'] == 1
    before = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert before['trial_hash'] is None
    assert before['trial_passed'] is False
    assert before['trial_snapshot'] is None
    body = expect_ok(
        _trial(
            client,
            admin_token,
            rider_id=rider['id'],
            start=start,
            end=end,
            items=[_item(client, admin_token, name='临时单价', formula={'类型': '固定金额', '金额': 9})],
        )
    )
    assert body['passed'] is True
    assert money(body['summary']['per_order_total']) == money('9.00')
    after = expect_ok(client.get(f'/rider-salary/plan-versions/{plan["version_id"]}', headers=admin_token))
    assert after['trial_hash'] is None
    assert after['trial_passed'] is False
    assert after['trial_snapshot'] is None
    assert after['items_hash'] == before['items_hash']
    assert after['items'][0]['formula_json']['金额'] == 5


def test_unsaved_trial_rejects_other_site_rider(
    client: ApiClient,
    admin_token: dict[str, str],
    role_accounts: dict[str, Any],
) -> None:
    """未保存试算同样校验骑手所属站点。"""
    own_site = create_site(client, admin_token, name='未保存本站')
    other_site = create_site(client, admin_token, name='未保存他站')
    other_rider = create_rider(client, admin_token, site_id=other_site['id'], name='他站骑手', hire_date='2026-01-01')
    start, end = month_bounds('2026-05')
    owner_token = _site_owner_with_trial(client, admin_token, role_accounts, site_id=own_site['id'])
    before_versions = _page_total(client, admin_token, '/rider-salary/plan-versions')
    denied = _trial(
        client,
        owner_token,
        rider_id=other_rider['id'],
        start=start,
        end=end,
        items=[_item(client, admin_token, name='基础单价', formula=C01_FORMULA)],
    )
    assert '无权访问该站点数据' in expect_error(denied, 403)
    assert _page_total(client, admin_token, '/rider-salary/plan-versions') == before_versions


def test_unsaved_eval_failure_is_explicit(client: ApiClient, admin_token: dict[str, str]) -> None:
    """公式求值失败返回告警且不算通过，不打成 500，也不当成试算成功的 0 元。"""
    site = create_site(client, admin_token, name='未保存除零站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='除零骑手', hire_date='2026-01-01')
    start, end = month_bounds('2026-06')
    marker = uuid.uuid4().hex[:10].upper()
    imported = import_completed_orders(
        client,
        admin_token,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=[order_row(f'UE{marker}04', '2026-06-04', '20.00')],
    )
    assert imported['success_rows'] == 1
    response = _trial(
        client,
        admin_token,
        rider_id=rider['id'],
        start=start,
        end=end,
        items=[_item(client, admin_token, name='除零单价', formula=DIV_ZERO)],
    )
    body = expect_ok(response)
    assert response.status_code == 200
    assert body['passed'] is False
    assert body['trial_hash'] is None
    assert any('除零单价' in item and '公式求值失败' in item for item in body['warnings'])


def test_unsaved_empty_formula_is_rejected(client: ApiClient, admin_token: dict[str, str]) -> None:
    """空公式在试算前拒绝，不会按 0 元算出通过结果。"""
    site = create_site(client, admin_token, name='未保存空公式站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='空公式骑手', hire_date='2026-01-01')
    start, end = month_bounds('2026-07')
    message = expect_error(
        _trial(
            client,
            admin_token,
            rider_id=rider['id'],
            start=start,
            end=end,
            items=[
                _item(client, admin_token, name='空公式', formula={'类型': '表达式', '表达式': ''}),
            ],
        )
    )
    assert '表达式' in message or '公式' in message


def test_unsaved_zero_order_trial_returns_400(client: ApiClient, admin_token: dict[str, str]) -> None:
    """没有已完成订单时拒绝，且不新增方案版本。"""
    site = create_site(client, admin_token, name='未保存零单站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='零单骑手', hire_date='2026-01-01')
    start, end = month_bounds('2026-08')
    before_versions = _page_total(client, admin_token, '/rider-salary/plan-versions')
    message = expect_error(
        _trial(
            client,
            admin_token,
            rider_id=rider['id'],
            start=start,
            end=end,
            items=[_item(client, admin_token, name='基础单价', formula=C01_FORMULA)],
        )
    )
    assert '已完成订单' in message
    assert _page_total(client, admin_token, '/rider-salary/plan-versions') == before_versions
