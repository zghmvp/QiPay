import re

from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.context import ctx
from backend.common.exception import errors
from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.audit_log import RiderSalaryAuditLog
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.notice import RiderSalaryNotice
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_employ_history import RiderSalaryRiderEmployHistory
from backend.plugin.rider_salary.model.rider_plan_binding import RiderSalaryRiderPlanBinding
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.utils.timezone import timezone
from backend.utils.trace_id import get_request_trace_id

# FBA 测试种子把 admin.nickname 写成「用户88888」，不算有效展示名
_PLACEHOLDER_NICKNAME = re.compile(r'^用户\d+$')
# 11 位手机号：保留前 3 位和后 4 位，中间 4 位打码。13812348000 → 138****8000
_MOBILE_IN_TEXT = re.compile(r'(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)')

# 方案、科目、方案版本没有站点。Q-14：这类全局审计对站点负责人/副手不可见。
_GLOBAL_TARGET_TYPES = frozenset({'plan', 'plan_version', 'subject'})
# 对象 ID 就是业务主键，站点要再查一次。
_LOOKUP_TARGET_TYPES = frozenset({
    'rider',
    'rider_plan_binding',
    'binding',
    'rider_employ_history',
    'order',
    'payroll',
    'period',
    'import_batch',
    'advance',
    'adjustment',
    'notice',
})

REASON_REQUIRED_ACTIONS = frozenset({
    '订单纠错',
    '奖惩修改',
    '奖惩删除',
    '锁账',
    '反冲补发',
    '方案停用',
    '方案回退',
    '预支驳回',
    '预支取消',
    '开通骑手账号',
    '停用骑手账号',
    'order_correct',
    'adjustment_edit',
    'adjustment_delete',
    'period_lock',
    'period_reverse',
    'plan_disable',
    'plan_rollback',
    'advance_reject',
    'advance_cancel',
    'rider_open_account',
    'rider_disable_account',
})


def require_reason(action: str, reason: str | None) -> None:
    """
    校验必填操作原因

    :param action: 动作
    :param reason: 原因
    :return:
    """
    if action in REASON_REQUIRED_ACTIONS and not (reason and reason.strip()):
        raise errors.RequestError(msg='请填写操作原因')


def _user_attr(user: object, *names: str) -> str | None:
    if user is None:
        return None
    dumped: dict[str, Any] | None = None
    for name in names:
        value = None
        if isinstance(user, dict):
            value = user.get(name)
        else:
            value = getattr(user, name, None)
            if value is None and hasattr(user, 'model_dump'):
                if dumped is None:
                    dumped = user.model_dump()
                value = dumped.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def user_display_name(user: object | None) -> str | None:
    """单个用户的显示名。

    优先昵称，其次用户名。占位昵称「用户」加数字不当成名字。
    没有可用名字时返回 None。

    :param user: 用户对象或字典
    :return:
    """
    nickname = _user_attr(user, 'nickname', 'nick_name')
    if nickname and _PLACEHOLDER_NICKNAME.fullmatch(nickname):
        nickname = None
    if nickname:
        return nickname
    username = _user_attr(user, 'username', 'user_name')
    if username and not _PLACEHOLDER_NICKNAME.fullmatch(username):
        return username
    return None


def operator_display_name(request: Request | None) -> str:
    """操作人显示名。没有请求的后台任务写「系统」。

    :param request: 请求对象；后台任务传 None
    :return:
    """
    if request is None:
        return '系统'
    return user_display_name(getattr(request, 'user', None)) or '未知'


def scrub_placeholder_nickname(text: str, request: Request | None) -> str:
    """自定义描述里若拼进了当前用户的占位昵称，换成统一显示名。

    :param text: 审计描述
    :param request: 请求对象
    :return:
    """
    if request is None or not text:
        return text
    nickname = _user_attr(getattr(request, 'user', None), 'nickname', 'nick_name')
    if not nickname or not _PLACEHOLDER_NICKNAME.fullmatch(nickname):
        return text
    display = operator_display_name(request)
    if nickname == display:
        return text
    return text.replace(nickname, display)


def _operator_id(request: Request | None) -> int:
    if request is None:
        return 0
    user = getattr(request, 'user', None)
    if isinstance(user, dict):
        return int(user.get('id') or 0)
    return int(getattr(user, 'id', 0) or 0)


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    state = getattr(request, 'state', None)
    state_ip = getattr(state, 'ip', None) if state is not None else None
    if state_ip:
        return str(state_ip)
    if ctx.exists():
        ctx_ip = getattr(ctx, 'ip', None)
        if ctx_ip:
            return str(ctx_ip)
    client = getattr(request, 'client', None)
    if client is not None:
        return client.host
    return None


def _format_time(operate_time: datetime) -> str:
    return timezone.to_str(operate_time)


def mask_audit_phones(value: Any) -> Any:
    """把快照、描述和原因里的手机号中间 4 位打成星号。

    :param value: 日志字段或嵌套快照
    :return: 打码后的副本，非文本原样返回
    """
    if isinstance(value, str):
        return _MOBILE_IN_TEXT.sub(r'\1****\2', value)
    if isinstance(value, dict):
        return {key: mask_audit_phones(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_audit_phones(item) for item in value]
    return value


def _target_pk(target_id: int | str | None) -> int | None:
    if target_id is None:
        return None
    text = str(target_id).strip()
    if not text.isdigit():
        return None
    return int(text)


def audit_site_hint(*, target_type: str, target_id: int | str | None, action: str) -> tuple[int | None, bool]:
    """判断站点能否不查库确定。

    返回 ``(site_id, needs_lookup)``。``needs_lookup`` 为真时第一项无意义，要按对象主键回查。
    显式传入的 ``site_id`` 优先于本函数。现有写法里，日标记、生成周期、导出订单的对象 ID 就是站点 ID。

    :param target_type: 对象类型
    :param target_id: 对象 ID
    :param action: 动作
    :return:
    """
    if target_type in _GLOBAL_TARGET_TYPES:
        return None, False
    pk = _target_pk(target_id)
    if target_type in {'site', 'day_flag'}:
        return pk, False
    if target_type == 'period' and action == '生成周期':
        return pk, False
    if target_type == 'order' and action == '导出订单':
        return pk, False
    if target_type in _LOOKUP_TARGET_TYPES and pk is not None:
        return None, True
    return None, False


async def resolve_audit_site_id(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: int | str | None,
    action: str,
) -> int | None:
    """调用方未传站点时，按对象类型回填。

    :param db: 数据库会话
    :param target_type: 对象类型
    :param target_id: 对象 ID
    :param action: 动作
    :return: 站点 ID；全局对象或无法判断时为 None
    """
    hinted, needs_lookup = audit_site_hint(target_type=target_type, target_id=target_id, action=action)
    if not needs_lookup:
        return hinted
    pk = _target_pk(target_id)
    if pk is None:
        return None
    await db.flush()
    return await _lookup_site_id(db, target_type, pk)


def _select_rider_site(pk: int) -> Select[tuple[int | None]]:
    return select(RiderSalaryRider.site_id).where(RiderSalaryRider.id == pk)


def _select_binding_site(pk: int) -> Select[tuple[int | None]]:
    return (
        select(RiderSalaryRider.site_id)
        .join(RiderSalaryRiderPlanBinding, RiderSalaryRiderPlanBinding.rider_id == RiderSalaryRider.id)
        .where(RiderSalaryRiderPlanBinding.id == pk)
    )


def _select_history_site(pk: int) -> Select[tuple[int | None]]:
    return (
        select(RiderSalaryRider.site_id)
        .join(RiderSalaryRiderEmployHistory, RiderSalaryRiderEmployHistory.rider_id == RiderSalaryRider.id)
        .where(RiderSalaryRiderEmployHistory.id == pk)
    )


def _select_order_site(pk: int) -> Select[tuple[int | None]]:
    return select(RiderSalaryOrder.site_id).where(RiderSalaryOrder.id == pk)


def _select_payroll_site(pk: int) -> Select[tuple[int | None]]:
    return (
        select(RiderSalarySettlePeriod.site_id)
        .join(RiderSalaryPayroll, RiderSalaryPayroll.period_id == RiderSalarySettlePeriod.id)
        .where(RiderSalaryPayroll.id == pk)
    )


def _select_period_site(pk: int) -> Select[tuple[int | None]]:
    return select(RiderSalarySettlePeriod.site_id).where(RiderSalarySettlePeriod.id == pk)


def _select_batch_site(pk: int) -> Select[tuple[int | None]]:
    return select(RiderSalaryImportBatch.site_id).where(RiderSalaryImportBatch.id == pk)


def _select_advance_site(pk: int) -> Select[tuple[int | None]]:
    return select(RiderSalaryAdvance.site_id).where(RiderSalaryAdvance.id == pk)


def _select_adjustment_site(pk: int) -> Select[tuple[int | None]]:
    return select(RiderSalaryAdjustment.site_id).where(RiderSalaryAdjustment.id == pk)


def _select_notice_site(pk: int) -> Select[tuple[int | None]]:
    return select(RiderSalaryNotice.site_id).where(RiderSalaryNotice.id == pk)


_SITE_SELECTORS = {
    'rider': _select_rider_site,
    'rider_plan_binding': _select_binding_site,
    'binding': _select_binding_site,
    'rider_employ_history': _select_history_site,
    'order': _select_order_site,
    'payroll': _select_payroll_site,
    'period': _select_period_site,
    'import_batch': _select_batch_site,
    'advance': _select_advance_site,
    'adjustment': _select_adjustment_site,
    'notice': _select_notice_site,
}


async def _lookup_site_id(db: AsyncSession, target_type: str, pk: int) -> int | None:
    selector = _SITE_SELECTORS.get(target_type)
    if selector is None:
        return None
    value = await db.scalar(selector(pk))
    return None if value is None else int(value)


def build_description(
    *,
    operator_name: str,
    operate_time: datetime,
    target_label: str,
    action: str,
    reason: str | None,
) -> str:
    """按模板生成审计描述"""
    text = f'{operator_name} 于 {_format_time(operate_time)} 对 {target_label} 执行了 {action}'
    if reason and reason.strip():
        return f'{text}，原因：{reason.strip()}'
    return text


class AuditService:
    """业务审计日志服务"""

    @staticmethod
    async def record(
        db: AsyncSession,
        request: Request,
        *,
        module: str,
        action: str,
        target_type: str,
        target_id: int | str | None,
        target_label: str,
        reason: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        description: str | None = None,
        site_id: int | None = None,
    ) -> None:
        """
        写入业务审计日志

        :param db: 数据库会话
        :param request: 请求对象
        :param module: 模块
        :param action: 动作
        :param target_type: 对象类型
        :param target_id: 对象 ID
        :param target_label: 对象摘要
        :param reason: 原因
        :param before: 变更前
        :param after: 变更后
        :param description: 自然语言描述
        :param site_id: 站点 ID。传入后不再回查；省略时按对象类型回填，全局对象保持为空
        :return:
        """
        require_reason(action, reason)
        operate_time = timezone.now()
        operator_name = operator_display_name(request)
        text = description or build_description(
            operator_name=operator_name,
            operate_time=operate_time,
            target_label=target_label,
            action=action,
            reason=reason,
        )
        text = scrub_placeholder_nickname(text, request)
        target_id_text = None if target_id is None else str(target_id)
        resolved_site_id = site_id
        if resolved_site_id is None:
            resolved_site_id = await resolve_audit_site_id(
                db,
                target_type=target_type,
                target_id=target_id,
                action=action,
            )
        db.add(
            RiderSalaryAuditLog(
                operator_id=_operator_id(request),
                operator_name=operator_name,
                operate_time=operate_time,
                module=module,
                action=action,
                target_type=target_type,
                target_label=target_label,
                target_id=target_id_text,
                reason=reason,
                before=before,
                after=after,
                description=text,
                ip=_client_ip(request),
                trace_id=get_request_trace_id(),
                site_id=resolved_site_id,
            )
        )


audit_service = AuditService()
