import { SA_MENUS, api, assertHas, injectAndOpen, isDenied, loginAs, sidebarText } from '../rbac-helpers.mjs';

export const name = 'rbac-sidebar-salary-admin';

export async function run({ page, helpers, config }) {
  const sa = await loginAs(config.salaryAdminUser, config.salaryAdminPass);
  await injectAndOpen(page, sa.access_token, sa.user?.uuid ?? null, '/rider-salary/period');
  const text = await sidebarText(page);
  assertHas(text, SA_MENUS, '薪资管理员');
  const periods = await api(sa.access_token, 'GET', '/api/v1/rider-salary/periods?page=1&size=5');
  if (periods.status >= 400) throw new Error(`SA 周期列表失败 ${periods.status} ${periods.msg}`);
  await injectAndOpen(page, sa.access_token, sa.user?.uuid ?? null, '/rider-salary/plan');
  const planText = await page.locator('body').innerText();
  if (planText.includes('回退方案') && !planText.includes('无权限')) {
    throw new Error('薪资管理员方案页出现回退');
  }
  const vers = await api(sa.access_token, 'GET', '/api/v1/rider-salary/plan-versions?page=1&size=5');
  const ver = vers.json?.data?.items?.[0];
  if (ver?.id) {
    const rb = await api(sa.access_token, 'POST', `/api/v1/rider-salary/plan-versions/${ver.id}/rollback`, {
      reason: 'CDP SA 回退探测',
    });
    if (!isDenied(rb)) throw new Error(`SA rollback 未拒绝：${rb.status} ${rb.msg}`);
  }
  await helpers.shot(page, 'rbac-sidebar-salary-admin');
}
