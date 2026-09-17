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

  // Vben confirm → reka AlertDialog（role=alertdialog / data-slot），非 Ant Modal
  const dialog = page.getByRole('alertdialog').or(
    page.locator('[data-slot="alert-dialog-content"]'),
  );
  try {
    await dialog.first().waitFor({ state: 'visible', timeout: 15000 });
  } catch (err) {
    throw new Error(
      '等待 Vben 确认框超时（alertdialog / [data-slot=alert-dialog-content]）。' +
        '若仍在等 .ant-modal / [role=dialog]：产品为 Vben confirm，不是 Ant Modal。' +
        ` 原始错误：${err.message}`,
    );
  }

  const text = await dialog.first().innerText();
  const hasBatch = text.includes('批量重算');
  const hasSiteOrPeriod =
    text.includes('站点') || text.includes('周期') || text.includes('骑手');
  if (!hasBatch || !hasSiteOrPeriod) {
    throw new Error(
      `确认框文案不符合预期（须含「批量重算」且含站点/周期/骑手语义）：${text}`,
    );
  }

  // 开框态 viewport 证据（cancel 前）；勿在 overlay 关闭后 fullPage
  await helpers.shot(page, 'cdp-ops-stale-batch-recalc-confirm', {
    fullPage: false,
    timeout: 10_000,
  });

  // Vben Alert 按钮 accessible name 常为「取 消」（字间空白）；勿用 /^取消$/
  await dialog.first().getByRole('button', { name: /^取\s*消$/ }).click();
  await dialog.first().waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});

  // 取消后辅证：viewport + optional（失败 WARN，不 FAIL）
  await helpers.shot(page, 'cdp-ops-stale-batch-recalc-after-cancel', {
    fullPage: false,
    timeout: 10_000,
    optional: true,
  });

  const bodyAfter = await page.locator('body').innerText();
  if (bodyAfter.includes('已提交批量重算')) {
    throw new Error('点击取消后出现提交成功态——疑似误点确认');
  }
  helpers.assertNoPaymentTaxCopy(bodyAfter);
}
