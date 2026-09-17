/** CDP: ops-stale-batch-recalc — 本站本月批量重算（站点负责人） */
export const name = 'ops-stale-batch-recalc';

export async function run({ page, helpers, config }) {
  const user = config.siteOwnerUser;
  const pass = config.siteOwnerPass;
  const login = await helpers.swaggerLogin(user, pass);
  await helpers.injectAdmin(page, login.access_token, login.user?.uuid ?? null);

  const siteId = process.env.CDP_SITE_ID || '';
  const month = process.env.CDP_MONTH || '2026-09';
  const qs = new URLSearchParams({ month });
  if (siteId) qs.set('site_id', siteId);

  await page.goto(`${config.adminUrl}/rider-salary/dashboard?${qs}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });

  const btn = page.getByTestId('stale-batch-recalc');
  await btn.waitFor({ state: 'visible', timeout: 30000 });
  await helpers.shot(page, 'cdp-ops-stale-batch-recalc-button');

  // 无 stale 时按钮 disabled — 仍算入口存在；有 stale 则点开确认框断言文案
  const disabled = await btn.isDisabled();
  if (!disabled) {
    await btn.click();
    const dialog = page.locator('.ant-modal, [role="dialog"]').last();
    await dialog.waitFor({ state: 'visible', timeout: 15000 });
    const text = await dialog.innerText();
    if (!text.includes('批量重算') && !text.includes('站点')) {
      throw new Error(`确认框文案不符合预期：${text}`);
    }
    // 取消，确保可取消
    const cancel = dialog.getByRole('button', { name: /取消|关闭/ }).first();
    if ((await cancel.count()) > 0) await cancel.click();
    await helpers.shot(page, 'cdp-ops-stale-batch-recalc-confirm');
  } else {
    console.warn('WARN: 本站本月无 stale，按钮禁用；入口与权限已验收');
  }
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
}
