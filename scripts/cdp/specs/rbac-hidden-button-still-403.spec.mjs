import { RBAC, api, isDenied, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-hidden-button-still-403';

export async function run({ helpers, page }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const sites = await api(ow.access_token, 'GET', '/api/v1/rider-salary/sites/all');
  const siteA = (sites.json?.data || [])[0];
  const suUser = process.env.CDP_USER || 'admin';
  const suPass = process.env.CDP_PASS || 'admin';
  let su;
  try {
    su = await loginAs(suUser, suPass);
  } catch {
    su = await loginAs('admin', '123456');
  }
  const suPeriods = await api(su.access_token, 'GET', '/api/v1/rider-salary/periods?page=1&size=50');
  const siteB = (suPeriods.json?.data?.items || []).find((p) => siteA && p.site_id !== siteA.id);
  if (!siteB) throw new Error('无外站周期，无法测藏按钮仍 403');
  const lock = await api(ow.access_token, 'POST', `/api/v1/rider-salary/periods/${siteB.id}/lock`, {
    reason: 'CDP 藏按钮锁账',
  });
  if (!isDenied(lock)) throw new Error(`直打外站 lock 未 403：${lock.status} ${lock.msg}`);
  await helpers.shot(page, 'rbac-hidden-button-still-403');
}
