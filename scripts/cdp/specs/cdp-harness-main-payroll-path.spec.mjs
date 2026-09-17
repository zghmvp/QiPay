/** CDP: cdp-harness-main-payroll-path — 主链路 smoke（断言中文/金额，截图仅附件） */
export const name = 'cdp-harness-main-payroll-path';

const ROUTES = [
  ['dashboard', '/rider-salary/dashboard'],
  ['plan', '/rider-salary/plan'],
  ['order', '/rider-salary/order'],
  ['period', '/rider-salary/period'],
  ['calendar', '/rider-salary/calendar'],
];

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  for (const [key, route] of ROUTES) {
    await page.goto(`${config.adminUrl}${route}`, {
      waitUntil: 'networkidle',
      timeout: 60000,
    });
    const body = await page.locator('body').innerText();
    helpers.assertNoPaymentTaxCopy(body);
    // 至少出现中文插件域文案
    if (!/骑手|薪资|方案|订单|周期|工作台|日历/.test(body)) {
      throw new Error(`主链路页缺少中文业务文案：${route}`);
    }
    await helpers.shot(page, `cdp-harness-main-payroll-path-${key}`);
  }
}
