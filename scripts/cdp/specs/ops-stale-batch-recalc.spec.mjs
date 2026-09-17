/** CDP: ops-stale-batch-recalc — 本站本月批量重算；无方案骑手不得纯绿「完成」 */
import {
  FIX_JOB_NO,
  PARTIAL_FAIL_COPY,
  assertNotGreenCompleteAlone,
  assertPartialFailVisible,
} from '../cycle1-lib.mjs';

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

  if (await btn.isDisabled()) {
    throw new Error(
      'stale-batch-recalc 按钮禁用（无 stale）。请先 seed ≥2 名骑手奖惩触发 mark_stale。禁止 CDP_ALLOW_EMPTY_STALE 换绿。',
    );
  }

  await btn.click();
  const dialog = page.getByRole('alertdialog').or(
    page.locator('[data-slot="alert-dialog-content"]'),
  );
  try {
    await dialog.first().waitFor({ state: 'visible', timeout: 15000 });
  } catch (err) {
    throw new Error(
      '等待 Vben 确认框超时（alertdialog / [data-slot=alert-dialog-content]）。' +
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
  await helpers.shot(page, 'cdp-ops-stale-batch-recalc-confirm', {
    fullPage: false,
    timeout: 10_000,
  });

  await dialog.first().getByRole('button', { name: /^确\s*认$/ }).click();

  const jobBox = page.getByTestId('dashboard-batch-job');
  await jobBox.waitFor({ state: 'visible', timeout: 30000 });
  const failed = page.getByTestId('dashboard-batch-failed');
  try {
    await failed.waitFor({ state: 'visible', timeout: 180000 });
  } catch {
    const jobText = await jobBox.innerText();
    throw new Error(
      `夹具含 ${FIX_JOB_NO} 时批量重算不得纯绿「完成」：${jobText.slice(0, 300)}`,
    );
  }
  const failText = await failed.innerText();
  assertNotGreenCompleteAlone(failText);
  assertPartialFailVisible(failText);
  if (!PARTIAL_FAIL_COPY.test(failText) && !/失败/.test(failText)) {
    throw new Error(`dashboard-batch-failed 未见部分失败/失败人数：${failText}`);
  }

  const gotoCalc = page.getByTestId('dashboard-batch-goto-calc').first();
  await gotoCalc.waitFor({ state: 'visible', timeout: 15000 });
  await gotoCalc.click();
  await page.waitForURL(/\/rider-salary\/period\/\d+\/calculate/, { timeout: 30000 });
  const calcFail = page.getByTestId('period-calc-failed');
  await calcFail.waitFor({ state: 'visible', timeout: 20000 });
  const calcText = await calcFail.innerText();
  if (!calcText.includes(FIX_JOB_NO) && !/无生效方案/.test(calcText)) {
    throw new Error(`算薪页未见无方案骑手 ${FIX_JOB_NO}：${calcText.slice(0, 200)}`);
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-stale-batch-recalc');
}
