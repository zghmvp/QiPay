/** CDP: ops-rider-profile-to-payroll — 档案「本骑手薪资结果」→ /payroll?rider_id= */
import { FIX_JOB_NO, resolveFixRiderId, siteMonth } from '../cycle1-lib.mjs';
import { GOTO_CALC_COPY, PROFILE_PAYROLL_CTA, TRIAL_AS_PAYROLL_COPY } from '../cycle2-lib.mjs';

export const name = 'ops-rider-profile-to-payroll';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId } = siteMonth();
  const riderId = await resolveFixRiderId(config.apiUrl, token, siteId);

  await page.goto(`${config.adminUrl}/rider-salary/rider/${riderId}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());

  const cta = page.getByTestId('rider-goto-payroll');
  try {
    await cta.waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error('骑手档案须有 rider-goto-payroll（「本骑手薪资结果」），不新菜单不新权限码');
  }
  const ctaText = await cta.innerText();
  if (!PROFILE_PAYROLL_CTA.test(ctaText)) {
    throw new Error(`rider-goto-payroll 文案须为「本骑手薪资结果」：${ctaText}`);
  }
  await cta.click();
  await page.waitForURL(/\/rider-salary\/payroll/, { timeout: 30000 });
  const url = page.url();
  if (!new RegExp(`[?&]rider_id=${riderId}(?:&|$)`).test(url)) {
    throw new Error(`须落到 /payroll?rider_id=${riderId}，实际 ${url}`);
  }
  const picker = page.getByTestId('payroll-period-picker');
  await picker.waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
  const grid = page.getByTestId('payroll-list-grid');
  if (await grid.isVisible().catch(() => false)) {
    const text = await grid.innerText();
    if (text && !text.includes(FIX_JOB_NO) && /D\d|FIX_/.test(text)) {
      throw new Error(`列表应只出该骑手，出现了他人工号：${text.slice(0, 200)}`);
    }
  }

  await page.goto(`${config.adminUrl}/rider-salary/rider/${riderId}?tab=binding`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const bindCta = page.getByTestId('rider-binding-goto-calculate');
  try {
    await bindCta.waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error('绑定区须有 rider-binding-goto-calculate（去周期算薪页）');
  }
  const bindCtaText = await bindCta.innerText();
  if (!GOTO_CALC_COPY.test(bindCtaText)) {
    throw new Error(`rider-binding-goto-calculate 文案须指向算薪页：${bindCtaText}`);
  }
  const bind = await page.locator('body').innerText();
  if (TRIAL_AS_PAYROLL_COPY.test(bind) && !GOTO_CALC_COPY.test(bind)) {
    throw new Error('绑定保存文案不得再把「试算」当成出账；须改为「去周期算薪页」');
  }
  if (!GOTO_CALC_COPY.test(bind) && /试算/.test(bind) && /保存后/.test(bind)) {
    throw new Error('绑定区仍写试算即出账');
  }
  await helpers.shot(page, 'cdp-ops-rider-profile-to-payroll');
}
