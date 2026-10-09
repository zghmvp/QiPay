"""P5-11：重复提交锁账返回 409，且不产生第二条锁账审计。"""

import uuid

from collections.abc import Generator

import pytest

from factories import (
    calculate_period,
    create_rider,
    create_site,
    expect_error,
    expect_ok,
    generate_month,
    get_period,
    lock_period,
    open_rider_account,
    order_row,
    period_payrolls,
    provision_c01_month,
    use_shared_db_session,
)
from runtime import ApiClient

from backend.plugin.rider_salary.service.advance_service import STATUS_CHANGED_MSG
from backend.plugin.rider_salary.service.period_service import PERIOD_STATUS_CHANGED_MSG


@pytest.fixture
def _me_session() -> Generator[None, None, None]:
    """/me 写接口同时拿只读会话和事务会话，单连接上必须合成一个。"""
    with use_shared_db_session():
        yield


def _audit_rows(client: ApiClient, headers: dict[str, str], *, action: str, keyword: str) -> list[dict[str, object]]:
    data = expect_ok(
        client.get(
            '/rider-salary/audit-logs',
            headers=headers,
            params={'page': 1, 'size': 20, 'action': action, 'keyword': keyword},
        )
    )
    return list(data['items'])


def test_repeat_lock_returns_409_without_second_audit(client: ApiClient, admin_token: dict[str, str]) -> None:
    """空周期锁账成功后，再提交两次都是 409，锁账审计只有一条，状态保持已锁账。"""
    token = uuid.uuid4().hex[:8]
    site_name = f'幂等锁账站{token}'
    reason = f'幂等锁账{token}'
    site = create_site(client, admin_token, name=site_name)
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-07')
    period_id = period['id']

    expect_ok(
        client.post(
            f'/rider-salary/periods/{period_id}/lock',
            headers=admin_token,
            json={'reason': reason, 'expected_status': 'open'},
        )
    )
    stale = client.post(
        f'/rider-salary/periods/{period_id}/lock',
        headers=admin_token,
        json={'reason': f'{reason}重复', 'expected_status': 'open'},
    )
    assert expect_error(stale, 409) == PERIOD_STATUS_CHANGED_MSG
    bare = client.post(
        f'/rider-salary/periods/{period_id}/lock',
        headers=admin_token,
        json={'reason': f'{reason}不带期望'},
    )
    assert expect_error(bare, 409) == PERIOD_STATUS_CHANGED_MSG

    detail = get_period(client, admin_token, period_id)
    assert detail['status'] == 'locked'
    logs = _audit_rows(client, admin_token, action='锁账', keyword=site_name)
    assert len(logs) == 1
    assert logs[0]['target_id'] == str(period_id)
    assert logs[0]['action'] == '锁账'


def test_repeat_mark_paid_returns_409_without_second_audit(client: ApiClient, admin_token: dict[str, str]) -> None:
    """已锁账周期标记发薪后再次提交返回 409，标记发薪审计只有一条。"""
    token = uuid.uuid4().hex[:8]
    site_name = f'幂等发薪站{token}'
    site = create_site(client, admin_token, name=site_name)
    period = generate_month(client, admin_token, site_id=site['id'], month='2026-08')
    period_id = period['id']
    lock_period(client, admin_token, period_id, f'发薪前锁账{token}')

    expect_ok(
        client.post(
            f'/rider-salary/periods/{period_id}/mark-paid',
            headers=admin_token,
            json={'reason': f'幂等发薪{token}', 'expected_status': 'locked'},
        )
    )
    again = client.post(
        f'/rider-salary/periods/{period_id}/mark-paid',
        headers=admin_token,
        json={'reason': f'幂等发薪重复{token}', 'expected_status': 'locked'},
    )
    assert expect_error(again, 409) == PERIOD_STATUS_CHANGED_MSG
    detail = get_period(client, admin_token, period_id)
    assert detail['status'] == 'paid'
    logs = _audit_rows(client, admin_token, action='标记发薪', keyword=site_name)
    assert len(logs) == 1
    assert logs[0]['target_id'] == str(period_id)


def test_repeat_reverse_keeps_single_reversal(client: ApiClient, admin_token: dict[str, str]) -> None:
    """再次反冲不生成第二张反冲单。不带期望状态仍是 400；带过期期望状态是 409。"""
    token = uuid.uuid4().hex[:8]
    site_name = f'幂等反冲站{token}'
    ready = provision_c01_month(
        client,
        admin_token,
        month='2026-02',
        orders=[order_row(f'P511-{token}', '2026-02-06')],
        hire_date='2026-02-01',
        rider_name='幂等反冲骑手',
        site_name=site_name,
    )
    period_id = ready['period']['id']
    rider_id = ready['rider']['id']
    calculate_period(client, admin_token, period_id)
    lock_period(client, admin_token, period_id, f'反冲前锁账{token}')

    first = expect_ok(
        client.post(
            f'/rider-salary/periods/{period_id}/reverse',
            headers=admin_token,
            json={'reason': f'幂等反冲{token}', 'expected_status': 'locked'},
        )
    )
    assert first['reversal_count'] == 1

    bare = client.post(
        f'/rider-salary/periods/{period_id}/reverse',
        headers=admin_token,
        json={'reason': f'幂等反冲重复{token}'},
    )
    assert '不允许执行反冲补发' in expect_error(bare, 400)

    stale = client.post(
        f'/rider-salary/periods/{period_id}/reverse',
        headers=admin_token,
        json={'reason': f'幂等反冲过期{token}', 'expected_status': 'locked'},
    )
    assert expect_error(stale, 409) == PERIOD_STATUS_CHANGED_MSG

    payrolls = period_payrolls(client, admin_token, period_id)
    reversals = [row for row in payrolls if row['rider_id'] == rider_id and row['kind'] == 'reversal']
    assert len(reversals) == 1
    detail = get_period(client, admin_token, period_id)
    assert detail['status'] == 'reopened'
    logs = _audit_rows(client, admin_token, action='反冲补发', keyword=site_name)
    assert len(logs) == 1


def test_repeat_advance_review_with_expected_status_returns_409(
    client: ApiClient,
    admin_token: dict[str, str],
    _me_session: None,
) -> None:
    """预支审核带上过期的待审核状态时返回 409，通过和驳回各自只留一条审计。"""
    _ = _me_session
    token = uuid.uuid4().hex[:8]
    site = create_site(client, admin_token, name=f'幂等预支站{token}')
    approver = create_rider(client, admin_token, site_id=site['id'], name='审核骑手', hire_date='2026-10-01')
    rejecter = create_rider(client, admin_token, site_id=site['id'], name='驳回骑手', hire_date='2026-10-01')
    approve_headers = open_rider_account(client, admin_token, rider_id=approver['id'], job_no=approver['job_no'])
    reject_headers = open_rider_account(client, admin_token, rider_id=rejecter['id'], job_no=rejecter['job_no'])
    approved = expect_ok(
        client.post(
            '/rider-salary/me/advances',
            headers=approve_headers,
            json={'amount': '20.00', 'reason': f'幂等通过{token}'},
        )
    )
    rejected = expect_ok(
        client.post(
            '/rider-salary/me/advances',
            headers=reject_headers,
            json={'amount': '30.00', 'reason': f'幂等驳回{token}'},
        )
    )

    expect_ok(
        client.post(
            f'/rider-salary/advances/{approved["id"]}/approve',
            headers=admin_token,
            json={'remark': '同意', 'expected_status': 'pending'},
        )
    )
    again = client.post(
        f'/rider-salary/advances/{approved["id"]}/approve',
        headers=admin_token,
        json={'remark': '再同意', 'expected_status': 'pending'},
    )
    assert expect_error(again, 409) == STATUS_CHANGED_MSG
    approve_detail = expect_ok(client.get(f'/rider-salary/advances/{approved["id"]}', headers=admin_token))
    assert approve_detail['status'] == 'to_pay'
    approve_logs = _audit_rows(client, admin_token, action='预支通过', keyword=f'预支单{approved["id"]}')
    assert len(approve_logs) == 1

    expect_ok(
        client.post(
            f'/rider-salary/advances/{rejected["id"]}/reject',
            headers=admin_token,
            json={'reason': f'资料不全{token}', 'expected_status': 'pending'},
        )
    )
    reject_again = client.post(
        f'/rider-salary/advances/{rejected["id"]}/reject',
        headers=admin_token,
        json={'reason': f'再驳回{token}', 'expected_status': 'pending'},
    )
    assert expect_error(reject_again, 409) == STATUS_CHANGED_MSG
    reject_detail = expect_ok(client.get(f'/rider-salary/advances/{rejected["id"]}', headers=admin_token))
    assert reject_detail['status'] == 'rejected'
    reject_logs = _audit_rows(client, admin_token, action='预支驳回', keyword=f'预支单{rejected["id"]}')
    assert len(reject_logs) == 1
