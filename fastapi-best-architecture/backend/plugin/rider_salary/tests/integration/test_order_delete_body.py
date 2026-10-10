"""P6-15：订单删除原因放在请求体，访问日志不记录原因文本。"""

from urllib.parse import quote

from factories import create_rider, create_site, expect_ok
from loguru import logger
from runtime import ApiClient

_REASON = 'P615水印原因不会进访问日志'


def _create_order(client: ApiClient, headers: dict[str, str], *, site_id: int, rider_id: int) -> int:
    created = expect_ok(
        client.post(
            '/rider-salary/orders',
            headers=headers,
            json={
                'order_no': 'P615DEL0001',
                'site_id': site_id,
                'rider_id': rider_id,
                'distance_km': '1.20',
                'weight_jin': '2.00',
                'order_time': '2026-10-08T10:00:00',
                'deliver_time': '2026-10-08T10:20:00',
                'status': 'completed',
                'amount': '18.00',
                'remark': '删除原因改请求体',
            },
        )
    )
    return int(created['id'])


def test_delete_reason_is_body_and_absent_from_access_log(
    client: ApiClient,
    admin_token: dict[str, str],
) -> None:
    """删除原因走 JSON 请求体。INFO 访问日志不含原文，也不含其 URL 编码。"""
    site = create_site(client, admin_token, name='删除原因站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='删除原因骑手', hire_date='2026-09-01')
    order_id = _create_order(client, admin_token, site_id=site['id'], rider_id=rider['id'])
    query_only = client.delete(f'/rider-salary/orders/{order_id}', headers=admin_token)
    assert query_only.status_code == 422, query_only.text
    still_there = expect_ok(client.get(f'/rider-salary/orders/{order_id}', headers=admin_token))
    assert still_there['id'] == order_id

    captured: list[str] = []

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        if record['level'].no <= 25:
            captured.append(str(record['message']))

    sink_id = logger.add(_sink, level='INFO')
    try:
        deleted = client.delete(
            f'/rider-salary/orders/{order_id}',
            headers=admin_token,
            json={'reason': _REASON},
        )
    finally:
        logger.remove(sink_id)

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()['code'] == 200
    assert 'reason=' not in str(deleted.request.url)
    assert _REASON not in str(deleted.request.url)
    missing = client.get(f'/rider-salary/orders/{order_id}', headers=admin_token)
    assert missing.status_code == 404
    blob = '\n'.join(captured)
    assert captured, '访问日志应至少有一条 INFO'
    assert _REASON not in blob
    assert quote(_REASON) not in blob
    assert any('DELETE' in line and f'/orders/{order_id}' in line for line in captured)


def test_delete_reason_rejects_overlong_text(client: ApiClient, admin_token: dict[str, str]) -> None:
    """删除原因超长时返回 422 中文提示。"""
    site = create_site(client, admin_token, name='删除原因超长站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='删除原因超长骑手')
    order_id = _create_order(client, admin_token, site_id=site['id'], rider_id=rider['id'])
    response = client.delete(
        f'/rider-salary/orders/{order_id}',
        headers=admin_token,
        json={'reason': '因' * 501},
    )
    body = response.json()
    assert response.status_code == 422, body
    assert body['code'] == 422
    assert '删除原因不能超过 500 个字' in body['msg']
