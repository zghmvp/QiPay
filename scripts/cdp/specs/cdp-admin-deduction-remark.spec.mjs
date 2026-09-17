/** CDP: cdp-admin-deduction-remark — 代扣空备注「无说明」 */
import { EMPTY_REMARK_COPY, pickPayrollWithMoney, siteMonth } from '../cycle2-lib.mjs';

export const name = 'cdp-admin-deduction-remark';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId } = siteMonth();
  const row = await pickPayrollWithMoney({ apiUrl: config.apiUrl, token, siteId });

  await page.goto(`${config.adminUrl}/rider-salary/payroll/${row.id}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const layers = page.getByTestId('payroll-layers');
  try {
    await layers.waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error('未见 payroll-layers，无法断言代扣备注');
  }

  const remarks = page.getByTestId('payroll-deduction-remark');
  const remarkCount = await remarks.count();
  const layersText = await layers.innerText();
  if (remarkCount === 0) {
    if (!layersText.includes(EMPTY_REMARK_COPY) && !/无代扣/.test(layersText)) {
      throw new Error(
        `空备注须写「${EMPTY_REMARK_COPY}」（payroll-deduction-remark），不得留空白：${layersText.slice(0, 300)}`,
      );
    }
  } else {
    const texts = [];
    for (let i = 0; i < remarkCount; i += 1) {
      texts.push((await remarks.nth(i).innerText()).trim());
    }
    if (texts.some((t) => !t)) {
      throw new Error(`payroll-deduction-remark 不得空白，空则「${EMPTY_REMARK_COPY}」：${texts.join(' | ')}`);
    }
    if (!texts.includes(EMPTY_REMARK_COPY) && !layersText.includes(EMPTY_REMARK_COPY)) {
      throw new Error(`夹具空备注须展示「${EMPTY_REMARK_COPY}」，实际：${texts.join('、')}`);
    }
  }
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-admin-deduction-remark');
}
