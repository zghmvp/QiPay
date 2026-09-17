import { RBAC, api, injectAndOpen, isDenied, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-token-swap-h5-vs-admin';

function collectTitles(nodes, acc = []) {
  for (const n of nodes || []) {
    const title = n?.meta?.title || n?.title || n?.name;
    if (title) acc.push(String(title));
    collectTitles(n?.children, acc);
  }
  return acc;
}

export async function run({ page, helpers, config }) {
  const rd = await loginAs(RBAC.riderUser, RBAC.riderPass);
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const menus = await api(rd.access_token, 'GET', '/api/v1/sys/menus/sidebar');
  const titles = collectTitles(menus.json?.data || []);
  if (titles.includes('订单明细') || titles.includes('结算周期') || titles.includes('骑手薪资')) {
    throw new Error(`骑手 token sidebar API 仍见业务菜单：${titles.filter((t) => /订单|结算|骑手薪资/.test(t)).join('、')}`);
  }
  await injectAndOpen(page, rd.access_token, rd.session_uuid || rd.user?.uuid || null, '/analytics');
  const aside = await page.evaluate(() => document.querySelector('aside')?.textContent || '');
  if (aside.includes('订单明细') || aside.includes('结算周期')) {
    throw new Error('骑手 token 贴进管理端后 aside 仍见业务菜单');
  }
  const orders = await api(rd.access_token, 'GET', '/api/v1/rider-salary/orders?page=1&size=5');
  if (!isDenied(orders)) throw new Error(`骑手 token 打 /orders 未 403：${orders.status}`);
  const me = await api(ow.access_token, 'GET', '/api/v1/rider-salary/me/profile');
  if (!isDenied(me)) throw new Error('负责人 token 打 /me 未 403');
  await page.goto(`${config.h5Url}/home`, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
  await helpers.shot(page, 'rbac-token-swap-h5-vs-admin', { fullPage: false, optional: true });
}
