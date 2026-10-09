from backend.common.exception import errors

MUST_CHANGE_PASSWORD_CODE = 423
MUST_CHANGE_PASSWORD_MSG = '请先修改初始密码'
MUST_CHANGE_PASSWORD_ERROR = 'MUST_CHANGE_PASSWORD'
_PASSWORD_PATH_SUFFIX = '/rider-salary/me/password'


def raise_if_must_change_password(path: str, method: str, rider: object) -> None:
    """须改密时拒绝 /me，改密接口本身除外。

    :param path: 请求路径
    :param method: 请求方法
    :param rider: 当前骑手
    :return:
    """
    if not bool(getattr(rider, 'must_change_password', False)):
        return
    normalized = path.rstrip('/')
    if method.upper() == 'PUT' and normalized.endswith(_PASSWORD_PATH_SUFFIX):
        return
    raise errors.RequestError(
        code=MUST_CHANGE_PASSWORD_CODE,
        msg=MUST_CHANGE_PASSWORD_MSG,
        data={'error_code': MUST_CHANGE_PASSWORD_ERROR},
    )
