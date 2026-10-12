"""P6-13：批量奖惩收集全部行错误后一次返回，整单回滚。"""

from factories import create_rider, create_site, expect_ok, subject_id
from runtime import ApiClient

_MISSING_ID = 9_007_199_254_740_991


def _item(*, rider_id: int, subject: int, amount: str, remark: str) -> dict[str, object]:
    return {
        'rider_id': rider_id,
        'biz_date': '2026-10-08',
        'subject_id': subject,
        'amount': amount,
        'remark': remark,
    }


def test_three_row_errors_returned_once_and_batch_rolls_back(
    client: ApiClient,
    admin_token: dict[str, str],
) -> None:
    """3 行错误一次返回 3 条中文提示；前面已通过的行也随整单回滚。"""
    site = create_site(client, admin_token, name='批量奖惩站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='批量奖惩骑手', hire_date='2026-09-01')
    complaint = subject_id(client, admin_token, 'COMPLAINT')
    response = client.post(
        '/rider-salary/adjustments/batch',
        headers=admin_token,
        json={
            'items': [
                _item(rider_id=rider['id'], subject=complaint, amount='12.50', remark='这行应整单回滚'),
                _item(rider_id=_MISSING_ID, subject=complaint, amount='8.00', remark='骑手不存在'),
                _item(rider_id=rider['id'], subject=_MISSING_ID, amount='8.00', remark='科目不存在'),
                _item(rider_id=rider['id'], subject=complaint, amount='0.00', remark='金额为零'),
            ]
        },
    )
    body = response.json()
    assert response.status_code == 400, body
    assert body['code'] == 400
    row_errors = body['data']['errors']
    assert [item['row'] for item in row_errors] == [2, 3, 4]
    assert [item['reason'] for item in row_errors] == ['骑手不存在', '科目不存在', '金额必须大于 0']
    for item in row_errors:
        assert f'第 {item["row"]} 行：{item["reason"]}' in body['msg']
    listed = expect_ok(
        client.get(
            '/rider-salary/adjustments',
            headers=admin_token,
            params={'rider_id': rider['id'], 'page': 1, 'size': 20},
        )
    )
    assert listed['total'] == 0
    assert listed['items'] == []
