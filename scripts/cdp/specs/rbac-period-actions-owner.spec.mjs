import { RBAC, api, injectAndOpen, isDenied, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-period-actions-owner';

export async function run({ page, helpers }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  await injectAndOpen(page, ow.access_token, ow.user?.uuid ?? null, '/rider-salary/period');
  const body = await page.locator('body').innerText();
  if (body.includes('反冲补发')) {
    throw new Error('负责人周期行出现反冲按钮');
  }
  const periods = await api(ow.access_token, 'GET', '/api/v1/rider-salary/periods?page=1&size=10');
  const row = (periods.json?.data?.items || []).find((p) => p.rider_id === 0) || periods.json?.data?.items?.[0];
  if (row?.id) {
    const rev = await api(ow.access_token, 'POST', `/api/v1/rider-salary/periods/${row.id}/reverse`, {
      reason: 'CDP 反冲探测',
    });
    if (!isDenied(rev)) throw new Error('负责人反冲 API 未 403');
  }
  await helpers.shot(page, 'rbac-period-actions-owner');
}
