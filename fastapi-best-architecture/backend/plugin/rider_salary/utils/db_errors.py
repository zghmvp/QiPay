"""把数据库完整性错误转成中文 409 / 422。不改框架的全局异常处理。"""

from sqlalchemy.exc import IntegrityError

from backend.common.exception import errors

# 唯一约束 → 409。草稿薪资单唯一冲突由 calc_service 单独处理，这里不覆盖那条路径。
RIDER_USER_BOUND_MSG = '该账号已绑定其他骑手'
SITE_OWNER_EXISTS_MSG = '该站点已有负责人'

_UNIQUE_MSG = {
    'uk_rs_site_code_deleted': '站点编码已存在',
    'uk_rs_subject_code_deleted': '科目编码已存在',
    'uk_rs_plan_code_deleted': '方案编码已存在',
    'uk_rs_plan_version_plan_no_deleted': '方案版本号已存在',
    'uk_rs_order_order_no_deleted': '订单号已存在',
    'uk_rs_rider_job_no_deleted': '工号已存在',
    'uq_rs_rider_one_user': RIDER_USER_BOUND_MSG,
    'uk_rs_day_flag_site_biz_date_deleted': '该日期的日标记已存在',
    'uk_rs_site_manager_site_user_deleted': '该用户已是站点负责人',
    'uq_rs_site_manager_one_owner': SITE_OWNER_EXISTS_MSG,
    'uk_rs_settle_period_site_rider_start_deleted': '该结算周期已存在',
}

_SQLSTATE_UNIQUE = '23505'
_SQLSTATE_FK = '23503'
_SQLSTATE_NOT_NULL = '23502'
_SQLSTATE_CHECK = '23514'
_SQLSTATE_TOO_LONG = '22001'


def _orig_text(exc: IntegrityError) -> str:
    orig = getattr(exc, 'orig', None)
    return '' if orig is None else str(orig)


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, 'orig', None)
    if orig is not None:
        name = getattr(orig, 'constraint_name', None)
        if name:
            return str(name)
        diag = getattr(orig, 'diag', None)
        if diag is not None and getattr(diag, 'constraint_name', None):
            return str(diag.constraint_name)
    text = _orig_text(exc)
    for key in _UNIQUE_MSG:
        if key in text:
            return key
    return None


def _sqlstate(exc: IntegrityError) -> str | None:
    orig = getattr(exc, 'orig', None)
    if orig is None:
        return None
    state = getattr(orig, 'sqlstate', None) or getattr(orig, 'pgcode', None)
    return str(state) if state else None


def client_error_from_integrity(exc: IntegrityError) -> errors.BaseExceptionError:
    """
    唯一冲突返回 409，外键、非空、检查和超长返回 422。

    :param exc: SQLAlchemy 完整性错误
    :return: 可直接 raise 的中文业务异常
    """
    name = _constraint_name(exc)
    state = _sqlstate(exc)
    text = _orig_text(exc).lower()
    unique = state == _SQLSTATE_UNIQUE or 'unique' in text or 'duplicate' in text
    if unique:
        return errors.ConflictError(msg=_UNIQUE_MSG.get(name or '', '数据已存在，请检查是否重复'))
    if state == _SQLSTATE_FK or 'foreign key' in text:
        return errors.RequestError(code=422, msg='关联的数据不存在或已被删除')
    if state == _SQLSTATE_NOT_NULL or 'not-null' in text or 'not null' in text:
        return errors.RequestError(code=422, msg='缺少必填字段')
    if state in {_SQLSTATE_CHECK, _SQLSTATE_TOO_LONG} or 'too long' in text or 'check constraint' in text:
        return errors.RequestError(code=422, msg='提交的数据不符合字段约束')
    return errors.RequestError(code=422, msg='数据保存失败，请检查是否重复或超出限制')
