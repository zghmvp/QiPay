"""日状态。月历和算薪共用，避免两套条件。"""

from datetime import date

from backend.plugin.rider_salary.enums import DayStatus


def employed_on(hire_date: date | None, leave_date: date | None, day: date) -> bool:
    """日期是否落在在职闭区间内。入职日、离职日为空表示该端不限制。"""
    if hire_date is not None and day < hire_date:
        return False
    return leave_date is None or day <= leave_date


def resolve_day_status(*, has_plan: bool, order_count: int, valid_order_count: int, imported: bool) -> str:
    """无方案且有完成单时标无方案，否则按有数据、无订单、未导入。"""
    if not has_plan and valid_order_count > 0:
        return DayStatus.no_plan.value
    if order_count > 0:
        return DayStatus.has_data.value
    if imported:
        return DayStatus.no_orders.value
    return DayStatus.not_imported.value


def day_status_for(
    *,
    plan_version_id: int | None,
    order_count: int,
    completed_order_count: int,
    employed: bool,
    imported: bool,
) -> str:
    """日历和算薪共用的日状态。

    无方案，且当天在职、有完成单时标无方案。
    入职日之前或离职日之后的完成单，不把这一天标成无方案。

    :param plan_version_id: 当日生效方案版本；没有则为空
    :param order_count: 当日订单数，含未完成
    :param completed_order_count: 当日已完成订单数，不看出勤
    :param employed: 该日是否在职
    :param imported: 该日是否已导入
    :return: 日状态编码
    """
    valid = completed_order_count if employed else 0
    return resolve_day_status(
        has_plan=plan_version_id is not None,
        order_count=order_count,
        valid_order_count=valid,
        imported=imported,
    )
