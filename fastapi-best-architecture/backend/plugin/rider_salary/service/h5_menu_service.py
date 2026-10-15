from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.h5_menu import h5_menu_dao
from backend.plugin.rider_salary.crud.site import site_dao
from backend.plugin.rider_salary.model.h5_menu import GLOBAL_H5_MENU_SITE_ID, RiderSalaryH5Menu
from backend.plugin.rider_salary.schema.h5_menu import GetH5Menu, GetMeH5Menu, SaveH5MenuParam
from backend.plugin.rider_salary.service.audit_service import audit_service, is_global_operator
from backend.plugin.rider_salary.service.h5_menu import (
    BOOL_FIELDS,
    H5MenuFlags,
    assert_feature_open,
    flag_values,
    flags_from_values,
    resolve_h5_menu,
)
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids


def _from_row(row: RiderSalaryH5Menu, source: str) -> H5MenuFlags:
    return flags_from_values(source=source, **{name: bool(getattr(row, name)) for name in BOOL_FIELDS})


def _snapshot(row: RiderSalaryH5Menu) -> dict[str, int | bool]:
    data: dict[str, int | bool] = {'site_id': row.site_id}
    for name in BOOL_FIELDS:
        data[name] = bool(getattr(row, name))
    return data


class H5MenuService:
    """骑手端菜单开关的读取、保存和拦截。"""

    async def resolve_for_site(self, db: AsyncSession, site_id: int) -> H5MenuFlags:
        site_row = None
        if site_id != GLOBAL_H5_MENU_SITE_ID:
            site_row = await h5_menu_dao.get_by_site(db, site_id)
        global_row = await h5_menu_dao.get_by_site(db, GLOBAL_H5_MENU_SITE_ID)
        return resolve_h5_menu(
            _from_row(site_row, 'site') if site_row is not None else None,
            _from_row(global_row, 'global') if global_row is not None else None,
        )

    async def assert_open(self, db: AsyncSession, rider: object, feature: str) -> H5MenuFlags:
        flags = await self.resolve_for_site(db, int(getattr(rider, 'site_id')))
        assert_feature_open(flags, feature)
        return flags

    async def for_rider(self, db: AsyncSession, rider: object) -> GetMeH5Menu:
        flags = await self.resolve_for_site(db, int(getattr(rider, 'site_id')))
        return GetMeH5Menu(**flag_values(flags))

    async def get(self, *, db: AsyncSession, request: Request, site_id: int) -> GetH5Menu:
        await self._assert_scope(db, request, site_id)
        flags = await self.resolve_for_site(db, site_id)
        site_name = '全局默认'
        if site_id != GLOBAL_H5_MENU_SITE_ID:
            site = await site_dao.get(db, site_id)
            if site is None:
                raise errors.NotFoundError(msg='站点不存在')
            site_name = site.name
        return GetH5Menu(
            site_id=site_id,
            source=flags.source,  # type: ignore[arg-type]
            site_name=site_name,
            **flag_values(flags),
        )

    async def save(self, *, db: AsyncSession, request: Request, obj: SaveH5MenuParam) -> GetH5Menu:
        await self._assert_scope(db, request, obj.site_id)
        if obj.site_id != GLOBAL_H5_MENU_SITE_ID:
            site = await site_dao.get(db, obj.site_id)
            if site is None:
                raise errors.NotFoundError(msg='站点不存在')
        row = await h5_menu_dao.get_by_site(db, obj.site_id)
        before = _snapshot(row) if row is not None else None
        if row is None:
            row = RiderSalaryH5Menu(site_id=obj.site_id)
            db.add(row)
        for name in BOOL_FIELDS:
            setattr(row, name, getattr(obj, name))
        await db.flush()
        label = '全局默认' if obj.site_id == GLOBAL_H5_MENU_SITE_ID else f'站点 {obj.site_id}'
        await audit_service.record(
            db,
            request,
            module='h5_menu',
            action='保存骑手端菜单',
            target_type='h5_menu',
            target_id=row.id,
            target_label=label,
            before=before,
            after=_snapshot(row),
            description=f'保存{label}骑手端菜单开关',
        )
        return await self.get(db=db, request=request, site_id=obj.site_id)

    async def _assert_scope(self, db: AsyncSession, request: Request, site_id: int) -> None:
        if site_id == GLOBAL_H5_MENU_SITE_ID:
            if not is_global_operator(request):
                raise errors.ForbiddenError(msg='只有薪资管理员可以修改全局骑手端菜单')
            return
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, site_id)


h5_menu_service: H5MenuService = H5MenuService()
