"""超长入参应返回 422 中文提示，而不是数据库 500。"""

from factories import create_site
from runtime import ApiClient


def test_long_rider_name_is_chinese_422(client: ApiClient, admin_token: dict[str, str]) -> None:
    """超长骑手姓名返回 422，提示为中文。"""
    site = create_site(client, admin_token)
    response = client.post(
        '/rider-salary/riders',
        headers=admin_token,
        json={
            'job_no': 'LONGNAME01',
            'name': '名' * 33,
            'site_id': site['id'],
            'employ_type': 'part_time',
            'hire_date': '2026-09-01',
            'status': 'on_job',
        },
    )
    body = response.json()
    assert response.status_code == 422
    assert body['code'] == 422
    assert '请求参数非法' in body['msg']
    assert '姓名不能超过 32 个字' in body['msg']
    assert 'String should' not in body['msg']


def test_advance_reason_length_is_chinese_422(client: ApiClient, rider_token: dict[str, str]) -> None:
    """预支原因超长时，骑手端返回 422 中文提示。"""
    response = client.post(
        '/rider-salary/me/advances',
        headers=rider_token,
        json={'amount': '100.00', 'reason': '因' * 201},
    )
    body = response.json()
    assert response.status_code == 422
    assert body['code'] == 422
    assert '请求参数非法' in body['msg']
    assert '申请原因不能超过 200 个字' in body['msg']
    assert 'String should' not in body['msg']
