"""P6-09：骑手预支列表返回精简时间线，不再固定为空。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import anyio

from backend.plugin.rider_salary.enums import AdvanceStatus
from backend.plugin.rider_salary.service.advance_service import advance_service, compact_advance_timeline

TZ = ZoneInfo('Asia/Shanghai')
T_SUBMIT = datetime(2026, 9, 1, 9, 0, tzinfo=TZ)
T_APPROVE = datetime(2026, 9, 1, 10, 0, tzinfo=TZ)
T_PAID = datetime(2026, 9, 1, 11, 0, tzinfo=TZ)
T_CANCEL = datetime(2026, 9, 1, 12, 0, tzinfo=TZ)


def _names(**kwargs: str | None) -> dict[str, str | None]:
    base: dict[str, str | None] = {
        'rider_name': '张伟',
        'approver_name': '站长',
        'paid_by_name': '财务',
    }
    base.update(kwargs)
    return base


def test_pending_timeline_is_submit_only() -> None:
    row = SimpleNamespace(
        status=AdvanceStatus.pending.value,
        submit_time=T_SUBMIT,
        approve_time=None,
        paid_time=None,
        cancel_time=None,
        approve_remark=None,
    )
    nodes = compact_advance_timeline(row, _names())
    assert [item['action'] for item in nodes] == ['提交预支']
    assert nodes[0]['operator_name'] == '张伟'


def test_paid_timeline_keeps_submit_approve_and_pay() -> None:
    row = SimpleNamespace(
        status=AdvanceStatus.paid.value,
        submit_time=T_SUBMIT,
        approve_time=T_APPROVE,
        paid_time=T_PAID,
        cancel_time=None,
        approve_remark='同意',
    )
    nodes = compact_advance_timeline(row, _names())
    assert [item['action'] for item in nodes] == ['提交预支', '预支通过', '预支发放标记']
    assert nodes[1]['operator_name'] == '站长'
    assert nodes[1]['reason'] == '同意'
    assert nodes[2]['operator_name'] == '财务'


def test_rejected_uses_reject_action() -> None:
    row = SimpleNamespace(
        status=AdvanceStatus.rejected.value,
        submit_time=T_SUBMIT,
        approve_time=T_APPROVE,
        paid_time=None,
        cancel_time=None,
        approve_remark='额度紧张',
    )
    nodes = compact_advance_timeline(row, _names())
    assert [item['action'] for item in nodes] == ['提交预支', '预支驳回']
    assert nodes[1]['reason'] == '额度紧张'


def test_rider_cancel_before_approval_uses_rider_name() -> None:
    row = SimpleNamespace(
        status=AdvanceStatus.cancelled.value,
        submit_time=T_SUBMIT,
        approve_time=None,
        paid_time=None,
        cancel_time=T_CANCEL,
        approve_remark=None,
    )
    nodes = compact_advance_timeline(row, _names())
    assert [item['action'] for item in nodes] == ['提交预支', '预支取消']
    assert nodes[1]['operator_name'] == '张伟'


def test_admin_cancel_after_approval_uses_admin_label() -> None:
    row = SimpleNamespace(
        status=AdvanceStatus.cancelled.value,
        submit_time=T_SUBMIT,
        approve_time=T_APPROVE,
        paid_time=None,
        cancel_time=T_CANCEL,
        approve_remark='先通过',
    )
    nodes = compact_advance_timeline(row, _names())
    assert [item['action'] for item in nodes] == ['提交预支', '预支通过', '预支取消']
    assert nodes[2]['operator_name'] == '管理员'


def test_nodes_sort_by_time_not_insert_order() -> None:
    row = SimpleNamespace(
        status=AdvanceStatus.paid.value,
        submit_time=T_SUBMIT,
        approve_time=T_APPROVE,
        paid_time=T_PAID,
        cancel_time=None,
        approve_remark=None,
    )
    nodes = compact_advance_timeline(row, _names())
    times = [item['operate_time'] for item in nodes]
    assert times == sorted(times)


def _detail_payload(status: str) -> dict[str, object]:
    return {
        'id': 7,
        'rider_id': 18,
        'site_id': 1,
        'amount': Decimal('200.00'),
        'reason': '周转',
        'status': status,
        'approver_id': 3,
        'approve_time': T_APPROVE,
        'approve_remark': '同意',
        'paid_by': None,
        'paid_time': None,
        'deducted_amount': Decimal('0.00'),
        'remaining_amount': None,
        'deduct_status': 'none',
        'submit_time': T_SUBMIT,
        'cancel_time': None,
        'rider_job_no': 'D5A001',
        'rider_name': '张伟',
        'site_name': '朝阳一站',
        'approver_name': '站长',
        'paid_by_name': None,
        'timeline': [],
        'created_time': T_SUBMIT,
        'updated_time': None,
    }


def test_list_for_rider_replaces_empty_timeline() -> None:
    """列表组装不再把 timeline 留空。"""
    row = SimpleNamespace(
        id=7,
        status=AdvanceStatus.to_pay.value,
        submit_time=T_SUBMIT,
        approve_time=T_APPROVE,
        paid_time=None,
        cancel_time=None,
        approve_remark='同意',
    )
    payload = _detail_payload(AdvanceStatus.to_pay.value)

    async def _run() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.advance_service.advance_dao.list_by_rider',
                AsyncMock(return_value=[row]),
            ),
            patch.object(advance_service, '_enrich', AsyncMock(return_value={7: payload})),
        ):
            items = await advance_service.list_for_rider(db=AsyncMock(), rider_id=18)
        assert [node.action for node in items[0].timeline] == ['提交预支', '预支通过']
        assert items[0].timeline[0].operator_name == '张伟'
        assert payload['timeline'] != []

    anyio.run(_run)
