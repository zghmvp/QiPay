"""主数据生命周期组合校验。

停用站点不能再分配骑手；离职骑手不能开通或重新启用账号；
停用方案即使底下还有启用中的版本，也不能用于新绑定，也不能再启用版本。
已有绑定只改日期、停用方案上继续写草稿，不走这里的拒绝。
"""

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import EnableStatus, PlanVersionStatus, RiderStatus

MSG_SITE_DISABLED = '所属站点已停用，不能分配新骑手'
MSG_RIDER_RESIGNED_OPEN = '离职骑手不能开通账号'
MSG_RIDER_RESIGNED_ENABLE = '离职骑手不能启用账号'
MSG_VERSION_NOT_ACTIVE = '只能绑定启用状态的方案版本'
MSG_PLAN_DISABLED_BIND = '停用方案不能用于新绑定'
MSG_PLAN_DISABLED_ACTIVATE = '方案已停用，不能启用版本'


def status_text(value: object | None) -> str:
    """枚举或字符串状态统一成存储值。

    :param value: 状态
    :return:
    """
    if value is None:
        return ''
    raw = getattr(value, 'value', value)
    return str(raw)


def is_disabled(status: object | None) -> bool:
    """是否为停用。缺省视为启用，与站点和方案的默认值一致。

    :param status: 状态
    :return:
    """
    return status_text(status) == EnableStatus.disable.value


def is_resigned(rider: object) -> bool:
    """骑手是否已离职。

    :param rider: 骑手
    :return:
    """
    return status_text(getattr(rider, 'status', None)) == RiderStatus.resigned.value


def plan_accepts_new_binding(plan: object) -> bool:
    """方案处于启用时才能用于新绑定。

    :param plan: 方案
    :return:
    """
    return not is_disabled(getattr(plan, 'status', None))


def assert_site_accepts_rider(site: object) -> None:
    """停用站点不能新建骑手，也不能把已有骑手换进来。

    :param site: 目标站点，调用方已确认存在
    :return:
    """
    if is_disabled(getattr(site, 'status', None)):
        raise errors.RequestError(msg=MSG_SITE_DISABLED)


def assert_rider_can_open_account(rider: object) -> None:
    """离职骑手不能开通账号。

    :param rider: 骑手
    :return:
    """
    if is_resigned(rider):
        raise errors.RequestError(msg=MSG_RIDER_RESIGNED_OPEN)


def assert_rider_can_enable_account(rider: object) -> None:
    """离职骑手不能重新启用账号。

    :param rider: 骑手
    :return:
    """
    if is_resigned(rider):
        raise errors.RequestError(msg=MSG_RIDER_RESIGNED_ENABLE)


def assert_binding_target(version: object, plan: object | None, *, new_assignment: bool) -> None:
    """绑定目标必须是启用中的版本；新绑定还要求所属方案未停用。

    已有绑定只改日期时 ``new_assignment`` 为 False：版本仍须是启用，
    但不因方案后来停用而拒绝这段历史修正。

    :param version: 方案版本
    :param plan: 所属方案。只改已有绑定的日期时可以不传
    :param new_assignment: 新建绑定，或把已有绑定改到另一个版本
    :return:
    """
    if status_text(getattr(version, 'status', None)) != PlanVersionStatus.active.value:
        raise errors.RequestError(msg=MSG_VERSION_NOT_ACTIVE)
    if new_assignment and (plan is None or not plan_accepts_new_binding(plan)):
        raise errors.RequestError(msg=MSG_PLAN_DISABLED_BIND)


def assert_plan_can_activate(plan: object) -> None:
    """停用方案不能再启用版本。

    :param plan: 方案
    :return:
    """
    if not plan_accepts_new_binding(plan):
        raise errors.RequestError(msg=MSG_PLAN_DISABLED_ACTIVATE)
