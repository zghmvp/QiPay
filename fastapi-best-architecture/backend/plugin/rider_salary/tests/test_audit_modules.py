"""P6-14：管理端审计模块筛选项与后端 module 字面量一致。"""

import re

from pathlib import Path

_PLUGIN = Path(__file__).resolve().parents[1]
_SERVICE = _PLUGIN / 'service'
_ENUMS = (
    Path(__file__).resolve().parents[5]
    / 'fastapi-best-architecture-ui/apps/web-antdv-next/src/plugins/rider-salary/constants/enums.ts'
)
_MODULE_LITERAL = re.compile(r"""module\s*=\s*(['"])([^'"]+)\1""")


def _backend_modules() -> set[str]:
    found: set[str] = set()
    for path in sorted(_SERVICE.glob('*.py')):
        found.update(match.group(2) for match in _MODULE_LITERAL.finditer(path.read_text(encoding='utf-8')))
    return found


def _frontend_modules() -> set[str]:
    text = _ENUMS.read_text(encoding='utf-8')
    block = re.search(r'export const AUDIT_MODULE_OPTIONS[\s\S]*?\n\];', text)
    assert block, '未找到 AUDIT_MODULE_OPTIONS'
    labels = re.findall(r"label:\s*'([^']+)'", block.group(0))
    values = re.findall(r"value:\s*'([^']+)'", block.group(0))
    assert labels == values
    return set(values)


def test_audit_module_options_match_backend_literals() -> None:
    """筛选项与 service 里的 module='…' 一一对应，包含预支。"""
    backend = _backend_modules()
    frontend = _frontend_modules()
    assert '预支' in backend
    assert backend == frontend, f'仅后端有 {sorted(backend - frontend)}；仅前端有 {sorted(frontend - backend)}'
