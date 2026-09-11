from datetime import datetime

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import NoticeStatus


class NoticeSchemaBase(SchemaBase):
    """站点公告基础模型"""

    title: str = Field(description='标题')
    content: str = Field(description='内容')
    site_id: int | None = Field(None, description='站点 ID（空表示全部站点）')


class CreateNoticeParam(NoticeSchemaBase):
    """创建站点公告参数"""


class UpdateNoticeParam(SchemaBase):
    """更新站点公告参数"""

    title: str | None = Field(None, description='标题')
    content: str | None = Field(None, description='内容')
    site_id: int | None = Field(None, description='站点 ID')


class GetNoticeDetail(NoticeSchemaBase):
    """站点公告详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='公告 ID')
    publisher_id: int = Field(description='发布人 ID')
    publish_time: datetime | None = Field(None, description='发布时间')
    status: str = Field(description='状态')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文"""
        try:
            return NoticeStatus(self.status).label
        except ValueError:
            return str(self.status)
