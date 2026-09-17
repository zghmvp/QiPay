import { RBAC, api, injectAndOpen, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-site-select-owner';

export async function run({ page, helpers, config }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const sites = await api(ow.access_token, 'GET', '/api/v1/rider-salary/sites/all');
  const rows = sites.json?.data || [];
  if (rows.length !== 1) {
    throw new Error(`SiteSelect 数据源应仅 1 站，实际 ${rows.length}：${rows.map((s) => s.code).join(',')}`);
  }
  if (rows.some((s) => s.code === 'RBACB')) {
    throw new Error('负责人下拉出现站 B');
  }
  await injectAndOpen(page, ow.access_token, ow.user?.uuid ?? null, '/rider-salary/order');
  const body = await page.locator('body').innerText();
  if (body.includes('权限站B')) throw new Error('订单页出现站 B 文案');
  await helpers.shot(page, 'rbac-site-select-owner');
}
