import {
  OWNER_FORBIDDEN,
  OWNER_MENUS,
  RBAC,
  api,
  assertHas,
  assertHasNone,
  isDenied,
  injectAndOpen,
  loginAs,
  sidebarText,
} from '../rbac-helpers.mjs';

export const name = 'rbac-sidebar-site-owner';

export async function run({ page, helpers, config }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  await injectAndOpen(page, ow.access_token, ow.user?.uuid ?? null, '/rider-salary/dashboard');
  const text = await sidebarText(page);
  assertHas(text, OWNER_MENUS, '站点负责人');
  assertHasNone(text, OWNER_FORBIDDEN, '站点负责人');
  const create = await api(ow.access_token, 'POST', '/api/v1/rider-salary/sites', {
    code: 'NOPE',
    name: 'x',
    settle_cycle: 'month',
  });
  if (!isDenied(create)) throw new Error(`负责人 POST /sites 未 403：${create.status} ${create.msg}`);
  await helpers.shot(page, 'rbac-sidebar-site-owner');
}
