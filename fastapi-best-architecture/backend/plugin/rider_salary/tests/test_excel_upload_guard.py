"""上传文件魔数、解压体积、列数与单元格长度（P3-10）。"""

import io
import struct
import zipfile

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.service.import_service import build_import_template, load_upload_rows
from backend.plugin.rider_salary.utils.excel import (
    MAX_CELL_CHARS,
    MAX_COLUMNS,
    MAX_UNCOMPRESSED_BYTES,
    MAX_ZIP_ENTRIES,
    REQUIRED_HEADERS,
    write_workbook,
)

_XLS_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


def _zip_members(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _patch_uncompressed(data: bytes, declared: int) -> bytes:
    """改写首个条目的未压缩大小，压缩数据保持不变。"""
    raw = bytearray(data)
    local = raw.find(b'PK\x03\x04')
    central = raw.rfind(b'PK\x01\x02')
    assert local >= 0
    assert central > local
    raw[local + 22 : local + 26] = struct.pack('<I', declared)
    raw[central + 24 : central + 28] = struct.pack('<I', declared)
    return bytes(raw)


def _expect_400(data: bytes, filename: str, match: str) -> None:
    with pytest.raises(errors.RequestError, match=match) as caught:
        load_upload_rows(data, filename)
    assert caught.value.code == 400


def test_text_renamed_to_xlsx_returns_400() -> None:
    _expect_400('站点编码,骑手工号\nCY01,RS001\n'.encode(), '订单.xlsx', '请上传真实的 xlsx 文件')


def test_text_renamed_to_xls_returns_400() -> None:
    _expect_400(b'not an excel workbook', '订单.xls', '请上传真实的 xls 文件')


def test_pk_prefix_that_is_not_a_zip_returns_400() -> None:
    _expect_400(b'PK this is plain text', '订单.xlsx', '请上传真实的 xlsx 文件')


def test_zip_bomb_declared_size_returns_400() -> None:
    """中心目录声明的解压体积超过上限时拒绝，且不展开该条目。"""
    payload = _patch_uncompressed(
        _zip_members({'xl/sharedStrings.xml': b'A' * 64}),
        MAX_UNCOMPRESSED_BYTES + 1,
    )
    assert len(payload) < 4096
    _expect_400(payload, 'bomb.xlsx', '文件解压后超过大小上限')


def test_understated_size_still_rejects_real_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    """声明体积很小、deflate 实际输出超限时仍然拒绝。"""
    monkeypatch.setattr(
        'backend.plugin.rider_salary.utils.excel.MAX_UNCOMPRESSED_BYTES',
        1024,
    )
    payload = _patch_uncompressed(_zip_members({'xl/sharedStrings.xml': b'B' * 4096}), 100)
    _expect_400(payload, 'bomb.xlsx', '文件解压后超过大小上限')


def test_too_many_zip_entries_returns_400() -> None:
    members = {f'xl/part{index}.xml': b'<a/>' for index in range(MAX_ZIP_ENTRIES + 1)}
    _expect_400(_zip_members(members), 'many.xlsx', '压缩包内文件数量超过上限')


def test_too_many_columns_returns_400() -> None:
    headers = [f'列{index}' for index in range(MAX_COLUMNS + 1)]
    content = write_workbook([('明细', headers, [['x'] * len(headers)])])
    _expect_400(content, 'wide.xlsx', f'列数超过上限 {MAX_COLUMNS}')


def test_column_limit_allows_boundary() -> None:
    headers = [f'列{index}' for index in range(MAX_COLUMNS)]
    row = [''] * (MAX_COLUMNS - 1) + ['x']
    content = write_workbook([('明细', headers, [row])])
    with pytest.raises(errors.RequestError, match='模板表头不符') as caught:
        load_upload_rows(content, 'wide.xlsx')
    assert caught.value.code == 400


def test_cell_too_long_returns_400() -> None:
    content = write_workbook([('明细', ['备注'], [['啊' * (MAX_CELL_CHARS + 1)]])])
    _expect_400(content, 'long.xlsx', f'单元格内容超过长度上限 {MAX_CELL_CHARS}')


def test_cell_limit_allows_boundary() -> None:
    headers = [*REQUIRED_HEADERS, '备注']
    row = ['CY01', 'RS001', 'ORD-1', '1', '1', '2026-09-01 10:00:00', '已完成', '啊' * MAX_CELL_CHARS]
    content = write_workbook([('明细', headers, [row])])
    rows = load_upload_rows(content, 'ok.xlsx')
    assert rows[0]['remark'] == '啊' * MAX_CELL_CHARS
    assert rows[0]['order_no'] == 'ORD-1'


def test_csv_cell_too_long_returns_400() -> None:
    text = '备注\n' + ('啊' * (MAX_CELL_CHARS + 1))
    _expect_400(text.encode(), '订单.csv', f'单元格内容超过长度上限 {MAX_CELL_CHARS}')


def test_template_still_readable() -> None:
    rows = load_upload_rows(build_import_template(), '订单导入模板.xlsx')
    assert rows[0]['site_code'] == 'CY01'
    assert rows[0]['order_no'] == 'ORD-DEMO-001'


def test_xls_magic_with_garbage_body_returns_400() -> None:
    _expect_400(_XLS_MAGIC + b'\x00' * 128, '订单.xls', '文件解析失败')
