"""新开户骑手在改密前不能看预计工资，重置密码会重新要求改密。"""

from collections.abc import Generator

import pytest

from factories import create_rider, create_site, expect_ok, login_username, use_shared_db_session
from runtime import ApiClient

_NEW_PASSWORD = 'Changed#Pass1'
_RESET_PASSWORD = 'Changed#Pass2'


@pytest.fixture(autouse=True)
def _one_session_per_request() -> Generator[None, None, None]:
    """改密接口同时拿只读会话和事务会话，单连接上必须合成一个。"""
    with use_shared_db_session():
        yield


def _blocked(client: ApiClient, headers: dict[str, str]) -> None:
    response = client.get('/rider-salary/me/payroll-estimate', headers=headers)
    assert response.status_code == 423, response.text
    body = response.json()
    assert body['code'] == 423
    assert body['msg'] == '请先修改初始密码'
    assert body['data']['error_code'] == 'MUST_CHANGE_PASSWORD'


def _change(client: ApiClient, headers: dict[str, str], old_password: str, new_password: str) -> None:
    expect_ok(
        client.put(
            '/rider-salary/me/password',
            headers=headers,
            json={
                'old_password': old_password,
                'new_password': new_password,
                'confirm_password': new_password,
            },
        )
    )


def test_generated_password_blocks_estimate_until_changed(client: ApiClient, admin_token: dict[str, str]) -> None:
    """不传密码时只返回一次随机口令；改密前预计工资被拒，改密后放行。重置会重新置位。"""
    site = create_site(client, admin_token, name='改密站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='改密骑手')
    opened = expect_ok(
        client.post(
            f'/rider-salary/riders/{rider["id"]}/open-account',
            headers=admin_token,
            json={'reason': '随机开户'},
        )
    )
    password = opened['initial_password']
    assert opened['username'] == rider['job_no']
    assert password
    assert password != 'Rider@123456'

    headers = login_username(client, rider['job_no'], password)
    _blocked(client, headers)
    profile = client.get('/rider-salary/me/profile', headers=headers)
    assert profile.status_code == 423

    _change(client, headers, password, _NEW_PASSWORD)
    estimate = expect_ok(client.get('/rider-salary/me/payroll-estimate', headers=headers))
    assert 'net_estimate' in estimate

    reset = expect_ok(
        client.post(
            f'/rider-salary/riders/{rider["id"]}/reset-password',
            headers=admin_token,
            json={'reason': '重置口令'},
        )
    )
    reset_password = reset['initial_password']
    assert reset_password
    assert reset_password != password
    fresh = login_username(client, rider['job_no'], reset_password)
    _blocked(client, fresh)
    _change(client, fresh, reset_password, _RESET_PASSWORD)
    expect_ok(client.get('/rider-salary/me/payroll-estimate', headers=fresh))


def test_supplied_password_is_not_echoed_but_still_requires_change(
    client: ApiClient, admin_token: dict[str, str]
) -> None:
    """管理员指定的密码不回显，开户后同样必须改密。"""
    site = create_site(client, admin_token, name='指定密码站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='指定密码骑手')
    chosen = 'Supplied#1a'
    opened = expect_ok(
        client.post(
            f'/rider-salary/riders/{rider["id"]}/open-account',
            headers=admin_token,
            json={'password': chosen, 'reason': '指定密码'},
        )
    )
    assert opened['initial_password'] is None
    headers = login_username(client, rider['job_no'], chosen)
    _blocked(client, headers)
