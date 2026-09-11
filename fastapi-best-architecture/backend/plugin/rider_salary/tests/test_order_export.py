from backend.plugin.rider_salary.service.order_service import ORDER_EXPORT_HEADERS
from backend.plugin.rider_salary.utils.excel import read_rows, write_workbook


def test_order_export_headers_chinese() -> None:
    content = write_workbook([('订单明细', ORDER_EXPORT_HEADERS, [['CY01', '测试站', 'RS001']])])
    assert content[:2] == b'PK'
    # HEADER_MAP 只覆盖导入列；导出多出站点名称等列，这里只校验工作簿可写
    assert '站点编码' in ORDER_EXPORT_HEADERS
    assert '骑手工号' in ORDER_EXPORT_HEADERS
    assert '是否锁账' in ORDER_EXPORT_HEADERS
    rows = read_rows(
        write_workbook([
            (
                '订单明细',
                [
                    '站点编码',
                    '骑手工号',
                    '订单号',
                    '配送距离(公里)',
                    '商品重量(斤)',
                    '下单时间',
                    '订单状态',
                ],
                [['CY01', 'RS001', 'ORD-1', '1', '2', '2026-09-01 10:00:00', '已完成']],
            )
        ]),
        'export.xlsx',
    )
    assert rows[0]['site_code'] == 'CY01'
