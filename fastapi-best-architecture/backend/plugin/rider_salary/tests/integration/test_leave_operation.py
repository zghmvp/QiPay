"""P0-04：离职截止绑定、标记当期草稿需重算、驳回待审核预支，锁账周期拒绝。

计划写锁账返回 400。本条与 ``assert_not_locked`` 对齐，实际返回 403。
"""

from collections.abc import Generator

import pytest

from factories import (
    activate_plan,
    bind_plan,
    calculate_period,
    create_c01_plan,
    create_rider,
    create_site,
    expect_error,
    expect_ok,
    generate_month,
    lock_period,
    month_bounds,
    open_rider_account,
    use_shared_db_session,
)
from runtime import ApiClient


@pytest.fixture(autouse=True)
def _one_session_per_request() -> Generator[None, None, None]:
    """/me 写接口同时拿只读会话和事务会话，单连接上必须合成一个。"""
    with use_shared_db_session():
        yield


def _payroll(client: ApiClient, headers: dict[str, str], period_id: int, rider_id: int) -> dict:
    items = expect_ok(
        client.get(
            '/rider-salary/payrolls',
            headers=headers,
            params={'period_id': period_id, 'rider_id': rider_id, 'page': 1, 'size': 20},
        )
    )['items']
    assert len(items) == 1
    return items[0]


def test_leave_closes_binding_and_marks_current_draft_stale(client: ApiClient, admin_token: dict[str, str]) -> None:
    """离职后开放绑定结束日等于离职日，当期草稿变为需重算，用工历史收到离职日。"""
    site = create_site(client, admin_token, name='离职配套站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='离职配套骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-09')
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=plan['version_id'], start_date='2026-01-01')
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    calculated = calculate_period(client, admin_token, period['id'])
    assert calculated['queued'] is False
    assert calculated['calculated'] == 1
    assert _payroll(client, admin_token, period['id'], rider['id'])['stale'] is False

    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}/leave',
            headers=admin_token,
            json={'leave_date': '2026-09-10', 'reason': '个人原因'},
        )
    )

    assert _payroll(client, admin_token, period['id'], rider['id'])['stale'] is True
    bindings = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}/bindings', headers=admin_token))
    assert len(bindings) == 1
    assert bindings[0]['end_date'] == '2026-09-10'
    histories = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}/employ-history', headers=admin_token))
    assert any(item['end_date'] == '2026-09-10' for item in histories)
    detail = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}', headers=admin_token))
    assert detail['status'] == 'resigned'
    assert detail['leave_date'] == '2026-09-10'


def test_leave_on_locked_period_returns_forbidden(client: ApiClient, admin_token: dict[str, str]) -> None:
    """离职日是已锁账周期的最后一天时拒绝，骑手和绑定都不变。"""
    site = create_site(client, admin_token, name='离职锁账站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='锁账离职骑手', hire_date='2026-01-01')
    plan = create_c01_plan(client, admin_token)
    start, end = month_bounds('2026-09')
    activate_plan(
        client,
        admin_token,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, admin_token, rider_id=rider['id'], version_id=plan['version_id'], start_date='2026-01-01')
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-09')
    calculate_period(client, admin_token, period['id'])
    lock_period(client, admin_token, period['id'], '场景锁账')

    blocked = client.put(
        f'/rider-salary/riders/{rider["id"]}/leave',
        headers=admin_token,
        json={'leave_date': '2026-09-30', 'reason': '个人原因'},
    )
    message = expect_error(blocked, 403)
    assert '反冲' in message
    detail = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}', headers=admin_token))
    assert detail['status'] == 'on_job'
    assert detail['leave_date'] is None
    bindings = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}/bindings', headers=admin_token))
    assert bindings[0]['end_date'] is None


def test_leave_before_last_employ_history_rejected(client: ApiClient, admin_token: dict[str, str]) -> None:
    """离职日早于最近一段用工历史的起点时返回 400。"""
    site = create_site(client, admin_token, name='离职日期站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='日期校验骑手', hire_date='2026-01-01')
    expect_ok(
        client.post(
            f'/rider-salary/riders/{rider["id"]}/employ-history',
            headers=admin_token,
            json={'employ_type': 'full_time', 'start_date': '2026-11-01'},
        )
    )
    blocked = client.put(
        f'/rider-salary/riders/{rider["id"]}/leave',
        headers=admin_token,
        json={'leave_date': '2026-10-15', 'reason': '个人原因'},
    )
    message = expect_error(blocked, 400)
    assert '用工历史' in message
    detail = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}', headers=admin_token))
    assert detail['status'] == 'on_job'


def test_leave_auto_rejects_pending_advance(client: ApiClient, admin_token: dict[str, str]) -> None:
    """待审核预支变为已驳回，备注为骑手离职自动驳回。"""
    site = create_site(client, admin_token, name='离职驳回站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='待审预支骑手', hire_date='2026-01-01')
    rider_headers = open_rider_account(client, admin_token, rider_id=rider['id'], job_no=rider['job_no'])
    created = expect_ok(
        client.post(
            '/rider-salary/me/advances',
            headers=rider_headers,
            json={'amount': '50.00', 'reason': '周转'},
        )
    )
    result = expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}/leave',
            headers=admin_token,
            json={'leave_date': '2026-09-10', 'reason': '个人原因'},
        )
    )
    assert result['rejected_advance_count'] == 1
    assert result['to_pay_advance_count'] == 0
    assert any('已驳回' in hint for hint in result['hints'])
    detail = expect_ok(client.get(f'/rider-salary/advances/{created["id"]}', headers=admin_token))
    assert f'{detail["status_label"]}（{detail["approve_remark"]}）' == '已驳回（骑手离职自动驳回）'
    assert detail['status'] == 'rejected'


def test_leave_keeps_to_pay_advance_and_returns_hint(client: ApiClient, admin_token: dict[str, str]) -> None:
    """待发放预支不自动取消，返回提示让管理员取消。"""
    site = create_site(client, admin_token, name='离职待发放站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='待发放骑手', hire_date='2026-01-01')
    rider_headers = open_rider_account(client, admin_token, rider_id=rider['id'], job_no=rider['job_no'])
    created = expect_ok(
        client.post(
            '/rider-salary/me/advances',
            headers=rider_headers,
            json={'amount': '80.00', 'reason': '待发放'},
        )
    )
    expect_ok(
        client.post(
            f'/rider-salary/advances/{created["id"]}/approve',
            headers=admin_token,
            json={'remark': '同意'},
        )
    )
    result = expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}/leave',
            headers=admin_token,
            json={'leave_date': '2026-09-10', 'reason': '个人原因'},
        )
    )
    assert result['to_pay_advance_count'] == 1
    assert result['rejected_advance_count'] == 0
    assert any('取消待发放' in hint for hint in result['hints'])
    detail = expect_ok(client.get(f'/rider-salary/advances/{created["id"]}', headers=admin_token))
    assert detail['status'] == 'to_pay'


def test_leave_hints_outstanding_paid_advance(client: ApiClient, admin_token: dict[str, str]) -> None:
    """已发放未抵扣不自动清零，提示继续在未锁账周期抵扣。"""
    site = create_site(client, admin_token, name='离职待抵站点')
    rider = create_rider(client, admin_token, site_id=site['id'], name='待抵骑手', hire_date='2026-01-01')
    rider_headers = open_rider_account(client, admin_token, rider_id=rider['id'], job_no=rider['job_no'])
    created = expect_ok(
        client.post(
            '/rider-salary/me/advances',
            headers=rider_headers,
            json={'amount': '120.00', 'reason': '已发放'},
        )
    )
    expect_ok(
        client.post(
            f'/rider-salary/advances/{created["id"]}/approve',
            headers=admin_token,
            json={'remark': '同意'},
        )
    )
    expect_ok(
        client.post(
            f'/rider-salary/advances/{created["id"]}/mark-paid',
            headers=admin_token,
            json={'remark': '已发放'},
        )
    )
    result = expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}/leave',
            headers=admin_token,
            json={'leave_date': '2026-09-10', 'reason': '个人原因'},
        )
    )
    assert any('120.00' in hint and '待抵扣' in hint for hint in result['hints'])
    detail = expect_ok(client.get(f'/rider-salary/advances/{created["id"]}', headers=admin_token))
    assert detail['status'] == 'paid'
