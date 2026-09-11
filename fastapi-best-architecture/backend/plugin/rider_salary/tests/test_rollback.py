import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.service.rollback_service import assert_rollback_confirm


def test_rollback_confirm_required_only_when_paid() -> None:
    assert_rollback_confirm(has_paid=False, confirm_text='')
    assert_rollback_confirm(has_paid=False, confirm_text=None)
    with pytest.raises(errors.RequestError, match='请输入确认文字「确认回退」'):
        assert_rollback_confirm(has_paid=True, confirm_text='')
    with pytest.raises(errors.RequestError, match='请输入确认文字「确认回退」'):
        assert_rollback_confirm(has_paid=True, confirm_text='确认')
    assert_rollback_confirm(has_paid=True, confirm_text='确认回退')
    assert_rollback_confirm(has_paid=True, confirm_text=' 确认回退 ')
