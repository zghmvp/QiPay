"""离职骑手 H5 只读宽限期。

Q-05 推荐方案：离职后 90 天内可以登录并查看，超过 90 天拒绝。
验收条文写的是 30 天，未拍板前按推荐的 90 天实现。写操作不在宽限期内放行。
"""

from datetime import date, datetime, timedelta

from backend.common.exception import errors
from backend.plugin.rider_salary.utils.lifecycle import is_resigned
from backend.utils.timezone import timezone

RESIGNED_READ_GRACE_DAYS = 90
NOT_RIDER_MSG = '当前账号不是有效骑手账号'
RESIGNED_EXPIRED_MSG = '离职已超过查阅期限，当前账号不是有效骑手账号'
MSG_RESIGNED_NO_ADVANCE = '离职骑手不能申请预支'
MSG_RESIGNED_NO_CANCEL = '离职骑手不能撤回预支'


def _as_date(value: object) -> date | None:
    """把日期或带时区的时间收成日期。其它类型视为没有日期。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def resigned_read_until(leave_date: object) -> date | None:
    """只读查阅的最后一天，含离职日当天起算的第 90 天。

    :param leave_date: 离职日期
    :return: 截止日期；没有离职日时为空
    """
    leave = _as_date(leave_date)
    if leave is None:
        return None
    return leave + timedelta(days=RESIGNED_READ_GRACE_DAYS)


def rider_can_read(rider: object, today: date | None = None) -> bool:
    """在职可以访问。离职只在查阅截止日当天及之前可以访问。

    :param rider: 骑手
    :param today: 比较用的日期，缺省为当前时区的今天
    :return:
    """
    if not is_resigned(rider):
        return True
    until = resigned_read_until(getattr(rider, 'leave_date', None))
    if until is None:
        return False
    current = today or timezone.now().date()
    return current <= until


def write_action_from_path(path: str) -> str:
    """根据路径区分预支申请和撤回。

    :param path: 请求路径
    :return: cancel 或 advance
    """
    if path.rstrip('/').endswith('/cancel'):
        return 'cancel'
    return 'advance'


def assert_rider_can_write(rider: object, *, action: str = 'advance') -> None:
    """离职骑手不能提交或撤回预支。改密不走这里。

    :param rider: 当前骑手
    :param action: advance 申请，cancel 撤回
    :return:
    """
    if not is_resigned(rider):
        return
    if action == 'cancel':
        raise errors.RequestError(msg=MSG_RESIGNED_NO_CANCEL)
    raise errors.RequestError(msg=MSG_RESIGNED_NO_ADVANCE)
