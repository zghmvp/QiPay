import {
  OWNER_FORBIDDEN,
  OWNER_MENUS,
  assertHas,
  assertHasNone,
  injectAndOpen,
  loginAs,
  sidebarText,
} from '../rbac-helpers.mjs';

export const name = 'rbac-sidebar-deputy';

export async function run({ page, helpers, config }) {
  const dp = await loginAs(config.deputyUser, config.deputyPass);
  await injectAndOpen(page, dp.access_token, dp.session_uuid || dp.user?.uuid || null, '/rider-salary/dashboard');
  const text = await sidebarText(page);
  assertHas(text, OWNER_MENUS, '副负责人');
  assertHasNone(text, OWNER_FORBIDDEN, '副负责人');
  await helpers.shot(page, 'rbac-sidebar-deputy');
}
