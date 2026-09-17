/** CDP: ops-abnormal-attention-parity — 异常同源回归 */
export const name = 'ops-abnormal-attention-parity';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  await page.goto(`${config.adminUrl}/rider-salary/dashboard`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const body = await page.locator('body').innerText();
  helpers.assertNoPaymentTaxCopy(body);
  // 工作台应能打开；异常待办模块标题若出现则截图
  if (body.includes('异常')) {
    await helpers.shot(page, 'cdp-ops-abnormal-attention-parity');
  } else {
    await helpers.shot(page, 'cdp-ops-abnormal-attention-parity-empty');
  }
}
