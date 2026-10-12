from __future__ import annotations

import contextlib
import csv
import io
import re
import struct
import zipfile
import zlib

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from openpyxl import Workbook
from openpyxl.cell.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from python_calamine import CalamineError, CalamineWorkbook
from sqlalchemy import Select, func, select

from backend.common.exception import errors
from backend.utils.timezone import timezone

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

HEADER_MAP: dict[str, str] = {
    '站点编码': 'site_code',
    '骑手工号': 'job_no',
    '订单号': 'order_no',
    '配送距离(公里)': 'distance_km',
    '商品重量(斤)': 'weight_jin',
    '下单时间': 'order_time',
    '送达时间': 'deliver_time',
    '订单状态': 'status',
    '订单金额': 'amount',
    '备注': 'remark',
}

REQUIRED_HEADERS: tuple[str, ...] = (
    '站点编码',
    '骑手工号',
    '订单号',
    '配送距离(公里)',
    '商品重量(斤)',
    '下单时间',
    '订单状态',
)

TEMPLATE_HEADERS: tuple[str, ...] = (
    '站点编码*',
    '骑手工号*',
    '订单号*',
    '配送距离(公里)*',
    '商品重量(斤)*',
    '下单时间*',
    '送达时间',
    '订单状态*',
    '订单金额',
    '备注',
)

_EXCEL_EXTS = {'.xlsx', '.xls'}
_CSV_EXTS = {'.csv'}
_FLEX_DT_RE = re.compile(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$')
# 公式注入触发符。openpyxl 会把以 = 开头且长度大于 1 的文本写成公式（单元格类型 f）。
_FORMULA_PREFIXES = frozenset('=+-@')
# 纯数字文本（含订单导出的 "-5.00"）不加撇号，避免导出再导入失真。
_PLAIN_NUMBER_RE = re.compile(r'^[+-]?\d+(\.\d+)?$')
# 控制字符：C0（保留换行 \n）、DEL、C1。\t 与 \r 同时是公式触发符，写入前去掉。
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x09\x0b-\x1f\x7f-\x9f]')
# xlsx 是 zip。先拒绝中心目录里声明的解压体积，再按实际输出封顶，避免「声明很小、实际膨胀」。
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_ENTRIES = 512
MAX_COLUMNS = 128
MAX_CELL_CHARS = 4000
# 订单、预支、周期导出和月历共用。超过后拒绝，不转后台作业。
MAX_EXPORT_ROWS = 50_000
EXPORT_ROW_LIMIT_MSG = '导出行数超过 5 万行上限，请缩小筛选范围后重试'
EXPORT_STREAM_YIELD = 500
_XLSX_MAGIC = b'PK'
_XLS_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
_UNZIP_TOO_LARGE = '文件解压后超过大小上限，请拆分后上传'
_INFLATE_CHUNK = 64 * 1024


class ExcelReadError(Exception):
    """Excel / CSV 读取错误"""

    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__(msg)


def normalize_header(name: object) -> str:
    """去掉星号与空白，全角括号转半角。"""
    text = '' if name is None else str(name).strip()
    text = text.replace('*', '').replace('＊', '')
    text = text.replace('（', '(').replace('）', ')')
    return text.replace(' ', '').replace('\u3000', '')


def parse_cell_datetime(value: object) -> datetime:
    """
    将单元格值解析为 FBA 时区感知 datetime

    :param value: 字符串、datetime、date 或 Excel 序列
    :return:
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError('时间为空')
    if isinstance(value, datetime):
        return _ensure_tz(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.tz_info)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = datetime(1899, 12, 30, tzinfo=timezone.tz_info)
        return epoch + timedelta(days=float(value))
    text = str(value).strip()
    matched = _FLEX_DT_RE.match(text)
    if matched:
        year, month, day, hour, minute, second = matched.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=timezone.tz_info,
        )
    raise ValueError(f'无法解析时间：{text}')


def read_rows(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """
    读取 xlsx/xls/csv，将中文表头映射为字段名

    :param file_bytes: 文件内容
    :param filename: 原始文件名（用于识别扩展名）
    :return:
    """
    ext = _file_ext(filename)
    if ext in _CSV_EXTS:
        raw_rows = _read_csv(file_bytes)
    elif ext in _EXCEL_EXTS:
        _assert_excel_container(file_bytes, ext)
        raw_rows = _read_excel(file_bytes)
    else:
        raise ExcelReadError('仅支持 Excel 或 CSV 文件')
    _assert_grid_limits(raw_rows)
    return _rows_to_dicts(raw_rows)


def assert_export_row_limit(row_count: int) -> None:
    """
    行数超过上限时拒绝，提示缩小筛选范围

    :param row_count: 将要读取或写出的数据行数
    :return:
    """
    if row_count > MAX_EXPORT_ROWS:
        raise errors.RequestError(msg=EXPORT_ROW_LIMIT_MSG)


def write_workbook(sheets: Sequence[tuple[str, Sequence[str], Iterable[Sequence[object]]]]) -> bytes:
    """
    用 openpyxl write_only 逐行写成 xlsx。数据行按迭代器消费，不先收成列表。

    :param sheets: (表名, 表头, 数据行迭代器)
    :return: 文件字节
    """
    book = StreamingWorkbook()
    for title, headers, rows in sheets:
        worksheet = book.add_sheet(title, headers)
        for row in rows:
            book.append(worksheet, row)
    return book.to_bytes()


class StreamingWorkbook:
    """write_only 工作簿。每写一行就交给 openpyxl，不保留已写数据行。"""

    def __init__(self) -> None:
        self._workbook = Workbook(write_only=True)
        self._sheets: list[Any] = []
        self._header_len: dict[int, int] = {}
        self._counts: dict[int, int] = {}
        self._written = 0

    def add_sheet(self, title: str, headers: Sequence[str]) -> Any:
        """
        增加工作表并写表头。列宽和冻结窗格必须在第一行之前设置。

        :param title: 表名
        :param headers: 表头
        :return: write_only 工作表
        """
        worksheet = self._workbook.create_sheet(title=(title or 'Sheet')[:31])
        _prepare_write_only_sheet(worksheet, headers)
        self._sheets.append(worksheet)
        self._header_len[id(worksheet)] = len(headers)
        self._counts[id(worksheet)] = 0
        return worksheet

    def append(self, worksheet: Any, row: Sequence[object]) -> None:
        """
        追加一行。累计超过上限时拒绝，不再继续读取后续行。

        :param worksheet: add_sheet 返回的工作表
        :param row: 数据行
        :return:
        """
        if self._written >= MAX_EXPORT_ROWS:
            self.discard()
            raise errors.RequestError(msg=EXPORT_ROW_LIMIT_MSG)
        worksheet.append(_plain_cells(row))
        self._written += 1
        self._counts[id(worksheet)] += 1

    def discard(self) -> None:
        """关闭尚未保存的工作表，避免 write_only 生成器在回收时写入已关闭文件。"""
        for worksheet in self._sheets:
            if worksheet.closed:
                continue
            worksheet.close()

    def to_bytes(self) -> bytes:
        """写入筛选区域并保存为 xlsx 字节。"""
        for worksheet in self._sheets:
            columns = max(self._header_len.get(id(worksheet), 1), 1)
            last_row = self._counts.get(id(worksheet), 0) + 1
            worksheet.auto_filter.ref = f'A1:{get_column_letter(columns)}{last_row}'
        buffer = io.BytesIO()
        self._workbook.save(buffer)
        return buffer.getvalue()


async def count_statement(db: AsyncSession, stmt: Select[Any]) -> int:
    """
    对已有 SELECT 计数，不取出数据行

    :param db: 数据库会话
    :param stmt: 查询
    :return: 行数
    """
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return int(total or 0)


async def stream_scalars(
    db: AsyncSession,
    stmt: Select[Any],
    *,
    yield_per: int = EXPORT_STREAM_YIELD,
) -> AsyncIterator[Any]:
    """按窗口流式返回 ORM 对象，调用方不要再收成列表。"""
    result = await db.stream(stmt.execution_options(yield_per=yield_per))
    async for item in result.scalars():
        yield item


async def stream_rows(
    db: AsyncSession,
    stmt: Select[Any],
    *,
    yield_per: int = EXPORT_STREAM_YIELD,
) -> AsyncIterator[Any]:
    """按窗口流式返回行，调用方不要再收成列表。"""
    result = await db.stream(stmt.execution_options(yield_per=yield_per))
    async for row in result:
        yield row


async def append_streamed_rows(
    book: StreamingWorkbook,
    worksheet: Any,
    rows: AsyncIterator[Sequence[object]],
) -> None:
    """逐行写入工作表，不把异步迭代器收成列表。"""
    async for row in rows:
        book.append(worksheet, row)


def _prepare_write_only_sheet(worksheet: Any, headers: Sequence[str]) -> None:
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='305496')
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for col, header in enumerate(headers, start=1):
        width = min(48, max(12, len(str(header)) + 4))
        worksheet.column_dimensions[get_column_letter(col)].width = width
    worksheet.freeze_panes = 'A2'
    worksheet.append(_header_cells(worksheet, headers, header_font, header_fill, header_align))


def _header_cells(
    worksheet: Any,
    headers: Sequence[str],
    header_font: Font,
    header_fill: PatternFill,
    header_align: Alignment,
) -> list[WriteOnlyCell]:
    cells: list[WriteOnlyCell] = []
    for header in headers:
        cell = WriteOnlyCell(worksheet, value=str(header))
        cell.data_type = 's'
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cells.append(cell)
    return cells


def _plain_cells(row: Sequence[object]) -> list[object]:
    return [_excel_cell_value(value) for value in row]


def _ensure_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.tz_info)
    return timezone.from_datetime(value)


def _file_ext(filename: str) -> str:
    name = (filename or '').strip().rsplit('/', maxsplit=1)[-1]
    name = name.rsplit('\\', maxsplit=1)[-1]
    if '.' not in name:
        return ''
    return '.' + name.rsplit('.', maxsplit=1)[-1].lower()


def _assert_excel_container(file_bytes: bytes, ext: str) -> None:
    """校验 Excel 魔数；xlsx 额外限制压缩包条目数和实际解压体积。"""
    if ext == '.xlsx':
        if not file_bytes.startswith(_XLSX_MAGIC):
            raise ExcelReadError('文件内容与扩展名不符，请上传真实的 xlsx 文件')
        _assert_xlsx_limits(file_bytes)
        return
    if not file_bytes.startswith(_XLS_MAGIC):
        raise ExcelReadError('文件内容与扩展名不符，请上传真实的 xls 文件')


def _assert_xlsx_limits(file_bytes: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ExcelReadError('文件内容与扩展名不符，请上传真实的 xlsx 文件') from exc
    try:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ExcelReadError('压缩包内文件数量超过上限，请检查后重新上传')
        declared = 0
        for info in infos:
            if info.flag_bits & 0x1:
                raise ExcelReadError('不支持加密的 Excel 文件')
            if info.file_size < 0 or info.file_size > MAX_UNCOMPRESSED_BYTES:
                raise ExcelReadError(_UNZIP_TOO_LARGE)
            declared += info.file_size
            if declared > MAX_UNCOMPRESSED_BYTES:
                raise ExcelReadError(_UNZIP_TOO_LARGE)
        produced = 0
        for info in infos:
            produced += _member_output_size(file_bytes, info, MAX_UNCOMPRESSED_BYTES - produced)
            if produced > MAX_UNCOMPRESSED_BYTES:
                raise ExcelReadError(_UNZIP_TOO_LARGE)
    finally:
        archive.close()


def _member_output_size(file_bytes: bytes, info: zipfile.ZipInfo, budget: int) -> int:
    if info.compress_size == 0 and info.file_size == 0:
        return 0
    payload = _member_payload(file_bytes, info)
    if info.compress_type == zipfile.ZIP_STORED:
        size = len(payload)
        if size > budget:
            raise ExcelReadError(_UNZIP_TOO_LARGE)
        return size
    if info.compress_type != zipfile.ZIP_DEFLATED:
        raise ExcelReadError('文件压缩方式不受支持，请另存为 xlsx 后重新上传')
    return _deflated_size(payload, budget)


def _member_payload(file_bytes: bytes, info: zipfile.ZipInfo) -> bytes:
    offset = info.header_offset
    if offset < 0 or offset + 30 > len(file_bytes) or file_bytes[offset : offset + 4] != b'PK\x03\x04':
        raise ExcelReadError('文件内容与扩展名不符，请上传真实的 xlsx 文件')
    name_len, extra_len = struct.unpack_from('<HH', file_bytes, offset + 26)
    start = offset + 30 + name_len + extra_len
    end = start + info.compress_size
    if start < offset or end < start or end > len(file_bytes):
        raise ExcelReadError('文件内容与扩展名不符，请上传真实的 xlsx 文件')
    return file_bytes[start:end]


def _deflated_size(payload: bytes, budget: int) -> int:
    """按原始 deflate 流统计输出字节，超过预算立即停止，不保留全部输出。"""
    if budget < 0:
        raise ExcelReadError(_UNZIP_TOO_LARGE)
    decoder = zlib.decompressobj(-15)
    produced = 0
    pending = payload
    try:
        while True:
            out = decoder.decompress(pending, _INFLATE_CHUNK)
            nxt = decoder.unconsumed_tail
            produced += len(out)
            if produced > budget:
                raise ExcelReadError(_UNZIP_TOO_LARGE)
            if decoder.eof:
                extra = decoder.flush()
                produced += len(extra)
                if produced > budget:
                    raise ExcelReadError(_UNZIP_TOO_LARGE)
                return produced
            if not nxt or (nxt == pending and not out):
                raise ExcelReadError('文件内容与扩展名不符，请上传真实的 xlsx 文件')
            pending = nxt
    except zlib.error as exc:
        raise ExcelReadError('文件内容与扩展名不符，请上传真实的 xlsx 文件') from exc


def _assert_grid_limits(raw_rows: list[list[Any]]) -> None:
    for row in raw_rows:
        if _used_width(row) > MAX_COLUMNS:
            raise ExcelReadError(f'列数超过上限 {MAX_COLUMNS}，请删除多余列后重新上传')
        for cell in row:
            if isinstance(cell, str) and len(cell) > MAX_CELL_CHARS:
                raise ExcelReadError(f'单元格内容超过长度上限 {MAX_CELL_CHARS}，请缩短后重新上传')


def _used_width(row: list[Any]) -> int:
    width = len(row)
    while width > 0 and _is_blank_cell(row[width - 1]):
        width -= 1
    return width


def _is_blank_cell(cell: object) -> bool:
    if cell is None:
        return True
    return bool(isinstance(cell, str) and not cell.strip())


def _read_excel(file_bytes: bytes) -> list[list[Any]]:
    try:
        workbook = CalamineWorkbook.from_filelike(io.BytesIO(file_bytes))
        sheet = workbook.get_sheet_by_index(0)
        rows = sheet.to_python(skip_empty_area=False)
        workbook.close()
    except (CalamineError, OSError, ValueError, IndexError) as exc:
        raise ExcelReadError('文件解析失败，请检查文件格式') from exc
    return rows


def _read_csv(file_bytes: bytes) -> list[list[Any]]:
    text = _decode_csv(file_bytes)
    reader = csv.reader(io.StringIO(text))
    return [list(row) for row in reader]


def _decode_csv(file_bytes: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'gbk'):
        with contextlib.suppress(UnicodeDecodeError):
            return file_bytes.decode(encoding)
    raise ExcelReadError('文件编码无法识别，请使用 UTF-8 或 GBK')


def _rows_to_dicts(raw_rows: list[list[Any]]) -> list[dict[str, Any]]:
    header_idx = None
    for idx, row in enumerate(raw_rows):
        if not _is_empty_row(row):
            header_idx = idx
            break
    if header_idx is None:
        raise ExcelReadError('文件为空，请按模板填写后重新上传')
    header_row = raw_rows[header_idx]
    field_by_col, missing = _map_headers(header_row)
    if missing:
        raise ExcelReadError(f'模板表头不符，缺少列：{"、".join(missing)}')
    result: list[dict[str, Any]] = []
    for offset, row in enumerate(raw_rows[header_idx + 1 :], start=header_idx + 2):
        if _is_empty_row(row):
            continue
        item: dict[str, Any] = {'_row': offset}
        for col, field in field_by_col.items():
            item[field] = row[col] if col < len(row) else None
        result.append(item)
    if not result:
        raise ExcelReadError('文件为空，请按模板填写后重新上传')
    return result


def _map_headers(header_row: list[Any]) -> tuple[dict[int, str], list[str]]:
    field_by_col: dict[int, str] = {}
    seen: set[str] = set()
    for col, cell in enumerate(header_row):
        normalized = normalize_header(cell)
        if not normalized:
            continue
        field = HEADER_MAP.get(normalized)
        if field is None:
            continue
        field_by_col[col] = field
        seen.add(normalized)
    missing = [name for name in REQUIRED_HEADERS if name not in seen]
    return field_by_col, missing


def _is_empty_row(row: list[Any]) -> bool:
    for cell in row:
        if cell is None:
            continue
        if isinstance(cell, str) and not cell.strip():
            continue
        return False
    return True


def _excel_cell_value(value: object) -> object:
    """文本先去掉公式触发符。openpyxl 只把以 = 开头的字符串当成公式。"""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        return _neutralize_excel_text(value)
    return value


def _neutralize_excel_text(value: str) -> str:
    """去掉控制字符；以 = + - @ 开头且不是纯数字的文本加前缀 '。"""
    cleaned = _CONTROL_CHARS_RE.sub('', value)
    if cleaned[:1] in _FORMULA_PREFIXES and _PLAIN_NUMBER_RE.match(cleaned) is None:
        return f"'{cleaned}"
    return cleaned
