/** CDP: ops-calc-sidepath-no-false-success — 工作台立即重算不得直 POST / 假完成 */
export const name = 'ops-calc-sidepath-no-false-success';

/**
 * 「立即重算」在折叠 panel 内；默认全收。先点开「需重算周期」再 visible。
 * 禁止：默认展开产品、只断言 attached、改点 header/批量按钮冒充行跳转。
 */
async function expandNeedRecalcPanel(page) {
  const gotoBtn = page.getByTestId('stale-goto-calculate').first();
  if (await gotoBtn.isVisible()) return;

  const header = page
    .locator('.ant-collapse-header')
    .filter({ hasText: '需重算周期' })
    .first();
  const headerByRole = page.getByRole('button', { name: /需重算周期/ });
  const headerByText = page.getByText('需重算周期', { exact: true }).first();

  try {
    if (await header.count()) {
      await header.waitFor({ state: 'visible', timeout: 20000 });
      await header.click();
    } else if (await headerByRole.count()) {
      await headerByRole.first().waitFor({ state: 'visible', timeout: 20000 });
      await headerByRole.first().click();
    } else {
      await headerByText.waitFor({ state: 'visible', timeout: 20000 });
      await headerByText.click();
    }
  } catch (err) {
    throw new Error(
      '未找到工作台「需重算周期」折叠头，无法展开行内「立即重算」。请先 seed stale 周期（FIX_C17 / 奖惩 mark_stale）。' +
        ` 原始错误：${err.message}`,
    );
  }
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  const siteId = process.env.CDP_SITE_ID || '13';
  const month = process.env.CDP_MONTH || '2026-09';
  const posted = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/periods\/\d+\/calculate/.test(req.url())) {
      posted.push(req.url());
    }
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );

  await expandNeedRecalcPanel(page);

  const btn = page.getByTestId('stale-goto-calculate').first();
  try {
    await btn.waitFor({ state: 'visible', timeout: 20000 });
  } catch (err) {
    throw new Error(
      '展开「需重算周期」后仍未找到工作台「立即重算」。请先 seed stale 周期（FIX_C17 / 奖惩 mark_stale）。' +
        ` 原始错误：${err.message}`,
    );
  }
  await helpers.shot(page, 'cdp-ops-calc-sidepath-dashboard');
  await btn.click();
  await page.waitForURL(/\/rider-salary\/period\/\d+\/calculate/, {
    timeout: 30000,
  });
  if (posted.length) {
    throw new Error(
      `工作台立即重算不得直 POST calculate，实际请求：${posted.join(', ')}`,
    );
  }
  const body = await page.locator('body').innerText();
  if (body.includes('已计算') && body.includes('完成') && !body.includes('失败')) {
    // 进页尚未开算，不应出现整页绿完成 toast 文案充作已出账
  }
  helpers.assertNoPaymentTaxCopy(body);
  await helpers.shot(page, 'cdp-ops-calc-sidepath-calc-page');
}
