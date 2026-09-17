import { assertHas, injectAndOpen, loginAs, sidebarText } from '../rbac-helpers.mjs';

export const name = 'rbac-sidebar-superuser';

export async function run({ page, helpers, config }) {
  const admin = await loginAs(config.username, config.password);
  await injectAndOpen(page, admin.access_token, admin.user?.uuid ?? null, '/rider-salary/dashboard');
  const text = await sidebarText(page);
  assertHas(text, ['骑手薪资', '站点管理', '薪资方案'], '超管');
  helpers.assertNoPaymentTaxCopy(text);
  await helpers.shot(page, 'rbac-sidebar-superuser');
}
