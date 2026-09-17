from types import SimpleNamespace

from backend.plugin.rider_salary.utils.audit import _operator_name, resolve_operator_name


def test_operator_prefers_real_nickname() -> None:
    req = SimpleNamespace(user=SimpleNamespace(nickname='李站长', username='owner1', id=2))
    assert resolve_operator_name(req) == '李站长'
    assert _operator_name(req) == '李站长'


def test_operator_falls_back_to_username() -> None:
    req = SimpleNamespace(user=SimpleNamespace(nickname=None, username='admin', id=1))
    assert resolve_operator_name(req) == 'admin'


def test_operator_skips_fba_placeholder_nickname() -> None:
    req = SimpleNamespace(user=SimpleNamespace(nickname='用户88888', username='admin', id=1))
    assert resolve_operator_name(req) == 'admin'


def test_operator_reads_dict_user() -> None:
    req = SimpleNamespace(user={'nickname': '', 'username': 'site_owner_d2', 'id': 9})
    assert resolve_operator_name(req) == 'site_owner_d2'


def test_operator_unknown_when_missing() -> None:
    req = SimpleNamespace(user=None)
    assert resolve_operator_name(req) == '未知'
