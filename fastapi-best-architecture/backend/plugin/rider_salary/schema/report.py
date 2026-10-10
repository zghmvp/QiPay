from decimal import Decimal

from pydantic import Field

from backend.common.schema import SchemaBase


class AdvanceLedgerLine(SchemaBase):
    """预支台账明细"""

    advance_id: int = Field(description='预支单 ID')
    rider_id: int = Field(description='骑手 ID')
    site_id: int = Field(description='站点 ID')
    issued: Decimal = Field(description='发放')
    deducted: Decimal = Field(description='抵扣')
    carried: Decimal = Field(description='结转')


class GetAdvanceLedger(SchemaBase):
    """预支台账"""

    issued: Decimal = Field(description='发放合计')
    deducted: Decimal = Field(description='抵扣合计')
    carried: Decimal = Field(description='结转合计')
    gap: Decimal = Field(description='差额，发放减抵扣再减结转')
    balanced: bool = Field(description='发放、抵扣、结转是否对平')
    lines: list[AdvanceLedgerLine] = Field(description='已发放预支明细')


class SiteMonthCostRow(SchemaBase):
    """站点月份成本"""

    site_id: int = Field(description='站点 ID')
    site_code: str = Field(description='站点编码')
    site_name: str = Field(description='站点名称')
    month: str = Field(description='月份，格式 YYYY-MM，取结算周期开始日')
    slip_count: int = Field(description='有效薪资单张数')
    gross: Decimal = Field(description='应发合计')
    net: Decimal = Field(description='实发合计')
    advance_deduction: Decimal = Field(description='预支抵扣合计')


class GetCostSummary(SchemaBase):
    """按站点和月份的成本汇总"""

    month: str | None = Field(None, description='筛选月份，空表示全部月份')
    rows: list[SiteMonthCostRow] = Field(description='站点月份明细')
    slip_count: int = Field(description='有效薪资单张数合计')
    gross: Decimal = Field(description='应发合计')
    net: Decimal = Field(description='实发合计')
    advance_deduction: Decimal = Field(description='预支抵扣合计')
