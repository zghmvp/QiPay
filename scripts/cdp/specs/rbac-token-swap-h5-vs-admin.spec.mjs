import { RBAC, api, injectAndOpen, isDenied, loginAs, sidebarText } from '../rbac-helpers.mjs';

export const name = 'rbac-token-swap-h5-vs-admin';

export async function run({ page, helpers, config }) {
  const rd = await loginAs(RBAC.riderUser, RBAC.riderPass);
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  await injectAndOpen(page, rd.access_token, rd.user?.uuid ?? null, '/analytics');
  const text = await sidebarText(page);
  if (text.includes('订单明细') || text.includes('结算周期')) {
    throw new Error('骑手 token 贴进管理端后仍见业务菜单');
  }
  const orders = await api(rd.access_token, 'GET', '/api/v1/rider-salary/orders?page=1&size=5');
  if (!isDenied(orders)) throw new Error(`骑手 token 打 /orders 未 403：${orders.status}`);
  const me = await api(ow.access_token, 'GET', '/api/v1/rider-salary/me/profile');
  if (!isDenied(me)) throw new Error('负责人 token 打 /me 未 403');
  await page.goto(`${config.h5Url}/home`, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
  await helpers.shot(page, 'rbac-token-swap-h5-vs-admin');
}
