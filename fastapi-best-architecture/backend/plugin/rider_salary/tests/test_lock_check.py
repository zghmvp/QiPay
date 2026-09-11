from backend.plugin.rider_salary.enums import PeriodStatus
from backend.plugin.rider_salary.schema.day_flag import GetDayFlagDetail
from backend.plugin.rider_salary.utils.lock_check import is_status_locked


def test_locked_statuses() -> None:
    assert is_status_locked(PeriodStatus.locked)
    assert is_status_locked(PeriodStatus.paid)
    assert is_status_locked('locked')
    assert is_status_locked('paid')
    assert not is_status_locked(PeriodStatus.open)
    assert not is_status_locked('reopened')
    assert not is_status_locked(None)


def test_day_flag_detail_has_is_locked() -> None:
    from datetime import date

    detail = GetDayFlagDetail(site_id=1, biz_date=date(2026, 9, 1), is_locked=True)
    assert detail.is_locked is True
    empty = GetDayFlagDetail(site_id=1, biz_date=date(2026, 9, 2))
    assert empty.is_locked is False
