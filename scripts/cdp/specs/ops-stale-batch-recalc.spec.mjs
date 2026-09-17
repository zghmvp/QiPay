/** CDP: ops-stale-batch-recalc — 本站本月批量重算（站点负责人，非超管） */
export const name = 'ops-stale-batch-recalc';

export async function run({ page, helpers, config }) {
  const user = config.siteOwnerUser;
  const pass = config.siteOwnerPass;
  if (user === 'admin' || user === config.username) {
    console.warn(
      'WARN: CDP_SITE_OWNER 指向超管/当前管理员——非正式 Must #5 口径；正式验收须 site_owner_d2',
    );
  }

  let login;
  try {
    login = await helpers.swaggerLogin(user, pass);
  } catch (err) {
    throw new Error(
      `站点负责人登录失败（${user}）。请先运行 node scripts/cdp/seed-xiaoxiang-fixtures.mjs；` +
        `正式路径禁止改用 admin。原始错误：${err.message}`,
    );
  }
  await helpers.injectAdmin(page, login.access_token, login.user?.uuid ?? null);

  const siteId = process.env.CDP_SITE_ID || '13';
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

  const disabled = await btn.isDisabled();
  const allowEmpty = process.env.CDP_ALLOW_EMPTY_STALE === '1';
  if (disabled) {
    if (allowEmpty) {
      console.warn('WARN: 本站本月无 stale，按钮禁用（CDP_ALLOW_EMPTY_STALE=1 逃生阀）');
      helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
      return;
    }
    throw new Error(
      'stale-batch-recalc 按钮禁用（无 stale）。请先 seed ≥2 名骑手奖惩触发 mark_stale；' +
        '排障临时可设 CDP_ALLOW_EMPTY_STALE=1',
    );
  }

  await btn.click();
  const dialog = page.locator('.ant-modal, [role="dialog"]').last();
  await dialog.waitFor({ state: 'visible', timeout: 15000 });
  const text = await dialog.innerText();
  if (!text.includes('批量重算') && !text.includes('站点')) {
    throw new Error(`确认框文案不符合预期：${text}`);
  }
  const cancel = dialog.getByRole('button', { name: /取消|关闭/ }).first();
  if ((await cancel.count()) > 0) await cancel.click();
  await helpers.shot(page, 'cdp-ops-stale-batch-recalc-confirm');
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
}
