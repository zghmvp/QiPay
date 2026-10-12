from pathlib import Path

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.service.rider_service import _issue_password
from backend.plugin.rider_salary.utils.initial_password import generate_initial_password
from backend.plugin.rider_salary.utils.password_gate import (
    MUST_CHANGE_PASSWORD_CODE,
    MUST_CHANGE_PASSWORD_ERROR,
    MUST_CHANGE_PASSWORD_MSG,
    raise_if_must_change_password,
)

_PLUGIN = Path(__file__).resolve().parents[1]
_WORKSPACE = _PLUGIN.parents[3]
_DEMO_PASSWORD = 'Rider@' + '123456'
_SOURCE_ROOTS = (
    _PLUGIN,
    _WORKSPACE / 'fastapi-best-architecture-ui/apps/web-antdv-next/src/plugins/rider-salary',
    _WORKSPACE / 'rider-h5/src',
)


def test_generated_password_has_letter_digit_and_symbol() -> None:
    seen: set[str] = set()
    for _ in range(8):
        password = generate_initial_password()
        seen.add(password)
        assert 8 <= len(password) <= 32
        assert any(char.isalpha() for char in password)
        assert any(char.isdigit() for char in password)
        assert any(not char.isalnum() for char in password)
        assert password != _DEMO_PASSWORD
    assert len(seen) > 1


def test_issue_password_reveals_only_generated_value() -> None:
    supplied, revealed = _issue_password('  Supplied#1a  ')
    assert supplied == 'Supplied#1a'
    assert revealed is None
    generated, shown = _issue_password('   ')
    assert shown == generated
    assert generated != _DEMO_PASSWORD


def test_password_gate_blocks_me_except_change() -> None:
    rider = type('Rider', (), {'must_change_password': True})()
    with pytest.raises(errors.RequestError) as caught:
        raise_if_must_change_password('/api/v1/rider-salary/me/payroll-estimate', 'GET', rider)
    assert caught.value.code == MUST_CHANGE_PASSWORD_CODE
    assert caught.value.msg == MUST_CHANGE_PASSWORD_MSG
    assert caught.value.data == {'error_code': MUST_CHANGE_PASSWORD_ERROR}
    raise_if_must_change_password('/api/v1/rider-salary/me/password', 'PUT', rider)
    clear = type('Rider', (), {'must_change_password': False})()
    raise_if_must_change_password('/api/v1/rider-salary/me/profile', 'GET', clear)


def test_application_source_has_no_demo_password() -> None:
    hits: list[str] = []
    for root in _SOURCE_ROOTS:
        assert root.is_dir(), root
        for path in root.rglob('*'):
            if not path.is_file() or 'tests' in path.parts:
                continue
            if path.suffix not in {'.py', '.vue', '.ts', '.sql'}:
                continue
            if _DEMO_PASSWORD in path.read_text(encoding='utf-8'):
                hits.append(path.relative_to(_WORKSPACE).as_posix())
    assert hits == []
