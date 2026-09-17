import { RBAC, api, injectAndOpen, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-export-download-owner';

export async function run({ page, helpers }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const sites = await api(ow.access_token, 'GET', '/api/v1/rider-salary/sites/all');
  const siteA = (sites.json?.data || [])[0];
  if (!siteA) throw new Error('负责人无可见站点');
  const ok = await fetch(
    `${process.env.API_URL || 'http://127.0.0.1:8000'}/api/v1/rider-salary/orders/export?site_id=${siteA.id}`,
    { headers: { Authorization: `Bearer ${ow.access_token}` } },
  );
  if (!ok.ok) throw new Error(`本站导出失败 ${ok.status}`);
  const su = await loginAs(process.env.CDP_USER || 'admin', process.env.CDP_PASS || 'admin').catch(() =>
    loginAs('admin', '123456'),
  );
  const allSites = await api(su.access_token, 'GET', '/api/v1/rider-salary/sites/all');
  const siteB = (allSites.json?.data || []).find((s) => s.id !== siteA.id);
  if (siteB) {
    const bad = await fetch(
      `${process.env.API_URL || 'http://127.0.0.1:8000'}/api/v1/rider-salary/orders/export?site_id=${siteB.id}`,
      { headers: { Authorization: `Bearer ${ow.access_token}` } },
    );
    if (bad.ok) throw new Error('改 query 为站 B 仍导出成功');
  }
  await injectAndOpen(page, ow.access_token, ow.user?.uuid ?? null, '/rider-salary/order');
  await helpers.shot(page, 'rbac-export-download-owner');
}
