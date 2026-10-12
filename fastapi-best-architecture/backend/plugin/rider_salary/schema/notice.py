from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import NoticeStatus
from backend.plugin.rider_salary.schema.limits import LEN_NOTICE_CONTENT, LEN_NOTICE_TITLE, zh_str


class NoticeSchemaBase(SchemaBase):
    """站点公告基础模型"""

    title: str = Field(description='标题')
    content: str = Field(description='内容')
    site_id: int | None = Field(None, description='站点 ID（空表示全部站点）')


class CreateNoticeParam(NoticeSchemaBase):
    """创建站点公告参数"""

    title: Annotated[str, zh_str('标题', LEN_NOTICE_TITLE, min_length=1)] = Field(
        min_length=1, max_length=LEN_NOTICE_TITLE, description='标题'
    )
    content: Annotated[str, zh_str('内容', LEN_NOTICE_CONTENT, min_length=1)] = Field(
        min_length=1, max_length=LEN_NOTICE_CONTENT, description='内容'
    )
    is_top: bool = Field(False, description='是否置顶')


class UpdateNoticeParam(SchemaBase):
    """更新站点公告参数"""

    title: Annotated[str | None, zh_str('标题', LEN_NOTICE_TITLE, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_NOTICE_TITLE, description='标题'
    )
    content: Annotated[str | None, zh_str('内容', LEN_NOTICE_CONTENT, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_NOTICE_CONTENT, description='内容'
    )
    site_id: int | None = Field(None, description='站点 ID')
    is_top: bool | None = Field(None, description='是否置顶')


class GetNoticeDetail(NoticeSchemaBase):
    """站点公告详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='公告 ID')
    publisher_id: int = Field(description='发布人 ID')
    publish_time: datetime | None = Field(None, description='发布时间')
    status: str = Field(description='状态')
    is_top: bool = Field(False, description='是否置顶')
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
