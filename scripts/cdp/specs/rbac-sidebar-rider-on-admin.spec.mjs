import { assertHasNone, injectAndOpen, loginAs, sidebarText } from '../rbac-helpers.mjs';

export const name = 'rbac-sidebar-rider-on-admin';

export async function run({ page, helpers, config }) {
  const rd = await loginAs(config.riderUser, config.riderPass);
  await injectAndOpen(page, rd.access_token, rd.user?.uuid ?? null, '/analytics');
  const text = await sidebarText(page);
  assertHasNone(text, ['骑手管理', '订单明细', '结算周期', '站点管理', '薪资方案'], '骑手登管理端');
  await helpers.shot(page, 'rbac-sidebar-rider-on-admin');
}
