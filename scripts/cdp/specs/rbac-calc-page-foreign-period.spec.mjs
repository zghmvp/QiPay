import { RBAC, api, injectAndOpen, isDenied, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-calc-page-foreign-period';

export async function run({ page, helpers }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const sites = await api(ow.access_token, 'GET', '/api/v1/rider-salary/sites/all');
  const siteA = (sites.json?.data || [])[0];
  const su = await loginAs(process.env.CDP_USER || 'admin', process.env.CDP_PASS || 'admin').catch(() =>
    loginAs('admin', '123456'),
  );
  const suPeriods = await api(su.access_token, 'GET', '/api/v1/rider-salary/periods?page=1&size=50');
  const foreign = (suPeriods.json?.data?.items || []).find((p) => siteA && p.site_id !== siteA.id);
  if (!foreign) throw new Error('无外站周期');
  const detail = await api(ow.access_token, 'GET', `/api/v1/rider-salary/periods/${foreign.id}`);
  if (!isDenied(detail)) throw new Error(`外站周期 API 未拒绝 ${detail.status}`);
  await injectAndOpen(page, ow.access_token, ow.user?.uuid ?? null, `/rider-salary/period/${foreign.id}/calculate`);
  const body = await page.locator('body').innerText();
  if (/开始算薪|预检通过/.test(body) && !/无权|不存在|403|404/.test(body)) {
    throw new Error('外站算薪页露出可操作体');
  }
  await helpers.shot(page, 'rbac-calc-page-foreign-period');
}
