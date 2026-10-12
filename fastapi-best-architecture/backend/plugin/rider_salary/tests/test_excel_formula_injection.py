"""Excel 导出防公式注入（P3-07 / C-E11）。"""

import io

from datetime import datetime, timezone

import pytest

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet

from backend.plugin.rider_salary.utils.excel import write_workbook


def _active_sheet(content: bytes) -> Worksheet:
    workbook = load_workbook(io.BytesIO(content))
    worksheet = workbook.active
    assert worksheet is not None
    return worksheet


def _sheet_cell(content: bytes, coordinate: str) -> Cell:
    return _active_sheet(content)[coordinate]


def test_e11_advance_reason_cell_type_is_string() -> None:
    """以 = 开头的预支原因导出后单元格类型为 s，不再是公式。"""
    reason = '=HYPERLINK("http://evil.example","点我")'
    content = write_workbook([('预支明细', ['工号', '原因'], [['D5A001', reason]])])
    cell = _sheet_cell(content, 'B2')
    assert cell.data_type == 's'
    assert cell.value == f"'{reason}"


@pytest.mark.parametrize(
    'raw',
    [
        '=1+1',
        "=cmd|'/c calc'!A0",
        '+1+2',
        '-2+3',
        '@SUM(A1:A2)',
        '=',
    ],
)
def test_formula_prefixes_are_quoted(raw: str) -> None:
    content = write_workbook([('明细', ['内容'], [[raw]])])
    cell = _sheet_cell(content, 'A2')
    assert cell.data_type == 's'
    assert cell.value == f"'{raw}"


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('-5.00', '-5.00'),
        ('+3', '+3'),
        ('-1+1', "'-1+1"),
        ('=1+1', "'=1+1"),
        ('@SUM(A1)', "'@SUM(A1)"),
    ],
)
def test_plain_numbers_stay_unquoted_formulas_are_quoted(raw: str, expected: str) -> None:
    """纯数字文本不加撇号，仍以字符串写入；公式文本照旧加前缀。"""
    content = write_workbook([('明细', ['金额'], [[raw]])])
    cell = _sheet_cell(content, 'A2')
    assert cell.data_type == 's'
    assert cell.value == expected


def test_control_chars_cannot_hide_a_formula() -> None:
    content = write_workbook([
        (
            '明细',
            ['内容'],
            [['\t=1+1'], ['\r+2+2'], ['\x00=3+3'], ['备注\x01说明\x1f'], ['第一行\n第二行']],
        )
    ])
    worksheet = _active_sheet(content)
    assert worksheet['A2'].data_type == 's'
    assert worksheet['A2'].value == "'=1+1"
    assert worksheet['A3'].data_type == 's'
    assert worksheet['A3'].value == "'+2+2"
    assert worksheet['A4'].data_type == 's'
    assert worksheet['A4'].value == "'=3+3"
    assert worksheet['A5'].data_type == 's'
    assert worksheet['A5'].value == '备注说明'
    assert worksheet['A6'].data_type == 's'
    assert worksheet['A6'].value == '第一行\n第二行'


def test_plain_text_numbers_and_datetimes_stay_intact() -> None:
    moment = datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc)
    content = write_workbook([
        ('明细', ['文本', '整数', '负数', '小数', '时间'], [['正常原因', 10, -100, -1.25, moment]]),
    ])
    worksheet = _active_sheet(content)
    assert worksheet['A1'].value == '文本'
    assert worksheet['A1'].data_type == 's'
    assert worksheet['A2'].value == '正常原因'
    assert worksheet['A2'].data_type == 's'
    assert worksheet['B2'].value == 10
    assert worksheet['B2'].data_type == 'n'
    assert worksheet['C2'].value == -100
    assert worksheet['C2'].data_type == 'n'
    decimal_cell = worksheet['D2'].value
    assert isinstance(decimal_cell, float)
    assert decimal_cell < 0
    assert abs(decimal_cell + 1.25) < 1e-9
    assert worksheet['D2'].data_type == 'n'
    written = worksheet['E2'].value
    assert isinstance(written, datetime)
    assert written.tzinfo is None
    assert (written.year, written.month, written.day, written.hour, written.minute) == (2026, 9, 1, 8, 30)
