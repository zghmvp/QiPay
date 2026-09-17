from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class GetAuditLogDetail(SchemaBase):
    """操作日志详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='日志 ID')
    operator_id: int = Field(description='操作人 ID')
    operator_name: str = Field(description='操作人姓名')
    operate_time: datetime = Field(description='操作时间')
    module: str = Field(description='模块')
    action: str = Field(description='动作')
    target_type: str = Field(description='对象类型')
    target_id: str | None = Field(None, description='对象 ID')
    site_id: int | None = Field(None, description='所属站点；空表示全局目录或无法归属')
    target_label: str = Field(description='对象摘要')
    reason: str | None = Field(None, description='原因')
    before: dict[str, Any] | None = Field(None, description='变更前')
    after: dict[str, Any] | None = Field(None, description='变更后')
    description: str | None = Field(None, description='自然语言描述')
    ip: str | None = Field(None, description='IP')
    trace_id: str | None = Field(None, description='追踪 ID')
    created_time: datetime = Field(description='创建时间')
