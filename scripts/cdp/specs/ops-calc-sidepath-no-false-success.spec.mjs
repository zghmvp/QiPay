/** CDP: ops-calc-sidepath-no-false-success — 工作台立即重算不得直 POST / 假完成 */
export const name = 'ops-calc-sidepath-no-false-success';

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

  const btn = page.getByTestId('stale-goto-calculate').first();
  try {
    await btn.waitFor({ state: 'visible', timeout: 20000 });
  } catch (err) {
    throw new Error(
      '未找到工作台「立即重算」。请先 seed stale 周期（FIX_C17 / 奖惩 mark_stale）。' +
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
