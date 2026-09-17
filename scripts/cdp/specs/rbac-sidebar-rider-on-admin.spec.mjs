import { api, injectAndOpen, loginAs, sidebarText } from '../rbac-helpers.mjs';

export const name = 'rbac-sidebar-rider-on-admin';

function collectTitles(nodes, acc = []) {
  for (const n of nodes || []) {
    const title = n?.meta?.title || n?.title || n?.name;
    if (title) acc.push(String(title));
    collectTitles(n?.children, acc);
  }
  return acc;
}

export async function run({ page, helpers, config }) {
  const rd = await loginAs(config.riderUser, config.riderPass);
  const menus = await api(rd.access_token, 'GET', '/api/v1/sys/menus/sidebar');
  const titles = collectTitles(menus.json?.data || []);
  const banned = ['骑手管理', '订单明细', '结算周期', '站点管理', '薪资方案', '骑手薪资'];
  const hit = banned.filter((b) => titles.includes(b));
  if (hit.length) {
    throw new Error(`骑手 sidebar API 不应含插件菜单：${hit.join('、')}`);
  }
  await injectAndOpen(page, rd.access_token, rd.session_uuid || rd.user?.uuid || null, '/analytics');
  // 仅看当前 aside 可见/折叠文案，避免其它 tab keep-alive
  const aside = await page.evaluate(() => document.querySelector('aside')?.textContent || '');
  const text = `${aside}\n${await sidebarText(page)}`;
  // 骑手无插件菜单时，侧栏 API 已证明；DOM 若仍见插件名则再红
  if (banned.some((b) => aside.includes(b))) {
    throw new Error(`骑手登管理端 aside 出现插件菜单：${banned.filter((b) => aside.includes(b)).join('、')}`);
  }
  await helpers.shot(page, 'rbac-sidebar-rider-on-admin', { fullPage: false, optional: true });
}
