"""日状态四态。月历和算薪共用，避免两套条件。"""

from backend.plugin.rider_salary.enums import DayStatus


def resolve_day_status(*, has_plan: bool, order_count: int, valid_order_count: int, imported: bool) -> str:
    """无方案且有完成单时标无方案，否则按有数据、无订单、未导入。"""
    if not has_plan and valid_order_count > 0:
        return DayStatus.no_plan.value
    if order_count > 0:
        return DayStatus.has_data.value
    if imported:
        return DayStatus.no_orders.value
    return DayStatus.not_imported.value
