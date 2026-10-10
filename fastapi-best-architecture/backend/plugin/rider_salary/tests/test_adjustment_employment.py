"""奖惩是否可录按业务日期判断，不因当前已离职就一律拒绝。"""

from datetime import date

from backend.plugin.rider_salary.enums import RiderStatus
from backend.plugin.rider_salary.service.adjustment_service import adjustment_employment_error


def test_on_job_is_allowed() -> None:
    assert adjustment_employment_error(RiderStatus.on_job, None, date(2026, 10, 16)) is None


def test_resigned_on_or_before_leave_date_is_allowed() -> None:
    leave = date(2026, 10, 15)
    assert adjustment_employment_error(RiderStatus.resigned, leave, leave) is None
    assert adjustment_employment_error('resigned', leave, date(2026, 10, 1)) is None


def test_resigned_after_leave_date_is_rejected() -> None:
    message = adjustment_employment_error(RiderStatus.resigned, date(2026, 10, 15), date(2026, 10, 16))
    assert message is not None
    assert '2026-10-15' in message
    assert '晚于离职日' in message


def test_resigned_without_leave_date_is_rejected() -> None:
    message = adjustment_employment_error(RiderStatus.resigned, None, date(2026, 10, 15))
    assert message == '骑手不在职，无法录入奖惩'
