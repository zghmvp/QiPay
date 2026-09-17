/** CDP: trial-binding-segments — 分段试算须出数字；无数字 = FAIL */
import { clickStartTrial, fillTrialTargets, waitTrialNumbers } from '../cycle2-lib.mjs';
import { FIX_JOB_NO, siteMonth } from '../cycle1-lib.mjs';

export const name = 'trial-binding-segments';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteCode, month } = siteMonth();

  await page.goto(`${config.adminUrl}/rider-salary/plan`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());

  const trialOnList = page.getByRole('button', { name: /^试算$/ }).first();
  if ((await trialOnList.count()) === 0) {
    throw new Error('方案列表无试算入口，请先灌 FIX_C17 演示种子');
  }
  await trialOnList.click();
  const mode = page.getByTestId('trial-mode');
  await mode.waitFor({ state: 'visible', timeout: 30000 });
  await page.getByText('按绑定分段试算').click();

  await fillTrialTargets(page, {
    siteCode,
    jobNo: FIX_JOB_NO,
    start: `${month}-01`,
    end: `${month}-30`,
  });
  await helpers.shot(page, 'cdp-trial-binding-segments-panel');
  await clickStartTrial(page);

  const { valid, plan } = await waitTrialNumbers(page);
  if (!(Number.isFinite(valid) && Number.isFinite(plan))) {
    throw new Error('trial-binding-segments 无试算结果数字 = FAIL（禁止 WARN 过）');
  }
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-trial-binding-segments-diverge');
}
