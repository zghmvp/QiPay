from backend.plugin.rider_salary.enums import PeriodStatus
from backend.plugin.rider_salary.utils.lock_check import is_status_locked


def test_locked_statuses() -> None:
    assert is_status_locked(PeriodStatus.locked)
    assert is_status_locked(PeriodStatus.paid)
    assert is_status_locked('locked')
    assert is_status_locked('paid')
    assert not is_status_locked(PeriodStatus.open)
    assert not is_status_locked('reopened')
    assert not is_status_locked(None)
